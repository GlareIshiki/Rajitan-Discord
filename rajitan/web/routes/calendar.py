"""FastAPI routes for Calendar endpoints

Provides a unified calendar view combining:
- Manual events (lm_calendar_events table)
- LeveMagi deadlines (lm_nuts with deadline field)
- Bot schedules (schedules table with next_execution)
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiosqlite
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Response, status
from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
from rajitan.utils.logger import get_logger

logger = get_logger("web_calendar")

router = APIRouter(tags=["calendar"])


# ======================================================================
# Models
# ======================================================================


class CalendarEventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    start_time: str  # ISO datetime string
    end_time: Optional[str] = None
    event_type: Optional[str] = "manual"
    color: Optional[str] = None
    is_all_day: Optional[bool] = False


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    color: Optional[str] = None
    is_all_day: Optional[bool] = None


class CalendarEvent(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    start_time: str
    end_time: Optional[str] = None
    event_type: str
    source_id: Optional[str] = None
    color: Optional[str] = None
    is_all_day: bool = False


# ======================================================================
# Helpers
# ======================================================================


def _get_db_path() -> str:
    """Get the database path from app_state."""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )
    return db_client.db_path


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO datetime string, tolerating date-only values."""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # Try date-only format
        return datetime.strptime(value, "%Y-%m-%d")


def _row_to_event(row: aiosqlite.Row) -> Dict[str, Any]:
    """Convert a database row to a calendar event dict."""
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "event_type": row["event_type"],
        "source_id": row["source_id"],
        "color": row["color"],
        "is_all_day": bool(row["is_all_day"]),
    }


# ======================================================================
# Endpoints
# ======================================================================


@router.get("/events")
async def get_events(
    user=Depends(get_current_user),
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get unified calendar events within a date range.

    Combines:
    1. Manual events from lm_calendar_events
    2. LeveMagi nut deadlines
    3. Bot schedule next_execution times
    """
    discord_id = user["id"]
    db_path = _get_db_path()

    # Parse date range
    range_from = _parse_datetime(from_date) if from_date else None
    range_to = _parse_datetime(to_date) if to_date else None

    events: List[Dict[str, Any]] = []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # 1. Manual calendar events
        if range_from and range_to:
            cursor = await db.execute(
                """SELECT id, title, description, start_time, end_time,
                          event_type, source_id, color, is_all_day
                   FROM lm_calendar_events
                   WHERE discord_id = ?
                     AND start_time >= ?
                     AND start_time <= ?
                   ORDER BY start_time""",
                (discord_id, range_from.isoformat(), range_to.isoformat()),
            )
        else:
            cursor = await db.execute(
                """SELECT id, title, description, start_time, end_time,
                          event_type, source_id, color, is_all_day
                   FROM lm_calendar_events
                   WHERE discord_id = ?
                   ORDER BY start_time""",
                (discord_id,),
            )
        rows = await cursor.fetchall()
        for row in rows:
            events.append(_row_to_event(row))

        # 2. LeveMagi deadlines (nuts with deadline set)
        if range_from and range_to:
            cursor = await db.execute(
                """SELECT id, name, description, deadline, status
                   FROM lm_nuts
                   WHERE discord_id = ?
                     AND deadline IS NOT NULL
                     AND deadline != ''
                     AND deadline >= ?
                     AND deadline <= ?
                   ORDER BY deadline""",
                (discord_id, range_from.strftime("%Y-%m-%d"), range_to.strftime("%Y-%m-%d")),
            )
        else:
            cursor = await db.execute(
                """SELECT id, name, description, deadline, status
                   FROM lm_nuts
                   WHERE discord_id = ?
                     AND deadline IS NOT NULL
                     AND deadline != ''
                   ORDER BY deadline""",
                (discord_id,),
            )
        rows = await cursor.fetchall()
        for row in rows:
            deadline_str = row["deadline"]
            events.append({
                "id": f"deadline-{row['id']}",
                "title": f"{row['name']}",
                "description": row["description"] or f"({row['status']})",
                "start_time": deadline_str if "T" in deadline_str else f"{deadline_str}T00:00:00",
                "end_time": None,
                "event_type": "deadline",
                "source_id": row["id"],
                "color": "#ef4444",  # red
                "is_all_day": True,
            })

        # 3. Bot schedules (next_execution within range)
        if range_from and range_to:
            cursor = await db.execute(
                """SELECT id, schedule_type, function_type, next_execution,
                          hour, minute, pattern_type
                   FROM schedules
                   WHERE is_active = 1
                     AND next_execution IS NOT NULL
                     AND next_execution >= ?
                     AND next_execution <= ?
                   ORDER BY next_execution""",
                (range_from.isoformat(), range_to.isoformat()),
            )
        else:
            cursor = await db.execute(
                """SELECT id, schedule_type, function_type, next_execution,
                          hour, minute, pattern_type
                   FROM schedules
                   WHERE is_active = 1
                     AND next_execution IS NOT NULL
                   ORDER BY next_execution""",
            )
        rows = await cursor.fetchall()
        for row in rows:
            func_type = row["function_type"] or row["schedule_type"]
            pattern = row["pattern_type"] or ""
            time_str = ""
            if row["hour"] is not None and row["minute"] is not None:
                time_str = f" ({row['hour']:02d}:{row['minute']:02d})"

            events.append({
                "id": f"schedule-{row['id']}",
                "title": f"{func_type}{time_str}",
                "description": f"{pattern}",
                "start_time": row["next_execution"],
                "end_time": None,
                "event_type": "schedule",
                "source_id": str(row["id"]),
                "color": "#3b82f6",  # blue
                "is_all_day": False,
            })

    # Sort all events by start_time
    events.sort(key=lambda e: e["start_time"] or "")

    return events


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: CalendarEventCreate,
    user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a manual calendar event."""
    discord_id = user["id"]
    db_path = _get_db_path()
    event_id = str(uuid.uuid4())[:8]

    # Validate start_time
    _parse_datetime(body.start_time)
    if body.end_time:
        _parse_datetime(body.end_time)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO lm_calendar_events
               (id, discord_id, title, description, start_time, end_time,
                event_type, color, is_all_day)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                discord_id,
                body.title,
                body.description,
                body.start_time,
                body.end_time,
                body.event_type or "manual",
                body.color,
                body.is_all_day or False,
            ),
        )
        await db.commit()

        cursor = await db.execute(
            """SELECT id, title, description, start_time, end_time,
                      event_type, source_id, color, is_all_day
               FROM lm_calendar_events WHERE id = ?""",
            (event_id,),
        )
        row = await cursor.fetchone()
        return _row_to_event(row)


@router.put("/events/{event_id}")
async def update_event(
    event_id: str,
    body: CalendarEventUpdate,
    user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Update a manual calendar event. Only manual events can be updated."""
    discord_id = user["id"]
    db_path = _get_db_path()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Check event exists and is manual
        cursor = await db.execute(
            """SELECT id, event_type FROM lm_calendar_events
               WHERE id = ? AND discord_id = ?""",
            (event_id, discord_id),
        )
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Event not found")
        if existing["event_type"] != "manual":
            raise HTTPException(
                status_code=400,
                detail="Only manual events can be updated",
            )

        # Build update fields
        fields = {}
        if body.title is not None:
            fields["title"] = body.title
        if body.description is not None:
            fields["description"] = body.description
        if body.start_time is not None:
            _parse_datetime(body.start_time)
            fields["start_time"] = body.start_time
        if body.end_time is not None:
            _parse_datetime(body.end_time)
            fields["end_time"] = body.end_time
        if body.color is not None:
            fields["color"] = body.color
        if body.is_all_day is not None:
            fields["is_all_day"] = body.is_all_day

        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [event_id, discord_id]
        await db.execute(
            f"UPDATE lm_calendar_events SET {set_clause} WHERE id = ? AND discord_id = ?",
            values,
        )
        await db.commit()

        cursor = await db.execute(
            """SELECT id, title, description, start_time, end_time,
                      event_type, source_id, color, is_all_day
               FROM lm_calendar_events WHERE id = ?""",
            (event_id,),
        )
        row = await cursor.fetchone()
        return _row_to_event(row)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    user=Depends(get_current_user),
):
    """Delete a manual calendar event. Only manual events can be deleted."""
    discord_id = user["id"]
    db_path = _get_db_path()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Check event exists and is manual
        cursor = await db.execute(
            """SELECT id, event_type FROM lm_calendar_events
               WHERE id = ? AND discord_id = ?""",
            (event_id, discord_id),
        )
        existing = await cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Event not found")
        if existing["event_type"] != "manual":
            raise HTTPException(
                status_code=400,
                detail="Only manual events can be deleted",
            )

        await db.execute(
            "DELETE FROM lm_calendar_events WHERE id = ? AND discord_id = ?",
            (event_id, discord_id),
        )
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
