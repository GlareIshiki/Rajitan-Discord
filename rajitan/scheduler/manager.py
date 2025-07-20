import asyncio
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("scheduler_manager")
config = get_config()


class SchedulerManager:
    """Manages scheduled tasks for automatic feature execution"""
    
    def __init__(self):
        self.tasks: Dict[str, asyncio.Task] = {}
        self.running = False
        self.check_interval = 60  # Check every minute
    
    async def start(self):
        """Start the scheduler"""
        if self.running:
            return
        
        self.running = True
        
        # Start main scheduler loop
        self.tasks["main_loop"] = asyncio.create_task(self._scheduler_loop())
        
        logger.info("Scheduler manager started")
    
    async def stop(self):
        """Stop the scheduler"""
        if not self.running:
            return
        
        self.running = False
        
        # Cancel all tasks
        for task_name, task in self.tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self.tasks.clear()
        logger.info("Scheduler manager stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop"""
        try:
            while self.running:
                await asyncio.sleep(self.check_interval)
                
                if not self.running:
                    break
                
                # This is a simplified scheduler
                # In a full implementation, this would check database for scheduled tasks
                # and execute them based on their timing
                
                logger.debug("Scheduler check completed")
                
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
    
    async def schedule_feature_check(
        self, 
        channel_id: str, 
        feature_type: str, 
        callback: Callable,
        interval_minutes: int = 30
    ):
        """Schedule a feature check task"""
        try:
            task_name = f"{feature_type}_{channel_id}"
            
            # Cancel existing task if any
            if task_name in self.tasks:
                self.tasks[task_name].cancel()
            
            # Create new task
            self.tasks[task_name] = asyncio.create_task(
                self._feature_check_loop(channel_id, feature_type, callback, interval_minutes)
            )
            
            logger.info(f"Scheduled {feature_type} check for channel {channel_id} (interval: {interval_minutes}m)")
            
        except Exception as e:
            logger.error(f"Failed to schedule feature check: {e}")
    
    async def _feature_check_loop(
        self, 
        channel_id: str, 
        feature_type: str, 
        callback: Callable, 
        interval_minutes: int
    ):
        """Feature check loop"""
        try:
            while self.running:
                await asyncio.sleep(interval_minutes * 60)  # Convert to seconds
                
                if not self.running:
                    break
                
                try:
                    # Execute callback
                    await callback(channel_id, feature_type)
                except Exception as e:
                    logger.error(f"Error in feature check callback for {feature_type}: {e}")
                
        except asyncio.CancelledError:
            logger.info(f"Feature check loop cancelled for {feature_type}_{channel_id}")
        except Exception as e:
            logger.error(f"Error in feature check loop: {e}")
    
    async def unschedule_feature_check(self, channel_id: str, feature_type: str):
        """Unschedule a feature check task"""
        try:
            task_name = f"{feature_type}_{channel_id}"
            
            if task_name in self.tasks:
                self.tasks[task_name].cancel()
                del self.tasks[task_name]
                logger.info(f"Unscheduled {feature_type} check for channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Failed to unschedule feature check: {e}")
    
    def get_scheduled_tasks(self) -> List[Dict[str, Any]]:
        """Get list of scheduled tasks"""
        tasks_info = []
        
        for task_name, task in self.tasks.items():
            if task_name != "main_loop":
                parts = task_name.split("_", 1)
                if len(parts) == 2:
                    feature_type, channel_id = parts
                    tasks_info.append({
                        "feature_type": feature_type,
                        "channel_id": channel_id,
                        "status": "running" if not task.done() else "completed"
                    })
        
        return tasks_info
    
    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self.running