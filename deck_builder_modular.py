#!/usr/bin/env python3
"""PyQt6 modular Deck Builder UI.

This application is intentionally a *builder* for deck configuration, not a runtime deck shell.
It scans a sibling ``Modules/`` directory, allows module selection, validates requirements,
and saves/exports a deck configuration payload.
"""

from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

DECK_VERSION = "2.0.0"


@dataclass
class ModuleSpec:
    name: str
    file_name: str
    category: str = "Uncategorized"
    secondary_categories: list[str] = field(default_factory=list)
    description: str = ""
    service_requirements: list[str] = field(default_factory=list)
    file_dependencies: list[str] = field(default_factory=list)
    compatibility: str = "unknown"
    enabled: bool = False


class ModuleDiscovery:
    """Discover optional module metadata from sibling Modules/*.py files."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.modules_dir = runtime_root / "Modules"
        self.errors: list[str] = []

    def discover(self) -> list[ModuleSpec]:
        self.errors = []
        self.modules_dir.mkdir(exist_ok=True)
        discovered: list[ModuleSpec] = []

        for module_file in sorted(self.modules_dir.glob("*.py")):
            if module_file.name.startswith("_"):
                continue

            module_data: dict[str, object] = {
                "name": module_file.stem,
                "category": "External",
                "description": "No description provided.",
                "secondary_categories": [],
                "service_requirements": [],
                "file_dependencies": [],
                "compatibility": "unknown",
            }

            try:
                spec = importlib.util.spec_from_file_location(
                    f"deck_external_{module_file.stem}", str(module_file)
                )
                if spec is None or spec.loader is None:
                    raise RuntimeError("Could not build import spec")

                py_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(py_module)

                register = getattr(py_module, "register", None)
                if callable(register):
                    payload = register()
                    if isinstance(payload, dict):
                        module_data.update(payload)
                    else:
                        raise TypeError("register() returned non-dict payload")
            except Exception as exc:
                self.errors.append(
                    f"Failed loading {module_file.name}: {exc}\n{traceback.format_exc()}"
                )

            discovered.append(
                ModuleSpec(
                    name=str(module_data.get("name", module_file.stem)),
                    file_name=module_file.name,
                    category=str(module_data.get("category", "External")),
                    secondary_categories=[str(x) for x in module_data.get("secondary_categories", [])],
                    description=str(module_data.get("description", "")),
                    service_requirements=[str(x) for x in module_data.get("service_requirements", [])],
                    file_dependencies=[str(x) for x in module_data.get("file_dependencies", [])],
                    compatibility=str(module_data.get("compatibility", "unknown")),
                )
            )

        return discovered


class DeckBuilderWindow(QMainWindow):
    def __init__(self, runtime_root: Path) -> None:
        super().__init__()
        self.runtime_root = runtime_root
        self.discovery = ModuleDiscovery(runtime_root)

        self.modules: list[ModuleSpec] = []
        self.builtin_systems = [
            "Instruments Core",
            "Diagnostics Core",
            "Persona Core",
            "Settings Core",
            "AI Startup Validator",
            "Module Registry Service",
        ]

        self.setWindowTitle(f"Deck Builder Modular v{DECK_VERSION}")
        self.resize(1540, 980)

        self._build_ui()
        self._rescan_modules()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        title = QLabel("Deck Builder — Configuration and Assembly Workspace")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root_layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, stretch=1)

        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.addWidget(self._build_deck_config_section())
        left_layout.addWidget(self._build_ai_config_section())
        left_layout.addWidget(self._build_builtins_section())
        left_layout.addStretch(1)

        center_col = QWidget()
        center_layout = QVBoxLayout(center_col)
        center_layout.addWidget(self._build_module_discovery_section(), stretch=3)
        center_layout.addWidget(self._build_category_preview_section(), stretch=2)

        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.addWidget(self._build_requirements_section(), stretch=3)
        right_layout.addWidget(self._build_log_section(), stretch=3)
        right_layout.addWidget(self._build_actions_section())

        splitter.addWidget(left_col)
        splitter.addWidget(center_col)
        splitter.addWidget(right_col)
        splitter.setSizes([430, 620, 490])

        self.setCentralWidget(root)

    def _build_deck_config_section(self) -> QGroupBox:
        box = QGroupBox("A. Deck Configuration")
        form = QFormLayout(box)

        self.deck_name = QLineEdit("MyDeck")
        self.output_folder = QLineEdit(str(self.runtime_root / "GeneratedDeck"))
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._pick_output_folder)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_folder)
        output_row.addWidget(browse_btn)
        output_wrap = QWidget()
        output_wrap.setLayout(output_row)

        self.theme_mode = QComboBox()
        self.theme_mode.addItems(["System", "Dark", "Light"])
        self.persona_baseline = QLineEdit("DefaultPersona")
        self.open_startup_logs = QCheckBox("Open validation log panel on startup")
        self.require_strict_validation = QCheckBox("Block build when validation fails")
        self.require_strict_validation.setChecked(True)

        form.addRow("Deck name:", self.deck_name)
        form.addRow("Output/runtime target:", output_wrap)
        form.addRow("Theme baseline:", self.theme_mode)
        form.addRow("Persona baseline:", self.persona_baseline)
        form.addRow(self.open_startup_logs)
        form.addRow(self.require_strict_validation)
        return box

    def _build_ai_config_section(self) -> QGroupBox:
        box = QGroupBox("B. AI Configuration")
        form = QFormLayout(box)

        self.ai_runner = QComboBox()
        self.ai_runner.addItems(["OpenAI API", "Local Ollama", "Azure OpenAI", "Custom Runner"])

        self.ai_model = QComboBox()
        self.ai_model.addItems(["gpt-4.1", "gpt-4o", "gpt-4o-mini", "custom-model"])

        self.sync_models = QCheckBox("Sync model list from selected runner (placeholder)")
        self.startup_validation_mode = QComboBox()
        self.startup_validation_mode.addItems(["Warn", "Strict", "Skip"])

        self.test_connection_btn = QPushButton("Test Runner Connection")
        self.test_connection_btn.clicked.connect(self._test_connection)

        self.recovery_notes = QPlainTextEdit()
        self.recovery_notes.setPlaceholderText(
            "Recovery/setup notes for tokens, keys, local runner setup, troubleshooting..."
        )
        self.recovery_notes.setFixedHeight(90)

        form.addRow("Runner:", self.ai_runner)
        form.addRow("Model:", self.ai_model)
        form.addRow(self.sync_models)
        form.addRow("Startup validation:", self.startup_validation_mode)
        form.addRow(self.test_connection_btn)
        form.addRow("Recovery/setup notes:", self.recovery_notes)
        return box

    def _build_builtins_section(self) -> QGroupBox:
        box = QGroupBox("C. Built-In Systems (Always Included)")
        layout = QVBoxLayout(box)

        self.builtin_list = QListWidget()
        for name in self.builtin_systems:
            item = QListWidgetItem(f"✅ {name}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.builtin_list.addItem(item)

        layout.addWidget(self.builtin_list)
        return box

    def _build_module_discovery_section(self) -> QGroupBox:
        box = QGroupBox("D. Optional Module Discovery")
        layout = QVBoxLayout(box)

        self.scan_summary = QLabel()
        self.scan_summary.setWordWrap(True)

        self.module_table = QTreeWidget()
        self.module_table.setHeaderLabels(
            ["Enabled", "Module", "Category", "Secondary", "Compatibility", "Services"]
        )
        self.module_table.itemSelectionChanged.connect(self._show_selected_module_details)
        self.module_table.itemChanged.connect(self._module_enable_toggled)

        self.module_metadata = QPlainTextEdit()
        self.module_metadata.setReadOnly(True)
        self.module_metadata.setPlaceholderText("Select a module to view metadata.")
        self.module_metadata.setFixedHeight(130)

        layout.addWidget(self.scan_summary)
        layout.addWidget(self.module_table, stretch=1)
        layout.addWidget(QLabel("Module metadata:"))
        layout.addWidget(self.module_metadata)
        return box

    def _build_requirements_section(self) -> QGroupBox:
        box = QGroupBox("E. Requirements / Dependencies")
        layout = QVBoxLayout(box)

        self.service_reqs = QPlainTextEdit()
        self.service_reqs.setReadOnly(True)
        self.file_reqs = QPlainTextEdit()
        self.file_reqs.setReadOnly(True)

        self.google_creds_label = QLabel(
            "Google Credentials Required:\n- GOOGLE_API_KEY\n- OAuth/Service account file (if module requires Drive/Gmail)"
        )
        self.google_creds_label.setStyleSheet("color: #a86f00; font-weight: 600;")
        self.google_creds_label.setVisible(False)

        self.warning_box = QPlainTextEdit()
        self.warning_box.setReadOnly(True)
        self.warning_box.setFixedHeight(80)

        layout.addWidget(QLabel("Shared service requirements triggered by enabled modules:"))
        layout.addWidget(self.service_reqs)
        layout.addWidget(self.google_creds_label)
        layout.addWidget(QLabel("File/dependency requirements:"))
        layout.addWidget(self.file_reqs)
        layout.addWidget(QLabel("Dependency warnings:"))
        layout.addWidget(self.warning_box)
        return box

    def _build_category_preview_section(self) -> QGroupBox:
        box = QGroupBox("F. Category Summary / Placement Preview")
        layout = QVBoxLayout(box)

        self.category_tree = QTreeWidget()
        self.category_tree.setHeaderLabels(["Category", "Modules / Secondary References"])

        layout.addWidget(self.category_tree)
        return box

    def _build_log_section(self) -> QGroupBox:
        box = QGroupBox("G. Build / Validation Log")
        layout = QVBoxLayout(box)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        return box

    def _build_actions_section(self) -> QGroupBox:
        box = QGroupBox("H. Builder Actions")
        layout = QGridLayout(box)

        rescan_btn = QPushButton("Rescan Modules")
        validate_btn = QPushButton("Validate Configuration")
        save_btn = QPushButton("Save Deck Config")
        build_btn = QPushButton("Build / Export")
        install_btn = QPushButton("Install Module File")
        remove_btn = QPushButton("Remove Module Registration")

        rescan_btn.clicked.connect(self._rescan_modules)
        validate_btn.clicked.connect(self._validate_configuration)
        save_btn.clicked.connect(self._save_deck_config)
        build_btn.clicked.connect(self._build_export)
        install_btn.clicked.connect(self._install_placeholder)
        remove_btn.clicked.connect(self._remove_placeholder)

        layout.addWidget(rescan_btn, 0, 0)
        layout.addWidget(validate_btn, 0, 1)
        layout.addWidget(save_btn, 1, 0)
        layout.addWidget(build_btn, 1, 1)
        layout.addWidget(install_btn, 2, 0)
        layout.addWidget(remove_btn, 2, 1)
        return box

    def _log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def _pick_output_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select output/runtime folder")
        if chosen:
            self.output_folder.setText(chosen)
            self._log(f"Output target updated: {chosen}")

    def _test_connection(self) -> None:
        self._log(
            f"AI connection test placeholder: runner={self.ai_runner.currentText()} model={self.ai_model.currentText()}"
        )
        QMessageBox.information(
            self,
            "Test Runner Connection",
            "Connection test placeholder completed. Integrate live runner handshake here.",
        )

    def _rescan_modules(self) -> None:
        self.modules = self.discovery.discover()
        self.module_table.blockSignals(True)
        self.module_table.clear()

        for module in self.modules:
            row = QTreeWidgetItem(
                [
                    "",
                    module.name,
                    module.category,
                    ", ".join(module.secondary_categories) or "-",
                    module.compatibility,
                    ", ".join(module.service_requirements) or "-",
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, module.file_name)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Checked if module.enabled else Qt.CheckState.Unchecked)
            self.module_table.addTopLevelItem(row)

        self.module_table.blockSignals(False)

        self.scan_summary.setText(
            "\n".join(
                [
                    f"Scanned path: {self.discovery.modules_dir}",
                    f"Discovered module files: {len(self.modules)}",
                    f"Load errors: {len(self.discovery.errors)}",
                ]
            )
        )

        self._refresh_requirements_panel()
        self._refresh_category_preview()
        self._log(f"Rescan complete. Modules discovered: {len(self.modules)}")
        for err in self.discovery.errors:
            self._log(err)

    def _module_enable_toggled(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        module_name = item.text(1)
        state = item.checkState(0) == Qt.CheckState.Checked
        for module in self.modules:
            if module.name == module_name:
                module.enabled = state
                self._log(f"Module {'enabled' if state else 'disabled'}: {module_name}")
                break

        self._refresh_requirements_panel()
        self._refresh_category_preview()

    def _show_selected_module_details(self) -> None:
        item = self.module_table.currentItem()
        if item is None:
            self.module_metadata.clear()
            return

        name = item.text(1)
        selected = next((m for m in self.modules if m.name == name), None)
        if selected is None:
            return

        self.module_metadata.setPlainText(
            "\n".join(
                [
                    f"Module: {selected.name}",
                    f"Source file: {selected.file_name}",
                    f"Primary category: {selected.category}",
                    f"Secondary categories: {', '.join(selected.secondary_categories) or '-'}",
                    f"Compatibility: {selected.compatibility}",
                    f"Service requirements: {', '.join(selected.service_requirements) or '-'}",
                    f"File dependencies: {', '.join(selected.file_dependencies) or '-'}",
                    "",
                    "Description:",
                    selected.description or "(none)",
                ]
            )
        )

    def _enabled_modules(self) -> list[ModuleSpec]:
        return [m for m in self.modules if m.enabled]

    def _refresh_requirements_panel(self) -> None:
        enabled = self._enabled_modules()
        services = sorted({req for m in enabled for req in m.service_requirements})
        files = sorted({dep for m in enabled for dep in m.file_dependencies})

        self.service_reqs.setPlainText("\n".join(services) if services else "No additional services required.")
        self.file_reqs.setPlainText("\n".join(files) if files else "No additional files/dependencies required.")

        requires_google = any("google" in req.lower() for req in services + files)
        self.google_creds_label.setVisible(requires_google)

        warnings: list[str] = []
        incompatible = [m.name for m in enabled if m.compatibility.lower() in {"incompatible", "unsupported"}]
        if incompatible:
            warnings.append(f"Incompatible modules selected: {', '.join(incompatible)}")
        if not enabled:
            warnings.append("No optional modules enabled. Build will include only built-in systems.")

        self.warning_box.setPlainText("\n".join(warnings) if warnings else "No dependency warnings.")

    def _refresh_category_preview(self) -> None:
        self.category_tree.clear()
        categories: dict[str, list[ModuleSpec]] = {}
        for module in self._enabled_modules():
            categories.setdefault(module.category, []).append(module)

        if not categories:
            QTreeWidgetItem(self.category_tree, ["(No optional modules enabled)", "Built-ins only"])
            return

        for category_name in sorted(categories):
            root = QTreeWidgetItem(self.category_tree, [category_name, "Primary category"])
            for module in sorted(categories[category_name], key=lambda m: m.name.lower()):
                secondary = ", ".join(module.secondary_categories) or "None"
                QTreeWidgetItem(root, [module.name, f"Secondary refs: {secondary}"])

        self.category_tree.expandAll()

    def _validate_configuration(self) -> bool:
        errors: list[str] = []

        if not self.deck_name.text().strip():
            errors.append("Deck name is required.")

        if not self.output_folder.text().strip():
            errors.append("Output/runtime target is required.")

        enabled = self._enabled_modules()
        if any(m.compatibility.lower() in {"incompatible", "unsupported"} for m in enabled):
            errors.append("One or more enabled modules are marked incompatible.")

        if self.google_creds_label.isVisible():
            errors.append("Google credentials required by selected modules (configure before build).")

        if errors:
            self._log("Validation failed:")
            for err in errors:
                self._log(f" - {err}")
            QMessageBox.warning(self, "Validation Failed", "\n".join(errors))
            return False

        self._log("Validation passed. Configuration appears ready.")
        QMessageBox.information(self, "Validation", "Configuration validation passed.")
        return True

    def _config_payload(self) -> dict[str, object]:
        enabled_modules = self._enabled_modules()
        return {
            "deck_name": self.deck_name.text().strip(),
            "version": DECK_VERSION,
            "output_folder": self.output_folder.text().strip(),
            "theme_mode": self.theme_mode.currentText(),
            "persona_baseline": self.persona_baseline.text().strip(),
            "startup": {
                "open_log": self.open_startup_logs.isChecked(),
                "strict_validation": self.require_strict_validation.isChecked(),
                "validation_mode": self.startup_validation_mode.currentText(),
            },
            "ai": {
                "runner": self.ai_runner.currentText(),
                "model": self.ai_model.currentText(),
                "sync_models_placeholder": self.sync_models.isChecked(),
                "recovery_notes": self.recovery_notes.toPlainText(),
            },
            "builtins": self.builtin_systems,
            "modules": [
                {
                    "name": m.name,
                    "file": m.file_name,
                    "category": m.category,
                    "secondary_categories": m.secondary_categories,
                    "service_requirements": m.service_requirements,
                    "file_dependencies": m.file_dependencies,
                    "compatibility": m.compatibility,
                }
                for m in enabled_modules
            ],
        }

    def _save_deck_config(self) -> None:
        payload = self._config_payload()
        output_dir = Path(self.output_folder.text().strip() or self.runtime_root)
        output_dir.mkdir(parents=True, exist_ok=True)
        config_path = output_dir / f"{self.deck_name.text().strip() or 'deck'}_config.json"
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._log(f"Deck configuration saved: {config_path}")
        QMessageBox.information(self, "Save Deck Config", f"Saved configuration to:\n{config_path}")

    def _build_export(self) -> None:
        if self.require_strict_validation.isChecked() and not self._validate_configuration():
            self._log("Build/export canceled due to strict validation failure.")
            return

        payload = self._config_payload()
        output_dir = Path(self.output_folder.text().strip() or self.runtime_root)
        output_dir.mkdir(parents=True, exist_ok=True)
        export_path = output_dir / f"{self.deck_name.text().strip() or 'deck'}_build_preview.json"
        export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._log(f"Build/export preview generated: {export_path}")
        QMessageBox.information(self, "Build / Export", f"Build preview exported to:\n{export_path}")

    def _install_placeholder(self) -> None:
        self._log("Install module file placeholder triggered.")
        QMessageBox.information(
            self,
            "Install Module File",
            "Install workflow placeholder. Add copy/register logic for module packages.",
        )

    def _remove_placeholder(self) -> None:
        self._log("Remove module registration placeholder triggered.")
        QMessageBox.information(
            self,
            "Remove Module Registration",
            "Remove workflow placeholder. Add unregister/delete logic here.",
        )


def main() -> int:
    app = QApplication([])
    window = DeckBuilderWindow(Path(__file__).resolve().parent)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
