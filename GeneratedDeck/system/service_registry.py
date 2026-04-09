from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ServiceAccessPolicy:
    name: str
    provider: Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}

    def subscribe(self, event_name: str, callback: Callable[[Any], None]) -> None:
        self._subscribers.setdefault(event_name, []).append(callback)

    def publish(self, event_name: str, payload: Any) -> None:
        for callback in self._subscribers.get(event_name, []):
            callback(payload)


class ServiceRegistry:
    def __init__(self, diagnostics_logger) -> None:
        self._services: dict[str, ServiceAccessPolicy] = {}
        self.diagnostics_logger = diagnostics_logger
        self.event_bus = EventBus()

    def register_service(self, service_name: str, provider: Any) -> None:
        self._services[service_name] = ServiceAccessPolicy(service_name, provider)
        self.diagnostics_logger.info(f"Service registered: {service_name}")

    def has_service(self, service_name: str) -> bool:
        return service_name in self._services

    def get_service(self, service_name: str) -> Any:
        if service_name not in self._services:
            raise KeyError(f"Service unavailable: {service_name}")
        return self._services[service_name].provider

    def request_services(self, required: list[str], optional: list[str] | None = None) -> dict[str, Any]:
        optional = optional or []
        granted: dict[str, Any] = {}
        for name in required:
            granted[name] = self.get_service(name)
        for name in optional:
            if self.has_service(name):
                granted[name] = self.get_service(name)
        return granted
