#!/usr/bin/env python3
"""PyQt6 modular Deck Builder / Runtime shell.

This entrypoint intentionally launches a GUI-only application.
No interactive CLI loop is provided.
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

DECK_VERSION = "1.0.0"


@dataclass
class ModuleSpec:
    name: str
    category: str
    source: str  # "builtin" or "external"
    description: str
    panel_factory: Callable[[], QWidget]
    enabled: bool = True


class ModuleDiscovery:
    """Discovers optional modules from a sibling Modules/ folder."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.modules_dir = runtime_root / "Modules"
        self.errors: list[str] = []

    def discover(self) -> list[ModuleSpec]:
        self.modules_dir.mkdir(exist_ok=True)
        discovered: list[ModuleSpec] = []

        for module_file in sorted(self.modules_dir.glob("*.py")):
            if module_file.name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"deck_external_{module_file.stem}", str(module_file)
                )
                if spec is None or spec.loader is None:
                    raise RuntimeError("Could not build import spec")

                py_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(py_module)

                register = getattr(py_module, "register", None)
                if register is None or not callable(register):
                    raise ValueError("Missing callable register()")

                module_info = register()
                if not isinstance(module_info, dict):
                    raise TypeError("register() must return a dict")

                name = str(module_info.get("name", module_file.stem))
                category = str(module_info.get("category", "External"))
                description = str(module_info.get("description", "External module"))

                def build_panel(info: dict = module_info, path: Path = module_file) -> QWidget:
                    panel = QWidget()
                    layout = QVBoxLayout(panel)
                    layout.addWidget(QLabel(f"Module: {info.get('name', path.stem)}"))
                    layout.addWidget(QLabel(f"Source file: {path.name}"))
                    desc = QPlainTextEdit()
                    desc.setReadOnly(True)
                    desc.setPlainText(str(info.get("description", "No description provided.")))
                    layout.addWidget(desc)
                    return panel

                discovered.append(
                    ModuleSpec(
                        name=name,
                        category=category,
                        source="external",
                        description=description,
                        panel_factory=build_panel,
                    )
                )
            except Exception as exc:
                self.errors.append(
                    f"Failed loading {module_file.name}: {exc}\n{traceback.format_exc()}"
                )

        return discovered


class DeckBuilderWindow(QMainWindow):
    def __init__(self, runtime_root: Path) -> None:
        super().__init__()
        self.runtime_root = runtime_root
        self.discovery = ModuleDiscovery(runtime_root)

        self.modules: list[ModuleSpec] = []
        self.category_tabs: dict[str, QTabWidget] = {}

        self.setWindowTitle(f"Deck Builder Modular v{DECK_VERSION}")
        self.resize(1400, 900)

        self._build_ui()
        self._load_modules()
        self._render_categories()

    # ------------------------- UI composition -------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        header = QLabel("Deck Builder Runtime / Visual Modular Shell")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root_layout.addWidget(header)

        body = QHBoxLayout()
        root_layout.addLayout(body, stretch=1)

        # Left: category navigation
        left_box = QGroupBox("Categories")
        left_layout = QVBoxLayout(left_box)
        self.category_list = QListWidget()
        self.category_list.currentTextChanged.connect(self._on_category_selected)
        left_layout.addWidget(self.category_list)
        body.addWidget(left_box, stretch=1)

        # Center: module tabs area
        center_box = QGroupBox("Modules in Selected Category")
        center_layout = QVBoxLayout(center_box)
        self.category_stack = QTabWidget()
        self.category_stack.setTabPosition(QTabWidget.TabPosition.North)
        center_layout.addWidget(self.category_stack)
        body.addWidget(center_box, stretch=3)

        # Right: discovery and module manager summary
        right_box = QGroupBox("Discovery / Module Manager")
        right_layout = QVBoxLayout(right_box)

        self.discovery_summary = QLabel("Scanning modules...")
        self.discovery_summary.setWordWrap(True)
        right_layout.addWidget(self.discovery_summary)

        self.manager_list = QListWidget()
        right_layout.addWidget(self.manager_list, stretch=1)

        manager_actions = QHBoxLayout()
        self.enable_btn = QPushButton("Enable")
        self.disable_btn = QPushButton("Disable")
        self.install_btn = QPushButton("Install")
        self.remove_btn = QPushButton("Remove")

        self.enable_btn.clicked.connect(self._enable_selected_module)
        self.disable_btn.clicked.connect(self._disable_selected_module)
        self.install_btn.clicked.connect(self._install_placeholder)
        self.remove_btn.clicked.connect(self._remove_placeholder)

        manager_actions.addWidget(self.enable_btn)
        manager_actions.addWidget(self.disable_btn)
        manager_actions.addWidget(self.install_btn)
        manager_actions.addWidget(self.remove_btn)
        right_layout.addLayout(manager_actions)

        body.addWidget(right_box, stretch=2)

        # Bottom: prompt area + status panel
        bottom = QHBoxLayout()

        prompt_box = QGroupBox("Prompt Area")
        prompt_layout = QVBoxLayout(prompt_box)
        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setPlaceholderText("Enter prompt text here...")
        self.prompt_input.setMinimumHeight(120)
        prompt_layout.addWidget(self.prompt_input)

        prompt_actions = QHBoxLayout()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_prompt)
        self.token_label = QLabel("Tokens: --")
        prompt_actions.addWidget(self.send_btn)
        prompt_actions.addWidget(self.token_label)
        prompt_actions.addStretch(1)
        prompt_layout.addLayout(prompt_actions)

        bottom.addWidget(prompt_box, stretch=2)

        status_box = QGroupBox("State / Status Log")
        status_layout = QVBoxLayout(status_box)
        self.status_log = QPlainTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        status_layout.addWidget(self.status_log)
        bottom.addWidget(status_box, stretch=3)

        root_layout.addLayout(bottom, stretch=1)

        self.setCentralWidget(root)

    # ------------------------- Built-ins + discovery -------------------------

    def _builtin_modules(self) -> list[ModuleSpec]:
        def placeholder_panel(title: str, message: str) -> Callable[[], QWidget]:
            def build() -> QWidget:
                panel = QFrame()
                layout = QVBoxLayout(panel)
                label = QLabel(title)
                label.setStyleSheet("font-size: 16px; font-weight: 600;")
                layout.addWidget(label)
                text = QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText(message)
                layout.addWidget(text)
                return panel

            return build

        return [
            ModuleSpec(
                name="Instruments",
                category="Built-in Systems",
                source="builtin",
                description="Instrumentation controls and baseline tools.",
                panel_factory=placeholder_panel(
                    "Instruments",
                    "Placeholder for instrument controls, deck hooks, and runtime signals.",
                ),
            ),
            ModuleSpec(
                name="Diagnostics",
                category="Built-in Systems",
                source="builtin",
                description="Runtime diagnostics and health checks.",
                panel_factory=placeholder_panel(
                    "Diagnostics",
                    "Placeholder for diagnostics streams, warnings, and health metrics.",
                ),
            ),
            ModuleSpec(
                name="Settings",
                category="Built-in Systems",
                source="builtin",
                description="Application and module settings.",
                panel_factory=placeholder_panel(
                    "Settings",
                    "Placeholder for app configuration, runtime profile, and persisted options.",
                ),
            ),
            ModuleSpec(
                name="Built-in Calendar",
                category="Built-in Systems",
                source="builtin",
                description="Baseline calendar integration placeholder.",
                panel_factory=placeholder_panel(
                    "Built-in Calendar",
                    "Placeholder for date-aware planning, scheduling, and timeline widgets.",
                ),
            ),
            ModuleSpec(
                name="Persona System",
                category="Built-in Systems",
                source="builtin",
                description="Persona management and behavioral profile.",
                panel_factory=placeholder_panel(
                    "Persona System",
                    "Placeholder for persona profile editor and behavior constraints.",
                ),
            ),
            ModuleSpec(
                name="Module Manager",
                category="Built-in Systems",
                source="builtin",
                description="Installed/discovered module management view.",
                panel_factory=self._module_manager_panel,
            ),
            ModuleSpec(
                name="AI Startup Validator",
                category="Built-in Systems",
                source="builtin",
                description="Startup validation results and remediation guidance.",
                panel_factory=placeholder_panel(
                    "AI Startup Validator",
                    "Checks for runtime folder shape, Modules availability, and module load errors.",
                ),
            ),
        ]

    def _module_manager_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Module Manager Panel"))

        instructions = QPlainTextEdit()
        instructions.setReadOnly(True)
        instructions.setPlainText(
            "Use the Discovery / Module Manager section on the right to select modules and "
            "run scaffolded Enable/Disable/Install/Remove actions."
        )
        layout.addWidget(instructions)
        return panel

    def _load_modules(self) -> None:
        self.modules = self._builtin_modules()
        external = self.discovery.discover()
        self.modules.extend(external)

        builtins = [m for m in self.modules if m.source == "builtin"]
        externals = [m for m in self.modules if m.source == "external"]

        self.discovery_summary.setText(
            "\n".join(
                [
                    f"Runtime root: {self.runtime_root}",
                    f"Modules path scanned: {self.discovery.modules_dir}",
                    f"Built-in systems: {len(builtins)}",
                    f"External modules discovered: {len(externals)}",
                ]
            )
        )

        if self.discovery.errors:
            self._log("Startup validator: module load issues detected.")
            for err in self.discovery.errors:
                self._log(err)

        self.manager_list.clear()
        for module in self.modules:
            item = QListWidgetItem(
                f"[{module.source}] {module.name} ({module.category}) - {'enabled' if module.enabled else 'disabled'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, module.name)
            self.manager_list.addItem(item)

    def _render_categories(self) -> None:
        self.category_tabs.clear()
        self.category_list.clear()
        self.category_stack.clear()

        categories = sorted({m.category for m in self.modules})
        for category in categories:
            self.category_list.addItem(category)

            tabs = QTabWidget()
            for module in [m for m in self.modules if m.category == category and m.enabled]:
                tabs.addTab(module.panel_factory(), module.name)
            if tabs.count() == 0:
                empty = QWidget()
                lay = QVBoxLayout(empty)
                lay.addWidget(QLabel("No enabled modules in this category."))
                tabs.addTab(empty, "Empty")

            self.category_tabs[category] = tabs
            self.category_stack.addTab(tabs, category)

        if self.category_list.count() > 0:
            self.category_list.setCurrentRow(0)

    # ------------------------- interactions -------------------------

    def _log(self, message: str) -> None:
        self.status_log.appendPlainText(message)

    def _on_category_selected(self, category: str) -> None:
        if not category:
            return
        for idx in range(self.category_stack.count()):
            if self.category_stack.tabText(idx) == category:
                self.category_stack.setCurrentIndex(idx)
                self._log(f"Category selected: {category}")
                break

    def _send_prompt(self) -> None:
        text = self.prompt_input.toPlainText().strip()
        if not text:
            self._log("Prompt send ignored: no input text.")
            return

        token_estimate = len(text.split())
        self.token_label.setText(f"Tokens (est.): {token_estimate}")
        self._log(f"Prompt submitted ({token_estimate} tokens est.): {text}")
        self.prompt_input.clear()

    def _selected_module_name(self) -> str | None:
        item = self.manager_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _enable_selected_module(self) -> None:
        name = self._selected_module_name()
        if not name:
            self._log("Enable action ignored: no module selected.")
            return
        for module in self.modules:
            if module.name == name:
                module.enabled = True
                self._log(f"Module enabled: {name}")
                break
        self._load_modules()
        self._render_categories()

    def _disable_selected_module(self) -> None:
        name = self._selected_module_name()
        if not name:
            self._log("Disable action ignored: no module selected.")
            return
        for module in self.modules:
            if module.name == name:
                module.enabled = False
                self._log(f"Module disabled: {name}")
                break
        self._load_modules()
        self._render_categories()

    def _install_placeholder(self) -> None:
        QMessageBox.information(
            self,
            "Install Module",
            "Install action scaffolded. Add install workflow implementation here.",
        )
        self._log("Install action triggered (scaffold placeholder).")

    def _remove_placeholder(self) -> None:
        QMessageBox.information(
            self,
            "Remove Module",
            "Remove action scaffolded. Add uninstall workflow implementation here.",
        )
        self._log("Remove action triggered (scaffold placeholder).")


def main() -> int:
    app = QApplication([])
    window = DeckBuilderWindow(Path(__file__).resolve().parent)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
