"""LeveMagi Pydantic models - mirrors the TypeScript types.ts"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


# ============================================================
# Core Models
# ============================================================

class LMUser(BaseModel):
    """LeveMagi user profile"""
    discord_id: str
    total_xp: float = 0.0
    gacha_tickets: int = 0
    collected_items: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class LMPortal(BaseModel):
    """Portal - a category/workspace grouping nuts"""
    id: str
    discord_id: str
    name: str
    category: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    rating: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LMNuts(BaseModel):
    """Nuts - a project or task container"""
    id: str
    discord_id: str
    portal_id: Optional[str] = None
    name: str
    description: str = ""
    status: str = "いつかやる"
    priority: str = "medium"
    difficulty: int = Field(default=1, ge=1, le=10)
    tags: List[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    deadline: Optional[str] = None
    icon: Optional[str] = None
    image_url: Optional[str] = None
    version: Optional[str] = None
    public_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LMTrunk(BaseModel):
    """Trunk - a branch of work within a nuts"""
    id: str
    discord_id: str
    nuts_id: str
    title: str
    type: Literal["non-issue", "issue"] = "non-issue"
    value: int = Field(default=1, ge=1, le=3)
    status: Literal["pending", "in_progress", "done"] = "pending"
    what: str = ""
    idea: str = ""
    conclusion: str = ""
    detail: Optional[str] = None
    comment: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class LMLeaf(BaseModel):
    """Leaf - an individual work session or task"""
    id: str
    discord_id: str
    nuts_id: Optional[str] = None
    trunk_id: Optional[str] = None
    title: str
    priority: str = "medium"
    difficulty: Literal["easy", "normal", "hard"] = "normal"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    actual_hours: Optional[float] = None
    bonus_hours: Optional[float] = None
    xp_subtotal: Optional[float] = None
    memo: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LMRoot(BaseModel):
    """Root - knowledge, reference, or seed idea"""
    id: str
    discord_id: str
    nuts_id: Optional[str] = None
    title: str
    type: Literal["seed", "knowledge", "guide", "column", "archive"] = "seed"
    value: Optional[float] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=3)
    tags: List[str] = Field(default_factory=list)
    what: str = ""
    content: str = ""
    comment: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LMWorklog(BaseModel):
    """Worklog - a work session record"""
    id: str
    discord_id: str
    nuts_id: str
    name: str
    started_at: str
    completed_at: Optional[str] = None
    status_snapshot: Optional[str] = None
    phase_snapshot: Optional[str] = None
    level_snapshot: Optional[int] = None
    deadline_snapshot: Optional[str] = None
    note: Optional[str] = None


class LMResource(BaseModel):
    """Resource - an external resource reference"""
    id: str
    discord_id: str
    name: str
    type: str
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LMTag(BaseModel):
    """Tag - user-defined label"""
    id: str
    discord_id: str
    name: str
    is_favorite: bool = False


# ============================================================
# Aggregate State
# ============================================================

class LMState(BaseModel):
    """Full LeveMagi state for a user"""
    nuts: List[LMNuts] = Field(default_factory=list)
    trunks: List[LMTrunk] = Field(default_factory=list)
    leaves: List[LMLeaf] = Field(default_factory=list)
    roots: List[LMRoot] = Field(default_factory=list)
    portals: List[LMPortal] = Field(default_factory=list)
    worklogs: List[LMWorklog] = Field(default_factory=list)
    resources: List[LMResource] = Field(default_factory=list)
    tags: List[LMTag] = Field(default_factory=list)
    user_data: LMUser


# ============================================================
# Create Schemas (no id, no discord_id)
# ============================================================

class LMNutsCreate(BaseModel):
    """Schema for creating a new Nuts"""
    id: Optional[str] = None
    portal_id: Optional[str] = None
    name: str
    description: str = ""
    status: str = "いつかやる"
    priority: str = "medium"
    difficulty: int = Field(default=1, ge=1, le=10)
    tags: List[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    deadline: Optional[str] = None
    icon: Optional[str] = None
    image_url: Optional[str] = None
    version: Optional[str] = None
    public_url: Optional[str] = None


class LMTrunkCreate(BaseModel):
    """Schema for creating a new Trunk"""
    id: Optional[str] = None
    nuts_id: str
    title: str
    type: Literal["non-issue", "issue"] = "non-issue"
    value: int = Field(default=1, ge=1, le=3)
    status: Literal["pending", "in_progress", "done"] = "pending"
    what: str = ""
    idea: str = ""
    conclusion: str = ""
    detail: Optional[str] = None
    comment: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class LMLeafCreate(BaseModel):
    """Schema for creating a new Leaf"""
    id: Optional[str] = None
    nuts_id: Optional[str] = None
    trunk_id: Optional[str] = None
    title: str
    priority: str = "medium"
    difficulty: Literal["easy", "normal", "hard"] = "normal"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    actual_hours: Optional[float] = None
    bonus_hours: Optional[float] = None
    xp_subtotal: Optional[float] = None
    memo: Optional[str] = None


class LMRootCreate(BaseModel):
    """Schema for creating a new Root"""
    id: Optional[str] = None
    nuts_id: Optional[str] = None
    title: str
    type: Literal["seed", "knowledge", "guide", "column", "archive"] = "seed"
    value: Optional[float] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=3)
    tags: List[str] = Field(default_factory=list)
    what: str = ""
    content: str = ""
    comment: Optional[str] = None
    url: Optional[str] = None


class LMPortalCreate(BaseModel):
    """Schema for creating a new Portal"""
    id: Optional[str] = None
    name: str
    category: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    rating: Optional[float] = None


class LMWorklogCreate(BaseModel):
    """Schema for creating a new Worklog"""
    id: Optional[str] = None
    nuts_id: str
    name: str
    started_at: str
    completed_at: Optional[str] = None
    status_snapshot: Optional[str] = None
    phase_snapshot: Optional[str] = None
    level_snapshot: Optional[int] = None
    deadline_snapshot: Optional[str] = None
    note: Optional[str] = None


class LMResourceCreate(BaseModel):
    """Schema for creating a new Resource"""
    id: Optional[str] = None
    name: str
    type: str
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    url: Optional[str] = None


class LMTagCreate(BaseModel):
    """Schema for creating a new Tag"""
    id: Optional[str] = None
    name: str
    is_favorite: bool = False


# ============================================================
# Update Schemas (all fields optional)
# ============================================================

class LMNutsUpdate(BaseModel):
    """Schema for updating a Nuts"""
    portal_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=10)
    tags: Optional[List[str]] = None
    start_date: Optional[str] = None
    deadline: Optional[str] = None
    icon: Optional[str] = None
    image_url: Optional[str] = None
    version: Optional[str] = None
    public_url: Optional[str] = None


class LMTrunkUpdate(BaseModel):
    """Schema for updating a Trunk"""
    title: Optional[str] = None
    type: Optional[Literal["non-issue", "issue"]] = None
    value: Optional[int] = Field(default=None, ge=1, le=3)
    status: Optional[Literal["pending", "in_progress", "done"]] = None
    what: Optional[str] = None
    idea: Optional[str] = None
    conclusion: Optional[str] = None
    detail: Optional[str] = None
    comment: Optional[str] = None
    tags: Optional[List[str]] = None


class LMLeafUpdate(BaseModel):
    """Schema for updating a Leaf"""
    nuts_id: Optional[str] = None
    trunk_id: Optional[str] = None
    title: Optional[str] = None
    priority: Optional[str] = None
    difficulty: Optional[Literal["easy", "normal", "hard"]] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    actual_hours: Optional[float] = None
    bonus_hours: Optional[float] = None
    xp_subtotal: Optional[float] = None
    memo: Optional[str] = None


class LMRootUpdate(BaseModel):
    """Schema for updating a Root"""
    nuts_id: Optional[str] = None
    title: Optional[str] = None
    type: Optional[Literal["seed", "knowledge", "guide", "column", "archive"]] = None
    value: Optional[float] = None
    difficulty: Optional[int] = Field(default=None, ge=1, le=3)
    tags: Optional[List[str]] = None
    what: Optional[str] = None
    content: Optional[str] = None
    comment: Optional[str] = None
    url: Optional[str] = None


class LMPortalUpdate(BaseModel):
    """Schema for updating a Portal"""
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    rating: Optional[float] = None


class LMWorklogUpdate(BaseModel):
    """Schema for updating a Worklog"""
    name: Optional[str] = None
    completed_at: Optional[str] = None
    status_snapshot: Optional[str] = None
    phase_snapshot: Optional[str] = None
    level_snapshot: Optional[int] = None
    deadline_snapshot: Optional[str] = None
    note: Optional[str] = None


class LMResourceUpdate(BaseModel):
    """Schema for updating a Resource"""
    name: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    url: Optional[str] = None


class LMTagUpdate(BaseModel):
    """Schema for updating a Tag"""
    name: Optional[str] = None
    is_favorite: Optional[bool] = None
