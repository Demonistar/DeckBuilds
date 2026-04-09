#!/usr/bin/env python3
"""Builds a fresh modular Deck runtime scaffold.

This builder generates a standalone runtime with dynamic module discovery,
category organization, a service registry, persona isolation, and startup
AI validation architecture.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


DECK_VERSION = "0.1.0"


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def build_generated_deck(base_dir: Path) -> Path:
    generated_root = base_dir / "GeneratedDeck"
    system_dir = generated_root / "system"
    modules_dir = generated_root / "Modules"

    generated_root.mkdir(parents=True, exist_ok=True)
    system_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    write_file(generated_root / "deck_runtime.py", DECK_RUNTIME)
    write_file(system_dir / "module_manager.py", MODULE_MANAGER)
    write_file(system_dir / "category_manager.py", CATEGORY_MANAGER)
    write_file(system_dir / "service_registry.py", SERVICE_REGISTRY)
    write_file(system_dir / "persona_system.py", PERSONA_SYSTEM)
    write_file(system_dir / "ai_startup_validator.py", AI_STARTUP_VALIDATOR)
    write_file(system_dir / "settings_manager.py", SETTINGS_MANAGER)
    write_file(system_dir / "diagnostics.py", DIAGNOSTICS)
    write_file(system_dir / "instruments.py", INSTRUMENTS)
    write_file(system_dir / "identity_store.dat", IDENTITY_STORE)

    return generated_root


DECK_RUNTIME = f'''
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from system.ai_startup_validator import AIStartupValidator
from system.category_manager import CategoryManager
from system.diagnostics import Diagnostics
from system.instruments import Instruments
from system.module_manager import ModuleManager
from system.persona_system import PersonaManager
from system.service_registry import ServiceRegistry
from system.settings_manager import SettingsManager


DECK_VERSION = "{DECK_VERSION}"


class PromptInput(QTextEdit):
    message_submitted = Signal(str)

    def __init__(self, max_visible_lines: int = 6) -> None:
        super().__init__()
        self.max_visible_lines = max_visible_lines
        self.setAcceptRichText(False)
        self.setWordWrapMode(self.wordWrapMode())
        self.setAcceptDrops(True)
        self.setPlaceholderText("Type a message...")
        self.textChanged.connect(self._auto_resize)
        self._auto_resize()

    def _line_height(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _auto_resize(self) -> None:
        doc_height = int(self.document().size().height())
        line_h = self._line_height()
        min_h = line_h + 12
        max_h = line_h * self.max_visible_lines + 12
        new_h = max(min_h, min(doc_height + 8, max_h))
        self.setFixedHeight(new_h)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if doc_height > max_h else Qt.ScrollBarAlwaysOff
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            modifiers = event.modifiers()
            if modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
                cursor = self.textCursor()
                cursor.insertText("\\n")
                self.setTextCursor(cursor)
                return
            message = self.toPlainText().strip()
            if message:
                self.message_submitted.emit(message)
                self.clear()
            return
        super().keyPressEvent(event)


class PromptPanel(QWidget):
    def __init__(self, route_callback) -> None:
        super().__init__()
        self.route_callback = route_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.output = QTextEdit()
        self.output.setReadOnly(True)

        self.input = PromptInput()
        self.token_counter = QLabel("Tokens: 0")

        self.input.message_submitted.connect(self._submit)
        self.input.textChanged.connect(self._update_token_counter)

        layout.addWidget(self.output)
        layout.addWidget(self.input)
        layout.addWidget(self.token_counter)

    def _update_token_counter(self) -> None:
        text = self.input.toPlainText().strip()
        token_count = len(text.split()) if text else 0
        self.token_counter.setText(f"Tokens: {{token_count}}")

    def _submit(self, message: str) -> None:
        self.append_message("You", message)
        self.route_callback(message)

    def append_message(self, sender: str, text: str) -> None:
        self.output.append(f"<b>{{sender}}:</b> {{text}}")
        self.output.moveCursor(QTextCursor.End)

    def send_to_prompt(self, text: str) -> None:
        current = self.input.toPlainText()
        spacer = "\\n" if current else ""
        self.input.setPlainText(current + spacer + text)
        self.input.moveCursor(QTextCursor.End)


class DeckRuntime(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Generated Deck Runtime")
        self.resize(1200, 800)

        self.runtime_root = Path(__file__).resolve().parent
        self.modules_path = self.runtime_root / "Modules"

        self.settings_manager = SettingsManager(self.runtime_root / "system")
        self.diagnostics = Diagnostics()
        self.instruments = Instruments()
        self.service_registry = ServiceRegistry(self.diagnostics)
        self.persona_manager = PersonaManager(self.settings_manager)
        self.category_manager = CategoryManager()
        self.module_manager = ModuleManager(
            deck_version=DECK_VERSION,
            modules_path=self.modules_path,
            service_registry=self.service_registry,
            category_manager=self.category_manager,
            diagnostics=self.diagnostics,
            settings_manager=self.settings_manager,
        )
        self.ai_validator = AIStartupValidator(self.settings_manager)

        self._setup_ui()
        self._register_core_services()
        self._register_built_in_system_modules()

        if not self.ai_validator.ensure_ready(self):
            QMessageBox.warning(
                self,
                "AI Startup",
                "AI initialization is incomplete. Recovery setup was shown.",
            )

        self.refresh_modules()

    def _setup_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.category_scroll = QScrollArea()
        self.category_scroll.setWidgetResizable(True)
        self.category_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.category_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.category_button_host = QWidget()
        self.category_button_layout = QHBoxLayout(self.category_button_host)
        self.category_button_layout.addStretch(1)
        self.category_scroll.setWidget(self.category_button_host)

        self.module_tabs = QTabWidget()

        self.prompt_panel = PromptPanel(self._route_prompt_message)
        self.google_credentials_widget = self._build_google_credentials_ui()
        self.google_credentials_widget.hide()

        controls = QHBoxLayout()
        reload_button = QPushButton("Reload Modules")
        reload_button.clicked.connect(self.refresh_modules)
        controls.addWidget(reload_button)

        root.addWidget(self.category_scroll)
        root.addWidget(self.module_tabs, 2)
        root.addLayout(controls)
        root.addWidget(self.google_credentials_widget)
        root.addWidget(self.prompt_panel, 1)

    def _build_google_credentials_ui(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Google Credentials"))
        layout.addWidget(QLabel("Google module(s) enabled. Configure credentials here."))
        return panel

    def _register_core_services(self) -> None:
        self.service_registry.register_service("prompt_interface", self.prompt_panel)
        self.service_registry.register_service("ai_interface_adapter", self._ai_adapter)
        self.service_registry.register_service("settings_storage", self.settings_manager)
        self.service_registry.register_service("event_bus", self.service_registry.event_bus)
        self.service_registry.register_service("diagnostics_logger", self.diagnostics)
        self.service_registry.register_service("ui_registration", self)
        self.service_registry.register_service("persona_access", self.persona_manager)
        self.service_registry.register_service("category_placement", self.category_manager)
        self.service_registry.register_service("slash_command_registration", self._register_slash_command)

    def _register_built_in_system_modules(self) -> None:
        built_ins = [
            ("Instruments", "builtin.instruments", "System Tools"),
            ("Diagnostics", "builtin.diagnostics", "System Tools"),
            ("Settings", "builtin.settings", "System Tools"),
            ("Built-in Calendar", "builtin.calendar", "System Tools"),
            ("Persona System", "builtin.persona", "System Tools"),
            ("AI Startup Validator", "builtin.ai_startup_validator", "System Tools"),
            ("Module Manager", "builtin.module_manager", "System Tools"),
            ("Category Manager", "builtin.category_manager", "System Tools"),
        ]
        for name, module_id, category in built_ins:
            pane = QWidget()
            pane_layout = QVBoxLayout(pane)
            pane_layout.addWidget(QLabel(f"{{name}} is active."))
            self.register_module_ui(module_id, name, pane, category)
            self.module_manager.mark_module_non_removable(module_id)

    def register_module_ui(self, module_id: str, module_name: str, widget: QWidget, category: str) -> None:
        self.category_manager.register_module(module_id, module_name, category, widget)
        self._refresh_category_buttons()
        self._show_category(category)

    def remove_module_ui(self, module_id: str) -> None:
        self.category_manager.remove_module(module_id)
        self._refresh_category_buttons()
        first_category = self.category_manager.first_category()
        if first_category:
            self._show_category(first_category)

    def _refresh_category_buttons(self) -> None:
        while self.category_button_layout.count() > 1:
            item = self.category_button_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for category in self.category_manager.category_names():
            button = QPushButton(category)
            button.clicked.connect(lambda _, cat=category: self._show_category(cat))
            self.category_button_layout.insertWidget(self.category_button_layout.count() - 1, button)

    def _show_category(self, category: str) -> None:
        self.module_tabs.clear()
        for module_name, widget in self.category_manager.widgets_for_category(category):
            self.module_tabs.addTab(widget, module_name)

    def refresh_modules(self) -> None:
        self.module_manager.reload_modules()
        self._apply_google_visibility_rule()

    def _apply_google_visibility_rule(self) -> None:
        enabled_google = any(
            module_info.manifest.get("primary_category") == "Google"
            for module_info in self.module_manager.enabled_modules()
        )
        self.google_credentials_widget.setVisible(enabled_google)

    def _route_prompt_message(self, message: str) -> None:
        response = self._ai_adapter(message)
        self.prompt_panel.append_message("Deck", response)

    def _ai_adapter(self, message: str) -> str:
        persona = self.persona_manager.active_persona()
        style = persona.display_name or "Neutral"
        return f"[{{style}}] Received: {{message}}"

    def _register_slash_command(self, command: str, handler: Any) -> None:
        self.diagnostics.info(f"Registered slash command: {{command}}")


def main() -> None:
    app = QApplication(sys.argv)
    runtime = DeckRuntime()
    runtime.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
'''


SERVICE_REGISTRY = '''
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
'''


CATEGORY_MANAGER = '''
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CategoryModule:
    module_id: str
    module_name: str
    widget: Any


class CategoryManager:
    def __init__(self) -> None:
        self._categories: dict[str, list[CategoryModule]] = {}
        self._module_to_category: dict[str, str] = {}

    def register_module(self, module_id: str, module_name: str, primary_category: str, widget: Any) -> None:
        self._categories.setdefault(primary_category, []).append(
            CategoryModule(module_id=module_id, module_name=module_name, widget=widget)
        )
        self._module_to_category[module_id] = primary_category

    def remove_module(self, module_id: str) -> None:
        category = self._module_to_category.pop(module_id, None)
        if not category:
            return
        modules = self._categories.get(category, [])
        self._categories[category] = [m for m in modules if m.module_id != module_id]
        if not self._categories[category]:
            del self._categories[category]

    def widgets_for_category(self, category: str) -> list[tuple[str, Any]]:
        return [(m.module_name, m.widget) for m in self._categories.get(category, [])]

    def category_names(self) -> list[str]:
        return list(self._categories.keys())

    def first_category(self) -> str | None:
        return next(iter(self._categories.keys()), None)
'''


MODULE_MANAGER = '''
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
'''


PERSONA_SYSTEM = '''
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pronouns:
    subject: str = ""
    object: str = ""
    possessive: str = ""
    reflexive: str = ""


@dataclass
class PersonaTheme:
    light_theme_colors: dict[str, str] = field(default_factory=dict)
    dark_theme_colors: dict[str, str] = field(default_factory=dict)
    accent_colors: dict[str, str] = field(default_factory=dict)


@dataclass
class Persona:
    display_name: str
    pronouns: Pronouns
    tone_profile: str
    system_prompt: str
    theme: PersonaTheme


class PersonaManager:
    def __init__(self, settings_manager) -> None:
        self.settings_manager = settings_manager
        self._active_persona = Persona(
            display_name="Neutral",
            pronouns=Pronouns(),
            tone_profile="balanced",
            system_prompt="",
            theme=PersonaTheme(),
        )

    def active_persona(self) -> Persona:
        return self._active_persona

    def switch_persona(self, persona_data: dict) -> Persona:
        self._active_persona = Persona(
            display_name=persona_data.get("display_name", ""),
            pronouns=Pronouns(**persona_data.get("pronouns", {})),
            tone_profile=persona_data.get("tone_profile", ""),
            system_prompt=persona_data.get("system_prompt", ""),
            theme=PersonaTheme(
                light_theme_colors=persona_data.get("light_theme_colors", {}),
                dark_theme_colors=persona_data.get("dark_theme_colors", {}),
                accent_colors=persona_data.get("accent_colors", {}),
            ),
        )
        self.settings_manager.set_value("persona", persona_data)
        return self._active_persona
'''


AI_STARTUP_VALIDATOR = '''
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ValidationState:
    status: str
    ready: bool


class AIRecoveryDialog(QDialog):
    def __init__(self, settings_manager) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.setWindowTitle("AI Recovery")
        self.resize(540, 420)

        outer_layout = QVBoxLayout(self)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        content = QWidget()
        form_layout = QVBoxLayout(content)

        form_layout.addWidget(QLabel("Runner executable"))
        path_layout = QHBoxLayout()
        self.runner_path = QLineEdit()
        browse = QPushButton("Locate...")
        browse.clicked.connect(self._pick_runner)
        path_layout.addWidget(self.runner_path)
        path_layout.addWidget(browse)
        form_layout.addLayout(path_layout)

        form_layout.addWidget(QLabel("Model"))
        self.model_selector = QComboBox()
        self.model_selector.addItems(["", "default-model", "custom-model"])
        form_layout.addWidget(self.model_selector)

        form_layout.addWidget(QLabel("Guided setup"))
        form_layout.addWidget(QLabel("Placeholder: setup assistant will be added in a future release."))

        save_button = QPushButton("Save Configuration")
        save_button.clicked.connect(self._save)
        form_layout.addWidget(save_button)
        form_layout.addStretch(1)

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)

    def _pick_runner(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Locate Runner")
        if file_name:
            self.runner_path.setText(file_name)

    def _save(self) -> None:
        self.settings_manager.set_value("ai_runner_path", self.runner_path.text().strip())
        self.settings_manager.set_value("ai_model", self.model_selector.currentText().strip())
        self.accept()


class StartupStatusDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Startup Validation")
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Initializing...")
        layout.addWidget(self.status_label)

    def update_status(self, text: str) -> None:
        self.status_label.setText(text)


class AIStartupValidator:
    def __init__(self, settings_manager) -> None:
        self.settings_manager = settings_manager

    def ensure_ready(self, parent=None) -> bool:
        status = StartupStatusDialog()
        status.setParent(parent)
        status.show()

        state = self._run_validation(status)
        if state.ready:
            QTimer.singleShot(200, status.accept)
            status.exec()
            return True

        status.accept()
        recovery = AIRecoveryDialog(self.settings_manager)
        recovery.setParent(parent)
        recovery.exec()
        return False

    def _run_validation(self, status_dialog: StartupStatusDialog) -> ValidationState:
        status_dialog.update_status("checking runner")
        runner_path = self.settings_manager.get_value("ai_runner_path", "")

        if runner_path and Path(runner_path).exists():
            status_dialog.update_status("validating model")
            model = self.settings_manager.get_value("ai_model", "")
            if model:
                status_dialog.update_status("AI ready")
                return ValidationState(status="ready", ready=True)

        status_dialog.update_status("starting runner")
        status_dialog.update_status("waiting for availability")
        status_dialog.update_status("validating model")
        return ValidationState(status="recovery_required", ready=False)
'''


SETTINGS_MANAGER = '''
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
'''


DIAGNOSTICS = '''
from __future__ import annotations

from datetime import datetime, timezone


class Diagnostics:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _log(self, level: str, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = f"[{timestamp}] [{level}] {message}"
        self.records.append((level, entry))
        print(entry)

    def info(self, message: str) -> None:
        self._log("INFO", message)

    def warning(self, message: str) -> None:
        self._log("WARN", message)

    def error(self, message: str) -> None:
        self._log("ERROR", message)
'''


INSTRUMENTS = '''
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InstrumentReading:
    name: str
    value: str


class Instruments:
    def __init__(self) -> None:
        self.readings: dict[str, InstrumentReading] = {}

    def set_reading(self, name: str, value: str) -> None:
        self.readings[name] = InstrumentReading(name=name, value=value)

    def get_reading(self, name: str) -> InstrumentReading | None:
        return self.readings.get(name)
'''


IDENTITY_STORE = "# identity handshake store placeholder\n"


def main() -> None:
    output_dir = build_generated_deck(Path(__file__).resolve().parent)
    print(f"Generated modular deck scaffold at: {output_dir}")


if __name__ == "__main__":
    main()
