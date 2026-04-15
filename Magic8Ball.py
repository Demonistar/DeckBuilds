from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup, Qt, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


MODULE_MANIFEST = {
    "key": "magic_8_ball",
    "display_name": "Magic 8-Ball",
    "version": "1.1.0",
    "deck_api_version": "1.0",
    "home_category": "Entertainment",
    "tab_definitions": [
        {
            "tab_id": "magic_8_ball_tab",
            "tab_name": "Magic 8-Ball",
        }
    ],
    "entry_function": "register",
    "description": "Persona-agnostic standalone Magic 8-Ball module with cached persona pool support.",
}


_CLASSIC_FALLBACK_POOL = [
    "It is certain.",
    "It is decidedly so.",
    "Without a doubt.",
    "Yes definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]


class Magic8BallRuntime:
    """Shared runtime/controller for tab UI, cache, and host bridge behavior."""

    def __init__(self, deck_api: dict[str, Any]):
        self._deck_api = deck_api
        self._log: Callable[[str], None] = deck_api.get("log") if callable(deck_api.get("log")) else (lambda _msg: None)
        self._cfg_get = deck_api.get("cfg_get") if callable(deck_api.get("cfg_get")) else (lambda _k, d=None: d)
        self._cfg_set = deck_api.get("cfg_set") if callable(deck_api.get("cfg_set")) else (lambda _k, _v: None)
        self._cfg_path = deck_api.get("cfg_path") if callable(deck_api.get("cfg_path")) else None
        self._request_ai = (
            deck_api.get("request_ai_interpretation") if callable(deck_api.get("request_ai_interpretation")) else None
        )
        self._request_ai_json = deck_api.get("request_ai_json") if callable(deck_api.get("request_ai_json")) else None

        self._pool: list[str] = list(_CLASSIC_FALLBACK_POOL)
        self._cache_path = self._resolve_cache_path()
        self._cache_key = "module_magic_8_ball_cache"

    def _resolve_cache_path(self) -> Optional[Path]:
        if not callable(self._cfg_path):
            return None
        try:
            path = self._cfg_path("magic_8_ball_pool_cache.json")
            if not path:
                return None
            cache_path = Path(path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            return cache_path
        except Exception as ex:
            self._log(f"Magic8Ball cache path unavailable: {ex}")
            return None

    def _persona_snapshot(self) -> dict[str, Any]:
        persona = self._cfg_get("persona", {})
        if not isinstance(persona, dict):
            persona = {}
        return {
            "name": str(persona.get("name") or ""),
            "face_prefix": str(persona.get("face_prefix") or ""),
            "sound_profile": str(persona.get("sound_profile") or ""),
            "vampire_states": bool(persona.get("vampire_states", False)),
            "torpor_system": bool(persona.get("torpor_system", False)),
        }

    def _persona_fingerprint(self) -> str:
        snapshot = self._persona_snapshot()
        blob = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _sanitize_pool(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    cleaned.append(text)
        return cleaned

    def _load_cached_pool(self) -> tuple[Optional[str], list[str]]:
        if self._cache_path and self._cache_path.exists():
            try:
                payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
                return str(payload.get("persona_fingerprint") or ""), self._sanitize_pool(payload.get("response_pool"))
            except Exception:
                return None, []

        cfg_payload = self._cfg_get(self._cache_key, {})
        if not isinstance(cfg_payload, dict):
            return None, []
        return str(cfg_payload.get("persona_fingerprint") or ""), self._sanitize_pool(cfg_payload.get("response_pool"))

    def _store_cached_pool(self, persona_fingerprint: str, pool: list[str]) -> None:
        payload = {
            "persona_fingerprint": persona_fingerprint,
            "response_pool": list(pool),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "persona_generated" if pool != _CLASSIC_FALLBACK_POOL else "classic_fallback",
        }

        if self._cache_path:
            try:
                self._cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as ex:
                self._log(f"Magic8Ball cache write failed: {ex}")

        try:
            self._cfg_set(self._cache_key, payload)
        except Exception:
            pass

    def _request_persona_pool(self) -> list[str]:
        request_context = {
            "intent": "generate_magic_8_ball_pool",
            "module": "magic_8_ball",
            "format": {
                "type": "json_array_of_strings",
                "min_items": 20,
                "max_items": 30,
            },
            "instruction": (
                "Generate Magic 8-Ball style oracle answers in the active persona voice. "
                "Keep answers concise, recognizable as 8-ball outcomes, and return only JSON array strings."
            ),
        }

        # Preferred structured path (future/optional host bridge).
        if callable(self._request_ai_json):
            try:
                result = self._request_ai_json("magic_8_ball", request_context)
                pool = self._sanitize_pool(result)
                if pool:
                    return pool
            except Exception as ex:
                self._log(f"Magic8Ball persona pool request_ai_json failed: {ex}")

        # Current host-owned hidden event path (best-effort fire-and-forget).
        if callable(self._request_ai):
            try:
                self._request_ai("magic_8_ball", request_context)
            except Exception as ex:
                self._log(f"Magic8Ball persona pool hidden request failed: {ex}")

        return []

    def ensure_pool_ready(self, force_refresh: bool = False) -> None:
        current_fp = self._persona_fingerprint()
        cached_fp, cached_pool = self._load_cached_pool()

        if not force_refresh and cached_fp == current_fp and cached_pool:
            self._pool = cached_pool
            return

        generated_pool = self._request_persona_pool()
        if generated_pool:
            self._pool = generated_pool
            self._store_cached_pool(current_fp, generated_pool)
            return

        self._pool = list(_CLASSIC_FALLBACK_POOL)
        self._store_cached_pool(current_fp, self._pool)

    def pick_answer(self) -> str:
        if not self._pool:
            self._pool = list(_CLASSIC_FALLBACK_POOL)
        return random.choice(self._pool)

    def handoff_interpretation(self, question: str, answer: str) -> bool:
        if not callable(self._request_ai):
            return False
        payload = {
            "intent": "persona_interpret_magic_8_ball_throw",
            "module": "magic_8_ball",
            "question": question,
            "answer": answer,
            "panel_display": answer,
            "instruction": (
                "Internally interpret this throw in persona voice with a short oracle-style follow-up. "
                "Do not ask for a second throw unless uncertainty is explicit."
            ),
        }
        try:
            return bool(self._request_ai("magic_8_ball", payload))
        except Exception:
            return False

    def handle_host_persona_changed(self) -> None:
        self.ensure_pool_ready(force_refresh=True)


class Magic8BallTab(QWidget):
    ACTIVE_DURATION_MS = 60_000

    def __init__(self, runtime: Magic8BallRuntime):
        super().__init__()
        self._runtime = runtime

        self._active_answer = ""
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._return_to_idle)

        self._fade_in_anim: Optional[QPropertyAnimation] = None
        self._pulse_anim: Optional[QSequentialAnimationGroup] = None
        self._fade_out_anim: Optional[QPropertyAnimation] = None

        self._build_ui()
        self._set_idle_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.question_input = QLineEdit(self)
        self.question_input.setPlaceholderText("Ask your yes/no question...")
        layout.addWidget(self.question_input)

        self.orb = QLabel("8", self)
        self.orb.setAlignment(Qt.AlignCenter)
        self.orb.setWordWrap(True)
        self.orb.setMinimumSize(260, 260)
        self.orb.setMaximumSize(360, 360)
        self.orb.setStyleSheet(
            """
            QLabel {
                color: #f3f6ff;
                font-size: 76px;
                font-weight: 800;
                border-radius: 130px;
                border: 1px solid rgba(220, 232, 255, 0.45);
                background: qradialgradient(
                    cx: 0.35, cy: 0.30, radius: 0.85,
                    fx: 0.32, fy: 0.25,
                    stop: 0 rgba(77, 88, 119, 0.78),
                    stop: 0.35 rgba(23, 28, 48, 0.92),
                    stop: 1 rgba(5, 8, 16, 0.98)
                );
                padding: 18px;
            }
            """
        )
        self.orb_opacity = QGraphicsOpacityEffect(self.orb)
        self.orb_opacity.setOpacity(1.0)
        self.orb.setGraphicsEffect(self.orb_opacity)
        layout.addWidget(self.orb, 0, Qt.AlignHCenter)

        self.throw_button = QPushButton("Throw the 8-Ball", self)
        self.throw_button.clicked.connect(self._on_throw)
        layout.addWidget(self.throw_button)

        layout.addStretch(1)

    def _set_idle_state(self) -> None:
        self._active_answer = ""
        self.orb.setText("8")
        self.orb.setStyleSheet(
            """
            QLabel {
                color: #f3f6ff;
                font-size: 76px;
                font-weight: 800;
                border-radius: 130px;
                border: 1px solid rgba(220, 232, 255, 0.45);
                background: qradialgradient(
                    cx: 0.35, cy: 0.30, radius: 0.85,
                    fx: 0.32, fy: 0.25,
                    stop: 0 rgba(77, 88, 119, 0.78),
                    stop: 0.35 rgba(23, 28, 48, 0.92),
                    stop: 1 rgba(5, 8, 16, 0.98)
                );
                padding: 18px;
            }
            """
        )
        self.orb_opacity.setOpacity(1.0)

    def _answer_font_px(self, answer: str) -> int:
        n = len(answer)
        if n > 95:
            return 25
        if n > 65:
            return 28
        if n > 42:
            return 31
        return 34

    def _apply_answer_style(self, answer: str) -> None:
        font_px = self._answer_font_px(answer)
        self.orb.setStyleSheet(
            f"""
            QLabel {{
                color: #ecf1ff;
                font-size: {font_px}px;
                font-weight: 700;
                border-radius: 130px;
                border: 1px solid rgba(220, 232, 255, 0.45);
                background: qradialgradient(
                    cx: 0.35, cy: 0.30, radius: 0.85,
                    fx: 0.32, fy: 0.25,
                    stop: 0 rgba(87, 104, 158, 0.70),
                    stop: 0.42 rgba(35, 44, 82, 0.92),
                    stop: 1 rgba(6, 10, 20, 0.98)
                );
                padding: 20px;
            }}
            """
        )

    def _stop_animations_and_timer(self) -> None:
        self._reset_timer.stop()
        for anim in (self._fade_in_anim, self._pulse_anim, self._fade_out_anim):
            if anim is not None:
                anim.stop()

    def _start_active_cycle(self, answer: str) -> None:
        self._stop_animations_and_timer()
        self._active_answer = answer
        self._apply_answer_style(answer)
        self.orb.setText(answer)
        self.orb_opacity.setOpacity(0.0)

        self._fade_in_anim = QPropertyAnimation(self.orb_opacity, b"opacity", self)
        self._fade_in_anim.setDuration(1000)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QEasingCurve.InOutSine)

        pulse_down = QPropertyAnimation(self.orb_opacity, b"opacity", self)
        pulse_down.setDuration(1700)
        pulse_down.setStartValue(1.0)
        pulse_down.setEndValue(0.52)
        pulse_down.setEasingCurve(QEasingCurve.InOutSine)

        pulse_up = QPropertyAnimation(self.orb_opacity, b"opacity", self)
        pulse_up.setDuration(1700)
        pulse_up.setStartValue(0.52)
        pulse_up.setEndValue(1.0)
        pulse_up.setEasingCurve(QEasingCurve.InOutSine)

        self._pulse_anim = QSequentialAnimationGroup(self)
        self._pulse_anim.addAnimation(pulse_down)
        self._pulse_anim.addAnimation(pulse_up)
        self._pulse_anim.setLoopCount(-1)

        def _begin_pulse() -> None:
            if self._pulse_anim is not None:
                self._pulse_anim.start()

        self._fade_in_anim.finished.connect(_begin_pulse)
        self._fade_in_anim.start()

        self._reset_timer.start(self.ACTIVE_DURATION_MS)

    def _return_to_idle(self) -> None:
        self._stop_animations_and_timer()

        self._fade_out_anim = QPropertyAnimation(self.orb_opacity, b"opacity", self)
        self._fade_out_anim.setDuration(900)
        self._fade_out_anim.setStartValue(self.orb_opacity.opacity())
        self._fade_out_anim.setEndValue(0.0)
        self._fade_out_anim.setEasingCurve(QEasingCurve.InOutSine)

        def _finish_idle() -> None:
            self._set_idle_state()

        self._fade_out_anim.finished.connect(_finish_idle)
        self._fade_out_anim.start()

    def _on_throw(self) -> None:
        question = self.question_input.text().strip()
        answer = self._runtime.pick_answer()
        self._start_active_cycle(answer)
        self._runtime.handoff_interpretation(question=question, answer=answer)



def register(deck_api: dict) -> dict:
    deck_api_version = str(deck_api.get("deck_api_version") or "")
    if deck_api_version != "1.0":
        raise RuntimeError(f"Unsupported deck API version: {deck_api_version}")

    runtime = Magic8BallRuntime(deck_api)

    def _on_startup() -> None:
        runtime.ensure_pool_ready(force_refresh=False)

    def _on_message(message: Any) -> None:
        # Future-safe persona refresh listener stub.
        # Current host dispatches user text strings here; ignore normal messages.
        if isinstance(message, dict):
            if str(message.get("event") or "").strip().lower() == "persona_changed":
                runtime.handle_host_persona_changed()
            return
        if not isinstance(message, str):
            return
        msg = message.strip().lower()
        if msg in {"[host_event] persona_changed", "__host_event__:persona_changed"}:
            runtime.handle_host_persona_changed()

    def _build_tab() -> QWidget:
        runtime.ensure_pool_ready(force_refresh=False)
        return Magic8BallTab(runtime=runtime)

    return {
        "deck_api_version": "1.0",
        "module_key": "magic_8_ball",
        "display_name": "Magic 8-Ball",
        "home_category": "Entertainment",
        "tabs": [
            {
                "tab_id": "magic_8_ball_tab",
                "tab_name": "Magic 8-Ball",
                "get_content": _build_tab,
            }
        ],
        "hooks": {
            "on_startup": _on_startup,
            "on_message": _on_message,
        },
    }
