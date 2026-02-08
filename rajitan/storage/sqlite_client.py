import aiosqlite
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from rajitan.storage.models import Guild, Channel, Character, Schedule, UsageStat
from rajitan.utils.logger import get_logger
from rajitan.utils.config import get_config

logger = get_logger("sqlite_client")
config = get_config()


class SQLiteClient:
    """SQLite database client"""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.database_url.replace("sqlite:///", "")
        self._initialized = False
    
    async def initialize(self):
        """Initialize database tables"""
        if self._initialized:
            return
        
        try:
            await self._create_tables()
            self._initialized = True
            logger.info("SQLite database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            raise
    
    async def _create_tables(self):
        """Create database tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Guilds table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS guilds (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Channels table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (guild_id) REFERENCES guilds(id)
                )
            ''')
            
            # Characters table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS characters (
                    guild_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    system_prompt TEXT NOT NULL,
                    personality_traits TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (guild_id) REFERENCES guilds(id)
                )
            ''')
            
            # Schedules table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    function_type TEXT NOT NULL,
                    custom_message TEXT,
                    
                    pattern_type TEXT NOT NULL,
                    hour INTEGER,
                    minute INTEGER,
                    day_of_week INTEGER,
                    day_of_month INTEGER,
                    specific_datetime TIMESTAMP,
                    
                    is_active BOOLEAN DEFAULT TRUE,
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_executed TIMESTAMP,
                    next_execution TIMESTAMP,
                    
                    FOREIGN KEY (channel_id) REFERENCES channels(id),
                    FOREIGN KEY (guild_id) REFERENCES guilds(id)
                )
            ''')
            
            # Schedule executions table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS schedule_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id INTEGER NOT NULL,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    execution_time_ms INTEGER,
                    
                    FOREIGN KEY (schedule_id) REFERENCES schedules(id)
                )
            ''')
            
            # Usage statistics table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS usage_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    feature_type TEXT NOT NULL,
                    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN DEFAULT TRUE,
                    FOREIGN KEY (guild_id) REFERENCES guilds(id)
                )
            ''')

            # LeveMagi tables
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_users (
                    discord_id TEXT PRIMARY KEY,
                    total_xp REAL DEFAULT 0,
                    gacha_tickets INTEGER DEFAULT 0,
                    collected_items TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_portals (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    rating REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (discord_id) REFERENCES lm_users(discord_id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_nuts (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    portal_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'いつかやる',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    difficulty INTEGER NOT NULL DEFAULT 1,
                    tags TEXT DEFAULT '[]',
                    start_date TEXT,
                    deadline TEXT,
                    icon TEXT,
                    image_url TEXT,
                    version TEXT,
                    public_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (discord_id) REFERENCES lm_users(discord_id),
                    FOREIGN KEY (portal_id) REFERENCES lm_portals(id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_trunks (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    nuts_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'non-issue',
                    value INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'pending',
                    what TEXT DEFAULT '',
                    idea TEXT DEFAULT '',
                    conclusion TEXT DEFAULT '',
                    detail TEXT,
                    comment TEXT,
                    tags TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (nuts_id) REFERENCES lm_nuts(id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_leaves (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    nuts_id TEXT,
                    trunk_id TEXT,
                    title TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'medium',
                    difficulty TEXT NOT NULL DEFAULT 'normal',
                    started_at TEXT,
                    completed_at TEXT,
                    actual_hours REAL,
                    bonus_hours REAL,
                    xp_subtotal REAL,
                    memo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (nuts_id) REFERENCES lm_nuts(id),
                    FOREIGN KEY (trunk_id) REFERENCES lm_trunks(id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_roots (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    nuts_id TEXT,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'seed',
                    value REAL,
                    difficulty INTEGER,
                    tags TEXT DEFAULT '[]',
                    what TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    comment TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (nuts_id) REFERENCES lm_nuts(id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_worklogs (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    nuts_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status_snapshot TEXT,
                    phase_snapshot TEXT,
                    level_snapshot INTEGER,
                    deadline_snapshot TEXT,
                    note TEXT,
                    FOREIGN KEY (nuts_id) REFERENCES lm_nuts(id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_resources (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    description TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_tags (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_favorite BOOLEAN DEFAULT FALSE,
                    UNIQUE(discord_id, name)
                )
            ''')

            # Calendar events table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lm_calendar_events (
                    id TEXT PRIMARY KEY,
                    discord_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    event_type TEXT NOT NULL DEFAULT 'manual',
                    source_id TEXT,
                    color TEXT,
                    is_all_day BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Bot activities table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Agent memories table (Tier 3: long-term memory)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, channel_id, user_id, category, key)
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_agent_memories_guild
                ON agent_memories(guild_id)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_agent_memories_user
                ON agent_memories(guild_id, user_id)
            ''')

            await db.commit()
    
    # Guild operations
    async def create_guild(self, guild: Guild) -> bool:
        """Create a new guild"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT OR REPLACE INTO guilds (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)',
                    (guild.id, guild.name, guild.created_at, guild.updated_at)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create guild: {e}")
            return False
    
    async def get_guild(self, guild_id: str) -> Optional[Guild]:
        """Get guild by ID"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT id, name, created_at, updated_at FROM guilds WHERE id = ?',
                    (guild_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return Guild(
                            id=row[0],
                            name=row[1],
                            created_at=datetime.fromisoformat(row[2]),
                            updated_at=datetime.fromisoformat(row[3])
                        )
                    return None
        except Exception as e:
            logger.error(f"Failed to get guild: {e}")
            return None
    
    # Channel operations
    async def create_channel(self, channel: Channel) -> bool:
        """Create a new channel"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT OR REPLACE INTO channels (id, guild_id, name, is_active, created_at) VALUES (?, ?, ?, ?, ?)',
                    (channel.id, channel.guild_id, channel.name, channel.is_active, channel.created_at)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create channel: {e}")
            return False
    
    async def get_channel(self, channel_id: str) -> Optional[Channel]:
        """Get channel by ID"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT id, guild_id, name, is_active, created_at FROM channels WHERE id = ?',
                    (channel_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return Channel(
                            id=row[0],
                            guild_id=row[1],
                            name=row[2],
                            is_active=bool(row[3]),
                            created_at=datetime.fromisoformat(row[4])
                        )
                    return None
        except Exception as e:
            logger.error(f"Failed to get channel: {e}")
            return None
    
    # Character operations
    async def create_character(self, character: Character) -> bool:
        """Create or update a character"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                personality_traits = character.personality_traits
                if personality_traits:
                    import json
                    personality_traits = json.dumps(personality_traits)
                
                await db.execute(
                    'INSERT OR REPLACE INTO characters (guild_id, name, system_prompt, personality_traits, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (character.guild_id, character.name, character.system_prompt, personality_traits, character.created_at, character.updated_at)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create character: {e}")
            return False
    
    async def get_character(self, guild_id: str) -> Optional[Character]:
        """Get character by guild ID"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    'SELECT guild_id, name, system_prompt, personality_traits, created_at, updated_at FROM characters WHERE guild_id = ?',
                    (guild_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        personality_traits = None
                        if row[3]:
                            import json
                            personality_traits = json.loads(row[3])
                        
                        return Character(
                            guild_id=row[0],
                            name=row[1],
                            system_prompt=row[2],
                            personality_traits=personality_traits,
                            created_at=datetime.fromisoformat(row[4]),
                            updated_at=datetime.fromisoformat(row[5])
                        )
                    return None
        except Exception as e:
            logger.error(f"Failed to get character: {e}")
            return None
    
    # Schedule operations
    async def create_schedule(self, schedule: Schedule) -> bool:
        """Create a new schedule"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO schedules (
                        channel_id, guild_id, schedule_type, function_type, custom_message,
                        pattern_type, hour, minute, day_of_week, day_of_month, specific_datetime,
                        is_active, created_by, created_at, last_executed, next_execution
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        schedule.channel_id, schedule.guild_id, schedule.schedule_type, 
                        schedule.function_type, schedule.custom_message,
                        schedule.pattern_type, schedule.hour, schedule.minute, 
                        schedule.day_of_week, schedule.day_of_month, schedule.specific_datetime,
                        schedule.is_active, schedule.created_by, schedule.created_at, 
                        schedule.last_executed, schedule.next_execution
                    )
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create schedule: {e}")
            return False
    
    async def get_schedules(self, channel_id: str) -> List[Schedule]:
        """Get all schedules for a channel"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    '''SELECT id, channel_id, guild_id, schedule_type, function_type, custom_message,
                        pattern_type, hour, minute, day_of_week, day_of_month, specific_datetime,
                        is_active, created_by, created_at, last_executed, next_execution 
                        FROM schedules WHERE channel_id = ?''',
                    (channel_id,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    schedules = []
                    for row in rows:
                        last_executed = None
                        if row[15]:
                            last_executed = datetime.fromisoformat(row[15])
                        
                        next_execution = None
                        if row[16]:
                            next_execution = datetime.fromisoformat(row[16])
                        
                        specific_datetime = None
                        if row[11]:
                            specific_datetime = datetime.fromisoformat(row[11])
                        
                        schedules.append(Schedule(
                            id=row[0],
                            channel_id=row[1],
                            guild_id=row[2],
                            schedule_type=row[3],
                            function_type=row[4],
                            custom_message=row[5],
                            pattern_type=row[6],
                            hour=row[7],
                            minute=row[8],
                            day_of_week=row[9],
                            day_of_month=row[10],
                            specific_datetime=specific_datetime,
                            is_active=bool(row[12]),
                            created_by=row[13],
                            created_at=datetime.fromisoformat(row[14]),
                            last_executed=last_executed,
                            next_execution=next_execution
                        ))
                    return schedules
        except Exception as e:
            logger.error(f"Failed to get schedules: {e}")
            return []
    
    async def update_schedule_execution(self, schedule_id: int, execution_time: datetime) -> bool:
        """Update schedule last execution time"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'UPDATE schedules SET last_executed = ? WHERE id = ?',
                    (execution_time, schedule_id)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to update schedule execution: {e}")
            return False
    
    # Usage statistics
    async def add_usage_stat(self, usage_stat: UsageStat) -> bool:
        """Add usage statistics"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT INTO usage_stats (guild_id, channel_id, feature_type, execution_time, success) VALUES (?, ?, ?, ?, ?)',
                    (usage_stat.guild_id, usage_stat.channel_id, usage_stat.feature_type, usage_stat.execution_time, usage_stat.success)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to add usage stat: {e}")
            return False
    
    # Agent memory operations (Tier 3)
    async def upsert_agent_memory(
        self, guild_id: str, category: str, key: str, value: str,
        channel_id: str = None, user_id: str = None
    ) -> bool:
        """Insert or update an agent memory entry"""
        try:
            # Convert None to empty string for UNIQUE constraint compatibility
            channel_id = channel_id or ''
            user_id = user_id or ''
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO agent_memories
                       (guild_id, channel_id, user_id, category, key, value, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(guild_id, channel_id, user_id, category, key)
                       DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP''',
                    (guild_id, channel_id, user_id, category, key, value)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to upsert agent memory: {e}")
            return False

    async def get_agent_memories(
        self, guild_id: str, category: str = None, user_id: str = None,
        channel_id: str = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get agent memories with optional filters"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                query = "SELECT guild_id, channel_id, user_id, category, key, value, created_at, updated_at FROM agent_memories WHERE guild_id = ?"
                params: list = [guild_id]

                if category:
                    query += " AND category = ?"
                    params.append(category)
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                if channel_id:
                    query += " AND channel_id = ?"
                    params.append(channel_id)

                query += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                async with db.execute(query, params) as cursor:
                    rows = await cursor.fetchall()
                    return [
                        {
                            "guild_id": r[0],
                            "channel_id": r[1],
                            "user_id": r[2],
                            "category": r[3],
                            "key": r[4],
                            "value": r[5],
                            "created_at": r[6],
                            "updated_at": r[7],
                        }
                        for r in rows
                    ]
        except Exception as e:
            logger.error(f"Failed to get agent memories: {e}")
            return []

    async def delete_agent_memory(self, guild_id: str, category: str, key: str) -> bool:
        """Delete an agent memory entry"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "DELETE FROM agent_memories WHERE guild_id = ? AND category = ? AND key = ?",
                    (guild_id, category, key)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete agent memory: {e}")
            return False

    async def close(self):
        """Close database connection"""
        pass