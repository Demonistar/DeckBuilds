#!/usr/bin/env python3
"""Modularized deck builder modeled on deck_builder.py structure.

- Builder-first UI (not runtime shell)
- Left configuration panels / right module selection via splitter
- Dynamic external module discovery from sibling Modules/
"""

from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

BUILDER_VERSION = "1.0.0"
SCRIPT_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPT_DIR / "Modules"


@dataclass
class ModuleManifest:
    module_id: str
    display_name: str
    source_file: str
    description: str = ""
    primary_category: str = "Uncategorized"
    secondary_categories: list[str] = field(default_factory=list)
    compatibility: str = "Unknown"
    requirement_flags: list[str] = field(default_factory=list)
    requires_google: bool = False
    enabled_by_default: bool = False


BUILTIN_SYSTEMS = [
    "Persona Template Parser",
    "Face Extraction",
    "Sound Generation",
    "Deck Template Writer",
    "Setup Worker",
    "UI Helper Widgets",
]


class ModuleDiscovery:
    """Discover external optional modules from sibling Modules/*.py manifests."""

    def __init__(self, modules_dir: Path) -> None:
        self.modules_dir = modules_dir
        self.errors: list[str] = []

    def discover(self) -> list[ModuleManifest]:
        self.errors = []
        self.modules_dir.mkdir(exist_ok=True)
        discovered: list[ModuleManifest] = []

        for module_path in sorted(self.modules_dir.glob("*.py")):
            if module_path.name.startswith("_"):
                continue
            try:
                manifest = self._load_manifest(module_path)
                discovered.append(manifest)
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{module_path.name}: {exc}\n{traceback.format_exc()}")

        return discovered

    def _load_manifest(self, module_path: Path) -> ModuleManifest:
        spec = importlib.util.spec_from_file_location(f"dbm_{module_path.stem}", module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create import spec")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        payload = self._extract_manifest_payload(module)

        module_id = str(payload.get("module_id") or module_path.stem)
        display_name = str(payload.get("display_name") or module_id)
        description = str(payload.get("description") or "")
        primary_category = str(payload.get("primary_category") or "Uncategorized")
        secondary_categories = [str(x) for x in payload.get("secondary_categories", []) or []]
        compatibility = str(payload.get("compatibility") or "Unknown")
        requirement_flags = [str(x) for x in payload.get("requirement_flags", []) or []]

        requires_google_raw = payload.get("requires_google")
        requires_google = bool(requires_google_raw)
        if not requires_google:
            joined = " ".join([primary_category, *secondary_categories, *requirement_flags]).lower()
            requires_google = "google" in joined

        enabled_by_default = bool(payload.get("enabled_by_default", False))

        return ModuleManifest(
            module_id=module_id,
            display_name=display_name,
            source_file=module_path.name,
            description=description,
            primary_category=primary_category,
            secondary_categories=secondary_categories,
            compatibility=compatibility,
            requirement_flags=requirement_flags,
            requires_google=requires_google,
            enabled_by_default=enabled_by_default,
        )

    @staticmethod
    def _extract_manifest_payload(module: Any) -> dict[str, Any]:
        if hasattr(module, "MODULE_MANIFEST") and isinstance(module.MODULE_MANIFEST, dict):
            return module.MODULE_MANIFEST
        for fn_name in ("get_manifest", "register", "manifest"):
            fn = getattr(module, fn_name, None)
            if callable(fn):
                data = fn()
                if isinstance(data, dict):
                    return data
                raise TypeError(f"{fn_name}() must return a dict")
        raise ValueError("No module manifest found (MODULE_MANIFEST/get_manifest/register)")


class DeckBuilderModularWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.discovery = ModuleDiscovery(MODULES_DIR)
        self.external_modules: list[ModuleManifest] = []
        self.setWindowTitle(f"Deck Builder Modular v{BUILDER_VERSION}")
        self.resize(1400, 900)
        self._build_ui()
        self._scan_modules()

    def _build_ui(self) -> None:
        root = QWidget()
        page = QVBoxLayout(root)

        page.addWidget(self._build_title_bar())
        page.addWidget(self._build_deck_name_section())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_configuration_column())
        splitter.addWidget(self._build_right_module_column())
        splitter.setSizes([650, 750])
        page.addWidget(splitter, stretch=1)

        page.addWidget(self._build_bottom_row())

        self.setCentralWidget(root)

    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        lay = QHBoxLayout(bar)
        title = QLabel("Echo Deck Builder — Modular")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        version = QLabel(f"v{BUILDER_VERSION}")
        self.theme_toggle = QPushButton("Toggle Light/Dark")
        self.theme_toggle.clicked.connect(self._toggle_theme)
        lay.addWidget(title)
        lay.addStretch(1)
        lay.addWidget(version)
        lay.addWidget(self.theme_toggle)
        return bar

    def _build_deck_name_section(self) -> QGroupBox:
        box = QGroupBox("Deck Name")
        form = QFormLayout(box)
        self.deck_name = QLineEdit()
        self.deck_name.setPlaceholderText("Enter deck name")
        form.addRow("Name:", self.deck_name)
        return box

    def _build_left_configuration_column(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.addWidget(self._connection_panel())
        lay.addWidget(self._persona_panel())
        lay.addWidget(self._face_panel())
        lay.addWidget(self._google_panel())
        lay.addStretch(1)
        return col

    def _connection_panel(self) -> QGroupBox:
        box = QGroupBox("Connection / Runner")
        form = QFormLayout(box)
        self.runner_endpoint = QLineEdit()
        self.runner_endpoint.setPlaceholderText("http://127.0.0.1:11434 or API endpoint")
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("Model name")
        form.addRow("Endpoint:", self.runner_endpoint)
        form.addRow("Model:", self.model_name)
        return box

    def _persona_panel(self) -> QGroupBox:
        box = QGroupBox("Persona")
        form = QFormLayout(box)
        self.persona_template_path = QLineEdit()
        self.persona_template_path.setPlaceholderText("Path to persona template .txt")
        self.persona_export_path = QLineEdit()
        self.persona_export_path.setPlaceholderText("Optional export location")
        form.addRow("Template file:", self.persona_template_path)
        form.addRow("Export target:", self.persona_export_path)
        return box

    def _face_panel(self) -> QGroupBox:
        box = QGroupBox("Face Pack")
        form = QFormLayout(box)
        self.face_pack_path = QLineEdit()
        self.face_pack_path.setPlaceholderText("ZIP or folder path for face extraction")
        self.sound_profile = QLineEdit()
        self.sound_profile.setPlaceholderText("Sound profile / voice preset")
        form.addRow("Input path:", self.face_pack_path)
        form.addRow("Sound profile:", self.sound_profile)
        return box

    def _google_panel(self) -> QGroupBox:
        self.google_group = QGroupBox("Google Credentials")
        form = QFormLayout(self.google_group)
        self.google_key = QLineEdit()
        self.google_key.setPlaceholderText("Google API key")
        self.google_oauth = QLineEdit()
        self.google_oauth.setPlaceholderText("OAuth credentials JSON path")
        form.addRow("API key:", self.google_key)
        form.addRow("OAuth file:", self.google_oauth)
        self.google_group.setVisible(False)
        return self.google_group

    def _build_right_module_column(self) -> QWidget:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.addWidget(self._builtins_panel())
        lay.addWidget(self._modules_panel(), stretch=1)
        return col

    def _builtins_panel(self) -> QGroupBox:
        box = QGroupBox("Built-In Systems (always included)")
        layout = QVBoxLayout(box)
        self.builtin_tree = QTreeWidget()
        self.builtin_tree.setHeaderLabels(["System", "Type"])
        for system in BUILTIN_SYSTEMS:
            QTreeWidgetItem(self.builtin_tree, [system, "Built-in"])
        self.builtin_tree.setRootIsDecorated(False)
        layout.addWidget(self.builtin_tree)
        return box

    def _modules_panel(self) -> QGroupBox:
        box = QGroupBox("External Modules (.\\Modules)")
        layout = QVBoxLayout(box)

        self.scan_label = QLabel()
        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(
            [
                "On",
                "Module",
                "Primary Category",
                "Secondary Categories",
                "Compatibility",
                "Requirement Flags",
            ]
        )
        self.module_tree.itemChanged.connect(self._on_module_toggle)

        self.module_details = QLabel("Select module entries to review metadata.")
        self.module_details.setWordWrap(True)

        refresh = QPushButton("Rescan Modules")
        refresh.clicked.connect(self._scan_modules)

        layout.addWidget(self.scan_label)
        layout.addWidget(self.module_tree, stretch=1)
        layout.addWidget(self.module_details)
        layout.addWidget(refresh)
        return box

    def _build_bottom_row(self) -> QWidget:
        row = QFrame()
        lay = QHBoxLayout(row)
        self.status_text = QLabel("Ready")
        build_btn = QPushButton("Build Deck")
        build_btn.clicked.connect(self._build_deck)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        lay.addWidget(self.status_text)
        lay.addStretch(1)
        lay.addWidget(build_btn)
        lay.addWidget(close_btn)
        return row

    def _toggle_theme(self) -> None:
        if self.styleSheet():
            self.setStyleSheet("")
            return
        self.setStyleSheet(
            """
            QWidget { background: #11131a; color: #d8def5; }
            QLineEdit, QTreeWidget, QGroupBox { background: #191c26; color: #d8def5; }
            QPushButton { background: #2a3550; border: 1px solid #445077; padding: 4px 8px; }
            """
        )

    def _scan_modules(self) -> None:
        self.external_modules = self.discovery.discover()
        self.module_tree.blockSignals(True)
        self.module_tree.clear()

        for mod in self.external_modules:
            item = QTreeWidgetItem(
                [
                    "",
                    mod.display_name,
                    mod.primary_category,
                    ", ".join(mod.secondary_categories) or "-",
                    mod.compatibility,
                    ", ".join(mod.requirement_flags) or "-",
                ]
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if mod.enabled_by_default else Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, mod.module_id)
            self.module_tree.addTopLevelItem(item)

        self.module_tree.blockSignals(False)

        self.scan_label.setText(
            f"Scanned: {self.discovery.modules_dir} | Found: {len(self.external_modules)} | Errors: {len(self.discovery.errors)}"
        )
        self._update_google_visibility()
        self._update_status("Modules scanned")
        if self.discovery.errors:
            self.module_details.setText("Manifest load errors:\n" + "\n".join(self.discovery.errors[:2]))

    def _selected_module_ids(self) -> set[str]:
        selected: set[str] = set()
        for i in range(self.module_tree.topLevelItemCount()):
            item = self.module_tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                selected.add(str(item.data(0, Qt.ItemDataRole.UserRole)))
        return selected

    def _enabled_modules(self) -> list[ModuleManifest]:
        selected = self._selected_module_ids()
        return [m for m in self.external_modules if m.module_id in selected]

    def _on_module_toggle(self, _item: QTreeWidgetItem, _column: int) -> None:
        enabled = self._enabled_modules()
        if enabled:
            names = ", ".join(m.display_name for m in enabled[:4])
            self.module_details.setText(f"Enabled modules: {names}")
        else:
            self.module_details.setText("No external modules enabled. Built-ins only.")
        self._update_google_visibility()

    def _update_google_visibility(self) -> None:
        show_google = any(m.requires_google for m in self._enabled_modules())
        self.google_group.setVisible(show_google)

    def _update_status(self, text: str) -> None:
        self.status_text.setText(text)

    def _build_deck(self) -> None:
        if not self.deck_name.text().strip():
            QMessageBox.warning(self, "Missing Deck Name", "Deck name is required before build.")
            return

        payload = {
            "builder_version": BUILDER_VERSION,
            "deck_name": self.deck_name.text().strip(),
            "connection": {
                "endpoint": self.runner_endpoint.text().strip(),
                "model": self.model_name.text().strip(),
            },
            "persona": {
                "template": self.persona_template_path.text().strip(),
                "export_target": self.persona_export_path.text().strip(),
            },
            "face_pack": {
                "input_path": self.face_pack_path.text().strip(),
                "sound_profile": self.sound_profile.text().strip(),
            },
            "google_credentials": {
                "required": self.google_group.isVisible(),
                "api_key": self.google_key.text().strip(),
                "oauth_file": self.google_oauth.text().strip(),
            },
            "built_in_systems": BUILTIN_SYSTEMS,
            "external_modules": [m.__dict__ for m in self._enabled_modules()],
        }

        output_path = SCRIPT_DIR / f"{self.deck_name.text().strip()}_deck_build.json"
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._update_status(f"Build written: {output_path.name}")
        QMessageBox.information(self, "Build Complete", f"Deck build manifest written:\n{output_path}")


def main() -> int:
    app = QApplication([])
    window = DeckBuilderModularWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
