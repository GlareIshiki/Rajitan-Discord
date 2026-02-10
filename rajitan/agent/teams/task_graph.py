"""
TaskGraph — Dependency-aware task management with wave computation.

Uses Kahn's algorithm for topological ordering. Provides atomic claim/complete
operations via asyncio.Lock for parallel safety.
"""

import asyncio
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set

from rajitan.agent.teams.models import TeamTask
from rajitan.utils.logger import get_logger

logger = get_logger("agent.teams.task_graph")


class CyclicDependencyError(Exception):
    """Raised when the task graph contains a cycle."""


class TaskGraph:
    """Dependency-aware task management with wave computation."""

    def __init__(self, tasks: List[TeamTask]):
        self._tasks: Dict[str, TeamTask] = {t.task_id: t for t in tasks}
        self._lock = asyncio.Lock()
        self._max_wave = 0
        self._compute_waves()

    def _compute_waves(self) -> None:
        """Assign wave numbers using Kahn's algorithm (topological sort).

        Wave 0 = no dependencies, Wave N = max(dependency wave) + 1.
        Raises CyclicDependencyError if a cycle is detected.
        """
        # Build in-degree map and adjacency
        in_degree: Dict[str, int] = {tid: 0 for tid in self._tasks}
        downstream: Dict[str, List[str]] = defaultdict(list)

        for task in self._tasks.values():
            for blocker_id in task.blocked_by:
                if blocker_id in self._tasks:
                    in_degree[task.task_id] += 1
                    downstream[blocker_id].append(task.task_id)

        # Initialize wave 0: tasks with no blockers
        queue: deque = deque()
        wave_of: Dict[str, int] = {}
        for tid, deg in in_degree.items():
            if deg == 0:
                queue.append(tid)
                wave_of[tid] = 0
                self._tasks[tid].wave = 0

        processed = 0
        while queue:
            tid = queue.popleft()
            processed += 1
            for child_id in downstream[tid]:
                in_degree[child_id] -= 1
                child_wave = wave_of[tid] + 1
                if child_id in wave_of:
                    child_wave = max(wave_of[child_id], child_wave)
                wave_of[child_id] = child_wave
                if in_degree[child_id] == 0:
                    queue.append(child_id)
                    self._tasks[child_id].wave = wave_of[child_id]

        if processed != len(self._tasks):
            raise CyclicDependencyError(
                f"Cyclic dependency detected: processed {processed}/{len(self._tasks)} tasks"
            )

        self._max_wave = max(wave_of.values()) if wave_of else 0
        logger.info(
            f"TaskGraph: {len(self._tasks)} tasks, {self._max_wave + 1} waves"
        )

    def get_wave_tasks(self, wave: int) -> List[TeamTask]:
        """Get all tasks in a specific wave."""
        return [t for t in self._tasks.values() if t.wave == wave]

    def get_max_wave(self) -> int:
        """Get the highest wave number."""
        return self._max_wave

    async def claim_task(self, task_id: str, teammate_id: str) -> bool:
        """Atomically claim a pending task. Returns False if already claimed."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != "pending":
                return False
            # Verify all blockers are completed
            for blocker_id in task.blocked_by:
                blocker = self._tasks.get(blocker_id)
                if blocker and blocker.status != "completed":
                    return False
            task.status = "in_progress"
            task.claimed_by = teammate_id
            return True

    async def get_claimable(self, role_id: Optional[str] = None) -> List[TeamTask]:
        """Get tasks that are pending and have all blockers completed."""
        async with self._lock:
            result = []
            for task in self._tasks.values():
                if task.status != "pending":
                    continue
                if role_id and task.assigned_role != role_id:
                    continue
                all_resolved = all(
                    self._tasks[bid].status == "completed"
                    for bid in task.blocked_by
                    if bid in self._tasks
                )
                if all_resolved:
                    result.append(task)
            return result

    async def complete_task(self, task_id: str, result: str) -> List[str]:
        """Mark task completed and return newly unblocked task_ids."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return []
            task.status = "completed"
            task.result = result

            # Find newly unblocked tasks
            unblocked = []
            for candidate in self._tasks.values():
                if candidate.status != "pending":
                    continue
                if task_id not in candidate.blocked_by:
                    continue
                all_resolved = all(
                    self._tasks[bid].status == "completed"
                    for bid in candidate.blocked_by
                    if bid in self._tasks
                )
                if all_resolved:
                    unblocked.append(candidate.task_id)
            return unblocked

    async def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = "failed"
                task.error = error

    def get_upstream_results(self, task_id: str) -> Dict[str, str]:
        """Get results from all upstream (blocked_by) tasks."""
        task = self._tasks.get(task_id)
        if not task:
            return {}
        results = {}
        for bid in task.blocked_by:
            blocker = self._tasks.get(bid)
            if blocker and blocker.result:
                results[bid] = blocker.result
        return results

    def get_task(self, task_id: str) -> Optional[TeamTask]:
        return self._tasks.get(task_id)

    def all_done(self) -> bool:
        """True if all tasks are completed or failed."""
        return all(
            t.status in ("completed", "failed") for t in self._tasks.values()
        )

    @property
    def tasks(self) -> Dict[str, TeamTask]:
        return self._tasks
