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
            from rajitan.agent.tools.summary_tool import SummaryTool
            from rajitan.agent.tools.quiz_tool import QuizTool
            from rajitan.agent.tools.music_tool import MusicTool
            from rajitan.agent.tools.schedule_tool import ScheduleCreateTool, ScheduleListTool, ScheduleDeleteTool
            from rajitan.agent.tools.task_tool import TaskAddTool, TaskCompleteTool, TaskListTool, ProjectListTool
            from rajitan.agent.tools.conversation_tool import GetConversationTool, SearchConversationTool, GetUserMessagesTool, AnalyzeMoodTool
            from rajitan.agent.tools.character_tool import CharacterTool
            from rajitan.agent.tools.discord_tool import SendMessageTool, AddReactionTool
            from rajitan.agent.orchestrator import AgentOrchestrator

            # Agent uses DeepSeek if configured, otherwise falls back to OpenAI
            if config.deepseek_api_key:
                from openai import AsyncOpenAI as _AsyncOpenAI
                deepseek_client = _AsyncOpenAI(
                    api_key=config.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                )
                llm_provider = OpenAIProvider(deepseek_client, "deepseek-chat")
                logger.info("Agent LLM: DeepSeek v3")
            else:
                llm_provider = OpenAIProvider(self.openai_client.client, self.openai_client.model)
                logger.info("Agent LLM: OpenAI")
            tool_registry = ToolRegistry()

            # Register all tools at startup (never add/remove dynamically)
            tool_registry.register(SummaryTool(self.conversation_summarizer, self.conversation_tracker))
            tool_registry.register(QuizTool(self.quiz_generator, self.quiz_runner, self.conversation_tracker))
            tool_registry.register(MusicTool(self.music_recommender, self.conversation_tracker))
            tool_registry.register(ScheduleCreateTool(self.enhanced_schedule_manager))
            tool_registry.register(ScheduleListTool(self.enhanced_schedule_manager))
            tool_registry.register(ScheduleDeleteTool(self.enhanced_schedule_manager))
            tool_registry.register(TaskAddTool(self.levemagi_client))
            tool_registry.register(TaskCompleteTool(self.levemagi_client))
            tool_registry.register(TaskListTool(self.levemagi_client))
            tool_registry.register(ProjectListTool(self.levemagi_client))
            tool_registry.register(GetConversationTool(self.conversation_tracker))
            tool_registry.register(SearchConversationTool())
            tool_registry.register(GetUserMessagesTool())
            tool_registry.register(AnalyzeMoodTool(self.conversation_tracker, self.conversation_analyzer))
            tool_registry.register(CharacterTool(self.character_manager))
            tool_registry.register(SendMessageTool())
            tool_registry.register(AddReactionTool())

            agent_orchestrator = AgentOrchestrator(
                llm_provider=llm_provider,
                tool_registry=tool_registry,
                character_manager=self.character_manager,
                conversation_tracker=self.conversation_tracker,
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