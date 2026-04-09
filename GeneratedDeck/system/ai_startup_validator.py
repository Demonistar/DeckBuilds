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
