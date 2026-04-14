from __future__ import annotations

import random
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget, QLabel


MODULE_MANIFEST = {
    "key": "magic_8_ball",
    "display_name": "Magic 8-Ball",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Entertainment",
    "tab_definitions": [
        {
            "tab_id": "magic_8_ball_tab",
            "tab_name": "Magic 8-Ball",
        }
    ],
    "entry_function": "register",
    "description": "Classic Magic 8-Ball module with host AI interpretation handoff.",
}


_CLASSIC_RESPONSES = [
    "It is certain",
    "It is decidedly so",
    "Without a doubt",
    "Yes definitely",
    "You may rely on it",
    "As I see it, yes",
    "Most likely",
    "Outlook good",
    "Yes",
    "Signs point to yes",
    "Reply hazy, try again",
    "Ask again later",
    "Better not tell you now",
    "Cannot predict now",
    "Concentrate and ask again",
    "Don't count on it",
    "My reply is no",
    "My sources say no",
    "Outlook not so good",
    "Very doubtful",
]


class Magic8BallTab(QWidget):
    def __init__(self, ask_ai: Callable[[str, dict], bool], log: Callable[[str], None]):
        super().__init__()
        self._ask_ai = ask_ai
        self._log = log

        layout = QVBoxLayout(self)

        self.question_input = QLineEdit(self)
        self.question_input.setPlaceholderText("Ask the Magic 8-Ball a yes/no question...")
        layout.addWidget(self.question_input)

        self.result_label = QLabel("Shake to reveal your fortune", self)
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; padding: 18px; border-radius: 8px;"
        )
        layout.addWidget(self.result_label)

        self.shake_button = QPushButton("Shake", self)
        self.shake_button.clicked.connect(self._on_shake)
        layout.addWidget(self.shake_button)

        layout.addStretch(1)

    def _on_shake(self) -> None:
        question = self.question_input.text().strip()
        response = random.choice(_CLASSIC_RESPONSES)
        self.result_label.setText(response)

        payload = {
            "module": "Magic 8-Ball",
            "question": question,
            "response": response,
            "response_pool": "classic_20",
            "instruction": (
                "Interpret this Magic 8-Ball result in your persona voice. "
                "If a question is present, address it directly."
            ),
        }
        delivered = self._ask_ai("magic_8_ball", payload)
        if not delivered:
            self._log("Magic 8-Ball AI handoff unavailable; result displayed locally only.")


def register(deck_api: dict) -> dict:
    deck_api_version = str(deck_api.get("deck_api_version") or "")
    if deck_api_version != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api_version}")

    ask_ai = deck_api.get("request_ai_interpretation")
    if not callable(ask_ai):
        raise RuntimeError("Host API missing request_ai_interpretation")

    log_fn = deck_api.get("log")
    if not callable(log_fn):
        log_fn = lambda _msg: None

    def _build_tab() -> QWidget:
        return Magic8BallTab(ask_ai=ask_ai, log=log_fn)

    return {
        "deck_api_version": "1.0",
        "module_key": "magic_8_ball",
        "home_category": "Entertainment",
        "tabs": [
            {
                "tab_id": "magic_8_ball_tab",
                "tab_name": "Magic 8-Ball",
                "get_content": _build_tab,
            }
        ],
        "hooks": {},
    }
