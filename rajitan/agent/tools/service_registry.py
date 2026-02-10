"""Service registry for generic tool executor.

Maps string service names to live service instances,
enabling YAML-defined tools to reference services by name.
"""

from typing import Any, Dict, List, Optional

from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.service_registry")


class ServiceRegistry:
    """Maps string service names to live service instances."""

    def __init__(self):
        self._services: Dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        if name in self._services:
            logger.warning(f"Service '{name}' already registered, overwriting")
        self._services[name] = instance
        logger.info(f"Registered service: {name}")

    def get(self, name: str) -> Optional[Any]:
        return self._services.get(name)

    def has(self, name: str) -> bool:
        return name in self._services

    def list_services(self) -> List[str]:
        return list(self._services.keys())

    def __len__(self) -> int:
        return len(self._services)
