"""FastAPI routes for LeveMagi CRUD endpoints"""

import random
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Response, status
from rajitan.web.auth import get_current_user
from rajitan.web.server import app_state
from rajitan.storage.levemagi_client import LeveMagiClient
from rajitan.storage.levemagi_models import (
    LMNutsCreate,
    LMNutsUpdate,
    LMLeafCreate,
    LMTrunkCreate,
    LMTrunkUpdate,
    LMRootCreate,
    LMRootUpdate,
    LMPortalCreate,
    LMPortalUpdate,
    LMResourceCreate,
    LMResourceUpdate,
    LMTagCreate,
    LMState,
)
from rajitan.utils.logger import get_logger

logger = get_logger("web_levemagi")

router = APIRouter(prefix="")


def _get_client() -> LeveMagiClient:
    """Create a LeveMagiClient from app_state."""
    db_client = app_state.get("db_client")
    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not available",
        )
    return LeveMagiClient(db_client.db_path)


# ======================================================================
# State
# ======================================================================


@router.get("/state")
async def get_state(user=Depends(get_current_user)):
    """Get full LeveMagi state for current user"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_full_state(discord_id)


@router.post("/import")
async def import_state(body: LMState, user=Depends(get_current_user)):
    """Import full state from localStorage"""
    discord_id = user["id"]
    client = _get_client()
    return await client.import_state(discord_id, body)


# ======================================================================
# Nuts (Projects)
# ======================================================================


@router.get("/nuts")
async def list_nuts(user=Depends(get_current_user)):
    """List all nuts"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_nuts(discord_id)


@router.post("/nuts", status_code=status.HTTP_201_CREATED)
async def create_nut(body: LMNutsCreate, user=Depends(get_current_user)):
    """Create a nut"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_nuts(discord_id, body)


@router.put("/nuts/{nut_id}")
async def update_nut(nut_id: str, body: LMNutsUpdate, user=Depends(get_current_user)):
    """Update a nut"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.update_nuts(discord_id, nut_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Nut not found")
    return result


@router.delete("/nuts/{nut_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nut(nut_id: str, user=Depends(get_current_user)):
    """Delete a nut (cascade deletes leaves, trunks, roots, worklogs)"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_nuts(discord_id, nut_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nut not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/nuts/{nut_id}/start-work")
async def start_work_on_nut(nut_id: str, user=Depends(get_current_user)):
    """Start work on a nut (creates worklog)"""
    discord_id = user["id"]
    client = _get_client()
    return await client.start_work_on_nuts(discord_id, nut_id)


@router.post("/nuts/{nut_id}/complete")
async def complete_nut(nut_id: str, user=Depends(get_current_user)):
    """Complete a nut"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.complete_nuts(discord_id, nut_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Nut not found")
    return result


# ======================================================================
# Leaves (Tasks)
# ======================================================================


@router.get("/leaves")
async def list_leaves(user=Depends(get_current_user)):
    """List all leaves"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_leaves(discord_id)


@router.post("/leaves", status_code=status.HTTP_201_CREATED)
async def create_leaf(body: LMLeafCreate, user=Depends(get_current_user)):
    """Create a leaf"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_leaf(discord_id, body)


@router.post("/leaves/{leaf_id}/start")
async def start_leaf(leaf_id: str, user=Depends(get_current_user)):
    """Start a leaf"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.start_leaf(discord_id, leaf_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Leaf not found")
    return result


class LeafCompleteRequest(BaseModel):
    actual_hours: float


@router.post("/leaves/{leaf_id}/complete")
async def complete_leaf(
    leaf_id: str, body: LeafCompleteRequest, user=Depends(get_current_user)
):
    """Complete a leaf"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.complete_leaf(discord_id, leaf_id, body.actual_hours)
    if result is None:
        raise HTTPException(status_code=404, detail="Leaf not found")
    return result


@router.delete("/leaves/{leaf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_leaf(leaf_id: str, user=Depends(get_current_user)):
    """Delete a leaf"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_leaf(discord_id, leaf_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Leaf not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# Trunks (Issues)
# ======================================================================


@router.get("/trunks")
async def list_trunks(user=Depends(get_current_user)):
    """List all trunks"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_trunks(discord_id)


@router.post("/trunks", status_code=status.HTTP_201_CREATED)
async def create_trunk(body: LMTrunkCreate, user=Depends(get_current_user)):
    """Create a trunk"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_trunk(discord_id, body)


@router.put("/trunks/{trunk_id}")
async def update_trunk(trunk_id: str, body: LMTrunkUpdate, user=Depends(get_current_user)):
    """Update a trunk"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.update_trunk(discord_id, trunk_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return result


@router.delete("/trunks/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(trunk_id: str, user=Depends(get_current_user)):
    """Delete a trunk"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_trunk(discord_id, trunk_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# Roots (Knowledge)
# ======================================================================


@router.get("/roots")
async def list_roots(user=Depends(get_current_user)):
    """List all roots"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_roots(discord_id)


@router.post("/roots", status_code=status.HTTP_201_CREATED)
async def create_root(body: LMRootCreate, user=Depends(get_current_user)):
    """Create a root"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_root(discord_id, body)


@router.put("/roots/{root_id}")
async def update_root(root_id: str, body: LMRootUpdate, user=Depends(get_current_user)):
    """Update a root"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.update_root(discord_id, root_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Root not found")
    return result


@router.delete("/roots/{root_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_root(root_id: str, user=Depends(get_current_user)):
    """Delete a root"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_root(discord_id, root_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Root not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# Portals
# ======================================================================


@router.get("/portals")
async def list_portals(user=Depends(get_current_user)):
    """List all portals"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_portals(discord_id)


@router.post("/portals", status_code=status.HTTP_201_CREATED)
async def create_portal(body: LMPortalCreate, user=Depends(get_current_user)):
    """Create a portal"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_portal(discord_id, body)


@router.put("/portals/{portal_id}")
async def update_portal(portal_id: str, body: LMPortalUpdate, user=Depends(get_current_user)):
    """Update a portal"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.update_portal(discord_id, portal_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Portal not found")
    return result


@router.delete("/portals/{portal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portal(portal_id: str, user=Depends(get_current_user)):
    """Delete a portal"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_portal(discord_id, portal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Portal not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# Resources
# ======================================================================


@router.get("/resources")
async def list_resources(user=Depends(get_current_user)):
    """List all resources"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_resources(discord_id)


@router.post("/resources", status_code=status.HTTP_201_CREATED)
async def create_resource(body: LMResourceCreate, user=Depends(get_current_user)):
    """Create a resource"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_resource(discord_id, body)


@router.put("/resources/{resource_id}")
async def update_resource(resource_id: str, body: LMResourceUpdate, user=Depends(get_current_user)):
    """Update a resource"""
    discord_id = user["id"]
    client = _get_client()
    result = await client.update_resource(discord_id, resource_id, body)
    if result is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return result


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: str, user=Depends(get_current_user)):
    """Delete a resource"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_resource(discord_id, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Resource not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# Tags
# ======================================================================


@router.get("/tags")
async def list_tags(user=Depends(get_current_user)):
    """List all tags"""
    discord_id = user["id"]
    client = _get_client()
    return await client.get_all_tags(discord_id)


@router.post("/tags", status_code=status.HTTP_201_CREATED)
async def create_tag(body: LMTagCreate, user=Depends(get_current_user)):
    """Create a tag"""
    discord_id = user["id"]
    client = _get_client()
    return await client.create_tag(discord_id, body)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: str, user=Depends(get_current_user)):
    """Delete a tag"""
    discord_id = user["id"]
    client = _get_client()
    deleted = await client.delete_tag(discord_id, tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ======================================================================
# User
# ======================================================================


@router.get("/user")
async def get_user(user=Depends(get_current_user)):
    """Get user data (XP, level, gacha)"""
    discord_id = user["id"]
    client = _get_client()
    lm_user = await client.get_or_create_user(discord_id)
    # Compute level from XP (100 XP per level)
    level = int(lm_user.total_xp // 100) + 1
    return {
        "discord_id": lm_user.discord_id,
        "total_xp": lm_user.total_xp,
        "level": level,
        "gacha_tickets": lm_user.gacha_tickets,
        "collected_items": lm_user.collected_items,
        "created_at": lm_user.created_at,
        "updated_at": lm_user.updated_at,
    }


# Gacha item pools
_GACHA_POOL = {
    "common": [
        {"item_name": "Bronze Seed", "item_type": "badge", "description": "A humble beginning."},
        {"item_name": "Wooden Shield", "item_type": "badge", "description": "Basic protection."},
        {"item_name": "Paper Scroll", "item_type": "badge", "description": "Ancient wisdom."},
    ],
    "rare": [
        {"item_name": "Silver Leaf", "item_type": "badge", "description": "A sign of growth."},
        {"item_name": "Crystal Shard", "item_type": "badge", "description": "Shimmering potential."},
    ],
    "epic": [
        {"item_name": "Golden Nut", "item_type": "badge", "description": "The fruit of hard work."},
        {"item_name": "Dragon Scale", "item_type": "badge", "description": "Legendary material."},
    ],
    "legendary": [
        {"item_name": "World Tree Seed", "item_type": "badge", "description": "The seed of creation itself."},
    ],
}


@router.post("/user/gacha")
async def do_gacha(user=Depends(get_current_user)):
    """Do gacha (consumes one ticket)"""
    discord_id = user["id"]
    client = _get_client()

    # Consume ticket
    consumed = await client.consume_gacha_ticket(discord_id)
    if not consumed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No gacha tickets available",
        )

    # Determine rarity
    roll = random.random()
    if roll < 0.01:
        rarity = "legendary"
    elif roll < 0.10:
        rarity = "epic"
    elif roll < 0.35:
        rarity = "rare"
    else:
        rarity = "common"

    item = random.choice(_GACHA_POOL[rarity])
    result = {"rarity": rarity, **item}

    # Record the collected item
    await client.add_collected_item(discord_id, f"{rarity}:{item['item_name']}")

    return result
