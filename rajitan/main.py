import asyncio
import signal
import sys
import os
import psutil
import uvicorn
from typing import Optional
from pathlib import Path
from rajitan.bot.client import RajitanBot
from rajitan.bot.commands import setup as setup_commands
from rajitan.storage.sqlite_client import SQLiteClient
from rajitan.storage.redis_client import RedisClient
from rajitan.api.openai_client import OpenAIClient
from rajitan.character.manager import CharacterManager
from rajitan.conversation.tracker import ConversationTracker
from rajitan.conversation.analyzer import ConversationAnalyzer
from rajitan.conversation.summarizer import ConversationSummarizer
from rajitan.features.quiz.generator import QuizGenerator
from rajitan.features.quiz.runner import QuizRunner
from rajitan.scheduler.enhanced_manager import EnhancedScheduleManager
from rajitan.scheduler.trigger_manager import TriggerManager
from rajitan.features.music.recommender import MusicRecommender
from rajitan.api.youtube_client import YouTubeClient
from rajitan.api.spotify_client import SpotifyClient
from rajitan.storage.levemagi_client import LeveMagiClient
from rajitan.api.google_calendar_client import GoogleCalendarClient
from rajitan.api.instagram_client import InstagramClient
from rajitan.api.canva_client import CanvaClient
from rajitan.web.server import create_app, app_state
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("main")
config = get_config()


class ProcessManager:
    """Manages process lifecycle and prevents duplicate instances"""
    
    def __init__(self, pid_file: str = "rajitan.pid"):
        self.pid_file = Path(pid_file)
        self.pid = os.getpid()
    
    def is_already_running(self) -> bool:
        """Check if another instance is already running"""
        try:
            if not self.pid_file.exists():
                return False
            
            # Read PID from file
            with open(self.pid_file, 'r') as f:
                stored_pid = int(f.read().strip())
            
            # Check if process is actually running
            if psutil.pid_exists(stored_pid):
                # Check if it's actually our application
                try:
                    process = psutil.Process(stored_pid)
                    if "python" in process.name().lower() and "rajitan" in " ".join(process.cmdline()).lower():
                        logger.warning(f"Rajitan is already running with PID {stored_pid}")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # PID file exists but process is dead, clean it up
            self.pid_file.unlink(missing_ok=True)
            return False
            
        except Exception as e:
            logger.error(f"Error checking if already running: {e}")
            return False
    
    def create_pid_file(self) -> bool:
        """Create PID file to mark this instance as running"""
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(self.pid))
            logger.info(f"Created PID file: {self.pid_file} (PID: {self.pid})")
            return True
        except Exception as e:
            logger.error(f"Failed to create PID file: {e}")
            return False
    
    def remove_pid_file(self):
        """Remove PID file"""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                logger.info(f"Removed PID file: {self.pid_file}")
        except Exception as e:
            logger.error(f"Failed to remove PID file: {e}")


class RajitanApplication:
    """Main application class for Rajitan Discord Bot"""

    def __init__(self):
        self.bot: Optional[RajitanBot] = None
        self.db_client: Optional[SQLiteClient] = None
        self.redis_client: Optional[RedisClient] = None
        self.openai_client: Optional[OpenAIClient] = None
        self.character_manager: Optional[CharacterManager] = None
        self.conversation_tracker: Optional[ConversationTracker] = None
        self.conversation_analyzer: Optional[ConversationAnalyzer] = None
        self.conversation_summarizer: Optional[ConversationSummarizer] = None
        self.quiz_generator: Optional[QuizGenerator] = None
        self.quiz_runner: Optional[QuizRunner] = None
        self.enhanced_schedule_manager: Optional[EnhancedScheduleManager] = None
        self.trigger_manager: Optional[TriggerManager] = None
        self.music_recommender: Optional[MusicRecommender] = None
        self.youtube_client: Optional[YouTubeClient] = None
        self.spotify_client: Optional[SpotifyClient] = None
        self.levemagi_client: Optional[LeveMagiClient] = None
        self.google_calendar_client: Optional[GoogleCalendarClient] = None
        self.instagram_client: Optional[InstagramClient] = None
        self.canva_client: Optional[CanvaClient] = None
        self.fastapi_app = None
        self.process_manager = ProcessManager()
        self.running = False
    
    async def initialize(self):
        """Initialize all services"""
        try:
            # Check for duplicate instances
            if self.process_manager.is_already_running():
                logger.error("Rajitan is already running. Please stop the existing instance first.")
                sys.exit(1)
            
            # Create PID file
            if not self.process_manager.create_pid_file():
                logger.error("Failed to create PID file. Cannot start application.")
                sys.exit(1)
            
            logger.info("Initializing Rajitan application...")
            
            # Initialize database clients
            logger.info("Initializing database clients...")
            self.db_client = SQLiteClient()
            await self.db_client.initialize()
            await self.db_client.seed_preset_personas()

            self.redis_client = RedisClient()
            await self.redis_client.initialize()
            
            # Initialize API clients
            logger.info("Initializing API clients...")
            self.openai_client = OpenAIClient()
            
            # Initialize core services
            logger.info("Initializing core services...")
            self.character_manager = CharacterManager(self.db_client, self.openai_client)
            
            self.conversation_analyzer = ConversationAnalyzer(self.openai_client)
            
            self.conversation_tracker = ConversationTracker(
                self.redis_client, 
                self.conversation_analyzer
            )
            
            self.conversation_summarizer = ConversationSummarizer(
                self.openai_client,
                self.character_manager
            )
            
            # Initialize feature services
            logger.info("Initializing feature services...")
            self.quiz_generator = QuizGenerator(self.openai_client, self.character_manager)
            self.quiz_runner = QuizRunner(self.redis_client)

            # Initialize music recommendation services
            logger.info("Initializing music services...")
            self.youtube_client = YouTubeClient()
            self.spotify_client = SpotifyClient()
            self.music_recommender = MusicRecommender(
                self.openai_client,
                self.character_manager,
                self.youtube_client,
                self.spotify_client
            )
            
            # Initialize LeveMagi client
            logger.info("Initializing LeveMagi client...")
            self.levemagi_client = LeveMagiClient(self.db_client.db_path)

            # Initialize Google Calendar client
            if config.google_client_id and config.google_client_secret:
                logger.info("Initializing Google Calendar client...")
                self.google_calendar_client = GoogleCalendarClient(self.db_client.db_path)

            # Initialize Instagram client
            logger.info("Initializing Instagram client...")
            self.instagram_client = InstagramClient(self.db_client.db_path)

            # Initialize Canva client (optional)
            if config.canva_client_id and config.canva_client_secret:
                logger.info("Initializing Canva client...")
                self.canva_client = CanvaClient(self.db_client.db_path)

            # Initialize Discord bot first
            logger.info("Initializing Discord bot...")
            self.bot = RajitanBot()
            
            # Initialize scheduler with bot instance
            logger.info("Initializing scheduler...")
            self.enhanced_schedule_manager = EnhancedScheduleManager(self.db_client, self.bot)
            self.trigger_manager = TriggerManager(self.bot)
            
            # Initialize agent system
            logger.info("Initializing agent system...")
            from rajitan.agent.llm.openai_provider import OpenAIProvider
            from rajitan.agent.tools.base import ToolRegistry
            from rajitan.agent.memory.manager import MemoryManager
            from rajitan.agent.orchestrator import AgentOrchestrator

            # Multi-model management
            from rajitan.agent.llm.model_manager import ModelManager, ModelConfig

            model_manager = ModelManager(self.db_client)

            # Register available models (skips if API key not set)
            model_manager.register(ModelConfig(
                "deepseek-chat", "DeepSeek v3",
                "https://api.deepseek.com", "DEEPSEEK_API_KEY",
                supports_thinking=True,
            ))
            model_manager.register(ModelConfig(
                "openai/gpt-oss-20b", "Groq GPT-OSS 20B",
                "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "openai/gpt-oss-120b", "Groq GPT-OSS 120B",
                "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "gemini-2.5-flash", "Gemini 2.5 Flash",
                "https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_AI_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "gpt-5", "GPT-5",
                "https://api.openai.com/v1", "OPENAI_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "claude-sonnet-4-5", "Claude Sonnet 4.5",
                "https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "gemini-3-flash-preview", "Gemini 3 Flash",
                "https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_AI_API_KEY",
                supports_thinking=False,
            ))
            model_manager.register(ModelConfig(
                "gemini-3-pro-preview", "Gemini 3 Pro",
                "https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_AI_API_KEY",
                supports_thinking=False,
            ))

            # Default provider (for ResponseGate etc.)
            if model_manager.list_available():
                llm_provider = model_manager.get_default()
                default_cfg = model_manager.get_config(model_manager.get_default_model_id())
                logger.info(f"Agent LLM default: {default_cfg.display_name}")
            else:
                llm_provider = OpenAIProvider(self.openai_client.client, self.openai_client.model)
                model_manager = None
                logger.info("Agent LLM: OpenAI (no model keys configured)")

            available = model_manager.list_available() if model_manager else []
            if available:
                logger.info(f"Available models: {[m.display_name for m in available]}")
            tool_registry = ToolRegistry()

            # Initialize memory system
            memory_manager = MemoryManager(self.redis_client, self.db_client)
            logger.info("Memory system initialized (3-tier)")

            # Load workflow definition from YAML
            from rajitan.agent.workflow.loader import WorkflowLoader
            workflow_loader = WorkflowLoader(db_client=self.db_client)
            wf = workflow_loader.base_config
            logger.info(f"Workflow loaded: {wf.name} (v{wf.version})")

            # --- YAML-driven tool system ---
            from rajitan.agent.tools.service_registry import ServiceRegistry
            from rajitan.agent.tools.definition import ToolDefinitionLoader
            from rajitan.agent.tools.executor import GenericExecutor

            service_registry = ServiceRegistry()
            service_registry.register("bot", self.bot)
            service_registry.register("conversation_summarizer", self.conversation_summarizer)
            service_registry.register("conversation_tracker", self.conversation_tracker)
            service_registry.register("conversation_analyzer", self.conversation_analyzer)
            service_registry.register("quiz_generator", self.quiz_generator)
            service_registry.register("quiz_runner", self.quiz_runner)
            service_registry.register("schedule_manager", self.enhanced_schedule_manager)
            service_registry.register("levemagi_client", self.levemagi_client)
            service_registry.register("character_manager", self.character_manager)
            service_registry.register("memory_manager", memory_manager)
            service_registry.register("music_recommender", self.music_recommender)
            service_registry.register("instagram_client", self.instagram_client)
            if self.canva_client:
                service_registry.register("canva_client", self.canva_client)
            if config.google_ai_api_key:
                service_registry.register("google_ai_api_key", config.google_ai_api_key)
            from rajitan.agent.workflow.editor import WorkflowEditor
            workflow_editor = WorkflowEditor(llm_provider, workflow_loader)
            service_registry.register("workflow_editor", workflow_editor)

            executor = GenericExecutor(service_registry)
            tool_registry.set_executor(executor)

            # Load all tool definitions from YAML (tools/ directory)
            tool_def_loader = ToolDefinitionLoader()
            yaml_tool_defs = tool_def_loader.load_all()

            # Skip tools whose required services are not available
            for tool_def in yaml_tool_defs.values():
                services_needed = tool_def.execution_config.get("services", [])
                missing = [s for s in services_needed if not service_registry.has(s)]
                if missing:
                    logger.warning(
                        f"Skipping tool '{tool_def.name}': missing services {missing}"
                    )
                    continue
                tool_registry.register_yaml(tool_def)

            logger.info(f"All tools registered via YAML ({len(tool_registry)} total)")

            # Apply workflow tool overrides (max_calls, disabled)
            tool_registry.apply_workflow_config(wf.tools)

            # Response quality gate (LLM-based YES/NO check before sending)
            from rajitan.agent.response_gate import ResponseGate
            response_gate = ResponseGate(llm_provider, gate_config=wf.response_gate)

            # Execution log collector for WebUI visualization
            from rajitan.agent.workflow.execution_log import ExecutionLogCollector
            execution_log = ExecutionLogCollector()

            # Initialize team coordinator (optional, controlled by workflow config)
            team_coordinator = None
            if wf.team.enabled:
                from rajitan.agent.team.coordinator import TeamCoordinator
                team_coordinator = TeamCoordinator(
                    llm_provider=llm_provider,
                    tool_registry=tool_registry,
                    team_config=wf.team,
                    character_manager=self.character_manager,
                    execution_log=execution_log,
                )
                logger.info(f"Team mode enabled (max {wf.team.max_sub_agents} sub-agents)")

            # Initialize Agent Teams coordinator (role-based collaboration)
            agent_teams_coordinator = None
            if wf.agent_teams.enabled:
                from rajitan.agent.teams.team_coordinator import AgentTeamCoordinator
                agent_teams_coordinator = AgentTeamCoordinator(
                    llm_provider=llm_provider,
                    tool_registry=tool_registry,
                    config=wf.agent_teams,
                    character_manager=self.character_manager,
                    execution_log=execution_log,
                )
                logger.info(f"Agent Teams enabled (max {wf.agent_teams.max_teammates} teammates)")

            agent_orchestrator = AgentOrchestrator(
                llm_provider=llm_provider,
                tool_registry=tool_registry,
                character_manager=self.character_manager,
                conversation_tracker=self.conversation_tracker,
                memory_manager=memory_manager,
                workflow_loader=workflow_loader,
                execution_log=execution_log,
                team_coordinator=team_coordinator,
                agent_teams_coordinator=agent_teams_coordinator,
                model_manager=model_manager,
            )
            logger.info(f"Agent system initialized with {len(tool_registry)} tools")

            # Inject dependencies into bot
            self.bot.inject_dependencies(
                db_client=self.db_client,
                redis_client=self.redis_client,
                character_manager=self.character_manager,
                conversation_tracker=self.conversation_tracker,
                conversation_summarizer=self.conversation_summarizer,
                quiz_generator=self.quiz_generator,
                quiz_runner=self.quiz_runner,
                enhanced_schedule_manager=self.enhanced_schedule_manager,
                trigger_manager=self.trigger_manager,
                music_recommender=self.music_recommender,
                levemagi_client=self.levemagi_client,
                agent_orchestrator=agent_orchestrator,
                memory_manager=memory_manager,
                response_gate=response_gate,
                model_manager=model_manager,
            )
            
            # Setup commands
            await setup_commands(self.bot)

            # Setup LeveMagi commands
            from rajitan.bot.levemagi_commands import setup as setup_levemagi_commands
            await setup_levemagi_commands(self.bot)

            # Initialize FastAPI server
            if config.api_enabled:
                logger.info("Initializing FastAPI server...")
                self.fastapi_app = create_app()
                app_state["bot"] = self.bot
                app_state["db_client"] = self.db_client
                app_state["redis_client"] = self.redis_client
                app_state["character_manager"] = self.character_manager
                app_state["conversation_tracker"] = self.conversation_tracker
                app_state["conversation_summarizer"] = self.conversation_summarizer
                app_state["enhanced_schedule_manager"] = self.enhanced_schedule_manager
                app_state["levemagi_client"] = self.levemagi_client
                if self.google_calendar_client:
                    app_state["google_calendar_client"] = self.google_calendar_client
                if self.instagram_client:
                    app_state["instagram_client"] = self.instagram_client
                if self.canva_client:
                    app_state["canva_client"] = self.canva_client
                app_state["workflow_loader"] = workflow_loader
                app_state["execution_log"] = execution_log
                app_state["tool_registry"] = tool_registry

            logger.info("Rajitan application initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize application: {e}")
            # Clean up PID file on initialization failure
            self.process_manager.remove_pid_file()
            raise
    
    async def start(self):
        """Start the application"""
        try:
            if self.running:
                logger.warning("Application is already running")
                return

            logger.info("Starting Rajitan application...")

            # Start schedulers and trigger manager
            await self.enhanced_schedule_manager.start()
            await self.trigger_manager.start()

            self.running = True

            # Start Discord bot + FastAPI concurrently
            tasks = [self.bot.start(config.discord_bot_token)]

            if config.api_enabled and self.fastapi_app:
                uvicorn_config = uvicorn.Config(
                    self.fastapi_app,
                    host=config.api_host,
                    port=config.api_port,
                    log_level="info",
                )
                server = uvicorn.Server(uvicorn_config)
                tasks.append(server.serve())
                logger.info(f"Starting API server on {config.api_host}:{config.api_port}")

            await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Failed to start application: {e}")
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Shutdown the application"""
        try:
            if not self.running:
                return
            
            logger.info("Shutting down Rajitan application...")
            self.running = False
            
            # Shutdown services in reverse order
            if self.trigger_manager:
                await self.trigger_manager.stop()

            if self.enhanced_schedule_manager:
                await self.enhanced_schedule_manager.stop()

            # Close API clients
            if self.instagram_client:
                await self.instagram_client.close()
            if self.canva_client:
                await self.canva_client.close()
            if self.google_calendar_client:
                await self.google_calendar_client.close()

            if self.youtube_client:
                await self.youtube_client.close()

            if self.spotify_client:
                await self.spotify_client.close()
            
            if self.bot:
                await self.bot.shutdown()
            
            if self.redis_client:
                await self.redis_client.close()
            
            if self.db_client:
                await self.db_client.close()
            
            # Remove PID file
            self.process_manager.remove_pid_file()
            
            logger.info("Rajitan application shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            # Ensure PID file is removed even on error
            self.process_manager.remove_pid_file()


# Global application instance
app = RajitanApplication()


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    
    # Create shutdown task
    loop = asyncio.get_event_loop()
    loop.create_task(app.shutdown())


async def main():
    """Main entry point"""
    try:
        # Enable discord.py debug logging
        import logging
        logging.getLogger("discord.gateway").setLevel(logging.DEBUG)
        logging.getLogger("discord.client").setLevel(logging.DEBUG)

        # Setup signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Initialize and start application
        await app.initialize()
        await app.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except SystemExit as e:
        logger.info(f"System exit with code {e.code}")
        sys.exit(e.code)
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
    finally:
        await app.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except SystemExit:
        # Already handled in main()
        pass
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)