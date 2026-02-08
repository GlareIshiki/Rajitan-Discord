"""
3層記憶システムのデータモデル。

Tier 1 (短期): WorkingMemory — チャンネルの現在の状態、待ちアクション
Tier 2 (中期): SessionMemory — 今日のアクション履歴
Tier 3 (長期): LongTermMemory — 永続的な知識
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PendingActionType(str, Enum):
    """エージェントが待っているアクションの種類"""

    QUIZ_ANSWERS = "quiz_answers"
    CONFIRMATION = "confirmation"
    USER_INPUT = "user_input"


@dataclass
class PendingAction:
    """Tier 1: エージェントが待っている具体的なアクション"""

    action_type: PendingActionType
    description: str  # LLMに伝える説明
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingAction":
        return cls(
            action_type=PendingActionType(data["action_type"]),
            description=data["description"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
            expires_at=(
                datetime.fromisoformat(data["expires_at"])
                if data.get("expires_at")
                else None
            ),
        )


@dataclass
class WorkingMemory:
    """Tier 1: チャンネルの現在の状態"""

    channel_id: str
    pending_actions: List[PendingAction] = field(default_factory=list)
    context_notes: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    def has_pending(self) -> bool:
        """期限切れでないアクティブな待ちアクションがあるか"""
        self._cleanup_expired()
        return len(self.pending_actions) > 0

    def _cleanup_expired(self):
        self.pending_actions = [a for a in self.pending_actions if not a.is_expired()]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "pending_actions": [a.to_dict() for a in self.pending_actions],
            "context_notes": self.context_notes,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkingMemory":
        return cls(
            channel_id=data["channel_id"],
            pending_actions=[
                PendingAction.from_dict(a) for a in data.get("pending_actions", [])
            ],
            context_notes=data.get("context_notes", []),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class ActionLogEntry:
    """Tier 2: エージェントが実行したアクション1件"""

    tool_name: str
    summary: str
    channel_id: str
    user_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "summary": self.summary,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionLogEntry":
        return cls(
            tool_name=data["tool_name"],
            summary=data["summary"],
            channel_id=data["channel_id"],
            user_id=data["user_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            success=data.get("success", True),
        )


@dataclass
class SessionMemory:
    """Tier 2: チャンネルの今日のアクション履歴"""

    channel_id: str
    actions: List[ActionLogEntry] = field(default_factory=list)

    def summarize(self, max_entries: int = 5) -> str:
        """直近N件のアクションを1行ずつの要約にする"""
        recent = self.actions[-max_entries:]
        lines = []
        for a in recent:
            time_str = a.timestamp.strftime("%H:%M")
            status = "\u2713" if a.success else "\u2717"
            lines.append(f"[{time_str}] {status} {a.summary}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMemory":
        return cls(
            channel_id=data["channel_id"],
            actions=[ActionLogEntry.from_dict(a) for a in data.get("actions", [])],
        )


@dataclass
class LongTermMemory:
    """Tier 3: 永続的な知識1件"""

    guild_id: str
    category: str  # "user_preference", "channel_trait", "learned_fact"
    key: str
    value: str
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
