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


DECK_VERSION = "0.1.0"


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
                cursor.insertText("\n")
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
        self.token_counter.setText(f"Tokens: {token_count}")

    def _submit(self, message: str) -> None:
        self.append_message("You", message)
        self.route_callback(message)

    def append_message(self, sender: str, text: str) -> None:
        self.output.append(f"<b>{sender}:</b> {text}")
        self.output.moveCursor(QTextCursor.End)

    def send_to_prompt(self, text: str) -> None:
        current = self.input.toPlainText()
        spacer = "\n" if current else ""
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
            pane_layout.addWidget(QLabel(f"{name} is active."))
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
        return f"[{style}] Received: {message}"

    def _register_slash_command(self, command: str, handler: Any) -> None:
        self.diagnostics.info(f"Registered slash command: {command}")


def main() -> None:
    app = QApplication(sys.argv)
    runtime = DeckRuntime()
    runtime.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
