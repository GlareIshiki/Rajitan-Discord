"""
ExecutionLogCollector — エージェント実行ログの収集とストリーム配信。

orchestrator.py からイベントを受け取り、メモリに保持。
WebSocket経由でリアルタイム配信も行う。
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from rajitan.utils.logger import get_logger

logger = get_logger("agent.workflow.execution_log")


@dataclass
class ExecutionEvent:
    """単一の実行イベント"""
    event_type: str  # start, step, tool_call, tool_result, final, error
    timestamp: float = field(default_factory=time.time)
    execution_id: str = ""
    guild_id: str = ""
    channel_id: str = ""
    user_id: str = ""
    step: Optional[int] = None
    max_steps: Optional[int] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_success: Optional[bool] = None
    content: Optional[str] = None
    tokens: Optional[int] = None
    thinking: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "execution_id": self.execution_id,
        }
        for key in (
            "guild_id", "channel_id", "user_id", "step", "max_steps",
            "tool_name", "tool_args", "tool_success", "content", "tokens", "thinking",
        ):
            val = getattr(self, key)
            if val is not None:
                d[key] = val
        return d


class ExecutionLogCollector:
    """イベント収集 + WebSocketストリーム配信"""

    def __init__(self, max_events: int = 1000):
        self._events: deque[ExecutionEvent] = deque(maxlen=max_events)
        self._subscribers: List[asyncio.Queue] = []
        self._execution_counter = 0

    def new_execution_id(self) -> str:
        """新しい実行IDを生成"""
        self._execution_counter += 1
        return f"exec-{int(time.time())}-{self._execution_counter}"

    async def emit(self, event: ExecutionEvent) -> None:
        """イベントを記録し、全サブスクライバーに配信"""
        self._events.append(event)

        # Non-blocking broadcast to subscribers
        dead = []
        for i, queue in enumerate(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(i)

        # Remove dead subscribers
        for i in reversed(dead):
            self._subscribers.pop(i)

    def subscribe(self) -> asyncio.Queue:
        """新しいサブスクライバーを追加。Queueを返す。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """サブスクライバーを削除"""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """直近のイベントを取得"""
        events = list(self._events)[-limit:]
        return [e.to_dict() for e in events]

    def get_executions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """直近の実行サマリーを取得（startイベント基準）"""
        starts = [e for e in self._events if e.event_type == "start"]
        recent = starts[-limit:]

        summaries = []
        for start in recent:
            exec_id = start.execution_id
            related = [e for e in self._events if e.execution_id == exec_id]
            final = next((e for e in related if e.event_type == "final"), None)
            error = next((e for e in related if e.event_type == "error"), None)
            tools = [e.tool_name for e in related if e.event_type == "tool_call" and e.tool_name]

            summaries.append({
                "execution_id": exec_id,
                "timestamp": start.timestamp,
                "guild_id": start.guild_id,
                "user_id": start.user_id,
                "content_preview": (start.content or "")[:100],
                "steps": max((e.step or 0 for e in related), default=0),
                "tools_used": tools,
                "success": final is not None,
                "error": error.content if error else None,
                "total_tokens": final.tokens if final else None,
            })

        return summaries
