from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SettingsManager:
    def __init__(self, system_path: Path) -> None:
        self.system_path = system_path
        self.settings_path = self.system_path / "settings.json"
        self._settings: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.settings_path.exists():
            self._settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        else:
            self._settings = {}

    def _save(self) -> None:
        self.settings_path.write_text(
            json.dumps(self._settings, indent=2, sort_keys=True), encoding="utf-8"
        )

    def get_value(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_value(self, key: str, value: Any) -> None:
        self._settings[key] = value
        self._save()

    def is_module_enabled(self, module_id: str) -> bool:
        modules = self._settings.get("modules", {})
        return modules.get(module_id, True)

    def set_module_enabled(self, module_id: str, enabled: bool) -> None:
        modules = self._settings.setdefault("modules", {})
        modules[module_id] = enabled
        self._save()
