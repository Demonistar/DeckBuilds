from __future__ import annotations

import random
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton

MODULE_MANIFEST = {
    "key": "magic_8_ball",
    "display_name": "Magic 8-Ball",
    "version": "1.0.0",
    "deck_api_version": "1.0",
    "home_category": "Entertainment",
    "tab_definitions": [
        {"tab_id": "magic_8ball", "tab_name": "Magic 8-Ball"},
    ],
    "hook_registrations": [],
    "shared_resource": None,
    "pip_dependencies": [],
}

RESPONSES = [
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
    def __init__(self, deck_api: dict[str, Any]):
        super().__init__()
        self._deck_api = deck_api

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._question = QLineEdit()
        self._question.setPlaceholderText("Ask a question... (optional)")
        layout.addWidget(self._question)

        self._result = QLabel("🎱")
        self._result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result.setMinimumHeight(140)
        self._result.setWordWrap(True)
        self._result.setStyleSheet(
            "font-size: 26px; font-weight: 700;"
            "border: 1px solid #445; border-radius: 10px;"
            "padding: 16px;"
        )
        layout.addWidget(self._result, 1)

        self._shake_btn = QPushButton("Shake the 8-Ball")
        self._shake_btn.clicked.connect(self._on_shake)
        layout.addWidget(self._shake_btn)

    def _on_shake(self) -> None:
        question = self._question.text().strip()
        answer = random.choice(RESPONSES)
        self._result.setText(answer)

        request_ai = self._deck_api.get("request_ai_interpretation")
        if callable(request_ai):
            request_ai(
                MODULE_MANIFEST["key"],
                {
                    "module_display_name": MODULE_MANIFEST["display_name"],
                    "user_question": question,
                    "magic_8_ball_result": answer,
                    "persona_task": "Interpret this Magic 8-Ball result in character.",
                },
            )



def register(deck_api: dict[str, Any]) -> dict[str, Any]:
    def build_tab() -> QWidget:
        return Magic8BallTab(deck_api)

    return {
        "key": MODULE_MANIFEST["key"],
        "display_name": MODULE_MANIFEST["display_name"],
        "version": MODULE_MANIFEST["version"],
        "deck_api_version": MODULE_MANIFEST["deck_api_version"],
        "home_category": MODULE_MANIFEST["home_category"],
        "tabs": [
            {
                "tab_id": MODULE_MANIFEST["tab_definitions"][0]["tab_id"],
                "tab_name": MODULE_MANIFEST["tab_definitions"][0]["tab_name"],
                "get_content": build_tab,
            }
        ],
        "hooks": {},
        "shared_resource": None,
        "shared_resource_priority": 1000,
        "settings_sections": [],
    }
