import asyncio
import signal
import sys
import os
import psutil
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
from rajitan.scheduler.manager import SchedulerManager
from rajitan.scheduler.enhanced_manager import EnhancedScheduleManager
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
        self.scheduler_manager: Optional[SchedulerManager] = None
        self.enhanced_schedule_manager: Optional[EnhancedScheduleManager] = None
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
            
            # Initialize Discord bot first
            logger.info("Initializing Discord bot...")
            self.bot = RajitanBot()
            
            # Initialize scheduler with bot instance
            logger.info("Initializing scheduler...")
            self.scheduler_manager = SchedulerManager()
            self.enhanced_schedule_manager = EnhancedScheduleManager(self.db_client, self.bot)
            
            # Inject dependencies into bot
            self.bot.inject_dependencies(
                db_client=self.db_client,
                redis_client=self.redis_client,
                character_manager=self.character_manager,
                conversation_tracker=self.conversation_tracker,
                conversation_summarizer=self.conversation_summarizer,
                quiz_generator=self.quiz_generator,
                quiz_runner=self.quiz_runner,
                scheduler_manager=self.scheduler_manager,
                enhanced_schedule_manager=self.enhanced_schedule_manager
            )
            
            # Setup commands
            await setup_commands(self.bot)
            
            # Setup automated features
            await self._setup_automated_features()
            
            logger.info("Rajitan application initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize application: {e}")
            # Clean up PID file on initialization failure
            self.process_manager.remove_pid_file()
            raise
    
    async def _setup_automated_features(self):
        """Setup automated feature execution"""
        try:
            # This would set up automatic triggers for features
            # For now, we'll implement a simple version
            
            async def check_and_execute_features(channel_id: str, feature_type: str):
                """Check and execute features automatically"""
                try:
                    if feature_type == "summary":
                        await self._auto_execute_summary(channel_id)
                    elif feature_type == "quiz":
                        await self._auto_execute_quiz(channel_id)
                except Exception as e:
                    logger.error(f"Error in auto feature execution: {e}")
            
            # Schedule feature checks (would be more sophisticated in production)
            # This is a simplified version for demonstration
            
            logger.info("Automated features setup completed")
            
        except Exception as e:
            logger.error(f"Failed to setup automated features: {e}")
    
    async def _auto_execute_summary(self, channel_id: str):
        """Automatically execute summary if conditions are met"""
        try:
            # Check if summary should be executed
            should_execute = await self.conversation_tracker.should_execute_feature(
                channel_id, "summary"
            )
            
            if not should_execute:
                return
            
            # Get conversation data
            summary_data = await self.conversation_tracker.get_conversation_summary_data(channel_id)
            
            if not summary_data or not summary_data["messages"]:
                return
            
            # Get guild ID (simplified - would need proper channel->guild mapping)
            # For now, skip auto-summary and only do manual
            logger.debug(f"Auto summary check for channel {channel_id} - conditions not met")
            
        except Exception as e:
            logger.error(f"Error in auto summary execution: {e}")
    
    async def _auto_execute_quiz(self, channel_id: str):
        """Automatically execute quiz if conditions are met"""
        try:
            # Check if quiz should be executed
            should_execute = await self.conversation_tracker.should_execute_feature(
                channel_id, "quiz"
            )
            
            if not should_execute:
                return
            
            # Check if quiz is already active
            if await self.quiz_runner.is_quiz_active(channel_id):
                return
            
            # For now, skip auto-quiz and only do manual
            logger.debug(f"Auto quiz check for channel {channel_id} - conditions not met")
            
        except Exception as e:
            logger.error(f"Error in auto quiz execution: {e}")
    
    async def start(self):
        """Start the application"""
        try:
            if self.running:
                logger.warning("Application is already running")
                return
            
            logger.info("Starting Rajitan application...")
            
            # Start schedulers
            await self.scheduler_manager.start()
            await self.enhanced_schedule_manager.start()
            
            # Start Discord bot
            self.running = True
            await self.bot.start(config.discord_bot_token)
            
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
            if self.enhanced_schedule_manager:
                await self.enhanced_schedule_manager.stop()
            
            if self.scheduler_manager:
                await self.scheduler_manager.stop()
            
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