"""
Agent Teams data models — role definitions, tasks, messages, results.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TeamRole:
    """Defines a teammate's specialization."""
    role_id: str
    display_name: str
    expertise: str
    allowed_tools: List[str]
    max_steps: int = 8


@dataclass
class TeamTask:
    """A single task in the dependency graph."""
    task_id: str
    description: str
    assigned_role: str
    status: str = "pending"  # pending / in_progress / completed / failed
    claimed_by: Optional[str] = None
    blocks: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    steps_taken: int = 0
    total_tokens: int = 0
    wave: int = 0


@dataclass
class TeamMessage:
    """Inter-agent message."""
    from_id: str
    to_id: str  # teammate_id or "all"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class TeamPlan:
    """Complete plan produced by the leader."""
    should_use_teams: bool
    reasoning: str = ""
    roles: List[TeamRole] = field(default_factory=list)
    tasks: List[TeamTask] = field(default_factory=list)


@dataclass
class TeammateResult:
    """Result from a teammate's execution of one task."""
    teammate_id: str
    task_id: str
    role_id: str
    success: bool
    data: str = ""
    tools_used: List[str] = field(default_factory=list)
    steps_taken: int = 0
    total_tokens: int = 0
    error: Optional[str] = None


@dataclass
class AgentTeamsResult:
    """Final result from Agent Teams execution."""
    used_teams: bool
    response: Optional[str] = None
    teammate_results: List[TeammateResult] = field(default_factory=list)
    total_tokens: int = 0
    plan_reasoning: str = ""
    waves_executed: int = 0
