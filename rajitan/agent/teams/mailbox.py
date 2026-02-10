"""
TeamMailbox — In-memory inter-agent messaging for a single execution.
"""

import time
from typing import List

from rajitan.agent.teams.models import TeamMessage
from rajitan.utils.logger import get_logger

logger = get_logger("agent.teams.mailbox")


class TeamMailbox:
    """In-memory message passing between teammates and leader."""

    def __init__(self):
        self._messages: List[TeamMessage] = []

    def send(self, from_id: str, to_id: str, content: str) -> None:
        """Send a message. to_id can be a teammate_id or 'all' for broadcast."""
        msg = TeamMessage(from_id=from_id, to_id=to_id, content=content)
        self._messages.append(msg)
        logger.debug(f"Mailbox: {from_id} → {to_id}: {content[:60]}...")

    def read(self, teammate_id: str, since: float = 0.0) -> List[TeamMessage]:
        """Read messages addressed to this teammate or 'all', optionally since a timestamp."""
        return [
            m for m in self._messages
            if (m.to_id == teammate_id or m.to_id == "all")
            and m.from_id != teammate_id
            and m.timestamp > since
        ]

    def read_all(self) -> List[TeamMessage]:
        """Read all messages (for leader synthesis)."""
        return list(self._messages)

    @property
    def message_count(self) -> int:
        return len(self._messages)
