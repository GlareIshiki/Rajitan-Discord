"""LeveMagi SQLite CRUD client"""

import json
import uuid
import aiosqlite
from datetime import datetime
from typing import Optional, List
from rajitan.storage.levemagi_models import (
    LMUser,
    LMNuts,
    LMNutsCreate,
    LMNutsUpdate,
    LMLeaf,
    LMLeafCreate,
    LMTrunk,
    LMTrunkCreate,
    LMTrunkUpdate,
    LMRoot,
    LMRootCreate,
    LMRootUpdate,
    LMPortal,
    LMPortalCreate,
    LMPortalUpdate,
    LMResource,
    LMResourceCreate,
    LMResourceUpdate,
    LMTag,
    LMTagCreate,
    LMWorklog,
    LMState,
)
from rajitan.utils.logger import get_logger

logger = get_logger("levemagi_client")


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now().isoformat()


class _LMConnection:
    """Async context manager that opens an aiosqlite connection with Row factory."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db = None

    async def __aenter__(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        return self._db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._db:
            await self._db.close()
        return False


class LeveMagiClient:
    """SQLite CRUD client for LeveMagi data"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self):
        """Return an aiosqlite context manager.

        Usage::

            async with self._connect() as db:
                ...
        """
        return _LMConnection(self.db_path)

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------
    async def initialize(self):
        """Create LeveMagi tables if not exist"""
        async with self._connect() as db:
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        logger.info("LeveMagi tables initialized")

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------
    async def get_or_create_user(self, discord_id: str) -> LMUser:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_users WHERE discord_id = ?", (discord_id,)
            )
            row = await cursor.fetchone()
            if row:
                return LMUser(
                    discord_id=row["discord_id"],
                    total_xp=row["total_xp"],
                    gacha_tickets=row["gacha_tickets"],
                    collected_items=json.loads(row["collected_items"] or "[]"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            now = _now_iso()
            await db.execute(
                "INSERT INTO lm_users (discord_id, total_xp, gacha_tickets, collected_items, created_at, updated_at) VALUES (?, 0, 0, '[]', ?, ?)",
                (discord_id, now, now),
            )
            await db.commit()
            return LMUser(
                discord_id=discord_id,
                total_xp=0,
                gacha_tickets=0,
                collected_items=[],
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )

    async def add_xp(self, discord_id: str, xp: float) -> LMUser:
        async with self._connect() as db:
            now = _now_iso()
            await db.execute(
                "UPDATE lm_users SET total_xp = total_xp + ?, updated_at = ? WHERE discord_id = ?",
                (xp, now, discord_id),
            )
            await db.commit()
        return await self.get_or_create_user(discord_id)

    async def consume_gacha_ticket(self, discord_id: str) -> bool:
        """Consume one gacha ticket. Returns False if no tickets available."""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT gacha_tickets FROM lm_users WHERE discord_id = ?",
                (discord_id,),
            )
            row = await cursor.fetchone()
            if not row or row["gacha_tickets"] <= 0:
                return False
            now = _now_iso()
            await db.execute(
                "UPDATE lm_users SET gacha_tickets = gacha_tickets - 1, updated_at = ? WHERE discord_id = ?",
                (now, discord_id),
            )
            await db.commit()
            return True

    async def add_collected_item(self, discord_id: str, item: str) -> LMUser:
        user = await self.get_or_create_user(discord_id)
        items = user.collected_items
        items.append(item)
        async with self._connect() as db:
            now = _now_iso()
            await db.execute(
                "UPDATE lm_users SET collected_items = ?, updated_at = ? WHERE discord_id = ?",
                (json.dumps(items), now, discord_id),
            )
            await db.commit()
        return await self.get_or_create_user(discord_id)

    # ------------------------------------------------------------------
    # Nuts (Projects)
    # ------------------------------------------------------------------
    async def get_all_nuts(self, discord_id: str) -> List[LMNuts]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_nuts WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_nuts(r) for r in rows]

    async def create_nuts(self, discord_id: str, data: LMNutsCreate) -> LMNuts:
        nid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_nuts
                   (id, discord_id, portal_id, name, description, status, priority, difficulty,
                    tags, start_date, deadline, icon, image_url, version, public_url, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    nid, discord_id, data.portal_id, data.name, data.description,
                    data.status, data.priority, data.difficulty,
                    json.dumps(data.tags), data.start_date, data.deadline,
                    data.icon, data.image_url, data.version, data.public_url, now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_nuts WHERE id = ?", (nid,))
            row = await cursor.fetchone()
            return _row_to_nuts(row)

    async def update_nuts(self, discord_id: str, nuts_id: str, data: LMNutsUpdate) -> Optional[LMNuts]:
        fields = data.model_dump(exclude_none=True)
        if not fields:
            return await self._get_nuts_by_id(discord_id, nuts_id)
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [nuts_id, discord_id]
        async with self._connect() as db:
            await db.execute(
                f"UPDATE lm_nuts SET {set_clause} WHERE id = ? AND discord_id = ?",
                values,
            )
            await db.commit()
        return await self._get_nuts_by_id(discord_id, nuts_id)

    async def delete_nuts(self, discord_id: str, nuts_id: str) -> bool:
        async with self._connect() as db:
            # Cascade: delete leaves, trunks, roots, worklogs tied to this nut
            for table in ("lm_leaves", "lm_trunks", "lm_roots", "lm_worklogs"):
                await db.execute(
                    f"DELETE FROM {table} WHERE nuts_id = ? AND discord_id = ?",
                    (nuts_id, discord_id),
                )
            cursor = await db.execute(
                "DELETE FROM lm_nuts WHERE id = ? AND discord_id = ?",
                (nuts_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def start_work_on_nuts(self, discord_id: str, nuts_id: str) -> LMWorklog:
        """Create a new worklog entry for starting work on a nut"""
        wid = _gen_id()
        now = _now_iso()
        nut = await self._get_nuts_by_id(discord_id, nuts_id)
        name = nut.name if nut else "Unknown"
        status_snapshot = nut.status if nut else None
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_worklogs
                   (id, discord_id, nuts_id, name, started_at, status_snapshot)
                   VALUES (?,?,?,?,?,?)""",
                (wid, discord_id, nuts_id, name, now, status_snapshot),
            )
            if nut and nut.status == "\u3044\u3064\u304b\u3084\u308b":
                await db.execute(
                    "UPDATE lm_nuts SET status = ? WHERE id = ? AND discord_id = ?",
                    ("\u9032\u884c\u4e2d", nuts_id, discord_id),
                )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_worklogs WHERE id = ?", (wid,))
            row = await cursor.fetchone()
            return _row_to_worklog(row)

    async def complete_nuts(self, discord_id: str, nuts_id: str) -> Optional[LMNuts]:
        """Mark a nut as completed"""
        async with self._connect() as db:
            await db.execute(
                "UPDATE lm_nuts SET status = ? WHERE id = ? AND discord_id = ?",
                ("\u5b8c\u4e86", nuts_id, discord_id),
            )
            await db.commit()
        return await self._get_nuts_by_id(discord_id, nuts_id)

    async def _get_nuts_by_id(self, discord_id: str, nuts_id: str) -> Optional[LMNuts]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_nuts WHERE id = ? AND discord_id = ?",
                (nuts_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_nuts(row) if row else None

    # ------------------------------------------------------------------
    # Leaves (Tasks)
    # ------------------------------------------------------------------
    async def get_all_leaves(self, discord_id: str) -> List[LMLeaf]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_leaves WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_leaf(r) for r in rows]

    async def create_leaf(self, discord_id: str, data: LMLeafCreate) -> LMLeaf:
        lid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_leaves
                   (id, discord_id, nuts_id, trunk_id, title, priority, difficulty,
                    started_at, completed_at, actual_hours, bonus_hours, xp_subtotal, memo, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lid, discord_id, data.nuts_id, data.trunk_id, data.title,
                    data.priority, data.difficulty, data.started_at, data.completed_at,
                    data.actual_hours, data.bonus_hours, data.xp_subtotal, data.memo, now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_leaves WHERE id = ?", (lid,))
            row = await cursor.fetchone()
            return _row_to_leaf(row)

    async def start_leaf(self, discord_id: str, leaf_id: str) -> Optional[LMLeaf]:
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                "UPDATE lm_leaves SET started_at = ? WHERE id = ? AND discord_id = ? AND started_at IS NULL",
                (now, leaf_id, discord_id),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM lm_leaves WHERE id = ? AND discord_id = ?",
                (leaf_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_leaf(row) if row else None

    async def complete_leaf(
        self, discord_id: str, leaf_id: str, actual_hours: float
    ) -> Optional[LMLeaf]:
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                "UPDATE lm_leaves SET completed_at = ?, actual_hours = ? WHERE id = ? AND discord_id = ?",
                (now, actual_hours, leaf_id, discord_id),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM lm_leaves WHERE id = ? AND discord_id = ?",
                (leaf_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_leaf(row) if row else None

    async def delete_leaf(self, discord_id: str, leaf_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_leaves WHERE id = ? AND discord_id = ?",
                (leaf_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Trunks (Issues)
    # ------------------------------------------------------------------
    async def get_all_trunks(self, discord_id: str) -> List[LMTrunk]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_trunks WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_trunk(r) for r in rows]

    async def create_trunk(self, discord_id: str, data: LMTrunkCreate) -> LMTrunk:
        tid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_trunks
                   (id, discord_id, nuts_id, title, type, value, status,
                    what, idea, conclusion, detail, comment, tags, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    tid, discord_id, data.nuts_id, data.title, data.type,
                    data.value, data.status, data.what, data.idea, data.conclusion,
                    data.detail, data.comment, json.dumps(data.tags), now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_trunks WHERE id = ?", (tid,))
            row = await cursor.fetchone()
            return _row_to_trunk(row)

    async def update_trunk(
        self, discord_id: str, trunk_id: str, data: LMTrunkUpdate
    ) -> Optional[LMTrunk]:
        fields = data.model_dump(exclude_none=True)
        if not fields:
            return await self._get_trunk_by_id(discord_id, trunk_id)
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [trunk_id, discord_id]
        async with self._connect() as db:
            await db.execute(
                f"UPDATE lm_trunks SET {set_clause} WHERE id = ? AND discord_id = ?",
                values,
            )
            await db.commit()
        return await self._get_trunk_by_id(discord_id, trunk_id)

    async def delete_trunk(self, discord_id: str, trunk_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_trunks WHERE id = ? AND discord_id = ?",
                (trunk_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _get_trunk_by_id(self, discord_id: str, trunk_id: str) -> Optional[LMTrunk]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_trunks WHERE id = ? AND discord_id = ?",
                (trunk_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_trunk(row) if row else None

    # ------------------------------------------------------------------
    # Roots (Knowledge)
    # ------------------------------------------------------------------
    async def get_all_roots(self, discord_id: str) -> List[LMRoot]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_roots WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_root(r) for r in rows]

    async def create_root(self, discord_id: str, data: LMRootCreate) -> LMRoot:
        rid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_roots
                   (id, discord_id, nuts_id, title, type, value, difficulty,
                    tags, what, content, comment, url, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid, discord_id, data.nuts_id, data.title, data.type,
                    data.value, data.difficulty, json.dumps(data.tags),
                    data.what, data.content, data.comment, data.url, now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_roots WHERE id = ?", (rid,))
            row = await cursor.fetchone()
            return _row_to_root(row)

    async def update_root(
        self, discord_id: str, root_id: str, data: LMRootUpdate
    ) -> Optional[LMRoot]:
        fields = data.model_dump(exclude_none=True)
        if not fields:
            return await self._get_root_by_id(discord_id, root_id)
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [root_id, discord_id]
        async with self._connect() as db:
            await db.execute(
                f"UPDATE lm_roots SET {set_clause} WHERE id = ? AND discord_id = ?",
                values,
            )
            await db.commit()
        return await self._get_root_by_id(discord_id, root_id)

    async def delete_root(self, discord_id: str, root_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_roots WHERE id = ? AND discord_id = ?",
                (root_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _get_root_by_id(self, discord_id: str, root_id: str) -> Optional[LMRoot]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_roots WHERE id = ? AND discord_id = ?",
                (root_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_root(row) if row else None

    # ------------------------------------------------------------------
    # Portals
    # ------------------------------------------------------------------
    async def get_all_portals(self, discord_id: str) -> List[LMPortal]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_portals WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_portal(r) for r in rows]

    async def create_portal(self, discord_id: str, data: LMPortalCreate) -> LMPortal:
        pid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_portals
                   (id, discord_id, name, category, description, tags, rating, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    pid, discord_id, data.name, data.category, data.description,
                    json.dumps(data.tags), data.rating, now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_portals WHERE id = ?", (pid,))
            row = await cursor.fetchone()
            return _row_to_portal(row)

    async def update_portal(
        self, discord_id: str, portal_id: str, data: LMPortalUpdate
    ) -> Optional[LMPortal]:
        fields = data.model_dump(exclude_none=True)
        if not fields:
            return await self._get_portal_by_id(discord_id, portal_id)
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [portal_id, discord_id]
        async with self._connect() as db:
            await db.execute(
                f"UPDATE lm_portals SET {set_clause} WHERE id = ? AND discord_id = ?",
                values,
            )
            await db.commit()
        return await self._get_portal_by_id(discord_id, portal_id)

    async def delete_portal(self, discord_id: str, portal_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_portals WHERE id = ? AND discord_id = ?",
                (portal_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _get_portal_by_id(self, discord_id: str, portal_id: str) -> Optional[LMPortal]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_portals WHERE id = ? AND discord_id = ?",
                (portal_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_portal(row) if row else None

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------
    async def get_all_resources(self, discord_id: str) -> List[LMResource]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_resources WHERE discord_id = ? ORDER BY created_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_resource(r) for r in rows]

    async def create_resource(self, discord_id: str, data: LMResourceCreate) -> LMResource:
        rid = data.id or _gen_id()
        now = _now_iso()
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO lm_resources
                   (id, discord_id, name, type, tags, description, url, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    rid, discord_id, data.name, data.type,
                    json.dumps(data.tags), data.description, data.url, now,
                ),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_resources WHERE id = ?", (rid,))
            row = await cursor.fetchone()
            return _row_to_resource(row)

    async def update_resource(
        self, discord_id: str, resource_id: str, data: LMResourceUpdate
    ) -> Optional[LMResource]:
        fields = data.model_dump(exclude_none=True)
        if not fields:
            return await self._get_resource_by_id(discord_id, resource_id)
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [resource_id, discord_id]
        async with self._connect() as db:
            await db.execute(
                f"UPDATE lm_resources SET {set_clause} WHERE id = ? AND discord_id = ?",
                values,
            )
            await db.commit()
        return await self._get_resource_by_id(discord_id, resource_id)

    async def delete_resource(self, discord_id: str, resource_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_resources WHERE id = ? AND discord_id = ?",
                (resource_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _get_resource_by_id(self, discord_id: str, resource_id: str) -> Optional[LMResource]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_resources WHERE id = ? AND discord_id = ?",
                (resource_id, discord_id),
            )
            row = await cursor.fetchone()
            return _row_to_resource(row) if row else None

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
    async def get_all_tags(self, discord_id: str) -> List[LMTag]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_tags WHERE discord_id = ?",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_tag(r) for r in rows]

    async def create_tag(self, discord_id: str, data: LMTagCreate) -> LMTag:
        tid = data.id or _gen_id()
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO lm_tags (id, discord_id, name, is_favorite) VALUES (?,?,?,?)",
                (tid, discord_id, data.name, data.is_favorite),
            )
            await db.commit()
            cursor = await db.execute("SELECT * FROM lm_tags WHERE id = ?", (tid,))
            row = await cursor.fetchone()
            return _row_to_tag(row)

    async def delete_tag(self, discord_id: str, tag_id: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM lm_tags WHERE id = ? AND discord_id = ?",
                (tag_id, discord_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Worklogs
    # ------------------------------------------------------------------
    async def get_all_worklogs(self, discord_id: str) -> List[LMWorklog]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM lm_worklogs WHERE discord_id = ? ORDER BY started_at DESC",
                (discord_id,),
            )
            rows = await cursor.fetchall()
            return [_row_to_worklog(r) for r in rows]

    # ------------------------------------------------------------------
    # Full State (import / export)
    # ------------------------------------------------------------------
    async def get_full_state(self, discord_id: str) -> LMState:
        user = await self.get_or_create_user(discord_id)
        nuts = await self.get_all_nuts(discord_id)
        trunks = await self.get_all_trunks(discord_id)
        leaves = await self.get_all_leaves(discord_id)
        roots = await self.get_all_roots(discord_id)
        portals = await self.get_all_portals(discord_id)
        worklogs = await self.get_all_worklogs(discord_id)
        resources = await self.get_all_resources(discord_id)
        tags = await self.get_all_tags(discord_id)
        return LMState(
            nuts=nuts,
            trunks=trunks,
            leaves=leaves,
            roots=roots,
            portals=portals,
            worklogs=worklogs,
            resources=resources,
            tags=tags,
            user_data=user,
        )

    async def import_state(self, discord_id: str, state: LMState) -> LMState:
        """Import full state, replacing all existing data for this user."""
        async with self._connect() as db:
            # Clear existing data
            for table in (
                "lm_worklogs", "lm_leaves", "lm_trunks", "lm_roots",
                "lm_portals", "lm_resources", "lm_tags", "lm_nuts", "lm_users",
            ):
                await db.execute(
                    f"DELETE FROM {table} WHERE discord_id = ?", (discord_id,)
                )

            # Insert user
            ud = state.user_data
            now = _now_iso()
            await db.execute(
                "INSERT INTO lm_users (discord_id, total_xp, gacha_tickets, collected_items, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (
                    discord_id, ud.total_xp, ud.gacha_tickets,
                    json.dumps(ud.collected_items), now, now,
                ),
            )

            # Insert portals
            for p in state.portals:
                await db.execute(
                    "INSERT INTO lm_portals (id, discord_id, name, category, description, tags, rating, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        p.id, discord_id, p.name, p.category, p.description,
                        json.dumps(p.tags), p.rating,
                        p.created_at.isoformat() if isinstance(p.created_at, datetime) else str(p.created_at),
                    ),
                )

            # Insert nuts
            for n in state.nuts:
                await db.execute(
                    """INSERT INTO lm_nuts
                       (id, discord_id, portal_id, name, description, status, priority, difficulty,
                        tags, start_date, deadline, icon, image_url, version, public_url, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        n.id, discord_id, n.portal_id, n.name, n.description,
                        n.status, n.priority, n.difficulty, json.dumps(n.tags),
                        n.start_date, n.deadline, n.icon, n.image_url, n.version, n.public_url,
                        n.created_at.isoformat() if isinstance(n.created_at, datetime) else str(n.created_at),
                    ),
                )

            # Insert trunks
            for t in state.trunks:
                await db.execute(
                    """INSERT INTO lm_trunks
                       (id, discord_id, nuts_id, title, type, value, status,
                        what, idea, conclusion, detail, comment, tags, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        t.id, discord_id, t.nuts_id, t.title, t.type,
                        t.value, t.status, t.what, t.idea, t.conclusion,
                        t.detail, t.comment, json.dumps(t.tags),
                        t.created_at.isoformat() if isinstance(t.created_at, datetime) else str(t.created_at),
                    ),
                )

            # Insert leaves
            for lf in state.leaves:
                await db.execute(
                    """INSERT INTO lm_leaves
                       (id, discord_id, nuts_id, trunk_id, title, priority, difficulty,
                        started_at, completed_at, actual_hours, bonus_hours, xp_subtotal, memo, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        lf.id, discord_id, lf.nuts_id, lf.trunk_id, lf.title,
                        lf.priority, lf.difficulty, lf.started_at, lf.completed_at,
                        lf.actual_hours, lf.bonus_hours, lf.xp_subtotal, lf.memo,
                        lf.created_at.isoformat() if isinstance(lf.created_at, datetime) else str(lf.created_at),
                    ),
                )

            # Insert roots
            for r in state.roots:
                await db.execute(
                    """INSERT INTO lm_roots
                       (id, discord_id, nuts_id, title, type, value, difficulty,
                        tags, what, content, comment, url, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.id, discord_id, r.nuts_id, r.title, r.type,
                        r.value, r.difficulty, json.dumps(r.tags),
                        r.what, r.content, r.comment, r.url,
                        r.created_at.isoformat() if isinstance(r.created_at, datetime) else str(r.created_at),
                    ),
                )

            # Insert worklogs
            for w in state.worklogs:
                await db.execute(
                    """INSERT INTO lm_worklogs
                       (id, discord_id, nuts_id, name, started_at, completed_at,
                        status_snapshot, phase_snapshot, level_snapshot, deadline_snapshot, note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        w.id, discord_id, w.nuts_id, w.name, w.started_at,
                        w.completed_at, w.status_snapshot, w.phase_snapshot,
                        w.level_snapshot, w.deadline_snapshot, w.note,
                    ),
                )

            # Insert resources
            for r in state.resources:
                await db.execute(
                    "INSERT INTO lm_resources (id, discord_id, name, type, tags, description, url, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        r.id, discord_id, r.name, r.type, json.dumps(r.tags),
                        r.description, r.url,
                        r.created_at.isoformat() if isinstance(r.created_at, datetime) else str(r.created_at),
                    ),
                )

            # Insert tags
            for t in state.tags:
                await db.execute(
                    "INSERT INTO lm_tags (id, discord_id, name, is_favorite) VALUES (?,?,?,?)",
                    (t.id, discord_id, t.name, t.is_favorite),
                )

            await db.commit()

        return await self.get_full_state(discord_id)


# ======================================================================
# Row -> Model converters
# ======================================================================

def _row_to_nuts(row) -> LMNuts:
    return LMNuts(
        id=row["id"],
        discord_id=row["discord_id"],
        portal_id=row["portal_id"],
        name=row["name"],
        description=row["description"],
        status=row["status"],
        priority=row["priority"],
        difficulty=row["difficulty"],
        tags=json.loads(row["tags"] or "[]"),
        start_date=row["start_date"],
        deadline=row["deadline"],
        icon=row["icon"],
        image_url=row["image_url"],
        version=row["version"],
        public_url=row["public_url"],
        created_at=row["created_at"],
    )


def _row_to_leaf(row) -> LMLeaf:
    return LMLeaf(
        id=row["id"],
        discord_id=row["discord_id"],
        nuts_id=row["nuts_id"],
        trunk_id=row["trunk_id"],
        title=row["title"],
        priority=row["priority"],
        difficulty=row["difficulty"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        actual_hours=row["actual_hours"],
        bonus_hours=row["bonus_hours"],
        xp_subtotal=row["xp_subtotal"],
        memo=row["memo"],
        created_at=row["created_at"],
    )


def _row_to_trunk(row) -> LMTrunk:
    return LMTrunk(
        id=row["id"],
        discord_id=row["discord_id"],
        nuts_id=row["nuts_id"],
        title=row["title"],
        type=row["type"],
        value=row["value"],
        status=row["status"],
        what=row["what"],
        idea=row["idea"],
        conclusion=row["conclusion"],
        detail=row["detail"],
        comment=row["comment"],
        tags=json.loads(row["tags"] or "[]"),
        created_at=row["created_at"],
    )


def _row_to_root(row) -> LMRoot:
    return LMRoot(
        id=row["id"],
        discord_id=row["discord_id"],
        nuts_id=row["nuts_id"],
        title=row["title"],
        type=row["type"],
        value=row["value"],
        difficulty=row["difficulty"],
        tags=json.loads(row["tags"] or "[]"),
        what=row["what"],
        content=row["content"],
        comment=row["comment"],
        url=row["url"],
        created_at=row["created_at"],
    )


def _row_to_portal(row) -> LMPortal:
    return LMPortal(
        id=row["id"],
        discord_id=row["discord_id"],
        name=row["name"],
        category=row["category"],
        description=row["description"],
        tags=json.loads(row["tags"] or "[]"),
        rating=row["rating"],
        created_at=row["created_at"],
    )


def _row_to_worklog(row) -> LMWorklog:
    return LMWorklog(
        id=row["id"],
        discord_id=row["discord_id"],
        nuts_id=row["nuts_id"],
        name=row["name"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status_snapshot=row["status_snapshot"],
        phase_snapshot=row["phase_snapshot"],
        level_snapshot=row["level_snapshot"],
        deadline_snapshot=row["deadline_snapshot"],
        note=row["note"],
    )


def _row_to_resource(row) -> LMResource:
    return LMResource(
        id=row["id"],
        discord_id=row["discord_id"],
        name=row["name"],
        type=row["type"],
        tags=json.loads(row["tags"] or "[]"),
        description=row["description"],
        url=row["url"],
        created_at=row["created_at"],
    )


def _row_to_tag(row) -> LMTag:
    return LMTag(
        id=row["id"],
        discord_id=row["discord_id"],
        name=row["name"],
        is_favorite=bool(row["is_favorite"]),
    )


# ======================================================================
# Schema SQL
# ======================================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lm_users (
    discord_id TEXT PRIMARY KEY,
    total_xp REAL DEFAULT 0,
    gacha_tickets INTEGER DEFAULT 0,
    collected_items TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_portals (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    rating REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_nuts (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    portal_id TEXT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT '\u3044\u3064\u304b\u3084\u308b',
    priority TEXT DEFAULT 'medium',
    difficulty INTEGER DEFAULT 1,
    tags TEXT DEFAULT '[]',
    start_date TEXT,
    deadline TEXT,
    icon TEXT,
    image_url TEXT,
    version TEXT,
    public_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_trunks (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    nuts_id TEXT NOT NULL,
    title TEXT NOT NULL,
    type TEXT DEFAULT 'non-issue',
    value INTEGER DEFAULT 1,
    status TEXT DEFAULT 'pending',
    what TEXT DEFAULT '',
    idea TEXT DEFAULT '',
    conclusion TEXT DEFAULT '',
    detail TEXT,
    comment TEXT,
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_leaves (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    nuts_id TEXT,
    trunk_id TEXT,
    title TEXT NOT NULL,
    priority TEXT DEFAULT 'medium',
    difficulty TEXT DEFAULT 'normal',
    started_at TEXT,
    completed_at TEXT,
    actual_hours REAL,
    bonus_hours REAL,
    xp_subtotal REAL,
    memo TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_roots (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    nuts_id TEXT,
    title TEXT NOT NULL,
    type TEXT DEFAULT 'seed',
    value REAL,
    difficulty INTEGER,
    tags TEXT DEFAULT '[]',
    what TEXT DEFAULT '',
    content TEXT DEFAULT '',
    comment TEXT,
    url TEXT,
    created_at TEXT NOT NULL
);

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
    note TEXT
);

CREATE TABLE IF NOT EXISTS lm_resources (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    description TEXT,
    url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lm_tags (
    id TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_favorite INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_lm_nuts_discord ON lm_nuts(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_trunks_discord ON lm_trunks(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_trunks_nuts ON lm_trunks(nuts_id);
CREATE INDEX IF NOT EXISTS idx_lm_leaves_discord ON lm_leaves(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_leaves_nuts ON lm_leaves(nuts_id);
CREATE INDEX IF NOT EXISTS idx_lm_roots_discord ON lm_roots(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_portals_discord ON lm_portals(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_worklogs_discord ON lm_worklogs(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_resources_discord ON lm_resources(discord_id);
CREATE INDEX IF NOT EXISTS idx_lm_tags_discord ON lm_tags(discord_id);
"""
