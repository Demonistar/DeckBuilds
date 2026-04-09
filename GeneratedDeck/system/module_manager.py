from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


REQUIRED_MANIFEST_FIELDS = {
    "module_name",
    "module_id",
    "version",
    "primary_category",
    "secondary_categories",
    "deck_version_compatibility",
    "entry_point",
    "required_services",
    "optional_services",
    "entitlement_token",
}


@dataclass
class ModuleInfo:
    manifest: dict[str, Any]
    module_path: Path
    is_enabled: bool = True


class ModuleManager:
    def __init__(
        self,
        deck_version: str,
        modules_path: Path,
        service_registry,
        category_manager,
        diagnostics,
        settings_manager,
    ) -> None:
        self.deck_version = deck_version
        self.modules_path = modules_path
        self.service_registry = service_registry
        self.category_manager = category_manager
        self.diagnostics = diagnostics
        self.settings_manager = settings_manager
        self._registered: dict[str, ModuleInfo] = {}
        self._non_removable: set[str] = set()

    def mark_module_non_removable(self, module_id: str) -> None:
        self._non_removable.add(module_id)

    def enabled_modules(self) -> list[ModuleInfo]:
        return [m for m in self._registered.values() if m.is_enabled]

    def reload_modules(self) -> None:
        self.diagnostics.info("Reloading modules")
        for module_file in self.discover_module_files():
            try:
                self._load_and_register_module(module_file)
            except Exception as exc:
                self.diagnostics.error(f"Failed module load for {module_file.name}: {exc}")

    def discover_module_files(self) -> list[Path]:
        self.modules_path.mkdir(parents=True, exist_ok=True)
        return sorted(
            [path for path in self.modules_path.iterdir() if path.suffix == ".py" and path.is_file()]
        )

    def _load_and_register_module(self, module_file: Path) -> None:
        py_module = self._import_module_from_path(module_file)
        manifest = getattr(py_module, "MANIFEST", None)
        if not isinstance(manifest, dict):
            raise ValueError("MANIFEST missing or not dict")

        self._validate_manifest(manifest)
        self.validate_module_entitlement(manifest)
        self._validate_compatibility(manifest)
        self._validate_required_services(manifest)

        module_id = manifest["module_id"]
        enabled = self.settings_manager.is_module_enabled(module_id)
        module_info = ModuleInfo(manifest=manifest, module_path=module_file, is_enabled=enabled)
        self._registered[module_id] = module_info

        if enabled:
            self._activate_module(py_module, manifest)

    def _activate_module(self, py_module: ModuleType, manifest: dict[str, Any]) -> None:
        entry_point_name = manifest["entry_point"]
        entry_fn = getattr(py_module, entry_point_name, None)
        if entry_fn is None:
            raise ValueError(f"Entry point not found: {entry_point_name}")

        services = self.service_registry.request_services(
            required=manifest.get("required_services", []),
            optional=manifest.get("optional_services", []),
        )
        registration = entry_fn(services)
        self._process_registration(manifest, registration)

    def _process_registration(self, manifest: dict[str, Any], registration: dict[str, Any]) -> None:
        if not isinstance(registration, dict):
            raise ValueError("Registration object must be dict")
        widget = registration.get("widget")
        if widget is None:
            raise ValueError("Registration missing 'widget'")

        ui_registrar = self.service_registry.get_service("ui_registration")
        ui_registrar.register_module_ui(
            module_id=manifest["module_id"],
            module_name=manifest["module_name"],
            widget=widget,
            category=manifest["primary_category"],
        )

    def disable_module(self, module_id: str) -> None:
        if module_id in self._non_removable:
            raise ValueError("Cannot disable built-in module")

        module = self._registered.get(module_id)
        if not module:
            raise ValueError("Module not registered")

        module.is_enabled = False
        self.settings_manager.set_module_enabled(module_id, False)
        self.service_registry.get_service("ui_registration").remove_module_ui(module_id)

    def enable_module(self, module_id: str) -> None:
        module = self._registered.get(module_id)
        if not module:
            raise ValueError("Module not registered")

        module.is_enabled = True
        self.settings_manager.set_module_enabled(module_id, True)
        self._load_and_register_module(module.module_path)

    def uninstall_module(self, module_id: str, delete_file: bool = False) -> None:
        if module_id in self._non_removable:
            raise ValueError("Cannot uninstall built-in module")
        module = self._registered.pop(module_id, None)
        if not module:
            raise ValueError("Module not registered")

        self.service_registry.get_service("ui_registration").remove_module_ui(module_id)
        if delete_file and module.module_path.exists():
            os.remove(module.module_path)

    def validate_module_entitlement(self, manifest: dict[str, Any]) -> bool:
        token = manifest.get("entitlement_token", "")
        self.diagnostics.info(
            f"Entitlement hook invoked for {manifest.get('module_id', 'unknown')} token='{token}'"
        )
        return True

    def _import_module_from_path(self, module_path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to import module: {module_path}")
        py_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(py_module)
        return py_module

    def _validate_manifest(self, manifest: dict[str, Any]) -> None:
        missing = REQUIRED_MANIFEST_FIELDS - set(manifest.keys())
        if missing:
            raise ValueError(f"Manifest missing fields: {sorted(missing)}")
        if not isinstance(manifest["secondary_categories"], list):
            raise ValueError("secondary_categories must be a list")

    def _validate_compatibility(self, manifest: dict[str, Any]) -> None:
        compatibility = manifest["deck_version_compatibility"]
        if compatibility not in ("*", self.deck_version):
            raise ValueError(
                f"Incompatible module version. deck={self.deck_version} module={compatibility}"
            )

    def _validate_required_services(self, manifest: dict[str, Any]) -> None:
        missing = [
            name
            for name in manifest.get("required_services", [])
            if not self.service_registry.has_service(name)
        ]
        if missing:
            raise ValueError(f"Required services unavailable: {missing}")
