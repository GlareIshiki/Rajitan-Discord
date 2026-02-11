"""Persona repository — all persona DB operations in one place."""

import aiosqlite
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from rajitan.storage.persona_models import Persona
from rajitan.utils.logger import get_logger

logger = get_logger("persona_repo")


class PersonaRepo:
    """Handles all persona-related database operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @staticmethod
    async def create_table(db: aiosqlite.Connection) -> None:
        """Create personas table, indexes, and run migrations.

        Called from SQLiteClient._create_tables() within an existing connection.
        """
        await db.execute('''
            CREATE TABLE IF NOT EXISTS personas (
                id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                personality_traits TEXT NOT NULL DEFAULT '{}',
                is_preset INTEGER NOT NULL DEFAULT 0,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_personas_guild
            ON personas(guild_id)
        ''')

        # Idempotent migrations
        try:
            await db.execute(
                "ALTER TABLE personas ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # Column already exists

        try:
            await db.execute(
                "ALTER TABLE personas ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass  # Column already exists

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------

    async def seed_preset_personas(self) -> None:
        """Seed the 8 preset personas if they don't exist."""
        from rajitan.character.prompts import PERSONALITY_TRAITS, get_system_prompt

        PRESET_DESCRIPTIONS = {
            "default": ("ナチュラル", "バランスの取れた標準パーソナリティ"),
            "rajitan": ("らじたん", "ノリと勢いのらじたん本人 テンポよくフランクに接する"),
            "cheerful": ("ひなた", "元気で明るく陽気な性格"),
            "calm": ("凪", "落ち着いていてリラックスした性格"),
            "witty": ("キレモノ", "ユーモアたっぷりの切れ者"),
            "professional": ("ノーブル", "丁寧でフォーマルな対応"),
            "friendly": ("ほのか", "親しみやすくフレンドリー"),
            "sarcastic": ("ツンデレ", "皮肉屋だけど愛嬌がある"),
        }

        try:
            async with aiosqlite.connect(self.db_path) as db:
                for ptype, traits in PERSONALITY_TRAITS.items():
                    persona_id = f"preset_{ptype}"
                    display_name, description = PRESET_DESCRIPTIONS.get(
                        ptype, (ptype, ptype)
                    )
                    system_prompt = get_system_prompt("らじたん", ptype)

                    async with db.execute(
                        "SELECT id FROM personas WHERE id = ?", (persona_id,)
                    ) as cursor:
                        if await cursor.fetchone():
                            await db.execute(
                                '''UPDATE personas
                                   SET display_name = ?, description = ?
                                   WHERE id = ? AND is_preset = 1''',
                                (display_name, description, persona_id),
                            )
                            continue

                    await db.execute(
                        '''INSERT INTO personas
                           (id, guild_id, name, display_name, description,
                            system_prompt, personality_traits, is_preset, created_by)
                           VALUES (?, '', ?, ?, ?, ?, ?, 1, '')''',
                        (
                            persona_id,
                            ptype,
                            display_name,
                            description,
                            system_prompt,
                            json.dumps(traits),
                        ),
                    )

                await db.commit()
                logger.info("Preset personas seeded successfully")
        except Exception as e:
            logger.error(f"Failed to seed preset personas: {e}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_persona(self, persona: Persona) -> bool:
        """Create a new persona."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO personas
                       (id, guild_id, name, display_name, description,
                        system_prompt, personality_traits, is_preset, created_by,
                        created_at, updated_at, is_public, avatar_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        persona.id,
                        persona.guild_id,
                        persona.name,
                        persona.display_name,
                        persona.description,
                        persona.system_prompt,
                        json.dumps(persona.personality_traits),
                        int(persona.is_preset),
                        persona.created_by,
                        persona.created_at,
                        persona.updated_at,
                        int(persona.is_public),
                        persona.avatar_url,
                    ),
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create persona: {e}")
            return False

    async def get_persona(self, persona_id: str) -> Optional[Persona]:
        """Get a persona by ID."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    '''SELECT id, guild_id, name, display_name, description,
                              system_prompt, personality_traits, is_preset, created_by,
                              created_at, updated_at, is_public, avatar_url
                       FROM personas WHERE id = ?''',
                    (persona_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return self._row_to_persona(row)
                    return None
        except Exception as e:
            logger.error(f"Failed to get persona: {e}")
            return None

    async def get_guild_personas(self, guild_id: str) -> List[Persona]:
        """Get all personas available to a guild (presets + guild custom + public)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    '''SELECT id, guild_id, name, display_name, description,
                              system_prompt, personality_traits, is_preset, created_by,
                              created_at, updated_at, is_public, avatar_url
                       FROM personas
                       WHERE guild_id = '' OR guild_id = ? OR is_public = 1
                       ORDER BY is_preset DESC, created_at ASC, name ASC''',
                    (guild_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [self._row_to_persona(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get guild personas: {e}")
            return []

    async def update_persona(self, persona_id: str, updates: Dict[str, Any]) -> bool:
        """Update a persona (presets: only avatar_url allowed)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT is_preset FROM personas WHERE id = ?", (persona_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return False
                    is_preset = bool(row[0])

                    if is_preset:
                        if set(updates.keys()) - {"avatar_url"}:
                            logger.warning(f"Cannot update preset persona fields (except avatar_url): {persona_id}")
                            return False

                set_parts = []
                params: list = []
                for key, value in updates.items():
                    if key == "personality_traits" and isinstance(value, dict):
                        set_parts.append("personality_traits = ?")
                        params.append(json.dumps(value))
                    elif key == "is_public":
                        set_parts.append("is_public = ?")
                        params.append(int(value))
                    elif key in ("name", "display_name", "description", "system_prompt", "avatar_url"):
                        set_parts.append(f"{key} = ?")
                        params.append(value)

                if not set_parts:
                    return False

                set_parts.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(persona_id)

                await db.execute(
                    f"UPDATE personas SET {', '.join(set_parts)} WHERE id = ?",
                    params,
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to update persona: {e}")
            return False

    async def delete_persona(self, persona_id: str) -> bool:
        """Delete a custom persona (refuses presets, clears active references)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT is_preset FROM personas WHERE id = ?", (persona_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return False
                    if row[0]:
                        logger.warning(f"Cannot delete preset persona: {persona_id}")
                        return False

                await db.execute(
                    "UPDATE characters SET active_persona_id = '' WHERE active_persona_id = ?",
                    (persona_id,),
                )
                await db.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete persona: {e}")
            return False

    async def count_guild_personas(self, guild_id: str) -> int:
        """Count custom (non-preset) personas for a guild."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM personas WHERE guild_id = ? AND is_preset = 0",
                    (guild_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            logger.error(f"Failed to count guild personas: {e}")
            return 0

    async def set_guild_active_persona(self, guild_id: str, persona_id: str) -> bool:
        """Set the active persona for a guild (updates characters table)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT id FROM personas WHERE id = ? AND (guild_id = '' OR guild_id = ? OR is_public = 1)",
                    (persona_id, guild_id),
                ) as cursor:
                    if not await cursor.fetchone():
                        logger.warning(f"Persona {persona_id} not accessible to guild {guild_id}")
                        return False

                await db.execute(
                    "UPDATE characters SET active_persona_id = ?, updated_at = ? WHERE guild_id = ?",
                    (persona_id, datetime.now().isoformat(), guild_id),
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to set guild active persona: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _row_to_persona(self, row) -> Persona:
        """Convert a database row to a Persona object."""
        traits = {}
        if row[6]:
            try:
                traits = json.loads(row[6])
            except (json.JSONDecodeError, TypeError):
                pass

        return Persona(
            id=row[0],
            guild_id=row[1] or "",
            name=row[2],
            display_name=row[3] or "",
            description=row[4] or "",
            system_prompt=row[5] or "",
            personality_traits=traits,
            is_preset=bool(row[7]),
            is_public=bool(row[11]) if len(row) > 11 else False,
            avatar_url=row[12] if len(row) > 12 else "",
            created_by=row[8] or "",
            created_at=datetime.fromisoformat(row[9]) if row[9] else datetime.now(),
            updated_at=datetime.fromisoformat(row[10]) if row[10] else datetime.now(),
        )
