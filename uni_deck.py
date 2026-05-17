"""
Universal deck runtime built on top of the proven GrimVeile deck implementation.

Architecture layers:
1) Python System Layer: truth, timers/state/memory/task/calendar IO, packaging.
2) Persona Layer: modular/toggleable style and behavior framing.
3) AI Layer: dialogue authoring via swappable model adapter contract.

This file intentionally preserves GrimVeile's working feature set by reusing the existing
runtime while reorganizing prompt assembly and model hand-off into explicit layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Protocol, Any

from PyQt6.QtWidgets import QApplication

import grimveil_deck as grim


APP_NAME = "ECHO DECK — UNIVERSAL RUNTIME"
APP_VERSION = "0.1.0"
APP_BUILD_DATE = "2026-04-01"
APP_FILENAME = "uni_deck.py"


@dataclass
class PersonaProfile:
    """Toggleable persona payload for style/identity framing."""

    enabled: bool = True
    identity: str = "GRIMVEILE-42"
    tone_style: str = "dry, strategic, sardonic, outcome-oriented"
    behavioral_framing: str = (
        "Answer user request first with concrete content; persona flavor wraps the answer and never replaces it."
    )
    autonomous_speech_flavor: str = (
        "Autonomous transmissions should feel like evolving internal strategic monologue, not repetitive one-liners."
    )
    startup_greeting_style: str = "Brief reactivation line plus continuity-oriented check-in."
    reaction_style: str = "Calm tactical framing under uncertainty; separate known facts vs inference."

    def to_prompt_block(self) -> str:
        if not self.enabled:
            return "Persona layer disabled. Use neutral analytical assistant voice."
        return (
            f"Persona identity: {self.identity}\n"
            f"Tone/style: {self.tone_style}\n"
            f"Behavioral framing: {self.behavioral_framing}\n"
            f"Autonomous speech flavor: {self.autonomous_speech_flavor}\n"
            f"Startup greeting style: {self.startup_greeting_style}\n"
            f"Reaction style: {self.reaction_style}"
        )


@dataclass
class OutputContract:
    """Describes what the AI response must do."""

    channel: str
    must_answer_first: bool = True
    max_style_intrusion: str = "medium"
    constraints: List[str] = field(default_factory=list)


@dataclass
class HandoffPacket:
    """Internal model hand-off payload (backend-agnostic)."""

    system_facts: Dict[str, Any]
    persistent_memory: List[Dict[str, Any]]
    session_context: List[Dict[str, str]]
    persona: PersonaProfile
    event_input: str
    output_contract: OutputContract


class AIAdapter(Protocol):
    """Swappable model/backend adapter contract."""

    def build_tactical_prompt(self, packet: HandoffPacket) -> str:
        ...

    def build_autonomous_prompt(self, packet: HandoffPacket, mode: str, turn_number: int, escalation: int, retry: bool) -> str:
        ...

    def build_startup_prompt(self, packet: HandoffPacket) -> str:
        ...


class GrimveilPromptAdapter:
    """Default adapter preserving GrimVeile-compatible prompt conventions."""

    def _facts_block(self, facts: Dict[str, Any]) -> str:
        return "\n".join(f"{k}: {v}" for k, v in facts.items())

    def _memory_block(self, memories: List[Dict[str, Any]]) -> str:
        if not memories:
            return "No relevant persistent memory was found for this prompt."
        lines = ["Relevant persistent memory records:"]
        for idx, item in enumerate(memories, start=1):
            lines.append(
                f"{idx}. [{item.get('type', 'memory')}] {item.get('title', 'Untitled')} — "
                f"{item.get('summary', '')} | keywords={', '.join(item.get('keywords', [])[:6])}"
            )
        return "\n".join(lines)

    def _contract_block(self, contract: OutputContract) -> str:
        items = "\n".join(f"- {c}" for c in contract.constraints)
        return (
            f"Output channel: {contract.channel}\n"
            f"Must answer first: {contract.must_answer_first}\n"
            f"Max style intrusion: {contract.max_style_intrusion}\n"
            f"Constraints:\n{items if items else '- none'}"
        )

    def build_tactical_prompt(self, packet: HandoffPacket) -> str:
        prompt = (
            "<|im_start|>system\n"
            f"{packet.system_facts['system_prompt']}\n"
            "\n[HANDOFF ORDER: system facts -> persistent memory -> session -> persona -> model knowledge]\n"
            f"{self._facts_block(packet.system_facts)}\n"
            f"{self._memory_block(packet.persistent_memory)}\n"
            f"{packet.persona.to_prompt_block()}\n"
            f"{self._contract_block(packet.output_contract)}\n"
            "If memory requested and records are absent, explicitly say no relevant memory was found.\n"
            "<|im_end|>\n"
        )
        for msg in packet.session_context:
            prompt += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
        prompt += f"<|im_start|>user\n{packet.event_input}<|im_end|>\n<|im_start|>assistant\n"
        return prompt

    def build_autonomous_prompt(self, packet: HandoffPacket, mode: str, turn_number: int, escalation: int, retry: bool) -> str:
        retry_line = "Retry requested due to duplicate/invalid prior output." if retry else "Fresh autonomous turn."
        return (
            "<|im_start|>system\n"
            f"{packet.system_facts['system_prompt']}\n"
            f"{packet.persona.to_prompt_block()}\n"
            "Author one autonomous Tactical Record line continuing internal thread continuity.\n"
            f"mode={mode}; turn={turn_number}; escalation={escalation}. {retry_line}\n"
            "Do not output labels, role names, or markdown. One concise line only.\n"
            "<|im_end|>\n"
            f"<|im_start|>user\n{packet.event_input}<|im_end|>\n<|im_start|>assistant\n"
        )

    def build_startup_prompt(self, packet: HandoffPacket) -> str:
        return (
            "<|im_start|>system\n"
            f"{packet.system_facts['system_prompt']}\n"
            f"{packet.persona.to_prompt_block()}\n"
            "Compose startup greeting for Tactical Record after boot diagnostics.\n"
            "1-2 sentences, continuity-aware, concrete and useful.\n"
            "<|im_end|>\n"
            f"<|im_start|>user\n{packet.event_input}<|im_end|>\n<|im_start|>assistant\n"
        )


class PythonSystemLayer:
    """Truth/action layer responsible for assembling deterministic runtime facts."""

    def __init__(self, deck: "UniversalDeck"):
        self.deck = deck

    def build_system_facts(self) -> Dict[str, Any]:
        now = datetime.now()
        return {
            "runtime_local_datetime": now.strftime("%m/%d/%Y %I:%M:%S %p"),
            "runtime_weekday": now.strftime("%A"),
            "anchor_state": f"{self.deck.anchor_state:.2f}",
            "status": self.deck.status,
            "system_prompt": self.deck.system_prompt,
            "date_time_truth_rule": "Never guess current date/time; use runtime context as truth source.",
        }

    def build_packet(
        self,
        event_input: str,
        persistent_memory: Optional[List[Dict[str, Any]]] = None,
        output_contract: Optional[OutputContract] = None,
    ) -> HandoffPacket:
        return HandoffPacket(
            system_facts=self.build_system_facts(),
            persistent_memory=persistent_memory or [],
            session_context=self.deck.history[-8:],
            persona=self.deck.persona_layer,
            event_input=event_input,
            output_contract=output_contract
            or OutputContract(
                channel="tactical_record",
                constraints=[
                    "Prioritize factual answer and actionable content.",
                    "Do not fabricate memory.",
                ],
            ),
        )


class TaskClassifier:
    """Expansion point for task/event classification and filtering."""

    def classify(self, text: str) -> Dict[str, Any]:
        t = text.lower()
        tags = []
        if "remind" in t:
            tags.append("reminder")
        if any(k in t for k in ("call", "meeting", "calendar", "appointment")):
            tags.append("calendar_event")
        return {"tags": tags, "priority": "normal"}


class UniversalDeck(grim.GrimveilDeck):
    """Universal architecture runtime preserving GrimVeile functionality."""

    def __init__(self):
        super().__init__()
        self.persona_layer = PersonaProfile(enabled=True)
        self.system_layer = PythonSystemLayer(self)
        self.ai_layer: AIAdapter = GrimveilPromptAdapter()
        self.task_classifier = TaskClassifier()

    def _build_final_prompt(self, current_text: str, retrieved):
        packet = self.system_layer.build_packet(
            event_input=current_text,
            persistent_memory=retrieved,
            output_contract=OutputContract(
                channel="tactical_record",
                constraints=[
                    "Answer the user request first.",
                    "Separate known facts from inference when uncertain.",
                    "Use persistent memory before model prior when relevant.",
                ],
            ),
        )
        return self.ai_layer.build_tactical_prompt(packet)

    def _build_unsolicited_prompt(self, mode: str, turn_number: int, escalation: int, thread_summary: str, last_output: str, retry: bool = False):
        event_input = (
            f"Thread summary: {thread_summary}\n"
            f"Last unsolicited output: {last_output}\n"
            "Continue the internal narrative coherently."
        )
        packet = self.system_layer.build_packet(
            event_input=event_input,
            persistent_memory=[],
            output_contract=OutputContract(
                channel="autonomous_speech",
                constraints=[
                    "One concise line.",
                    "No role labels.",
                    "No duplicated prior line.",
                ],
            ),
        )
        return self.ai_layer.build_autonomous_prompt(packet, mode, turn_number, escalation, retry)

    def _emit_wake_mode(self):
        # Preserve existing boot/diagnostic continuity behavior.
        super()._emit_wake_mode()

        # Tactical Record greeting defaults to AI-authored content.
        if not getattr(self, "model_loaded", False):
            return

        continuity = "Summarize startup continuity and greet command authority."
        packet = self.system_layer.build_packet(
            event_input=continuity,
            persistent_memory=self.memory.load_recent_memories(limit=3),
            output_contract=OutputContract(
                channel="startup_greeting",
                constraints=[
                    "1-2 sentences.",
                    "Useful and continuity-aware.",
                ],
            ),
        )
        prompt = self.ai_layer.build_startup_prompt(packet)
        worker = grim.DolphinWorker(self.model, self.tokenizer, prompt)
        worker.response_ready.connect(lambda text: self._append_chat("GRIMVEILE", self._normalize_persona_response(text, "startup")))
        worker.error_occurred.connect(lambda err: self.log_diagnostic(f"AI startup greeting fallback: {err}", level="WARN"))
        worker.status_changed.connect(self._set_status)
        worker.diagnostic.connect(self.log_diagnostic)
        worker.start()
        self.worker = worker


def main():
    app = QApplication([])
    app.setWindowIcon(grim.QIcon())
    window = UniversalDeck()
    window.show()
    sys_exit = app.exec()
    raise SystemExit(sys_exit)


if __name__ == "__main__":
    main()
