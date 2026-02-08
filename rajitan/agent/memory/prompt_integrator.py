"""
MemoryPromptIntegrator — 3層の記憶をシステムプロンプト用テキストに変換。

トークン予算を守りながら、最も重要な情報を優先して注入する。
"""

from typing import TYPE_CHECKING, List

from rajitan.utils.logger import get_logger

if TYPE_CHECKING:
    from rajitan.agent.memory.manager import MemoryManager
    from rajitan.agent.orchestrator import AgentContext

logger = get_logger("agent.memory.prompt")

# 予算: ~700トークン ≈ 2100文字（日本語 3文字/token）
MAX_MEMORY_CHARS = 2100


class MemoryPromptIntegrator:
    """3層の記憶をプロンプト用テキストに変換"""

    def __init__(self, memory_manager: "MemoryManager"):
        self.memory = memory_manager

    async def build_memory_section(self, context: "AgentContext") -> str:
        """3層の記憶をまとめてプロンプト用テキストを生成"""
        parts: List[str] = []
        chars_used = 0

        # Tier 1: ワーキングメモリ（最優先、常に全量含める）
        tier1 = await self._build_tier1(context.channel_id)
        if tier1:
            parts.append(tier1)
            chars_used += len(tier1)

        # Tier 2: アクションログ（直近5件）
        tier2 = await self._build_tier2(context.channel_id)
        if tier2 and chars_used + len(tier2) <= MAX_MEMORY_CHARS:
            parts.append(tier2)
            chars_used += len(tier2)

        # Tier 3: 長期記憶（残り予算で）
        remaining = MAX_MEMORY_CHARS - chars_used
        if remaining > 100:
            tier3 = await self._build_tier3(context, remaining)
            if tier3:
                parts.append(tier3)

        if not parts:
            return ""

        return "## 記憶\n\n" + "\n\n".join(parts)

    async def _build_tier1(self, channel_id: str) -> str:
        """Tier 1: 現在の状態"""
        wm = await self.memory.get_working_memory(channel_id)

        lines: List[str] = []
        for action in wm.pending_actions:
            if not action.is_expired():
                lines.append(f"- \u23f3 {action.description}")

        for note in wm.context_notes[-3:]:
            lines.append(f"- \u30e1\u30e2: {note}")

        if not lines:
            return ""

        return "### \u73fe\u5728\u306e\u72b6\u614b\uff08\u30ef\u30fc\u30ad\u30f3\u30b0\u30e1\u30e2\u30ea\uff09\n" + "\n".join(lines)

    async def _build_tier2(self, channel_id: str) -> str:
        """Tier 2: 今日のアクション履歴"""
        session = await self.memory.get_session_memory(channel_id)

        if not session.actions:
            return ""

        summary = session.summarize(max_entries=5)
        return f"### \u4eca\u65e5\u306e\u30a2\u30af\u30b7\u30e7\u30f3\u5c65\u6b74\n{summary}"

    async def _build_tier3(self, context: "AgentContext", max_chars: int) -> str:
        """Tier 3: 長期記憶"""
        memories = await self.memory.recall(
            guild_id=context.guild_id,
            user_id=context.user_id,
            limit=5,
        )
        # チャンネル固有の記憶も取得
        channel_memories = await self.memory.recall(
            guild_id=context.guild_id,
            channel_id=context.channel_id,
            limit=3,
        )

        # 重複除去（keyベース）
        seen_keys = set()
        all_memories = []
        for m in memories + channel_memories:
            mkey = (m.category, m.key)
            if mkey not in seen_keys:
                seen_keys.add(mkey)
                all_memories.append(m)

        if not all_memories:
            return ""

        lines: List[str] = []
        chars = 0
        for m in all_memories:
            line = f"- {m.value}"
            if chars + len(line) > max_chars:
                break
            lines.append(line)
            chars += len(line)

        if not lines:
            return ""

        return "### \u77e5\u3063\u3066\u3044\u308b\u3053\u3068\n" + "\n".join(lines)
