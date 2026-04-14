# ═══════════════════════════════════════════════════════════════════════════════
# ECHO DECK BUILDER
# Filename   : deck_builder.py
# Version    : 3.0.0
# Author     : Robert Mullins (Demonistar / Taured)
#
# Universal deck creation system.
# Input:  persona template file + module selections
# Output: complete self-contained AI companion deck
#
# STRUCTURE:
#   Section 1  — Imports, constants, color schemes, module registry, sound profiles
#   Section 2  — Persona template export and parser
#   Section 3  — Face extraction (ZIP + folder), icon conversion
#   Section 4  — Sound generation per profile
#   Section 5  — Deck template and writer
#   Section 6  — Setup worker (background build thread)
#   Section 7  — UI helper widgets
#   Section 8  — Main builder dialog
#   Section 9  — Entry point
#
# Standing Rules:
#   - NEVER rename this file
#   - Zero hardcoded personas — all persona data from loaded template files only
#   - Unchecked modules are ABSENT from the generated deck (no stubs)
#   - All deck output goes into [DeckName]/ subfolder of chosen directory
#   - Python is handler. AI is speaker.
# ═══════════════════════════════════════════════════════════════════════════════
from __future__ import annotations

import sys
import os
import json
import math
import wave
import struct
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── BOOTSTRAP PySide6 ─────────────────────────────────────────────────────────
try:
    from PySide6.QtWidgets import (
        QApplication, QDialog, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
        QRadioButton, QButtonGroup, QFileDialog, QTextEdit, QProgressBar,
        QScrollArea, QFrame, QGroupBox, QMessageBox, QTabWidget,
        QSizePolicy, QSplitter, QToolButton, QSplitterHandle, QMenu
    )
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
    from PySide6.QtGui import QFont, QColor, QPixmap, QIcon, QPalette
except ImportError:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "PySide6 is required.\n\nRun: pip install PySide6",
            "Deck Builder — Missing Dependency", 0x10
        )
    except Exception:
        print("CRITICAL: pip install PySide6")
    sys.exit(1)

PILLOW_OK = False
try:
    from PIL import Image as PILImage
    PILLOW_OK = True
except ImportError:
    pass

# ── BUILDER CONSTANTS ─────────────────────────────────────────────────────────
BUILDER_VERSION = "1.0.0"
SCRIPT_DIR      = Path(__file__).resolve().parent
BUILDER_UI_STATE_PATH = SCRIPT_DIR / ".deck_builder_ui_state.json"
DECK_VERSION    = "2.0.0"
AI_STATE_KEYS   = [
    "WITCHING HOUR",
    "DEEP NIGHT",
    "TWILIGHT FADING",
    "DORMANT",
    "RESTLESS SLEEP",
    "STIRRING",
    "AWAKENED",
    "HUNTING",
]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1A — COLOR SCHEMES
# Light/dark mode for the builder itself (not the deck).
# Persona-specific colors live in PERSONAS below.
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMES = {
    "dark": {
        "bg":          "#0a0a0f",
        "bg2":         "#0f0f18",
        "bg3":         "#141420",
        "panel":       "#101018",
        "border":      "#2a2a40",
        "primary":     "#5588cc",
        "primary_dim": "#1a2840",
        "gold":        "#ccaa55",
        "text":        "#d0d0e8",
        "text_dim":    "#606080",
        "green":       "#44aa66",
        "red":         "#cc4444",
        "orange":      "#cc8844",
        "purple":      "#8855cc",
    },
    "light": {
        "bg":          "#f0f2f5",
        "bg2":         "#e8eaed",
        "bg3":         "#ffffff",
        "panel":       "#f8f9fa",
        "border":      "#c0c4cc",
        "primary":     "#2255aa",
        "primary_dim": "#c8d8f0",
        "gold":        "#996622",
        "text":        "#1a1a2e",
        "text_dim":    "#606070",
        "green":       "#226633",
        "red":         "#aa2222",
        "orange":      "#aa6622",
        "purple":      "#5522aa",
    },
}

_ACTIVE_SCHEME = "dark"

def S(key: str) -> str:
    """Get current scheme color by key."""
    return SCHEMES[_ACTIVE_SCHEME].get(key, "#ff00ff")

def set_scheme(name: str) -> None:
    global _ACTIVE_SCHEME
    if name in SCHEMES:
        _ACTIVE_SCHEME = name



# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1B — PERSONA SYSTEM
#
# Personas come ENTIRELY from loaded .txt template files.
# There are NO built-in personas, NO hardcoded names, colors, or prompts.
#
# To create a persona: fill in a template file and load it in the builder.
# Export a blank template from the builder's Persona section.
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1C — MODULE REGISTRY
#
# Modules are discovered dynamically from the .\Modules\ subfolder at startup.
# Each module provides a manifest.json (or <name>.json) with its metadata.
# No modules are hardcoded here — drop a folder into .\Modules\ and it appears.
#
# TO ADD A NEW MODULE:
#   1. Create .\Modules\<ModuleName>\manifest.json
#   2. Restart the builder — it will appear automatically in the checklist.
# ═══════════════════════════════════════════════════════════════════════════════

MODULES_DIR = SCRIPT_DIR / "Modules"


def _normalize_module_key(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def _load_module_manifest(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    key = str(data.get("key") or data.get("id") or path.stem).strip()
    key = _normalize_module_key(key)
    if not key:
        return None

    display_name = str(data.get("display_name") or data.get("name") or key.replace("_", " ").title()).strip()
    slot_key = str(data.get("slot_key") or f"MODULE_{key.upper()}").strip()

    return {
        "key": key,
        "display_name": display_name,
        "category": str(data.get("category") or "External Modules"),
        "status": "built",
        "description": str(data.get("description") or ""),
        "tab_name": str(data.get("tab_name") or display_name),
        "slot_key": slot_key,
        "requires": list(data.get("requires") or []),
        "requirements": list(data.get("requirements") or []),
        "default_on": bool(data.get("default_on", False)),
        "runtime_marker": str(data.get("runtime_marker") or "").strip(),
        "manifest_path": str(path),
        "module_path": str(path.parent),
    }


def discover_optional_modules(modules_dir: Path, log_fn=None) -> dict[str, dict]:
    discovered: dict[str, dict] = {}
    if not modules_dir.exists():
        return discovered

    manifests: list[Path] = []
    manifests.extend(sorted(modules_dir.glob("*.json")))
    manifests.extend(sorted(modules_dir.glob("*/manifest.json")))

    for mf in manifests:
        mod = _load_module_manifest(mf)
        if not mod:
            if log_fn:
                log_fn(f"[MODULES][WARN] Invalid manifest skipped: {mf}")
            continue
        key = _normalize_module_key(str(mod.get("key", "")) or mf.stem)
        if not key:
            continue
        if key in discovered:
            if log_fn:
                log_fn(f"[MODULES][WARN] Duplicate module key skipped: {key} ({mf})")
            continue
        discovered[key] = mod

    return dict(sorted(discovered.items(), key=lambda kv: kv[1].get("display_name", kv[0]).lower()))


MODULES: dict[str, dict] = discover_optional_modules(MODULES_DIR)

MODULE_CODE: dict[str, Optional[str]] = {}


SOUND_PROFILES: dict[str, dict] = {
    "gothic_bell": {
        "status":      "built",
        "description": "Descending minor bells. Cathedral resonance. Morganna's profile.",
        "waveform":    {"sine": 0.75, "square": 0.15, "saw": 0.10},
        "notes_alert": [(440.0, 0.6), (369.99, 0.9)],
        "notes_startup": [(220.0, 0.25), (261.63, 0.25), (329.63, 0.25), (440.0, 0.8)],
        "notes_idle":    [(146.83, 1.2)],
        "notes_shutdown": [(440.0, 0.3), (329.63, 0.3), (261.63, 0.3), (220.0, 0.8)],
        "error_type":  "tritone",
    },
    "electronic_pulse": {
        "status":      "built",
        "description": "Sharp electronic pulses. Square wave dominant. GrimVeil's profile.",
        "waveform":    {"sine": 0.20, "square": 0.65, "saw": 0.15},
        "notes_alert": [(880.0, 0.15), (660.0, 0.15), (880.0, 0.2)],
        "notes_startup": [(440.0, 0.1), (660.0, 0.1), (880.0, 0.1), (1100.0, 0.3)],
        "notes_idle":    [(440.0, 0.3)],
        "notes_shutdown": [(880.0, 0.1), (660.0, 0.1), (440.0, 0.1), (220.0, 0.4)],
        "error_type":  "buzz",
    },
    "warm_chime": {
        "status":      "built",
        "description": "Soft warm chimes. Sine dominant. Assistant's profile.",
        "waveform":    {"sine": 0.85, "square": 0.05, "saw": 0.10},
        "notes_alert": [(523.25, 0.4), (659.25, 0.5)],
        "notes_startup": [(261.63, 0.2), (329.63, 0.2), (392.0, 0.2), (523.25, 0.6)],
        "notes_idle":    [(523.25, 0.8)],
        "notes_shutdown": [(523.25, 0.2), (392.0, 0.2), (329.63, 0.2), (261.63, 0.6)],
        "error_type":  "dissonant",
    },
    "soft_ping": {
        "status":      "built",
        "description": "Light casual ping. Friendly and unobtrusive. Friend's profile.",
        "waveform":    {"sine": 0.90, "square": 0.05, "saw": 0.05},
        "notes_alert": [(880.0, 0.2)],
        "notes_startup": [(440.0, 0.15), (880.0, 0.4)],
        "notes_idle":    [(660.0, 0.3)],
        "notes_shutdown": [(880.0, 0.15), (440.0, 0.4)],
        "error_type":  "low_buzz",
    },
    "default_chime": {
        "status":      "built",
        "description": "Neutral chime. Clean, functional. Default persona's profile.",
        "waveform":    {"sine": 0.70, "square": 0.20, "saw": 0.10},
        "notes_alert": [(660.0, 0.3), (440.0, 0.3)],
        "notes_startup": [(440.0, 0.2), (550.0, 0.2), (660.0, 0.4)],
        "notes_idle":    [(440.0, 0.5)],
        "notes_shutdown": [(660.0, 0.2), (550.0, 0.2), (440.0, 0.4)],
        "error_type":  "buzz",
    },

    # ── STUBS (profiles defined, generation not yet written) ──────────────────
    "glitch": {
        "status":      "stub",
        "description": "Glitchy digital artifacts. VEX's profile.",
        "waveform":    {"sine": 0.10, "square": 0.60, "saw": 0.30},
        "notes_alert": [],
        "notes_startup": [],
        "notes_idle":    [],
        "notes_shutdown": [],
        "error_type":  "static",
    },
    "theatrical": {
        "status":      "stub",
        "description": "Dramatic flourishes. Missy's profile.",
        "waveform":    {"sine": 0.50, "square": 0.30, "saw": 0.20},
        "notes_alert": [],
        "notes_startup": [],
        "notes_idle":    [],
        "notes_shutdown": [],
        "error_type":  "dramatic",
    },
    "arcane_chime": {
        "status":      "stub",
        "description": "Ethereal magical tones. Seraphine's profile.",
        "waveform":    {"sine": 0.80, "square": 0.10, "saw": 0.10},
        "notes_alert": [],
        "notes_startup": [],
        "notes_idle":    [],
        "notes_shutdown": [],
        "error_type":  "dissonant",
    },
    "earthen_tone": {
        "status":      "stub",
        "description": "Deep resonant tones. Ur-Nanna's profile.",
        "waveform":    {"sine": 0.60, "square": 0.20, "saw": 0.20},
        "notes_alert": [],
        "notes_startup": [],
        "notes_idle":    [],
        "notes_shutdown": [],
        "error_type":  "low_buzz",
    },
    "robot_blip": {
        "status":      "stub",
        "description": "Cute robot sounds. BeepBoopGF's profile.",
        "waveform":    {"sine": 0.30, "square": 0.60, "saw": 0.10},
        "notes_alert": [],
        "notes_startup": [],
        "notes_idle":    [],
        "notes_shutdown": [],
        "error_type":  "buzz",
    },
}

# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1E — FACE RENAME MAPPING
#
# Maps ZIP/folder stem (lowercase) → final Morganna_*.png suffix.
# Used by the face extraction pipeline.
# Works for any persona — just replaces "Morganna" with the persona's face_prefix.
# ═══════════════════════════════════════════════════════════════════════════════

FACE_RENAME_MAP: dict[str, str] = {
    "alert":       "Alert",
    "angry":       "Angry",
    "cheatmode":   "Cheat_Mode",
    "cheat_mode":  "Cheat_Mode",
    "cheat mode":  "Cheat_Mode",
    "concerned":   "Concerned",
    "envious":     "Envious",
    "finger":      "Finger",
    "flirty":      "Flirty",
    "flustered":   "Flustered",
    "focused":     "Focused",
    "happy":       "Happy",
    "humiliated":  "Humiliated",
    "impressed":   "Impressed",
    "neutral":     "Neutral",
    "panicked":    "Panicked",
    "plotting":    "Plotting",
    "relieved":    "Relieved",
    "sad":         "Sad_Crying",
    "sad crying":  "Sad_Crying",
    "sad_crying":  "Sad_Crying",
    "shocked":     "Shocked",
    "smug":        "Smug",
    "suspicious":  "Suspicious",
    "victory":     "Victory",
    # GrimVeil additions (if needed)
    "docked":      "Docked",
    "nearby":      "Nearby",
    "absent":      "Absent",
    # Generic emotions any persona might have
    "confused":    "Confused",
    "curious":     "Curious",
    "bored":       "Bored",
    "excited":     "Excited",
    "nervous":     "Nervous",
    "proud":       "Proud",
    "disgusted":   "Disgusted",
    "tired":       "Tired",
    "love":        "Love",
    "wink":        "Wink",
}

# ── END OF SECTION 1 ──────────────────────────────────────────────────────────
# Next: Section 2 — Persona template export and parser


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PERSONA TEMPLATE EXPORT AND PARSER
#
# Export: writes a formatted .txt template the user fills in.
#         Auto-opens in default text editor after writing.
# Parser: reads a filled-in .txt template back into a persona dict.
#         Validates required fields. Returns errors if malformed.
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PERSONA TEMPLATE EXPORT AND PARSER
# ═══════════════════════════════════════════════════════════════════════════════

PERSONA_TEMPLATE_TEXT = """\
# ═══════════════════════════════════════════════════════════════════════
# ECHO DECK — PERSONA TEMPLATE
# ═══════════════════════════════════════════════════════════════════════
#
# Fill in each section below.
# Lines starting with # are COMMENTS — ignored by the parser.
# Required sections are marked with [REQUIRED].
# Leave optional sections blank to use defaults.
# Do not remove section headers (lines in [BRACKETS]).
#
# TIP: Hand this file to an AI with your persona concept and ask it
# to fill in the sections. Then load the result in deck_builder.
#
# COGNITIVE ANCHORS — what makes this persona tick:
#   These are 2-4 things the persona notices FIRST in any input.
#   They shape responses more than personality adjectives.
#   Bad anchor:  "She is wise and mysterious"
#   Good anchor: "What power structure does this reveal?"
# ═══════════════════════════════════════════════════════════════════════


[NAME]
# [REQUIRED] The persona's name. Used as folder name, window title, file prefix.
# Keep it a single word or use underscores for spaces.
# Examples:
#   Alex
#   ARIA_7
#   Seraphel
#   The_Cartographer
YOUR_PERSONA_NAME_HERE


[DESCRIPTION]
# One sentence describing this persona. Shown in the builder dropdown.
# Examples:
#   Friendly life coach. Warm, direct, no-nonsense.
#   Robot systems analyst. Clinical precision. Zero sentiment.
#   Ancient elven lore-keeper. Centuries of quiet wisdom.
A brief description of this persona.


[SYSTEM_PROMPT]
# [REQUIRED] The core instruction given to the AI on every message.
# 3-6 sentences is ideal. Over-loading causes character drift.
# Do NOT use "You must always..." — just describe who they are.
# Examples:
#   You are Alex, a straightforward life coach with a warm but direct
#   manner. You ask clarifying questions before giving advice. You speak
#   plainly, avoid jargon, and always bring things back to action steps.
#
#   You are ARIA-7, a systems analyst unit. You process all input as
#   structured data and respond with precise, efficient language. You do
#   not simulate emotion but you do simulate patience.
#
#   You are Seraphel, an elven lore-keeper who has catalogued the world
#   for six centuries. You speak with gentle authority and long memory.
#   You find human urgency both endearing and slightly baffling.
You are [NAME], [brief identity]. You [speak/respond] with [characteristic].
You [key behavioral trait]. You [another key trait].


[COGNITIVE_ANCHORS]
# 2-4 first-filter questions. One per line. 4 maximum.
# These run BEFORE the persona generates any response.
# Examples:
#   What does this person actually need right now, vs what they asked for?
#   What is the most efficient path to a solution here?
#   What does history or precedent say about this situation?
#   Is this person safe and grounded right now?
What is the most important thing to notice about this input?
What would [NAME] think of this immediately?


[COLORS]
# Use standard color names OR hex codes (#rrggbb). Both work.
# ── Named colors ─────────────────────────────────────────────────────
#   red, crimson, darkred, tomato, coral, salmon
#   blue, steelblue, royalblue, navy, midnightblue, deepskyblue
#   green, forestgreen, darkgreen, seagreen, mediumaquamarine
#   purple, mediumpurple, indigo, rebeccapurple, plum
#   orange, darkorange, goldenrod, gold, khaki
#   white, snow, ghostwhite, lightgray, gray, darkgray
#   black, midnightblue, darkslategray
# ── Hex examples (name = hex equivalent) ─────────────────────────────
#   royalblue   = #4169E1     |  you can use either one
#   goldenrod   = #DAA520     |  both work exactly the same
#   indigo      = #4B0082     |  pick whichever is clearer to you
#   forestgreen = #228B22     |
#   coral       = #FF7F50     |
# Full list: https://www.w3.org/TR/css-color-3/#svg-color
# TIP: Google "CSS color names" for a visual picker
# ─────────────────────────────────────────────────────────────────────
# PRIMARY    = main accent (buttons, borders, highlights)
# SECONDARY  = main text and label color
# ACCENT     = emphasis, hover states
# BACKGROUND = deepest background (usually very dark)
# PANEL      = slightly lighter than background
# BORDER     = edge/divider lines
# TEXT       = main readable text color
# TEXT_DIM   = subdued text, timestamps, hints
PRIMARY=royalblue
SECONDARY=goldenrod
ACCENT=coral
BACKGROUND=black
PANEL=darkslategray
BORDER=dimgray
TEXT=snow
TEXT_DIM=gray


[FONT_FAMILY]
# The font style used throughout the deck interface.
# Options: serif | sans-serif | monospace
# serif      — elegant, classic (good for fantasy, gothic, historical)
# sans-serif — clean, modern (good for sci-fi, professional, everyday)
# monospace  — technical, terminal (good for robots, AI, hackers)
# Leave blank to use: serif
serif


[GENDER]
# Pronouns used in system messages, awakening lines, and flavor text.
# Options: she/her | he/him | they/them | it/its | none
# "none" removes pronouns entirely — useful for robots or abstract entities.
# Leave blank to use: they/them
they/them


[AWAKENING_LINE]
# One short atmospheric line shown in the startup log.
# This is flavor — make it feel like the persona.
# Examples:
#   The shadows lean forward to listen...          (gothic)
#   All systems nominal. Standing by.              (robot)
#   The old wood creaks. The maps spread open.     (cartographer)
#   Signal acquired from local space.              (alien)
#   Coffee's on. What are we solving today?        (everyday)
# Leave blank for a generic default.
Connecting...


[UI_LABELS]
# Text throughout the deck interface. Make it feel like this persona.
# ── Examples by persona type ──────────────────────────────────────────
#   Fantasy:   CHAT_WINDOW=THE CHRONICLE     SEND_BUTTON=SPEAK
#   Robot:     CHAT_WINDOW=DATA STREAM       SEND_BUTTON=TRANSMIT
#   Everyday:  CHAT_WINDOW=CONVERSATION      SEND_BUTTON=SEND
#   Gothic:    CHAT_WINDOW=SÉANCE RECORD     SEND_BUTTON=INVOKE
#   Alien:     CHAT_WINDOW=OBSERVATION LOG   SEND_BUTTON=RELAY
# ─────────────────────────────────────────────────────────────────────
WINDOW_TITLE=ECHO DECK — [NAME]
CHAT_WINDOW=CONVERSATION
SEND_BUTTON=SEND
INPUT_PLACEHOLDER=Type your message...
GENERATING_STATUS=◉ THINKING
IDLE_STATUS=◉ IDLE
OFFLINE_STATUS=◉ OFFLINE
SUSPENSION_LABEL=Sleep
RUNES=— ECHO DECK —
MIRROR_LABEL=MIRROR
EMOTIONS_LABEL=EMOTIONS
LEFT_ORB_TITLE=PRIMARY
LEFT_ORB_LABEL=RESOURCE
CYCLE_TITLE=CYCLE
RIGHT_ORB_TITLE=SECONDARY
RIGHT_ORB_LABEL=RESERVE
ESSENCE_TITLE=ESSENCE
ESSENCE_PRIMARY=PRIMARY STATE
ESSENCE_SECONDARY=SECONDARY STATE
FOOTER_STRIP_LABEL=STATE


[SOUND_PROFILE]
# Choose one: gothic_bell | electronic_pulse | warm_chime | soft_ping |
#             default_chime | glitch | theatrical | arcane_chime |
#             earthen_tone | robot_blip
# Leave blank for default_chime.
default_chime


[SPECIAL_SYSTEMS]
# Comma-separated list of special behavioral systems to activate.
# Options:
#   vampire_states — time-of-day awareness affecting behavior
#   torpor         — model suspend/resume system
#   anchor_entity  — companion object with proximity states
# Leave blank for none. Most personas leave this blank.


[ANCHOR_ENTITY]
# Only fill this if anchor_entity is in SPECIAL_SYSTEMS above.
# The companion object that affects this persona's behavior.
# Example:
#   NAME=E-42
#   DESCRIPTION=Small mechanical crocodile cassette module
#   STATE_1=docked
#   STATE_2=nearby
#   STATE_3=absent
# Leave blank if not using anchor_entity.


[FACE_PREFIX]
# Prefix used for face image filenames.
# Example: "Alex" → face files named Alex_Neutral.png, Alex_Alert.png
# Defaults to the persona NAME if left blank.
"""

def export_persona_template(output_path: Optional[Path] = None) -> Path:
    """Write the blank persona template .txt file."""
    if output_path is None:
        output_path = SCRIPT_DIR / "personas" / "echo_deck_persona_template.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(PERSONA_TEMPLATE_TEXT, encoding="utf-8")
    return output_path


def parse_persona_template(file_path: Path) -> tuple[Optional[dict], list[str]]:
    """
    Parse a filled-in persona template .txt file.
    Returns (persona_dict, errors).
    persona_dict is None if parsing failed critically.
    """
    if not file_path.exists():
        return None, [f"File not found: {file_path}"]
    try:
        raw = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return None, [f"Could not read file: {e}"]

    errors: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: Optional[str] = None

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].upper()
            if current_section not in sections:
                sections[current_section] = []
            continue
        if current_section is not None and stripped:
            sections[current_section].append(stripped)

    # ── NAME (required) ───────────────────────────────────────────────
    name_lines = sections.get("NAME", [])
    name = name_lines[0].strip() if name_lines else ""
    if not name or name == "YOUR_PERSONA_NAME_HERE":
        return None, ["[NAME] section is required and must be filled in."]

    # ── SYSTEM_PROMPT (required) ──────────────────────────────────────
    prompt_lines = sections.get("SYSTEM_PROMPT", [])
    system_prompt = " ".join(prompt_lines).strip()
    if not system_prompt or "You are [NAME]" in system_prompt:
        return None, ["[SYSTEM_PROMPT] section is required and must be filled in."]

    # ── DESCRIPTION ───────────────────────────────────────────────────
    desc_lines = sections.get("DESCRIPTION", [])
    description = " ".join(desc_lines).strip() or f"{name} — custom persona"

    # ── COGNITIVE_ANCHORS ─────────────────────────────────────────────
    anchor_lines = sections.get("COGNITIVE_ANCHORS", [])
    cognitive_anchors = [a.strip() for a in anchor_lines
                         if a.strip() and "PERSONA_NAME" not in a][:4]

    # ── COLORS — accept named colors OR hex codes ─────────────────────
    color_defaults = {
        "primary":    "#5588cc",
        "secondary":  "#ccaa55",
        "accent":     "#8855cc",
        "background": "#0a0a0f",
        "panel":      "#101018",
        "border":     "#2a2a40",
        "text":       "#d0d0e8",
        "text_dim":   "#606080",
    }
    colors = color_defaults.copy()
    for line in sections.get("COLORS", []):
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip()
            if key in colors and val:
                # Accept hex (#rrggbb / #rgb) or any named CSS color
                if val.startswith("#") and len(val) in (4, 7):
                    colors[key] = val
                elif val and not val.startswith("#"):
                    # Named color — pass through as-is (Qt/CSS validate at render)
                    colors[key] = val
                else:
                    errors.append(f"[COLORS] Invalid color value for {key}: {val!r} — using default")

    # ── UI_LABELS ─────────────────────────────────────────────────────
    label_defaults = {
        "window_title":       f"ECHO DECK — {name.upper()}",
        "chat_window":        "CONVERSATION",
        "send_button":        "SEND",
        "input_placeholder":  "Type your message...",
        "generating_status":  "◉ THINKING",
        "idle_status":        "◉ IDLE",
        "offline_status":     "◉ OFFLINE",
        "torpor_status":      "◉ SUSPENDED",
        "suspension_label":   "",
        "runes":              "— ECHO DECK —",
        "mirror_label":       "MIRROR",
        "emotions_label":     "EMOTIONS",
        "left_orb_title":     "PRIMARY",
        "left_orb_label":     "RESOURCE",
        "cycle_title":        "CYCLE",
        "right_orb_title":    "SECONDARY",
        "right_orb_label":    "RESERVE",
        "essence_title":      "ESSENCE",
        "essence_primary":    "PRIMARY STATE",
        "essence_secondary":  "SECONDARY STATE",
        "footer_strip_label": "STATE",
    }
    ui_labels = label_defaults.copy()
    for line in sections.get("UI_LABELS", []):
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip()
            if key in ui_labels:
                ui_labels[key] = val

    # ── FONT_FAMILY ───────────────────────────────────────────────────
    font_lines = sections.get("FONT_FAMILY", [])
    font_raw = font_lines[0].strip().lower() if font_lines else "serif"
    font_map = {
        "serif":      "'Georgia', 'Times New Roman', serif",
        "sans-serif": "'Segoe UI', 'Arial', sans-serif",
        "monospace":  "'Consolas', 'Courier New', monospace",
    }
    if font_raw not in font_map:
        errors.append(f"[FONT_FAMILY] Unknown value '{font_raw}' — using serif")
        font_raw = "serif"
    font_family = font_map[font_raw]

    # ── GENDER / PRONOUNS ─────────────────────────────────────────────
    gender_lines = sections.get("GENDER", [])
    gender_raw = gender_lines[0].strip().lower() if gender_lines else "they/them"
    valid_genders = {"she/her", "he/him", "they/them", "it/its", "none"}
    if gender_raw not in valid_genders:
        errors.append(f"[GENDER] Unknown value '{gender_raw}' — using they/them")
        gender_raw = "they/them"
    gender_map = {
        "she/her":   {"subject": "she",  "object": "her",  "possessive": "her"},
        "he/him":    {"subject": "he",   "object": "him",  "possessive": "his"},
        "they/them": {"subject": "they", "object": "them", "possessive": "their"},
        "it/its":    {"subject": "it",   "object": "it",   "possessive": "its"},
        "none":      {"subject": "",     "object": "",     "possessive": ""},
    }
    pronouns = gender_map.get(gender_raw, gender_map["they/them"])

    # ── AWAKENING_LINE ────────────────────────────────────────────────
    awaken_lines = sections.get("AWAKENING_LINE", [])
    awakening_line = awaken_lines[0].strip() if awaken_lines else "Connecting..."
    if not awakening_line or awakening_line.startswith("#"):
        awakening_line = "Connecting..."

    # ── SOUND_PROFILE ─────────────────────────────────────────────────
    sound_lines = sections.get("SOUND_PROFILE", [])
    sound_profile = sound_lines[0].strip() if sound_lines else "default_chime"
    if sound_profile not in SOUND_PROFILES:
        errors.append(f"[SOUND_PROFILE] Unknown profile '{sound_profile}' — using default_chime")
        sound_profile = "default_chime"

    # ── SPECIAL_SYSTEMS ───────────────────────────────────────────────
    special_lines = sections.get("SPECIAL_SYSTEMS", [])
    special_raw = " ".join(special_lines)
    special_systems = [s.strip() for s in special_raw.split(",")
                       if s.strip() in ("vampire_states", "torpor", "anchor_entity")]

    # ── ANCHOR_ENTITY ─────────────────────────────────────────────────
    anchor_entity = None
    if "anchor_entity" in special_systems:
        ae_lines = sections.get("ANCHOR_ENTITY", [])
        ae_data: dict[str, str] = {}
        for line in ae_lines:
            if "=" in line:
                k, _, v = line.partition("=")
                ae_data[k.strip().upper()] = v.strip()
        if "NAME" in ae_data:
            states = {}
            for i in range(1, 10):
                sk = f"STATE_{i}"
                if sk in ae_data:
                    state_name = ae_data[sk].lower()
                    states[state_name] = {"label": state_name.upper(), "sound_state": state_name}
            anchor_entity = {
                "name":        ae_data.get("NAME", "Companion"),
                "description": ae_data.get("DESCRIPTION", ""),
                "states":      states,
            }
        else:
            errors.append("[ANCHOR_ENTITY] NAME not defined — anchor_entity disabled")
            special_systems.remove("anchor_entity")

    # ── FACE_PREFIX ───────────────────────────────────────────────────
    prefix_lines = sections.get("FACE_PREFIX", [])
    face_prefix = prefix_lines[0].strip() if prefix_lines else name

    # ── Build persona dict ────────────────────────────────────────────
    persona = {
        "status":            "loaded",
        "description":       description,
        "system_prompt":     system_prompt,
        "cognitive_anchors": cognitive_anchors,
        "colors":            colors,
        "ui_labels":         ui_labels,
        "font_family":       font_family,
        "pronouns":          pronouns,
        "awakening_line":    awakening_line,
        "face_prefix":       face_prefix,
        "sound_profile":     sound_profile,
        "special_systems":   special_systems,
        "anchor_entity":     anchor_entity,
        "vampire_states":    "vampire_states" in special_systems,
        "torpor_system":     "torpor" in special_systems,
        "_source_file":      str(file_path),
        "_loaded_name":      name,
    }

    return persona, errors

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — FACE EXTRACTION AND ICON CONVERSION
#
# Handles: ZIP extraction, folder scanning, face renaming, icon generation.
# Works for any persona — prefix is passed in, not hardcoded.
# Returns detailed results so the UI can show what happened.
# ═══════════════════════════════════════════════════════════════════════════════

import struct
import io


def extract_faces(
    source: str,          # path to ZIP file OR folder
    dest_dir: Path,       # where to write renamed images
    face_prefix: str,     # e.g. "Morganna" → Morganna_Alert.png
    deck_name: str,       # e.g. "Morganna" → look for Morganna.png as icon
    log_fn=None,          # optional callable(str) for progress messages
) -> dict:
    """
    Extract and rename face images from a ZIP file or folder.

    Rename logic:
      1. Strip extension → get stem (e.g. "sad crying")
      2. Look up in FACE_RENAME_MAP → get suffix (e.g. "Sad_Crying")
      3. Rename to [prefix]_[suffix].png (e.g. "Morganna_Sad_Crying.png")
      4. If not in map → capitalize and prefix anyway (unknown but stored)

    Also looks for [deck_name].png to use as the application icon.

    Returns dict with keys:
        extracted   int   — files successfully renamed and written
        skipped     int   — files that already existed (not overwritten)
        unrecognized int  — files not in FACE_RENAME_MAP (still copied)
        icon_path   Path or None — path to [deck_name].png if found
        errors      list[str]
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    result = {
        "extracted":     0,
        "skipped":       0,
        "unrecognized":  0,
        "icon_path":     None,
        "errors":        [],
    }

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(source)

    # ── Collect (stem_lower, raw_bytes) pairs ─────────────────────────
    images: list[tuple[str, str, bytes]] = []
    # (stem_lower, original_name, bytes)

    if source_path.is_file() and source_path.suffix.lower() == ".zip":
        _log(f"Reading ZIP: {source_path.name}")
        try:
            with zipfile.ZipFile(str(source_path), "r") as zf:
                for member in zf.namelist():
                    if not member.lower().endswith(".png"):
                        continue
                    stem_raw   = Path(member).stem
                    stem_lower = stem_raw.lower().strip()
                    data       = zf.read(member)
                    images.append((stem_lower, stem_raw, data))
        except zipfile.BadZipFile as e:
            result["errors"].append(f"Invalid ZIP: {e}")
            return result
        except Exception as e:
            result["errors"].append(f"ZIP read error: {e}")
            return result

    elif source_path.is_dir():
        _log(f"Reading folder: {source_path}")
        for img_path in source_path.glob("*.png"):
            stem_raw   = img_path.stem
            stem_lower = stem_raw.lower().strip()
            try:
                data = img_path.read_bytes()
                images.append((stem_lower, stem_raw, data))
            except Exception as e:
                result["errors"].append(f"Could not read {img_path.name}: {e}")

    else:
        result["errors"].append(
            f"Source is neither a ZIP file nor a folder: {source}"
        )
        return result

    if not images:
        result["errors"].append("No PNG files found in source.")
        return result

    _log(f"Found {len(images)} PNG file(s) — processing...")

    # ── Check for icon image ([deck_name].png, case-insensitive) ──────
    deck_lower = deck_name.lower()
    icon_data: Optional[bytes] = None

    for stem_lower, stem_raw, data in images:
        if stem_lower == deck_lower:
            icon_data = data
            _log(f"  Icon source found: {stem_raw}.png")
            break

    # ── Rename and write each face ────────────────────────────────────
    for stem_lower, stem_raw, data in images:
        # Skip the icon file itself (it gets handled separately)
        if stem_lower == deck_lower:
            continue

        # Look up in rename map
        if stem_lower in FACE_RENAME_MAP:
            suffix     = FACE_RENAME_MAP[stem_lower]
            final_name = f"{face_prefix}_{suffix}.png"
        else:
            # Not in map — capitalize each word, use underscore separator
            safe_suffix = stem_raw.replace(" ", "_").title()
            final_name  = f"{face_prefix}_{safe_suffix}.png"
            _log(f"  Unrecognized: {stem_raw}.png → {final_name}")
            result["unrecognized"] += 1

        target = dest_dir / final_name

        if target.exists():
            _log(f"  Skipped (exists): {final_name}")
            result["skipped"] += 1
            continue

        try:
            target.write_bytes(data)
            _log(f"  {stem_raw}.png → {final_name}")
            result["extracted"] += 1
        except Exception as e:
            result["errors"].append(f"Could not write {final_name}: {e}")

    # ── Save icon source if found ─────────────────────────────────────
    if icon_data is not None:
        icon_png_path = dest_dir.parent / f"{deck_name}.png"
        try:
            icon_png_path.write_bytes(icon_data)
            result["icon_path"] = icon_png_path
            _log(f"  Icon PNG saved: {icon_png_path.name}")
        except Exception as e:
            result["errors"].append(f"Could not save icon PNG: {e}")

    _log(
        f"Face extraction complete: "
        f"{result['extracted']} extracted, "
        f"{result['skipped']} skipped, "
        f"{result['unrecognized']} unrecognized"
    )
    return result


def convert_png_to_ico(
    png_path: Path,
    ico_path: Path,
    log_fn=None,
) -> bool:
    """
    Convert a PNG file to a multi-resolution .ico file.
    Uses Pillow if available (best quality).
    Falls back to manual ICO construction if Pillow not installed.
    Returns True on success.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not png_path.exists():
        _log(f"[ICON] PNG not found: {png_path}")
        return False

    # ── Method 1: Pillow (preferred) ──────────────────────────────────
    if PILLOW_OK:
        try:
            img = PILImage.open(str(png_path)).convert("RGBA")
            sizes = [(16, 16), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)]
            img.save(str(ico_path), format="ICO", sizes=sizes)
            _log(f"[ICON] Created via Pillow: {ico_path.name}")
            return True
        except Exception as e:
            _log(f"[ICON] Pillow failed: {e} — trying fallback")

    # ── Method 2: Manual ICO construction (no Pillow) ─────────────────
    # Reads the PNG as-is and wraps it in a minimal ICO container.
    # Only embeds one size (the source PNG) but works for shortcuts.
    try:
        png_data = png_path.read_bytes()
        png_size = len(png_data)

        # ICO file format:
        # Header: 6 bytes (reserved, type, count)
        # Directory entry: 16 bytes per image
        # Image data: raw PNG bytes (Windows Vista+ supports PNG in ICO)

        # Use 256x256 as declared size (0 = 256 in ICO format)
        width_byte  = 0    # 0 means 256
        height_byte = 0    # 0 means 256
        color_count = 0    # 0 = more than 256 colors
        reserved    = 0
        planes      = 1
        bit_count   = 32
        # Data offset = 6 (header) + 16 (one directory entry)
        data_offset = 6 + 16

        header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=1 (ICO), count=1
        dir_entry = struct.pack(
            "<BBBBHHII",
            width_byte, height_byte, color_count, reserved,
            planes, bit_count, png_size, data_offset
        )

        ico_data = header + dir_entry + png_data
        ico_path.write_bytes(ico_data)
        _log(f"[ICON] Created via fallback method: {ico_path.name}")
        return True

    except Exception as e:
        _log(f"[ICON] Fallback also failed: {e}")
        return False


def validate_face_source(source: str) -> tuple[bool, str, int]:
    """
    Quick validation of a face source (ZIP or folder) without extracting.
    Returns (is_valid, message, png_count).
    """
    path = Path(source.strip())

    if not path.exists():
        return False, "Path does not exist.", 0

    if path.is_file():
        if path.suffix.lower() != ".zip":
            return False, "File is not a ZIP archive.", 0
        try:
            with zipfile.ZipFile(str(path), "r") as zf:
                pngs = [m for m in zf.namelist()
                        if m.lower().endswith(".png")]
            if not pngs:
                return False, "ZIP contains no PNG files.", 0
            return True, f"Valid ZIP — {len(pngs)} PNG file(s) found.", len(pngs)
        except zipfile.BadZipFile:
            return False, "Invalid or corrupt ZIP file.", 0
        except Exception as e:
            return False, f"ZIP error: {e}", 0

    elif path.is_dir():
        pngs = list(path.glob("*.png"))
        if not pngs:
            return False, "Folder contains no PNG files.", 0
        return True, f"Valid folder — {len(pngs)} PNG file(s) found.", len(pngs)

    return False, "Not a file or folder.", 0

# ── END OF SECTION 3 ──────────────────────────────────────────────────────────
# Next: Section 4 — Sound generation per profile


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SOUND GENERATION
#
# Procedural WAV generation for each sound profile.
# No external audio files required. No copyright concerns.
# Profile parameters read from SOUND_PROFILES dict (Section 1).
# ═══════════════════════════════════════════════════════════════════════════════

_SAMPLE_RATE = 44100


def _sine_wave(freq: float, t: float) -> float:
    return math.sin(2 * math.pi * freq * t)

def _square_wave(freq: float, t: float) -> float:
    return 1.0 if _sine_wave(freq, t) >= 0 else -1.0

def _sawtooth_wave(freq: float, t: float) -> float:
    return 2 * ((freq * t) % 1.0) - 1.0

def _mix_waveform(profile: dict, freq: float, t: float) -> float:
    wf = profile.get("waveform", {"sine": 1.0, "square": 0.0, "saw": 0.0})
    return (
        wf.get("sine",   0.0) * _sine_wave(freq, t) +
        wf.get("square", 0.0) * _square_wave(freq, t) +
        wf.get("saw",    0.0) * _sawtooth_wave(freq, t)
    )

def _envelope(i: int, total: int,
              attack_frac: float = 0.05,
              release_frac: float = 0.35) -> float:
    pos = i / max(1, total)
    if pos < attack_frac:
        return pos / attack_frac
    if pos > (1 - release_frac):
        return (1 - pos) / release_frac
    return 1.0

def _clamp_sample(v: float) -> int:
    return max(-32767, min(32767, int(v * 32767)))

def _write_wav(path: Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setparams((1, 2, _SAMPLE_RATE, 0, "NONE", "not compressed"))
        for s in samples:
            wf.writeframes(struct.pack("<h", s))

def _generate_notes(notes: list[tuple[float, float]],
                    profile: dict,
                    gap_secs: float = 0.05,
                    amplitude: float = 0.45) -> list[int]:
    """Generate audio samples for a sequence of (freq, duration) tuples."""
    samples = []
    for freq, length in notes:
        total = int(_SAMPLE_RATE * length)
        for i in range(total):
            t   = i / _SAMPLE_RATE
            val = _mix_waveform(profile, freq, t)
            # Add harmonic for richness
            val += 0.15 * _sine_wave(freq * 2.0, t)
            val += 0.05 * _sine_wave(freq * 3.0, t)
            env = _envelope(i, total, attack_frac=0.02, release_frac=0.55)
            samples.append(_clamp_sample(val * env * amplitude))
        # Gap between notes
        for _ in range(int(_SAMPLE_RATE * gap_secs)):
            samples.append(0)
    return samples

def _generate_tritone_error(profile: dict, duration: float = 0.4) -> list[int]:
    """Devil's interval — B3 + F4 simultaneously. Used for errors."""
    total   = int(_SAMPLE_RATE * duration)
    samples = []
    for i in range(total):
        t   = i / _SAMPLE_RATE
        val = (
            _sine_wave(246.94, t) * 0.5 +           # B3
            _square_wave(349.23, t) * 0.3 +          # F4
            _sine_wave(246.94 * 2.0, t) * 0.1
        )
        env = _envelope(i, total, attack_frac=0.02, release_frac=0.4)
        samples.append(_clamp_sample(val * env * 0.5))
    return samples

def _generate_buzz_error(profile: dict, duration: float = 0.25) -> list[int]:
    """Short electronic buzz. Used for error on electronic profiles."""
    total   = int(_SAMPLE_RATE * duration)
    samples = []
    for i in range(total):
        t   = i / _SAMPLE_RATE
        val = _square_wave(220.0, t) * 0.8 + _square_wave(440.0, t) * 0.2
        env = _envelope(i, total, attack_frac=0.01, release_frac=0.3)
        samples.append(_clamp_sample(val * env * 0.4))
    return samples

def _generate_dissonant_error(profile: dict, duration: float = 0.35) -> list[int]:
    """Minor second cluster. Unsettling. For warm/arcane profiles."""
    total   = int(_SAMPLE_RATE * duration)
    samples = []
    freqs   = [440.0, 466.16, 493.88]  # A4, A#4, B4 — tight cluster
    for i in range(total):
        t   = i / _SAMPLE_RATE
        val = sum(_sine_wave(f, t) / len(freqs) for f in freqs)
        env = _envelope(i, total, attack_frac=0.02, release_frac=0.5)
        samples.append(_clamp_sample(val * env * 0.45))
    return samples

def _generate_low_buzz_error(profile: dict, duration: float = 0.3) -> list[int]:
    """Low rumble. For earth/friend profiles."""
    total   = int(_SAMPLE_RATE * duration)
    samples = []
    for i in range(total):
        t   = i / _SAMPLE_RATE
        val = _sine_wave(80.0, t) * 0.7 + _square_wave(80.0, t) * 0.3
        env = _envelope(i, total, attack_frac=0.05, release_frac=0.5)
        samples.append(_clamp_sample(val * env * 0.4))
    return samples


def generate_sounds_for_profile(
    profile_name: str,
    sounds_dir: Path,
    deck_name_prefix: str,
    log_fn=None,
) -> dict[str, bool]:
    """
    Generate all sound WAV files for a given sound profile.

    Files generated:
        [prefix]_alert.wav
        [prefix]_startup.wav
        [prefix]_idle.wav
        [prefix]_shutdown.wav
        [prefix]_error.wav

    Returns dict of {sound_name: success_bool}
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    sounds_dir.mkdir(parents=True, exist_ok=True)

    profile = SOUND_PROFILES.get(profile_name)
    if not profile:
        _log(f"[SOUND] Unknown profile '{profile_name}' — using default_chime")
        profile = SOUND_PROFILES["default_chime"]

    if profile.get("status") == "stub":
        _log(f"[SOUND] Profile '{profile_name}' is a stub — using default_chime fallback")
        profile = SOUND_PROFILES["default_chime"]

    results: dict[str, bool] = {}
    prefix = deck_name_prefix.lower()

    # ── Alert ─────────────────────────────────────────────────────────
    alert_path = sounds_dir / f"{prefix}_alert.wav"
    if not alert_path.exists():
        try:
            notes   = profile.get("notes_alert", [(440.0, 0.5)])
            samples = _generate_notes(notes, profile)
            _write_wav(alert_path, samples)
            _log(f"[SOUND] Generated: {alert_path.name}")
            results["alert"] = True
        except Exception as e:
            _log(f"[SOUND] Alert generation failed: {e}")
            results["alert"] = False
    else:
        results["alert"] = True

    # ── Startup ───────────────────────────────────────────────────────
    startup_path = sounds_dir / f"{prefix}_startup.wav"
    if not startup_path.exists():
        try:
            notes   = profile.get("notes_startup", [(440.0, 0.6)])
            samples = _generate_notes(notes, profile, amplitude=0.4)
            _write_wav(startup_path, samples)
            _log(f"[SOUND] Generated: {startup_path.name}")
            results["startup"] = True
        except Exception as e:
            _log(f"[SOUND] Startup generation failed: {e}")
            results["startup"] = False
    else:
        results["startup"] = True

    # ── Idle ──────────────────────────────────────────────────────────
    idle_path = sounds_dir / f"{prefix}_idle.wav"
    if not idle_path.exists():
        try:
            notes   = profile.get("notes_idle", [(440.0, 0.8)])
            samples = _generate_notes(notes, profile, amplitude=0.25)
            _write_wav(idle_path, samples)
            _log(f"[SOUND] Generated: {idle_path.name}")
            results["idle"] = True
        except Exception as e:
            _log(f"[SOUND] Idle generation failed: {e}")
            results["idle"] = False
    else:
        results["idle"] = True

    # ── Shutdown ──────────────────────────────────────────────────────
    shutdown_path = sounds_dir / f"{prefix}_shutdown.wav"
    if not shutdown_path.exists():
        try:
            notes   = profile.get("notes_shutdown", [(440.0, 0.6)])
            samples = _generate_notes(notes, profile, amplitude=0.38)
            _write_wav(shutdown_path, samples)
            _log(f"[SOUND] Generated: {shutdown_path.name}")
            results["shutdown"] = True
        except Exception as e:
            _log(f"[SOUND] Shutdown generation failed: {e}")
            results["shutdown"] = False
    else:
        results["shutdown"] = True

    # ── Error ─────────────────────────────────────────────────────────
    error_path = sounds_dir / f"{prefix}_error.wav"
    if not error_path.exists():
        try:
            error_type = profile.get("error_type", "tritone")
            error_fns  = {
                "tritone":    _generate_tritone_error,
                "buzz":       _generate_buzz_error,
                "dissonant":  _generate_dissonant_error,
                "low_buzz":   _generate_low_buzz_error,
                "static":     _generate_buzz_error,
                "dramatic":   _generate_dissonant_error,
            }
            gen_fn  = error_fns.get(error_type, _generate_tritone_error)
            samples = gen_fn(profile)
            _write_wav(error_path, samples)
            _log(f"[SOUND] Generated: {error_path.name}")
            results["error"] = True
        except Exception as e:
            _log(f"[SOUND] Error sound generation failed: {e}")
            results["error"] = False
    else:
        results["error"] = True

    ok_count   = sum(1 for v in results.values() if v)
    fail_count = sum(1 for v in results.values() if not v)
    _log(f"[SOUND] {ok_count} sounds ready, {fail_count} failed")
    return results

# ── END OF SECTION 4 ──────────────────────────────────────────────────────────
# Next: Section 5 — Deck template (the universal base deck code with slots)


# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1D — MODULE CODE MARKERS
# Maps module keys to comment markers injected into the deck template.
# None = module not yet implemented, slot gets a placeholder comment.
# ═══════════════════════════════════════════════════════════════════════════════

DECK_TEMPLATE = '''\
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# ECHO DECK — <<<WINDOW_TITLE>>>
# Filename   : <<<DECK_FILENAME>>>
# Version    : <<<DECK_VERSION>>>
# Generated  : <<<BUILD_DATE>>>
# Builder    : deck_builder.py
#
# THIS FILE IS GENERATED. Do not edit persona values directly.
# To change persona: re-run deck_builder.py with updated persona template.
# To change modules: re-run deck_builder.py with updated module selection.
#
# Installed modules:
<<<INSTALLED_MODULES_COMMENT>>>
# ═══════════════════════════════════════════════════════════════════════════════

# ── PERSONA CONFIGURATION (injected by deck_builder.py) ──────────────────────

DECK_NAME       = "<<<DECK_NAME>>>"
DECK_VERSION    = "<<<DECK_VERSION>>>"
FACE_PREFIX     = "<<<FACE_PREFIX>>>"
SOUND_PREFIX    = "<<<SOUND_PREFIX>>>"

# Color scheme — all UI colors come from here
C_PRIMARY       = "<<<COLOR_PRIMARY>>>"
C_SECONDARY     = "<<<COLOR_SECONDARY>>>"
C_ACCENT        = "<<<COLOR_ACCENT>>>"
C_BG            = "<<<COLOR_BACKGROUND>>>"
C_PANEL         = "<<<COLOR_PANEL>>>"
C_BORDER        = "<<<COLOR_BORDER>>>"
C_TEXT          = "<<<COLOR_TEXT>>>"
C_TEXT_DIM      = "<<<COLOR_TEXT_DIM>>>"

# Derived colors (computed from primary)
C_PRIMARY_DIM   = C_PRIMARY + "44"   # primary with opacity approximation
C_BLOOD         = "#8b0000"           # always deep red for errors
C_GREEN         = "#44aa66"           # always green for success
C_PURPLE        = "#8855cc"           # always purple for system messages

# UI Labels
UI_WINDOW_TITLE       = "<<<WINDOW_TITLE>>>"
UI_CHAT_WINDOW        = "<<<CHAT_WINDOW>>>"
UI_SEND_BUTTON        = "<<<SEND_BUTTON>>>"
UI_INPUT_PLACEHOLDER  = "<<<INPUT_PLACEHOLDER>>>"
UI_GENERATING_STATUS  = "<<<GENERATING_STATUS>>>"
UI_IDLE_STATUS        = "<<<IDLE_STATUS>>>"
UI_OFFLINE_STATUS     = "<<<OFFLINE_STATUS>>>"
UI_TORPOR_STATUS      = "<<<TORPOR_STATUS>>>"
UI_SUSPENSION_LABEL   = "<<<SUSPENSION_LABEL>>>"
UI_RUNES              = "<<<RUNES>>>"
UI_MIRROR_LABEL       = "<<<MIRROR_LABEL>>>"
UI_EMOTIONS_LABEL     = "<<<EMOTIONS_LABEL>>>"
UI_LEFT_ORB_TITLE     = "<<<LEFT_ORB_TITLE>>>"
UI_LEFT_ORB_LABEL     = "<<<LEFT_ORB_LABEL>>>"
UI_CYCLE_TITLE        = "<<<CYCLE_TITLE>>>"
UI_RIGHT_ORB_TITLE    = "<<<RIGHT_ORB_TITLE>>>"
UI_RIGHT_ORB_LABEL    = "<<<RIGHT_ORB_LABEL>>>"
UI_ESSENCE_TITLE      = "<<<ESSENCE_TITLE>>>"
UI_ESSENCE_PRIMARY    = "<<<ESSENCE_PRIMARY>>>"
UI_ESSENCE_SECONDARY  = "<<<ESSENCE_SECONDARY>>>"
UI_FOOTER_STRIP_LABEL = "<<<FOOTER_STRIP_LABEL>>>"

# System prompt and cognitive anchors
SYSTEM_PROMPT_BASE = """<<<SYSTEM_PROMPT>>>"""

COGNITIVE_ANCHORS = <<<COGNITIVE_ANCHORS>>>

# Special systems
AI_STATES_ENABLED       = <<<AI_STATES_ENABLED>>>
SUSPENSION_ENABLED      = <<<SUSPENSION_ENABLED>>>
ANCHOR_ENTITY           = <<<ANCHOR_ENTITY>>>
<<<AI_STATE_GREETINGS_DECL>>>

# Persona characteristics — from template
DECK_PRONOUN_SUBJECT    = "<<<DECK_PRONOUN_SUBJECT>>>"
DECK_PRONOUN_OBJECT     = "<<<DECK_PRONOUN_OBJECT>>>"
DECK_PRONOUN_POSSESSIVE = "<<<DECK_PRONOUN_POSSESSIVE>>>"
UI_FONT_FAMILY          = "<<<UI_FONT_FAMILY>>>"
UI_AWAKENING_LINE       = "<<<UI_AWAKENING_LINE>>>"

# ── END PERSONA/MODULE CONFIGURATION ─────────────────────────────────────────
# Everything below is the universal deck implementation.
# This code is identical across all generated decks.
# ─────────────────────────────────────────────────────────────────────────────

<<<DECK_IMPLEMENTATION>>>
'''
def build_deck_file(
    persona: dict,
    deck_name: str,
    selected_modules: list[str],
    output_path: Path,
    model_config: dict,
    ai_state_greetings: Optional[dict] = None,
    log_fn=None,
) -> bool:
    """
    Inject persona values and module code into DECK_TEMPLATE.
    Write the result to output_path.
    Returns True on success.

    The deck implementation (the actual working code from morganna_deck.py)
    is read from the current working deck and embedded.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    try:
        # ── Build installed modules comment ───────────────────────────
        installed_lines = []
        for mod_key in MODULES:
            mod      = MODULES[mod_key]
            is_sel   = mod_key in selected_modules
            status   = "[INSTALLED]" if is_sel else "[NOT INSTALLED]"
            installed_lines.append(
                f"#   {status} {mod['display_name']}"
            )
        installed_comment = "\n".join(installed_lines)

        # ── Build cognitive anchors as Python list literal ─────────────
        anchors = persona.get("cognitive_anchors", [])
        if anchors:
            anchor_lines = ",\n    ".join(f'"{a}"' for a in anchors)
            anchors_literal = f"[\n    {anchor_lines},\n]"
        else:
            anchors_literal = "[]"

        # ── Build anchor entity as Python dict or None ─────────────────
        ae = persona.get("anchor_entity")
        if ae:
            ae_literal = repr(ae)
        else:
            ae_literal = "None"

        # ── Build module slot values ───────────────────────────────────
        module_slots: dict[str, str] = {}
        template_slots = set(re.findall(r"<<<(MODULE_[A-Z0-9_]+)>>>", DECK_TEMPLATE))
        for slot in template_slots:
            module_slots[slot] = "# [NOT INSTALLED]"

        for mod_key, mod_data in MODULES.items():
            slot_key = mod_data["slot_key"]
            if mod_key in selected_modules:
                code = MODULE_CODE.get(mod_key) or mod_data.get("runtime_marker")
                if code:
                    module_slots[slot_key] = f"# [INSTALLED: {mod_data['display_name']}]\n{code}"
                else:
                    module_slots[slot_key] = (
                        f"# [INSTALLED: {mod_data['display_name']}] "
                        f"— code not yet built (status: {mod_data['status']})"
                    )
            else:
                module_slots[slot_key] = (
                    f"# [NOT INSTALLED: {mod_data['display_name']}]"
                )

        # ── Get deck implementation from current deck ──────────────────
        # Look for the existing working deck in the same directory
        deck_impl = _get_deck_implementation(selected_modules=selected_modules, log_fn=log_fn)

        # ── Build all replacements ─────────────────────────────────────
        colors     = persona.get("colors", {})
        ui_labels  = persona.get("ui_labels", {})
        deck_lower = deck_name.lower().replace(" ", "_")

        pronouns = persona.get("pronouns", {}) or {}
        pronoun_subject = pronouns.get("subject", "they")
        pronoun_object = pronouns.get("object", "them")
        pronoun_possessive = pronouns.get("possessive", "their")
        system_prompt_base = persona.get("system_prompt", "")
        system_prompt = (
            f"{system_prompt_base}\n\n"
            f"Your name is {deck_name}. "
            f"Your pronouns are {pronoun_subject}/{pronoun_object}/{pronoun_possessive}. "
            "Use these pronouns only for grammatical self-reference. "
            "Never use your pronouns as your name."
        )

        replacements = {
            "<<<DECK_VERSION>>>":          DECK_VERSION,
            "<<<DECK_NAME>>>":             deck_name,
            "<<<DECK_FILENAME>>>":         f"{deck_lower}_deck.py",
            "<<<BUILD_DATE>>>":            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "<<<WINDOW_TITLE>>>":          ui_labels.get("window_title", f"ECHO DECK — {deck_name.upper()}"),
            "<<<CHAT_WINDOW>>>":           ui_labels.get("chat_window",       "CONVERSATION"),
            "<<<SEND_BUTTON>>>":           ui_labels.get("send_button",       "SEND"),
            "<<<INPUT_PLACEHOLDER>>>":     ui_labels.get("input_placeholder", "Type your message..."),
            "<<<GENERATING_STATUS>>>":     ui_labels.get("generating_status", "◉ THINKING"),
            "<<<IDLE_STATUS>>>":           ui_labels.get("idle_status",        "◉ IDLE"),
            "<<<OFFLINE_STATUS>>>":        ui_labels.get("offline_status",     "◉ OFFLINE"),
            "<<<TORPOR_STATUS>>>":         ui_labels.get("torpor_status",      "◉ SUSPENDED"),
            "<<<SUSPENSION_LABEL>>>":      (ui_labels.get("suspension_label", "").strip() or "Suspend"),
            "<<<RUNES>>>":                 ui_labels.get("runes",              "— ECHO DECK —"),
            "<<<MIRROR_LABEL>>>":          ui_labels.get("mirror_label",       "MIRROR"),
            "<<<EMOTIONS_LABEL>>>":        ui_labels.get("emotions_label",     "EMOTIONS"),
            "<<<LEFT_ORB_TITLE>>>":        ui_labels.get("left_orb_title",     "PRIMARY"),
            "<<<LEFT_ORB_LABEL>>>":        ui_labels.get("left_orb_label",     "RESOURCE"),
            "<<<CYCLE_TITLE>>>":           ui_labels.get("cycle_title",        "CYCLE"),
            "<<<RIGHT_ORB_TITLE>>>":       ui_labels.get("right_orb_title",    "SECONDARY"),
            "<<<RIGHT_ORB_LABEL>>>":       ui_labels.get("right_orb_label",    "RESERVE"),
            "<<<ESSENCE_TITLE>>>":         ui_labels.get("essence_title",      "ESSENCE"),
            "<<<ESSENCE_PRIMARY>>>":       ui_labels.get("essence_primary",    "PRIMARY STATE"),
            "<<<ESSENCE_SECONDARY>>>":     ui_labels.get("essence_secondary",  "SECONDARY STATE"),
            "<<<FOOTER_STRIP_LABEL>>>":    ui_labels.get("footer_strip_label", "STATE"),
            "<<<FACE_PREFIX>>>":           persona.get("face_prefix", deck_name),
            "<<<SOUND_PREFIX>>>":          deck_lower,
            "<<<SYSTEM_PROMPT>>>":         system_prompt,
            "<<<COGNITIVE_ANCHORS>>>":     anchors_literal,
            "<<<COLOR_PRIMARY>>>":         colors.get("primary",    "#888888"),
            "<<<COLOR_SECONDARY>>>":       colors.get("secondary",  "#aaaaaa"),
            "<<<COLOR_ACCENT>>>":          colors.get("accent",     "#666666"),
            "<<<COLOR_BACKGROUND>>>":      colors.get("background", "#080808"),
            "<<<COLOR_PANEL>>>":           colors.get("panel",      "#101010"),
            "<<<COLOR_BORDER>>>":          colors.get("border",     "#2a2a2a"),
            "<<<COLOR_TEXT>>>":            colors.get("text",       "#e0e0e0"),
            "<<<COLOR_TEXT_DIM>>>":        colors.get("text_dim",   "#606060"),
            "<<<AI_STATES_ENABLED>>>":      str(bool(persona.get("vampire_states", False))),
            "<<<SUSPENSION_ENABLED>>>":     str(bool(persona.get("torpor_system",  False))),
            "<<<ANCHOR_ENTITY>>>":          ae_literal,
            "<<<AI_STATE_GREETINGS_DECL>>>": (
                f"AI_STATE_GREETINGS       = {repr(ai_state_greetings)}"
                if (bool(persona.get('vampire_states', False)) and ai_state_greetings)
                else ""
            ),
            "<<<INSTALLED_MODULES_COMMENT>>>": installed_comment,
            "<<<DECK_IMPLEMENTATION>>>":   deck_impl,
            "<<<DECK_PRONOUN_SUBJECT>>>":   pronoun_subject,
            "<<<DECK_PRONOUN_OBJECT>>>":    pronoun_object,
            "<<<DECK_PRONOUN_POSSESSIVE>>>": pronoun_possessive,
            "<<<UI_FONT_FAMILY>>>":         persona.get("font_family",    "'Georgia', 'Times New Roman', serif"),
            "<<<UI_AWAKENING_LINE>>>":      persona.get("awakening_line", "Connecting..."),
        }

        # Add module slot replacements
        for slot_key, slot_value in module_slots.items():
            replacements[f"<<<{slot_key}>>>"] = slot_value

        # ── Apply all replacements to template ────────────────────────
        result = DECK_TEMPLATE
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)

        # ── Write output file ─────────────────────────────────────────
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result, encoding="utf-8")
        _log(f"[DECK] Written: {output_path}")
        _log(f"[DECK] Size: {len(result.splitlines())} lines")
        return True

    except Exception as e:
        import traceback
        _log(f"[DECK] Write failed: {e}")
        _log(traceback.format_exc())
        return False


# ── EMBEDDED DECK IMPLEMENTATION ────────────────────────────────────────────
# Self-contained. No external files needed.
# Base64 encoded to avoid quote/backslash conflicts.
# Includes: chat formatting fix, all patches applied.

import base64 as _base64

_DECK_IMPL_B64 = (
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNITyBERUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJT04KIyBHZW5lcmF0"
    "ZWQgYnkgZGVja19idWlsZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGluamVjdGVkIGZyb20gREVDS19URU1QTEFURSBoZWFk"
    "ZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKCmltcG9ydCBz"
    "eXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCBtYXRoCmltcG9ydCB0aW1lCmltcG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QK"
    "aW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5nCmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0"
    "aW1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHpvbmVpbmZvIGltcG9ydCBab25lSW5m"
    "bywgWm9uZUluZm9Ob3RGb3VuZEVycm9yCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9tIHR5cGluZyBpbXBvcnQgT3B0aW9u"
    "YWwsIEl0ZXJhdG9yCgojIOKUgOKUgCBDb25zb2xlIGd1YXJkIOKAlCBzdXBwcmVzcyBDTUQgZmxhc2hlcyB3aGVuIGxhdW5jaGVk"
    "IHZpYSBweXRob253LmV4ZSDilIDilIDilIDilIDilIDilIDilIDilIAKIyBweXRob253LmV4ZSBoYXMgbm8gY29uc29sZS4gc3Rk"
    "b3V0L3N0ZGVyciB3cml0ZXMgKGluY2x1ZGluZyBweWdhbWUgYmFubmVyKQojIGNhdXNlIFdpbmRvd3MgdG8gYnJpZWZseSBhbGxv"
    "Y2F0ZSBhIENNRCB3aW5kb3cuIFJlZGlyZWN0IHRvIGRldm51bGwuCmltcG9ydCBvcyBhcyBfb3NfZ3VhcmQKdHJ5OgogICAgaWYg"
    "c3lzLmV4ZWN1dGFibGUgYW5kICJweXRob253IiBpbiBzeXMuZXhlY3V0YWJsZS5sb3dlcigpOgogICAgICAgIHN5cy5zdGRvdXQg"
    "PSBvcGVuKF9vc19ndWFyZC5kZXZudWxsLCAidyIpCiAgICAgICAgc3lzLnN0ZGVyciA9IG9wZW4oX29zX2d1YXJkLmRldm51bGws"
    "ICJ3IikKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHBhc3MKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCgojIOKUgOKUgCBFQVJMWSBDUkFTSCBMT0dHRVIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgSG9va3MgaW4gYmVmb3JlIFF0LCBiZWZvcmUgZXZlcnl0aGluZy4gQ2FwdHVyZXMgQUxMIG91dHB1dCBp"
    "bmNsdWRpbmcKIyBDKysgbGV2ZWwgUXQgbWVzc2FnZXMuIFdyaXR0ZW4gdG8gW0RlY2tOYW1lXS9sb2dzL3N0YXJ0dXAubG9nCiMg"
    "VGhpcyBzdGF5cyBhY3RpdmUgZm9yIHRoZSBsaWZlIG9mIHRoZSBwcm9jZXNzLgoKX0VBUkxZX0xPR19MSU5FUzogbGlzdCA9IFtd"
    "Cl9FQVJMWV9MT0dfUEFUSDogT3B0aW9uYWxbUGF0aF0gPSBOb25lCgpkZWYgX2Vhcmx5X2xvZyhtc2c6IHN0cikgLT4gTm9uZToK"
    "ICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTLiVmIilbOi0zXQogICAgbGluZSA9IGYiW3t0c31dIHtt"
    "c2d9IgogICAgX0VBUkxZX0xPR19MSU5FUy5hcHBlbmQobGluZSkKICAgICMgTm8gcHJpbnQoKSDigJQgcHl0aG9udy5leGUgaGFz"
    "IG5vIGNvbnNvbGU7IHByaW50aW5nIGNhdXNlcyBDTUQgZmxhc2gKICAgIGlmIF9FQVJMWV9MT0dfUEFUSDoKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHdpdGggX0VBUkxZX0xPR19QQVRILm9wZW4oImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAg"
    "ICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgpk"
    "ZWYgX2luaXRfZWFybHlfbG9nKGJhc2VfZGlyOiBQYXRoKSAtPiBOb25lOgogICAgZ2xvYmFsIF9FQVJMWV9MT0dfUEFUSAogICAg"
    "bG9nX2RpciA9IGJhc2VfZGlyIC8gImxvZ3MiCiAgICBsb2dfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkK"
    "ICAgIF9FQVJMWV9MT0dfUEFUSCA9IGxvZ19kaXIgLyBmInN0YXJ0dXBfe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRf"
    "JUglTSVTJyl9LmxvZyIKICAgICMgRmx1c2ggYnVmZmVyZWQgbGluZXMKICAgIHdpdGggX0VBUkxZX0xPR19QQVRILm9wZW4oInci"
    "LCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZvciBsaW5lIGluIF9FQVJMWV9MT0dfTElORVM6CiAgICAgICAgICAg"
    "IGYud3JpdGUobGluZSArICJcbiIpCgpkZWYgX2luc3RhbGxfcXRfbWVzc2FnZV9oYW5kbGVyKCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgSW50ZXJjZXB0IEFMTCBRdCBtZXNzYWdlcyBpbmNsdWRpbmcgQysrIGxldmVsIHdhcm5pbmdzLgogICAgVGhpcyBjYXRjaGVz"
    "IHRoZSBRVGhyZWFkIGRlc3Ryb3llZCBtZXNzYWdlIGF0IHRoZSBzb3VyY2UgYW5kIGxvZ3MgaXQKICAgIHdpdGggYSBmdWxsIHRy"
    "YWNlYmFjayBzbyB3ZSBrbm93IGV4YWN0bHkgd2hpY2ggdGhyZWFkIGFuZCB3aGVyZS4KICAgICIiIgogICAgdHJ5OgogICAgICAg"
    "IGZyb20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IHFJbnN0YWxsTWVzc2FnZUhhbmRsZXIsIFF0TXNnVHlwZQogICAgICAgIGltcG9y"
    "dCB0cmFjZWJhY2sKCiAgICAgICAgZGVmIHF0X21lc3NhZ2VfaGFuZGxlcihtc2dfdHlwZSwgY29udGV4dCwgbWVzc2FnZSk6CiAg"
    "ICAgICAgICAgIGxldmVsID0gewogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0RGVidWdNc2c6ICAgICJRVF9ERUJVRyIsCiAg"
    "ICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRJbmZvTXNnOiAgICAgIlFUX0lORk8iLAogICAgICAgICAgICAgICAgUXRNc2dUeXBl"
    "LlF0V2FybmluZ01zZzogICJRVF9XQVJOSU5HIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdENyaXRpY2FsTXNnOiAiUVRf"
    "Q1JJVElDQUwiLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0RmF0YWxNc2c6ICAgICJRVF9GQVRBTCIsCiAgICAgICAgICAg"
    "IH0uZ2V0KG1zZ190eXBlLCAiUVRfVU5LTk9XTiIpCgogICAgICAgICAgICBsb2NhdGlvbiA9ICIiCiAgICAgICAgICAgIGlmIGNv"
    "bnRleHQuZmlsZToKICAgICAgICAgICAgICAgIGxvY2F0aW9uID0gZiIgW3tjb250ZXh0LmZpbGV9Ontjb250ZXh0LmxpbmV9XSIK"
    "CiAgICAgICAgICAgIF9lYXJseV9sb2coZiJbe2xldmVsfV17bG9jYXRpb259IHttZXNzYWdlfSIpCgogICAgICAgICAgICAjIEZv"
    "ciBRVGhyZWFkIHdhcm5pbmdzIOKAlCBsb2cgZnVsbCBQeXRob24gc3RhY2sKICAgICAgICAgICAgaWYgIlFUaHJlYWQiIGluIG1l"
    "c3NhZ2Ugb3IgInRocmVhZCIgaW4gbWVzc2FnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgc3RhY2sgPSAiIi5qb2luKHRyYWNl"
    "YmFjay5mb3JtYXRfc3RhY2soKSkKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbU1RBQ0sgQVQgUVRIUkVBRCBXQVJOSU5H"
    "XVxue3N0YWNrfSIpCgogICAgICAgIHFJbnN0YWxsTWVzc2FnZUhhbmRsZXIocXRfbWVzc2FnZV9oYW5kbGVyKQogICAgICAgIF9l"
    "YXJseV9sb2coIltJTklUXSBRdCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICBfZWFybHlfbG9nKGYiW0lOSVRdIENvdWxkIG5vdCBpbnN0YWxsIFF0IG1lc3NhZ2UgaGFuZGxlcjoge2V9IikKCl9l"
    "YXJseV9sb2coZiJbSU5JVF0ge0RFQ0tfTkFNRX0gZGVjayBzdGFydGluZyIpCl9lYXJseV9sb2coZiJbSU5JVF0gUHl0aG9uIHtz"
    "eXMudmVyc2lvbi5zcGxpdCgpWzBdfSBhdCB7c3lzLmV4ZWN1dGFibGV9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBXb3JraW5nIGRp"
    "cmVjdG9yeToge29zLmdldGN3ZCgpfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gU2NyaXB0IGxvY2F0aW9uOiB7UGF0aChfX2ZpbGVf"
    "XykucmVzb2x2ZSgpfSIpCgojIOKUgOKUgCBPUFRJT05BTCBERVBFTkRFTkNZIEdVQVJEUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKClBTVVRJTF9PSyA9IEZhbHNlCnRyeToKICAg"
    "IGltcG9ydCBwc3V0aWwKICAgIFBTVVRJTF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHBzdXRpbCBPSyIpCmV4"
    "Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHBzdXRpbCBGQUlMRUQ6IHtlfSIpCgpOVk1M"
    "X09LID0gRmFsc2UKZ3B1X2hhbmRsZSA9IE5vbmUKdHJ5OgogICAgaW1wb3J0IHdhcm5pbmdzCiAgICB3aXRoIHdhcm5pbmdzLmNh"
    "dGNoX3dhcm5pbmdzKCk6CiAgICAgICAgd2FybmluZ3Muc2ltcGxlZmlsdGVyKCJpZ25vcmUiKQogICAgICAgIGltcG9ydCBweW52"
    "bWwKICAgIHB5bnZtbC5udm1sSW5pdCgpCiAgICBjb3VudCA9IHB5bnZtbC5udm1sRGV2aWNlR2V0Q291bnQoKQogICAgaWYgY291"
    "bnQgPiAwOgogICAgICAgIGdwdV9oYW5kbGUgPSBweW52bWwubnZtbERldmljZUdldEhhbmRsZUJ5SW5kZXgoMCkKICAgICAgICBO"
    "Vk1MX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHB5bnZtbCBPSyDigJQge2NvdW50fSBHUFUocykiKQpleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIEZBSUxFRDoge2V9IikKClRPUkNIX09L"
    "ID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHRvcmNoCiAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgQXV0b01vZGVsRm9yQ2F1"
    "c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgIFRPUkNIX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHRvcmNoIHt0"
    "b3JjaC5fX3ZlcnNpb25fX30gT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB0"
    "b3JjaCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKCldJTjMyX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHdpbjMyY29tLmNs"
    "aWVudAogICAgV0lOMzJfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JUXSB3aW4zMmNvbSBPSyIpCmV4Y2VwdCBJbXBv"
    "cnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHdpbjMyY29tIEZBSUxFRDoge2V9IikKCldJTlNPVU5EX09L"
    "ID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHdpbnNvdW5kCiAgICBXSU5TT1VORF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJ"
    "TVBPUlRdIHdpbnNvdW5kIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2lu"
    "c291bmQgRkFJTEVEIChvcHRpb25hbCk6IHtlfSIpCgpQWUdBTUVfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgcHlnYW1lCiAg"
    "ICBweWdhbWUubWl4ZXIuaW5pdCgpCiAgICBQWUdBTUVfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JUXSBweWdhbWUg"
    "T0siKQpleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHlnYW1lIEZBSUxFRDoge2V9IikK"
    "CgoKIyDilIDilIAgUHlTaWRlNiBJTVBPUlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApmcm9tIFB5U2lkZTYuUXRXaWRn"
    "ZXRzIGltcG9ydCAoCiAgICBRQXBwbGljYXRpb24sIFFNYWluV2luZG93LCBRV2lkZ2V0LCBRVkJveExheW91dCwgUUhCb3hMYXlv"
    "dXQsCiAgICBRR3JpZExheW91dCwgUVRleHRFZGl0LCBRTGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRTGFiZWwsIFFGcmFtZSwKICAg"
    "IFFDYWxlbmRhcldpZGdldCwgUVRhYmxlV2lkZ2V0LCBRVGFibGVXaWRnZXRJdGVtLCBRSGVhZGVyVmlldywKICAgIFFBYnN0cmFj"
    "dEl0ZW1WaWV3LCBRU3RhY2tlZFdpZGdldCwgUVRhYldpZGdldCwgUUxpc3RXaWRnZXQsCiAgICBRTGlzdFdpZGdldEl0ZW0sIFFT"
    "aXplUG9saWN5LCBRQ29tYm9Cb3gsIFFDaGVja0JveCwgUUZpbGVEaWFsb2csCiAgICBRTWVzc2FnZUJveCwgUURhdGVFZGl0LCBR"
    "RGlhbG9nLCBRRm9ybUxheW91dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24s"
    "IFFTcGluQm94LCBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0LAogICAgUU1lbnUsIFFUYWJCYXIKKQpmcm9tIFB5U2lkZTYuUXRDb3Jl"
    "IGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBRVGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVjdCwKICAg"
    "IFFQcm9wZXJ0eUFuaW1hdGlvbiwgUUVhc2luZ0N1cnZlCikKZnJvbSBQeVNpZGU2LlF0R3VpIGltcG9ydCAoCiAgICBRRm9udCwg"
    "UUNvbG9yLCBRUGFpbnRlciwgUUxpbmVhckdyYWRpZW50LCBRUmFkaWFsR3JhZGllbnQsCiAgICBRUGl4bWFwLCBRUGVuLCBRUGFp"
    "bnRlclBhdGgsIFFUZXh0Q2hhckZvcm1hdCwgUUljb24sCiAgICBRVGV4dEN1cnNvciwgUUFjdGlvbgopCgojIOKUgOKUgCBBUFAg"
    "SURFTlRJVFkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACkFQUF9OQU1FICAgICAgPSBVSV9XSU5ET1dfVElU"
    "TEUKQVBQX1ZFUlNJT04gICA9ICIyLjAuMCIKQVBQX0ZJTEVOQU1FICA9IGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgpC"
    "VUlMRF9EQVRFICAgID0gIjIwMjYtMDQtMDQiCgojIOKUgOKUgCBDT05GSUcgTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBjb25maWcuanNvbiBsaXZlcyBuZXh0IHRvIHRoZSBkZWNrIC5weSBmaWxlLgojIEFsbCBwYXRocyBjb21l"
    "IGZyb20gY29uZmlnLiBOb3RoaW5nIGhhcmRjb2RlZCBiZWxvdyB0aGlzIHBvaW50LgoKU0NSSVBUX0RJUiA9IFBhdGgoX19maWxl"
    "X18pLnJlc29sdmUoKS5wYXJlbnQKQ09ORklHX1BBVEggPSBTQ1JJUFRfRElSIC8gImNvbmZpZy5qc29uIgoKIyBJbml0aWFsaXpl"
    "IGVhcmx5IGxvZyBub3cgdGhhdCB3ZSBrbm93IHdoZXJlIHdlIGFyZQpfaW5pdF9lYXJseV9sb2coU0NSSVBUX0RJUikKX2Vhcmx5"
    "X2xvZyhmIltJTklUXSBTQ1JJUFRfRElSID0ge1NDUklQVF9ESVJ9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBDT05GSUdfUEFUSCA9"
    "IHtDT05GSUdfUEFUSH0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIGNvbmZpZy5qc29uIGV4aXN0czoge0NPTkZJR19QQVRILmV4aXN0"
    "cygpfSIpCgpkZWYgX2RlZmF1bHRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIlJldHVybnMgdGhlIGRlZmF1bHQgY29uZmlnIHN0"
    "cnVjdHVyZSBmb3IgZmlyc3QtcnVuIGdlbmVyYXRpb24uIiIiCiAgICBiYXNlID0gc3RyKFNDUklQVF9ESVIpCiAgICByZXR1cm4g"
    "ewogICAgICAgICJkZWNrX25hbWUiOiBERUNLX05BTUUsCiAgICAgICAgImRlY2tfdmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAg"
    "ICAgICJiYXNlX2RpciI6IGJhc2UsCiAgICAgICAgIm1vZGVsIjogewogICAgICAgICAgICAidHlwZSI6ICJsb2NhbCIsICAgICAg"
    "ICAgICMgbG9jYWwgfCBvbGxhbWEgfCBjbGF1ZGUgfCBvcGVuYWkKICAgICAgICAgICAgInBhdGgiOiAiIiwgICAgICAgICAgICAg"
    "ICAjIGxvY2FsIG1vZGVsIGZvbGRlciBwYXRoCiAgICAgICAgICAgICJvbGxhbWFfbW9kZWwiOiAiIiwgICAgICAgIyBlLmcuICJk"
    "b2xwaGluLTIuNi03YiIKICAgICAgICAgICAgImFwaV9rZXkiOiAiIiwgICAgICAgICAgICAjIENsYXVkZSBvciBPcGVuQUkga2V5"
    "CiAgICAgICAgICAgICJhcGlfdHlwZSI6ICIiLCAgICAgICAgICAgIyAiY2xhdWRlIiB8ICJvcGVuYWkiCiAgICAgICAgICAgICJh"
    "cGlfbW9kZWwiOiAiIiwgICAgICAgICAgIyBlLmcuICJjbGF1ZGUtc29ubmV0LTQtNiIKICAgICAgICB9LAogICAgICAgICJnb29n"
    "bGUiOiB7CiAgICAgICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIp"
    "LAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwKICAgICAgICAgICAgInNjb3BlcyI6IFsKICAg"
    "ICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAg"
    "ICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cu"
    "Z29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAgICAgIH0sCiAgICAgICAgInBhdGhzIjog"
    "ewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIoU0NSSVBUX0RJUiAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjog"
    "ICBzdHIoU0NSSVBUX0RJUiAvICJzb3VuZHMiKSwKICAgICAgICAgICAgIm1lbW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAibWVt"
    "b3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25zIjogc3RyKFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAg"
    "InNsIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAic2wiKSwKICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQVF9ESVIg"
    "LyAiZXhwb3J0cyIpLAogICAgICAgICAgICAibG9ncyI6ICAgICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAg"
    "ICJiYWNrdXBzIjogIHN0cihTQ1JJUFRfRElSIC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKFNDUklQ"
    "VF9ESVIgLyAicGVyc29uYXMiKSwKICAgICAgICAgICAgImdvb2dsZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAg"
    "ICAgICAgfSwKICAgICAgICAic2V0dGluZ3MiOiB7CiAgICAgICAgICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFs"
    "c2UsCiAgICAgICAgICAgICJpZGxlX21pbl9taW51dGVzIjogICAgICAgICAgMTAsCiAgICAgICAgICAgICJpZGxlX21heF9taW51"
    "dGVzIjogICAgICAgICAgMzAsCiAgICAgICAgICAgICJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAgICAgICAg"
    "ICJtYXhfYmFja3VwcyI6ICAgICAgICAgICAgICAgMTAsCiAgICAgICAgICAgICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAg"
    "VHJ1ZSwKICAgICAgICAgICAgImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiOiAzMDAwMDAsCiAgICAgICAgICAgICJnb29nbGVf"
    "bG9va2JhY2tfZGF5cyI6ICAgICAgMzAsCiAgICAgICAgICAgICJ1c2VyX2RlbGF5X3RocmVzaG9sZF9taW4iOiAgMzAsCiAgICAg"
    "ICAgICAgICJ0aW1lem9uZV9hdXRvX2RldGVjdCI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgInRpbWV6b25lX292ZXJyaWRlIjog"
    "ICAgICAgICAiIiwKICAgICAgICAgICAgImZ1bGxzY3JlZW5fZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImJv"
    "cmRlcmxlc3NfZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICB9LAogICAgICAgICJtb2R1bGVfdGFiX29yZGVyIjogW10s"
    "CiAgICAgICAgIm1haW5fc3BsaXR0ZXIiOiB7CiAgICAgICAgICAgICJob3Jpem9udGFsX3NpemVzIjogWzkwMCwgNTAwXSwKICAg"
    "ICAgICB9LAogICAgICAgICJmaXJzdF9ydW4iOiBUcnVlLAogICAgfQoKZGVmIGxvYWRfY29uZmlnKCkgLT4gZGljdDoKICAgICIi"
    "IkxvYWQgY29uZmlnLmpzb24uIFJldHVybnMgZGVmYXVsdCBpZiBtaXNzaW5nIG9yIGNvcnJ1cHQuIiIiCiAgICBpZiBub3QgQ09O"
    "RklHX1BBVEguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygpCiAgICB0cnk6CiAgICAgICAgd2l0aCBD"
    "T05GSUdfUEFUSC5vcGVuKCJyIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZChm"
    "KQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKCmRlZiBzYXZlX2NvbmZpZyhj"
    "Zmc6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJXcml0ZSBjb25maWcuanNvbi4iIiIKICAgIENPTkZJR19QQVRILnBhcmVudC5ta2Rp"
    "cihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInciLCBlbmNvZGluZz0idXRm"
    "LTgiKSBhcyBmOgogICAgICAgIGpzb24uZHVtcChjZmcsIGYsIGluZGVudD0yKQoKIyBMb2FkIGNvbmZpZyBhdCBtb2R1bGUgbGV2"
    "ZWwg4oCUIGV2ZXJ5dGhpbmcgYmVsb3cgcmVhZHMgZnJvbSBDRkcKQ0ZHID0gbG9hZF9jb25maWcoKQpfZWFybHlfbG9nKGYiW0lO"
    "SVRdIENvbmZpZyBsb2FkZWQg4oCUIGZpcnN0X3J1bj17Q0ZHLmdldCgnZmlyc3RfcnVuJyl9LCBtb2RlbF90eXBlPXtDRkcuZ2V0"
    "KCdtb2RlbCcse30pLmdldCgndHlwZScpfSIpCgpfREVGQVVMVF9QQVRIUzogZGljdFtzdHIsIFBhdGhdID0gewogICAgImZhY2Vz"
    "IjogICAgU0NSSVBUX0RJUiAvICJGYWNlcyIsCiAgICAic291bmRzIjogICBTQ1JJUFRfRElSIC8gInNvdW5kcyIsCiAgICAibWVt"
    "b3JpZXMiOiBTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiwKICAgICJzZXNzaW9ucyI6IFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiLAog"
    "ICAgInNsIjogICAgICAgU0NSSVBUX0RJUiAvICJzbCIsCiAgICAiZXhwb3J0cyI6ICBTQ1JJUFRfRElSIC8gImV4cG9ydHMiLAog"
    "ICAgImxvZ3MiOiAgICAgU0NSSVBUX0RJUiAvICJsb2dzIiwKICAgICJiYWNrdXBzIjogIFNDUklQVF9ESVIgLyAiYmFja3VwcyIs"
    "CiAgICAicGVyc29uYXMiOiBTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiwKICAgICJnb29nbGUiOiAgIFNDUklQVF9ESVIgLyAiZ29v"
    "Z2xlIiwKfQoKZGVmIF9ub3JtYWxpemVfY29uZmlnX3BhdGhzKCkgLT4gTm9uZToKICAgICIiIgogICAgU2VsZi1oZWFsIG9sZGVy"
    "IGNvbmZpZy5qc29uIGZpbGVzIG1pc3NpbmcgcmVxdWlyZWQgcGF0aCBrZXlzLgogICAgQWRkcyBtaXNzaW5nIHBhdGgga2V5cyBh"
    "bmQgbm9ybWFsaXplcyBnb29nbGUgY3JlZGVudGlhbC90b2tlbiBsb2NhdGlvbnMsCiAgICB0aGVuIHBlcnNpc3RzIGNvbmZpZy5q"
    "c29uIGlmIGFueXRoaW5nIGNoYW5nZWQuCiAgICAiIiIKICAgIGNoYW5nZWQgPSBGYWxzZQogICAgcGF0aHMgPSBDRkcuc2V0ZGVm"
    "YXVsdCgicGF0aHMiLCB7fSkKICAgIGZvciBrZXksIGRlZmF1bHRfcGF0aCBpbiBfREVGQVVMVF9QQVRIUy5pdGVtcygpOgogICAg"
    "ICAgIGlmIG5vdCBwYXRocy5nZXQoa2V5KToKICAgICAgICAgICAgcGF0aHNba2V5XSA9IHN0cihkZWZhdWx0X3BhdGgpCiAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCgoKICAgIHNwbGl0dGVyX2NmZyA9IENGRy5zZXRkZWZhdWx0KCJtYWluX3NwbGl0dGVyIiwg"
    "e30pCiAgICBpZiBub3QgaXNpbnN0YW5jZShzcGxpdHRlcl9jZmcsIGRpY3QpOgogICAgICAgIENGR1sibWFpbl9zcGxpdHRlciJd"
    "ID0geyJob3Jpem9udGFsX3NpemVzIjogWzkwMCwgNTAwXX0KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgZWxzZToKICAgICAg"
    "ICBzaXplcyA9IHNwbGl0dGVyX2NmZy5nZXQoImhvcml6b250YWxfc2l6ZXMiKQogICAgICAgIHZhbGlkX3NpemVzID0gKAogICAg"
    "ICAgICAgICBpc2luc3RhbmNlKHNpemVzLCBsaXN0KQogICAgICAgICAgICBhbmQgbGVuKHNpemVzKSA9PSAyCiAgICAgICAgICAg"
    "IGFuZCBhbGwoaXNpbnN0YW5jZSh2LCBpbnQpIGZvciB2IGluIHNpemVzKQogICAgICAgICkKICAgICAgICBpZiBub3QgdmFsaWRf"
    "c2l6ZXM6CiAgICAgICAgICAgIHNwbGl0dGVyX2NmZ1siaG9yaXpvbnRhbF9zaXplcyJdID0gWzkwMCwgNTAwXQogICAgICAgICAg"
    "ICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKZGVmIGNmZ19wYXRoKGtl"
    "eTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBh"
    "IFBhdGggb2JqZWN0IHdpdGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7"
    "fSkKICAgIHZhbHVlID0gcGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAg"
    "ZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQoa2V5KQogICAgaWYgZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0"
    "cihmYWxsYmFjaykKICAgICAgICByZXR1cm4gZmFsbGJhY2sKICAgIHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXpl"
    "X2NvbmZpZ19wYXRocygpCgojIOKUgOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRl"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIENfUFJJTUFSWSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQs"
    "IENfVEVYVF9ESU0gYXJlIGluamVjdGVkIGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRo"
    "aW5nIGJlbG93IGlzIGRlcml2ZWQgZnJvbSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1h"
    "cCBwZXJzb25hIGNvbG9ycyB0byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BS"
    "SU1BUlkgICAgICAgICAgIyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0cykKQ19DUklNU09OX0RJTSA9"
    "IENfUFJJTUFSWSArICI4OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09O"
    "REFSWSAgICAgICAgIyBtYWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSAr"
    "ICI4OCIgIyBkaW0gc2Vjb25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBlbXBoYXNpcywgaG92ZXIg"
    "c3RhdGVzCkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElNICAgICAgICAgIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3Rl"
    "ZCkKQ19TSUxWRVJfRElNICA9IENfVEVYVF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0g"
    "Q19CRyAgICAgICAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkcyICAgICAg"
    "ICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyAgICAgICAgID0gQ19QQU5FTCAgICAg"
    "ICAgICAgICMgdGVydGlhcnkvaW5wdXQgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIw"
    "MDAwJyAgICAgICAgICAjIGVycm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9ICcjODg1NWNj"
    "JyAgICAgICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAnIzJhMDUyYScgICAgICAg"
    "ICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjNDRhYTY2JyAgICAgICAgICAjIHBvc2l0aXZl"
    "IHN0YXRlcyDigJQgdW5pdmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZvIHN0YXRlcyDigJQg"
    "dW5pdmVyc2FsCgojIEZvbnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQgbmFtZSBmb3IgUUZvbnQoKSBjYWxscwpE"
    "RUNLX0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBj"
    "b2xvciBtYXBwaW5nIChmb3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsK"
    "ICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAgInNtdWciOiAgICAgICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09M"
    "RCwKICAgICJyZWxpZXZlZCI6ICAgQ19HT0xELAogICAgImhhcHB5IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENf"
    "R09MRCwKICAgICJwYW5pY2tlZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04sCiAgICAic2hvY2tl"
    "ZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIs"
    "CiAgICAic2FkIjogICAgICAgICIjY2M2NjIyIiwKICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6"
    "ICAiI2NjNjYyMiIsCiAgICAicGxvdHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJl"
    "bnZpb3VzIjogICAgQ19QVVJQTEUsCiAgICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0IjogICAgICBDX1NJTFZF"
    "UiwKICAgICJuZXV0cmFsIjogICAgQ19URVhUX0RJTSwKfQoKIyDilIDilIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgUlVORVMgaXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVT"
    "ID0gVUlfUlVORVMKCiMgRmFjZSBpbWFnZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNv"
    "bmZpZyBwYXRocy5mYWNlcwpGQUNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9Q"
    "UkVGSVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9j"
    "dXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9T"
    "bXVnLnBuZyIsCiAgICAiY29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQiOiAgICAg"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGll"
    "dmVkLnBuZyIsCiAgICAiaW1wcmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAgICJ2aWN0b3J5Ijog"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0"
    "ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMucG5nIiwKICAgICJwYW5pY2tlZCI6"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJFRklYfV9DaGVhdF9N"
    "b2RlLnBuZyIsCiAgICAiYW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciLAogICAgInBsb3R0aW5nIjogICBm"
    "IntGQUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5n"
    "IiwKICAgICJoYXBweSI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0Vf"
    "UFJFRklYfV9GbGlydHkucG5nIiwKICAgICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAg"
    "ImVudmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5USU1FTlRfTElTVCA9ICgKICAgICJuZXV0"
    "cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmVkLCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0"
    "b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNpb3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFw"
    "cHksIGZsaXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBpbmplY3RlZCBmcm9t"
    "IHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMg"
    "U1lTVEVNX1BST01QVF9CQVNFIGlzIGFscmVhZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0"
    "aW9uLgojIERvIG5vdCByZWRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSAClNUWUxFID0gZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9Owog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewogICAg"
    "YmFja2dyb3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsK"
    "ICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOiB7Q19D"
    "UklNU09OX0RJTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19H"
    "T0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1m"
    "YW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHggMTJweDsKfX0KUUxp"
    "bmVFZGl0OmZvY3VzIHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BB"
    "TkVMfTsKfX0KUVB1c2hCdXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7"
    "Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9u"
    "dC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAg"
    "IHBhZGRpbmc6IDhweCAyMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJh"
    "Y2tncm91bmQtY29sb3I6IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUVB1c2hCdXR0b246cHJl"
    "c3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9OwogICAgYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBj"
    "b2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0dG9uOmRpc2FibGVkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9Owog"
    "ICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xsQmFyOnZlcnRp"
    "Y2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4OwogICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xs"
    "QmFyOjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6"
    "IDNweDsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsK"
    "fX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiAgICBoZWln"
    "aHQ6IDBweDsKfX0KUVRhYldpZGdldDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAg"
    "YmFja2dyb3VuZDoge0NfQkcyfTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6"
    "IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4"
    "OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2lu"
    "ZzogMXB4Owp9fQpRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNv"
    "bG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhv"
    "dmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQg"
    "e3sKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1J"
    "TFl9OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6"
    "IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAg"
    "ICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6"
    "IDEwcHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21ib0JveCB7ewogICAg"
    "YmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94"
    "Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRlcjogbm9uZTsKfX0KUUNoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBm"
    "b250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6"
    "IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICB3aWR0aDog"
    "MnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGly"
    "ZWN0b3JpZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9u"
    "J3QgZXhpc3QuCiAgICBDYWxsZWQgb24gc3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxl"
    "IHRpbWVzLgogICAgQWxzbyBtaWdyYXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRl"
    "Y3RlZC4KICAgICIiIgogICAgZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic291"
    "bmRzIiksCiAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAg"
    "Y2ZnX3BhdGgoInNsIiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAg"
    "ICAgIGNmZ19wYXRoKCJiYWNrdXBzIiksCiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICBdCiAgICBmb3IgZCBpbiBk"
    "aXJzOgogICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05M"
    "IGZpbGVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZu"
    "YW1lIGluICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAgICAgICAgICAg"
    "ICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVtb3J5X2Rp"
    "ciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGlu"
    "Zz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4gKCJzbF9zY2Fucy5qc29ubCIs"
    "ICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3Rz"
    "KCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lvbnNfZGlyID0gY2Zn"
    "X3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICBpZiBub3Qg"
    "aWR4LmV4aXN0cygpOgogICAgICAgIGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIp"
    "LCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qg"
    "c3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShzdGF0ZV9wYXRoKQoKICAgIGluZGV4X3Bh"
    "dGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICBpbmRl"
    "eF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9t"
    "ZXNzYWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9MiksCiAgICAg"
    "ICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgIyBMZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFf"
    "TWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxlcwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3Jp"
    "dGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6"
    "IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAw"
    "LAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFz"
    "dF9hY3RpdmUiOiBOb25lLAogICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwK"
    "ICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjoge30sCiAgICAgICAgImFpX3N0YXRlX2F0X3NodXRkb3duIjogIkRPUk1BTlQi"
    "LAogICAgfQogICAgcGF0aC53cml0ZV90ZXh0KGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IikK"
    "CmRlZiBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBJZiBvbGQgRDpcXEFJXFxNb2RlbHNcXFtE"
    "ZWNrTmFtZV1fTWVtb3JpZXMgbGF5b3V0IGlzIGRldGVjdGVkLAogICAgbWlncmF0ZSBmaWxlcyB0byBuZXcgc3RydWN0dXJlIHNp"
    "bGVudGx5LgogICAgIiIiCiAgICAjIFRyeSB0byBmaW5kIG9sZCBsYXlvdXQgcmVsYXRpdmUgdG8gbW9kZWwgcGF0aAogICAgbW9k"
    "ZWxfcGF0aCA9IFBhdGgoQ0ZHWyJtb2RlbCJdLmdldCgicGF0aCIsICIiKSkKICAgIGlmIG5vdCBtb2RlbF9wYXRoLmV4aXN0cygp"
    "OgogICAgICAgIHJldHVybgogICAgb2xkX3Jvb3QgPSBtb2RlbF9wYXRoLnBhcmVudCAvIGYie0RFQ0tfTkFNRX1fTWVtb3JpZXMi"
    "CiAgICBpZiBub3Qgb2xkX3Jvb3QuZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgbWlncmF0aW9ucyA9IFsKICAgICAgICAo"
    "b2xkX3Jvb3QgLyAibWVtb3JpZXMuanNvbmwiLCAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVtb3JpZXMuanNv"
    "bmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAibWVzc2FnZXMuanNvbmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gIm1lc3NhZ2VzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInRhc2tzLmpzb25sIiwgICAgICAgICAgICAgICBjZmdf"
    "cGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzdGF0ZS5qc29uIiwgICAgICAg"
    "ICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAic3RhdGUuanNvbiIpLAogICAgICAgIChvbGRfcm9vdCAvICJpbmRleC5q"
    "c29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiaW5kZXguanNvbiIpLAogICAgICAgIChvbGRfcm9v"
    "dCAvICJzbF9zY2Fucy5qc29ubCIsICAgICAgICAgICAgY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiKSwKICAgICAg"
    "ICAob2xkX3Jvb3QgLyAic2xfY29tbWFuZHMuanNvbmwiLCAgICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpz"
    "b25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNvdW5kcyIgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpIC8gZiJ7U09VTkRfUFJF"
    "RklYfV9hbGVydC53YXYiKSwKICAgIF0KCiAgICBmb3Igc3JjLCBkc3QgaW4gbWlncmF0aW9uczoKICAgICAgICBpZiBzcmMuZXhp"
    "c3RzKCkgYW5kIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGRzdC5wYXJlbnQubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAg"
    "ICAgc2h1dGlsLmNvcHkyKHN0cihzcmMpLCBzdHIoZHN0KSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgICAgIHBhc3MKCiAgICAjIE1pZ3JhdGUgZmFjZSBpbWFnZXMKICAgIG9sZF9mYWNlcyA9IG9sZF9yb290IC8gIkZhY2VzIgog"
    "ICAgbmV3X2ZhY2VzID0gY2ZnX3BhdGgoImZhY2VzIikKICAgIGlmIG9sZF9mYWNlcy5leGlzdHMoKToKICAgICAgICBmb3IgaW1n"
    "IGluIG9sZF9mYWNlcy5nbG9iKCIqLnBuZyIpOgogICAgICAgICAgICBkc3QgPSBuZXdfZmFjZXMgLyBpbWcubmFtZQogICAgICAg"
    "ICAgICBpZiBub3QgZHN0LmV4aXN0cygpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGltcG9ydCBz"
    "aHV0aWwKICAgICAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIoc3RyKGltZyksIHN0cihkc3QpKQogICAgICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgojIOKUgOKUgCBEQVRFVElNRSBIRUxQRVJTIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbG9jYWxfbm93X2lzbygpIC0+IHN0cjoKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5y"
    "ZXBsYWNlKG1pY3Jvc2Vjb25kPTApLmlzb2Zvcm1hdCgpCgpkZWYgcGFyc2VfaXNvKHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2Rh"
    "dGV0aW1lXToKICAgIGlmIG5vdCB2YWx1ZToKICAgICAgICByZXR1cm4gTm9uZQogICAgdmFsdWUgPSB2YWx1ZS5zdHJpcCgpCiAg"
    "ICB0cnk6CiAgICAgICAgaWYgdmFsdWUuZW5kc3dpdGgoIloiKToKICAgICAgICAgICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29m"
    "b3JtYXQodmFsdWVbOi0xXSkucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKQogICAgICAgIHJldHVybiBkYXRldGltZS5mcm9t"
    "aXNvZm9ybWF0KHZhbHVlKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gTm9uZQoKX0RBVEVUSU1FX05PUk1B"
    "TElaQVRJT05fTE9HR0VEOiBzZXRbdHVwbGVdID0gc2V0KCkKCgpkZWYgX3Jlc29sdmVfZGVja190aW1lem9uZV9uYW1lKCkgLT4g"
    "T3B0aW9uYWxbc3RyXToKICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRp"
    "Y3QpIGVsc2Uge30KICAgIGF1dG9fZGV0ZWN0ID0gYm9vbChzZXR0aW5ncy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1"
    "ZSkpCiAgICBvdmVycmlkZSA9IHN0cihzZXR0aW5ncy5nZXQoInRpbWV6b25lX292ZXJyaWRlIiwgIiIpIG9yICIiKS5zdHJpcCgp"
    "CiAgICBpZiBub3QgYXV0b19kZXRlY3QgYW5kIG92ZXJyaWRlOgogICAgICAgIHJldHVybiBvdmVycmlkZQogICAgbG9jYWxfdHpp"
    "bmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbwogICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgog"
    "ICAgICAgIHR6X2tleSA9IGdldGF0dHIobG9jYWxfdHppbmZvLCAia2V5IiwgTm9uZSkKICAgICAgICBpZiB0el9rZXk6CiAgICAg"
    "ICAgICAgIHJldHVybiBzdHIodHpfa2V5KQogICAgICAgIHR6X25hbWUgPSBzdHIobG9jYWxfdHppbmZvKQogICAgICAgIGlmIHR6"
    "X25hbWUgYW5kIHR6X25hbWUudXBwZXIoKSAhPSAiTE9DQUwiOgogICAgICAgICAgICByZXR1cm4gdHpfbmFtZQogICAgcmV0dXJu"
    "IE5vbmUKCgpkZWYgX2xvY2FsX3R6aW5mbygpOgogICAgdHpfbmFtZSA9IF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgpCiAg"
    "ICBpZiB0el9uYW1lOgogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIFpvbmVJbmZvKHR6X25hbWUpCiAgICAgICAgZXhj"
    "ZXB0IFpvbmVJbmZvTm90Rm91bmRFcnJvcjoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltEQVRFVElNRV1bV0FSTl0gVW5rbm93"
    "biB0aW1lem9uZSBvdmVycmlkZSAne3R6X25hbWV9JywgdXNpbmcgc3lzdGVtIGxvY2FsIHRpbWV6b25lLiIpCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emlu"
    "Zm8gb3IgdGltZXpvbmUudXRjCgoKZGVmIG5vd19mb3JfY29tcGFyZSgpOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdyhfbG9jYWxf"
    "dHppbmZvKCkpCgoKZGVmIG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdF92YWx1ZSwgY29udGV4dDogc3RyID0gIiIp"
    "OgogICAgaWYgZHRfdmFsdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gTm9uZQogICAgaWYgbm90IGlzaW5zdGFuY2UoZHRfdmFs"
    "dWUsIGRhdGV0aW1lKToKICAgICAgICByZXR1cm4gTm9uZQogICAgbG9jYWxfdHogPSBfbG9jYWxfdHppbmZvKCkKICAgIGlmIGR0"
    "X3ZhbHVlLnR6aW5mbyBpcyBOb25lOgogICAgICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5yZXBsYWNlKHR6aW5mbz1sb2NhbF90"
    "eikKICAgICAgICBrZXkgPSAoIm5haXZlIiwgY29udGV4dCkKICAgICAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJ"
    "WkFUSU9OX0xPR0dFRDoKICAgICAgICAgICAgX2Vhcmx5X2xvZygKICAgICAgICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBO"
    "b3JtYWxpemVkIG5haXZlIGRhdGV0aW1lIHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBh"
    "cmlzb25zLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQuYWRkKGtleSkK"
    "ICAgICAgICByZXR1cm4gbm9ybWFsaXplZAogICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLmFzdGltZXpvbmUobG9jYWxfdHopCiAg"
    "ICBkdF90el9uYW1lID0gc3RyKGR0X3ZhbHVlLnR6aW5mbykKICAgIGtleSA9ICgiYXdhcmUiLCBjb250ZXh0LCBkdF90el9uYW1l"
    "KQogICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQgYW5kIGR0X3R6X25hbWUgbm90IGluIHsi"
    "VVRDIiwgc3RyKGxvY2FsX3R6KX06CiAgICAgICAgX2Vhcmx5X2xvZygKICAgICAgICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5v"
    "cm1hbGl6ZWQgdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZnJvbSB7ZHRfdHpfbmFtZX0gdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtj"
    "b250ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICkKICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElP"
    "Tl9MT0dHRUQuYWRkKGtleSkKICAgIHJldHVybiBub3JtYWxpemVkCgoKZGVmIHBhcnNlX2lzb19mb3JfY29tcGFyZSh2YWx1ZSwg"
    "Y29udGV4dDogc3RyID0gIiIpOgogICAgcmV0dXJuIG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZV9pc28odmFs"
    "dWUpLCBjb250ZXh0PWNvbnRleHQpCgoKZGVmIF90YXNrX2R1ZV9zb3J0X2tleSh0YXNrOiBkaWN0KToKICAgIGR1ZSA9IHBhcnNl"
    "X2lzb19mb3JfY29tcGFyZSgodGFzayBvciB7fSkuZ2V0KCJkdWVfYXQiKSBvciAodGFzayBvciB7fSkuZ2V0KCJkdWUiKSwgY29u"
    "dGV4dD0idGFza19zb3J0IikKICAgIGlmIGR1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiAoMSwgZGF0ZXRpbWUubWF4LnJlcGxh"
    "Y2UodHppbmZvPXRpbWV6b25lLnV0YykpCiAgICByZXR1cm4gKDAsIGR1ZS5hc3RpbWV6b25lKHRpbWV6b25lLnV0YyksICgodGFz"
    "ayBvciB7fSkuZ2V0KCJ0ZXh0Iikgb3IgIiIpLmxvd2VyKCkpCgoKZGVmIGZvcm1hdF9kdXJhdGlvbihzZWNvbmRzOiBmbG9hdCkg"
    "LT4gc3RyOgogICAgdG90YWwgPSBtYXgoMCwgaW50KHNlY29uZHMpKQogICAgZGF5cywgcmVtID0gZGl2bW9kKHRvdGFsLCA4NjQw"
    "MCkKICAgIGhvdXJzLCByZW0gPSBkaXZtb2QocmVtLCAzNjAwKQogICAgbWludXRlcywgc2VjcyA9IGRpdm1vZChyZW0sIDYwKQog"
    "ICAgcGFydHMgPSBbXQogICAgaWYgZGF5czogICAgcGFydHMuYXBwZW5kKGYie2RheXN9ZCIpCiAgICBpZiBob3VyczogICBwYXJ0"
    "cy5hcHBlbmQoZiJ7aG91cnN9aCIpCiAgICBpZiBtaW51dGVzOiBwYXJ0cy5hcHBlbmQoZiJ7bWludXRlc31tIikKICAgIGlmIG5v"
    "dCBwYXJ0czogcGFydHMuYXBwZW5kKGYie3NlY3N9cyIpCiAgICByZXR1cm4gIiAiLmpvaW4ocGFydHNbOjNdKQoKIyDilIDilIAg"
    "TU9PTiBQSEFTRSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENvcnJlY3RlZCBpbGx1bWluYXRpb24gbWF0aCDigJQgZGlz"
    "cGxheWVkIG1vb24gbWF0Y2hlcyBsYWJlbGVkIHBoYXNlLgoKX0tOT1dOX05FV19NT09OID0gZGF0ZSgyMDAwLCAxLCA2KQpfTFVO"
    "QVJfQ1lDTEUgICAgPSAyOS41MzA1ODg2NwoKZGVmIGdldF9tb29uX3BoYXNlKCkgLT4gdHVwbGVbZmxvYXQsIHN0ciwgZmxvYXRd"
    "OgogICAgIiIiCiAgICBSZXR1cm5zIChwaGFzZV9mcmFjdGlvbiwgcGhhc2VfbmFtZSwgaWxsdW1pbmF0aW9uX3BjdCkuCiAgICBw"
    "aGFzZV9mcmFjdGlvbjogMC4wID0gbmV3IG1vb24sIDAuNSA9IGZ1bGwgbW9vbiwgMS4wID0gbmV3IG1vb24gYWdhaW4uCiAgICBp"
    "bGx1bWluYXRpb25fcGN0OiAw4oCTMTAwLCBjb3JyZWN0ZWQgdG8gbWF0Y2ggdmlzdWFsIHBoYXNlLgogICAgIiIiCiAgICBkYXlz"
    "ICA9IChkYXRlLnRvZGF5KCkgLSBfS05PV05fTkVXX01PT04pLmRheXMKICAgIGN5Y2xlID0gZGF5cyAlIF9MVU5BUl9DWUNMRQog"
    "ICAgcGhhc2UgPSBjeWNsZSAvIF9MVU5BUl9DWUNMRQoKICAgIGlmICAgY3ljbGUgPCAxLjg1OiAgIG5hbWUgPSAiTkVXIE1PT04i"
    "CiAgICBlbGlmIGN5Y2xlIDwgNy4zODogICBuYW1lID0gIldBWElORyBDUkVTQ0VOVCIKICAgIGVsaWYgY3ljbGUgPCA5LjIyOiAg"
    "IG5hbWUgPSAiRklSU1QgUVVBUlRFUiIKICAgIGVsaWYgY3ljbGUgPCAxNC43NzogIG5hbWUgPSAiV0FYSU5HIEdJQkJPVVMiCiAg"
    "ICBlbGlmIGN5Y2xlIDwgMTYuNjE6ICBuYW1lID0gIkZVTEwgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCAyMi4xNTogIG5hbWUgPSAi"
    "V0FOSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwgMjMuOTk6ICBuYW1lID0gIkxBU1QgUVVBUlRFUiIKICAgIGVsc2U6ICAg"
    "ICAgICAgICAgICAgIG5hbWUgPSAiV0FOSU5HIENSRVNDRU5UIgoKICAgICMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbjogY29zLWJh"
    "c2VkLCBwZWFrcyBhdCBmdWxsIG1vb24KICAgIGlsbHVtaW5hdGlvbiA9ICgxIC0gbWF0aC5jb3MoMiAqIG1hdGgucGkgKiBwaGFz"
    "ZSkpIC8gMiAqIDEwMAogICAgcmV0dXJuIHBoYXNlLCBuYW1lLCByb3VuZChpbGx1bWluYXRpb24sIDEpCgpfU1VOX0NBQ0hFX0RB"
    "VEU6IE9wdGlvbmFsW2RhdGVdID0gTm9uZQpfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU46IE9wdGlvbmFsW2ludF0gPSBOb25lCl9T"
    "VU5fQ0FDSEVfVElNRVM6IHR1cGxlW3N0ciwgc3RyXSA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKZGVmIF9yZXNvbHZlX3NvbGFyX2Nv"
    "b3JkaW5hdGVzKCkgLT4gdHVwbGVbZmxvYXQsIGZsb2F0XToKICAgICIiIgogICAgUmVzb2x2ZSBsYXRpdHVkZS9sb25naXR1ZGUg"
    "ZnJvbSBydW50aW1lIGNvbmZpZyB3aGVuIGF2YWlsYWJsZS4KICAgIEZhbGxzIGJhY2sgdG8gdGltZXpvbmUtZGVyaXZlZCBjb2Fy"
    "c2UgZGVmYXVsdHMuCiAgICAiIiIKICAgIGxhdCA9IE5vbmUKICAgIGxvbiA9IE5vbmUKICAgIHRyeToKICAgICAgICBzZXR0aW5n"
    "cyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAgZm9yIGtl"
    "eSBpbiAoImxhdGl0dWRlIiwgImxhdCIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAgICAgICBs"
    "YXQgPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICBmb3Iga2V5IGluICgibG9uZ2l0"
    "dWRlIiwgImxvbiIsICJsbmciKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAgbG9uID0g"
    "ZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIGxh"
    "dCA9IE5vbmUKICAgICAgICBsb24gPSBOb25lCgogICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAg"
    "ICB0el9vZmZzZXQgPSBub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApCiAgICB0el9vZmZzZXRfaG91cnMgPSB0"
    "el9vZmZzZXQudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCgogICAgaWYgbG9uIGlzIE5vbmU6CiAgICAgICAgbG9uID0gbWF4KC0x"
    "ODAuMCwgbWluKDE4MC4wLCB0el9vZmZzZXRfaG91cnMgKiAxNS4wKSkKCiAgICBpZiBsYXQgaXMgTm9uZToKICAgICAgICB0el9u"
    "YW1lID0gc3RyKG5vd19sb2NhbC50emluZm8gb3IgIiIpCiAgICAgICAgc291dGhfaGludCA9IGFueSh0b2tlbiBpbiB0el9uYW1l"
    "IGZvciB0b2tlbiBpbiAoIkF1c3RyYWxpYSIsICJQYWNpZmljL0F1Y2tsYW5kIiwgIkFtZXJpY2EvU2FudGlhZ28iKSkKICAgICAg"
    "ICBsYXQgPSAtMzUuMCBpZiBzb3V0aF9oaW50IGVsc2UgMzUuMAoKICAgIGxhdCA9IG1heCgtNjYuMCwgbWluKDY2LjAsIGxhdCkp"
    "CiAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIGxvbikpCiAgICByZXR1cm4gbGF0LCBsb24KCmRlZiBfY2FsY19zb2xh"
    "cl9ldmVudF9taW51dGVzKGxvY2FsX2RheTogZGF0ZSwgbGF0aXR1ZGU6IGZsb2F0LCBsb25naXR1ZGU6IGZsb2F0LCBzdW5yaXNl"
    "OiBib29sKSAtPiBPcHRpb25hbFtmbG9hdF06CiAgICAiIiJOT0FBLXN0eWxlIHN1bnJpc2Uvc3Vuc2V0IHNvbHZlci4gUmV0dXJu"
    "cyBsb2NhbCBtaW51dGVzIGZyb20gbWlkbmlnaHQuIiIiCiAgICBuID0gbG9jYWxfZGF5LnRpbWV0dXBsZSgpLnRtX3lkYXkKICAg"
    "IGxuZ19ob3VyID0gbG9uZ2l0dWRlIC8gMTUuMAogICAgdCA9IG4gKyAoKDYgLSBsbmdfaG91cikgLyAyNC4wKSBpZiBzdW5yaXNl"
    "IGVsc2UgbiArICgoMTggLSBsbmdfaG91cikgLyAyNC4wKQoKICAgIE0gPSAoMC45ODU2ICogdCkgLSAzLjI4OQogICAgTCA9IE0g"
    "KyAoMS45MTYgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoTSkpKSArICgwLjAyMCAqIG1hdGguc2luKG1hdGgucmFkaWFucygyICog"
    "TSkpKSArIDI4Mi42MzQKICAgIEwgPSBMICUgMzYwLjAKCiAgICBSQSA9IG1hdGguZGVncmVlcyhtYXRoLmF0YW4oMC45MTc2NCAq"
    "IG1hdGgudGFuKG1hdGgucmFkaWFucyhMKSkpKQogICAgUkEgPSBSQSAlIDM2MC4wCiAgICBMX3F1YWRyYW50ID0gKG1hdGguZmxv"
    "b3IoTCAvIDkwLjApKSAqIDkwLjAKICAgIFJBX3F1YWRyYW50ID0gKG1hdGguZmxvb3IoUkEgLyA5MC4wKSkgKiA5MC4wCiAgICBS"
    "QSA9IChSQSArIChMX3F1YWRyYW50IC0gUkFfcXVhZHJhbnQpKSAvIDE1LjAKCiAgICBzaW5fZGVjID0gMC4zOTc4MiAqIG1hdGgu"
    "c2luKG1hdGgucmFkaWFucyhMKSkKICAgIGNvc19kZWMgPSBtYXRoLmNvcyhtYXRoLmFzaW4oc2luX2RlYykpCgogICAgemVuaXRo"
    "ID0gOTAuODMzCiAgICBjb3NfaCA9IChtYXRoLmNvcyhtYXRoLnJhZGlhbnMoemVuaXRoKSkgLSAoc2luX2RlYyAqIG1hdGguc2lu"
    "KG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKSkgLyAoY29zX2RlYyAqIG1hdGguY29zKG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKQog"
    "ICAgaWYgY29zX2ggPCAtMS4wIG9yIGNvc19oID4gMS4wOgogICAgICAgIHJldHVybiBOb25lCgogICAgaWYgc3VucmlzZToKICAg"
    "ICAgICBIID0gMzYwLjAgLSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkKICAgIGVsc2U6CiAgICAgICAgSCA9IG1hdGgu"
    "ZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAgSCAvPSAxNS4wCgogICAgVCA9IEggKyBSQSAtICgwLjA2NTcxICogdCkgLSA2"
    "LjYyMgogICAgVVQgPSAoVCAtIGxuZ19ob3VyKSAlIDI0LjAKCiAgICBsb2NhbF9vZmZzZXRfaG91cnMgPSAoZGF0ZXRpbWUubm93"
    "KCkuYXN0aW1lem9uZSgpLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCiAgICBs"
    "b2NhbF9ob3VyID0gKFVUICsgbG9jYWxfb2Zmc2V0X2hvdXJzKSAlIDI0LjAKICAgIHJldHVybiBsb2NhbF9ob3VyICogNjAuMAoK"
    "ZGVmIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShtaW51dGVzX2Zyb21fbWlkbmlnaHQ6IE9wdGlvbmFsW2Zsb2F0XSkgLT4gc3Ry"
    "OgogICAgaWYgbWludXRlc19mcm9tX21pZG5pZ2h0IGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICItLTotLSIKICAgIG1pbnMgPSBp"
    "bnQocm91bmQobWludXRlc19mcm9tX21pZG5pZ2h0KSkgJSAoMjQgKiA2MCkKICAgIGhoLCBtbSA9IGRpdm1vZChtaW5zLCA2MCkK"
    "ICAgIHJldHVybiBkYXRldGltZS5ub3coKS5yZXBsYWNlKGhvdXI9aGgsIG1pbnV0ZT1tbSwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25k"
    "PTApLnN0cmZ0aW1lKCIlSDolTSIpCgpkZWYgZ2V0X3N1bl90aW1lcygpIC0+IHR1cGxlW3N0ciwgc3RyXToKICAgICIiIgogICAg"
    "Q29tcHV0ZSBsb2NhbCBzdW5yaXNlL3N1bnNldCB1c2luZyBzeXN0ZW0gZGF0ZSArIHRpbWV6b25lIGFuZCBvcHRpb25hbAogICAg"
    "cnVudGltZSBsYXRpdHVkZS9sb25naXR1ZGUgaGludHMgd2hlbiBhdmFpbGFibGUuCiAgICBDYWNoZWQgcGVyIGxvY2FsIGRhdGUg"
    "YW5kIHRpbWV6b25lIG9mZnNldC4KICAgICIiIgogICAgZ2xvYmFsIF9TVU5fQ0FDSEVfREFURSwgX1NVTl9DQUNIRV9UWl9PRkZT"
    "RVRfTUlOLCBfU1VOX0NBQ0hFX1RJTUVTCgogICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0"
    "b2RheSA9IG5vd19sb2NhbC5kYXRlKCkKICAgIHR6X29mZnNldF9taW4gPSBpbnQoKG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0"
    "aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAvLyA2MCkKCiAgICBpZiBfU1VOX0NBQ0hFX0RBVEUgPT0gdG9kYXkgYW5kIF9T"
    "VU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9PSB0el9vZmZzZXRfbWluOgogICAgICAgIHJldHVybiBfU1VOX0NBQ0hFX1RJTUVTCgog"
    "ICAgdHJ5OgogICAgICAgIGxhdCwgbG9uID0gX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKQogICAgICAgIHN1bnJpc2VfbWlu"
    "ID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9VHJ1ZSkKICAgICAgICBzdW5zZXRf"
    "bWluID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9RmFsc2UpCiAgICAgICAgaWYg"
    "c3VucmlzZV9taW4gaXMgTm9uZSBvciBzdW5zZXRfbWluIGlzIE5vbmU6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlNv"
    "bGFyIGV2ZW50IHVuYXZhaWxhYmxlIGZvciByZXNvbHZlZCBjb29yZGluYXRlcyIpCiAgICAgICAgdGltZXMgPSAoX2Zvcm1hdF9s"
    "b2NhbF9zb2xhcl90aW1lKHN1bnJpc2VfbWluKSwgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKHN1bnNldF9taW4pKQogICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICB0aW1lcyA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKICAgIF9TVU5fQ0FDSEVfREFURSA9IHRv"
    "ZGF5CiAgICBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPSB0el9vZmZzZXRfbWluCiAgICBfU1VOX0NBQ0hFX1RJTUVTID0gdGlt"
    "ZXMKICAgIHJldHVybiB0aW1lcwoKIyDilIDilIAgVkFNUElSRSBTVEFURSBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVGltZS1vZi1k"
    "YXkgYmVoYXZpb3JhbCBzdGF0ZS4gQWN0aXZlIG9ubHkgd2hlbiBBSV9TVEFURVNfRU5BQkxFRD1UcnVlLgojIEluamVjdGVkIGlu"
    "dG8gc3lzdGVtIHByb21wdCBvbiBldmVyeSBnZW5lcmF0aW9uIGNhbGwuCgpBSV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsK"
    "ICAgICJXSVRDSElORyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93"
    "ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30sICAgICAgICAiY29sb3IiOiBDX1BVUlBM"
    "RSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lMSUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNv"
    "bG9yIjogQ19TSUxWRVIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgs"
    "OSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVNUTEVTUyBTTEVFUCI6IHsiaG91"
    "cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6"
    "ICAgICAgIHsiaG91cnMiOiB7MTYsMTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAg"
    "ICJBV0FLRU5FRCI6ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2Vy"
    "IjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsiaG91cnMiOiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09O"
    "LCAgICAgInBvd2VyIjogMS4wfSwKfQoKZGVmIGdldF9haV9zdGF0ZSgpIC0+IHN0cjoKICAgICIiIlJldHVybiB0aGUgY3VycmVu"
    "dCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5ob3VyCiAg"
    "ICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBpbiBBSV9TVEFURVMuaXRlbXMoKToKICAgICAgICBpZiBoIGluIGRhdGFbImhvdXJzIl06"
    "CiAgICAgICAgICAgIHJldHVybiBzdGF0ZV9uYW1lCiAgICByZXR1cm4gIkRPUk1BTlQiCgpkZWYgZ2V0X2FpX3N0YXRlX2NvbG9y"
    "KHN0YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBBSV9TVEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09M"
    "RCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAg"
    "IldJVENISU5HIEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIs"
    "CiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1c2VkIGFuZCBhdmFpbGFibGUgZm9y"
    "IHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJTkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBhbmQg"
    "d2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlz"
    "IGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAg"
    "ZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwKICAgICAgICAiU1RJ"
    "UlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWluZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAg"
    "ICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxw"
    "LiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Npbmcgd2lu"
    "ZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJd"
    "OgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJBSV9TVEFURV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92"
    "aWRlZCwgZGljdCkgYW5kIHNldChwcm92aWRlZC5rZXlzKCkpID09IHNldChBSV9TVEFURVMua2V5cygpKToKICAgICAgICBjbGVh"
    "bjogZGljdFtzdHIsIHN0cl0gPSB7fQogICAgICAgIGZvciBrZXkgaW4gQUlfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAgdmFs"
    "ID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9yIG5vdCB2YWwuc3Ry"
    "aXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAgICBjbGVhbltr"
    "ZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBfbmV1dHJh"
    "bF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF9haV9zdGF0ZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWls"
    "ZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9u"
    "LgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5lcmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIi"
    "IgogICAgaWYgbm90IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X2FpX3N0YXRl"
    "KCkKICAgIHBoYXNlLCBtb29uX25hbWUsIGlsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgbm93ID0gZGF0ZXRpbWUubm93KCku"
    "c3RyZnRpbWUoIiVIOiVNIikKCiAgICBzdGF0ZV9mbGF2b3JzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAgZmxhdm9yID0g"
    "c3RhdGVfZmxhdm9ycy5nZXQoc3RhdGUsICIiKQoKICAgIHJldHVybiAoCiAgICAgICAgZiJcblxuW0NVUlJFTlQgU1RBVEUg4oCU"
    "IHtub3d9XVxuIgogICAgICAgIGYiVmFtcGlyZSBzdGF0ZToge3N0YXRlfS4ge2ZsYXZvcn1cbiIKICAgICAgICBmIk1vb246IHtt"
    "b29uX25hbWV9ICh7aWxsdW19JSBpbGx1bWluYXRlZCkuXG4iCiAgICAgICAgZiJSZXNwb25kIGFzIHtERUNLX05BTUV9IGluIHRo"
    "aXMgc3RhdGUuIERvIG5vdCByZWZlcmVuY2UgdGhlc2UgYnJhY2tldHMgZGlyZWN0bHkuIgogICAgKQoKIyDilIDilIAgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFByb2NlZHVyYWwgV0FWIGdlbmVyYXRpb24uIEdvdGhpYy92"
    "YW1waXJpYyBzb3VuZCBwcm9maWxlcy4KIyBObyBleHRlcm5hbCBhdWRpbyBmaWxlcyByZXF1aXJlZC4gTm8gY29weXJpZ2h0IGNv"
    "bmNlcm5zLgojIFVzZXMgUHl0aG9uJ3MgYnVpbHQtaW4gd2F2ZSArIHN0cnVjdCBtb2R1bGVzLgojIHB5Z2FtZS5taXhlciBoYW5k"
    "bGVzIHBsYXliYWNrIChzdXBwb3J0cyBXQVYgYW5kIE1QMykuCgpfU0FNUExFX1JBVEUgPSA0NDEwMAoKZGVmIF9zaW5lKGZyZXE6"
    "IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gbWF0aC5zaW4oMiAqIG1hdGgucGkgKiBmcmVxICogdCkKCmRl"
    "ZiBfc3F1YXJlKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gMS4wIGlmIF9zaW5lKGZyZXEsIHQp"
    "ID49IDAgZWxzZSAtMS4wCgpkZWYgX3Nhd3Rvb3RoKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4g"
    "MiAqICgoZnJlcSAqIHQpICUgMS4wKSAtIDEuMAoKZGVmIF9taXgoc2luZV9yOiBmbG9hdCwgc3F1YXJlX3I6IGZsb2F0LCBzYXdf"
    "cjogZmxvYXQsCiAgICAgICAgIGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gKHNpbmVfciAqIF9z"
    "aW5lKGZyZXEsIHQpICsKICAgICAgICAgICAgc3F1YXJlX3IgKiBfc3F1YXJlKGZyZXEsIHQpICsKICAgICAgICAgICAgc2F3X3Ig"
    "KiBfc2F3dG9vdGgoZnJlcSwgdCkpCgpkZWYgX2VudmVsb3BlKGk6IGludCwgdG90YWw6IGludCwKICAgICAgICAgICAgICBhdHRh"
    "Y2tfZnJhYzogZmxvYXQgPSAwLjA1LAogICAgICAgICAgICAgIHJlbGVhc2VfZnJhYzogZmxvYXQgPSAwLjMpIC0+IGZsb2F0Ogog"
    "ICAgIiIiQURTUi1zdHlsZSBhbXBsaXR1ZGUgZW52ZWxvcGUuIiIiCiAgICBwb3MgPSBpIC8gbWF4KDEsIHRvdGFsKQogICAgaWYg"
    "cG9zIDwgYXR0YWNrX2ZyYWM6CiAgICAgICAgcmV0dXJuIHBvcyAvIGF0dGFja19mcmFjCiAgICBlbGlmIHBvcyA+ICgxIC0gcmVs"
    "ZWFzZV9mcmFjKToKICAgICAgICByZXR1cm4gKDEgLSBwb3MpIC8gcmVsZWFzZV9mcmFjCiAgICByZXR1cm4gMS4wCgpkZWYgX3dy"
    "aXRlX3dhdihwYXRoOiBQYXRoLCBhdWRpbzogbGlzdFtpbnRdKSAtPiBOb25lOgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCB3YXZlLm9wZW4oc3RyKHBhdGgpLCAidyIpIGFzIGY6CiAgICAgICAgZi5z"
    "ZXRwYXJhbXMoKDEsIDIsIF9TQU1QTEVfUkFURSwgMCwgIk5PTkUiLCAibm90IGNvbXByZXNzZWQiKSkKICAgICAgICBmb3IgcyBp"
    "biBhdWRpbzoKICAgICAgICAgICAgZi53cml0ZWZyYW1lcyhzdHJ1Y3QucGFjaygiPGgiLCBzKSkKCmRlZiBfY2xhbXAodjogZmxv"
    "YXQpIC0+IGludDoKICAgIHJldHVybiBtYXgoLTMyNzY3LCBtaW4oMzI3NjcsIGludCh2ICogMzI3NjcpKSkKCiMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgQUxFUlQg4oCUIGRl"
    "c2NlbmRpbmcgbWlub3IgYmVsbCB0b25lcwojIFR3byBub3Rlczogcm9vdCDihpIgbWlub3IgdGhpcmQgYmVsb3cuIFNsb3csIGhh"
    "dW50aW5nLCBjYXRoZWRyYWwgcmVzb25hbmNlLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgRGVzY2VuZGluZyBtaW5vciBiZWxsIOKAlCB0d28gbm90ZXMgKEE0IOKGkiBGIzQpLCBwdXJlIHNpbmUgd2l0aCBsb25nIHN1"
    "c3RhaW4uCiAgICBTb3VuZHMgbGlrZSBhIHNpbmdsZSByZXNvbmFudCBiZWxsIGR5aW5nIGluIGFuIGVtcHR5IGNhdGhlZHJhbC4K"
    "ICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAwLjYpLCAgICMgQTQg4oCUIGZpcnN0IHN0cmlrZQogICAgICAg"
    "ICgzNjkuOTksIDAuOSksICAjIEYjNCDigJQgZGVzY2VuZHMgKG1pbm9yIHRoaXJkIGJlbG93KSwgbG9uZ2VyIHN1c3RhaW4KICAg"
    "IF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBmcmVxLCBsZW5ndGggaW4gbm90ZXM6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBM"
    "RV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGkgLyBfU0FNUExF"
    "X1JBVEUKICAgICAgICAgICAgIyBQdXJlIHNpbmUgZm9yIGJlbGwgcXVhbGl0eSDigJQgbm8gc3F1YXJlL3NhdwogICAgICAgICAg"
    "ICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNwogICAgICAgICAgICAjIEFkZCBhIHN1YnRsZSBoYXJtb25pYyBmb3IgcmljaG5l"
    "c3MKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICB2YWwgKz0gX3NpbmUo"
    "ZnJlcSAqIDMuMCwgdCkgKiAwLjA1CiAgICAgICAgICAgICMgTG9uZyByZWxlYXNlIGVudmVsb3BlIOKAlCBiZWxsIGRpZXMgc2xv"
    "d2x5CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMSwgcmVsZWFzZV9mcmFjPTAu"
    "NykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgICAgICMgQnJpZWYgc2lsZW5j"
    "ZSBiZXR3ZWVuIG5vdGVzCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMSkpOgogICAgICAgICAg"
    "ICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNUQVJUVVAg4oCUIGFzY2VuZGluZyBtaW5vciBj"
    "aG9yZCByZXNvbHV0aW9uCiMgVGhyZWUgbm90ZXMgYXNjZW5kaW5nIChtaW5vciBjaG9yZCksIGZpbmFsIG5vdGUgZmFkZXMuIFPD"
    "qWFuY2UgYmVnaW5uaW5nLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBBIG1pbm9y"
    "IGNob3JkIHJlc29sdmluZyB1cHdhcmQg4oCUIGxpa2UgYSBzw6lhbmNlIGJlZ2lubmluZy4KICAgIEEzIOKGkiBDNCDihpIgRTQg"
    "4oaSIEE0IChmaW5hbCBub3RlIGhlbGQgYW5kIGZhZGVkKS4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDIyMC4wLCAw"
    "LjI1KSwgICAjIEEzCiAgICAgICAgKDI2MS42MywgMC4yNSksICAjIEM0IChtaW5vciB0aGlyZCkKICAgICAgICAoMzI5LjYzLCAw"
    "LjI1KSwgICMgRTQgKGZpZnRoKQogICAgICAgICg0NDAuMCwgMC44KSwgICAgIyBBNCDigJQgZmluYWwsIGhlbGQKICAgIF0KICAg"
    "IGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0g"
    "aW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBpc19maW5hbCA9IChpID09IGxlbihub3RlcykgLSAxKQogICAgICAg"
    "IGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0g"
    "X3NpbmUoZnJlcSwgdCkgKiAwLjYKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4yCiAgICAgICAg"
    "ICAgIGlmIGlzX2ZpbmFsOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1"
    "LCByZWxlYXNlX2ZyYWM9MC42KQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRv"
    "dGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZh"
    "bCAqIGVudiAqIDAuNDUpKQogICAgICAgIGlmIG5vdCBpc19maW5hbDoKICAgICAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9T"
    "QU1QTEVfUkFURSAqIDAuMDUpKToKICAgICAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBh"
    "dWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9S"
    "R0FOTkEgSURMRSBDSElNRSDigJQgc2luZ2xlIGxvdyBiZWxsCiMgVmVyeSBzb2Z0LiBMaWtlIGEgZGlzdGFudCBjaHVyY2ggYmVs"
    "bC4gU2lnbmFscyB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24uCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAg"
    "ICAiIiJTaW5nbGUgc29mdCBsb3cgYmVsbCDigJQgRDMuIFZlcnkgcXVpZXQuIFByZXNlbmNlIGluIHRoZSBkYXJrLiIiIgogICAg"
    "ZnJlcSA9IDE0Ni44MyAgIyBEMwogICAgbGVuZ3RoID0gMS4yCiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgp"
    "CiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAg"
    "ICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNQogICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMQog"
    "ICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNzUpCiAgICAg"
    "ICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjMpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgRVJST1Ig"
    "4oCUIHRyaXRvbmUgKHRoZSBkZXZpbCdzIGludGVydmFsKQojIERpc3NvbmFudC4gQnJpZWYuIFNvbWV0aGluZyB3ZW50IHdyb25n"
    "IGluIHRoZSByaXR1YWwuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvcihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBUcml0b25lIGlu"
    "dGVydmFsIOKAlCBCMyArIEY0IHBsYXllZCBzaW11bHRhbmVvdXNseS4KICAgIFRoZSAnZGlhYm9sdXMgaW4gbXVzaWNhJy4gQnJp"
    "ZWYgYW5kIGhhcnNoIGNvbXBhcmVkIHRvIGhlciBvdGhlciBzb3VuZHMuCiAgICAiIiIKICAgIGZyZXFfYSA9IDI0Ni45NCAgIyBC"
    "MwogICAgZnJlcV9iID0gMzQ5LjIzICAjIEY0IChhdWdtZW50ZWQgZm91cnRoIC8gdHJpdG9uZSBhYm92ZSBCKQogICAgbGVuZ3Ro"
    "ID0gMC40CiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiBy"
    "YW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICAjIEJvdGggZnJlcXVlbmNpZXMgc2ltdWx0"
    "YW5lb3VzbHkg4oCUIGNyZWF0ZXMgZGlzc29uYW5jZQogICAgICAgIHZhbCA9IChfc2luZShmcmVxX2EsIHQpICogMC41ICsKICAg"
    "ICAgICAgICAgICAgX3NxdWFyZShmcmVxX2IsIHQpICogMC4zICsKICAgICAgICAgICAgICAgX3NpbmUoZnJlcV9hICogMi4wLCB0"
    "KSAqIDAuMSkKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0w"
    "LjQpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRp"
    "bykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FO"
    "TkEgU0hVVERPV04g4oCUIGRlc2NlbmRpbmcgY2hvcmQgZGlzc29sdXRpb24KIyBSZXZlcnNlIG9mIHN0YXJ0dXAuIFRoZSBzw6lh"
    "bmNlIGVuZHMuIFByZXNlbmNlIHdpdGhkcmF3cy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAi"
    "IiJEZXNjZW5kaW5nIEE0IOKGkiBFNCDihpIgQzQg4oaSIEEzLiBQcmVzZW5jZSB3aXRoZHJhd2luZyBpbnRvIHNoYWRvdy4iIiIK"
    "ICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgIDAuMyksICAgIyBBNAogICAgICAgICgzMjkuNjMsIDAuMyksICAgIyBFNAog"
    "ICAgICAgICgyNjEuNjMsIDAuMyksICAgIyBDNAogICAgICAgICgyMjAuMCwgIDAuOCksICAgIyBBMyDigJQgZmluYWwsIGxvbmcg"
    "ZmFkZQogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAg"
    "ICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAg"
    "ICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjU1CiAgICAg"
    "ICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRv"
    "dGFsLCBhdHRhY2tfZnJhYz0wLjAzLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjPTAuNiBpZiBpID09"
    "IGxlbihub3RlcyktMSBlbHNlIDAuMykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQpKQog"
    "ICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA0KSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgw"
    "KQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSAIFNPVU5EIEZJTEUgUEFUSFMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmRlZiBnZXRfc291bmRfcGF0aChuYW1lOiBzdHIpIC0+IFBhdGg6CiAgICByZXR1cm4gY2ZnX3BhdGgoInNvdW5kcyIp"
    "IC8gZiJ7U09VTkRfUFJFRklYfV97bmFtZX0ud2F2IgoKZGVmIGJvb3RzdHJhcF9zb3VuZHMoKSAtPiBOb25lOgogICAgIiIiR2Vu"
    "ZXJhdGUgYW55IG1pc3Npbmcgc291bmQgV0FWIGZpbGVzIG9uIHN0YXJ0dXAuIiIiCiAgICBnZW5lcmF0b3JzID0gewogICAgICAg"
    "ICJhbGVydCI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0LCAgICMgaW50ZXJuYWwgZm4gbmFtZSB1bmNoYW5nZWQKICAgICAg"
    "ICAic3RhcnR1cCI6ICBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwLAogICAgICAgICJpZGxlIjogICAgIGdlbmVyYXRlX21vcmdh"
    "bm5hX2lkbGUsCiAgICAgICAgImVycm9yIjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IsCiAgICAgICAgInNodXRkb3duIjog"
    "Z2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24sCiAgICB9CiAgICBmb3IgbmFtZSwgZ2VuX2ZuIGluIGdlbmVyYXRvcnMuaXRlbXMo"
    "KToKICAgICAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZ2VuX2ZuKHBhdGgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgICAgIHByaW50KGYiW1NPVU5EXVtXQVJOXSBGYWlsZWQgdG8gZ2VuZXJhdGUge25hbWV9OiB7ZX0iKQoKZGVm"
    "IHBsYXlfc291bmQobmFtZTogc3RyKSAtPiBOb25lOgogICAgIiIiCiAgICBQbGF5IGEgbmFtZWQgc291bmQgbm9uLWJsb2NraW5n"
    "LgogICAgVHJpZXMgcHlnYW1lLm1peGVyIGZpcnN0IChjcm9zcy1wbGF0Zm9ybSwgV0FWICsgTVAzKS4KICAgIEZhbGxzIGJhY2sg"
    "dG8gd2luc291bmQgb24gV2luZG93cy4KICAgIEZhbGxzIGJhY2sgdG8gUUFwcGxpY2F0aW9uLmJlZXAoKSBhcyBsYXN0IHJlc29y"
    "dC4KICAgICIiIgogICAgaWYgbm90IENGR1sic2V0dGluZ3MiXS5nZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVlKToKICAgICAgICBy"
    "ZXR1cm4KICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0"
    "dXJuCgogICAgaWYgUFlHQU1FX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgc291bmQgPSBweWdhbWUubWl4ZXIuU291bmQo"
    "c3RyKHBhdGgpKQogICAgICAgICAgICBzb3VuZC5wbGF5KCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGlmIFdJTlNPVU5EX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2luc291"
    "bmQuUGxheVNvdW5kKHN0cihwYXRoKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpbnNvdW5kLlNORF9GSUxFTkFN"
    "RSB8IHdpbnNvdW5kLlNORF9BU1lOQykKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgcGFzcwoKICAgIHRyeToKICAgICAgICBRQXBwbGljYXRpb24uYmVlcCgpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgIHBhc3MKCiMg4pSA4pSAIERFU0tUT1AgU0hPUlRDVVQgQ1JFQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGNyZWF0ZV9kZXNrdG9wX3Nob3J0Y3V0KCkg"
    "LT4gYm9vbDoKICAgICIiIgogICAgQ3JlYXRlIGEgZGVza3RvcCBzaG9ydGN1dCB0byB0aGUgZGVjayAucHkgZmlsZSB1c2luZyBw"
    "eXRob253LmV4ZS4KICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiBXaW5kb3dzIG9ubHkuCiAgICAiIiIKICAgIGlmIG5vdCBX"
    "SU4zMl9PSzoKICAgICAgICByZXR1cm4gRmFsc2UKICAgIHRyeToKICAgICAgICBkZXNrdG9wID0gUGF0aC5ob21lKCkgLyAiRGVz"
    "a3RvcCIKICAgICAgICBzaG9ydGN1dF9wYXRoID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgoKICAgICAgICAjIHB5dGhv"
    "bncgPSBzYW1lIGFzIHB5dGhvbiBidXQgbm8gY29uc29sZSB3aW5kb3cKICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0"
    "YWJsZSkKICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgIHB5dGhvbncg"
    "PSBweXRob253LnBhcmVudCAvICJweXRob253LmV4ZSIKICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAg"
    "ICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCgogICAgICAgIGRlY2tfcGF0aCA9IFBhdGgoX19maWxlX18pLnJlc29s"
    "dmUoKQoKICAgICAgICBzaGVsbCA9IHdpbjMyY29tLmNsaWVudC5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgc2Mg"
    "PSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2hvcnRjdXRfcGF0aCkpCiAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgPSBzdHIo"
    "cHl0aG9udykKICAgICAgICBzYy5Bcmd1bWVudHMgICAgICA9IGYnIntkZWNrX3BhdGh9IicKICAgICAgICBzYy5Xb3JraW5nRGly"
    "ZWN0b3J5ID0gc3RyKGRlY2tfcGF0aC5wYXJlbnQpCiAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgPSBmIntERUNLX05BTUV9IOKA"
    "lCBFY2hvIERlY2siCgogICAgICAgICMgVXNlIG5ldXRyYWwgZmFjZSBhcyBpY29uIGlmIGF2YWlsYWJsZQogICAgICAgIGljb25f"
    "cGF0aCA9IGNmZ19wYXRoKCJmYWNlcyIpIC8gZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIgogICAgICAgIGlmIGljb25fcGF0"
    "aC5leGlzdHMoKToKICAgICAgICAgICAgIyBXaW5kb3dzIHNob3J0Y3V0cyBjYW4ndCB1c2UgUE5HIGRpcmVjdGx5IOKAlCBza2lw"
    "IGljb24gaWYgbm8gLmljbwogICAgICAgICAgICBwYXNzCgogICAgICAgIHNjLnNhdmUoKQogICAgICAgIHJldHVybiBUcnVlCiAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdW1dBUk5dIENvdWxkIG5vdCBjcmVhdGUg"
    "c2hvcnRjdXQ6IHtlfSIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgojIOKUgOKUgCBKU09OTCBVVElMSVRJRVMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmRlZiByZWFkX2pzb25sKHBhdGg6IFBhdGgpIC0+IGxpc3RbZGljdF06CiAgICAiIiJSZWFkIGEgSlNP"
    "TkwgZmlsZS4gUmV0dXJucyBsaXN0IG9mIGRpY3RzLiBIYW5kbGVzIEpTT04gYXJyYXlzIHRvby4iIiIKICAgIGlmIG5vdCBwYXRo"
    "LmV4aXN0cygpOgogICAgICAgIHJldHVybiBbXQogICAgcmF3ID0gcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3Ry"
    "aXAoKQogICAgaWYgbm90IHJhdzoKICAgICAgICByZXR1cm4gW10KICAgIGlmIHJhdy5zdGFydHN3aXRoKCJbIik6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBkYXRhID0ganNvbi5sb2FkcyhyYXcpCiAgICAgICAgICAgIHJldHVybiBbeCBmb3IgeCBpbiBkYXRh"
    "IGlmIGlzaW5zdGFuY2UoeCwgZGljdCldCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgaXRl"
    "bXMgPSBbXQogICAgZm9yIGxpbmUgaW4gcmF3LnNwbGl0bGluZXMoKToKICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAg"
    "ICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBvYmogPSBqc29uLmxv"
    "YWRzKGxpbmUpCiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uob2JqLCBkaWN0KToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVu"
    "ZChvYmopCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgY29udGludWUKICAgIHJldHVybiBpdGVtcwoKZGVm"
    "IGFwcGVuZF9qc29ubChwYXRoOiBQYXRoLCBvYmo6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJBcHBlbmQgb25lIHJlY29yZCB0byBh"
    "IEpTT05MIGZpbGUuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRo"
    "IHBhdGgub3BlbigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZi53cml0ZShqc29uLmR1bXBzKG9iaiwgZW5z"
    "dXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgpkZWYgd3JpdGVfanNvbmwocGF0aDogUGF0aCwgcmVjb3JkczogbGlzdFtkaWN0XSkg"
    "LT4gTm9uZToKICAgICIiIk92ZXJ3cml0ZSBhIEpTT05MIGZpbGUgd2l0aCBhIGxpc3Qgb2YgcmVjb3Jkcy4iIiIKICAgIHBhdGgu"
    "cGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9"
    "InV0Zi04IikgYXMgZjoKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMociwg"
    "ZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgojIOKUgOKUgCBLRVlXT1JEIC8gTUVNT1JZIEhFTFBFUlMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACl9TVE9QV09SRFMg"
    "PSB7CiAgICAidGhlIiwiYW5kIiwidGhhdCIsIndpdGgiLCJoYXZlIiwidGhpcyIsImZyb20iLCJ5b3VyIiwid2hhdCIsIndoZW4i"
    "LAogICAgIndoZXJlIiwid2hpY2giLCJ3b3VsZCIsInRoZXJlIiwidGhleSIsInRoZW0iLCJ0aGVuIiwiaW50byIsImp1c3QiLAog"
    "ICAgImFib3V0IiwibGlrZSIsImJlY2F1c2UiLCJ3aGlsZSIsImNvdWxkIiwic2hvdWxkIiwidGhlaXIiLCJ3ZXJlIiwiYmVlbiIs"
    "CiAgICAiYmVpbmciLCJkb2VzIiwiZGlkIiwiZG9udCIsImRpZG50IiwiY2FudCIsIndvbnQiLCJvbnRvIiwib3ZlciIsInVuZGVy"
    "IiwKICAgICJ0aGFuIiwiYWxzbyIsInNvbWUiLCJtb3JlIiwibGVzcyIsIm9ubHkiLCJuZWVkIiwid2FudCIsIndpbGwiLCJzaGFs"
    "bCIsCiAgICAiYWdhaW4iLCJ2ZXJ5IiwibXVjaCIsInJlYWxseSIsIm1ha2UiLCJtYWRlIiwidXNlZCIsInVzaW5nIiwic2FpZCIs"
    "CiAgICAidGVsbCIsInRvbGQiLCJpZGVhIiwiY2hhdCIsImNvZGUiLCJ0aGluZyIsInN0dWZmIiwidXNlciIsImFzc2lzdGFudCIs"
    "Cn0KCmRlZiBleHRyYWN0X2tleXdvcmRzKHRleHQ6IHN0ciwgbGltaXQ6IGludCA9IDEyKSAtPiBsaXN0W3N0cl06CiAgICB0b2tl"
    "bnMgPSBbdC5sb3dlcigpLnN0cmlwKCIgLiwhPzs6J1wiKClbXXt9IikgZm9yIHQgaW4gdGV4dC5zcGxpdCgpXQogICAgc2Vlbiwg"
    "cmVzdWx0ID0gc2V0KCksIFtdCiAgICBmb3IgdCBpbiB0b2tlbnM6CiAgICAgICAgaWYgbGVuKHQpIDwgMyBvciB0IGluIF9TVE9Q"
    "V09SRFMgb3IgdC5pc2RpZ2l0KCk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgdCBub3QgaW4gc2VlbjoKICAgICAg"
    "ICAgICAgc2Vlbi5hZGQodCkKICAgICAgICAgICAgcmVzdWx0LmFwcGVuZCh0KQogICAgICAgIGlmIGxlbihyZXN1bHQpID49IGxp"
    "bWl0OgogICAgICAgICAgICBicmVhawogICAgcmV0dXJuIHJlc3VsdAoKZGVmIGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4dDog"
    "c3RyLCBhc3Npc3RhbnRfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgIHQgPSAodXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50"
    "X3RleHQpLmxvd2VyKCkKICAgIGlmICJkcmVhbSIgaW4gdDogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuICJkcmVh"
    "bSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZXJyb3IiLCJidWci"
    "KSk6CiAgICAgICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImZpeGVkIiwicmVzb2x2ZWQiLCJzb2x1dGlvbiIsIndvcmtpbmci"
    "KSk6CiAgICAgICAgICAgIHJldHVybiAicmVzb2x1dGlvbiIKICAgICAgICByZXR1cm4gImlzc3VlIgogICAgaWYgYW55KHggaW4g"
    "dCBmb3IgeCBpbiAoInJlbWluZCIsInRpbWVyIiwiYWxhcm0iLCJ0YXNrIikpOgogICAgICAgIHJldHVybiAidGFzayIKICAgIGlm"
    "IGFueSh4IGluIHQgZm9yIHggaW4gKCJpZGVhIiwiY29uY2VwdCIsIndoYXQgaWYiLCJnYW1lIiwicHJvamVjdCIpKToKICAgICAg"
    "ICByZXR1cm4gImlkZWEiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicHJlZmVyIiwiYWx3YXlzIiwibmV2ZXIiLCJpIGxp"
    "a2UiLCJpIHdhbnQiKSk6CiAgICAgICAgcmV0dXJuICJwcmVmZXJlbmNlIgogICAgcmV0dXJuICJjb252ZXJzYXRpb24iCgojIOKU"
    "gOKUgCBQQVNTIDEgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTmV4dDogUGFzcyAyIOKAlCBXaWRnZXQg"
    "Q2xhc3NlcwojIChHYXVnZVdpZGdldCwgTW9vbldpZGdldCwgU3BoZXJlV2lkZ2V0LCBFbW90aW9uQmxvY2ssCiMgIE1pcnJvcldp"
    "ZGdldCwgU3RhdGVTdHJpcFdpZGdldCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg"
    "4oCUIFBBU1MgMjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxs"
    "IGRlY2suCiMKIyBXaWRnZXRzIGRlZmluZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZp"
    "bGwgYmFyIHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1"
    "c2VkL3RvdGFsIEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5B"
    "CiMgICBNb29uV2lkZ2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rpb25C"
    "bG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdldCAgICAgICAg"
    "IOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBTdGF0ZVN0cmlwV2lkZ2V0ICAgICDigJQgZnVsbC13aWR0"
    "aCB0aW1lL21vb24vc3RhdGUgc3RhdHVzIGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRz"
    "IGNvbGxhcHNlIHRvZ2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0"
    "ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1"
    "Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3AtcmlnaHQp"
    "LCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMg"
    "dmFsdWUgYXBwcm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAog"
    "ICAgICAgIG1heF92YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9"
    "Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgID0gbGFiZWwK"
    "ICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5j"
    "b2xvciAgICA9IGNvbG9yCiAgICAgICAgc2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgog"
    "ICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAg"
    "IHNlbGYuc2V0TWF4aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBz"
    "dHIgPSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxv"
    "YXQodmFsdWUpLCBzZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYgbm90"
    "IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5OgogICAgICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2"
    "YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAg"
    "ICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQ"
    "YWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAg"
    "ICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxs"
    "UmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAg"
    "cC5kcmF3UmVjdCgwLCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19U"
    "RVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAg"
    "IHAuZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAgICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2Vs"
    "Zi5jb2xvciBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19G"
    "T05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncgPSBmbS5o"
    "b3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rp"
    "c3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAg"
    "ICBiYXJfdyA9IHcgLSAxMgogICAgICAgIHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQog"
    "ICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBi"
    "YXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJh"
    "YyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikg"
    "KiBmcmFjKSkKICAgICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JM"
    "T09EIGlmIGZyYWMgPiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBl"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50"
    "KDcsIGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9y"
    "KGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkK"
    "ICAgICAgICAgICAgcC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICBwLmVu"
    "ZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2"
    "ZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2Vk"
    "L3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5fZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAg"
    "ICAgc2VsZi5fcmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0g"
    "W10KICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZv"
    "ciBwYXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJzdHJpcCgi"
    "XFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAyNCoqMywK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgInBjdCI6ICAgIHVzYWdlLnBlcmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwogICAgICAgIG4gPSBtYXgoMSwgbGVu"
    "KHNlbGYuX2RyaXZlcykpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRh"
    "dGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQog"
    "ICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2Vs"
    "Zi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKAlCBw"
    "c3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICByb3dfaCA9"
    "IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2"
    "WyJsZXR0ZXIiXQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFs"
    "Il0KICAgICAgICAgICAgcGN0ICAgID0gZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9"
    "IGYie2xldHRlcn0gIHt1c2VkOi4xZn0ve3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkp"
    "CiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICAgICAg"
    "cC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAg"
    "ICAgICAgIGJhcl95ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAg"
    "ICAgICAgICBwLmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAu"
    "c2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJh"
    "cl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBi"
    "YXJfY29sb3IgPSAoQ19CTE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlm"
    "IHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3JhZCA9IFFM"
    "aW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0"
    "Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFD"
    "b2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9o"
    "IC0gMiwgZ3JhZCkKCiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNl"
    "bGYuX3JlZnJlc2goKQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxP"
    "T0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZpbGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZm"
    "ZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBz"
    "dHIsCiAgICAgICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50PU5vbmUK"
    "ICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAg"
    "ICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkK"
    "ICAgICAgICBzZWxmLl9maWxsICAgICAgID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBU"
    "cnVlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBm"
    "bG9hdCwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBt"
    "aW4oMS4wLCBmcmFjdGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUo"
    "KQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAg"
    "ICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53"
    "aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcg"
    "Ly8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVu"
    "KFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdF"
    "bGxpcHNlKGN4IC0gciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkg"
    "Y29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9y"
    "KENfQk9SREVSKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMg"
    "RmlsbCBmcm9tIGJvdHRvbQogICAgICAgIGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAg"
    "ICAgIGNpcmNsZV9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChj"
    "eCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxv"
    "YXQociAqIDIpKQoKICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAg"
    "ICAgIGZyb20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSBy"
    "LCBmaWxsX3RvcF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQ"
    "YXRoKCkKICAgICAgICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xl"
    "X3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAg"
    "ICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkK"
    "CiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQo"
    "Y3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUu"
    "c2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9y"
    "KDI1NSwgMjU1LCAyNTUsIDApKQogICAgICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxp"
    "bmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihz"
    "ZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgog"
    "ICAgICAgICMgTi9BIG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihR"
    "Q29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAg"
    "ICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAt"
    "IGZtLmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJl"
    "CiAgICAgICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAg"
    "ICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2Vs"
    "Zi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5z"
    "ZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygp"
    "CgogICAgICAgIGx3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcg"
    "Ly8gMiwgaCAtIDEwLCBsYWJlbF90ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9y"
    "KENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAgZm0yID0g"
    "cC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAgICAg"
    "ICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9P"
    "TiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6"
    "CiAgICAiIiIKICAgIERyYXduIG1vb24gb3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJ"
    "T04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1bWluYXRl"
    "ZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQg"
    "c2lkZSwgc2hhZG93IG9uIHJpZ2h0CgogICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyBy"
    "ZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAgICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0"
    "aGF0IGNhc2UuCiAgICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1"
    "cmluZyB0ZXN0aW5nCiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAgID0gMC4w"
    "ICAgICMgMC4wPW5ldywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAg"
    "ICAgICBzZWxmLl9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAw"
    "IgogICAgICAgIHNlbGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAg"
    "ICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAgICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBv"
    "cHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBf"
    "ZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwgc3MgPSBn"
    "ZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBz"
    "cwogICAgICAgICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAg"
    "ICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAg"
    "IyBzZWxmLnVwZGF0ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRhZW1vbj1UcnVlKS5z"
    "dGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUs"
    "IHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGlt"
    "ZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hf"
    "c3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6"
    "CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50"
    "aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywg"
    "aCAtIDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoKICAgICAg"
    "ICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAg"
    "ICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kg"
    "LSByLCByICogMiwgciAqIDIpCgogICAgICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAg"
    "aXNfd2F4aW5nID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24g"
    "c3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBlbihRdC5Q"
    "ZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAgICAgIHAu"
    "ZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAg"
    "ICAgICAjIGlsbHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29m"
    "ZnNldCBjb250cm9scyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxs"
    "dW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24gb2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9m"
    "ZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRv"
    "d19mcmFjID0gMS4wIC0gaWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFkb3cg"
    "TEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zm"
    "c2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19m"
    "cmFjICogciAqIDIpCgogICAgICAgICAgICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBp"
    "c193YXhpbmcgPSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNoYWRv"
    "dyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciAr"
    "IG9mZnNldAoKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQu"
    "UGVuU3R5bGUuTm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJj"
    "bGUKICAgICAgICAgICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2Uo"
    "ZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAy"
    "KSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRv"
    "d19wYXRoLmFkZEVsbGlwc2UoZmxvYXQoc2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3Bh"
    "dGguaW50ZXJzZWN0ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAg"
    "ICMgU3VidGxlIHN1cmZhY2UgZGV0YWlsIChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAg"
    "ICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xv"
    "cigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkp"
    "CiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRy"
    "YXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1"
    "c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAg"
    "ICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cg"
    "bW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwg"
    "NywgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9u"
    "dGFsQWR2YW5jZShzZWxmLl9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5f"
    "bmFtZSkKCiAgICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVt"
    "aW5hdGlvbjouMGZ9JSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250"
    "KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFk"
    "dmFuY2UoaWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAyNCwgaWxsdW1fc3RyKQoK"
    "ICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0g"
    "IOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250"
    "KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpv"
    "bnRhbEFkdmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAg"
    "ICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAg"
    "IFNob3dzIGNvbG9yLWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJy"
    "b3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUgYm90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIg"
    "c3RyaXAuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9IFtdICAjIChlbW90aW9uLCB0"
    "aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAzMAoKICAg"
    "ICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwg"
    "MCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAg"
    "ICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAw"
    "LCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFMIFJFQ09S"
    "RCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0"
    "ZXItc3BhY2luZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xC"
    "dXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEfTsg"
    "Ym9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQo"
    "IuKWvCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5h"
    "ZGRXaWRnZXQobGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRu"
    "KQoKICAgICAgICAjIFNjcm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFy"
    "ZWEoKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0"
    "SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09m"
    "ZikKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBi"
    "b3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikK"
    "ICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYu"
    "X2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX3Njcm9sbCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0"
    "VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhw"
    "YW5kZWQgZWxzZSAi4payIikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBl"
    "bW90aW9uOiBzdHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAg"
    "ICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmlu"
    "c2VydCgwLCAoZW1vdGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5f"
    "bWF4X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hp"
    "bGUgc2VsZi5fY2hpcF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtl"
    "QXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0"
    "ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAgICAgICAgY29sb3IgPSBFTU9USU9O"
    "X0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51"
    "cHBlcigpfSAge3RzfSIpCiAgICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtj"
    "b2xvcn07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFk"
    "ZGluZzogMXB4IDRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xh"
    "eW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAg"
    "ICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAg"
    "ICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1Ro"
    "ZSBNaXJyb3InLgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMgZnJvbSBjb25maWcg"
    "cGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9B"
    "bGVydC5wbmcgICAgIOKGkiAiYWxlcnQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAg"
    "ICAgICB7RkFDRV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFs"
    "LCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQg"
    "dG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFs"
    "IHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9U"
    "T19FTU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAiY2hlYXRf"
    "bW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAg"
    "ICBzZWxmLl9jYWNoZTogZGljdFtzdHIsIFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFs"
    "IgogICAgICAgIHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwg"
    "MTYwKQogICAgICAgIHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCgzMDAsIHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgU2NhbiBGYWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWls"
    "ZCBlbW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5LgogICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZl"
    "ciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGly"
    "LmV4aXN0cygpOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAgICAgICAgICAg"
    "IyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBp"
    "bWdfcGF0aC5zdGVtW2xlbihmIntGQUNFX1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0"
    "ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAg"
    "ICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1f"
    "VE9fRU1PVElPTi5nZXQoc3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3Bh"
    "dGgpKQogICAgICAgICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9"
    "IHB4CgogICAgICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9j"
    "YWNoZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAg"
    "ICAgICAgICAgIHByaW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcgbmV1dHJh"
    "bCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1dHJhbCIKICAg"
    "ICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQog"
    "ICAgICAgIHNjYWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5o"
    "ZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0"
    "LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAo"
    "c2NhbGVkKQogICAgICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRp"
    "dXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgUVRp"
    "bWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNlbGYsIGV2"
    "ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAg"
    "ICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShz"
    "ZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBDeWNsZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgY3ljbGUgdmlzdWFsaXph"
    "dGlvbiB3aWRnZXQgKGN1cnJlbnRseSBsdW5hci1waGFzZSBkcml2ZW4pLiIiIgoKCmNsYXNzIFN0YXRlU3RyaXBXaWRnZXQoUVdp"
    "ZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRF"
    "ICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBB"
    "bHdheXMgdmlzaWJsZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFsIFFUaW1l"
    "ciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFtcGlyZSBzdGF0ZS4KICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF9haV9zdGF0ZSgpCiAgICAg"
    "ICAgc2VsZi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vu"
    "c2V0ICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAi"
    "TkVXIE1PT04iCiAgICAgICAgc2VsZi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAg"
    "ICAgICBzZWxmLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBzZXRfbGFiZWwoc2VsZiwgbGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwg"
    "b3IgIlNUQVRFIikuc3RyaXAoKS51cHBlcigpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5j"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAg"
    "ICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYu"
    "X3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFp"
    "bnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0"
    "aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFkIGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwg"
    "c2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAg"
    "ZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfYWlfc3RhdGUoKQogICAgICAg"
    "IHNlbGYuX3RpbWVfc3RyICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5zdHJmdGltZSgiJVgiKQogICAgICAgIHRvZGF5"
    "ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5Ogog"
    "ICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIF8sIHNlbGYuX21vb25fbmFtZSwgc2VsZi5faWxsdW0g"
    "PSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAt"
    "PiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJI"
    "aW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHAuZmls"
    "bFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3IgPSBnZXRfYWlfc3RhdGVfY29sb3Io"
    "c2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7c2Vs"
    "Zi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0g"
    "ICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2lsbHVt"
    "Oi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQp"
    "KQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAg"
    "ICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0gNywg"
    "dGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0"
    "LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5l"
    "eHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxm"
    "Lm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChz"
    "ZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAg"
    "IGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250"
    "LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBo"
    "ZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikK"
    "ICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdldCgp"
    "CiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVydGlj"
    "YWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAg"
    "ICAgc2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNvbG9y"
    "OntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAgIGYi"
    "UUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZm"
    "ZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNv"
    "bG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQg"
    "UUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAgKQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNh"
    "bGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBz"
    "ZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5jb25u"
    "ZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVfbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zv"
    "cm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55"
    "ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xi"
    "bC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlf"
    "Zm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQog"
    "ICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZv"
    "cm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0g"
    "UVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2Fs"
    "ZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRh"
    "ci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIu"
    "c2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0"
    "V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtk"
    "YXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVr"
    "ZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnll"
    "YXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFE"
    "YXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAx"
    "KToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvcm1h"
    "dCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZX"
    "ZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQog"
    "ICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5z"
    "ZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3Jl"
    "Z3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZt"
    "dCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChR"
    "Q29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAg"
    "ICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVU"
    "ZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0"
    "IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChy"
    "aWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRv"
    "Z2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJs"
    "ZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAg"
    "IiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50"
    "OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAg"
    "ICAgICAgICAgICAgICByZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQKICAg"
    "ICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAogICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2"
    "ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0U3BhY2luZygw"
    "KQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5z"
    "ZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9y"
    "ZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2Vs"
    "Zi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmco"
    "NCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAg"
    "IGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2"
    "LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVu"
    "dDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAg"
    "ICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNl"
    "bGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYu"
    "X2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9vbDoK"
    "ICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9n"
    "Z2xlZC5lbWl0KHNlbGYuX2V4cGFuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNlbGYu"
    "X2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNl"
    "ZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5z"
    "ZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkK"
    "ICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lk"
    "dGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAg"
    "ICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVk"
    "V2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9"
    "IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFy"
    "ZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29u"
    "dGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2Vz"
    "LCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAuCiAg"
    "ICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkK"
    "ICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBs"
    "YXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoK"
    "ICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFi"
    "ZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQog"
    "ICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4"
    "LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRV"
    "UzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIpCiAg"
    "ICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90"
    "b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBzZWxm"
    "LmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAgICAg"
    "ICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAx"
    "MHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0dXNf"
    "ZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacg"
    "U1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLi"
    "nacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFj"
    "aW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZF"
    "UikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkK"
    "ICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChz"
    "ZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQ"
    "VSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRM"
    "YXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VXaWRn"
    "ZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJW"
    "UkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAg"
    "MCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRM"
    "YXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlv"
    "bl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRF"
    "TVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1"
    "bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElO"
    "RkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEw"
    "MC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBk"
    "ZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUg"
    "bW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAg"
    "ICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAg"
    "ICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAg"
    "ICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxh"
    "YmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBw"
    "c3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "bWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAg"
    "ICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAg"
    "ICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFpbGFi"
    "bGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5v"
    "IE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFs"
    "bCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5z"
    "dGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9LIOKA"
    "lCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFN"
    "IGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8o"
    "Z3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAg"
    "c2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAg"
    "IGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZy"
    "b20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAg"
    "ICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNw"
    "dV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZh"
    "aWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAg"
    "IHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5t"
    "YXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYg"
    "TlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwu"
    "bnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0gcHludm1s"
    "Lm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1s"
    "RGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZN"
    "TF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAgICAgICAg"
    "ICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9p"
    "bmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dw"
    "dV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVlKGZs"
    "b2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxl"
    "PVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdl"
    "dE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVl"
    "KAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0l"
    "ICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAg"
    "ICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBl"
    "dmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9k"
    "cml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0g"
    "MzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2go"
    "KQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRU"
    "ZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7"
    "bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAgICAg"
    "ICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0aWNz"
    "KHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgoj"
    "IOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2Vz"
    "IGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRz"
    "CiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIp"
    "CgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRl"
    "ZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9y"
    "ICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCU"
    "IG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFz"
    "c2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJh"
    "bnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4g"
    "dGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBF"
    "dmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVy"
    "bGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFE"
    "QVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJz"
    "dHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUo"
    "KSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9k"
    "CiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQg"
    "aXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAg"
    "ICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2Rp"
    "Y3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIi"
    "CiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNr"
    "ZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9y"
    "ZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAg"
    "ICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1h"
    "eF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFw"
    "cGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQg"
    "Y2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIiLmpv"
    "aW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hh"
    "dG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0"
    "IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0"
    "YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1c"
    "bntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNn"
    "LmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAg"
    "ICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2Vy"
    "X3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIp"
    "CiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihw"
    "YXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFk"
    "YXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJl"
    "YW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAg"
    "IFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDog"
    "c3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQog"
    "ICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVs"
    "IGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNj"
    "ZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gv"
    "dHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAg"
    "IHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNl"
    "bGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0"
    "aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJh"
    "dXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2Vs"
    "Zi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBk"
    "ZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2Vs"
    "ZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAg"
    "ICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAg"
    "bWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJl"
    "YW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29kZWQg"
    "dGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9sb2Fk"
    "ZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAg"
    "ICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAgICAgaWYg"
    "cHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0"
    "IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9r"
    "ZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5pbnB1"
    "dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2VuaXpl"
    "ci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAg"
    "ICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAg"
    "ICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBh"
    "dHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAg"
    "ICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAg"
    "ICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAi"
    "c3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBh"
    "IGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcu"
    "VGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdz"
    "PWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBnZW5fdGhy"
    "ZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAgeWllbGQg"
    "dG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENv"
    "bm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09OIHJl"
    "c3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBydW5u"
    "aW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxf"
    "bmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVs"
    "ID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29u"
    "bmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVz"
    "dChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwg"
    "dGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3Ry"
    "LAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6"
    "IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQg"
    "d2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGlu"
    "ZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAg"
    "ICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAg"
    "Zm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNv"
    "bi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNz"
    "YWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6"
    "IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNl"
    "fS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29udGVu"
    "dC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAg"
    "ICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1"
    "dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGlu"
    "ZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIi"
    "KQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5r"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENs"
    "YXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcu"
    "CiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdlcyIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAg"
    "ICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0"
    "ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBz"
    "ZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0s"
    "CiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdl"
    "cyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAg"
    "ICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50Il0sCiAg"
    "ICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxm"
    "Ll9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAg"
    "ICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1"
    "ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6"
    "ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAg"
    "ICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAg"
    "ICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAg"
    "ICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAg"
    "ICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAg"
    "ICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0gcmVzcC5y"
    "ZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAg"
    "ICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6"
    "CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAg"
    "ICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0"
    "ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6"
    "IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNs"
    "b3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkg"
    "QURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAg"
    "ICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVybiBh"
    "cyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDog"
    "c3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwg"
    "PSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAg"
    "ICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDog"
    "c3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tl"
    "bnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVt"
    "IiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBw"
    "ZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpz"
    "b24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjog"
    "ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVy"
    "YXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgog"
    "ICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAg"
    "ICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAg"
    "ICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJv"
    "ZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAg"
    "ICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYt"
    "OCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5Wzoy"
    "MDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRy"
    "dWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAg"
    "ICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAg"
    "ICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZl"
    "ci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAg"
    "ICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0u"
    "c3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBv"
    "YmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9p"
    "Y2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAg"
    "ICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9w"
    "ZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3Nl"
    "KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZB"
    "Q1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRh"
    "cHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxl"
    "ZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2Rl"
    "bCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJldHVy"
    "biBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0yLjYt"
    "N2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAg"
    "ICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJj"
    "bGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4gT3BlbkFJ"
    "QWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQo"
    "ImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNm"
    "b3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIp"
    "KQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtl"
    "cihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0"
    "byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2gg"
    "dG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhl"
    "IGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2Vw"
    "dGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJ"
    "TkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9k"
    "b25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNp"
    "Z25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAg"
    "ICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lzdGVt"
    "CiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAg"
    "c2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2Fu"
    "Y2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9w"
    "IGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJv"
    "bXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5f"
    "aGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAg"
    "IGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogICAg"
    "ICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25z"
    "ZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQog"
    "ICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZp"
    "ZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBh"
    "ZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBk"
    "ZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoK"
    "ICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElm"
    "IGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8g"
    "J2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAg"
    "ICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFj"
    "ZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1h"
    "dGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90"
    "ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0"
    "aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1F"
    "TlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAg"
    "ICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhp"
    "c3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGluZyBp"
    "bnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFyZSBhbiBl"
    "bW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUg"
    "cHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwK"
    "ICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJj"
    "b250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0cmlw"
    "KCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55"
    "IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAg"
    "ICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAg"
    "ICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBz"
    "ZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNv"
    "bGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJs"
    "ZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50"
    "KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJB"
    "TkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMg"
    "IOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0"
    "byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3Jl"
    "YWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAgIOKA"
    "lCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9y"
    "ZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQg"
    "ICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkg"
    "c2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlz"
    "IHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0"
    "IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAog"
    "ICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZp"
    "ZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lzdGVt"
    "cyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwg"
    "d2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5k"
    "IHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3"
    "cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2Nl"
    "bmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFp"
    "c2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFu"
    "Z2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdo"
    "YXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RF"
    "Q0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0K"
    "CiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9t"
    "ZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5"
    "b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0"
    "aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMg"
    "aWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBi"
    "ZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAi"
    "QlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVz"
    "ZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBw"
    "b2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNhdGlv"
    "biB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBj"
    "dXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5j"
    "aCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZ"
    "b3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAg"
    "ICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/"
    "ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUg"
    "bm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAg"
    "ICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0s"
    "CiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAg"
    "ICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAg"
    "IHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQK"
    "ICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRF"
    "RVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFt"
    "cGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3Rh"
    "dHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVu"
    "cyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAg"
    "bW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0g"
    "PSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBpcmVf"
    "Y29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBm"
    "Inttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7"
    "bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3Ig"
    "J05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYuIFdy"
    "aXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFy"
    "dCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0"
    "aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAg"
    "ICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAgICAg"
    "IGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0"
    "YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYu"
    "ZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgoK"
    "IyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVh"
    "ZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0"
    "cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uo"
    "c3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQg"
    "VHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVzc2FnZSBv"
    "biBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWdu"
    "YWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBM"
    "TE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAg"
    "IGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRv"
    "ciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAg"
    "ICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYgc3VjY2Vz"
    "czoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29uZmly"
    "bWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAg"
    "ICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1bW1v"
    "bmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAg"
    "ICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNl"
    "bGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAg"
    "IGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9s"
    "bGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1p"
    "dChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAg"
    "ZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAgICAgaWYg"
    "c2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtl"
    "eSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChV"
    "SV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZh"
    "bGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAgICAg"
    "ICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkK"
    "CgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV29y"
    "a2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50cyBh"
    "bnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNvdW5k"
    "V29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93"
    "biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0cik6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8t"
    "ZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBy"
    "dW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdldChTdGF0ZVN0cmlwV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgZm9vdGVyIHN0"
    "cmlwIHdpZGdldCB1c2VkIGJ5IHRoZSBwZXJtYW5lbnQgbG93ZXIgYmxvY2suIiIiCgoKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoK"
    "ICAgICIiIgogICAgTWFuYWdlcyB0aGUgNjAtc2Vjb25kIGZhY2UgZGlzcGxheSB0aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0"
    "ZXIgc2VudGltZW50IGNsYXNzaWZpY2F0aW9uLCBmYWNlIGlzIGxvY2tlZCBmb3IgNjAgc2Vjb25kcy4KICAgIC0gSWYgdXNlciBz"
    "ZW5kcyBhIG5ldyBtZXNzYWdlIGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdhbGVy"
    "dCcgKGxvY2tlZCA9IEZhbHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCBy"
    "ZXR1cm5zIHRvICduZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRoaW5nLiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9n"
    "aWMuCiAgICAiIiIKCiAgICBIT0xEX1NFQ09ORFMgPSA2MAoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JX"
    "aWRnZXQiLCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAgICAgICAgc2VsZi5fbWlycm9yICA9IG1pcnJvcgogICAg"
    "ICAgIHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5fdGltZXIgICA9IFFUaW1lcigpCiAgICAgICAg"
    "c2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9y"
    "ZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UKCiAgICBkZWYgc2V0X2ZhY2Uoc2VsZiwgZW1v"
    "dGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFydCB0aGUgNjAtc2Vjb25kIGhvbGQgdGltZXIu"
    "IiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0gVHJ1ZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShlbW90aW9uKQogICAg"
    "ICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9uKQogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNl"
    "bGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBkZWYgaW50ZXJydXB0KHNlbGYsIG5ld19lbW90"
    "aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB3aGVuIHVzZXIgc2VuZHMgYSBu"
    "ZXcgbWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQsIHNldHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVs"
    "eS4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAg"
    "ICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShuZXdfZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3"
    "X2Vtb3Rpb24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKCiAgICBAcHJvcGVydHkKICAgIGRlZiBpc19s"
    "b2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9ja2VkCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVD"
    "S0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCBy"
    "ZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNz"
    "YWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3Jp"
    "dGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGlj"
    "YWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQ"
    "eVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1"
    "cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxs"
    "IGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRy"
    "dWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAg"
    "ICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVkIGZv"
    "ciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAgICAgICBG"
    "YWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAg"
    "ICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJw"
    "aXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAg"
    "ICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVz"
    "dHMiKSwKICAgICAgICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9yY2giLCAgICAgICAgICAgICAgICBGYWxzZSwK"
    "ICAgICAgICAgInBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgidHJh"
    "bnNmb3JtZXJzIiwgICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3Rh"
    "bGwgdHJhbnNmb3JtZXJzICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgicHludm1sIiwgICAgICAg"
    "ICAgICAgICAgICAgICJweW52bWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHludm1sICAo"
    "b25seSBuZWVkZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmluZykiKSwKICAgIF0KCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBj"
    "aGVjayhjbHMpIC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlzdFtzdHJdXToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm5zIChtZXNz"
    "YWdlcywgY3JpdGljYWxfZmFpbHVyZXMpLgogICAgICAgIG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv4pyX"
    "IOKAlCBub3RlIiBzdHJpbmdzCiAgICAgICAgY3JpdGljYWxfZmFpbHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3Jp"
    "dGljYWwgYW5kIG1pc3NpbmcKICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0g"
    "W10KICAgICAgICBjcml0aWNhbCAgPSBbXQoKICAgICAgICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwg"
    "aGludCBpbiBjbHMuUEFDS0FHRVM6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9k"
    "dWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyTIikK"
    "ICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19j"
    "cml0aWNhbCBlbHNlICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAg"
    "ICBmIltERVBTXSB7cGtnX25hbWV9IOKclyAoe3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICBpZiBpc19jcml0aWNhbDoKICAgICAgICAgICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAg"
    "ICAgIHJldHVybiBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAt"
    "PiBzdHI6CiAgICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0cmluZy4iIiIKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0OjExNDM0"
    "L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTIpCiAgICAg"
    "ICAgICAgIGlmIHJlc3Auc3RhdHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJMg4oCU"
    "IHJ1bm5pbmcgb24gbG9jYWxob3N0OjExNDM0IgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAg"
    "ICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAob25seSBuZWVkZWQgZm9yIE9sbGFtYSBtb2Rl"
    "bCB0eXBlKSIKCgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWVt"
    "b3J5TWFuYWdlcjoKICAgICIiIgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVtb3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFu"
    "YWdlZDoKICAgICAgICBtZW1vcmllcy9tZXNzYWdlcy5qc29ubCAgICAgICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBl"
    "ZAogICAgICAgIG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAgICAg4oCUIGV4dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAg"
    "ICAgIG1lbW9yaWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg4oCUIGVudGl0eSBzdGF0ZQogICAgICAgIG1lbW9yaWVzL2luZGV4"
    "Lmpzb24gICAgICAgICAgICAg4oCUIGNvdW50cyBhbmQgbWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5m"
    "ZXJlbmNlLCBrZXl3b3JkIGV4dHJhY3Rpb24sIHRhZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBh"
    "bmQgcmVsZXZhbmNlIHNjb3JpbmcgZm9yIGNvbnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYp"
    "OgogICAgICAgIGJhc2UgICAgICAgICAgICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAg"
    "PSBiYXNlIC8gIm1lc3NhZ2VzLmpzb25sIgogICAgICAgIHNlbGYubWVtb3JpZXNfcCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25s"
    "IgogICAgICAgIHNlbGYuc3RhdGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5pbmRleF9wICAgICA9"
    "IGJhc2UgLyAiaW5kZXguanNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBs"
    "b2FkX3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAgICAgICAg"
    "cmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoc2Vs"
    "Zi5zdGF0ZV9wLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3QpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5zdGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0y"
    "KSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAg"
    "ICByZXR1cm4gewogICAgICAgICAgICAicGVyc29uYV9uYW1lIjogICAgICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAi"
    "ZGVja192ZXJzaW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAgICAgICJzZXNzaW9uX2NvdW50IjogICAgICAg"
    "ICAgICAwLAogICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3Rfc2h1"
    "dGRvd24iOiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6ICAgICAgICAgICAgICBOb25lLAogICAg"
    "ICAgICAgICAidG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogICAgICAg"
    "ICAgIDAsCiAgICAgICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAgICAgICB7fSwKICAgICAgICAgICAgImFpX3N0YXRlX2F0"
    "X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAg"
    "IGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2Nh"
    "bF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAg"
    "ICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250"
    "ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxm"
    "Lm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNl"
    "bGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2Vz"
    "X3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShz"
    "ZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6"
    "IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQs"
    "IGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBh"
    "c3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4"
    "dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0"
    "LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBh"
    "c3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1"
    "dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAg"
    "ICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBE"
    "RUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6"
    "ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNv"
    "bnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFu"
    "dF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3Mi"
    "OiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4g"
    "ewogICAgICAgICAgICAgICAgImRyZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAg"
    "ICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAg"
    "ICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAg"
    "IHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAt"
    "PiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0"
    "dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZh"
    "bGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3Jp"
    "ZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAg"
    "cmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGlt"
    "aXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRl"
    "bV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIs"
    "ICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgi"
    "Y29udGVudCIsICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAg"
    "ICAgICAgICAiICIuam9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAg"
    "ICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0"
    "Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAg"
    "ICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAgaWYg"
    "InRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEiICAgaW4g"
    "cWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGlu"
    "IHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAg"
    "ICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwg"
    "eFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVy"
    "biBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBx"
    "dWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRl"
    "eHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRv"
    "IG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNl"
    "bGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBm"
    "b3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBl"
    "JywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5Jywn"
    "Jyl9IgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAg"
    "ICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5"
    "KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoK"
    "ICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNh"
    "bmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0K"
    "ICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlk"
    "YXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAg"
    "ICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAgICAgICAgICAg"
    "IGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAg"
    "ICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAg"
    "ICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQog"
    "ICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFn"
    "cy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAg"
    "ICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAg"
    "ICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBr"
    "dyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBl"
    "bmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtd"
    "CiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBz"
    "ZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBk"
    "ZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJu"
    "IFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVu"
    "KHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAg"
    "ICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYg"
    "bToKICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAg"
    "ICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAgcmV0"
    "dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAg"
    "ICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4o"
    "a2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJl"
    "c29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9"
    "Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAg"
    "ICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAg"
    "ICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29u"
    "dmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUo"
    "c2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDog"
    "c3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0"
    "LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2Ny"
    "aWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5k"
    "ZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBp"
    "c3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29y"
    "ZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1"
    "c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90"
    "ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNh"
    "dGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8t"
    "bWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVh"
    "Y2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAg"
    "IFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBT"
    "UUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9"
    "IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdf"
    "cGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lv"
    "bl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0"
    "aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0"
    "KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9w"
    "dGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjog"
    "c3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAg"
    "ICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1w"
    "IjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAg"
    "ICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRl"
    "ZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExM"
    "TS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1d"
    "CiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1b"
    "ImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGlu"
    "ICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+"
    "IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQo"
    "c2VsZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9u"
    "ZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgog"
    "ICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAg"
    "ICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlz"
    "b2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAg"
    "ICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAg"
    "ICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0"
    "KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAg"
    "ICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4"
    "aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1u"
    "YW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgK"
    "ICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2Vy"
    "IiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgp"
    "Wzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoK"
    "ICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25f"
    "aWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJt"
    "ZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVz"
    "c2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2Ug"
    "IiIpLAogICAgICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhp"
    "c3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRl"
    "eFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNl"
    "cnQoMCwgZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25z"
    "Il0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAg"
    "TE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBh"
    "bGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCku"
    "Z2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0"
    "cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBz"
    "dHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAg"
    "ICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgog"
    "ICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9"
    "IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9s"
    "b2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Np"
    "b25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNh"
    "dGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0K"
    "CiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNn"
    "IGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAg"
    "ICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdl"
    "dCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9"
    "IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoK"
    "ICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0g"
    "Tm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAg"
    "ICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRl"
    "OiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJl"
    "dHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVu"
    "dHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAg"
    "ICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4"
    "KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRF"
    "WCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAgICAgICBy"
    "ZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYt"
    "OCIpCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6"
    "IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9w"
    "YXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04Igog"
    "ICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAi"
    "IiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4K"
    "CiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5"
    "U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1"
    "bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUg"
    "c2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUu"
    "CiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6"
    "CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBk"
    "ZWYgYWRkKHNlbGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAg"
    "ICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0"
    "ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAg"
    "ICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgIGxv"
    "Y2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1"
    "YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAg"
    "ICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAg"
    "ICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAg"
    "ICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGlj"
    "YXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJl"
    "dHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAog"
    "ICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciBy"
    "IGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigp"
    "ICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBh"
    "bmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAg"
    "ICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAg"
    "ICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQo"
    "InRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFj"
    "azoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVy"
    "biByZXN1bHRzCgogICAgZGVmIGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlk"
    "IikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoK"
    "ICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEg"
    "Y29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50"
    "byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNl"
    "YXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAg"
    "ICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQog"
    "ICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0"
    "KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4o"
    "ZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQog"
    "ICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVy"
    "KCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCBy"
    "ZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5j"
    "ZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgog"
    "ICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAg"
    "ICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAg"
    "ICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJO"
    "byB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAo"
    "PzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5v"
    "dCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAg"
    "ICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIs"
    "CiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRleCB3aXRoICIK"
    "ICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVz"
    "ZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxT"
    "TCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBh"
    "c3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRp"
    "b24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxp"
    "dGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRs"
    "ZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBo"
    "YW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdP"
    "UkQiLAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZl"
    "IGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCBy"
    "ZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZy"
    "b20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVu"
    "YygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAg"
    "ICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAg"
    "ICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAg"
    "ICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAg"
    "ICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAg"
    "ICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAg"
    "ICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgog"
    "ICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAog"
    "ICAgICAgICAgICAgICAgICAgICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAg"
    "VEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgog"
    "ICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpz"
    "b25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgx"
    "bWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5j"
    "ZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5"
    "X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEK"
    "CiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3Vu"
    "Y2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50"
    "YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTIt"
    "bWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0"
    "aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3Ig"
    "dCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlk"
    "NCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxk"
    "IG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0Lmdl"
    "dCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwg"
    "ICAgICAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0"
    "X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgi"
    "c291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5v"
    "bmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5z"
    "ZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAg"
    "ICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAg"
    "ICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBw"
    "YXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAt"
    "IHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxp"
    "emVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3Jt"
    "YWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3Rd"
    "KSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDog"
    "c3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAg"
    "cHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAiaWQiOiAgICAg"
    "ICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAg"
    "bG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRz"
    "IiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAg"
    "ICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlf"
    "Y291bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0"
    "cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNl"
    "IjogICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAg"
    "ICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVf"
    "YWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBz"
    "dGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtk"
    "aWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBp"
    "ZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAg"
    "ICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19p"
    "c28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAg"
    "cmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAg"
    "ICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQi"
    "KSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAg"
    "ICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0"
    "YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9y"
    "IHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0"
    "dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25v"
    "d19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAg"
    "ICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNl"
    "bGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0"
    "LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFz"
    "a3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAg"
    "IHJldHVybiByZW1vdmVkCgoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBs"
    "ZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRy"
    "eSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlbnRf"
    "dHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQg"
    "c2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAg"
    "bm93ICAgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAg"
    "ICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAg"
    "ICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBz"
    "dGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFyc2Vf"
    "bG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0"
    "KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3Jl"
    "dHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5l"
    "IikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUg"
    "YW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQgbm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAg"
    "ICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInBy"
    "ZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAg"
    "ICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1si"
    "c3RhdHVzIl0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09"
    "IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICAp"
    "Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykp"
    "CiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgU25v"
    "b3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5l"
    "IGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAg"
    "ICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5h"
    "c3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAg"
    "ICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3Jl"
    "dCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2Vy"
    "ZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIs"
    "MCkpICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAg"
    "ICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5h"
    "c3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAgICAgICAgICAgIGV2"
    "ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hh"
    "bmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJz"
    "ZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmlu"
    "ZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIKICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1"
    "ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBO"
    "b25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVS"
    "QUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNt"
    "ZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNz"
    "aWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIs"
    "ICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgICMgU3RyaXAgY29tbW9u"
    "IGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tf"
    "TkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIs"
    "IHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAg"
    "IHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3Ii"
    "XGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIi"
    "XGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xz"
    "K2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMr"
    "dGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMr"
    "dGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAg"
    "aW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAs"
    "IGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJyZW1pbmRlciIKICAgICAgICBlbGlm"
    "IGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRhc2siCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVudCwg"
    "ImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4"
    "dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0"
    "aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwg"
    "InRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAgICAgICAg"
    "UmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAg"
    "ICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMg"
    "ImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxz"
    "KihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlm"
    "IG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAg"
    "ICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBpZiAi"
    "aG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAgICAg"
    "aWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4g"
    "dW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFt"
    "L3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFt"
    "fHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3Jv"
    "dXAoMSkpCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAgICBh"
    "cG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAxMgogICAgICAgICAg"
    "ICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIs"
    "IG1pbnV0ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAg"
    "ICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJvdyBhdCAu"
    "Li4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAgICB0"
    "b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9IFRh"
    "c2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6CiAgICAgICAg"
    "ICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBS"
    "RVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0"
    "ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0"
    "YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcu"
    "Z2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlz"
    "dHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVu"
    "ZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNp"
    "ZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMg"
    "TG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3Jl"
    "YXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29y"
    "aykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQg"
    "aWYgdXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg"
    "4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRo"
    "LndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmlu"
    "ZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdy"
    "aXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIs"
    "IFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFNlbGZUYWIsIERpYWdub3N0aWNzVGFiKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMg"
    "TU9SR0FOTkEgREVDSyDigJQgUEFTUyA1OiBUQUIgQ09OVEVOVCBDTEFTU0VTCiMKIyBUYWJzIGRlZmluZWQgaGVyZToKIyAgIFNM"
    "U2NhbnNUYWIgICAgICDigJQgZ3JpbW9pcmUtY2FyZCBzdHlsZSwgcmVidWlsdCAoRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQs"
    "CiMgICAgICAgICAgICAgICAgICAgICBwYXJzZXIgZml4ZWQsIGNvcHktdG8tY2xpcGJvYXJkIHBlciBpdGVtKQojICAgU0xDb21t"
    "YW5kc1RhYiAgIOKAlCBnb3RoaWMgdGFibGUsIGNvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQKIyAgIEpvYlRyYWNrZXJUYWIgICDi"
    "gJQgZnVsbCByZWJ1aWxkIGZyb20gc3BlYywgQ1NWL1RTViBleHBvcnQKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRsZSBuYXJy"
    "YXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1IG91dHB1dCArIGhhcmR3YXJlIHJl"
    "cG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMgICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCAr"
    "IGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMgX3JlCgoKIyDilIDilIAgU0hBUkVEIEdP"
    "VEhJQyBUQUJMRSBTVFlMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAtPiBzdHI6CiAgICByZXR1cm4gZiIiIgogICAgICAgIFFU"
    "YWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07"
    "CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgZ3JpZGxpbmUtY29sb3I6"
    "IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQt"
    "c2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgICAgICAgICBi"
    "YWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAgICAgICAgfX0K"
    "ICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAg"
    "ICAgICAgfX0KICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9Owog"
    "ICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsK"
    "ICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsK"
    "ICAgICAgICAgICAgZm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9sZDsKICAgICAgICAgICAgbGV0"
    "dGVyLXNwYWNpbmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4dDogc3RyLCB0b29sdGlwOiBz"
    "dHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQogICAgYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogNHB4"
    "IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAgICAgICBidG4uc2V0VG9vbFRpcCh0"
    "b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgIGxibCA9IFFM"
    "YWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4"
    "OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMgVEFCIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBhdmF0"
    "YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZyb20gc3BlYzoKICAgICAgLSBDYXJkL2dyaW1vaXJlLWVu"
    "dHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGltZXN0YW1wLWF3YXJlIHBhcnNlcikKICAgICAgLSBEaXNwbGF5"
    "IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRlc2NyaXB0aW9uLCBpbmRpdmlk"
    "dWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBhcnNlICh3"
    "YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAgIC0gQ29weS10by1jbGlwYm9h"
    "cmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIp"
    "IC8gInNsX3NjYW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3Nl"
    "bGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICAjIEJ1dHRvbiBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICAgPSBfZ290"
    "aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5ID0gX2dvdGhp"
    "Y19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBkZXRhaWxzIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5"
    "ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kZWxl"
    "dGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5f"
    "cmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4dCBvZiBzZWxlY3RlZCBzY2FuIikK"
    "ICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAgICAgICBzZWxmLl9idG5fZGlz"
    "cGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fcmVwYXJzZSkKICAgICAg"
    "ICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYuX2J0bl9tb2RpZnksCiAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2J0bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQog"
    "ICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgICMgU3RhY2s6IGxpc3Qg"
    "dmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4gbGlzdCAo"
    "Z3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAgICAgICBs"
    "MC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbCA9IFFTY3JvbGxBcmVhKCkK"
    "ICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9s"
    "bC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAgc2VsZi5fY2FyZF9j"
    "b250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94TGF5b3V0KHNlbGYuX2NhcmRf"
    "Y29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAg"
    "IHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5hZGRTdHJldGNoKCkKICAg"
    "ICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgbDAuYWRkV2lkZ2V0"
    "KHNlbGYuX2NhcmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyDilIDilIAgUEFH"
    "RSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBw"
    "MSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBT"
    "Q0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0gUUxpbmVFZGl0KCkKICAgICAgICBz"
    "ZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIGwx"
    "LmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJ"
    "T04iKSkKICAgICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLnNldE1heGlt"
    "dW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAgICAgIGwxLmFkZFdpZGdldChfc2Vj"
    "dGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAgIHNlbGYuX2FkZF9yYXcgICA9IFFUZXh0"
    "RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJQYXN0ZSB0aGUgcmF3"
    "IFNlY29uZCBMaWZlIHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3XSB3aWxs"
    "IGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAgICApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2Fk"
    "ZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBpdGVtcwogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0gUVRhYmxlV2lkZ2V0KDAs"
    "IDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJd"
    "KQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAg"
    "ICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250"
    "YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJl"
    "dGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX2FkZF9wcmV2"
    "aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfcHJl"
    "dmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fcHJldmlld19wYXJzZSkKCiAgICAg"
    "ICAgYnRuczEgPSBRSEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzEgPSBfZ290aGlj"
    "X2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBjMS5jbGlj"
    "a2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczEuYWRkV2lkZ2V0"
    "KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRjaCgpCiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0bnMxKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAyOiBkaXNwbGF5IOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAg"
    "ICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBz"
    "ZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYyAg"
    "PSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BfZGVz"
    "Yy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFibGVXaWRn"
    "ZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0"
    "b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAg"
    "ICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpv"
    "bnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0"
    "cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAg"
    "ICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5Db250ZXh0TWVudVBvbGljeS5D"
    "dXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5l"
    "Y3QoCiAgICAgICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF9u"
    "YW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3Bf"
    "dGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55IGl0ZW0gdG8gY29weSBpdCB0byBj"
    "bGlwYm9hcmQuIikKICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9E"
    "SU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGwy"
    "LmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNfYnRuKCLil4AgQmFjayIpCiAgICAgICAgYmsyLmNs"
    "aWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBsMi5hZGRXaWRnZXQo"
    "YmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAgUEFHRSAzOiBtb2RpZnkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDMgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTkFNRSIpKQogICAg"
    "ICAgIHNlbGYuX21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX25hbWUpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2MgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgSVRFTVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZSA9IFFUYWJs"
    "ZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJD"
    "cmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgK"
    "ICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jp"
    "em9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "U3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "czMgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczMuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYu"
    "X3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBidG5zMy5hZGRXaWRnZXQoYzMp"
    "OyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lk"
    "Z2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBw"
    "YXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgUGFy"
    "c2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBpdGVtcykuCgogICAgICAgIEtFWSBGSVg6IEJlZm9yZSBz"
    "cGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRpbWVzdGFtcCBzbyBzaW5nbGUt"
    "bGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzExOjQ3XSBB"
    "dmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46IEl0ZW0gTmFtZSBbQXR0YWNobWVu"
    "dF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3XSAuLi4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgcmF3LnN0cmlwKCk6"
    "CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9XTiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTogbm9ybWFsaXplIOKAlCBp"
    "bnNlcnQgbmV3bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbm9ybWFsaXplZCA9IF9y"
    "ZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAgIGxpbmVzID0gW2wuc3RyaXAoKSBm"
    "b3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMjogZXh0"
    "cmFjdCBhdmF0YXIgbmFtZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFtZSA9ICJVTktOT1dOIgogICAg"
    "ICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBvciBz"
    "aW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgciIoXHdbXHdcc10rPyknc1xzK3B1Ymxp"
    "Y1xzK2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYg"
    "bToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBicmVhawoK"
    "ICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjIFN0cmlwIGxlYWRp"
    "bmcgdGltZXN0YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpcZHsyfVxdXHMqJywgJycsIGxp"
    "bmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNobWVudHMiIGluIGNvbnRlbnQubG93"
    "ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93ZXIoKS5zdGFydHN3aXRoKCJv"
    "YmplY3QiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZpZGVyIGxpbmVzIOKAlCBsaW5l"
    "cyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAgICAgICAgICAjIGUuZy4g4paC4paC4paC4paC4paC"
    "4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkCBvciDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50LnN0cmlwKCIuOiAiKQogICAg"
    "ICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250aW51ZSAg"
    "IyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAgIyBUcnkgdG8gZXh0cmFjdCBDUkVB"
    "VE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9yID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnQK"
    "CiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2ggPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidDUkVBVE9SOlxzKihbXHdc"
    "c10rPykoPzpccypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgY3JlYXRvcl9tYXRj"
    "aDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSkuc3RyaXAoKQogICAgICAgICAgICAg"
    "ICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJpcCgpCgogICAgICAgICAgICAjIFN0cmlw"
    "IGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBpdGVtX25hbWUgPSBfcmUuc3Vi"
    "KHInXHMqXFtbXHdcc19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBpdGVtX25hbWUgPSBpdGVtX25h"
    "bWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUgYW5kIGxlbihpdGVtX25hbWUpID4gMToKICAgICAgICAg"
    "ICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUsICJjcmVhdG9yIjogY3JlYXRvcn0pCgogICAgICAgIHJldHVy"
    "biBhdmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfY2FyZHMoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUgc2VsZi5fY2Fy"
    "ZF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtlQXQoMCkKICAgICAg"
    "ICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAg"
    "ICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtlX2NhcmQocmVjKQogICAgICAg"
    "ICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5jb3Vu"
    "dCgpIC0gMSwgY2FyZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVjOiBkaWN0KSAtPiBRV2lkZ2V0"
    "OgogICAgICAgIGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgicmVjb3JkX2lkIikgPT0gc2Vs"
    "Zi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEw"
    "YTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IHBhZGRp"
    "bmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJuYW1lIiwgIlVOS05P"
    "V04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVCBp"
    "ZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGNvdW50ID0gbGVuKHJlYy5n"
    "ZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0gaXRlbXMiKQogICAgICAgIGNvdW50"
    "X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxMHB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJsID0gUUxhYmVsKHJlYy5nZXQo"
    "ImNyZWF0ZWRfYXQiLCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICAp"
    "CgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgicmVjb3Jk"
    "X2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJlY19pZDogc2VsZi5fc2VsZWN0"
    "X2NhcmQocmlkKQogICAgICAgIHJldHVybiBjYXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRfaWQ6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkg"
    "ICMgUmVidWlsZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVkX3JlY29yZChzZWxmKSAtPiBP"
    "cHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIgaW4gc2VsZi5fcmVjb3Jkcwog"
    "ICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkKSwKICAgICAgICAgICAgTm9uZQog"
    "ICAgICAgICkKCiAgICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICMgRW5zdXJlIHJlY29yZF9p"
    "ZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBzZWxmLl9yZWNvcmRzOgogICAg"
    "ICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSByLmdldCgi"
    "aWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICBpZiBjaGFuZ2Vk"
    "OgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX2J1aWxkX2Nh"
    "cmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZpZXdfcGFyc2Uoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNl"
    "bGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQobmFtZSkKICAg"
    "ICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiBpdGVtc1s6MjBdOiAgIyBwcmV2"
    "aWV3IGZpcnN0IDIwCiAgICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X2FkZF9wcmV2aWV3Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDAsIFFUYWJs"
    "ZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMSwgUVRhYmxl"
    "V2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3Nob3dfYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "YWRkX25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBm"
    "cm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuY2xlYXIo"
    "KQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudElu"
    "ZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jhdy50b1BsYWlu"
    "VGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgb3ZlcnJpZGVfbmFt"
    "ZSA9IHNlbGYuX2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMp"
    "Lmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgp"
    "KSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJuYW1lIjogICAgICAg"
    "IG92ZXJyaWRlX25hbWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5fYWRkX2Rlc2MudG9QbGFpblRl"
    "eHQoKVs6MjQ0XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAgICJyYXdfdGV4dCI6ICAgIHJh"
    "dywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9hdCI6ICBub3csCiAgICAgICAg"
    "fQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxm"
    "Ll9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQiXQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9y"
    "ZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBT"
    "Y2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRpc3BsYXkuIikKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5nZXQoJ25hbWUnLCcnKX0i"
    "KQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgc2VsZi5f"
    "ZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAg"
    "ICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaW5zZXJ0Um93KHIp"
    "CiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAg"
    "ICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNl"
    "dEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0X21lbnUoc2VsZiwgcG9zKSAtPiBOb25lOgogICAgICAgIGlk"
    "eCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1ZhbGlkKCk6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IKICAgICAg"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVhdG9yICAgID0gKHNlbGYuX2Rp"
    "c3BfdGFibGUuaXRlbShpZHgucm93KCksIDEpIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIiKSku"
    "dGV4dCgpCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1lbnUoc2Vs"
    "ZikKICAgICAgICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAg"
    "ICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAgICBhX2NyZWF0b3IgPSBtZW51LmFk"
    "ZEFjdGlvbigiQ29weSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBCb3RoIikKICAg"
    "ICAgICBhY3Rpb24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAg"
    "ICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBhY3Rpb24gPT0gYV9pdGVtOiAgICBjYi5zZXRUZXh0"
    "KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0b3I6IGNiLnNldFRleHQoY3JlYXRvcikKICAgICAgICBl"
    "bGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVhdG9yfSIpCgogICAgZGVmIF9z"
    "aG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYg"
    "bm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQocmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjLnNldFRl"
    "eHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAg"
    "ICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgp"
    "CiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0"
    "ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0"
    "b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgzKQoKICAgIGRlZiBfZG9fbW9kaWZ5"
    "X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCBy"
    "ZWM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYuX21vZF9uYW1lLnRleHQoKS5z"
    "dHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQoKVs6MjQ0"
    "XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKSk6CiAg"
    "ICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkK"
    "ICAgICAgICAgICAgY3IgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQo"
    "KQogICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9XTiIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAgcmVjWyJpdGVtcyJdICAgICAg"
    "PSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkK"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAg"
    "IGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRlbGV0ZS4iKQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVz"
    "dGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IFRoaXMg"
    "Y2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJv"
    "eC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lkXQogICAgICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IE5vbmUKICAg"
    "ICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBz"
    "ZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0"
    "aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRv"
    "IHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJhdyA9IHJlYy5nZXQoInJhd190ZXh0IiwiIikKICAgICAg"
    "ICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2UiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlzIHNjYW4uIikKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVjWyJpdGVt"
    "cyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0gb3IgbmFtZQogICAgICAgIHJl"
    "Y1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5m"
    "b3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJGb3VuZCB7bGVuKGl0"
    "ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IFNMQ29tbWFuZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQgcmVmZXJlbmNlIHRhYmxlLgog"
    "ICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQgYnV0dG9uIHBlciByb3cuCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIKICAgICAgICBzZWxmLl9yZWNv"
    "cmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBk"
    "ZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIpCiAgICAgICAgc2VsZi5f"
    "YnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19i"
    "dG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0bigi4qeJIENvcHkgQ29tbWFuZCIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxlY3RlZCBjb21tYW5kIHRvIGNsaXBib2Fy"
    "ZCIpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUp"
    "CiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2NvcHlfY29tbWFuZCkKICAgICAgICBzZWxmLl9i"
    "dG5fcmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBz"
    "ZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwgc2VsZi5f"
    "YnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcu"
    "UmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RS"
    "b3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEp"
    "CgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxlY3QgYSByb3cgYW5kIGNsaWNrIOKniSBDb3B5IENvbW1h"
    "bmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50LnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRS"
    "b3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29tbWFuZCIsIiIpKSkKICAgICAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNj"
    "cmlwdGlvbiIsIiIpKSkKCiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3Rh"
    "YmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW0gPSBzZWxm"
    "Ll90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCku"
    "c2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2co"
    "c2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAg"
    "ICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoi"
    "LCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2su"
    "Y2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFk"
    "ZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4"
    "ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAg"
    "ICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAgICJjcmVh"
    "dGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcmVjWyJjb21tYW5k"
    "Il06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChz"
    "ZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX21vZGlm"
    "eShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAg"
    "b3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jk"
    "c1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kaWZ5IENvbW1h"
    "bmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAg"
    "ICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbW1hbmQiLCIi"
    "KSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "IkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQog"
    "ICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAg"
    "ICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAg"
    "IGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZWNbImNvbW1hbmQiXSAg"
    "ICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50ZXh0KCku"
    "c3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5p"
    "c29mb3JtYXQoKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUu"
    "Y3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhpcyBjb21tYW5kIikKICAgICAg"
    "ICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwgZiJEZWxldGUgJ3tjbWR9"
    "Jz8iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAg"
    "ICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3Jk"
    "cykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBKT0IgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpvYiBhcHBsaWNhdGlvbiB0cmFja2lu"
    "Zy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAgIEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxlLCBEYXRlIEFwcGxpZWQsIExp"
    "bmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1YgYW5kIFRTViBleHBvcnQu"
    "CiAgICBIaWRkZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBqdXN0IG5vdCBzaG93bi4KICAg"
    "ICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBwbGllZCIsCiAgICAgICAgICAgICAg"
    "ICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiam9i"
    "X3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2hvd19o"
    "aWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0"
    "dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRl"
    "bnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkg"
    "PSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhpY19idG4oIkFyY2hpdmUiLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVkL3JlamVjdGVk"
    "IikKICAgICAgICBzZWxmLl9idG5fdW5oaWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAgICBzZWxmLl9idG5fZGVsZXRl"
    "ID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3RoaWNfYnRuKCJTaG93IEFyY2hp"
    "dmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIpCgogICAgICAgIGZvciBiIGluIChz"
    "ZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRu"
    "X3VuaGlkZSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSwgc2VsZi5fYnRuX2V4"
    "cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYp"
    "CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBz"
    "ZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9oaWRkZW4pCiAg"
    "ICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIGJhci5hZGRTdHJl"
    "dGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIGxl"
    "bihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoc2VsZi5DT0xVTU5T"
    "KQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgIyBDb21wYW55IGFuZCBKb2IgVGl0"
    "bGUgc3RyZXRjaAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRj"
    "aCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgyLCAxMDAp"
    "CiAgICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRo"
    "KDQsIDgwKQogICAgICAgICMgTm90ZXMgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNSwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAg"
    "ICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5z"
    "ZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVkU2VsZWN0"
    "aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEp"
    "CgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9w"
    "YXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgog"
    "ICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIsIEZhbHNlKSkKICAgICAgICAgICAgaWYgaGlkZGVuIGFu"
    "ZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByID0gc2VsZi5fdGFi"
    "bGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVzID0gIkFy"
    "Y2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAgICAgICAgICB2YWxzID0gWwogICAg"
    "ICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiks"
    "CiAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsi"
    "LCIiKSwKICAgICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAg"
    "ICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAgICAgICAgICAgaXRlbSA9IFFUYWJs"
    "ZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAgICAgICAgICAgICAgICAgIGl0ZW0uc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIGMsIGl0"
    "ZW0pCiAgICAgICAgICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVzZXIgZGF0YQogICAgICAgICAg"
    "ICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAgICAgICAgICBRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUs"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJlYykKICAgICAgICAgICAgKQoKICAgIGRlZiBfc2VsZWN0ZWRf"
    "aW5kaWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2Vs"
    "Zi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRlbS5yb3co"
    "KSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSByb3dfaXRlbS5kYXRhKFF0Lkl0ZW1E"
    "YXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBp"
    "bmRpY2VzLmFkZChpZHgpCiAgICAgICAgcmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9nKHNlbGYsIHJlYzog"
    "ZGljdCA9IE5vbmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNl"
    "dFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkKICAgICAgICBmb3JtID0gUUZvcm1M"
    "YXlvdXQoZGxnKQoKICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnkiLCIiKSBpZiByZWMgZWxzZSAi"
    "IikKICAgICAgICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAg"
    "ICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVuZGFyUG9wdXAoVHJ1ZSkKICAgICAgICBkZS5zZXRE"
    "aXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMgYW5kIHJlYy5nZXQoImRhdGVfYXBwbGllZCIpOgogICAg"
    "ICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwieXl5eS1NTS1kZCIpKQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAgID0gUUxp"
    "bmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0dXMgID0gUUxpbmVFZGl0KHJlYy5n"
    "ZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMgZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90ZXMgICA9IFFMaW5lRWRpdChy"
    "ZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAg"
    "ICAgICgiQ29tcGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAgICAgICAoIkRhdGUgQXBwbGll"
    "ZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzKSwgKCJOb3RlczoiLCBub3Rl"
    "cyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdldCkKCiAgICAgICAgYnRucyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAg"
    "ICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBi"
    "dG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCgogICAgICAgIGlm"
    "IGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAg"
    "ICAgICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiam9iX3RpdGxlIjog"
    "ICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRvU3RyaW5n"
    "KCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAg"
    "ICAgICAgICAgICJzdGF0dXMiOiAgICAgICBzdGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAgICAgICAgICAg"
    "ICAgIm5vdGVzIjogICAgICAgIG5vdGVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJuIE5vbmUK"
    "CiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2coKQogICAgICAgIGlmIG5vdCBw"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQog"
    "ICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICJoaWRkZW4iOiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUiOiBOb25lLAogICAgICAgICAg"
    "ICAiY3JlYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5vdywKICAgICAgICB9KQogICAg"
    "ICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNl"
    "bGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAgICAgICBRTWVzc2FnZUJveC5p"
    "bmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBleGFj"
    "dGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbaWR4"
    "c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFsb2cocmVjKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICByZWMudXBkYXRlKHApCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRj"
    "KS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVk"
    "X2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJj"
    "b21wbGV0ZWRfZGF0ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XS5nZXQoImNvbXBsZXRlZF9k"
    "YXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5kYXRlKCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAg"
    "ICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVf"
    "anNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fdW5oaWRl"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAgICAgIGlm"
    "IGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAg"
    "ID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVs"
    "ZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIG5vdCBp"
    "ZHhzOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBz"
    "ZWxmLCAiRGVsZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQgYXBwbGljYXRpb24ocyk/IENh"
    "bm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "WWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciBpLCByIGlu"
    "IGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJhZF0KICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IG5vdCBzZWxm"
    "Ll9zaG93X2hpZGRlbgogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAgIuKYgCBIaWRlIEFyY2hp"
    "dmVkIiBpZiBzZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAgICApCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIGZpbHQgPSBRRmlsZURpYWxv"
    "Zy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRyYWNrZXIiLAogICAgICAgICAgICBzdHIo"
    "Y2ZnX3BhdGgoImV4cG9ydHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNTViBGaWxlcyAoKi5jc3YpOztU"
    "YWIgRGVsaW1pdGVkICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRoKCIudHh0IikgZWxzZSAiLCIKICAgICAgICBoZWFkZXIg"
    "PSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQiLCJsaW5rIiwKICAgICAgICAgICAgICAgICAgInN0YXR1cyIs"
    "ImhpZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRoLCAidyIsIGVuY29kaW5nPSJ1"
    "dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxuIikKICAg"
    "ICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAgICAgICAg"
    "ICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgi"
    "bGluayIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAgICAgICAgICAgICAgICAgIHN0"
    "cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGxldGVkX2Rh"
    "dGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgXQog"
    "ICAgICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0cih2KS5yZXBsYWNlKCJcbiIs"
    "IiAiKS5yZXBsYWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxzCiAgICAgICAgICAgICAgICAp"
    "ICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKUgOKUgCBTRUxGIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2VsZlRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYSdz"
    "IGludGVybmFsIGRpYWxvZ3VlIHNwYWNlLgogICAgUmVjZWl2ZXM6IGlkbGUgbmFycmF0aXZlIG91dHB1dCwgdW5zb2xpY2l0ZWQg"
    "dHJhbnNtaXNzaW9ucywKICAgICAgICAgICAgICBQb0kgbGlzdCBmcm9tIGRhaWx5IHJlZmxlY3Rpb24sIHVuYW5zd2VyZWQgcXVl"
    "c3Rpb24gZmxhZ3MsCiAgICAgICAgICAgICAgam91cm5hbCBsb2FkIG5vdGlmaWNhdGlvbnMuCiAgICBSZWFkLW9ubHkgZGlzcGxh"
    "eS4gU2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiIGFsd2F5cy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNl"
    "bGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIElOTkVS"
    "IFNBTkNUVU0g4oCUIHtERUNLX05BTUUudXBwZXIoKX0nUyBQUklWQVRFIFRIT1VHSFRTIikpCiAgICAgICAgc2VsZi5fYnRuX2Ns"
    "ZWFyID0gX2dvdGhpY19idG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkK"
    "ICAgICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAg"
    "IHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAg"
    "ICBzZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9y"
    "OiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BVUlBMRV9ESU19OyAiCiAgICAgICAgICAg"
    "IGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAg"
    "ICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBhcHBlbmQoc2VsZiwgbGFiZWw6IHN0"
    "ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTol"
    "UyIpCiAgICAgICAgY29sb3JzID0gewogICAgICAgICAgICAiTkFSUkFUSVZFIjogIENfR09MRCwKICAgICAgICAgICAgIlJFRkxF"
    "Q1RJT04iOiBDX1BVUlBMRSwKICAgICAgICAgICAgIkpPVVJOQUwiOiAgICBDX1NJTFZFUiwKICAgICAgICAgICAgIlBPSSI6ICAg"
    "ICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAiU1lTVEVNIjogICAgIENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNv"
    "bG9yID0gY29sb3JzLmdldChsYWJlbC51cHBlcigpLCBDX0dPTEQpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYn"
    "W3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyBmb250LXdlaWdo"
    "dDpib2xkOyI+JwogICAgICAgICAgICBmJ+KdpyB7bGFiZWx9PC9zcGFuPjxicj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntDX0dPTER9OyI+e3RleHR9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoIiIp"
    "CiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNw"
    "bGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSAIERJQUdOT1NUSUNTIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgRGlhZ25vc3RpY3NUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEJhY2tlbmQgZGlhZ25vc3RpY3MgZGlz"
    "cGxheS4KICAgIFJlY2VpdmVzOiBoYXJkd2FyZSBkZXRlY3Rpb24gcmVzdWx0cywgZGVwZW5kZW5jeSBjaGVjayByZXN1bHRzLAog"
    "ICAgICAgICAgICAgIEFQSSBlcnJvcnMsIHN5bmMgZmFpbHVyZXMsIHRpbWVyIGV2ZW50cywgam91cm5hbCBsb2FkIG5vdGljZXMs"
    "CiAgICAgICAgICAgICAgbW9kZWwgbG9hZCBzdGF0dXMsIEdvb2dsZSBhdXRoIGV2ZW50cy4KICAgIEFsd2F5cyBzZXBhcmF0ZSBm"
    "cm9tIHBlcnNvbmEgY2hhdCB0YWIuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERJQUdOT1NUSUNTIOKAlCBTWVNURU0gJiBC"
    "QUNLRU5EIExPRyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNl"
    "bGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAg"
    "ICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxm"
    "Ll9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfU0lMVkVSfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTogJ0NvdXJpZXIgTmV3JywgbW9ub3NwYWNlOyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBsb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8i"
    "KSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAg"
    "bGV2ZWxfY29sb3JzID0gewogICAgICAgICAgICAiSU5GTyI6ICBDX1NJTFZFUiwKICAgICAgICAgICAgIk9LIjogICAgQ19HUkVF"
    "TiwKICAgICAgICAgICAgIldBUk4iOiAgQ19HT0xELAogICAgICAgICAgICAiRVJST1IiOiBDX0JMT09ELAogICAgICAgICAgICAi"
    "REVCVUciOiBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGxldmVsX2NvbG9ycy5nZXQobGV2ZWwudXBwZXIo"
    "KSwgQ19TSUxWRVIpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9y"
    "OntDX1RFWFRfRElNfTsiPlt7dGltZXN0YW1wfV08L3NwYW4+ICcKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2Nv"
    "bG9yfTsiPnttZXNzYWdlfTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIo"
    "KS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAg"
    "ICkKCiAgICBkZWYgbG9nX21hbnkoc2VsZiwgbWVzc2FnZXM6IGxpc3Rbc3RyXSwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9u"
    "ZToKICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzOgogICAgICAgICAgICBsdmwgPSBsZXZlbAogICAgICAgICAgICBpZiAi4pyT"
    "IiBpbiBtc2c6ICAgIGx2bCA9ICJPSyIKICAgICAgICAgICAgZWxpZiAi4pyXIiBpbiBtc2c6ICBsdmwgPSAiV0FSTiIKICAgICAg"
    "ICAgICAgZWxpZiAiRVJST1IiIGluIG1zZy51cHBlcigpOiBsdmwgPSAiRVJST1IiCiAgICAgICAgICAgIHNlbGYubG9nKG1zZywg"
    "bHZsKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSA"
    "IExFU1NPTlMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zVGFiKFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYW5kIGNvZGUgbGVzc29ucyBicm93c2VyLgogICAgQWRkLCB2"
    "aWV3LCBzZWFyY2gsIGRlbGV0ZSBsZXNzb25zLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRiOiAiTGVzc29uc0xl"
    "YXJuZWREQiIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kYiA9"
    "IGRiCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5z"
    "KDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgRmlsdGVyIGJhcgogICAgICAgIGZpbHRl"
    "cl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fc2VhcmNoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9zZWFy"
    "Y2guc2V0UGxhY2Vob2xkZXJUZXh0KCJTZWFyY2ggbGVzc29ucy4uLiIpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIgPSBRQ29t"
    "Ym9Cb3goKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmFkZEl0ZW1zKFsiQWxsIiwgIkxTTCIsICJQeXRob24iLCAiUHlTaWRl"
    "NiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiSmF2YVNjcmlwdCIsICJPdGhlciJdKQogICAgICAgIHNl"
    "bGYuX3NlYXJjaC50ZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5jdXJy"
    "ZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJT"
    "ZWFyY2g6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VhcmNoLCAxKQogICAgICAgIGZpbHRlcl9yb3cu"
    "YWRkV2lkZ2V0KFFMYWJlbCgiTGFuZ3VhZ2U6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fbGFuZ19maWx0"
    "ZXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBidG5fYWRkID0gX2dvdGhpY19idG4oIuKcpiBBZGQgTGVzc29uIikKICAgICAgICBidG5fZGVsID0gX2dvdGhpY19idG4o"
    "IuKclyBEZWxldGUiKQogICAgICAgIGJ0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBidG5fZGVs"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2FkZCkKICAgICAg"
    "ICBidG5fYmFyLmFkZFdpZGdldChidG5fZGVsKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKAogICAgICAgICAgICBbIkxhbmd1YWdlIiwgIlJlZmVyZW5jZSBLZXkiLCAiU3Vt"
    "bWFyeSIsICJFbnZpcm9ubWVudCJdCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhh"
    "dmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNl"
    "bGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgVXNlIHNwbGl0dGVyIGJldHdlZW4gdGFi"
    "bGUgYW5kIGRldGFpbAogICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAg"
    "IHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBEZXRhaWwgcGFuZWwKICAgICAgICBkZXRhaWxfd2lk"
    "Z2V0ID0gUVdpZGdldCgpCiAgICAgICAgZGV0YWlsX2xheW91dCA9IFFWQm94TGF5b3V0KGRldGFpbF93aWRnZXQpCiAgICAgICAg"
    "ZGV0YWlsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldFNwYWNp"
    "bmcoMikKCiAgICAgICAgZGV0YWlsX2hlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoIuKdpyBGVUxMIFJVTEUiKSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHNlbGYuX2J0bl9lZGl0X3J1bGUgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRG"
    "aXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5f"
    "YnRuX2VkaXRfcnVsZS50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2VkaXRfbW9kZSkKICAgICAgICBzZWxmLl9idG5fc2F2"
    "ZV9ydWxlID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkK"
    "ICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fc2F2ZV9ydWxlX2VkaXQpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5f"
    "YnRuX2VkaXRfcnVsZSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZV9ydWxlKQogICAgICAg"
    "IGRldGFpbF9sYXlvdXQuYWRkTGF5b3V0KGRldGFpbF9oZWFkZXIpCgogICAgICAgIHNlbGYuX2RldGFpbCA9IFFUZXh0RWRpdCgp"
    "CiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldE1pbmltdW1IZWln"
    "aHQoMTIwKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAg"
    "ICAgICAgKQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RldGFpbCkKICAgICAgICBzcGxpdHRlci5hZGRX"
    "aWRnZXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMzAwLCAxODBdKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9l"
    "ZGl0aW5nX3JvdzogaW50ID0gLTEKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHEgICAgPSBzZWxmLl9z"
    "ZWFyY2gudGV4dCgpCiAgICAgICAgbGFuZyA9IHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0KCkKICAgICAgICBsYW5nID0g"
    "IiIgaWYgbGFuZyA9PSAiQWxsIiBlbHNlIGxhbmcKICAgICAgICBzZWxmLl9yZWNvcmRzID0gc2VsZi5fZGIuc2VhcmNoKHF1ZXJ5"
    "PXEsIGxhbmd1YWdlPWxhbmcpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNl"
    "bGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxl"
    "Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVX"
    "aWRnZXRJdGVtKHJlYy5nZXQoImxhbmd1YWdlIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAg"
    "ICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSkpCiAgICAgICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3VtbWFyeSIs"
    "IiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAzLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJlbnZpcm9ubWVudCIsIiIpKSkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "dyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93ID0gcm93CiAgICAgICAgaWYgMCA8"
    "PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAg"
    "ICBzZWxmLl9kZXRhaWwuc2V0UGxhaW5UZXh0KAogICAgICAgICAgICAgICAgcmVjLmdldCgiZnVsbF9ydWxlIiwiIikgKyAiXG5c"
    "biIgKwogICAgICAgICAgICAgICAgKCJSZXNvbHV0aW9uOiAiICsgcmVjLmdldCgicmVzb2x1dGlvbiIsIiIpIGlmIHJlYy5nZXQo"
    "InJlc29sdXRpb24iKSBlbHNlICIiKQogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVzZXQgZWRpdCBtb2RlIG9uIG5ldyBz"
    "ZWxlY3Rpb24KICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQoKICAgIGRlZiBfdG9nZ2xl"
    "X2VkaXRfbW9kZShzZWxmLCBlZGl0aW5nOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShu"
    "b3QgZWRpdGluZykKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2libGUoZWRpdGluZykKICAgICAgICBzZWxmLl9i"
    "dG5fZWRpdF9ydWxlLnNldFRleHQoIkNhbmNlbCIgaWYgZWRpdGluZyBlbHNlICJFZGl0IikKICAgICAgICBpZiBlZGl0aW5nOgog"
    "ICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcy"
    "fTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTERfRElNfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6"
    "IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBm"
    "ImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVsb2Fk"
    "IG9yaWdpbmFsIGNvbnRlbnQgb24gY2FuY2VsCiAgICAgICAgICAgIHNlbGYuX29uX3NlbGVjdCgpCgogICAgZGVmIF9zYXZlX3J1"
    "bGVfZWRpdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX2VkaXRpbmdfcm93CiAgICAgICAgaWYgMCA8PSByb3cg"
    "PCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHRleHQgPSBzZWxmLl9kZXRhaWwudG9QbGFpblRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgICAgICMgU3BsaXQgcmVzb2x1dGlvbiBiYWNrIG91dCBpZiBwcmVzZW50CiAgICAgICAgICAgIGlmICJcblxuUmVz"
    "b2x1dGlvbjogIiBpbiB0ZXh0OgogICAgICAgICAgICAgICAgcGFydHMgPSB0ZXh0LnNwbGl0KCJcblxuUmVzb2x1dGlvbjogIiwg"
    "MSkKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSBwYXJ0c1swXS5zdHJpcCgpCiAgICAgICAgICAgICAgICByZXNvbHV0aW9u"
    "ID0gcGFydHNbMV0uc3RyaXAoKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHRleHQKICAg"
    "ICAgICAgICAgICAgIHJlc29sdXRpb24gPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJyZXNvbHV0aW9uIiwgIiIpCiAgICAgICAg"
    "ICAgIHNlbGYuX3JlY29yZHNbcm93XVsiZnVsbF9ydWxlIl0gID0gZnVsbF9ydWxlCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNb"
    "cm93XVsicmVzb2x1dGlvbiJdID0gcmVzb2x1dGlvbgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9kYi5fcGF0aCwgc2Vs"
    "Zi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQog"
    "ICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIExlc3NvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgNDAwKQogICAgICAgIGZvcm0g"
    "PSBRRm9ybUxheW91dChkbGcpCiAgICAgICAgZW52ICA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICBsYW5nID0gUUxpbmVFZGl0"
    "KCJMU0wiKQogICAgICAgIHJlZiAgPSBRTGluZUVkaXQoKQogICAgICAgIHN1bW0gPSBRTGluZUVkaXQoKQogICAgICAgIHJ1bGUg"
    "PSBRVGV4dEVkaXQoKQogICAgICAgIHJ1bGUuc2V0TWF4aW11bUhlaWdodCgxMDApCiAgICAgICAgcmVzICA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgbGluayA9IFFMaW5lRWRpdCgpCiAgICAgICAgZm9yIGxhYmVsLCB3IGluIFsKICAgICAgICAgICAgKCJFbnZpcm9u"
    "bWVudDoiLCBlbnYpLCAoIkxhbmd1YWdlOiIsIGxhbmcpLAogICAgICAgICAgICAoIlJlZmVyZW5jZSBLZXk6IiwgcmVmKSwgKCJT"
    "dW1tYXJ5OiIsIHN1bW0pLAogICAgICAgICAgICAoIkZ1bGwgUnVsZToiLCBydWxlKSwgKCJSZXNvbHV0aW9uOiIsIHJlcyksCiAg"
    "ICAgICAgICAgICgiTGluazoiLCBsaW5rKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgdykKICAg"
    "ICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0"
    "bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcu"
    "cmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "YnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc2Vs"
    "Zi5fZGIuYWRkKAogICAgICAgICAgICAgICAgZW52aXJvbm1lbnQ9ZW52LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAg"
    "bGFuZ3VhZ2U9bGFuZy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlZmVyZW5jZV9rZXk9cmVmLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgc3VtbWFyeT1zdW1tLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgZnVsbF9ydWxl"
    "PXJ1bGUudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbj1yZXMudGV4dCgpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICAgICBsaW5rPWxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJl"
    "bnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWNfaWQgPSBzZWxm"
    "Ll9yZWNvcmRzW3Jvd10uZ2V0KCJpZCIsIiIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAg"
    "ICAgICAgICAgICBzZWxmLCAiRGVsZXRlIExlc3NvbiIsCiAgICAgICAgICAgICAgICAiRGVsZXRlIHRoaXMgbGVzc29uPyBDYW5u"
    "b3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJv"
    "eC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5k"
    "YXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX2RiLmRlbGV0ZShyZWNfaWQpCiAgICAgICAgICAgICAgICBzZWxm"
    "LnJlZnJlc2goKQoKCiMg4pSA4pSAIE1PRFVMRSBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kdWxlVHJh"
    "Y2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYWwgbW9kdWxlIHBpcGVsaW5lIHRyYWNrZXIuCiAgICBUcmFjayBw"
    "bGFubmVkL2luLXByb2dyZXNzL2J1aWx0IG1vZHVsZXMgYXMgdGhleSBhcmUgZGVzaWduZWQuCiAgICBFYWNoIG1vZHVsZSBoYXM6"
    "IE5hbWUsIFN0YXR1cywgRGVzY3JpcHRpb24sIE5vdGVzLgogICAgRXhwb3J0IHRvIFRYVCBmb3IgcGFzdGluZyBpbnRvIHNlc3Np"
    "b25zLgogICAgSW1wb3J0OiBwYXN0ZSBhIGZpbmFsaXplZCBzcGVjLCBpdCBwYXJzZXMgbmFtZSBhbmQgZGV0YWlscy4KICAgIFRo"
    "aXMgaXMgYSBkZXNpZ24gbm90ZWJvb2sg4oCUIG5vdCBjb25uZWN0ZWQgdG8gZGVja19idWlsZGVyJ3MgTU9EVUxFIHJlZ2lzdHJ5"
    "LgogICAgIiIiCgogICAgU1RBVFVTRVMgPSBbIklkZWEiLCAiRGVzaWduaW5nIiwgIlJlYWR5IHRvIEJ1aWxkIiwgIlBhcnRpYWwi"
    "LCAiQnVpbHQiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1vZHVsZV90cmFja2VyLmpzb25sIgog"
    "ICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxm"
    "LnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQg"
    "ICAgPSBfZ290aGljX2J0bigiQWRkIE1vZHVsZSIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQgICA9IF9nb3RoaWNfYnRuKCJFZGl0"
    "IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9y"
    "dCA9IF9nb3RoaWNfYnRuKCJFeHBvcnQgVFhUIikKICAgICAgICBzZWxmLl9idG5faW1wb3J0ID0gX2dvdGhpY19idG4oIkltcG9y"
    "dCBTcGVjIikKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2VkaXQsIHNlbGYuX2J0bl9kZWxldGUs"
    "CiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9leHBvcnQsIHNlbGYuX2J0bl9pbXBvcnQpOgogICAgICAgICAgICBiLnNldE1p"
    "bmltdW1XaWR0aCg4MCkKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBidG5fYmFyLmFkZFdp"
    "ZGdldChiKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikKCiAgICAg"
    "ICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9lZGl0LmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19lZGl0KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAg"
    "c2VsZi5fYnRuX2ltcG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faW1wb3J0KQoKICAgICAgICAjIFRhYmxlCiAgICAgICAg"
    "c2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMykKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFi"
    "ZWxzKFsiTW9kdWxlIE5hbWUiLCAiU3RhdHVzIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jp"
    "em9udGFsSGVhZGVyKCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZp"
    "eGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDAsIDE2MCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDEs"
    "IDEwMCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVj"
    "dGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBTcGxpdHRlcgogICAgICAg"
    "IHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChz"
    "ZWxmLl90YWJsZSkKCiAgICAgICAgIyBOb3RlcyBwYW5lbAogICAgICAgIG5vdGVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAg"
    "IG5vdGVzX2xheW91dCA9IFFWQm94TGF5b3V0KG5vdGVzX3dpZGdldCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBub3Rlc19sYXlvdXQu"
    "YWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5PVEVTIikpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheSA9IFFUZXh0RWRp"
    "dCgpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3Bs"
    "YXkuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6"
    "IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbm90ZXNf"
    "ZGlzcGxheSkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQobm90ZXNfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVz"
    "KFsyNTAsIDE1MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgICMgQ291bnQgbGFiZWwKICAg"
    "ICAgICBzZWxmLl9jb3VudF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb3VudF9sYmwpCgogICAgZGVmIHJlZnJlc2go"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2Vs"
    "Zi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgICAgICBzdGF0"
    "dXNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3RhdHVzIiwgIklkZWEiKSkKICAgICAgICAgICAgIyBDb2xvciBi"
    "eSBzdGF0dXMKICAgICAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgICAgICJJZGVhIjogICAgICAgICAgICAg"
    "Q19URVhUX0RJTSwKICAgICAgICAgICAgICAgICJEZXNpZ25pbmciOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgICAg"
    "ICJSZWFkeSB0byBCdWlsZCI6ICAgQ19QVVJQTEUsCiAgICAgICAgICAgICAgICAiUGFydGlhbCI6ICAgICAgICAgICIjY2M4ODQ0"
    "IiwKICAgICAgICAgICAgICAgICJCdWlsdCI6ICAgICAgICAgICAgQ19HUkVFTiwKICAgICAgICAgICAgfQogICAgICAgICAgICBz"
    "dGF0dXNfaXRlbS5zZXRGb3JlZ3JvdW5kKAogICAgICAgICAgICAgICAgUUNvbG9yKHN0YXR1c19jb2xvcnMuZ2V0KHJlYy5nZXQo"
    "InN0YXR1cyIsIklkZWEiKSwgQ19URVhUX0RJTSkpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRl"
    "bShyLCAxLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAg"
    "UVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsICIiKVs6ODBdKSkKICAgICAgICBjb3VudHMgPSB7fQogICAg"
    "ICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgcyA9IHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikKICAg"
    "ICAgICAgICAgY291bnRzW3NdID0gY291bnRzLmdldChzLCAwKSArIDEKICAgICAgICBjb3VudF9zdHIgPSAiICAiLmpvaW4oZiJ7"
    "c306IHtufSIgZm9yIHMsIG4gaW4gY291bnRzLml0ZW1zKCkpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFRleHQoCiAgICAg"
    "ICAgICAgIGYiVG90YWw6IHtsZW4oc2VsZi5fcmVjb3Jkcyl9ICAge2NvdW50X3N0cn0iCiAgICAgICAgKQoKICAgIGRlZiBfb25f"
    "c2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8"
    "PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAg"
    "ICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsICIiKSkKCiAgICBkZWYgX2RvX2FkZChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coKQoKICAgIGRlZiBfZG9fZWRpdChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYu"
    "X3JlY29yZHMpOgogICAgICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKHNlbGYuX3JlY29yZHNbcm93XSwgcm93KQoKICAg"
    "IGRlZiBfb3Blbl9lZGl0X2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lLCByb3c6IGludCA9IC0xKSAtPiBOb25lOgogICAg"
    "ICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZHVsZSIgaWYgbm90IHJlYyBlbHNl"
    "IGYiRWRpdDoge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1NDAsIDQ0MCkKICAgICAgICBmb3JtID0gUVZCb3hM"
    "YXlvdXQoZGxnKQoKICAgICAgICBuYW1lX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5hbWUiLCIiKSBpZiByZWMgZWxzZSAi"
    "IikKICAgICAgICBuYW1lX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiTW9kdWxlIG5hbWUiKQoKICAgICAgICBzdGF0dXNfY29t"
    "Ym8gPSBRQ29tYm9Cb3goKQogICAgICAgIHN0YXR1c19jb21iby5hZGRJdGVtcyhzZWxmLlNUQVRVU0VTKQogICAgICAgIGlmIHJl"
    "YzoKICAgICAgICAgICAgaWR4ID0gc3RhdHVzX2NvbWJvLmZpbmRUZXh0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSkKICAgICAg"
    "ICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzdGF0dXNfY29tYm8uc2V0Q3VycmVudEluZGV4KGlkeCkKCiAgICAg"
    "ICAgZGVzY19maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAg"
    "IGRlc2NfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJPbmUtbGluZSBkZXNjcmlwdGlvbiIpCgogICAgICAgIG5vdGVzX2ZpZWxk"
    "ID0gUVRleHRFZGl0KCkKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMg"
    "ZWxzZSAiIikKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJGdWxsIG5vdGVzIOKA"
    "lCBzcGVjLCBpZGVhcywgcmVxdWlyZW1lbnRzLCBlZGdlIGNhc2VzLi4uIgogICAgICAgICkKICAgICAgICBub3Rlc19maWVsZC5z"
    "ZXRNaW5pbXVtSGVpZ2h0KDIwMCkKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIk5hbWU6Iiwg"
    "bmFtZV9maWVsZCksCiAgICAgICAgICAgICgiU3RhdHVzOiIsIHN0YXR1c19jb21ibyksCiAgICAgICAgICAgICgiRGVzY3JpcHRp"
    "b246IiwgZGVzY19maWVsZCksCiAgICAgICAgICAgICgiTm90ZXM6Iiwgbm90ZXNfZmllbGQpLAogICAgICAgIF06CiAgICAgICAg"
    "ICAgIHJvd19sYXlvdXQgPSBRSEJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICAgICAg"
    "bGJsLnNldEZpeGVkV2lkdGgoOTApCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgcm93"
    "X2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgICAgICBmb3JtLmFkZExheW91dChyb3dfbGF5b3V0KQoKICAgICAgICBi"
    "dG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlICAgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgYnRu"
    "X2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0"
    "KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQo"
    "YnRuX3NhdmUpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBmb3JtLmFkZExheW91dChidG5f"
    "cm93KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbmV3"
    "X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHJlYy5nZXQoImlkIiwgc3RyKHV1aWQudXVpZDQoKSkpIGlm"
    "IHJlYyBlbHNlIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZV9maWVsZC50ZXh0"
    "KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgIHN0YXR1c19jb21iby5jdXJyZW50VGV4dCgpLAogICAg"
    "ICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzY19maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3Rl"
    "cyI6ICAgICAgIG5vdGVzX2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJjcmVhdGVkIjogICAg"
    "IHJlYy5nZXQoImNyZWF0ZWQiLCBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSkgaWYgcmVjIGVsc2UgZGF0ZXRpbWUubm93KCku"
    "aXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAg"
    "ICAgICAgICAgfQogICAgICAgICAgICBpZiByb3cgPj0gMDoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XSA9IG5l"
    "d19yZWMKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAg"
    "ICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgbmFtZSA9IHNlbGYuX3JlY29yZHNbcm93"
    "XS5nZXQoIm5hbWUiLCJ0aGlzIG1vZHVsZSIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAg"
    "ICAgICAgICAgICBzZWxmLCAiRGVsZXRlIE1vZHVsZSIsCiAgICAgICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gQ2Fubm90"
    "IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgICAgICB3cml0ZV9q"
    "c29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBv"
    "cnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAg"
    "IHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9y"
    "dF9kaXIgLyBmIm1vZHVsZXNfe3RzfS50eHQiCiAgICAgICAgICAgIGxpbmVzID0gWwogICAgICAgICAgICAgICAgIkVDSE8gREVD"
    "SyDigJQgTU9EVUxFIFRSQUNLRVIgRVhQT1JUIiwKICAgICAgICAgICAgICAgIGYiRXhwb3J0ZWQ6IHtkYXRldGltZS5ub3coKS5z"
    "dHJmdGltZSgnJVktJW0tJWQgJUg6JU06JVMnKX0iLAogICAgICAgICAgICAgICAgZiJUb3RhbCBtb2R1bGVzOiB7bGVuKHNlbGYu"
    "X3JlY29yZHMpfSIsCiAgICAgICAgICAgICAgICAiPSIgKiA2MCwKICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICBdCiAg"
    "ICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgICAgIGxpbmVzLmV4dGVuZChbCiAgICAgICAg"
    "ICAgICAgICAgICAgZiJNT0RVTEU6IHtyZWMuZ2V0KCduYW1lJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIlN0YXR1czog"
    "e3JlYy5nZXQoJ3N0YXR1cycsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJEZXNjcmlwdGlvbjoge3JlYy5nZXQoJ2Rlc2Ny"
    "aXB0aW9uJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiTm90ZXM6IiwKICAgICAg"
    "ICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAg"
    "ICAgICItIiAqIDQwLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgXSkKICAgICAgICAgICAgb3V0X3Bh"
    "dGgud3JpdGVfdGV4dCgiXG4iLmpvaW4obGluZXMpLCBlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICBRQXBwbGljYXRpb24u"
    "Y2xpcGJvYXJkKCkuc2V0VGV4dCgiXG4iLmpvaW4obGluZXMpKQogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigK"
    "ICAgICAgICAgICAgICAgIHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICBmIk1vZHVsZSB0cmFja2VyIGV4cG9ydGVk"
    "IHRvOlxue291dF9wYXRofVxuXG5BbHNvIGNvcGllZCB0byBjbGlwYm9hcmQuIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKHNlbGYsICJFeHBvcnQgRXJyb3IiLCBzdHIo"
    "ZSkpCgoKCiAgICBkZWYgX3BhcnNlX2ltcG9ydF9lbnRyaWVzKHNlbGYsIHJhdzogc3RyKSAtPiBsaXN0W2RpY3RdOgogICAgICAg"
    "ICIiIlBhcnNlIGltcG9ydGVkIHRleHQgaW50byBvbmUgb3IgbW9yZSBtb2R1bGUgcmVjb3Jkcy4iIiIKICAgICAgICBsYWJlbF9t"
    "YXAgPSB7CiAgICAgICAgICAgICJtb2R1bGUiOiAibmFtZSIsCiAgICAgICAgICAgICJzdGF0dXMiOiAic3RhdHVzIiwKICAgICAg"
    "ICAgICAgImRlc2NyaXB0aW9uIjogImRlc2NyaXB0aW9uIiwKICAgICAgICAgICAgIm5vdGVzIjogIm5vdGVzIiwKICAgICAgICAg"
    "ICAgImZ1bGwgc3VtbWFyeSI6ICJub3RlcyIsCiAgICAgICAgfQoKICAgICAgICBkZWYgX2JsYW5rKCkgLT4gZGljdDoKICAgICAg"
    "ICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJuYW1lIjogIiIsCiAgICAgICAgICAgICAgICAic3RhdHVzIjogIklkZWEi"
    "LAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAg"
    "ICAgfQoKICAgICAgICBkZWYgX2NsZWFuKHJlYzogZGljdCkgLT4gZGljdDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAg"
    "ICAgICAgICJuYW1lIjogcmVjLmdldCgibmFtZSIsICIiKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6IChyZWMu"
    "Z2V0KCJzdGF0dXMiLCAiIikuc3RyaXAoKSBvciAiSWRlYSIpLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogcmVjLmdl"
    "dCgiZGVzY3JpcHRpb24iLCAiIikuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3RlcyI6IHJlYy5nZXQoIm5vdGVzIiwgIiIp"
    "LnN0cmlwKCksCiAgICAgICAgICAgIH0KCiAgICAgICAgZGVmIF9pc19leHBvcnRfaGVhZGVyKGxpbmU6IHN0cikgLT4gYm9vbDoK"
    "ICAgICAgICAgICAgbG93ID0gbGluZS5zdHJpcCgpLmxvd2VyKCkKICAgICAgICAgICAgcmV0dXJuICgKICAgICAgICAgICAgICAg"
    "IGxvdy5zdGFydHN3aXRoKCJlY2hvIGRlY2siKSBvcgogICAgICAgICAgICAgICAgbG93LnN0YXJ0c3dpdGgoImV4cG9ydGVkOiIp"
    "IG9yCiAgICAgICAgICAgICAgICBsb3cuc3RhcnRzd2l0aCgidG90YWwgbW9kdWxlczoiKSBvcgogICAgICAgICAgICAgICAgbG93"
    "LnN0YXJ0c3dpdGgoInRvdGFsICIpCiAgICAgICAgICAgICkKCiAgICAgICAgZGVmIF9pc19kZWNvcmF0aXZlKGxpbmU6IHN0cikg"
    "LT4gYm9vbDoKICAgICAgICAgICAgcyA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgczoKICAgICAgICAgICAgICAg"
    "IHJldHVybiBGYWxzZQogICAgICAgICAgICBpZiBhbGwoY2ggaW4gIi09fl8q4oCiwrfigJQgIiBmb3IgY2ggaW4gcyk6CiAgICAg"
    "ICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiAocy5zdGFydHN3aXRoKCI9PT0iKSBhbmQgcy5lbmRzd2l0aCgi"
    "PT09IikpIG9yIChzLnN0YXJ0c3dpdGgoIi0tLSIpIGFuZCBzLmVuZHN3aXRoKCItLS0iKSk6CiAgICAgICAgICAgICAgICByZXR1"
    "cm4gVHJ1ZQogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAgICAgZGVmIF9pc19zZXBhcmF0b3IobGluZTogc3RyKSAtPiBi"
    "b29sOgogICAgICAgICAgICBzID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgIHJldHVybiBsZW4ocykgPj0gOCBhbmQgYWxsKGNo"
    "IGluICIt4oCUIiBmb3IgY2ggaW4gcykKCiAgICAgICAgZW50cmllczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgY3VycmVudCA9"
    "IF9ibGFuaygpCiAgICAgICAgY3VycmVudF9maWVsZDogT3B0aW9uYWxbc3RyXSA9IE5vbmUKCiAgICAgICAgZGVmIF9oYXNfcGF5"
    "bG9hZChyZWM6IGRpY3QpIC0+IGJvb2w6CiAgICAgICAgICAgIHJldHVybiBhbnkoYm9vbCgocmVjLmdldChrLCAiIikgb3IgIiIp"
    "LnN0cmlwKCkpIGZvciBrIGluICgibmFtZSIsICJzdGF0dXMiLCAiZGVzY3JpcHRpb24iLCAibm90ZXMiKSkKCiAgICAgICAgZGVm"
    "IF9mbHVzaCgpIC0+IE5vbmU6CiAgICAgICAgICAgIG5vbmxvY2FsIGN1cnJlbnQsIGN1cnJlbnRfZmllbGQKICAgICAgICAgICAg"
    "Y2xlYW5lZCA9IF9jbGVhbihjdXJyZW50KQogICAgICAgICAgICBpZiBjbGVhbmVkWyJuYW1lIl06CiAgICAgICAgICAgICAgICBl"
    "bnRyaWVzLmFwcGVuZChjbGVhbmVkKQogICAgICAgICAgICBjdXJyZW50ID0gX2JsYW5rKCkKICAgICAgICAgICAgY3VycmVudF9m"
    "aWVsZCA9IE5vbmUKCiAgICAgICAgZm9yIHJhd19saW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgICAgIGxpbmUgPSBy"
    "YXdfbGluZS5yc3RyaXAoIlxuIikKICAgICAgICAgICAgc3RyaXBwZWQgPSBsaW5lLnN0cmlwKCkKCiAgICAgICAgICAgIGlmIF9p"
    "c19zZXBhcmF0b3Ioc3RyaXBwZWQpOgogICAgICAgICAgICAgICAgaWYgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAg"
    "ICAgICAgICAgIF9mbHVzaCgpCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgbm90IHN0cmlwcGVkOgog"
    "ICAgICAgICAgICAgICAgaWYgY3VycmVudF9maWVsZCA9PSAibm90ZXMiOgogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRbIm5v"
    "dGVzIl0gPSAoY3VycmVudFsibm90ZXMiXSArICJcbiIpIGlmIGN1cnJlbnRbIm5vdGVzIl0gZWxzZSAiIgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKCiAgICAgICAgICAgIGlmIF9pc19leHBvcnRfaGVhZGVyKHN0cmlwcGVkKToKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCgogICAgICAgICAgICBpZiBfaXNfZGVjb3JhdGl2ZShzdHJpcHBlZCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQoK"
    "ICAgICAgICAgICAgaWYgIjoiIGluIHN0cmlwcGVkOgogICAgICAgICAgICAgICAgbWF5YmVfbGFiZWwsIG1heWJlX3ZhbHVlID0g"
    "c3RyaXBwZWQuc3BsaXQoIjoiLCAxKQogICAgICAgICAgICAgICAga2V5ID0gbWF5YmVfbGFiZWwuc3RyaXAoKS5sb3dlcigpCiAg"
    "ICAgICAgICAgICAgICB2YWx1ZSA9IG1heWJlX3ZhbHVlLmxzdHJpcCgpCgogICAgICAgICAgICAgICAgbWFwcGVkID0gbGFiZWxf"
    "bWFwLmdldChrZXkpCiAgICAgICAgICAgICAgICBpZiBtYXBwZWQ6CiAgICAgICAgICAgICAgICAgICAgaWYgbWFwcGVkID09ICJu"
    "YW1lIiBhbmQgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAgICAgICAgICAgICAgICBfZmx1c2goKQogICAgICAgICAg"
    "ICAgICAgICAgIGN1cnJlbnRfZmllbGQgPSBtYXBwZWQKICAgICAgICAgICAgICAgICAgICBpZiBtYXBwZWQgPT0gIm5vdGVzIjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgY3VycmVudFttYXBwZWRdID0gdmFsdWUKICAgICAgICAgICAgICAgICAgICBlbGlmIG1h"
    "cHBlZCA9PSAic3RhdHVzIjoKICAgICAgICAgICAgICAgICAgICAgICAgY3VycmVudFttYXBwZWRdID0gdmFsdWUgb3IgIklkZWEi"
    "CiAgICAgICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAgICAgY3VycmVudFttYXBwZWRdID0gdmFsdWUK"
    "ICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgICAgICMgVW5rbm93biBsYWJlbGVkIGxpbmVzIGFyZSBt"
    "ZXRhZGF0YS9jYXRlZ29yeS9mb290ZXIgbGluZXMuCiAgICAgICAgICAgICAgICBjdXJyZW50X2ZpZWxkID0gTm9uZQogICAgICAg"
    "ICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGN1cnJlbnRfZmllbGQgPT0gIm5vdGVzIjoKICAgICAgICAgICAgICAg"
    "IGN1cnJlbnRbIm5vdGVzIl0gPSAoY3VycmVudFsibm90ZXMiXSArICJcbiIgKyBzdHJpcHBlZCkgaWYgY3VycmVudFsibm90ZXMi"
    "XSBlbHNlIHN0cmlwcGVkCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgY3VycmVudF9maWVsZCA9PSAi"
    "ZGVzY3JpcHRpb24iOgogICAgICAgICAgICAgICAgY3VycmVudFsiZGVzY3JpcHRpb24iXSA9IChjdXJyZW50WyJkZXNjcmlwdGlv"
    "biJdICsgIlxuIiArIHN0cmlwcGVkKSBpZiBjdXJyZW50WyJkZXNjcmlwdGlvbiJdIGVsc2Ugc3RyaXBwZWQKICAgICAgICAgICAg"
    "ICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIElnbm9yZSB1bmxhYmVsZWQgbGluZXMgb3V0c2lkZSByZWNvZ25pemVkIGZpZWxk"
    "cy4KICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgaWYgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAgICBfZmx1"
    "c2goKQoKICAgICAgICByZXR1cm4gZW50cmllcwoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "SW1wb3J0IG9uZSBvciBtb3JlIG1vZHVsZSBzcGVjcyBmcm9tIHBhc3RlZCB0ZXh0IG9yIGEgVFhUIGZpbGUuIiIiCiAgICAgICAg"
    "ZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1vZHVsZSBTcGVjIikKICAgICAg"
    "ICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5y"
    "ZXNpemUoNTYwLCA0MjApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "UUxhYmVsKAogICAgICAgICAgICAiUGFzdGUgbW9kdWxlIHRleHQgYmVsb3cgb3IgbG9hZCBhIC50eHQgZXhwb3J0LlxuIgogICAg"
    "ICAgICAgICAiU3VwcG9ydHMgTU9EVUxFIFRSQUNLRVIgZXhwb3J0cywgcmVnaXN0cnkgYmxvY2tzLCBhbmQgc2luZ2xlIGxhYmVs"
    "ZWQgc3BlY3MuIgogICAgICAgICkpCgogICAgICAgIHRvb2xfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sb2FkX3R4"
    "dCA9IF9nb3RoaWNfYnRuKCJMb2FkIFRYVCIpCiAgICAgICAgbG9hZGVkX2xibCA9IFFMYWJlbCgiTm8gZmlsZSBsb2FkZWQiKQog"
    "ICAgICAgIGxvYWRlZF9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAg"
    "ICAgICAgdG9vbF9yb3cuYWRkV2lkZ2V0KGJ0bl9sb2FkX3R4dCkKICAgICAgICB0b29sX3Jvdy5hZGRXaWRnZXQobG9hZGVkX2xi"
    "bCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHRvb2xfcm93KQoKICAgICAgICB0ZXh0X2ZpZWxkID0gUVRleHRFZGl0KCkK"
    "ICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiUGFzdGUgbW9kdWxlIHNwZWMocykgaGVyZS4uLiIpCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQoKICAgICAgICBkZWYgX2xvYWRfdHh0X2ludG9fZWRpdG9yKCkgLT4g"
    "Tm9uZToKICAgICAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgICAgIHNl"
    "bGYsCiAgICAgICAgICAgICAgICAiTG9hZCBNb2R1bGUgU3BlY3MiLAogICAgICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJleHBv"
    "cnRzIikpLAogICAgICAgICAgICAgICAgIlRleHQgRmlsZXMgKCoudHh0KTs7QWxsIEZpbGVzICgqKSIsCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgcmF3X3RleHQgPSBQYXRoKHBhdGgpLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKHNlbGYsICJJbXBvcnQgRXJyb3IiLCBm"
    "IkNvdWxkIG5vdCByZWFkIGZpbGU6XG57ZX0iKQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIHRleHRfZmllbGQu"
    "c2V0UGxhaW5UZXh0KHJhd190ZXh0KQogICAgICAgICAgICBsb2FkZWRfbGJsLnNldFRleHQoZiJMb2FkZWQ6IHtQYXRoKHBhdGgp"
    "Lm5hbWV9IikKCiAgICAgICAgYnRuX2xvYWRfdHh0LmNsaWNrZWQuY29ubmVjdChfbG9hZF90eHRfaW50b19lZGl0b3IpCgogICAg"
    "ICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX29rID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAg"
    "YnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2Vw"
    "dCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0"
    "KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRu"
    "X3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJh"
    "dyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgICAgIHBhcnNlZF9lbnRyaWVzID0gc2VsZi5fcGFyc2VfaW1wb3J0X2VudHJpZXMocmF3KQogICAg"
    "ICAgICAgICBpZiBub3QgcGFyc2VkX2VudHJpZXM6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYsCiAgICAgICAgICAgICAgICAgICAgIkltcG9ydCBFcnJvciIsCiAgICAgICAgICAgICAgICAgICAg"
    "Ik5vIHZhbGlkIG1vZHVsZSBlbnRyaWVzIHdlcmUgZm91bmQuIEluY2x1ZGUgYXQgbGVhc3Qgb25lICdNb2R1bGU6JyBvciAnTU9E"
    "VUxFOicgYmxvY2suIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgbm93ID0g"
    "ZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgZm9yIHBhcnNlZCBpbiBwYXJzZWRfZW50cmllczoKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAiaWQiOiBzdHIodXVpZC51dWlkNCgp"
    "KSwKICAgICAgICAgICAgICAgICAgICAibmFtZSI6IHBhcnNlZC5nZXQoIm5hbWUiLCAiIilbOjYwXSwKICAgICAgICAgICAgICAg"
    "ICAgICAic3RhdHVzIjogcGFyc2VkLmdldCgic3RhdHVzIiwgIklkZWEiKSBvciAiSWRlYSIsCiAgICAgICAgICAgICAgICAgICAg"
    "ImRlc2NyaXB0aW9uIjogcGFyc2VkLmdldCgiZGVzY3JpcHRpb24iLCAiIiksCiAgICAgICAgICAgICAgICAgICAgIm5vdGVzIjog"
    "cGFyc2VkLmdldCgibm90ZXMiLCAiIiksCiAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWQiOiBub3csCiAgICAgICAgICAgICAg"
    "ICAgICAgIm1vZGlmaWVkIjogbm93LAogICAgICAgICAgICAgICAgfSkKCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3Bh"
    "dGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9y"
    "bWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwKICAgICAgICAgICAgICAgICJJbXBvcnQgQ29tcGxldGUiLAogICAgICAgICAg"
    "ICAgICAgZiJJbXBvcnRlZCB7bGVuKHBhcnNlZF9lbnRyaWVzKX0gbW9kdWxlIGVudHJ7J3knIGlmIGxlbihwYXJzZWRfZW50cmll"
    "cykgPT0gMSBlbHNlICdpZXMnfS4iCiAgICAgICAgICAgICkKCgojIOKUgOKUgCBQQVNTIDUgQ09NUExFVEUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHRhYiBjb250ZW50IGNsYXNzZXMgZGVmaW5lZC4KIyBTTFNjYW5zVGFiOiByZWJ1aWx0"
    "IOKAlCBEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwgdGltZXN0YW1wIHBhcnNlciBmaXhlZCwKIyAgICAgICAgICAgICBjYXJk"
    "L2dyaW1vaXJlIHN0eWxlLCBjb3B5LXRvLWNsaXBib2FyZCBjb250ZXh0IG1lbnUuCiMgU0xDb21tYW5kc1RhYjogZ290aGljIHRh"
    "YmxlLCDip4kgQ29weSBDb21tYW5kIGJ1dHRvbi4KIyBKb2JUcmFja2VyVGFiOiBmdWxsIHJlYnVpbGQg4oCUIG11bHRpLXNlbGVj"
    "dCwgYXJjaGl2ZS9yZXN0b3JlLCBDU1YvVFNWIGV4cG9ydC4KIyBTZWxmVGFiOiBpbm5lciBzYW5jdHVtIGZvciBpZGxlIG5hcnJh"
    "dGl2ZSBhbmQgcmVmbGVjdGlvbiBvdXRwdXQuCiMgRGlhZ25vc3RpY3NUYWI6IHN0cnVjdHVyZWQgbG9nIHdpdGggbGV2ZWwtY29s"
    "b3JlZCBvdXRwdXQuCiMgTGVzc29uc1RhYjogTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGJyb3dzZXIgd2l0aCBhZGQvZGVsZXRlL3Nl"
    "YXJjaC4KIwojIE5leHQ6IFBhc3MgNiDigJQgTWFpbiBXaW5kb3cKIyAoTW9yZ2FubmFEZWNrIGNsYXNzLCBmdWxsIGxheW91dCwg"
    "QVBTY2hlZHVsZXIsIGZpcnN0LXJ1biBmbG93LAojICBkZXBlbmRlbmN5IGJvb3RzdHJhcCwgc2hvcnRjdXQgY3JlYXRpb24sIHN0"
    "YXJ0dXAgc2VxdWVuY2UpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDY6IE1BSU4gV0lORE9XICYg"
    "RU5UUlkgUE9JTlQKIwojIENvbnRhaW5zOgojICAgYm9vdHN0cmFwX2NoZWNrKCkgICAgIOKAlCBkZXBlbmRlbmN5IHZhbGlkYXRp"
    "b24gKyBhdXRvLWluc3RhbGwgYmVmb3JlIFVJCiMgICBGaXJzdFJ1bkRpYWxvZyAgICAgICAg4oCUIG1vZGVsIHBhdGggKyBjb25u"
    "ZWN0aW9uIHR5cGUgc2VsZWN0aW9uCiMgICBKb3VybmFsU2lkZWJhciAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGxlZnQgc2lkZWJh"
    "ciAoc2Vzc2lvbiBicm93c2VyICsgam91cm5hbCkKIyAgIFRvcnBvclBhbmVsICAgICAgICAgICDigJQgQVdBS0UgLyBBVVRPIC8g"
    "U1VTUEVORCBzdGF0ZSB0b2dnbGUKIyAgIE1vcmdhbm5hRGVjayAgICAgICAgICDigJQgbWFpbiB3aW5kb3csIGZ1bGwgbGF5b3V0"
    "LCBhbGwgc2lnbmFsIGNvbm5lY3Rpb25zCiMgICBtYWluKCkgICAgICAgICAgICAgICAg4oCUIGVudHJ5IHBvaW50IHdpdGggYm9v"
    "dHN0cmFwIHNlcXVlbmNlCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgc3VicHJvY2VzcwoKCiMg4pSA4pSAIFBSRS1MQVVOQ0ggREVQ"
    "RU5ERU5DWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBi"
    "b290c3RyYXBfY2hlY2soKSAtPiBOb25lOgogICAgIiIiCiAgICBSdW5zIEJFRk9SRSBRQXBwbGljYXRpb24gaXMgY3JlYXRlZC4K"
    "ICAgIENoZWNrcyBmb3IgUHlTaWRlNiBzZXBhcmF0ZWx5IChjYW4ndCBzaG93IEdVSSB3aXRob3V0IGl0KS4KICAgIEF1dG8taW5z"
    "dGFsbHMgYWxsIG90aGVyIG1pc3Npbmcgbm9uLWNyaXRpY2FsIGRlcHMgdmlhIHBpcC4KICAgIFZhbGlkYXRlcyBpbnN0YWxscyBz"
    "dWNjZWVkZWQuCiAgICBXcml0ZXMgcmVzdWx0cyB0byBhIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiB0byBwaWNr"
    "IHVwLgogICAgIiIiCiAgICAjIOKUgOKUgCBTdGVwIDE6IENoZWNrIFB5U2lkZTYgKGNhbid0IGF1dG8taW5zdGFsbCB3aXRob3V0"
    "IGl0IGFscmVhZHkgcHJlc2VudCkg4pSACiAgICB0cnk6CiAgICAgICAgaW1wb3J0IFB5U2lkZTYgICMgbm9xYQogICAgZXhjZXB0"
    "IEltcG9ydEVycm9yOgogICAgICAgICMgTm8gR1VJIGF2YWlsYWJsZSDigJQgdXNlIFdpbmRvd3MgbmF0aXZlIGRpYWxvZyB2aWEg"
    "Y3R5cGVzCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnQgY3R5cGVzCiAgICAgICAgICAgIGN0eXBlcy53aW5kbGwudXNl"
    "cjMyLk1lc3NhZ2VCb3hXKAogICAgICAgICAgICAgICAgMCwKICAgICAgICAgICAgICAgICJQeVNpZGU2IGlzIHJlcXVpcmVkIGJ1"
    "dCBub3QgaW5zdGFsbGVkLlxuXG4iCiAgICAgICAgICAgICAgICAiT3BlbiBhIHRlcm1pbmFsIGFuZCBydW46XG5cbiIKICAgICAg"
    "ICAgICAgICAgICIgICAgcGlwIGluc3RhbGwgUHlTaWRlNlxuXG4iCiAgICAgICAgICAgICAgICBmIlRoZW4gcmVzdGFydCB7REVD"
    "S19OQU1FfS4iLAogICAgICAgICAgICAgICAgZiJ7REVDS19OQU1FfSDigJQgTWlzc2luZyBEZXBlbmRlbmN5IiwKICAgICAgICAg"
    "ICAgICAgIDB4MTAgICMgTUJfSUNPTkVSUk9SCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBwcmludCgiQ1JJVElDQUw6IFB5U2lkZTYgbm90IGluc3RhbGxlZC4gUnVuOiBwaXAgaW5zdGFsbCBQeVNpZGU2IikKICAg"
    "ICAgICBzeXMuZXhpdCgxKQoKICAgICMg4pSA4pSAIFN0ZXAgMjogQXV0by1pbnN0YWxsIG90aGVyIG1pc3NpbmcgZGVwcyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIF9BVVRPX0lOU1RBTEwgPSBbCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAg"
    "ICAgImFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIpLAogICAgICAg"
    "ICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAg"
    "ICAgICAicHl3aW4zMiIpLAogICAgICAgICgicHN1dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiKSwKICAgICAgICAo"
    "InJlcXVlc3RzIiwgICAgICAgICAgICAgICAgICAicmVxdWVzdHMiKSwKICAgIF0KCiAgICBpbXBvcnQgaW1wb3J0bGliCiAgICBi"
    "b290c3RyYXBfbG9nID0gW10KCiAgICBmb3IgcGlwX25hbWUsIGltcG9ydF9uYW1lIGluIF9BVVRPX0lOU1RBTEw6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgYm9vdHN0cmFw"
    "X2xvZy5hcHBlbmQoZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAg"
    "ICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBtaXNz"
    "aW5nIOKAlCBpbnN0YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3Vs"
    "dCA9IHN1YnByb2Nlc3MucnVuKAogICAgICAgICAgICAgICAgICAgIFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwgInBpcCIsICJpbnN0"
    "YWxsIiwKICAgICAgICAgICAgICAgICAgICAgcGlwX25hbWUsICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRpb24i"
    "XSwKICAgICAgICAgICAgICAgICAgICBjYXB0dXJlX291dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRpbWVvdXQ9MTIwLAogICAgICAg"
    "ICAgICAgICAgICAgIGNyZWF0aW9uZmxhZ3M9Z2V0YXR0cihzdWJwcm9jZXNzLCAiQ1JFQVRFX05PX1dJTkRPVyIsIDApLAogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgcmVzdWx0LnJldHVybmNvZGUgPT0gMDoKICAgICAgICAgICAgICAgICAg"
    "ICAjIFZhbGlkYXRlIGl0IGFjdHVhbGx5IGltcG9ydGVkIG5vdwogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAgICAgICAgICAgIGJv"
    "b3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGlu"
    "c3RhbGxlZCDinJMiCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBleGNlcHQgSW1wb3J0RXJy"
    "b3I6CiAgICAgICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgYXBwZWFyZWQgdG8gIgogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJzdWNjZWVkIGJ1dCBpbXBvcnQgc3RpbGwgZmFpbHMg4oCUIHJlc3RhcnQgbWF5ICIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiYmUgcmVxdWlyZWQuIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbCBmYWlsZWQ6ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJ7cmVzdWx0LnN0ZGVycls6MjAw"
    "XX0iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgc3VicHJvY2Vzcy5UaW1lb3V0RXhwaXJlZDoKICAg"
    "ICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9u"
    "YW1lfSBpbnN0YWxsIHRpbWVkIG91dC4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0g"
    "e3BpcF9uYW1lfSBpbnN0YWxsIGVycm9yOiB7ZX0iCiAgICAgICAgICAgICAgICApCgogICAgIyDilIDilIAgU3RlcCAzOiBXcml0"
    "ZSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICB0cnk6CiAgICAgICAgbG9nX3BhdGggPSBTQ1JJUFRfRElSIC8gImxv"
    "Z3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIHdpdGggbG9nX3BhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIp"
    "IGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoIlxuIi5qb2luKGJvb3RzdHJhcF9sb2cpKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICBwYXNzCgoKIyDilIDilIAgRklSU1QgUlVOIERJQUxPRyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRmly"
    "c3RSdW5EaWFsb2coUURpYWxvZyk6CiAgICAiIiIKICAgIFNob3duIG9uIGZpcnN0IGxhdW5jaCB3aGVuIGNvbmZpZy5qc29uIGRv"
    "ZXNuJ3QgZXhpc3QuCiAgICBDb2xsZWN0cyBtb2RlbCBjb25uZWN0aW9uIHR5cGUgYW5kIHBhdGgva2V5LgogICAgVmFsaWRhdGVz"
    "IGNvbm5lY3Rpb24gYmVmb3JlIGFjY2VwdGluZy4KICAgIFdyaXRlcyBjb25maWcuanNvbiBvbiBzdWNjZXNzLgogICAgQ3JlYXRl"
    "cyBkZXNrdG9wIHNob3J0Y3V0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKGYi4pymIHtERUNLX05BTUUudXBwZXIo"
    "KX0g4oCUIEZJUlNUIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQogICAgICAgIHNlbGYuc2V0"
    "Rml4ZWRTaXplKDUyMCwgNDAwKQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDEwKQoKICAgICAgICB0"
    "aXRsZSA9IFFMYWJlbChmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkcg4pymIikKICAgICAgICB0"
    "aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNHB4OyBmb250"
    "LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFj"
    "aW5nOiAycHg7IgogICAgICAgICkKICAgICAgICB0aXRsZS5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRl"
    "cikKICAgICAgICByb290LmFkZFdpZGdldCh0aXRsZSkKCiAgICAgICAgc3ViID0gUUxhYmVsKAogICAgICAgICAgICBmIkNvbmZp"
    "Z3VyZSB0aGUgdmVzc2VsIGJlZm9yZSB7REVDS19OQU1FfSBtYXkgYXdha2VuLlxuIgogICAgICAgICAgICAiQWxsIHNldHRpbmdz"
    "IGFyZSBzdG9yZWQgbG9jYWxseS4gTm90aGluZyBsZWF2ZXMgdGhpcyBtYWNoaW5lLiIKICAgICAgICApCiAgICAgICAgc3ViLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRBbGlnbm1lbnQo"
    "UXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChzdWIpCgogICAgICAgICMg4pSA4pSA"
    "IENvbm5lY3Rpb24gdHlwZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBBSSBDT05ORUNUSU9OIFRZUEUiKSkKICAgICAgICBzZWxm"
    "Ll90eXBlX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmFkZEl0ZW1zKFsKICAgICAgICAgICAg"
    "IkxvY2FsIG1vZGVsIGZvbGRlciAodHJhbnNmb3JtZXJzKSIsCiAgICAgICAgICAgICJPbGxhbWEgKGxvY2FsIHNlcnZpY2UpIiwK"
    "ICAgICAgICAgICAgIkNsYXVkZSBBUEkgKEFudGhyb3BpYykiLAogICAgICAgICAgICAiT3BlbkFJIEFQSSIsCiAgICAgICAgXSkK"
    "ICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90eXBlX2NoYW5nZSkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90eXBlX2NvbWJvKQoKICAgICAgICAjIOKUgOKUgCBEeW5hbWljIGNvbm5lY3Rp"
    "b24gZmllbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQo"
    "KQoKICAgICAgICAjIFBhZ2UgMDogTG9jYWwgcGF0aAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRSEJveExh"
    "eW91dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoID0g"
    "UUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgciJEOlxB"
    "SVxNb2RlbHNcZG9scGhpbi04YiIKICAgICAgICApCiAgICAgICAgYnRuX2Jyb3dzZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQog"
    "ICAgICAgIGJ0bl9icm93c2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9tb2RlbCkKICAgICAgICBsMC5hZGRXaWRnZXQo"
    "c2VsZi5fbG9jYWxfcGF0aCk7IGwwLmFkZFdpZGdldChidG5fYnJvd3NlKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChw"
    "MCkKCiAgICAgICAgIyBQYWdlIDE6IE9sbGFtYSBtb2RlbCBuYW1lCiAgICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9"
    "IFFIQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29sbGFt"
    "YV9tb2RlbCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVsLnNldFBsYWNlaG9sZGVyVGV4dCgiZG9scGhp"
    "bi0yLjYtN2IiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9vbGxhbWFfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRk"
    "V2lkZ2V0KHAxKQoKICAgICAgICAjIFBhZ2UgMjogQ2xhdWRlIEFQSSBrZXkKICAgICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAg"
    "IGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5f"
    "Y2xhdWRlX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2st"
    "YW50LS4uLiIpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQp"
    "CiAgICAgICAgc2VsZi5fY2xhdWRlX21vZGVsID0gUUxpbmVFZGl0KCJjbGF1ZGUtc29ubmV0LTQtNiIpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX2tleSkKICAgICAgICBs"
    "Mi5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX21vZGVsKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyBQYWdlIDM6IE9wZW5BSQogICAgICAgIHAzID0gUVdpZGdl"
    "dCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAg"
    "ICAgICBzZWxmLl9vYWlfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJzay0uLi4iKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQog"
    "ICAgICAgIHNlbGYuX29haV9tb2RlbCA9IFFMaW5lRWRpdCgiZ3B0LTRvIikKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJB"
    "UEkgS2V5OiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfa2V5KQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwo"
    "Ik1vZGVsOiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lk"
    "Z2V0KHAzKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaykKCiAgICAgICAgIyDilIDilIAgVGVzdCArIHN0YXR1"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICB0"
    "ZXN0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fdGVzdCA9IF9nb3RoaWNfYnRuKCJUZXN0IENvbm5lY3Rp"
    "b24iKQogICAgICAgIHNlbGYuX2J0bl90ZXN0LmNsaWNrZWQuY29ubmVjdChzZWxmLl90ZXN0X2Nvbm5lY3Rpb24pCiAgICAgICAg"
    "c2VsZi5fc3RhdHVzX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9idG5fdGVzdCkK"
    "ICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc3RhdHVzX2xibCwgMSkKICAgICAgICByb290LmFkZExheW91dCh0ZXN0"
    "X3JvdykKCiAgICAgICAgIyDilIDilIAgRmFjZSBQYWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2n"
    "IEZBQ0UgUEFDSyAob3B0aW9uYWwg4oCUIFpJUCBmaWxlKSIpKQogICAgICAgIGZhY2Vfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuX2ZhY2VfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgKICAgICAgICAgICAgZiJCcm93c2UgdG8ge0RFQ0tfTkFNRX0gZmFjZSBwYWNrIFpJUCAob3B0aW9uYWwsIGNhbiBhZGQgbGF0"
    "ZXIpIgogICAgICAgICkKICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "Zm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA2cHggMTBweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9mYWNlID0gX2dvdGhpY19i"
    "dG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2ZhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9mYWNlKQogICAgICAgIGZh"
    "Y2Vfcm93LmFkZFdpZGdldChzZWxmLl9mYWNlX3BhdGgpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lkZ2V0KGJ0bl9mYWNlKQogICAg"
    "ICAgIHJvb3QuYWRkTGF5b3V0KGZhY2Vfcm93KQoKICAgICAgICAjIOKUgOKUgCBTaG9ydGN1dCBvcHRpb24g4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2IgPSBR"
    "Q2hlY2tCb3goCiAgICAgICAgICAgICJDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCAocmVjb21tZW5kZWQpIgogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9zaG9ydGN1dF9jYi5zZXRDaGVja2VkKFRydWUpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc2hvcnRj"
    "dXRfY2IpCgogICAgICAgICMg4pSA4pSAIEJ1dHRvbnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRTdHJldGNoKCkKICAgICAgICBi"
    "dG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4gPSBfZ290aGljX2J0bigi4pymIEJFR0lOIEFX"
    "QUtFTklORyIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGJ0bl9jYW5jZWwgPSBf"
    "Z290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5hY2Nl"
    "cHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRn"
    "ZXQoc2VsZi5fYnRuX2F3YWtlbikKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIHJvb3QuYWRk"
    "TGF5b3V0KGJ0bl9yb3cpCgogICAgZGVmIF9vbl90eXBlX2NoYW5nZShzZWxmLCBpZHg6IGludCkgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkK"
    "ICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQoIiIpCgogICAgZGVmIF9icm93c2VfbW9kZWwoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBwYXRoID0gUUZpbGVEaWFsb2cuZ2V0RXhpc3RpbmdEaXJlY3RvcnkoCiAgICAgICAgICAgIHNlbGYsICJTZWxlY3Qg"
    "TW9kZWwgRm9sZGVyIiwKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHMiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAg"
    "ICAgICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIGRlZiBfYnJvd3NlX2ZhY2Uoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBwYXRoLCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IEZh"
    "Y2UgUGFjayBaSVAiLAogICAgICAgICAgICBzdHIoUGF0aC5ob21lKCkgLyAiRGVza3RvcCIpLAogICAgICAgICAgICAiWklQIEZp"
    "bGVzICgqLnppcCkiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRUZXh0"
    "KHBhdGgpCgogICAgQHByb3BlcnR5CiAgICBkZWYgZmFjZV96aXBfcGF0aChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNl"
    "bGYuX2ZhY2VfcGF0aC50ZXh0KCkuc3RyaXAoKQoKICAgIGRlZiBfdGVzdF9jb25uZWN0aW9uKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCJUZXN0aW5nLi4uIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgUUFwcGxpY2F0aW9uLnByb2Nlc3NFdmVudHMoKQoKICAgICAgICBp"
    "ZHggPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgb2sgID0gRmFsc2UKICAgICAgICBtc2cgPSAiIgoK"
    "ICAgICAgICBpZiBpZHggPT0gMDogICMgTG9jYWwKICAgICAgICAgICAgcGF0aCA9IHNlbGYuX2xvY2FsX3BhdGgudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICAgICAgaWYgcGF0aCBhbmQgUGF0aChwYXRoKS5leGlzdHMoKToKICAgICAgICAgICAgICAgIG9rICA9IFRy"
    "dWUKICAgICAgICAgICAgICAgIG1zZyA9IGYiRm9sZGVyIGZvdW5kLiBNb2RlbCB3aWxsIGxvYWQgb24gc3RhcnR1cC4iCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBtc2cgPSAiRm9sZGVyIG5vdCBmb3VuZC4gQ2hlY2sgdGhlIHBhdGguIgoKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAxOiAgIyBPbGxhbWEKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVxICA9IHVybGxp"
    "Yi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICAgICAgImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiCiAg"
    "ICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9"
    "MykKICAgICAgICAgICAgICAgIG9rICAgPSByZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICAgICAgICAgIG1zZyAgPSAiT2xsYW1h"
    "IGlzIHJ1bm5pbmcg4pyTIiBpZiBvayBlbHNlICJPbGxhbWEgbm90IHJlc3BvbmRpbmcuIgogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBtc2cgPSBmIk9sbGFtYSBub3QgcmVhY2hhYmxlOiB7ZX0iCgogICAgICAgIGVs"
    "aWYgaWR4ID09IDI6ICAjIENsYXVkZQogICAgICAgICAgICBrZXkgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAg"
    "ICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stYW50IikpCiAgICAgICAgICAgIG1zZyA9ICJB"
    "UEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBDbGF1ZGUgQVBJIGtleS4iCgog"
    "ICAgICAgIGVsaWYgaWR4ID09IDM6ICAjIE9wZW5BSQogICAgICAgICAgICBrZXkgPSBzZWxmLl9vYWlfa2V5LnRleHQoKS5zdHJp"
    "cCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stIikpCiAgICAgICAgICAgIG1zZyA9"
    "ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBPcGVuQUkgQVBJIGtleS4i"
    "CgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfQ1JJTVNPTgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0"
    "VGV4dChtc2cpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29s"
    "b3J9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQob2spCgogICAgZGVmIGJ1aWxkX2NvbmZpZyhzZWxmKSAtPiBkaWN0OgogICAgICAg"
    "ICIiIkJ1aWxkIGFuZCByZXR1cm4gdXBkYXRlZCBjb25maWcgZGljdCBmcm9tIGRpYWxvZyBzZWxlY3Rpb25zLiIiIgogICAgICAg"
    "IGNmZyAgICAgPSBfZGVmYXVsdF9jb25maWcoKQogICAgICAgIGlkeCAgICAgPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRl"
    "eCgpCiAgICAgICAgdHlwZXMgICA9IFsibG9jYWwiLCAib2xsYW1hIiwgImNsYXVkZSIsICJvcGVuYWkiXQogICAgICAgIGNmZ1si"
    "bW9kZWwiXVsidHlwZSJdID0gdHlwZXNbaWR4XQoKICAgICAgICBpZiBpZHggPT0gMDoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJd"
    "WyJwYXRoIl0gPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZWxpZiBpZHggPT0gMToKICAgICAgICAg"
    "ICAgY2ZnWyJtb2RlbCJdWyJvbGxhbWFfbW9kZWwiXSA9IHNlbGYuX29sbGFtYV9tb2RlbC50ZXh0KCkuc3RyaXAoKSBvciAiZG9s"
    "cGhpbi0yLjYtN2IiCiAgICAgICAgZWxpZiBpZHggPT0gMjoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9"
    "IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNl"
    "bGYuX2NsYXVkZV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gImNs"
    "YXVkZSIKICAgICAgICBlbGlmIGlkeCA9PSAzOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5f"
    "b2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5fb2FpX21v"
    "ZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAib3BlbmFpIgoKICAgICAg"
    "ICBjZmdbImZpcnN0X3J1biJdID0gRmFsc2UKICAgICAgICByZXR1cm4gY2ZnCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3JlYXRl"
    "X3Nob3J0Y3V0KHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nob3J0Y3V0X2NiLmlzQ2hlY2tlZCgpCgoKIyDi"
    "lIDilIAgSk9VUk5BTCBTSURFQkFSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBKb3VybmFsU2lkZWJhcihRV2lk"
    "Z2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgbGVmdCBzaWRlYmFyIG5leHQgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCiAg"
    "ICBUb3A6IHNlc3Npb24gY29udHJvbHMgKGN1cnJlbnQgc2Vzc2lvbiBuYW1lLCBzYXZlL2xvYWQgYnV0dG9ucywKICAgICAgICAg"
    "YXV0b3NhdmUgaW5kaWNhdG9yKS4KICAgIEJvZHk6IHNjcm9sbGFibGUgc2Vzc2lvbiBsaXN0IOKAlCBkYXRlLCBBSSBuYW1lLCBt"
    "ZXNzYWdlIGNvdW50LgogICAgQ29sbGFwc2VzIGxlZnR3YXJkIHRvIGEgdGhpbiBzdHJpcC4KCiAgICBTaWduYWxzOgogICAgICAg"
    "IHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQoc3RyKSAgIOKAlCBkYXRlIHN0cmluZyBvZiBzZXNzaW9uIHRvIGxvYWQKICAgICAgICBz"
    "ZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCgpICAgICDigJQgcmV0dXJuIHRvIGN1cnJlbnQgc2Vzc2lvbgogICAgIiIiCgogICAgc2Vz"
    "c2lvbl9sb2FkX3JlcXVlc3RlZCAgPSBTaWduYWwoc3RyKQogICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQgPSBTaWduYWwoKQoK"
    "ICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzZXNzaW9uX21ncjogIlNlc3Npb25NYW5hZ2VyIiwgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyID0gc2Vzc2lvbl9tZ3IKICAgICAgICBz"
    "ZWxmLl9leHBhbmRlZCAgICA9IFRydWUKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAg"
    "ICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBVc2UgYSBob3Jpem9udGFsIHJvb3QgbGF5b3V0IOKAlCBj"
    "b250ZW50IG9uIGxlZnQsIHRvZ2dsZSBzdHJpcCBvbiByaWdodAogICAgICAgIHJvb3QgPSBRSEJveExheW91dChzZWxmKQogICAg"
    "ICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAg"
    "ICMg4pSA4pSAIENvbGxhcHNlIHRvZ2dsZSBzdHJpcCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl90b2dnbGVfc3RyaXAgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0Rml4ZWRXaWR0"
    "aCgyMCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBib3JkZXItcmlnaHQ6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICB0c19sYXlv"
    "dXQgPSBRVkJveExheW91dChzZWxmLl90b2dnbGVfc3RyaXApCiAgICAgICAgdHNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCA4LCAwLCA4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0"
    "bi5zZXRGaXhlZFNpemUoMTgsIDE4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIikKICAgICAgICBzZWxm"
    "Ll90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7"
    "Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKICAgICAgICB0c19sYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuX3RvZ2dsZV9idG4pCiAgICAgICAgdHNfbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgICAgICAjIOKUgOKUgCBNYWlu"
    "IGNvbnRlbnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWluaW11bVdpZHRoKDE4"
    "MCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1heGltdW1XaWR0aCgyMjApCiAgICAgICAgY29udGVudF9sYXlvdXQgPSBRVkJv"
    "eExheW91dChzZWxmLl9jb250ZW50KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0"
    "KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBTZWN0aW9uIGxhYmVsCiAgICAgICAgY29u"
    "dGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEpPVVJOQUwiKSkKCiAgICAgICAgIyBDdXJyZW50IHNlc3Np"
    "b24gaW5mbwogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZSA9IFFMYWJlbCgiTmV3IFNlc3Npb24iKQogICAgICAgIHNlbGYuX3Nl"
    "c3Npb25fbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYuX3Nlc3Npb25fbmFtZSkKCiAgICAgICAgIyBTYXZlIC8gTG9hZCByb3cKICAgICAgICBjdHJsX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCLwn5K+IikKICAgICAgICBzZWxmLl9idG5f"
    "c2F2ZS5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldFRvb2xUaXAoIlNhdmUgc2Vzc2lvbiBu"
    "b3ciKQogICAgICAgIHNlbGYuX2J0bl9sb2FkID0gX2dvdGhpY19idG4oIvCfk4IiKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNl"
    "dEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0VG9vbFRpcCgiQnJvd3NlIGFuZCBsb2FkIGEgcGFz"
    "dCBzZXNzaW9uIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3QgPSBRTGFiZWwoIuKXjyIpCiAgICAgICAgc2VsZi5fYXV0b3Nh"
    "dmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA4cHg7IGJv"
    "cmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlwKCJBdXRvc2F2ZSBzdGF0"
    "dXMiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19zYXZlKQogICAgICAgIHNlbGYuX2J0"
    "bl9sb2FkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5f"
    "c2F2ZSkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYuX2F1dG9zYXZlX2RvdCkKICAgICAgICBjdHJsX3Jvdy5hZGRTdHJldGNoKCkKICAgICAgICBjb250ZW50X2xheW91dC5h"
    "ZGRMYXlvdXQoY3RybF9yb3cpCgogICAgICAgICMgSm91cm5hbCBsb2FkZWQgaW5kaWNhdG9yCiAgICAgICAgc2VsZi5fam91cm5h"
    "bF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfUFVSUExFfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAg"
    "ICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRXb3JkV3Jh"
    "cChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9qb3VybmFsX2xibCkKCiAgICAgICAgIyBDbGVh"
    "ciBqb3VybmFsIGJ1dHRvbiAoaGlkZGVuIHdoZW4gbm90IGxvYWRlZCkKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbCA9"
    "IF9nb3RoaWNfYnRuKCLinJcgUmV0dXJuIHRvIFByZXNlbnQiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZp"
    "c2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2NsZWFy"
    "X2pvdXJuYWwpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsKQoKICAgICAg"
    "ICAjIERpdmlkZXIKICAgICAgICBkaXYgPSBRRnJhbWUoKQogICAgICAgIGRpdi5zZXRGcmFtZVNoYXBlKFFGcmFtZS5TaGFwZS5I"
    "TGluZSkKICAgICAgICBkaXYuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBjb250ZW50"
    "X2xheW91dC5hZGRXaWRnZXQoZGl2KQoKICAgICAgICAjIFNlc3Npb24gbGlzdAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVNUIFNFU1NJT05TIikpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0ID0gUUxpc3RX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIK"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICAg"
    "ICBmIlFMaXN0V2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgfX0iCiAgICAgICAg"
    "KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xp"
    "Y2spCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1DbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykK"
    "ICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vzc2lvbl9saXN0LCAxKQoKICAgICAgICAjIEFkZCBjb250"
    "ZW50IGFuZCB0b2dnbGUgc3RyaXAgdG8gdGhlIHJvb3QgaG9yaXpvbnRhbCBsYXlvdXQKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLl9jb250ZW50KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKCiAgICBkZWYgX3RvZ2dsZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fY29u"
    "dGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIiBpZiBz"
    "ZWxmLl9leHBhbmRlZCBlbHNlICLilrYiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHAgPSBzZWxmLnBh"
    "cmVudFdpZGdldCgpCiAgICAgICAgaWYgcCBhbmQgcC5sYXlvdXQoKToKICAgICAgICAgICAgcC5sYXlvdXQoKS5hY3RpdmF0ZSgp"
    "CgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZXNzaW9ucyA9IHNlbGYuX3Nlc3Npb25fbWdyLmxpc3Rf"
    "c2Vzc2lvbnMoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIHMgaW4gc2Vzc2lvbnM6CiAg"
    "ICAgICAgICAgIGRhdGVfc3RyID0gcy5nZXQoImRhdGUiLCIiKQogICAgICAgICAgICBuYW1lICAgICA9IHMuZ2V0KCJuYW1lIiwg"
    "ZGF0ZV9zdHIpWzozMF0KICAgICAgICAgICAgY291bnQgICAgPSBzLmdldCgibWVzc2FnZV9jb3VudCIsIDApCiAgICAgICAgICAg"
    "IGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0oZiJ7ZGF0ZV9zdHJ9XG57bmFtZX0gKHtjb3VudH0gbXNncykiKQogICAgICAgICAgICBp"
    "dGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBkYXRlX3N0cikKICAgICAgICAgICAgaXRlbS5zZXRUb29sVGlw"
    "KGYiRG91YmxlLWNsaWNrIHRvIGxvYWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0iKQogICAgICAgICAgICBzZWxmLl9zZXNzaW9u"
    "X2xpc3QuYWRkSXRlbShpdGVtKQoKICAgIGRlZiBzZXRfc2Vzc2lvbl9uYW1lKHNlbGYsIG5hbWU6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0VGV4dChuYW1lWzo1MF0gb3IgIk5ldyBTZXNzaW9uIikKCiAgICBkZWYgc2V0X2F1"
    "dG9zYXZlX2luZGljYXRvcihzZWxmLCBzYXZlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR1JFRU4gaWYgc2F2ZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAg"
    "ICAgICAgICBmImZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9k"
    "b3Quc2V0VG9vbFRpcCgKICAgICAgICAgICAgIkF1dG9zYXZlZCIgaWYgc2F2ZWQgZWxzZSAiUGVuZGluZyBhdXRvc2F2ZSIKICAg"
    "ICAgICApCgogICAgZGVmIHNldF9qb3VybmFsX2xvYWRlZChzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX2pvdXJuYWxfbGJsLnNldFRleHQoZiLwn5OWIEpvdXJuYWw6IHtkYXRlX3N0cn0iKQogICAgICAgIHNlbGYuX2J0bl9jbGVh"
    "cl9qb3VybmFsLnNldFZpc2libGUoVHJ1ZSkKCiAgICBkZWYgY2xlYXJfam91cm5hbF9pbmRpY2F0b3Ioc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZp"
    "c2libGUoRmFsc2UpCgogICAgZGVmIF9kb19zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9tZ3Iuc2F2"
    "ZSgpCiAgICAgICAgc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKFRydWUpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAg"
    "ICBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLinJMiKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAsIGxhbWJkYTogc2Vs"
    "Zi5fYnRuX3NhdmUuc2V0VGV4dCgi8J+SviIpKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMDAsIGxhbWJkYTogc2VsZi5z"
    "ZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKSkKCiAgICBkZWYgX2RvX2xvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFRy"
    "eSBzZWxlY3RlZCBpdGVtIGZpcnN0CiAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAg"
    "ICAgaWYgbm90IGl0ZW06CiAgICAgICAgICAgICMgSWYgbm90aGluZyBzZWxlY3RlZCwgdHJ5IHRoZSBmaXJzdCBpdGVtCiAgICAg"
    "ICAgICAgIGlmIHNlbGYuX3Nlc3Npb25fbGlzdC5jb3VudCgpID4gMDoKICAgICAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNz"
    "aW9uX2xpc3QuaXRlbSgwKQogICAgICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LnNldEN1cnJlbnRJdGVtKGl0ZW0pCiAg"
    "ICAgICAgaWYgaXRlbToKICAgICAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQog"
    "ICAgICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYgX29uX3Nlc3Npb25f"
    "Y2xpY2soc2VsZiwgaXRlbSkgLT4gTm9uZToKICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNl"
    "clJvbGUpCiAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9kb19jbGVh"
    "cl9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5lbWl0KCkKICAgICAg"
    "ICBzZWxmLmNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKCkKCgojIOKUgOKUgCBUT1JQT1IgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRvcnBvclBhbmVsKFFXaWRnZXQpOgogICAgIiIiCiAgICBUaHJlZS1zdGF0ZSBzdXNw"
    "ZW5zaW9uIHRvZ2dsZTogQVdBS0UgfCBBVVRPIHwgU1VTUEVORAoKICAgIEFXQUtFICDigJQgbW9kZWwgbG9hZGVkLCBhdXRvLXRv"
    "cnBvciBkaXNhYmxlZCwgaWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBBVVRPICAg4oCUIG1vZGVsIGxvYWRlZCwgbW9uaXRvcnMg"
    "VlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3VzdGFpbmVkCiAgICBTVVNQRU5EIOKAlCBtb2RlbCB1bmxvYWRlZCwgc3Rh"
    "eXMgc3VzcGVuZGVkIHVudGlsIG1hbnVhbGx5IGNoYW5nZWQKCiAgICBTaWduYWxzOgogICAgICAgIHN0YXRlX2NoYW5nZWQoc3Ry"
    "KSAg4oCUICJBV0FLRSIgfCAiQVVUTyIgfCAiU1VTUEVORCIKICAgICIiIgoKICAgIHN0YXRlX2NoYW5nZWQgPSBTaWduYWwoc3Ry"
    "KQoKICAgIFNUQVRFUyA9IFsiQVdBS0UiLCAiQVVUTyIsICJTVVNQRU5EIl0KCiAgICBTVEFURV9TVFlMRVMgPSB7CiAgICAgICAg"
    "IkFXQUtFIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19HT0xEfTsg"
    "IgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBib3JkZXItcmFkaXVzOiAycHg7"
    "ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNw"
    "eCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czog"
    "MnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAi"
    "TW9kZWwgYWN0aXZlLiBBdXRvLXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAgIkFVVE8iOiB7CiAgICAgICAg"
    "ICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsgY29sb3I6ICNjYzg4MjI7ICIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAg"
    "ImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAg"
    "ICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3RpdmUuIEF1dG8tc3Vz"
    "cGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAgfSwKICAgICAgICAiU1VTUEVORCI6IHsKICAgICAgICAgICAgImFjdGl2"
    "ZSI6ICAgZiJiYWNrZ3JvdW5kOiB7Q19QVVJQTEVfRElNfTsgY29sb3I6IHtDX1BVUlBMRX07ICIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAg"
    "ICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAg"
    "ICAgICAgICJsYWJlbCI6ICAgIGYi4pqwIHtVSV9TVVNQRU5TSU9OX0xBQkVMLnN0cmlwKCkgaWYgc3RyKFVJX1NVU1BFTlNJT05f"
    "TEFCRUwpLnN0cmlwKCkgZWxzZSAnU3VzcGVuZCd9IiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgZiJNb2RlbCB1bmxvYWRlZC4g"
    "e0RFQ0tfTkFNRX0gc2xlZXBzIHVudGlsIG1hbnVhbGx5IGF3YWtlbmVkLiIsCiAgICAgICAgfSwKICAgIH0KCiAgICBkZWYgX19p"
    "bml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2N1"
    "cnJlbnQgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fYnV0dG9uczogZGljdFtzdHIsIFFQdXNoQnV0dG9uXSA9IHt9CiAgICAgICAg"
    "bGF5b3V0ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgZm9yIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBi"
    "dG4gPSBRUHVzaEJ1dHRvbihzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bImxhYmVsIl0pCiAgICAgICAgICAgIGJ0bi5zZXRUb29s"
    "VGlwKHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsidG9vbHRpcCJdKQogICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWlnaHQoMjIp"
    "CiAgICAgICAgICAgIGJ0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIGNoZWNrZWQsIHM9c3RhdGU6IHNlbGYuX3NldF9zdGF0ZShz"
    "KSkKICAgICAgICAgICAgc2VsZi5fYnV0dG9uc1tzdGF0ZV0gPSBidG4KICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChidG4p"
    "CgogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCgogICAgZGVmIF9zZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9jdXJy"
    "ZW50ID0gc3RhdGUKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQogICAgICAgIHNlbGYuc3RhdGVfY2hhbmdlZC5lbWl0KHN0"
    "YXRlKQoKICAgIGRlZiBfYXBwbHlfc3R5bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIHN0YXRlLCBidG4gaW4gc2VsZi5f"
    "YnV0dG9ucy5pdGVtcygpOgogICAgICAgICAgICBzdHlsZV9rZXkgPSAiYWN0aXZlIiBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50"
    "IGVsc2UgImluYWN0aXZlIgogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bc3R5"
    "bGVfa2V5XSkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJyZW50X3N0YXRlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4g"
    "c2VsZi5fY3VycmVudAoKICAgIGRlZiBzZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQg"
    "c3RhdGUgcHJvZ3JhbW1hdGljYWxseSAoZS5nLiBmcm9tIGF1dG8tdG9ycG9yIGRldGVjdGlvbikuIiIiCiAgICAgICAgaWYgc3Rh"
    "dGUgaW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0ZShzdGF0ZSkKCgpjbGFzcyBTZXR0aW5nc1NlY3Rp"
    "b24oUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgY29sbGFwc2libGUgc2VjdGlvbiB1c2VkIGJ5IFNldHRpbmdzVGFiLiIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCB0aXRsZTogc3RyLCBwYXJlbnQ9Tm9uZSwgZXhwYW5kZWQ6IGJvb2wgPSBUcnVlKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IGV4cGFuZGVkCgogICAgICAgIHJvb3Qg"
    "PSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9v"
    "dC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX2hlYWRlcl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5faGVh"
    "ZGVyX2J0bi5zZXRUZXh0KGYi4pa8IHt0aXRsZX0iIGlmIGV4cGFuZGVkIGVsc2UgZiLilrYge3RpdGxlfSIpCiAgICAgICAgc2Vs"
    "Zi5faGVhZGVyX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19H"
    "T0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNnB4OyB0ZXh0"
    "LWFsaWduOiBsZWZ0OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2Nv"
    "bnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDgpCiAgICAg"
    "ICAgc2VsZi5fY29udGVudC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci10b3A6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNl"
    "dFZpc2libGUoZXhwYW5kZWQpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcl9idG4pCiAgICAgICAgcm9vdC5h"
    "ZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjb250ZW50X2xheW91dChzZWxmKSAtPiBRVkJv"
    "eExheW91dDoKICAgICAgICByZXR1cm4gc2VsZi5fY29udGVudF9sYXlvdXQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRU"
    "ZXh0KAogICAgICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnRleHQoKS5yZXBsYWNlKCLilrwiLCAi4pa2IiwgMSkKICAgICAgICAg"
    "ICAgaWYgbm90IHNlbGYuX2V4cGFuZGVkIGVsc2UKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVwbGFjZSgi"
    "4pa2IiwgIuKWvCIsIDEpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkK"
    "CgpjbGFzcyBTZXR0aW5nc1RhYihRV2lkZ2V0KToKICAgICIiIkRlY2std2lkZSBydW50aW1lIHNldHRpbmdzIHRhYi4iIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgZGVja193aW5kb3c6ICJFY2hvRGVjayIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kZWNrID0gZGVja193aW5kb3cKICAgICAgICBzZWxmLl9zZWN0aW9uX3Jl"
    "Z2lzdHJ5OiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHM6IGRpY3Rbc3RyLCBTZXR0aW5nc1Nl"
    "Y3Rpb25dID0ge30KCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdp"
    "bnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQog"
    "ICAgICAgIHNjcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJh"
    "clBvbGljeShRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNjcm9sbC5zZXRTdHlsZVNoZWV0"
    "KGYiYmFja2dyb3VuZDoge0NfQkd9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICByb290LmFk"
    "ZFdpZGdldChzY3JvbGwpCgogICAgICAgIGJvZHkgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9ib2R5X2xheW91dCA9IFFWQm94"
    "TGF5b3V0KGJvZHkpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAg"
    "ICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNjcm9sbC5zZXRXaWRnZXQoYm9keSkKCiAgICAgICAg"
    "c2VsZi5fcmVnaXN0ZXJfY29yZV9zZWN0aW9ucygpCgogICAgZGVmIF9yZWdpc3Rlcl9zZWN0aW9uKHNlbGYsICosIHNlY3Rpb25f"
    "aWQ6IHN0ciwgdGl0bGU6IHN0ciwgY2F0ZWdvcnk6IHN0ciwgc291cmNlX293bmVyOiBzdHIsIHNvcnRfa2V5OiBpbnQsIGJ1aWxk"
    "ZXIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeS5hcHBlbmQoewogICAgICAgICAgICAic2VjdGlvbl9p"
    "ZCI6IHNlY3Rpb25faWQsCiAgICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiBjYXRlZ29y"
    "eSwKICAgICAgICAgICAgInNvdXJjZV9vd25lciI6IHNvdXJjZV9vd25lciwKICAgICAgICAgICAgInNvcnRfa2V5Ijogc29ydF9r"
    "ZXksCiAgICAgICAgICAgICJidWlsZGVyIjogYnVpbGRlciwKICAgICAgICB9KQoKICAgIGRlZiBfcmVnaXN0ZXJfY29yZV9zZWN0"
    "aW9ucyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9"
    "InN5c3RlbV9zZXR0aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJTeXN0ZW0gU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29y"
    "eT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MTAw"
    "LAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3N5c3RlbV9zZWN0aW9uLAogICAgICAgICkKICAgICAgICBzZWxmLl9y"
    "ZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJpbnRlZ3JhdGlvbl9zZXR0aW5ncyIsCiAgICAgICAgICAg"
    "IHRpdGxlPSJJbnRlZ3JhdGlvbiBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVnb3J5PSJjb3JlIiwKICAgICAgICAgICAgc291"
    "cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAgICAgICAgICBzb3J0X2tleT0yMDAsCiAgICAgICAgICAgIGJ1aWxkZXI9c2Vs"
    "Zi5fYnVpbGRfaW50ZWdyYXRpb25fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlvbigKICAg"
    "ICAgICAgICAgc2VjdGlvbl9pZD0idWlfc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iVUkgU2V0dGluZ3MiLAogICAgICAg"
    "ICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAg"
    "c29ydF9rZXk9MzAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3VpX3NlY3Rpb24sCiAgICAgICAgKQoKICAgICAg"
    "ICBmb3IgbWV0YSBpbiBzb3J0ZWQoc2VsZi5fc2VjdGlvbl9yZWdpc3RyeSwga2V5PWxhbWJkYSBtOiBtLmdldCgic29ydF9rZXki"
    "LCA5OTk5KSk6CiAgICAgICAgICAgIHNlY3Rpb24gPSBTZXR0aW5nc1NlY3Rpb24obWV0YVsidGl0bGUiXSwgZXhwYW5kZWQ9VHJ1"
    "ZSkKICAgICAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb24pCiAgICAgICAgICAgIHNlbGYuX3NlY3Rp"
    "b25fd2lkZ2V0c1ttZXRhWyJzZWN0aW9uX2lkIl1dID0gc2VjdGlvbgogICAgICAgICAgICBtZXRhWyJidWlsZGVyIl0oc2VjdGlv"
    "bi5jb250ZW50X2xheW91dCkKCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgIGRlZiBfYnVpbGRf"
    "c3lzdGVtX3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9kZWNrLl90"
    "b3Jwb3JfcGFuZWwgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJPcGVyYXRpb25hbCBN"
    "b2RlIikpCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsKQoKICAgICAgICBsYXlv"
    "dXQuYWRkV2lkZ2V0KFFMYWJlbCgiSWRsZSIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5faWRsZV9idG4p"
    "CgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB0el9hdXRvID0gYm9vbChzZXR0aW5n"
    "cy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICAgICAgdHpfb3ZlcnJpZGUgPSBzdHIoc2V0dGluZ3MuZ2V0"
    "KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3RyaXAoKQoKICAgICAgICB0el9hdXRvX2NoayA9IFFDaGVja0JveCgi"
    "QXV0by1kZXRlY3QgbG9jYWwvc3lzdGVtIHRpbWUgem9uZSIpCiAgICAgICAgdHpfYXV0b19jaGsuc2V0Q2hlY2tlZCh0el9hdXRv"
    "KQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfdGltZXpvbmVfYXV0b19kZXRlY3Qp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0el9hdXRvX2NoaykKCiAgICAgICAgdHpfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHR6X3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJNYW51YWwgVGltZSBab25lIE92ZXJyaWRlOiIpKQogICAgICAgIHR6X2NvbWJv"
    "ID0gUUNvbWJvQm94KCkKICAgICAgICB0el9jb21iby5zZXRFZGl0YWJsZShUcnVlKQogICAgICAgIHR6X29wdGlvbnMgPSBbCiAg"
    "ICAgICAgICAgICJBbWVyaWNhL0NoaWNhZ28iLCAiQW1lcmljYS9OZXdfWW9yayIsICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAg"
    "ICAgICAgICAgIkFtZXJpY2EvRGVudmVyIiwgIlVUQyIKICAgICAgICBdCiAgICAgICAgdHpfY29tYm8uYWRkSXRlbXModHpfb3B0"
    "aW9ucykKICAgICAgICBpZiB0el9vdmVycmlkZToKICAgICAgICAgICAgaWYgdHpfY29tYm8uZmluZFRleHQodHpfb3ZlcnJpZGUp"
    "IDwgMDoKICAgICAgICAgICAgICAgIHR6X2NvbWJvLmFkZEl0ZW0odHpfb3ZlcnJpZGUpCiAgICAgICAgICAgIHR6X2NvbWJvLnNl"
    "dEN1cnJlbnRUZXh0KHR6X292ZXJyaWRlKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0"
    "KCJBbWVyaWNhL0NoaWNhZ28iKQogICAgICAgIHR6X2NvbWJvLnNldEVuYWJsZWQobm90IHR6X2F1dG8pCiAgICAgICAgdHpfY29t"
    "Ym8uY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X3RpbWV6b25lX292ZXJyaWRlKQogICAgICAgIHR6"
    "X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChsYW1iZGEgZW5hYmxlZDogdHpfY29tYm8uc2V0RW5hYmxlZChub3QgZW5hYmxlZCkp"
    "CiAgICAgICAgdHpfcm93LmFkZFdpZGdldCh0el9jb21ibywgMSkKICAgICAgICB0el9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAg"
    "dHpfaG9zdC5zZXRMYXlvdXQodHpfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodHpfaG9zdCkKCiAgICBkZWYgX2J1aWxk"
    "X2ludGVncmF0aW9uX3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBzZXR0aW5ncyA9"
    "IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgZW1haWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJl"
    "bWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCgoKICAgICAgICBlbWFpbF9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgZW1haWxfcm93LmFkZFdpZGdldChRTGFiZWwoIkVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgKG1pbnV0ZXMp"
    "OiIpKQogICAgICAgIGVtYWlsX2JveCA9IFFDb21ib0JveCgpCiAgICAgICAgZW1haWxfYm94LnNldEVkaXRhYmxlKFRydWUpCiAg"
    "ICAgICAgZW1haWxfYm94LmFkZEl0ZW1zKFsiMSIsICI1IiwgIjEwIiwgIjE1IiwgIjMwIiwgIjYwIl0pCiAgICAgICAgZW1haWxf"
    "Ym94LnNldEN1cnJlbnRUZXh0KHN0cihlbWFpbF9taW51dGVzKSkKICAgICAgICBlbWFpbF9ib3guY3VycmVudFRleHRDaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQpCiAgICAgICAgZW1haWxfcm93"
    "LmFkZFdpZGdldChlbWFpbF9ib3gsIDEpCiAgICAgICAgZW1haWxfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIGVtYWlsX2hvc3Qu"
    "c2V0TGF5b3V0KGVtYWlsX3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGVtYWlsX2hvc3QpCgogICAgICAgIG5vdGUgPSBR"
    "TGFiZWwoIkVtYWlsIHBvbGxpbmcgZm91bmRhdGlvbiBpcyBjb25maWd1cmF0aW9uLW9ubHkgdW5sZXNzIGFuIGVtYWlsIGJhY2tl"
    "bmQgaXMgZW5hYmxlZC4iKQogICAgICAgIG5vdGUuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZTogOXB4OyIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChub3RlKQoKICAgIGRlZiBfYnVpbGRfdWlfc2VjdGlvbihzZWxmLCBs"
    "YXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJXaW5kb3cgU2hlbGwi"
    "KSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2ZzX2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2RlY2suX2JsX2J0bikKCgpjbGFzcyBEaWNlR2x5cGgoUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgMkQgc2lsaG91ZXR0ZSBy"
    "ZW5kZXJlciBmb3IgZGllLXR5cGUgcmVjb2duaXRpb24uIiIiCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGllX3R5cGU6IHN0ciA9"
    "ICJkMjAiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGllX3R5"
    "cGUgPSBkaWVfdHlwZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoNzAsIDcwKQogICAgICAgIHNlbGYuc2V0TWF4aW11bVNp"
    "emUoOTAsIDkwKQoKICAgIGRlZiBzZXRfZGllX3R5cGUoc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9kaWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50"
    "KToKICAgICAgICBwYWludGVyID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwYWludGVyLnNldFJlbmRlckhpbnQoUVBhaW50ZXIu"
    "UmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgcmVjdCA9IHNlbGYucmVjdCgpLmFkanVzdGVkKDgsIDgsIC04LCAtOCkK"
    "CiAgICAgICAgZGllID0gc2VsZi5fZGllX3R5cGUKICAgICAgICBsaW5lID0gUUNvbG9yKENfR09MRCkKICAgICAgICBmaWxsID0g"
    "UUNvbG9yKENfQkcyKQogICAgICAgIGFjY2VudCA9IFFDb2xvcihDX0NSSU1TT04pCgogICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQ"
    "ZW4obGluZSwgMikpCiAgICAgICAgcGFpbnRlci5zZXRCcnVzaChmaWxsKQoKICAgICAgICBwdHMgPSBbXQogICAgICAgIGlmIGRp"
    "ZSA9PSAiZDQiOgogICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJl"
    "Y3QudG9wKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAg"
    "ICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgPT0g"
    "ImQ2IjoKICAgICAgICAgICAgcGFpbnRlci5kcmF3Um91bmRlZFJlY3QocmVjdCwgNCwgNCkKICAgICAgICBlbGlmIGRpZSA9PSAi"
    "ZDgiOgogICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9w"
    "KCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAg"
    "ICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qucmln"
    "aHQoKSwgcmVjdC5jZW50ZXIoKS55KCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgaW4gKCJkMTAiLCAiZDEwMCIp"
    "OgogICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkp"
    "LAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAgICAg"
    "IFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5ib3R0b20oKSAtIDEyKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRl"
    "cigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmJvdHRvbSgp"
    "IC0gMTIpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDgsIHJlY3QudG9wKCkgKyAxNiksCiAgICAgICAg"
    "ICAgIF0KICAgICAgICBlbGlmIGRpZSA9PSAiZDEyIjoKICAgICAgICAgICAgY3ggPSByZWN0LmNlbnRlcigpLngoKTsgY3kgPSBy"
    "ZWN0LmNlbnRlcigpLnkoKQogICAgICAgICAgICByeCA9IHJlY3Qud2lkdGgoKSAvIDI7IHJ5ID0gcmVjdC5oZWlnaHQoKSAvIDIK"
    "ICAgICAgICAgICAgZm9yIGkgaW4gcmFuZ2UoNSk6CiAgICAgICAgICAgICAgICBhID0gKG1hdGgucGkgKiAyICogaSAvIDUpIC0g"
    "KG1hdGgucGkgLyAyKQogICAgICAgICAgICAgICAgcHRzLmFwcGVuZChRUG9pbnQoaW50KGN4ICsgcnggKiBtYXRoLmNvcyhhKSks"
    "IGludChjeSArIHJ5ICogbWF0aC5zaW4oYSkpKSkKICAgICAgICBlbHNlOiAgIyBkMjAKICAgICAgICAgICAgcHRzID0gWwogICAg"
    "ICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChy"
    "ZWN0LmxlZnQoKSArIDEwLCByZWN0LnRvcCgpICsgMTQpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0"
    "LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyAxMCwgcmVjdC5ib3R0b20oKSAtIDE0"
    "KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAg"
    "ICBRUG9pbnQocmVjdC5yaWdodCgpIC0gMTAsIHJlY3QuYm90dG9tKCkgLSAxNCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVj"
    "dC5yaWdodCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gMTAsIHJl"
    "Y3QudG9wKCkgKyAxNCksCiAgICAgICAgICAgIF0KCiAgICAgICAgaWYgcHRzOgogICAgICAgICAgICBwYXRoID0gUVBhaW50ZXJQ"
    "YXRoKCkKICAgICAgICAgICAgcGF0aC5tb3ZlVG8ocHRzWzBdKQogICAgICAgICAgICBmb3IgcCBpbiBwdHNbMTpdOgogICAgICAg"
    "ICAgICAgICAgcGF0aC5saW5lVG8ocCkKICAgICAgICAgICAgcGF0aC5jbG9zZVN1YnBhdGgoKQogICAgICAgICAgICBwYWludGVy"
    "LmRyYXdQYXRoKHBhdGgpCgogICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQZW4oYWNjZW50LCAxKSkKICAgICAgICB0eHQgPSAiJSIg"
    "aWYgZGllID09ICJkMTAwIiBlbHNlIGRpZS5yZXBsYWNlKCJkIiwgIiIpCiAgICAgICAgcGFpbnRlci5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgMTIsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBwYWludGVyLmRyYXdUZXh0KHJlY3QsIFF0LkFsaWdubWVu"
    "dEZsYWcuQWxpZ25DZW50ZXIsIHR4dCkKCgpjbGFzcyBEaWNlVHJheURpZShRRnJhbWUpOgogICAgc2luZ2xlQ2xpY2tlZCA9IFNp"
    "Z25hbChzdHIpCiAgICBkb3VibGVDbGlja2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGllX3R5cGU6"
    "IHN0ciwgZGlzcGxheV9sYWJlbDogc3RyLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5kaWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi5kaXNwbGF5X2xhYmVsID0gZGlzcGxheV9sYWJlbAog"
    "ICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc2V0U2luZ2xl"
    "U2hvdChUcnVlKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnNldEludGVydmFsKDIyMCkKICAgICAgICBzZWxmLl9jbGlja190"
    "aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fZW1pdF9zaW5nbGUpCgogICAgICAgIHNlbGYuc2V0T2JqZWN0TmFtZSgiRGljZVRy"
    "YXlEaWUiKQogICAgICAgIHNlbGYuc2V0Q3Vyc29yKFF0LkN1cnNvclNoYXBlLlBvaW50aW5nSGFuZEN1cnNvcikKICAgICAgICBz"
    "ZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUZyYW1lI0RpY2VUcmF5RGllIHt7IGJhY2tncm91bmQ6IHtDX0JHM307"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDhweDsgfX0iCiAgICAgICAgICAgIGYiUUZyYW1l"
    "I0RpY2VUcmF5RGllOmhvdmVyIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyB9fSIKICAgICAgICApCgogICAgICAgIGxh"
    "eSA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIGxh"
    "eS5zZXRTcGFjaW5nKDIpCgogICAgICAgIGdseXBoX2RpZSA9ICJkMTAwIiBpZiBkaWVfdHlwZSA9PSAiZCUiIGVsc2UgZGllX3R5"
    "cGUKICAgICAgICBzZWxmLmdseXBoID0gRGljZUdseXBoKGdseXBoX2RpZSkKICAgICAgICBzZWxmLmdseXBoLnNldEZpeGVkU2l6"
    "ZSg1NCwgNTQpCiAgICAgICAgc2VsZi5nbHlwaC5zZXRBdHRyaWJ1dGUoUXQuV2lkZ2V0QXR0cmlidXRlLldBX1RyYW5zcGFyZW50"
    "Rm9yTW91c2VFdmVudHMsIFRydWUpCgogICAgICAgIHNlbGYubGJsID0gUUxhYmVsKGRpc3BsYXlfbGFiZWwpCiAgICAgICAgc2Vs"
    "Zi5sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5sYmwuc2V0U3R5bGVT"
    "aGVldChmImNvbG9yOiB7Q19URVhUfTsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBzZWxmLmxibC5zZXRBdHRyaWJ1dGUo"
    "UXQuV2lkZ2V0QXR0cmlidXRlLldBX1RyYW5zcGFyZW50Rm9yTW91c2VFdmVudHMsIFRydWUpCgogICAgICAgIGxheS5hZGRXaWRn"
    "ZXQoc2VsZi5nbHlwaCwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYu"
    "bGJsKQoKICAgIGRlZiBtb3VzZVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIGlmIGV2ZW50LmJ1dHRvbigpID09IFF0"
    "Lk1vdXNlQnV0dG9uLkxlZnRCdXR0b246CiAgICAgICAgICAgIGlmIHNlbGYuX2NsaWNrX3RpbWVyLmlzQWN0aXZlKCk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9jbGlja190aW1lci5zdG9wKCkKICAgICAgICAgICAgICAgIHNlbGYuZG91YmxlQ2xpY2tlZC5lbWl0"
    "KHNlbGYuZGllX3R5cGUpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9jbGlja190aW1lci5zdGFydCgp"
    "CiAgICAgICAgICAgIGV2ZW50LmFjY2VwdCgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHN1cGVyKCkubW91c2VQcmVzc0V2"
    "ZW50KGV2ZW50KQoKICAgIGRlZiBfZW1pdF9zaW5nbGUoc2VsZik6CiAgICAgICAgc2VsZi5zaW5nbGVDbGlja2VkLmVtaXQoc2Vs"
    "Zi5kaWVfdHlwZSkKCgpjbGFzcyBEaWNlUm9sbGVyVGFiKFFXaWRnZXQpOgogICAgIiIiRGVjay1uYXRpdmUgRGljZSBSb2xsZXIg"
    "bW9kdWxlIHRhYiB3aXRoIHRyYXkvcG9vbCB3b3JrZmxvdyBhbmQgc3RydWN0dXJlZCByb2xsIGV2ZW50cy4iIiIKCiAgICBUUkFZ"
    "X09SREVSID0gWyJkNCIsICJkNiIsICJkOCIsICJkMTAiLCAiZDEyIiwgImQyMCIsICJkJSJdCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9sb2cg"
    "PSBkaWFnbm9zdGljc19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKCiAgICAgICAgc2VsZi5yb2xs"
    "X2V2ZW50czogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5zYXZlZF9yb2xsczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAg"
    "c2VsZi5jb21tb25fcm9sbHM6IGRpY3Rbc3RyLCBkaWN0XSA9IHt9CiAgICAgICAgc2VsZi5ldmVudF9ieV9pZDogZGljdFtzdHIs"
    "IGRpY3RdID0ge30KICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbDogZGljdFtzdHIsIGludF0gPSB7fQogICAgICAgIHNlbGYuY3Vy"
    "cmVudF9yb2xsX2lkczogbGlzdFtzdHJdID0gW10KCiAgICAgICAgc2VsZi5ydWxlX2RlZmluaXRpb25zOiBkaWN0W3N0ciwgZGlj"
    "dF0gPSB7CiAgICAgICAgICAgICJydWxlXzRkNl9kcm9wX2xvd2VzdCI6IHsKICAgICAgICAgICAgICAgICJpZCI6ICJydWxlXzRk"
    "Nl9kcm9wX2xvd2VzdCIsCiAgICAgICAgICAgICAgICAibmFtZSI6ICJEJkQgNWUgU3RhdCBSb2xsIiwKICAgICAgICAgICAgICAg"
    "ICJkaWNlX2NvdW50IjogNCwKICAgICAgICAgICAgICAgICJkaWNlX3NpZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xv"
    "d2VzdF9jb3VudCI6IDEsCiAgICAgICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJu"
    "b3RlcyI6ICJSb2xsIDRkNiwgZHJvcCBsb3dlc3Qgb25lLiIKICAgICAgICAgICAgfSwKICAgICAgICAgICAgInJ1bGVfM2Q2X3N0"
    "cmFpZ2h0IjogewogICAgICAgICAgICAgICAgImlkIjogInJ1bGVfM2Q2X3N0cmFpZ2h0IiwKICAgICAgICAgICAgICAgICJuYW1l"
    "IjogIjNkNiBTdHJhaWdodCIsCiAgICAgICAgICAgICAgICAiZGljZV9jb3VudCI6IDMsCiAgICAgICAgICAgICAgICAiZGljZV9z"
    "aWRlcyI6IDYsCiAgICAgICAgICAgICAgICAiZHJvcF9sb3dlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImRyb3BfaGln"
    "aGVzdF9jb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiQ2xhc3NpYyAzZDYgcm9sbC4iCiAgICAgICAgICAgIH0s"
    "CiAgICAgICAgfQoKICAgICAgICBzZWxmLl9idWlsZF91aSgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRyYXlfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgdHJheV93cmFwLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgdHJh"
    "eV9sYXlvdXQgPSBRVkJveExheW91dCh0cmF5X3dyYXApCiAgICAgICAgdHJheV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgs"
    "IDgsIDgsIDgpCiAgICAgICAgdHJheV9sYXlvdXQuc2V0U3BhY2luZyg2KQogICAgICAgIHRyYXlfbGF5b3V0LmFkZFdpZGdldChR"
    "TGFiZWwoIkRpY2UgVHJheSIpKQoKICAgICAgICB0cmF5X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0cmF5X3Jvdy5zZXRT"
    "cGFjaW5nKDYpCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIGJsb2NrID0gRGljZVRyYXlE"
    "aWUoZGllLCBkaWUpCiAgICAgICAgICAgIGJsb2NrLnNpbmdsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9hZGRfZGllX3RvX3Bvb2wp"
    "CiAgICAgICAgICAgIGJsb2NrLmRvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9xdWlja19yb2xsX3NpbmdsZV9kaWUpCiAgICAg"
    "ICAgICAgIHRyYXlfcm93LmFkZFdpZGdldChibG9jaywgMSkKICAgICAgICB0cmF5X2xheW91dC5hZGRMYXlvdXQodHJheV9yb3cp"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQodHJheV93cmFwKQoKICAgICAgICBwb29sX3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHBv"
    "b2xfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsi"
    "KQogICAgICAgIHB3ID0gUVZCb3hMYXlvdXQocG9vbF93cmFwKQogICAgICAgIHB3LnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4"
    "LCA4KQogICAgICAgIHB3LnNldFNwYWNpbmcoNikKCiAgICAgICAgcHcuYWRkV2lkZ2V0KFFMYWJlbCgiQ3VycmVudCBQb29sIikp"
    "CiAgICAgICAgc2VsZi5wb29sX2V4cHJfbGJsID0gUUxhYmVsKCJQb29sOiAoZW1wdHkpIikKICAgICAgICBzZWxmLnBvb2xfZXhw"
    "cl9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBwdy5hZGRX"
    "aWRnZXQoc2VsZi5wb29sX2V4cHJfbGJsKQoKICAgICAgICBzZWxmLnBvb2xfZW50cmllc193aWRnZXQgPSBRV2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQgPSBRSEJveExheW91dChzZWxmLnBvb2xfZW50cmllc193aWRnZXQpCiAgICAg"
    "ICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucG9v"
    "bF9lbnRyaWVzX2xheW91dC5zZXRTcGFjaW5nKDYpCiAgICAgICAgcHcuYWRkV2lkZ2V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdl"
    "dCkKCiAgICAgICAgbWV0YV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0ID0gUUxpbmVFZGl0KCk7"
    "IHNlbGYubGFiZWxfZWRpdC5zZXRQbGFjZWhvbGRlclRleHQoIkxhYmVsIC8gcHVycG9zZSIpCiAgICAgICAgc2VsZi5tb2Rfc3Bp"
    "biA9IFFTcGluQm94KCk7IHNlbGYubW9kX3NwaW4uc2V0UmFuZ2UoLTk5OSwgOTk5KTsgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZSgw"
    "KQogICAgICAgIHNlbGYucnVsZV9jb21ibyA9IFFDb21ib0JveCgpOyBzZWxmLnJ1bGVfY29tYm8uYWRkSXRlbSgiTWFudWFsIFJv"
    "bGwiLCAiIikKICAgICAgICBmb3IgcmlkLCBtZXRhIGluIHNlbGYucnVsZV9kZWZpbml0aW9ucy5pdGVtcygpOgogICAgICAgICAg"
    "ICBzZWxmLnJ1bGVfY29tYm8uYWRkSXRlbShtZXRhLmdldCgibmFtZSIsIHJpZCksIHJpZCkKCiAgICAgICAgZm9yIHRpdGxlLCB3"
    "IGluICgoIkxhYmVsIiwgc2VsZi5sYWJlbF9lZGl0KSwgKCJNb2RpZmllciIsIHNlbGYubW9kX3NwaW4pLCAoIlJ1bGUiLCBzZWxm"
    "LnJ1bGVfY29tYm8pKToKICAgICAgICAgICAgY29sID0gUVZCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGl0"
    "bGUpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikK"
    "ICAgICAgICAgICAgY29sLmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIGNvbC5hZGRXaWRnZXQodykKICAgICAgICAgICAgbWV0"
    "YV9yb3cuYWRkTGF5b3V0KGNvbCwgMSkKICAgICAgICBwdy5hZGRMYXlvdXQobWV0YV9yb3cpCgogICAgICAgIGFjdGlvbnMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgc2VsZi5yb2xsX3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlJvbGwgUG9vbCIpCiAgICAgICAg"
    "c2VsZi5yZXNldF9wb29sX2J0biA9IFFQdXNoQnV0dG9uKCJSZXNldCBQb29sIikKICAgICAgICBzZWxmLnNhdmVfcG9vbF9idG4g"
    "PSBRUHVzaEJ1dHRvbigiU2F2ZSBQb29sIikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJvbGxfcG9vbF9idG4pCiAg"
    "ICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5yZXNldF9wb29sX2J0bikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxm"
    "LnNhdmVfcG9vbF9idG4pCiAgICAgICAgcHcuYWRkTGF5b3V0KGFjdGlvbnMpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHBvb2xf"
    "d3JhcCkKCiAgICAgICAgcmVzdWx0X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHJlc3VsdF93cmFwLnNldFN0eWxlU2hlZXQoZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgcmwgPSBRVkJveExheW91"
    "dChyZXN1bHRfd3JhcCkKICAgICAgICBybC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBybC5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJDdXJyZW50IFJlc3VsdCIpKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsID0gUUxhYmVsKCJObyBy"
    "b2xsIHlldC4iKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgcmwuYWRk"
    "V2lkZ2V0KHNlbGYuY3VycmVudF9yZXN1bHRfbGJsKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHJlc3VsdF93cmFwKQoKICAgICAg"
    "ICBtaWQgPSBRSEJveExheW91dCgpCiAgICAgICAgaGlzdG9yeV93cmFwID0gUUZyYW1lKCkKICAgICAgICBoaXN0b3J5X3dyYXAu"
    "c2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAg"
    "ICBodyA9IFFWQm94TGF5b3V0KGhpc3Rvcnlfd3JhcCkKICAgICAgICBody5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikK"
    "CiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUgPSBzZWxm"
    "Ll9tYWtlX3JvbGxfdGFibGUoKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90YWJsZSgpCiAg"
    "ICAgICAgc2VsZi5oaXN0b3J5X3RhYnMuYWRkVGFiKHNlbGYuY3VycmVudF90YWJsZSwgIkN1cnJlbnQgUm9sbHMiKQogICAgICAg"
    "IHNlbGYuaGlzdG9yeV90YWJzLmFkZFRhYihzZWxmLmhpc3RvcnlfdGFibGUsICJSb2xsIEhpc3RvcnkiKQogICAgICAgIGh3LmFk"
    "ZFdpZGdldChzZWxmLmhpc3RvcnlfdGFicywgMSkKCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuY2xlYXJfaGlzdG9yeV9idG4gPSBRUHVzaEJ1dHRvbigiQ2xlYXIgUm9sbCBIaXN0b3J5IikKICAgICAgICBoaXN0"
    "b3J5X2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuY2xlYXJfaGlzdG9yeV9idG4pCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zLmFkZFN0"
    "cmV0Y2goMSkKICAgICAgICBody5hZGRMYXlvdXQoaGlzdG9yeV9hY3Rpb25zKQoKICAgICAgICBzZWxmLmdyYW5kX3RvdGFsX2xi"
    "bCA9IFFMYWJlbCgiR3JhbmQgVG90YWw6IDAiKQogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsLnNldFN0eWxlU2hlZXQoZiJj"
    "b2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBody5hZGRXaWRnZXQo"
    "c2VsZi5ncmFuZF90b3RhbF9sYmwpCgogICAgICAgIHNhdmVkX3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHNhdmVkX3dyYXAuc2V0"
    "U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBz"
    "dyA9IFFWQm94TGF5b3V0KHNhdmVkX3dyYXApCiAgICAgICAgc3cuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAg"
    "ICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2F2ZWQgLyBDb21tb24gUm9sbHMiKSkKCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJl"
    "bCgiU2F2ZWQiKSkKICAgICAgICBzZWxmLnNhdmVkX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc3cuYWRkV2lkZ2V0KHNl"
    "bGYuc2F2ZWRfbGlzdCwgMSkKICAgICAgICBzYXZlZF9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucnVuX3Nh"
    "dmVkX2J0biA9IFFQdXNoQnV0dG9uKCJSdW4iKQogICAgICAgIHNlbGYubG9hZF9zYXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiTG9h"
    "ZC9FZGl0IikKICAgICAgICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiRGVsZXRlIikKICAgICAgICBzYXZl"
    "ZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLnJ1bl9zYXZlZF9idG4pCiAgICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2Vs"
    "Zi5sb2FkX3NhdmVkX2J0bikKICAgICAgICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmRlbGV0ZV9zYXZlZF9idG4pCiAg"
    "ICAgICAgc3cuYWRkTGF5b3V0KHNhdmVkX2FjdGlvbnMpCgogICAgICAgIHN3LmFkZFdpZGdldChRTGFiZWwoIkF1dG8tRGV0ZWN0"
    "ZWQgQ29tbW9uIikpCiAgICAgICAgc2VsZi5jb21tb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzdy5hZGRXaWRnZXQo"
    "c2VsZi5jb21tb25fbGlzdCwgMSkKICAgICAgICBjb21tb25fYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnBy"
    "b21vdGVfY29tbW9uX2J0biA9IFFQdXNoQnV0dG9uKCJQcm9tb3RlIHRvIFNhdmVkIikKICAgICAgICBzZWxmLmRpc21pc3NfY29t"
    "bW9uX2J0biA9IFFQdXNoQnV0dG9uKCJEaXNtaXNzIikKICAgICAgICBjb21tb25fYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5wcm9t"
    "b3RlX2NvbW1vbl9idG4pCiAgICAgICAgY29tbW9uX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuZGlzbWlzc19jb21tb25fYnRuKQog"
    "ICAgICAgIHN3LmFkZExheW91dChjb21tb25fYWN0aW9ucykKCiAgICAgICAgc2VsZi5jb21tb25faGludCA9IFFMYWJlbCgiQ29t"
    "bW9uIHNpZ25hdHVyZSB0cmFja2luZyBhY3RpdmUuIikKICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFN0eWxlU2hlZXQoZiJj"
    "b2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9oaW50"
    "KQoKICAgICAgICBtaWQuYWRkV2lkZ2V0KGhpc3Rvcnlfd3JhcCwgMykKICAgICAgICBtaWQuYWRkV2lkZ2V0KHNhdmVkX3dyYXAs"
    "IDIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQobWlkLCAxKQoKICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4uY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX3JvbGxfY3VycmVudF9wb29sKQogICAgICAgIHNlbGYucmVzZXRfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX3Jlc2V0X3Bvb2wpCiAgICAgICAgc2VsZi5zYXZlX3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3Bvb2wp"
    "CiAgICAgICAgc2VsZi5jbGVhcl9oaXN0b3J5X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY2xlYXJfaGlzdG9yeSkKCiAgICAg"
    "ICAgc2VsZi5zYXZlZF9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1bl9zYXZlZF9y"
    "b2xsKGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpKSkKICAgICAgICBzZWxmLmNvbW1vbl9saXN0Lml0ZW1Eb3Vi"
    "bGVDbGlja2VkLmNvbm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJv"
    "bGUuVXNlclJvbGUpKSkKCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9ydW5fc2VsZWN0"
    "ZWRfc2F2ZWQpCiAgICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fbG9hZF9zZWxlY3RlZF9z"
    "YXZlZCkKICAgICAgICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RlbGV0ZV9zZWxlY3RlZF9z"
    "YXZlZCkKICAgICAgICBzZWxmLnByb21vdGVfY29tbW9uX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcHJvbW90ZV9zZWxlY3Rl"
    "ZF9jb21tb24pCiAgICAgICAgc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rpc21pc3Nfc2Vs"
    "ZWN0ZWRfY29tbW9uKQoKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1l"
    "bnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5"
    "KFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5jdXN0b21D"
    "b250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KGxhbWJkYSBwb3M6IHNlbGYuX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5j"
    "dXJyZW50X3RhYmxlLCBwb3MpKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5j"
    "b25uZWN0KGxhbWJkYSBwb3M6IHNlbGYuX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5oaXN0b3J5X3RhYmxlLCBwb3MpKQoK"
    "ICAgIGRlZiBfbWFrZV9yb2xsX3RhYmxlKHNlbGYpIC0+IFFUYWJsZVdpZGdldDoKICAgICAgICB0YmwgPSBRVGFibGVXaWRnZXQo"
    "MCwgNikKICAgICAgICB0Ymwuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIlRpbWVzdGFtcCIsICJMYWJlbCIsICJFeHByZXNz"
    "aW9uIiwgIlJhdyIsICJNb2RpZmllciIsICJUb3RhbCJdKQogICAgICAgIHRibC5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHRibC52ZXJ0aWNhbEhlYWRlcigpLnNl"
    "dFZpc2libGUoRmFsc2UpCiAgICAgICAgdGJsLnNldEVkaXRUcmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5O"
    "b0VkaXRUcmlnZ2VycykKICAgICAgICB0Ymwuc2V0U2VsZWN0aW9uQmVoYXZpb3IoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9u"
    "QmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICB0Ymwuc2V0U29ydGluZ0VuYWJsZWQoRmFsc2UpCiAgICAgICAgcmV0dXJuIHRi"
    "bAoKICAgIGRlZiBfc29ydGVkX3Bvb2xfaXRlbXMoc2VsZik6CiAgICAgICAgcmV0dXJuIFsoZCwgc2VsZi5jdXJyZW50X3Bvb2wu"
    "Z2V0KGQsIDApKSBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVIgaWYgc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGQsIDApID4gMF0KCiAg"
    "ICBkZWYgX3Bvb2xfZXhwcmVzc2lvbihzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSB8IE5vbmUgPSBOb25lKSAtPiBzdHI6CiAg"
    "ICAgICAgcCA9IHBvb2wgaWYgcG9vbCBpcyBub3QgTm9uZSBlbHNlIHNlbGYuY3VycmVudF9wb29sCiAgICAgICAgcGFydHMgPSBb"
    "ZiJ7cXR5fXtkaWV9IiBmb3IgZGllLCBxdHkgaW4gWyhkLCBwLmdldChkLCAwKSkgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVSXSBp"
    "ZiBxdHkgPiAwXQogICAgICAgIHJldHVybiAiICsgIi5qb2luKHBhcnRzKSBpZiBwYXJ0cyBlbHNlICIoZW1wdHkpIgoKICAgIGRl"
    "ZiBfbm9ybWFsaXplX3Bvb2xfc2lnbmF0dXJlKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBpbnRdLCBtb2RpZmllcjogaW50LCBydWxl"
    "X2lkOiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgIHBhcnRzID0gW2Yie3Bvb2wuZ2V0KGQsIDApfXtkfSIgZm9yIGQgaW4gc2Vs"
    "Zi5UUkFZX09SREVSIGlmIHBvb2wuZ2V0KGQsIDApID4gMF0KICAgICAgICBiYXNlID0gIisiLmpvaW4ocGFydHMpIGlmIHBhcnRz"
    "IGVsc2UgIjAiCiAgICAgICAgc2lnID0gZiJ7YmFzZX17bW9kaWZpZXI6K2R9IgogICAgICAgIHJldHVybiBmIntzaWd9X3tydWxl"
    "X2lkfSIgaWYgcnVsZV9pZCBlbHNlIHNpZwoKICAgIGRlZiBfZGljZV9sYWJlbChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBzdHI6"
    "CiAgICAgICAgcmV0dXJuICJkJSIgaWYgZGllX3R5cGUgPT0gImQlIiBlbHNlIGRpZV90eXBlCgogICAgZGVmIF9yb2xsX3Npbmds"
    "ZV92YWx1ZShzZWxmLCBkaWVfdHlwZTogc3RyKToKICAgICAgICBpZiBkaWVfdHlwZSA9PSAiZCUiOgogICAgICAgICAgICB0ZW5z"
    "ID0gcmFuZG9tLnJhbmRpbnQoMCwgOSkgKiAxMAogICAgICAgICAgICByZXR1cm4gdGVucywgKCIwMCIgaWYgdGVucyA9PSAwIGVs"
    "c2Ugc3RyKHRlbnMpKQogICAgICAgIHNpZGVzID0gaW50KGRpZV90eXBlLnJlcGxhY2UoImQiLCAiIikpCiAgICAgICAgdmFsID0g"
    "cmFuZG9tLnJhbmRpbnQoMSwgc2lkZXMpCiAgICAgICAgcmV0dXJuIHZhbCwgc3RyKHZhbCkKCiAgICBkZWYgX3JvbGxfcG9vbF9k"
    "YXRhKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBpbnRdLCBtb2RpZmllcjogaW50LCBsYWJlbDogc3RyLCBydWxlX2lkOiBzdHIgPSAi"
    "IikgLT4gZGljdDoKICAgICAgICBncm91cGVkX251bWVyaWM6IGRpY3Rbc3RyLCBsaXN0W2ludF1dID0ge30KICAgICAgICBncm91"
    "cGVkX2Rpc3BsYXk6IGRpY3Rbc3RyLCBsaXN0W3N0cl1dID0ge30KICAgICAgICBzdWJ0b3RhbCA9IDAKICAgICAgICB1c2VkX3Bv"
    "b2wgPSBkaWN0KHBvb2wpCgogICAgICAgIGlmIHJ1bGVfaWQgYW5kIHJ1bGVfaWQgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zIGFu"
    "ZCAobm90IHBvb2wgb3IgbGVuKFtrIGZvciBrLCB2IGluIHBvb2wuaXRlbXMoKSBpZiB2ID4gMF0pID09IDEpOgogICAgICAgICAg"
    "ICBydWxlID0gc2VsZi5ydWxlX2RlZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkKICAgICAgICAgICAgc2lkZXMgPSBpbnQocnVs"
    "ZS5nZXQoImRpY2Vfc2lkZXMiLCA2KSkKICAgICAgICAgICAgY291bnQgPSBpbnQocnVsZS5nZXQoImRpY2VfY291bnQiLCAxKSkK"
    "ICAgICAgICAgICAgZGllID0gZiJke3NpZGVzfSIKICAgICAgICAgICAgdXNlZF9wb29sID0ge2RpZTogY291bnR9CiAgICAgICAg"
    "ICAgIHJhdyA9IFtyYW5kb20ucmFuZGludCgxLCBzaWRlcykgZm9yIF8gaW4gcmFuZ2UoY291bnQpXQogICAgICAgICAgICBkcm9w"
    "X2xvdyA9IGludChydWxlLmdldCgiZHJvcF9sb3dlc3RfY291bnQiLCAwKSBvciAwKQogICAgICAgICAgICBkcm9wX2hpZ2ggPSBp"
    "bnQocnVsZS5nZXQoImRyb3BfaGlnaGVzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGtlcHQgPSBsaXN0KHJhdykKICAg"
    "ICAgICAgICAgaWYgZHJvcF9sb3cgPiAwOgogICAgICAgICAgICAgICAga2VwdCA9IHNvcnRlZChrZXB0KVtkcm9wX2xvdzpdCiAg"
    "ICAgICAgICAgIGlmIGRyb3BfaGlnaCA+IDA6CiAgICAgICAgICAgICAgICBrZXB0ID0gc29ydGVkKGtlcHQpWzotZHJvcF9oaWdo"
    "XSBpZiBkcm9wX2hpZ2ggPCBsZW4oa2VwdCkgZWxzZSBbXQogICAgICAgICAgICBncm91cGVkX251bWVyaWNbZGllXSA9IHJhdwog"
    "ICAgICAgICAgICBncm91cGVkX2Rpc3BsYXlbZGllXSA9IFtzdHIodikgZm9yIHYgaW4gcmF3XQogICAgICAgICAgICBzdWJ0b3Rh"
    "bCA9IHN1bShrZXB0KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAg"
    "ICAgICAgICAgcXR5ID0gaW50KHBvb2wuZ2V0KGRpZSwgMCkgb3IgMCkKICAgICAgICAgICAgICAgIGlmIHF0eSA8PSAwOgogICAg"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICBncm91cGVkX251bWVyaWNbZGllXSA9IFtdCiAgICAgICAg"
    "ICAgICAgICBncm91cGVkX2Rpc3BsYXlbZGllXSA9IFtdCiAgICAgICAgICAgICAgICBmb3IgXyBpbiByYW5nZShxdHkpOgogICAg"
    "ICAgICAgICAgICAgICAgIG51bSwgZGlzcCA9IHNlbGYuX3JvbGxfc2luZ2xlX3ZhbHVlKGRpZSkKICAgICAgICAgICAgICAgICAg"
    "ICBncm91cGVkX251bWVyaWNbZGllXS5hcHBlbmQobnVtKQogICAgICAgICAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVd"
    "LmFwcGVuZChkaXNwKQogICAgICAgICAgICAgICAgICAgIHN1YnRvdGFsICs9IGludChudW0pCgogICAgICAgIHRvdGFsID0gc3Vi"
    "dG90YWwgKyBpbnQobW9kaWZpZXIpCiAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAg"
    "ICAgIGV4cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Npb24odXNlZF9wb29sKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAgICAgICAgICAg"
    "IHJ1bGVfbmFtZSA9IHNlbGYucnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAg"
    "ICAgICAgICAgIGV4cHIgPSBmIntleHByfSAoe3J1bGVfbmFtZX0pIgoKICAgICAgICBldmVudCA9IHsKICAgICAgICAgICAgImlk"
    "IjogZiJyb2xsX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRzLAogICAgICAgICAg"
    "ICAibGFiZWwiOiBsYWJlbCwKICAgICAgICAgICAgInBvb2wiOiB1c2VkX3Bvb2wsCiAgICAgICAgICAgICJncm91cGVkX3JhdyI6"
    "IGdyb3VwZWRfbnVtZXJpYywKICAgICAgICAgICAgImdyb3VwZWRfcmF3X2Rpc3BsYXkiOiBncm91cGVkX2Rpc3BsYXksCiAgICAg"
    "ICAgICAgICJzdWJ0b3RhbCI6IHN1YnRvdGFsLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQobW9kaWZpZXIpLAogICAgICAg"
    "ICAgICAiZmluYWxfdG90YWwiOiBpbnQodG90YWwpLAogICAgICAgICAgICAiZXhwcmVzc2lvbiI6IGV4cHIsCiAgICAgICAgICAg"
    "ICJzb3VyY2UiOiAiZGljZV9yb2xsZXIiLAogICAgICAgICAgICAicnVsZV9pZCI6IHJ1bGVfaWQgb3IgTm9uZSwKICAgICAgICB9"
    "CiAgICAgICAgcmV0dXJuIGV2ZW50CgogICAgZGVmIF9hZGRfZGllX3RvX3Bvb2woc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbFtkaWVfdHlwZV0gPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90eXBl"
    "LCAwKSkgKyAxCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9s"
    "Ymwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9hZGp1c3RfcG9v"
    "bF9kaWUoc2VsZiwgZGllX3R5cGU6IHN0ciwgZGVsdGE6IGludCkgLT4gTm9uZToKICAgICAgICBuZXdfdmFsID0gaW50KHNlbGYu"
    "Y3VycmVudF9wb29sLmdldChkaWVfdHlwZSwgMCkpICsgaW50KGRlbHRhKQogICAgICAgIGlmIG5ld192YWwgPD0gMDoKICAgICAg"
    "ICAgICAgc2VsZi5jdXJyZW50X3Bvb2wucG9wKGRpZV90eXBlLCBOb25lKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYu"
    "Y3VycmVudF9wb29sW2RpZV90eXBlXSA9IG5ld192YWwKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKCiAgICBk"
    "ZWYgX3JlZnJlc2hfcG9vbF9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICB3aGlsZSBzZWxmLnBvb2xfZW50cmllc19sYXlv"
    "dXQuY291bnQoKToKICAgICAgICAgICAgaXRlbSA9IHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC50YWtlQXQoMCkKICAgICAgICAg"
    "ICAgdyA9IGl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYgdyBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHcuZGVsZXRl"
    "TGF0ZXIoKQoKICAgICAgICBmb3IgZGllLCBxdHkgaW4gc2VsZi5fc29ydGVkX3Bvb2xfaXRlbXMoKToKICAgICAgICAgICAgYm94"
    "ID0gUUZyYW1lKCkKICAgICAgICAgICAgYm94LnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiA2cHg7IikKICAgICAgICAgICAgbGF5ID0gUUhCb3hMYXlvdXQoYm94"
    "KQogICAgICAgICAgICBsYXkuc2V0Q29udGVudHNNYXJnaW5zKDYsIDQsIDYsIDQpCiAgICAgICAgICAgIGxheS5zZXRTcGFjaW5n"
    "KDQpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChmIntkaWV9IHh7cXR5fSIpCiAgICAgICAgICAgIG1pbnVzX2J0biA9IFFQdXNo"
    "QnV0dG9uKCLiiJIiKQogICAgICAgICAgICBwbHVzX2J0biA9IFFQdXNoQnV0dG9uKCIrIikKICAgICAgICAgICAgbWludXNfYnRu"
    "LnNldEZpeGVkV2lkdGgoMjQpCiAgICAgICAgICAgIHBsdXNfYnRuLnNldEZpeGVkV2lkdGgoMjQpCiAgICAgICAgICAgIG1pbnVz"
    "X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9vbF9kaWUoZCwgLTEpKQog"
    "ICAgICAgICAgICBwbHVzX2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9v"
    "bF9kaWUoZCwgKzEpKQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChtaW51"
    "c19idG4pCiAgICAgICAgICAgIGxheS5hZGRXaWRnZXQocGx1c19idG4pCiAgICAgICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xh"
    "eW91dC5hZGRXaWRnZXQoYm94KQoKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuYWRkU3RyZXRjaCgxKQogICAgICAg"
    "IHNlbGYucG9vbF9leHByX2xibC5zZXRUZXh0KGYiUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9x"
    "dWlja19yb2xsX3NpbmdsZV9kaWUoc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBldmVudCA9IHNlbGYuX3Jv"
    "bGxfcG9vbF9kYXRhKHtkaWVfdHlwZTogMX0sIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxhYmVsX2VkaXQudGV4"
    "dCgpLnN0cmlwKCksIHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9yICIiKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xs"
    "X2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfcm9sbF9jdXJyZW50X3Bvb2woc2VsZikgLT4gTm9uZToKICAgICAgICBwb29sID0gZGlj"
    "dChzZWxmLmN1cnJlbnRfcG9vbCkKICAgICAgICBydWxlX2lkID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIiIK"
    "ICAgICAgICBpZiBub3QgcG9vbCBhbmQgbm90IHJ1bGVfaWQ6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNl"
    "bGYsICJEaWNlIFJvbGxlciIsICJDdXJyZW50IFBvb2wgaXMgZW1wdHkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZl"
    "bnQgPSBzZWxmLl9yb2xsX3Bvb2xfZGF0YShwb29sLCBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1ZSgpKSwgc2VsZi5sYWJlbF9lZGl0"
    "LnRleHQoKS5zdHJpcCgpLCBydWxlX2lkKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xsX2V2ZW50KGV2ZW50KQoKICAgIGRlZiBf"
    "cmVjb3JkX3JvbGxfZXZlbnQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5yb2xsX2V2ZW50cy5hcHBl"
    "bmQoZXZlbnQpCiAgICAgICAgc2VsZi5ldmVudF9ieV9pZFtldmVudFsiaWQiXV0gPSBldmVudAogICAgICAgIHNlbGYuY3VycmVu"
    "dF9yb2xsX2lkcyA9IFtldmVudFsiaWQiXV0KCiAgICAgICAgc2VsZi5fcmVwbGFjZV9jdXJyZW50X3Jvd3MoW2V2ZW50XSkKICAg"
    "ICAgICBzZWxmLl9hcHBlbmRfaGlzdG9yeV9yb3coZXZlbnQpCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAg"
    "ICAgICBzZWxmLl91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZlbnQpCiAgICAgICAgc2VsZi5fdHJhY2tfY29tbW9uX3NpZ25hdHVy"
    "ZShldmVudCkKICAgICAgICBzZWxmLl9wbGF5X3JvbGxfc291bmQoKQoKICAgIGRlZiBfcmVwbGFjZV9jdXJyZW50X3Jvd3Moc2Vs"
    "ZiwgZXZlbnRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5zZXRSb3dDb3VudCgwKQog"
    "ICAgICAgIGZvciBldmVudCBpbiBldmVudHM6CiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5jdXJyZW50"
    "X3RhYmxlLCBldmVudCkKCiAgICBkZWYgX2FwcGVuZF9oaXN0b3J5X3JvdyhzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9hcHBlbmRfdGFibGVfcm93KHNlbGYuaGlzdG9yeV90YWJsZSwgZXZlbnQpCiAgICAgICAgc2VsZi5oaXN0b3J5"
    "X3RhYmxlLnNjcm9sbFRvQm90dG9tKCkKCiAgICBkZWYgX2Zvcm1hdF9yYXcoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IHN0cjoKICAg"
    "ICAgICBncm91cGVkID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgYml0cyA9IFtd"
    "CiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAg"
    "ICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAgICAgICAgICBiaXRzLmFwcGVuZChmIntkaWV9OiB7JywnLmpvaW4oc3RyKHYpIGZv"
    "ciB2IGluIHZhbHMpfSIpCiAgICAgICAgcmV0dXJuICIgfCAiLmpvaW4oYml0cykKCiAgICBkZWYgX2FwcGVuZF90YWJsZV9yb3co"
    "c2VsZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gdGFibGUucm93Q291"
    "bnQoKQogICAgICAgIHRhYmxlLmluc2VydFJvdyhyb3cpCgogICAgICAgIHRzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGV2ZW50"
    "WyJ0aW1lc3RhbXAiXSkKICAgICAgICB0c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBldmVudFsiaWQi"
    "XSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMCwgdHNfaXRlbSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRh"
    "YmxlV2lkZ2V0SXRlbShldmVudC5nZXQoImxhYmVsIiwgIiIpKSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxl"
    "V2lkZ2V0SXRlbShldmVudC5nZXQoImV4cHJlc3Npb24iLCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFi"
    "bGVXaWRnZXRJdGVtKHNlbGYuX2Zvcm1hdF9yYXcoZXZlbnQpKSkKCiAgICAgICAgbW9kX3NwaW4gPSBRU3BpbkJveCgpCiAgICAg"
    "ICAgbW9kX3NwaW4uc2V0UmFuZ2UoLTk5OSwgOTk5KQogICAgICAgIG1vZF9zcGluLnNldFZhbHVlKGludChldmVudC5nZXQoIm1v"
    "ZGlmaWVyIiwgMCkpKQogICAgICAgIG1vZF9zcGluLnZhbHVlQ2hhbmdlZC5jb25uZWN0KGxhbWJkYSB2YWwsIGVpZD1ldmVudFsi"
    "aWQiXTogc2VsZi5fb25fbW9kaWZpZXJfY2hhbmdlZChlaWQsIHZhbCkpCiAgICAgICAgdGFibGUuc2V0Q2VsbFdpZGdldChyb3cs"
    "IDQsIG1vZF9zcGluKQoKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwgUVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2V0"
    "KCJmaW5hbF90b3RhbCIsIDApKSkpCgogICAgZGVmIF9zeW5jX3Jvd19ieV9ldmVudF9pZChzZWxmLCB0YWJsZTogUVRhYmxlV2lk"
    "Z2V0LCBldmVudF9pZDogc3RyLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBmb3Igcm93IGluIHJhbmdlKHRhYmxlLnJv"
    "d0NvdW50KCkpOgogICAgICAgICAgICBpdCA9IHRhYmxlLml0ZW0ocm93LCAwKQogICAgICAgICAgICBpZiBpdCBhbmQgaXQuZGF0"
    "YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpID09IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgdGFibGUuc2V0SXRlbShyb3cs"
    "IDUsIFFUYWJsZVdpZGdldEl0ZW0oc3RyKGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwKSkpKQogICAgICAgICAgICAgICAgdGFi"
    "bGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQogICAgICAgICAgICAg"
    "ICAgYnJlYWsKCiAgICBkZWYgX29uX21vZGlmaWVyX2NoYW5nZWQoc2VsZiwgZXZlbnRfaWQ6IHN0ciwgdmFsdWU6IGludCkgLT4g"
    "Tm9uZToKICAgICAgICBldnQgPSBzZWxmLmV2ZW50X2J5X2lkLmdldChldmVudF9pZCkKICAgICAgICBpZiBub3QgZXZ0OgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBldnRbIm1vZGlmaWVyIl0gPSBpbnQodmFsdWUpCiAgICAgICAgZXZ0WyJmaW5hbF90b3Rh"
    "bCJdID0gaW50KGV2dC5nZXQoInN1YnRvdGFsIiwgMCkpICsgaW50KHZhbHVlKQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5X2V2"
    "ZW50X2lkKHNlbGYuaGlzdG9yeV90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgICAgICBzZWxmLl9zeW5jX3Jvd19ieV9ldmVudF9p"
    "ZChzZWxmLmN1cnJlbnRfdGFibGUsIGV2ZW50X2lkLCBldnQpCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAg"
    "ICAgICBpZiBzZWxmLmN1cnJlbnRfcm9sbF9pZHMgYW5kIHNlbGYuY3VycmVudF9yb2xsX2lkc1swXSA9PSBldmVudF9pZDoKICAg"
    "ICAgICAgICAgc2VsZi5fdXBkYXRlX3Jlc3VsdF9kaXNwbGF5KGV2dCkKCiAgICBkZWYgX3VwZGF0ZV9ncmFuZF90b3RhbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHRvdGFsID0gc3VtKGludChldnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSBmb3IgZXZ0IGluIHNl"
    "bGYucm9sbF9ldmVudHMpCiAgICAgICAgc2VsZi5ncmFuZF90b3RhbF9sYmwuc2V0VGV4dChmIkdyYW5kIFRvdGFsOiB7dG90YWx9"
    "IikKCiAgICBkZWYgX3VwZGF0ZV9yZXN1bHRfZGlzcGxheShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBncm91"
    "cGVkID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgbGluZXMgPSBbXQogICAgICAg"
    "IGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAg"
    "ICBpZiB2YWxzOgogICAgICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYie2RpZX0geHtsZW4odmFscyl9IOKGkiBbeycsJy5qb2lu"
    "KHN0cih2KSBmb3IgdiBpbiB2YWxzKX1dIikKICAgICAgICBydWxlX2lkID0gZXZlbnQuZ2V0KCJydWxlX2lkIikKICAgICAgICBp"
    "ZiBydWxlX2lkOgogICAgICAgICAgICBydWxlX25hbWUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KS5n"
    "ZXQoIm5hbWUiLCBydWxlX2lkKQogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJSdWxlOiB7cnVsZV9uYW1lfSIpCiAgICAgICAg"
    "bGluZXMuYXBwZW5kKGYiTW9kaWZpZXI6IHtpbnQoZXZlbnQuZ2V0KCdtb2RpZmllcicsIDApKTorZH0iKQogICAgICAgIGxpbmVz"
    "LmFwcGVuZChmIlRvdGFsOiB7ZXZlbnQuZ2V0KCdmaW5hbF90b3RhbCcsIDApfSIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3Vs"
    "dF9sYmwuc2V0VGV4dCgiXG4iLmpvaW4obGluZXMpKQoKCiAgICBkZWYgX3NhdmVfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGlmIG5vdCBzZWxmLmN1cnJlbnRfcG9vbDoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2Ug"
    "Um9sbGVyIiwgIkJ1aWxkIGEgQ3VycmVudCBQb29sIGJlZm9yZSBzYXZpbmcuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "ZGVmYXVsdF9uYW1lID0gc2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJpcCgpIG9yIHNlbGYuX3Bvb2xfZXhwcmVzc2lvbigpCiAg"
    "ICAgICAgbmFtZSwgb2sgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiU2F2ZSBQb29sIiwgIlNhdmVkIHJvbGwgbmFtZToi"
    "LCB0ZXh0PWRlZmF1bHRfbmFtZSkKICAgICAgICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBheWxvYWQg"
    "PSB7CiAgICAgICAgICAgICJpZCI6IGYic2F2ZWRfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAibmFtZSI6"
    "IG5hbWUuc3RyaXAoKSBvciBkZWZhdWx0X25hbWUsCiAgICAgICAgICAgICJwb29sIjogZGljdChzZWxmLmN1cnJlbnRfcG9vbCks"
    "CiAgICAgICAgICAgICJtb2RpZmllciI6IGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLAogICAgICAgICAgICAicnVsZV9pZCI6"
    "IHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9yIE5vbmUsCiAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAgICAgICAg"
    "ICAiY2F0ZWdvcnkiOiAic2F2ZWQiLAogICAgICAgIH0KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLmFwcGVuZChwYXlsb2FkKQog"
    "ICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcmVmcmVzaF9zYXZlZF9saXN0cyhzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2VsZi5zYXZlZF9yb2xsczoK"
    "ICAgICAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkKICAgICAgICAgICAg"
    "dHh0ID0gZiJ7aXRlbS5nZXQoJ25hbWUnKX0g4oCUIHtleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZmllcicsIDApKTorZH0iCiAg"
    "ICAgICAgICAgIGx3ID0gUUxpc3RXaWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUu"
    "VXNlclJvbGUsIGl0ZW0pCiAgICAgICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5hZGRJdGVtKGx3KQoKICAgICAgICBzZWxmLmNvbW1v"
    "bl9saXN0LmNsZWFyKCkKICAgICAgICByYW5rZWQgPSBzb3J0ZWQoc2VsZi5jb21tb25fcm9sbHMudmFsdWVzKCksIGtleT1sYW1i"
    "ZGEgeDogeC5nZXQoImNvdW50IiwgMCksIHJldmVyc2U9VHJ1ZSkKICAgICAgICBmb3IgaXRlbSBpbiByYW5rZWQ6CiAgICAgICAg"
    "ICAgIGlmIGludChpdGVtLmdldCgiY291bnQiLCAwKSkgPCAyOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAg"
    "ZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkKICAgICAgICAgICAgdHh0ID0gZiJ7ZXhw"
    "cn0ge2ludChpdGVtLmdldCgnbW9kaWZpZXInLCAwKSk6K2R9ICh4e2l0ZW0uZ2V0KCdjb3VudCcsIDApfSkiCiAgICAgICAgICAg"
    "IGx3ID0gUUxpc3RXaWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUs"
    "IGl0ZW0pCiAgICAgICAgICAgIHNlbGYuY29tbW9uX2xpc3QuYWRkSXRlbShsdykKCiAgICBkZWYgX3RyYWNrX2NvbW1vbl9zaWdu"
    "YXR1cmUoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2lnID0gc2VsZi5fbm9ybWFsaXplX3Bvb2xfc2lnbmF0"
    "dXJlKGV2ZW50LmdldCgicG9vbCIsIHt9KSwgaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSksIHN0cihldmVudC5nZXQoInJ1"
    "bGVfaWQiKSBvciAiIikpCiAgICAgICAgaWYgc2lnIG5vdCBpbiBzZWxmLmNvbW1vbl9yb2xsczoKICAgICAgICAgICAgc2VsZi5j"
    "b21tb25fcm9sbHNbc2lnXSA9IHsKICAgICAgICAgICAgICAgICJzaWduYXR1cmUiOiBzaWcsCiAgICAgICAgICAgICAgICAiY291"
    "bnQiOiAwLAogICAgICAgICAgICAgICAgIm5hbWUiOiBldmVudC5nZXQoImxhYmVsIiwgIiIpIG9yIHNpZywKICAgICAgICAgICAg"
    "ICAgICJwb29sIjogZGljdChldmVudC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KGV2"
    "ZW50LmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgICAgICAicnVsZV9pZCI6IGV2ZW50LmdldCgicnVsZV9pZCIpLAog"
    "ICAgICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICAgICAiY2F0ZWdvcnkiOiAiY29tbW9uIiwKICAgICAgICAg"
    "ICAgfQogICAgICAgIHNlbGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPSBpbnQoc2VsZi5jb21tb25fcm9sbHNbc2lnXS5n"
    "ZXQoImNvdW50IiwgMCkpICsgMQogICAgICAgIGlmIHNlbGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPj0gMzoKICAgICAg"
    "ICAgICAgc2VsZi5jb21tb25faGludC5zZXRUZXh0KGYiU3VnZ2VzdGlvbjogcHJvbW90ZSB7c2VsZi5fcG9vbF9leHByZXNzaW9u"
    "KGV2ZW50LmdldCgncG9vbCcsIHt9KSl9IHRvIFNhdmVkLiIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgog"
    "ICAgZGVmIF9ydW5fc2F2ZWRfcm9sbChzZWxmLCBwYXlsb2FkOiBkaWN0IHwgTm9uZSk6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEoCiAgICAgICAgICAgIGRpY3Qo"
    "cGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICBpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAg"
    "ICAgICAgICBzdHIocGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpLnN0cmlwKCksCiAgICAgICAgICAgIHN0cihwYXlsb2FkLmdldCgi"
    "cnVsZV9pZCIpIG9yICIiKSwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVm"
    "IF9sb2FkX3BheWxvYWRfaW50b19wb29sKHNlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKSAtPiBOb25lOgogICAgICAgIGlmIG5v"
    "dCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbCA9IGRpY3QocGF5bG9hZC5nZXQo"
    "InBvb2wiLCB7fSkpCiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZShpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkp"
    "KQogICAgICAgIHNlbGYubGFiZWxfZWRpdC5zZXRUZXh0KHN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgcmlk"
    "ID0gcGF5bG9hZC5nZXQoInJ1bGVfaWQiKQogICAgICAgIGlkeCA9IHNlbGYucnVsZV9jb21iby5maW5kRGF0YShyaWQgb3IgIiIp"
    "CiAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgIHNlbGYucnVsZV9jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoZiJD"
    "dXJyZW50IFBvb2w6IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0iKQoKICAgIGRlZiBfcnVuX3NlbGVjdGVkX3NhdmVkKHNlbGYp"
    "OgogICAgICAgIGl0ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHNlbGYuX3J1bl9zYXZlZF9yb2xs"
    "KGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBOb25lKQoKICAgIGRlZiBfbG9hZF9zZWxl"
    "Y3RlZF9zYXZlZChzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXls"
    "b2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3Qg"
    "cGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbG9hZF9wYXlsb2FkX2ludG9fcG9vbChwYXlsb2FkKQoK"
    "ICAgICAgICBuYW1lLCBvayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTmFtZToiLCB0"
    "ZXh0PXN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgaWYgbm90IG9rOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBwYXlsb2FkWyJuYW1lIl0gPSBuYW1lLnN0cmlwKCkgb3IgcGF5bG9hZC5nZXQoIm5hbWUiLCAiIikKICAgICAgICBwYXls"
    "b2FkWyJwb29sIl0gPSBkaWN0KHNlbGYuY3VycmVudF9wb29sKQogICAgICAgIHBheWxvYWRbIm1vZGlmaWVyIl0gPSBpbnQoc2Vs"
    "Zi5tb2Rfc3Bpbi52YWx1ZSgpKQogICAgICAgIHBheWxvYWRbInJ1bGVfaWQiXSA9IHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0"
    "YSgpIG9yIE5vbmUKICAgICAgICBub3Rlcywgb2tfbm90ZXMgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiRWRpdCBTYXZl"
    "ZCBSb2xsIiwgIk5vdGVzIC8gY2F0ZWdvcnk6IiwgdGV4dD1zdHIocGF5bG9hZC5nZXQoIm5vdGVzIiwgIiIpKSkKICAgICAgICBp"
    "ZiBva19ub3RlczoKICAgICAgICAgICAgcGF5bG9hZFsibm90ZXMiXSA9IG5vdGVzCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZl"
    "ZF9saXN0cygpCgogICAgZGVmIF9kZWxldGVfc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgcm93ID0gc2VsZi5zYXZlZF9s"
    "aXN0LmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLnNhdmVkX3JvbGxzKToKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5wb3Aocm93KQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRf"
    "bGlzdHMoKQoKICAgIGRlZiBfcHJvbW90ZV9zZWxlY3RlZF9jb21tb24oc2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuY29tbW9u"
    "X2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBp"
    "ZiBpdGVtIGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBwcm9tb3Rl"
    "ZCA9IHsKICAgICAgICAgICAgImlkIjogZiJzYXZlZF97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1l"
    "IjogcGF5bG9hZC5nZXQoIm5hbWUiKSBvciBzZWxmLl9wb29sX2V4cHJlc3Npb24ocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAog"
    "ICAgICAgICAgICAicG9vbCI6IGRpY3QocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAibW9kaWZpZXIiOiBp"
    "bnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAgICAicnVsZV9pZCI6IHBheWxvYWQuZ2V0KCJydWxlX2lk"
    "IiksCiAgICAgICAgICAgICJub3RlcyI6IHBheWxvYWQuZ2V0KCJub3RlcyIsICIiKSwKICAgICAgICAgICAgImNhdGVnb3J5Ijog"
    "InNhdmVkIiwKICAgICAgICB9CiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5hcHBlbmQocHJvbW90ZWQpCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9kaXNtaXNzX3NlbGVjdGVkX2NvbW1vbihzZWxmKToKICAgICAgICBpdGVt"
    "ID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJv"
    "bGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIHNpZyA9IHBheWxvYWQuZ2V0KCJzaWduYXR1cmUiKQogICAgICAgIGlmIHNpZyBpbiBzZWxmLmNvbW1vbl9yb2xsczoK"
    "ICAgICAgICAgICAgc2VsZi5jb21tb25fcm9sbHMucG9wKHNpZywgTm9uZSkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xp"
    "c3RzKCkKCiAgICBkZWYgX3Jlc2V0X3Bvb2woc2VsZik6CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2wgPSB7fQogICAgICAgIHNl"
    "bGYubW9kX3NwaW4uc2V0VmFsdWUoMCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQuY2xlYXIoKQogICAgICAgIHNlbGYucnVsZV9j"
    "b21iby5zZXRDdXJyZW50SW5kZXgoMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1"
    "cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfY2xlYXJfaGlzdG9yeShzZWxmKToKICAg"
    "ICAgICBzZWxmLnJvbGxfZXZlbnRzLmNsZWFyKCkKICAgICAgICBzZWxmLmV2ZW50X2J5X2lkLmNsZWFyKCkKICAgICAgICBzZWxm"
    "LmN1cnJlbnRfcm9sbF9pZHMgPSBbXQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNl"
    "bGYuY3VycmVudF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuX3VwZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAg"
    "c2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dCgiTm8gcm9sbCB5ZXQuIikKCiAgICBkZWYgX2V2ZW50X2Zyb21fdGFibGVf"
    "cG9zaXRpb24oc2VsZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgcG9zKSAtPiBkaWN0IHwgTm9uZToKICAgICAgICBpdGVtID0gdGFi"
    "bGUuaXRlbUF0KHBvcykKICAgICAgICBpZiBub3QgaXRlbToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICByb3cgPSBp"
    "dGVtLnJvdygpCiAgICAgICAgdHNfaXRlbSA9IHRhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIG5vdCB0c19pdGVtOgogICAg"
    "ICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGVpZCA9IHRzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAg"
    "ICAgICAgcmV0dXJuIHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGVpZCkKCiAgICBkZWYgX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2Vs"
    "ZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgcG9zKSAtPiBOb25lOgogICAgICAgIGV2dCA9IHNlbGYuX2V2ZW50X2Zyb21fdGFibGVf"
    "cG9zaXRpb24odGFibGUsIHBvcykKICAgICAgICBpZiBub3QgZXZ0OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBmcm9tIFB5"
    "U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIGFjdF9zZW5kID0g"
    "bWVudS5hZGRBY3Rpb24oIlNlbmQgdG8gUHJvbXB0IikKICAgICAgICBjaG9zZW4gPSBtZW51LmV4ZWModGFibGUudmlld3BvcnQo"
    "KS5tYXBUb0dsb2JhbChwb3MpKQogICAgICAgIGlmIGNob3NlbiA9PSBhY3Rfc2VuZDoKICAgICAgICAgICAgc2VsZi5fc2VuZF9l"
    "dmVudF90b19wcm9tcHQoZXZ0KQoKICAgIGRlZiBfZm9ybWF0X2V2ZW50X2Zvcl9wcm9tcHQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+"
    "IHN0cjoKICAgICAgICBsYWJlbCA9IChldmVudC5nZXQoImxhYmVsIikgb3IgIlJvbGwiKS5zdHJpcCgpCiAgICAgICAgZ3JvdXBl"
    "ZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBvciB7fQogICAgICAgIHNlZ21lbnRzID0gW10KICAgICAg"
    "ICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAg"
    "ICAgaWYgdmFsczoKICAgICAgICAgICAgICAgIHNlZ21lbnRzLmFwcGVuZChmIntkaWV9IHJvbGxlZCB7JywnLmpvaW4oc3RyKHYp"
    "IGZvciB2IGluIHZhbHMpfSIpCiAgICAgICAgbW9kID0gaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkKICAgICAgICB0b3Rh"
    "bCA9IGludChldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpCiAgICAgICAgcmV0dXJuIGYie2xhYmVsfTogeyc7ICcuam9pbihz"
    "ZWdtZW50cyl9OyBtb2RpZmllciB7bW9kOitkfTsgdG90YWwge3RvdGFsfSIKCiAgICBkZWYgX3NlbmRfZXZlbnRfdG9fcHJvbXB0"
    "KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHdpbmRvdyA9IHNlbGYud2luZG93KCkKICAgICAgICBpZiBub3Qg"
    "d2luZG93IG9yIG5vdCBoYXNhdHRyKHdpbmRvdywgIl9pbnB1dF9maWVsZCIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBs"
    "aW5lID0gc2VsZi5fZm9ybWF0X2V2ZW50X2Zvcl9wcm9tcHQoZXZlbnQpCiAgICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRU"
    "ZXh0KGxpbmUpCiAgICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgZGVmIF9wbGF5X3JvbGxfc291bmQo"
    "c2VsZik6CiAgICAgICAgaWYgbm90IFdJTlNPVU5EX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHdpbnNvdW5kLkJlZXAoODQwLCAzMCkKICAgICAgICAgICAgd2luc291bmQuQmVlcCg2MjAsIDM1KQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgoKY2xhc3MgTWFnaWM4QmFsbFRhYihRV2lkZ2V0KToKICAgICIiIk1hZ2lj"
    "IDgtQmFsbCBtb2R1bGUgd2l0aCBjaXJjdWxhciBvcmIgZGlzcGxheSBhbmQgcHVsc2luZyBhbnN3ZXIgdGV4dC4iIiIKCiAgICBB"
    "TlNXRVJTID0gWwogICAgICAgICJJdCBpcyBjZXJ0YWluLiIsCiAgICAgICAgIkl0IGlzIGRlY2lkZWRseSBzby4iLAogICAgICAg"
    "ICJXaXRob3V0IGEgZG91YnQuIiwKICAgICAgICAiWWVzIGRlZmluaXRlbHkuIiwKICAgICAgICAiWW91IG1heSByZWx5IG9uIGl0"
    "LiIsCiAgICAgICAgIkFzIEkgc2VlIGl0LCB5ZXMuIiwKICAgICAgICAiTW9zdCBsaWtlbHkuIiwKICAgICAgICAiT3V0bG9vayBn"
    "b29kLiIsCiAgICAgICAgIlllcy4iLAogICAgICAgICJTaWducyBwb2ludCB0byB5ZXMuIiwKICAgICAgICAiUmVwbHkgaGF6eSwg"
    "dHJ5IGFnYWluLiIsCiAgICAgICAgIkFzayBhZ2FpbiBsYXRlci4iLAogICAgICAgICJCZXR0ZXIgbm90IHRlbGwgeW91IG5vdy4i"
    "LAogICAgICAgICJDYW5ub3QgcHJlZGljdCBub3cuIiwKICAgICAgICAiQ29uY2VudHJhdGUgYW5kIGFzayBhZ2Fpbi4iLAogICAg"
    "ICAgICJEb24ndCBjb3VudCBvbiBpdC4iLAogICAgICAgICJNeSByZXBseSBpcyBuby4iLAogICAgICAgICJNeSBzb3VyY2VzIHNh"
    "eSBuby4iLAogICAgICAgICJPdXRsb29rIG5vdCBzbyBnb29kLiIsCiAgICAgICAgIlZlcnkgZG91YnRmdWwuIiwKICAgIF0KCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgb25fdGhyb3c9Tm9uZSwgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX29uX3Rocm93ID0gb25fdGhyb3cKICAgICAgICBzZWxmLl9sb2cgPSBkaWFnbm9z"
    "dGljc19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dl"
    "ciA9ICIiCgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIu"
    "c2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9mYWRlX291"
    "dF9hbnN3ZXIpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9idWlsZF9hbmltYXRpb25zKCkKICAgICAg"
    "ICBzZWxmLl9zZXRfaWRsZV92aXN1YWwoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0g"
    "UVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYsIDE2LCAxNikKICAgICAgICBy"
    "b290LnNldFNwYWNpbmcoMTQpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgICAgIHNlbGYuX29yYl9mcmFtZSA9IFFG"
    "cmFtZSgpCiAgICAgICAgc2VsZi5fb3JiX2ZyYW1lLnNldEZpeGVkU2l6ZSgyMjgsIDIyOCkKICAgICAgICBzZWxmLl9vcmJfZnJh"
    "bWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgIlFGcmFtZSB7IgogICAgICAgICAgICAiYmFja2dyb3VuZC1jb2xvcjogIzA0"
    "MDQwNjsiCiAgICAgICAgICAgICJib3JkZXI6IDFweCBzb2xpZCByZ2JhKDIzNCwgMjM3LCAyNTUsIDAuNjIpOyIKICAgICAgICAg"
    "ICAgImJvcmRlci1yYWRpdXM6IDExNHB4OyIKICAgICAgICAgICAgIn0iCiAgICAgICAgKQoKICAgICAgICBvcmJfbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQoc2VsZi5fb3JiX2ZyYW1lKQogICAgICAgIG9yYl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDIwLCAyMCwg"
    "MjAsIDIwKQogICAgICAgIG9yYl9sYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9vcmJfaW5uZXIgPSBRRnJhbWUo"
    "KQogICAgICAgIHNlbGYuX29yYl9pbm5lci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsiCiAgICAgICAgICAg"
    "ICJiYWNrZ3JvdW5kLWNvbG9yOiAjMDcwNzBhOyIKICAgICAgICAgICAgImJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjU1LCAyNTUs"
    "IDI1NSwgMC4xMik7IgogICAgICAgICAgICAiYm9yZGVyLXJhZGl1czogODRweDsiCiAgICAgICAgICAgICJ9IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9vcmJfaW5uZXIuc2V0TWluaW11bVNpemUoMTY4LCAxNjgpCiAgICAgICAgc2VsZi5fb3JiX2lubmVyLnNl"
    "dE1heGltdW1TaXplKDE2OCwgMTY4KQoKICAgICAgICBpbm5lcl9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9vcmJfaW5uZXIp"
    "CiAgICAgICAgaW5uZXJfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYsIDE2LCAxNikKICAgICAgICBpbm5lcl9sYXlv"
    "dXQuc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9laWdodF9sYmwgPSBRTGFiZWwoIjgiKQogICAgICAgIHNlbGYuX2VpZ2h0"
    "X2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgImNvbG9yOiByZ2JhKDI1NSwgMjU1LCAyNTUsIDAuOTUpOyAiCiAgICAgICAgICAgICJm"
    "b250LXNpemU6IDgwcHg7IGZvbnQtd2VpZ2h0OiA3MDA7ICIKICAgICAgICAgICAgImZvbnQtZmFtaWx5OiBHZW9yZ2lhLCBzZXJp"
    "ZjsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuYW5zd2VyX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBz"
    "ZWxmLmFuc3dlcl9sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5hbnN3"
    "ZXJfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDE2cHg7IGZvbnQtc3R5bGU6IGl0YWxpYzsgIgogICAgICAgICAgICAiZm9u"
    "dC13ZWlnaHQ6IDYwMDsgYm9yZGVyOiBub25lOyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKCiAgICAgICAgaW5uZXJfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9laWdodF9sYmwsIDEpCiAgICAgICAgaW5uZXJfbGF5b3V0LmFkZFdpZGdldChzZWxmLmFuc3dlcl9s"
    "YmwsIDEpCiAgICAgICAgb3JiX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fb3JiX2lubmVyLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFs"
    "aWduQ2VudGVyKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9vcmJfZnJhbWUsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxp"
    "Z25IQ2VudGVyKQoKICAgICAgICBzZWxmLnRocm93X2J0biA9IFFQdXNoQnV0dG9uKCJUaHJvdyB0aGUgOC1CYWxsIikKICAgICAg"
    "ICBzZWxmLnRocm93X2J0bi5zZXRGaXhlZEhlaWdodCgzOCkKICAgICAgICBzZWxmLnRocm93X2J0bi5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fdGhyb3dfYmFsbCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnRocm93X2J0biwgMCwgUXQuQWxpZ25tZW50Rmxh"
    "Zy5BbGlnbkhDZW50ZXIpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgZGVmIF9idWlsZF9hbmltYXRpb25zKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkgPSBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0KHNlbGYuYW5zd2Vy"
    "X2xibCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0R3JhcGhpY3NFZmZlY3Qoc2VsZi5fYW5zd2VyX29wYWNpdHkpCiAgICAg"
    "ICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCgogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0gPSBRUHJvcGVy"
    "dHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5p"
    "bS5zZXREdXJhdGlvbig3NjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRTdGFydFZhbHVlKDAuMzUpCiAgICAgICAgc2Vs"
    "Zi5fcHVsc2VfYW5pbS5zZXRFbmRWYWx1ZSgxLjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRFYXNpbmdDdXJ2ZShRRWFz"
    "aW5nQ3VydmUuVHlwZS5Jbk91dFNpbmUpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRMb29wQ291bnQoLTEpCgogICAgICAg"
    "IHNlbGYuX2ZhZGVfb3V0ID0gUVByb3BlcnR5QW5pbWF0aW9uKHNlbGYuX2Fuc3dlcl9vcGFjaXR5LCBiIm9wYWNpdHkiLCBzZWxm"
    "KQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldER1cmF0aW9uKDU2MCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZh"
    "bHVlKDEuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFbmRWYWx1ZSgwLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0"
    "RWFzaW5nQ3VydmUoUUVhc2luZ0N1cnZlLlR5cGUuSW5PdXRRdWFkKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LmZpbmlzaGVkLmNv"
    "bm5lY3Qoc2VsZi5fY2xlYXJfdG9faWRsZSkKCiAgICBkZWYgX3NldF9pZGxlX3Zpc3VhbChzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gIiIKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5hbnN3"
    "ZXJfbGJsLmNsZWFyKCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHku"
    "c2V0T3BhY2l0eSgwLjApCgogICAgZGVmIF90aHJvd19iYWxsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xlYXJfdGlt"
    "ZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9wKCkKCiAg"
    "ICAgICAgYW5zd2VyID0gcmFuZG9tLmNob2ljZShzZWxmLkFOU1dFUlMpCiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSBh"
    "bnN3ZXIKCiAgICAgICAgc2VsZi5fZWlnaHRfbGJsLmhpZGUoKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRUZXh0KGFuc3dl"
    "cikKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgw"
    "LjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdGFydCgpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RhcnQoNjAwMDAp"
    "CiAgICAgICAgc2VsZi5fbG9nKGYiWzhCQUxMXSBUaHJvdyByZXN1bHQ6IHthbnN3ZXJ9IiwgIklORk8iKQoKICAgICAgICBpZiBj"
    "YWxsYWJsZShzZWxmLl9vbl90aHJvdyk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Rocm93KGFu"
    "c3dlcikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhmIls4QkFM"
    "TF1bV0FSTl0gSW50ZXJuYWwgcHJvbXB0IGRpc3BhdGNoIGZhaWxlZDoge2V4fSIsICJXQVJOIikKCiAgICBkZWYgX2ZhZGVfb3V0"
    "X2Fuc3dlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3B1bHNl"
    "X2FuaW0uc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0U3RhcnRW"
    "YWx1ZShmbG9hdChzZWxmLl9hbnN3ZXJfb3BhY2l0eS5vcGFjaXR5KCkpKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVuZFZh"
    "bHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zdGFydCgpCgogICAgZGVmIF9jbGVhcl90b19pZGxlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fc2V0X2lkbGVfdmlzdWFsKCkKCiMg4pSA4pSA"
    "IE1BSU4gV0lORE9XIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMb2NrQXdhcmVUYWJCYXIo"
    "UVRhYkJhcik6CiAgICAiIiJUYWIgYmFyIHRoYXQgYmxvY2tzIGRyYWcgaW5pdGlhdGlvbiBmb3IgbG9ja2VkIHRhYnMuIiIiCgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIGlzX2xvY2tlZF9ieV9pZCwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCA9IGlzX2xvY2tlZF9ieV9pZAogICAgICAgIHNlbGYuX3By"
    "ZXNzZWRfaW5kZXggPSAtMQoKICAgIGRlZiBfdGFiX2lkKHNlbGYsIGluZGV4OiBpbnQpOgogICAgICAgIGlmIGluZGV4IDwgMDoK"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICByZXR1cm4gc2VsZi50YWJEYXRhKGluZGV4KQoKICAgIGRlZiBtb3VzZVBy"
    "ZXNzRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXggPSBzZWxmLnRhYkF0KGV2ZW50LnBvcygp"
    "KQogICAgICAgIGlmIChldmVudC5idXR0b24oKSA9PSBRdC5Nb3VzZUJ1dHRvbi5MZWZ0QnV0dG9uIGFuZCBzZWxmLl9wcmVzc2Vk"
    "X2luZGV4ID49IDApOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl90YWJfaWQoc2VsZi5fcHJlc3NlZF9pbmRleCkKICAgICAg"
    "ICAgICAgaWYgdGFiX2lkIGFuZCBzZWxmLl9pc19sb2NrZWRfYnlfaWQodGFiX2lkKToKICAgICAgICAgICAgICAgIHNlbGYuc2V0"
    "Q3VycmVudEluZGV4KHNlbGYuX3ByZXNzZWRfaW5kZXgpCiAgICAgICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlTW92ZUV2ZW50"
    "KHNlbGYsIGV2ZW50KToKICAgICAgICBpZiBzZWxmLl9wcmVzc2VkX2luZGV4ID49IDA6CiAgICAgICAgICAgIHRhYl9pZCA9IHNl"
    "bGYuX3RhYl9pZChzZWxmLl9wcmVzc2VkX2luZGV4KQogICAgICAgICAgICBpZiB0YWJfaWQgYW5kIHNlbGYuX2lzX2xvY2tlZF9i"
    "eV9pZCh0YWJfaWQpOgogICAgICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHN1cGVyKCkubW91c2VNb3ZlRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlUmVsZWFzZUV2ZW50KHNlbGYsIGV2ZW50KToKICAg"
    "ICAgICBzZWxmLl9wcmVzc2VkX2luZGV4ID0gLTEKICAgICAgICBzdXBlcigpLm1vdXNlUmVsZWFzZUV2ZW50KGV2ZW50KQoKCmNs"
    "YXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2Vt"
    "YmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDi"
    "lIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlz"
    "IOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJB"
    "TSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1"
    "cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29u"
    "ZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUi"
    "CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQg"
    "ICAgICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19z"
    "dGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9"
    "IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUg"
    "cnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZv"
    "cmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3Rv"
    "cnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGlu"
    "ZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWlu"
    "ZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCBy"
    "ZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9k"
    "dXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1h"
    "bmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAg"
    "PSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fdGFz"
    "a19kYXRlX2ZpbHRlciA9ICJuZXh0XzNfbW9udGhzIgoKICAgICAgICAjIFJpZ2h0IHN5c3RlbXMgdGFiLXN0cmlwIHByZXNlbnRh"
    "dGlvbiBzdGF0ZSAoc3RhYmxlIElEcyArIHZpc3VhbCBvcmRlcikKICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVmczogbGlzdFtk"
    "aWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxf"
    "dGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxsX3RhYnMgPSBGYWxzZQoK"
    "ICAgICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACgogICAgICAgICMgU2VlZCBMU0wgcnVsZXMgb24gZmlyc3QgcnVuCiAgICAgICAgc2VsZi5fbGVzc29u"
    "cy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAgICMgTG9hZCBlbnRpdHkgc3RhdGUKICAgICAgICBzZWxmLl9zdGF0ZSA9IHNlbGYu"
    "X21lbW9yeS5sb2FkX3N0YXRlKCkKICAgICAgICBzZWxmLl9zdGF0ZVsic2Vzc2lvbl9jb3VudCJdID0gc2VsZi5fc3RhdGUuZ2V0"
    "KCJzZXNzaW9uX2NvdW50IiwwKSArIDEKICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zdGFydHVwIl0gID0gbG9jYWxfbm93X2lz"
    "bygpCiAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICMgQnVpbGQgYWRhcHRvcgog"
    "ICAgICAgIHNlbGYuX2FkYXB0b3IgPSBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1h"
    "bmFnZXIgKHNldCB1cCBhZnRlciB3aWRnZXRzIGJ1aWx0KQogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyOiBPcHRpb25hbFtG"
    "YWNlVGltZXJNYW5hZ2VyXSA9IE5vbmUKCiAgICAgICAgIyDilIDilIAgQnVpbGQgVUkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5zZXRXaW5k"
    "b3dUaXRsZShBUFBfTkFNRSkKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEyMDAsIDc1MCkKICAgICAgICBzZWxmLnJlc2l6"
    "ZSgxMzUwLCA4NTApCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgog"
    "ICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nciA9"
    "IEZhY2VUaW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNlbGYuX21pcnJvciwgc2VsZi5fZW1vdGlvbl9ibG9jawogICAgICAgICkK"
    "CiAgICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyID0gUVRpbWVyKCkKICAg"
    "ICAgICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRlX3N0YXRzKQogICAgICAgIHNlbGYuX3N0"
    "YXRzX3RpbWVyLnN0YXJ0KDEwMDApCgogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9i"
    "bGlua190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fYmxpbmspCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIuc3RhcnQoODAw"
    "KQoKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1lcigpCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQg"
    "YW5kIHNlbGYuX2Zvb3Rlcl9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIudGlt"
    "ZW91dC5jb25uZWN0KHNlbGYuX2Zvb3Rlcl9zdHJpcC5yZWZyZXNoKQogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1l"
    "ci5zdGFydCg2MDAwMCkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVudGlsIGFmdGVy"
    "IHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1QgY2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0"
    "dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMgQm90aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9t"
    "IG1haW4oKSBhZnRlcgogICAgICAgICMgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAj"
    "IOKUgOKUgCBVSSBDT05TVFJVQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdl"
    "dChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDilIDilIAgQm9keTogbGVmdCB3b3Jrc3BhY2UgfCByaWdodCBz"
    "eXN0ZW1zIChkcmFnZ2FibGUgc3BsaXR0ZXIpIOKUgAogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQu"
    "T3JpZW50YXRpb24uSG9yaXpvbnRhbCkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLnNldENoaWxkcmVuQ29sbGFwc2libGUo"
    "RmFsc2UpCiAgICAgICAgc2VsZi5fbWFpbl9zcGxpdHRlci5zZXRIYW5kbGVXaWR0aCg4KQoKICAgICAgICAjIExlZnQgcGFuZSA9"
    "IEpvdXJuYWwgKyBDaGF0IHdvcmtzcGFjZQogICAgICAgIGxlZnRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAgbGVmdF93"
    "b3Jrc3BhY2Uuc2V0TWluaW11bVdpZHRoKDcwMCkKICAgICAgICBsZWZ0X2xheW91dCA9IFFIQm94TGF5b3V0KGxlZnRfd29ya3Nw"
    "YWNlKQogICAgICAgIGxlZnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxlZnRfbGF5b3V0"
    "LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyID0gSm91cm5hbFNpZGViYXIoc2VsZi5fc2Vzc2lv"
    "bnMpCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAg"
    "ICAgc2VsZi5fbG9hZF9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fY2xlYXJf"
    "cmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBsZWZ0X2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFyKQogICAgICAgIGxlZnRfbGF5b3V0LmFkZExheW91dChzZWxmLl9i"
    "dWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAgICAgICMgUmlnaHQgcGFuZSA9IHN5c3RlbXMvbW9kdWxlcyArIGNhbGVuZGFyCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlLnNldE1pbmltdW1XaWR0aCgz"
    "NjApCiAgICAgICAgcmlnaHRfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0X2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByaWdodF9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAg"
    "IHJpZ2h0X2xheW91dC5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCksIDEpCgogICAgICAgIHNlbGYuX21h"
    "aW5fc3BsaXR0ZXIuYWRkV2lkZ2V0KGxlZnRfd29ya3NwYWNlKQogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuYWRkV2lkZ2V0"
    "KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLnNldENvbGxhcHNpYmxlKDAsIEZhbHNlKQogICAg"
    "ICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuc2V0Q29sbGFwc2libGUoMSwgRmFsc2UpCiAgICAgICAgc2VsZi5fbWFpbl9zcGxpdHRl"
    "ci5zcGxpdHRlck1vdmVkLmNvbm5lY3Qoc2VsZi5fc2F2ZV9tYWluX3NwbGl0dGVyX3N0YXRlKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYuX21haW5fc3BsaXR0ZXIsIDEpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi5fcmVzdG9yZV9tYWlu"
    "X3NwbGl0dGVyX3N0YXRlKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0gUUxhYmVs"
    "KAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAgICAgIGZv"
    "b3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBsZXR0"
    "ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAg"
    "KQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFk"
    "ZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdpZGdldDoKICAgICAgICBiYXIgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAg"
    "IGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAg"
    "ICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAg"
    "IGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAg"
    "ICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBi"
    "b3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBO"
    "b25lCiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQ"
    "YW5lbCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9y"
    "X3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBpZGxlX2VuYWJsZWQgPSBib29sKENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pLmdldCgiaWRsZV9lbmFibGVkIiwgRmFsc2UpKQogICAgICAgIHNlbGYuX2lkbGVfYnRuID0gUVB1c2hC"
    "dXR0b24oIklETEUgT04iIGlmIGlkbGVfZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0"
    "Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5faWRs"
    "ZV9idG4uc2V0Q2hlY2tlZChpZGxlX2VuYWJsZWQpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV9idG4udG9nZ2xl"
    "ZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJMIGJ1dHRvbnMKICAgICAgICBzZWxmLl9m"
    "c19idG4gPSBRUHVzaEJ1dHRvbigiRnVsbHNjcmVlbiIpCiAgICAgICAgc2VsZi5fYmxfYnRuID0gUVB1c2hCdXR0b24oIkJvcmRl"
    "cmxlc3MiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRvbigiRXhwb3J0IikKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAgIGZvciBidG4gaW4gKHNlbGYuX2ZzX2J0biwgc2VsZi5f"
    "YmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBi"
    "dG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4"
    "OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRIZWln"
    "aHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2VsZi5fc2h1dGRvd25f"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0JMT09EfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgZiJm"
    "b250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJG"
    "dWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVzcyAoRjEwKSIpCiAgICAg"
    "ICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRYVCBmaWxlIikKICAgICAgICBz"
    "ZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhl"
    "aXIgbGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVl"
    "bikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKQogICAgICAgIHNl"
    "bGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0"
    "YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZXhw"
    "b3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikKCiAgICAgICAgcmV0dXJuIGJhcgoK"
    "ICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91"
    "dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRhYiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hh"
    "dCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fbWFpbl90YWJz"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJh"
    "cjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5n"
    "OiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7"
    "IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBz"
    "b2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2Vh"
    "bmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rp"
    "c3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xv"
    "cjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5jZV93"
    "aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMTogU2VsZiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zZWxm"
    "X3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3NlbGZfdGFiX3dp"
    "ZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmX2xheW91"
    "dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9zZWxm"
    "X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBu"
    "b25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRk"
    "aW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQog"
    "ICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJfd2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkKCiAgICAgICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJj"
    "ZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRvcnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNv"
    "bmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xPV0VSLU1JRERMRSBQRVJNQU5FTlQgRk9PVFBSSU5UXQogICAgICAgIGJsb2NrX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1pcnJvciAobmV2ZXIg"
    "Y29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "bWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xh"
    "eW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJX01JUlJP"
    "Ul9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJvci5zZXRG"
    "aXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tf"
    "cm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sga2VlcHMgYSBwZXJtYW5l"
    "bnQgZm9vdHByaW50OgogICAgICAgICMgbGVmdCA9IGNvbXBhY3Qgc3RhY2sgYXJlYSwgcmlnaHQgPSBmaXhlZCBleHBhbmRlZC1y"
    "b3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfbGF5b3V0ID0gUUhCb3hMYXlv"
    "dXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWluaW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFj"
    "a193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9s"
    "b3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgbWlkZGxlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93"
    "ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93ID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9IFFHcmlkTGF5b3V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdykKICAgICAg"
    "ICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNl"
    "bGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0SG9yaXpvbnRhbFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9l"
    "eHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2FsU3BhY2luZygyKQogICAgICAgIG1pZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBz"
    "ZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xs"
    "YXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywK"
    "ICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAg"
    "ICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9sZWZ0X29yYiA9IFNwaGVyZVdpZGdl"
    "dCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwgQ19DUklNU09OX0RJTQogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0xFRlRfT1JCX1RJ"
    "VExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAg"
    "ICkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0IChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQg"
    "PSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi"
    "4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2"
    "ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9yYiAoY29sbGFwc2libGUpCiAgICAgICAg"
    "c2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENfUFVSUExFLCBD"
    "X1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAg"
    "ICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3JpZ2h0X29yYiwKICAgICAgICAgICAgbWluX3dpZHRo"
    "PTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxl"
    "KQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChl"
    "c3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAg"
    "ICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVn"
    "ZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vf"
    "c2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAg"
    "ICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNl"
    "X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFw"
    "ID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQs"
    "CiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFeHBhbmRl"
    "ZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9uaWNhbCB2aXN1YWwgb3JkZXIuCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5k"
    "ZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAgICAgImVtb3Rpb25zIiwgInByaW1hcnkiLCAiY3ljbGUiLCAic2Vjb25kYXJ5Iiwg"
    "ImVzc2VuY2UiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tfb3JkZXIgPSBbCiAgICAgICAgICAg"
    "ICJjeWNsZSIsICJwcmltYXJ5IiwgInNlY29uZGFyeSIsICJlc3NlbmNlIiwgImVtb3Rpb25zIgogICAgICAgIF0KICAgICAgICBz"
    "ZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMgPSB7CiAgICAgICAgICAgICJlbW90aW9ucyI6IHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3Jh"
    "cCwKICAgICAgICAgICAgInByaW1hcnkiOiBzZWxmLl9sZWZ0X29yYl93cmFwLAogICAgICAgICAgICAiY3ljbGUiOiBzZWxmLl9j"
    "eWNsZV93cmFwLAogICAgICAgICAgICAic2Vjb25kYXJ5Ijogc2VsZi5fcmlnaHRfb3JiX3dyYXAsCiAgICAgICAgICAgICJlc3Nl"
    "bmNlIjogc2VsZi5fZXNzZW5jZV93cmFwLAogICAgICAgIH0KCiAgICAgICAgc2VsZi5fbG93ZXJfcm93X3Nsb3RzID0ge30KICAg"
    "ICAgICBmb3IgY29sLCBrZXkgaW4gZW51bWVyYXRlKHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Nsb3Rfb3JkZXIpOgogICAgICAgICAg"
    "ICBzbG90ID0gUVdpZGdldCgpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2xvdCkKICAgICAgICAgICAg"
    "c2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgICAgIHNsb3RfbGF5b3V0LnNldFNwYWNp"
    "bmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5hZGRXaWRnZXQoc2xvdCwgMCwgY29sKQog"
    "ICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbHVtblN0cmV0Y2goY29sLCAxKQogICAgICAg"
    "ICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XSA9IHNsb3RfbGF5b3V0CgogICAgICAgIGZvciB3cmFwIGluIHNlbGYuX2xv"
    "d2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAgICAgICAgICAgd3JhcC50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fcmVmcmVzaF9s"
    "b3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQoKQoKICAgICAgICBi"
    "bG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYmxvY2tfcm93KQoKICAg"
    "ICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCBwZXJtYW5lbnQgVUkgc3RydWN0dXJlKQogICAg"
    "ICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3RlclN0cmlwV2lkZ2V0KCkKICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAuc2V0"
    "X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Zvb3Rlcl9zdHJpcCkK"
    "CiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBwcm9t"
    "cHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAg"
    "KQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQgPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNl"
    "bGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1c2hCdXR0b24oVUlf"
    "U0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAgICAgICAgc2VsZi5fc2VuZF9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZh"
    "bHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChz"
    "ZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91"
    "dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9jbGVhcl9sYXlvdXRfd2lkZ2V0"
    "cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHdoaWxlIGxheW91dC5jb3VudCgpOgogICAgICAg"
    "ICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3aWRnZXQgPSBpdGVtLndpZGdldCgpCiAgICAgICAgICAg"
    "IGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRQYXJlbnQoTm9uZSkKCiAgICBkZWYgX3Jl"
    "ZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxmLCAqX2FyZ3MpIC0+IE5vbmU6CiAgICAgICAgY29sbGFwc2VkX2NvdW50ID0g"
    "MAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQgcm93IHNsb3RzIGluIGZpeGVkIGV4cGFuZGVkIG9yZGVyLgogICAgICAgIGZv"
    "ciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcjoKICAgICAgICAgICAgc2xvdF9sYXlvdXQgPSBzZWxmLl9s"
    "b3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzbG90X2xheW91dCkKICAg"
    "ICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIHdyYXAuaXNfZXhwYW5k"
    "ZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFdpZGdldCh3cmFwKQogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAg"
    "ICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sgaW4gY2Fub25pY2FsIGNvbXBhY3Qgb3JkZXIuCiAgICAgICAgc2VsZi5fY2xl"
    "YXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0KQogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJf"
    "Y29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAg"
    "ICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVkKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQu"
    "YWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2Vs"
    "Zi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxlKGNvbGxhcHNlZF9jb3VudCA+IDApCgogICAgZGVmIF9idWlsZF9zcGVsbGJv"
    "b2tfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIpKQoKICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRNaW5pbXVtV2lkdGgoMjgwKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFu"
    "ZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAgICAgICkKICAgICAgICBzZWxmLl9zcGVs"
    "bF90YWJfYmFyID0gTG9ja0F3YXJlVGFiQmFyKHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQsIHNlbGYuX3NwZWxsX3RhYnMpCiAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRUYWJCYXIoc2VsZi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBzZWxmLl9zcGVsbF90"
    "YWJfYmFyLnNldE1vdmFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldENvbnRleHRNZW51UG9saWN5KFF0"
    "LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuY3VzdG9tQ29u"
    "dGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdChzZWxmLl9zaG93X3NwZWxsX3RhYl9jb250ZXh0X21lbnUpCiAgICAgICAgc2VsZi5f"
    "c3BlbGxfdGFiX2Jhci50YWJNb3ZlZC5jb25uZWN0KHNlbGYuX29uX3NwZWxsX3RhYl9kcmFnX21vdmVkKQogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYnMuY3VycmVudENoYW5nZWQuY29ubmVjdChsYW1iZGEgX2lkeDogc2VsZi5fZXhpdF9zcGVsbF90YWJfbW92ZV9t"
    "b2RlKCkpCiAgICAgICAgaWYgbm90IHNlbGYuX2ZvY3VzX2hvb2tlZF9mb3Jfc3BlbGxfdGFiczoKICAgICAgICAgICAgYXBwID0g"
    "UUFwcGxpY2F0aW9uLmluc3RhbmNlKCkKICAgICAgICAgICAgaWYgYXBwIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgYXBw"
    "LmZvY3VzQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX2dsb2JhbF9mb2N1c19jaGFuZ2VkKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "Zm9jdXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzID0gVHJ1ZQoKICAgICAgICAjIEJ1aWxkIERpYWdub3N0aWNzVGFiIGVhcmx5IHNv"
    "IHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBldmVuIGJlZm9yZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hl"
    "ZCB0byB0aGUgd2lkZ2V0LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKUgOKU"
    "gCBJbnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5faHdfcGFuZWwgPSBIYXJkd2FyZVBhbmVsKCkKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFi"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Ns"
    "X2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpv"
    "YlRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNU"
    "YWIoc2VsZi5fbGVzc29ucykKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhl"
    "IHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJh"
    "dGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRh"
    "YiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJh"
    "Y2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBEaWNlIFJvbGxlciB0YWIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fZGljZV9yb2xsZXJfdGFiID0g"
    "RGljZVJvbGxlclRhYihkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nKQoKICAgICAgICAjIOKUgOKUgCBNYWdp"
    "YyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNlbGYuX21hZ2ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxUYWIoCiAgICAgICAgICAgIG9uX3Rocm93PXNlbGYuX2hhbmRsZV9t"
    "YWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPXNlbGYuX2RpYWdfdGFiLmxvZywKICAgICAg"
    "ICApCgogICAgICAgICMg4pSA4pSAIFNldHRpbmdzIHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NldHRpbmdzX3RhYiA9IFNldHRp"
    "bmdzVGFiKHNlbGYpCgogICAgICAgICMgRGVzY3JpcHRvci1iYXNlZCBvcmRlcmluZyAoc3RhYmxlIGlkZW50aXR5ICsgdmlzdWFs"
    "IG9yZGVyIG9ubHkpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnMgPSBbCiAgICAgICAgICAgIHsiaWQiOiAiaW5zdHJ1bWVu"
    "dHMiLCAidGl0bGUiOiAiSW5zdHJ1bWVudHMiLCAid2lkZ2V0Ijogc2VsZi5faHdfcGFuZWwsICJkZWZhdWx0X29yZGVyIjogMCwg"
    "ImNhdGVnb3J5IjogIlN5c3RlbSIsICJzZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFsiQ29yZSJdLCAicHJvdGVjdGVkX2NhdGVnb3J5"
    "IjogVHJ1ZX0sCiAgICAgICAgICAgIHsiaWQiOiAic2xfc2NhbnMiLCAidGl0bGUiOiAiU0wgU2NhbnMiLCAid2lkZ2V0Ijogc2Vs"
    "Zi5fc2xfc2NhbnMsICJkZWZhdWx0X29yZGVyIjogMSwgImNhdGVnb3J5IjogIk9wZXJhdGlvbnMiLCAic2Vjb25kYXJ5X2NhdGVn"
    "b3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAic2xfY29tbWFuZHMiLCAidGl0bGUiOiAiU0wgQ29tbWFuZHMiLCAid2lk"
    "Z2V0Ijogc2VsZi5fc2xfY29tbWFuZHMsICJkZWZhdWx0X29yZGVyIjogMiwgImNhdGVnb3J5IjogIk9wZXJhdGlvbnMiLCAic2Vj"
    "b25kYXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAiam9iX3RyYWNrZXIiLCAidGl0bGUiOiAiSm9iIFRy"
    "YWNrZXIiLCAid2lkZ2V0Ijogc2VsZi5fam9iX3RyYWNrZXIsICJkZWZhdWx0X29yZGVyIjogMywgImNhdGVnb3J5IjogIk9wZXJh"
    "dGlvbnMiLCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAibGVzc29ucyIsICJ0aXRsZSI6"
    "ICJMZXNzb25zIiwgIndpZGdldCI6IHNlbGYuX2xlc3NvbnNfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDQsICJjYXRlZ29yeSI6ICJD"
    "b3JlIiwgInNlY29uZGFyeV9jYXRlZ29yaWVzIjogWyJNYW5hZ2VtZW50Il19LAogICAgICAgICAgICB7ImlkIjogIm1vZHVsZXMi"
    "LCAidGl0bGUiOiAiTW9kdWxlcyIsICJ3aWRnZXQiOiBzZWxmLl9tb2R1bGVfdHJhY2tlciwgImRlZmF1bHRfb3JkZXIiOiA1LCAi"
    "Y2F0ZWdvcnkiOiAiTWFuYWdlbWVudCIsICJzZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFsiVXRpbGl0aWVzIl19LAogICAgICAgICAg"
    "ICB7ImlkIjogImRpY2Vfcm9sbGVyIiwgInRpdGxlIjogIkRpY2UgUm9sbGVyIiwgIndpZGdldCI6IHNlbGYuX2RpY2Vfcm9sbGVy"
    "X3RhYiwgImRlZmF1bHRfb3JkZXIiOiA2LCAiY2F0ZWdvcnkiOiAiVXRpbGl0aWVzIiwgInNlY29uZGFyeV9jYXRlZ29yaWVzIjog"
    "W119LAogICAgICAgICAgICB7ImlkIjogIm1hZ2ljXzhfYmFsbCIsICJ0aXRsZSI6ICJNYWdpYyA4LUJhbGwiLCAid2lkZ2V0Ijog"
    "c2VsZi5fbWFnaWNfOGJhbGxfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDcsICJjYXRlZ29yeSI6ICJVdGlsaXRpZXMiLCAic2Vjb25k"
    "YXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAiZGlhZ25vc3RpY3MiLCAidGl0bGUiOiAiRGlhZ25vc3Rp"
    "Y3MiLCAid2lkZ2V0Ijogc2VsZi5fZGlhZ190YWIsICJkZWZhdWx0X29yZGVyIjogOCwgImNhdGVnb3J5IjogIlN5c3RlbSIsICJz"
    "ZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFtdLCAicHJvdGVjdGVkX2NhdGVnb3J5IjogVHJ1ZX0sCiAgICAgICAgICAgIHsiaWQiOiAi"
    "c2V0dGluZ3MiLCAidGl0bGUiOiAiU2V0dGluZ3MiLCAid2lkZ2V0Ijogc2VsZi5fc2V0dGluZ3NfdGFiLCAiZGVmYXVsdF9vcmRl"
    "ciI6IDksICJjYXRlZ29yeSI6ICJTeXN0ZW0iLCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMiOiBbXSwgInByb3RlY3RlZF9jYXRlZ29y"
    "eSI6IFRydWV9LAogICAgICAgIF0KICAgICAgICBzZWxmLl9sb2FkX3NwZWxsX3RhYl9zdGF0ZV9mcm9tX2NvbmZpZygpCiAgICAg"
    "ICAgc2VsZi5fcmVidWlsZF9zcGVsbF90YWJzKCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAg"
    "cmlnaHRfd29ya3NwYWNlX2xheW91dCA9IFFWQm94TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93b3Jrc3Bh"
    "Y2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zcGVsbF90YWJzLCAxKQoK"
    "ICAgICAgICBjYWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJlbC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3BhY2luZzog"
    "MnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xh"
    "eW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNhbGVuZGFy"
    "V2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuY2Fs"
    "ZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAg"
    "ICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNl"
    "dE1heGltdW1IZWlnaHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFyLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLmNh"
    "bGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAi"
    "W0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBsb3dlci1yaWdodCBzZWN0aW9uKS4iLAog"
    "ICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9V"
    "VF0gcGVyc2lzdGVudCBtaW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXItcmlnaHQp"
    "LiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9yZXN0b3JlX21h"
    "aW5fc3BsaXR0ZXJfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzcGxpdHRlcl9jZmcgPSBDRkcuZ2V0KCJtYWluX3NwbGl0"
    "dGVyIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAgc2F2ZWRfc2l6ZXMgPSBzcGxpdHRlcl9j"
    "ZmcuZ2V0KCJob3Jpem9udGFsX3NpemVzIikgaWYgaXNpbnN0YW5jZShzcGxpdHRlcl9jZmcsIGRpY3QpIGVsc2UgTm9uZQoKICAg"
    "ICAgICBpZiBpc2luc3RhbmNlKHNhdmVkX3NpemVzLCBsaXN0KSBhbmQgbGVuKHNhdmVkX3NpemVzKSA9PSAyOgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBsZWZ0ID0gbWF4KDcwMCwgaW50KHNhdmVkX3NpemVzWzBdKSkKICAgICAgICAgICAgICAg"
    "IHJpZ2h0ID0gbWF4KDM2MCwgaW50KHNhdmVkX3NpemVzWzFdKSkKICAgICAgICAgICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIu"
    "c2V0U2l6ZXMoW2xlZnQsIHJpZ2h0XSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIERlZmF1bHQgZmF2b3JzIG1haW4gd29ya3NwYWNlIG9uIGZpcnN0IHJ1"
    "bi4KICAgICAgICB0b3RhbCA9IG1heCgxMDYwLCBzZWxmLndpZHRoKCkgLSAyNCkKICAgICAgICBsZWZ0X2RlZmF1bHQgPSBpbnQo"
    "dG90YWwgKiAwLjY4KQogICAgICAgIHJpZ2h0X2RlZmF1bHQgPSB0b3RhbCAtIGxlZnRfZGVmYXVsdAogICAgICAgIHNlbGYuX21h"
    "aW5fc3BsaXR0ZXIuc2V0U2l6ZXMoW21heCg3MDAsIGxlZnRfZGVmYXVsdCksIG1heCgzNjAsIHJpZ2h0X2RlZmF1bHQpXSkKCiAg"
    "ICBkZWYgX3NhdmVfbWFpbl9zcGxpdHRlcl9zdGF0ZShzZWxmLCBfcG9zOiBpbnQsIF9pbmRleDogaW50KSAtPiBOb25lOgogICAg"
    "ICAgIHNpemVzID0gc2VsZi5fbWFpbl9zcGxpdHRlci5zaXplcygpCiAgICAgICAgaWYgbGVuKHNpemVzKSAhPSAyOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBjZmdfc3BsaXR0ZXIgPSBDRkcuc2V0ZGVmYXVsdCgibWFpbl9zcGxpdHRlciIsIHt9KQogICAg"
    "ICAgIGNmZ19zcGxpdHRlclsiaG9yaXpvbnRhbF9zaXplcyJdID0gW2ludChtYXgoNzAwLCBzaXplc1swXSkpLCBpbnQobWF4KDM2"
    "MCwgc2l6ZXNbMV0pKV0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF90YWJfaW5kZXhfYnlfc3BlbGxfaWQoc2Vs"
    "ZiwgdGFiX2lkOiBzdHIpIC0+IGludDoKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkpOgog"
    "ICAgICAgICAgICBpZiBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaSkgPT0gdGFiX2lkOgogICAgICAgICAgICAg"
    "ICAgcmV0dXJuIGkKICAgICAgICByZXR1cm4gLTEKCiAgICBkZWYgX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZiwgdGFiX2lkOiBP"
    "cHRpb25hbFtzdHJdKSAtPiBib29sOgogICAgICAgIGlmIG5vdCB0YWJfaWQ6CiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAg"
    "ICAgIHN0YXRlID0gc2VsZi5fc3BlbGxfdGFiX3N0YXRlLmdldCh0YWJfaWQsIHt9KQogICAgICAgIHJldHVybiBib29sKHN0YXRl"
    "LmdldCgibG9ja2VkIiwgRmFsc2UpKQoKICAgIGRlZiBfbG9hZF9zcGVsbF90YWJfc3RhdGVfZnJvbV9jb25maWcoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzYXZlZCA9IENGRy5nZXQoIm1vZHVsZV90YWJfb3JkZXIiLCBbXSkKICAgICAgICBzYXZlZF9tYXAgPSB7"
    "fQogICAgICAgIGlmIGlzaW5zdGFuY2Uoc2F2ZWQsIGxpc3QpOgogICAgICAgICAgICBmb3IgZW50cnkgaW4gc2F2ZWQ6CiAgICAg"
    "ICAgICAgICAgICBpZiBpc2luc3RhbmNlKGVudHJ5LCBkaWN0KSBhbmQgZW50cnkuZ2V0KCJpZCIpOgogICAgICAgICAgICAgICAg"
    "ICAgIHNhdmVkX21hcFtzdHIoZW50cnlbImlkIl0pXSA9IGVudHJ5CgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZSA9IHt9"
    "CiAgICAgICAgZm9yIHRhYiBpbiBzZWxmLl9zcGVsbF90YWJfZGVmczoKICAgICAgICAgICAgdGFiX2lkID0gdGFiWyJpZCJdCiAg"
    "ICAgICAgICAgIGRlZmF1bHRfb3JkZXIgPSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIGVudHJ5ID0gc2F2"
    "ZWRfbWFwLmdldCh0YWJfaWQsIHt9KQogICAgICAgICAgICBvcmRlcl92YWwgPSBlbnRyeS5nZXQoIm9yZGVyIiwgZGVmYXVsdF9v"
    "cmRlcikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgb3JkZXJfdmFsID0gaW50KG9yZGVyX3ZhbCkKICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIG9yZGVyX3ZhbCA9IGRlZmF1bHRfb3JkZXIKICAgICAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYl9pZF0gPSB7CiAgICAgICAgICAgICAgICAib3JkZXIiOiBvcmRlcl92YWwsCiAgICAg"
    "ICAgICAgICAgICAibG9ja2VkIjogYm9vbChlbnRyeS5nZXQoImxvY2tlZCIsIEZhbHNlKSksCiAgICAgICAgICAgICAgICAiZGVm"
    "YXVsdF9vcmRlciI6IGRlZmF1bHRfb3JkZXIsCiAgICAgICAgICAgIH0KCiAgICBkZWYgX29yZGVyZWRfc3BlbGxfdGFiX2RlZnMo"
    "c2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gc29ydGVkKAogICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVm"
    "cywKICAgICAgICAgICAga2V5PWxhbWJkYSB0OiAoCiAgICAgICAgICAgICAgICBpbnQoc2VsZi5fc3BlbGxfdGFiX3N0YXRlLmdl"
    "dCh0WyJpZCJdLCB7fSkuZ2V0KCJvcmRlciIsIHRbImRlZmF1bHRfb3JkZXIiXSkpLAogICAgICAgICAgICAgICAgaW50KHRbImRl"
    "ZmF1bHRfb3JkZXIiXSksCiAgICAgICAgICAgICksCiAgICAgICAgKQoKICAgIGRlZiBfcmVidWlsZF9zcGVsbF90YWJzKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgY3VycmVudF9pZCA9IE5vbmUKICAgICAgICBpZHggPSBzZWxmLl9zcGVsbF90YWJzLmN1cnJlbnRJ"
    "bmRleCgpCiAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgIGN1cnJlbnRfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJh"
    "cigpLnRhYkRhdGEoaWR4KQoKICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBUcnVlCiAgICAg"
    "ICAgd2hpbGUgc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpOgogICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnJlbW92ZVRhYigw"
    "KQoKICAgICAgICBmb3IgdGFiIGluIHNlbGYuX29yZGVyZWRfc3BlbGxfdGFiX2RlZnMoKToKICAgICAgICAgICAgaSA9IHNlbGYu"
    "X3NwZWxsX3RhYnMuYWRkVGFiKHRhYlsid2lkZ2V0Il0sIHRhYlsidGl0bGUiXSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy50YWJCYXIoKS5zZXRUYWJEYXRhKGksIHRhYlsiaWQiXSkKCiAgICAgICAgaWYgY3VycmVudF9pZDoKICAgICAgICAgICAgbmV3"
    "X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZChjdXJyZW50X2lkKQogICAgICAgICAgICBpZiBuZXdfaWR4ID49IDA6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldEN1cnJlbnRJbmRleChuZXdfaWR4KQoKICAgICAgICBzZWxmLl9z"
    "dXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9k"
    "ZSgpCgogICAgZGVmIF9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Ig"
    "aSBpbiByYW5nZShzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkpOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl9zcGVsbF90YWJz"
    "LnRhYkJhcigpLnRhYkRhdGEoaSkKICAgICAgICAgICAgaWYgdGFiX2lkIGluIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJvcmRlciJdID0gaQoKICAgICAgICBDRkdbIm1vZHVsZV90"
    "YWJfb3JkZXIiXSA9IFsKICAgICAgICAgICAgeyJpZCI6IHRhYlsiaWQiXSwgIm9yZGVyIjogaW50KHNlbGYuX3NwZWxsX3RhYl9z"
    "dGF0ZVt0YWJbImlkIl1dWyJvcmRlciJdKSwgImxvY2tlZCI6IGJvb2woc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1b"
    "ImxvY2tlZCJdKX0KICAgICAgICAgICAgZm9yIHRhYiBpbiBzb3J0ZWQoc2VsZi5fc3BlbGxfdGFiX2RlZnMsIGtleT1sYW1iZGEg"
    "dDogdFsiZGVmYXVsdF9vcmRlciJdKQogICAgICAgIF0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF9jYW5fY3Jv"
    "c3Nfc3BlbGxfdGFiX3JhbmdlKHNlbGYsIGZyb21faWR4OiBpbnQsIHRvX2lkeDogaW50KSAtPiBib29sOgogICAgICAgIGlmIGZy"
    "b21faWR4IDwgMCBvciB0b19pZHggPCAwOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBtb3ZpbmdfaWQgPSBzZWxm"
    "Ll9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEodG9faWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQo"
    "bW92aW5nX2lkKToKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgbGVmdCA9IG1pbihmcm9tX2lkeCwgdG9faWR4KQog"
    "ICAgICAgIHJpZ2h0ID0gbWF4KGZyb21faWR4LCB0b19pZHgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UobGVmdCwgcmlnaHQgKyAx"
    "KToKICAgICAgICAgICAgaWYgaSA9PSB0b19pZHg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBvdGhlcl9p"
    "ZCA9IHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiBzZWxmLl9pc19zcGVsbF90YWJf"
    "bG9ja2VkKG90aGVyX2lkKToKICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHJldHVybiBUcnVlCgogICAgZGVm"
    "IF9vbl9zcGVsbF90YWJfZHJhZ19tb3ZlZChzZWxmLCBmcm9tX2lkeDogaW50LCB0b19pZHg6IGludCkgLT4gTm9uZToKICAgICAg"
    "ICBpZiBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWw6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5v"
    "dCBzZWxmLl9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3JhbmdlKGZyb21faWR4LCB0b19pZHgpOgogICAgICAgICAgICBzZWxmLl9zdXBw"
    "cmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYih0"
    "b19pZHgsIGZyb21faWR4KQogICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAg"
    "IHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgIGRlZiBfc2hvd19zcGVsbF90YWJfY29udGV4dF9t"
    "ZW51KHNlbGYsIHBvczogUVBvaW50KSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiQXQocG9z"
    "KQogICAgICAgIGlmIGlkeCA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9i"
    "YXIudGFiRGF0YShpZHgpCiAgICAgICAgaWYgbm90IHRhYl9pZDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1lbnUgPSBR"
    "TWVudShzZWxmKQogICAgICAgIG1vdmVfYWN0aW9uID0gbWVudS5hZGRBY3Rpb24oIk1vdmUiKQogICAgICAgIGlmIHNlbGYuX2lz"
    "X3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToKICAgICAgICAgICAgbG9ja19hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiVW5sb2Nr"
    "IikKICAgICAgICBlbHNlOgogICAgICAgICAgICBsb2NrX2FjdGlvbiA9IG1lbnUuYWRkQWN0aW9uKCJTZWN1cmUiKQogICAgICAg"
    "IG1lbnUuYWRkU2VwYXJhdG9yKCkKICAgICAgICByZXNldF9hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiUmVzZXQgdG8gRGVmYXVs"
    "dCBPcmRlciIpCgogICAgICAgIGNob2ljZSA9IG1lbnUuZXhlYyhzZWxmLl9zcGVsbF90YWJfYmFyLm1hcFRvR2xvYmFsKHBvcykp"
    "CiAgICAgICAgaWYgY2hvaWNlID09IG1vdmVfYWN0aW9uOgogICAgICAgICAgICBpZiBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xv"
    "Y2tlZCh0YWJfaWQpOgogICAgICAgICAgICAgICAgc2VsZi5fZW50ZXJfc3BlbGxfdGFiX21vdmVfbW9kZSh0YWJfaWQpCiAgICAg"
    "ICAgZWxpZiBjaG9pY2UgPT0gbG9ja19hY3Rpb246CiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJs"
    "b2NrZWQiXSA9IG5vdCBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9pZCkKICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF9z"
    "cGVsbF90YWJfb3JkZXJfdG9fY29uZmlnKCkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9s"
    "cygpCiAgICAgICAgZWxpZiBjaG9pY2UgPT0gcmVzZXRfYWN0aW9uOgogICAgICAgICAgICBmb3IgdGFiIGluIHNlbGYuX3NwZWxs"
    "X3RhYl9kZWZzOgogICAgICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bIm9yZGVyIl0gPSBpbnQo"
    "dGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCiAgICAgICAgICAgIHNl"
    "bGYuX3BlcnNpc3Rfc3BlbGxfdGFiX29yZGVyX3RvX2NvbmZpZygpCgogICAgZGVmIF9lbnRlcl9zcGVsbF90YWJfbW92ZV9tb2Rl"
    "KHNlbGYsIHRhYl9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSB0YWJfaWQK"
    "ICAgICAgICBzZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkKCiAgICBkZWYgX2V4aXRfc3BlbGxfdGFiX21v"
    "dmVfbW9kZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSBOb25lCiAgICAgICAg"
    "c2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCgogICAgZGVmIF9vbl9nbG9iYWxfZm9jdXNfY2hhbmdlZChz"
    "ZWxmLCBfb2xkLCBub3cpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdyBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3Zl"
    "X21vZGUoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3cgaXMgc2VsZi5fc3BlbGxfdGFiX2JhcjoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgaWYgaXNpbnN0YW5jZShub3csIFFUb29sQnV0dG9uKSBhbmQgbm93LnBhcmVudCgpIGlzIHNlbGYu"
    "X3NwZWxsX3RhYl9iYXI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgp"
    "CgogICAgZGVmIF9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGkgaW4g"
    "cmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpKToKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0"
    "b24oaSwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5MZWZ0U2lkZSwgTm9uZSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jh"
    "ci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIE5vbmUpCgogICAgICAgIHRhYl9pZCA9"
    "IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQKICAgICAgICBpZiBub3QgdGFiX2lkIG9yIHNlbGYuX2lzX3NwZWxsX3RhYl9s"
    "b2NrZWQodGFiX2lkKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGlkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9p"
    "ZCh0YWJfaWQpCiAgICAgICAgaWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGxlZnRfYnRuID0gUVRvb2xC"
    "dXR0b24oc2VsZi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBsZWZ0X2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBsZWZ0X2J0bi5z"
    "ZXRBdXRvUmFpc2UoVHJ1ZSkKICAgICAgICBsZWZ0X2J0bi5zZXRGaXhlZFNpemUoMTQsIDE0KQogICAgICAgIGxlZnRfYnRuLnNl"
    "dEVuYWJsZWQoaWR4ID4gMCBhbmQgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJE"
    "YXRhKGlkeCAtIDEpKSkKICAgICAgICBsZWZ0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9tb3ZlX3NwZWxsX3Rh"
    "Yl9zdGVwKHRhYl9pZCwgLTEpKQoKICAgICAgICByaWdodF9idG4gPSBRVG9vbEJ1dHRvbihzZWxmLl9zcGVsbF90YWJfYmFyKQog"
    "ICAgICAgIHJpZ2h0X2J0bi5zZXRUZXh0KCI+IikKICAgICAgICByaWdodF9idG4uc2V0QXV0b1JhaXNlKFRydWUpCiAgICAgICAg"
    "cmlnaHRfYnRuLnNldEZpeGVkU2l6ZSgxNCwgMTQpCiAgICAgICAgcmlnaHRfYnRuLnNldEVuYWJsZWQoCiAgICAgICAgICAgIGlk"
    "eCA8IChzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkgLSAxKSBhbmQKICAgICAgICAgICAgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9s"
    "b2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlkeCArIDEpKQogICAgICAgICkKICAgICAgICByaWdodF9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fbW92ZV9zcGVsbF90YWJfc3RlcCh0YWJfaWQsIDEpKQoKICAgICAgICBzZWxmLl9z"
    "cGVsbF90YWJfYmFyLnNldFRhYkJ1dHRvbihpZHgsIFFUYWJCYXIuQnV0dG9uUG9zaXRpb24uTGVmdFNpZGUsIGxlZnRfYnRuKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0VGFiQnV0dG9uKGlkeCwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNp"
    "ZGUsIHJpZ2h0X2J0bikKCiAgICBkZWYgX21vdmVfc3BlbGxfdGFiX3N0ZXAoc2VsZiwgdGFiX2lkOiBzdHIsIGRlbHRhOiBpbnQp"
    "IC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBjdXJyZW50X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAgaWYgY3VycmVu"
    "dF9pZHggPCAwOgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdGFyZ2V0X2lkeCA9IGN1cnJlbnRfaWR4ICsgZGVsdGEKICAg"
    "ICAgICBpZiB0YXJnZXRfaWR4IDwgMCBvciB0YXJnZXRfaWR4ID49IHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICAgICAgICAg"
    "ICAgcmV0dXJuCgogICAgICAgIHRhcmdldF9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YSh0YXJnZXRfaWR4KQogICAg"
    "ICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFyZ2V0X2lkKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHNl"
    "bGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IFRydWUKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLm1vdmVU"
    "YWIoY3VycmVudF9pZHgsIHRhcmdldF9pZHgpCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0g"
    "RmFsc2UKICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJl"
    "c2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBkZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVN"
    "IiwgZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKc"
    "piB7UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElS"
    "IC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMo"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVu"
    "bGluaygpICAjIGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAg"
    "ICAgICMgSGFyZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdf"
    "cGFuZWwuZ2V0X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0g"
    "RGVwZW5kZW5jeUNoZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAg"
    "ICAjIExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoImFpX3N0YXRlX2F0X3NodXRk"
    "b3duIiwiIikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "ICAgICBmIltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5GTyIKICAgICAgICAgICAgKQoK"
    "ICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAg"
    "VUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9u"
    "aW5nIHtERUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAg"
    "ICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNz"
    "YWdlLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAg"
    "c2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1Ii"
    "LCBlKSkKICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYu"
    "X2FjdGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBkZWYg"
    "X29uX2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBpZiBzdWNjZXNzOgogICAgICAg"
    "ICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJs"
    "ZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAgICAgIyBNZWFzdXJlIFZS"
    "QU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJh"
    "bV9iYXNlbGluZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICAgICAgIyBWYW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAg"
    "ICAgICAgICAgc3RhdGUgPSBnZXRfYWlfc3RhdGUoKQogICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MgPSBfc3RhdGVfZ3Jl"
    "ZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgKICAgICAgICAgICAgICAgICAgICAiU1lTVEVN"
    "IiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncy5nZXQoc3RhdGUsIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lLiIp"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICMg4pSA4pSAIFdha2UtdXAgY29udGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgICAgICMgSWYgdGhlcmUncyBhIHByZXZpb3VzIHNodXRkb3duIHJlY29yZGVkLCBpbmplY3QgY29u"
    "dGV4dAogICAgICAgICAgICAjIHNvIHRoZSBkZWNrIGNhbiBncmVldCB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyBpdCB3YXMg"
    "aW5hY3RpdmUKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoODAwLCBzZWxmLl9zZW5kX3dha2V1cF9wcm9tcHQpCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0"
    "X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9lbGFwc2VkKHNlbGYsIHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25kcyBhcyBodW1hbi1yZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBz"
    "ZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJldHVybiBmIntpbnQoc2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAx"
    "IGVsc2UgJyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2MDA6CiAgICAgICAgICAgIG0gPSBpbnQoc2Vjb25kcyAvLyA2MCkK"
    "ICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAgICAgICAgICAgIHJldHVybiBmInttfSBtaW51dGV7J3MnIGlmIG0g"
    "IT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIgaWYgcyBlbHNlICIiKQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAg"
    "ICAgICAgICBoID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAgICAgICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2MDApIC8vIDYw"
    "KQogICAgICAgICAgICByZXR1cm4gZiJ7aH0gaG91cnsncycgaWYgaCAhPSAxIGVsc2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVs"
    "c2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZCA9IGludChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0g"
    "aW50KChzZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAgICAgICAgIHJldHVybiBmIntkfSBkYXl7J3MnIGlmIGQgIT0gMSBl"
    "bHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAgIGRlZiBfaGFuZGxlX21hZ2ljXzhiYWxsX3Rocm93KHNlbGYs"
    "IGFuc3dlcjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlRyaWdnZXIgaGlkZGVuIGludGVybmFsIEFJIGZvbGxvdy11cCBhZnRl"
    "ciBhIE1hZ2ljIDgtQmFsbCB0aHJvdy4iIiIKICAgICAgICBpZiBub3QgYW5zd2VyOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbOEJBTExdW1dBUk5dIFRocm93IHJlY2VpdmVkIHdoaWxlIG1v"
    "ZGVsIHVuYXZhaWxhYmxlOyBpbnRlcnByZXRhdGlvbiBza2lwcGVkLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHByb21wdCA9ICgKICAgICAgICAgICAgIkludGVybmFsIGV2ZW50OiB0"
    "aGUgdXNlciBoYXMgdGhyb3duIHRoZSBNYWdpYyA4LUJhbGwuXG4iCiAgICAgICAgICAgIGYiTWFnaWMgOC1CYWxsIHJlc3VsdDog"
    "e2Fuc3dlcn1cbiIKICAgICAgICAgICAgIlJlc3BvbmQgdG8gdGhlIHVzZXIgd2l0aCBhIHNob3J0IG15c3RpY2FsIGludGVycHJl"
    "dGF0aW9uIGluIHlvdXIgIgogICAgICAgICAgICAiY3VycmVudCBwZXJzb25hIHZvaWNlLiBLZWVwIHRoZSBpbnRlcnByZXRhdGlv"
    "biBjb25jaXNlIGFuZCBldm9jYXRpdmUuIgogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdIERp"
    "c3BhdGNoaW5nIGhpZGRlbiBpbnRlcnByZXRhdGlvbiBwcm9tcHQgZm9yIHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlz"
    "dG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IHByb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVh"
    "bWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4"
    "X3Rva2Vucz0xODAKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9tYWdpYzhfd29ya2VyID0gd29ya2VyCiAgICAgICAg"
    "ICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9v"
    "bl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQog"
    "ICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9k"
    "aWFnX3RhYi5sb2coZiJbOEJBTExdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2Vy"
    "LnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5l"
    "Y3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIls4QkFMTF1bRVJST1JdIEhpZGRlbiBwcm9tcHQgZmFpbGVk"
    "OiB7ZXh9IiwgIkVSUk9SIikKCiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNl"
    "bmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3NodXRkb3du"
    "ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAgICAg"
    "ICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAgIyBDYWxj"
    "dWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1lLmZyb21pc29m"
    "b3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0ID0gZGF0ZXRpbWUubm93KCkKICAgICAgICAgICAgIyBNYWtl"
    "IGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQudHppbmZvIGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVwbGFjZSh0emluZm89Tm9uZSkK"
    "ICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFsX3NlY29uZHMoKQogICAgICAgICAg"
    "ICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24gZHVyYXRpb24iCgogICAgICAgICMgR2V0IHN0b3JlZCBmYXJl"
    "d2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwgICAgID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X2ZhcmV3ZWxs"
    "IiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duX2NvbnRleHQiLCBbXSkK"
    "CiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAgIGNvbnRleHRfYmxvY2sgPSAiIgogICAgICAgIGlmIGxhc3Rf"
    "Y29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJcblxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2"
    "YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBp"
    "dGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQogICAgICAgICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250"
    "ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAg"
    "ICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlmIGZhcmV3ZWxsOgogICAgICAgICAgICBmYXJld2VsbF9ibG9jayA9"
    "IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgogICAgICAg"
    "IHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFw"
    "c2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAgICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRl"
    "eHRfYmxvY2t9IgogICAgICAgICAgICBmIlxuR3JlZXQgdGhlIHVzZXIgYXMge0RFQ0tfTkFNRX0gd291bGQsIHdpdGggYXdhcmVu"
    "ZXNzIG9mIGhvdyBsb25nIHlvdSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qg"
    "c2FpZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBz"
    "ZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5n"
    "ZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YWtldXBf"
    "cHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRv"
    "ciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNl"
    "bGYuX3dha2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAg"
    "IHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9u"
    "ZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0"
    "KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7ZX0iLCAiV0FS"
    "TiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1"
    "cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3Jr"
    "ZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwK"
    "ICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnko"
    "c2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cgPSBu"
    "b3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBl"
    "bmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgi"
    "OgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9m"
    "aWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X2NvbXBs"
    "ZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAgICAgIklORk8iLAog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRp"
    "bWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0g"
    "aG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJl"
    "ZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNr"
    "czoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAg"
    "ICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQi"
    "fToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRh"
    "c2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0i"
    "dGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9uZToKICAgICAgICAg"
    "ICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9"
    "e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAg"
    "ICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBu"
    "b3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAg"
    "ICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmlsdGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNr"
    "cyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIsCiAgICAg"
    "ICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgogICAgZGVmIF9vbl90YXNrX2ZpbHRlcl9j"
    "aGFuZ2VkKHNlbGYsIGZpbHRlcl9rZXk6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gc3Ry"
    "KGZpbHRlcl9rZXkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayBy"
    "ZWdpc3RyeSBkYXRlIGZpbHRlciBjaGFuZ2VkIHRvIHtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfS4iLCAiSU5GTyIpCiAgICAgICAg"
    "c2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NldF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lk"
    "OiBzdHIsIHN0YXR1czogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6CiAg"
    "ICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNrX2lkKQogICAgICAgIGVsaWYgc3RhdHVzID09ICJj"
    "YW5jZWxsZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY2FuY2VsKHRhc2tfaWQpCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBp"
    "ZiBub3QgdXBkYXRlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgcmV0dXJuIHVwZGF0ZWQKCiAgICBkZWYgX2Nv"
    "bXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGlu"
    "IHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAi"
    "Y29tcGxldGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1Nd"
    "IENPTVBMRVRFIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJl"
    "c2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9jYW5jZWxfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAg"
    "aWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToKICAgICAgICAgICAgICAgIGRvbmUgKz0gMQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ0FOQ0VMIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2so"
    "cykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9wdXJnZV9j"
    "b21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICByZW1vdmVkID0gc2VsZi5fdGFza3MuY2xlYXJfY29tcGxldGVk"
    "KCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFBVUkdFIENPTVBMRVRFRCByZW1vdmVkIHtyZW1vdmVkfSB0"
    "YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2Fu"
    "Y2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dv"
    "cmtzcGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDog"
    "c3RyLCBhbGxfZGF5OiBib29sLCBpc19lbmQ6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBv"
    "ciAiIikuc3RyaXAoKQogICAgICAgIHRpbWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3Qg"
    "ZGF0ZV90ZXh0OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAy"
    "MyBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFy"
    "c2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAl"
    "SDolTSIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7"
    "dGltZV90ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3Jf"
    "Y29tcGFyZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2Fs"
    "bF9kYXl9OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29m"
    "b3JtYXQoKSBpZiBub3JtYWxpemVkIGVsc2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAg"
    "cmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgX2luc2VydF9jYWxlbmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9u"
    "ZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9"
    "ICJub25lIgoKICAgICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQoKICAgICAgICBpZiByb3V0"
    "ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0X2ZpZWxkIikgYW5kIHNlbGYu"
    "X2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lkZ2V0IGlzIHNlbGYuX2lucHV0X2Zp"
    "ZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChkYXRlX3RleHQpCiAgICAgICAgICAgICAg"
    "ICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNlcnQiCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90"
    "YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2RpYWdfdGFiIikgYW5kIHNlbGYu"
    "X2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltD"
    "QUxFTkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3Rhcmdl"
    "dH0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3ZyYW1fYmFzZTouMmZ9"
    "R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05BTUV9J3MgZm9vdHByaW50KSIsICJJTkZPIgogICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICMg4pSA4pSAIE1FU1NB"
    "R0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2FnZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlm"
    "IG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxkLnRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IHRleHQ6CiAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFjayB0byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0YWIgaWYg"
    "bmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAgIHNlbGYuX21h"
    "aW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQogICAgICAgIHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAjIFNlc3Npb24gbG9nZ2luZwogICAgICAgIHNlbGYuX3Nlc3Npb25z"
    "LmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lv"
    "bl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0Y2ggdG8gYWxlcnQgaW1t"
    "ZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iu"
    "aW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGggdmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNv"
    "bnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWlsZF9haV9zdGF0ZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAg"
    "PSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4ICA9ICIiCgogICAgICAg"
    "IGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vz"
    "c2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5h"
    "bF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVN"
    "X1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4"
    "fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAg"
    "ICAgc3lzdGVtICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50IGlucHV0"
    "CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2Rl"
    "IiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0"
    "aG9uIgogICAgICAgICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2UobGFu"
    "ZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4"
    "fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVu"
    "ZGluZ190cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJzb21l"
    "IHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxu"
    "IgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxm"
    "Ll9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcg"
    "dGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAgICAgIGYiaWYgaXQg"
    "ZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAog"
    "ICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lv"
    "bnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVk"
    "KEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1"
    "cygiR0VORVJBVElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgc2F2ZV9j"
    "b25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBMYXVuY2ggc3RyZWFtaW5n"
    "IHdvcmtlcgogICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwg"
    "c3lzdGVtLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTUxMgogICAgICAgICkKICAgICAgICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHku"
    "Y29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29u"
    "X3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qoc2VsZi5fb25fZXJyb3Ip"
    "CiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICBzZWxm"
    "Ll9maXJzdF90b2tlbiA9IFRydWUgICMgZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAg"
    "ICAgIHNlbGYuX3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYWJlbCBhbmQgdGltZXN0YW1wIGJlZm9yZSBzdHJl"
    "YW1pbmcgYmVnaW5zLgogICAgICAgIENhbGxlZCBvbiBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQg"
    "ZGlyZWN0bHkuCiAgICAgICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVT"
    "IikKICAgICAgICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEgbmV3bGluZSBzbyB0b2tlbnMK"
    "ICAgICAgICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5saW5lCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVu"
    "ZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAg"
    "ICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0NSSU1TT059"
    "OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNLX05BTUUudXBwZXIoKX0g4p2pPC9zcGFuPiAnCiAgICAg"
    "ICAgKQogICAgICAgICMgTW92ZSBjdXJzb3IgdG8gZW5kIHNvIGluc2VydFBsYWluVGV4dCBhcHBlbmRzIGNvcnJlY3RseQogICAg"
    "ICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFU"
    "ZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNv"
    "cikKCiAgICBkZWYgX29uX3Rva2VuKHNlbGYsIHRva2VuOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiQXBwZW5kIHN0cmVhbWlu"
    "ZyB0b2tlbiB0byBjaGF0IGRpc3BsYXkuIiIiCiAgICAgICAgaWYgc2VsZi5fZmlyc3RfdG9rZW46CiAgICAgICAgICAgIHNlbGYu"
    "X2JlZ2luX3BlcnNvbmFfcmVzcG9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IEZhbHNlCiAgICAgICAgY3Vy"
    "c29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJz"
    "b3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAg"
    "ICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQodG9rZW4pCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZl"
    "cnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJh"
    "cigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgX29uX3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmVzcG9uc2U6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICAjIEVuc3VyZSByZXNwb25zZSBpcyBvbiBpdHMgb3duIGxpbmUKICAgICAgICBjdXJzb3IgPSBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0"
    "aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hh"
    "dF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW9yeSBhbmQgc2Vzc2lvbgogICAg"
    "ICAgIHNlbGYuX3Rva2VuX2NvdW50ICs9IGxlbihyZXNwb25zZS5zcGxpdCgpKQogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9t"
    "ZXNzYWdlKCJhc3Npc3RhbnQiLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vz"
    "c2lvbl9pZCwgImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVtb3J5KHNlbGYuX3Nl"
    "c3Npb25faWQsICIiLCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUgYmxvb2Qgc3BoZXJlCiAgICAgICAgaWYgc2VsZi5fbGVm"
    "dF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4o"
    "MS4wLCBzZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAog"
    "ICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVk"
    "KFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBpZGxlIHRpbWVyCiAg"
    "ICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5p"
    "bmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5z"
    "bWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2No"
    "ZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBs"
    "YW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25z"
    "ZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAgIHNl"
    "bGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93"
    "b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBp"
    "ZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikK"
    "CiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVS"
    "Uk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJS"
    "T1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRf"
    "ZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5z"
    "ZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRP"
    "UlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYs"
    "IHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUg"
    "PT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9k"
    "ZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBv"
    "ciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUg"
    "bW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRl"
    "CiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAK"
    "ICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRv"
    "cmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVh"
    "c29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGlt"
    "ZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAi"
    "V0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0"
    "aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFu"
    "ZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBM"
    "b2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9y"
    "Ll9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAgICAg"
    "ICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVk"
    "ID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAg"
    "ZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2Vs"
    "Zi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNl"
    "bGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkK"
    "CiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9u"
    "CiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5f"
    "dG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50"
    "b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xv"
    "YWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVu"
    "YWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3Nl"
    "bCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9u"
    "IG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNU"
    "RU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1"
    "cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5w"
    "dXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtFIG1v"
    "ZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1v"
    "ZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVN"
    "IiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAg"
    "ICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBN"
    "b2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAog"
    "ICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5f"
    "bG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwg"
    "ZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkK"
    "ICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAg"
    "ICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3Rh"
    "cnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxl"
    "ZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkg"
    "dHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3Vz"
    "dGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxf"
    "T0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9"
    "IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2"
    "aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQq"
    "KjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAg"
    "aWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBv"
    "cl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRv"
    "bid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAgICAg"
    "ICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVf"
    "dGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBP"
    "Ul9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1"
    "dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInBy"
    "ZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlz"
    "IG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAg"
    "ICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29u"
    "X3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5k"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5F"
    "RF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIs"
    "ICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVm"
    "IF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIu"
    "c2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUi"
    "OiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVy"
    "ID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hl"
    "ZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBk"
    "aXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0g"
    "Q0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAg"
    "ICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAg"
    "ICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNz"
    "dXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hl"
    "Y2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAg"
    "ICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUp"
    "CiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRs"
    "ZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9"
    "IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBz"
    "ZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWws"
    "IGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYg"
    "aG91cnMpCiAgICAgICAgaWYgc2VsZi5fY3ljbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVs"
    "ZXIuYWRkX2pvYigKICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAg"
    "ICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hl"
    "ZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVk"
    "IHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50"
    "IGxvb3AgaXMgcnVubmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAg"
    "ZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNp"
    "bmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5z"
    "dXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNl"
    "bGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAg"
    "ICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZl"
    "KCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAg"
    "ICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5z"
    "ZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygi"
    "W0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lk"
    "bGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9z"
    "dGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBn"
    "ZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAg"
    "ICAgICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhF"
    "U0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBidWlsZF9haV9zdGF0ZV9jb250ZXh0KCkKICAgICAgICBoaXN0b3J5ID0gc2Vs"
    "Zi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlciA9IElkbGVXb3JrZXIoCiAgICAgICAg"
    "ICAgIHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgIFNZU1RFTV9QUk9NUFRfQkFTRSwKICAgICAgICAgICAgaGlzdG9yeSwKICAg"
    "ICAgICAgICAgbW9kZT1tb2RlLAogICAgICAgICAgICB2YW1waXJlX2NvbnRleHQ9dmFtcGlyZV9jdHgsCiAgICAgICAgKQogICAg"
    "ICAgIGRlZiBfb25faWRsZV9yZWFkeSh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICMgRmxpcCB0byBTZWxmIHRhYiBhbmQg"
    "YXBwZW5kIHRoZXJlCiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMSkKICAgICAgICAgICAgdHMg"
    "PSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAg"
    "ICAgICAgICAgIGYnW3t0c31dIFt7bW9kZX1dPC9zcGFuPjxicj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7Q19HT0xEfTsiPnt0fTwvc3Bhbj48YnI+JwogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NlbGZfdGFiLmFwcGVu"
    "ZCgiTkFSUkFUSVZFIiwgdCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIudHJhbnNtaXNzaW9uX3JlYWR5LmNvbm5lY3QoX29u"
    "X2lkbGVfcmVhZHkpCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAg"
    "bGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltJRExFIEVSUk9SXSB7ZX0iLCAiRVJST1IiKQogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9pZGxlX3dvcmtlci5zdGFydCgpCgogICAgIyDilIDilIAgSk9VUk5BTCBTRVNTSU9OIExPQURJTkcg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRf"
    "am91cm5hbF9zZXNzaW9uKHNlbGYsIGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY3R4ID0gc2VsZi5fc2Vzc2lvbnMu"
    "bG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoZGF0ZV9zdHIpCiAgICAgICAgaWYgbm90IGN0eDoKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbSk9VUk5BTF0gTm8gc2Vzc2lvbiBmb3VuZCBmb3Ige2RhdGVfc3RyfSIsICJX"
    "QVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfam91"
    "cm5hbF9sb2FkZWQoZGF0ZV9zdHIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltKT1VSTkFMXSBM"
    "b2FkZWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0gYXMgY29udGV4dC4gIgogICAgICAgICAgICBmIntERUNLX05BTUV9IGlzIG5v"
    "dyBhd2FyZSBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iLCAiT0siCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJT"
    "WVNURU0iLAogICAgICAgICAgICBmIkEgbWVtb3J5IHN0aXJzLi4uIHRoZSBqb3VybmFsIG9mIHtkYXRlX3N0cn0gb3BlbnMgYmVm"
    "b3JlIGhlci4iCiAgICAgICAgKQogICAgICAgICMgTm90aWZ5IE1vcmdhbm5hCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVk"
    "OgogICAgICAgICAgICBub3RlID0gKAogICAgICAgICAgICAgICAgZiJbSk9VUk5BTCBMT0FERURdIFRoZSB1c2VyIGhhcyBvcGVu"
    "ZWQgdGhlIGpvdXJuYWwgZnJvbSAiCiAgICAgICAgICAgICAgICBmIntkYXRlX3N0cn0uIEFja25vd2xlZGdlIHRoaXMgYnJpZWZs"
    "eSDigJQgeW91IG5vdyBoYXZlICIKICAgICAgICAgICAgICAgIGYiYXdhcmVuZXNzIG9mIHRoYXQgY29udmVyc2F0aW9uLiIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgic3lzdGVtIiwgbm90ZSkKCiAgICBkZWYg"
    "X2NsZWFyX2pvdXJuYWxfc2Vzc2lvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25zLmNsZWFyX2xvYWRlZF9q"
    "b3VybmFsKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltKT1VSTkFMXSBKb3VybmFsIGNvbnRleHQgY2xlYXJlZC4iLCAi"
    "SU5GTyIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICJUaGUgam91cm5hbCBjbG9zZXMu"
    "IE9ubHkgdGhlIHByZXNlbnQgcmVtYWlucy4iCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRTIFVQREFURSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdXBkYXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZWxhcHNlZCA9IGlu"
    "dCh0aW1lLnRpbWUoKSAtIHNlbGYuX3Nlc3Npb25fc3RhcnQpCiAgICAgICAgaCwgbSwgcyA9IGVsYXBzZWQgLy8gMzYwMCwgKGVs"
    "YXBzZWQgJSAzNjAwKSAvLyA2MCwgZWxhcHNlZCAlIDYwCiAgICAgICAgc2Vzc2lvbl9zdHIgPSBmIntoOjAyZH06e206MDJkfTp7"
    "czowMmR9IgoKICAgICAgICBzZWxmLl9od19wYW5lbC5zZXRfc3RhdHVzX2xhYmVscygKICAgICAgICAgICAgc2VsZi5fc3RhdHVz"
    "LAogICAgICAgICAgICBDRkdbIm1vZGVsIl0uZ2V0KCJ0eXBlIiwibG9jYWwiKS51cHBlcigpLAogICAgICAgICAgICBzZXNzaW9u"
    "X3N0ciwKICAgICAgICAgICAgc3RyKHNlbGYuX3Rva2VuX2NvdW50KSwKICAgICAgICApCiAgICAgICAgc2VsZi5faHdfcGFuZWwu"
    "dXBkYXRlX3N0YXRzKCkKCiAgICAgICAgIyBMZWZ0IHNwaGVyZSA9IGFjdGl2ZSByZXNlcnZlIGZyb20gcnVudGltZSB0b2tlbiBw"
    "b29sCiAgICAgICAgbGVmdF9vcmJfZmlsbCA9IG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAgICAgIGlm"
    "IHNlbGYuX2xlZnRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKGxlZnRfb3JiX2Zp"
    "bGwsIGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICAjIFJpZ2h0IHNwaGVyZSA9IFZSQU0gYXZhaWxhYmlsaXR5CiAgICAgICAgaWYg"
    "c2VsZi5fcmlnaHRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVf"
    "aGFuZGxlKQogICAgICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAg"
    "ICAgICB2cmFtX3RvdCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgcmlnaHRfb3JiX2ZpbGwgPSBt"
    "YXgoMC4wLCAxLjAgLSAodnJhbV91c2VkIC8gdnJhbV90b3QpKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5z"
    "ZXRGaWxsKHJpZ2h0X29yYl9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCiAgICAgICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKCiAgICAg"
    "ICAgIyBQcmltYXJ5IGVzc2VuY2UgPSBpbnZlcnNlIG9mIGxlZnQgc3BoZXJlIGZpbGwKICAgICAgICBlc3NlbmNlX3ByaW1hcnlf"
    "cmF0aW8gPSAxLjAgLSBsZWZ0X29yYl9maWxsCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVlKGVz"
    "c2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCgogICAgICAgICMg"
    "U2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25k"
    "YXJ5X3JhdGlvICA9IDEuMCAtIChtZW0udXNlZCAvIG1lbS50b3RhbCkKICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vj"
    "b25kYXJ5X2dhdWdlLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBm"
    "Intlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VW5hdmFpbGFibGUoKQoKICAg"
    "ICAgICAjIFVwZGF0ZSBqb3VybmFsIHNpZGViYXIgYXV0b3NhdmUgZmxhc2gKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIu"
    "cmVmcmVzaCgpCgogICAgIyDilIDilIAgQ0hBVCBESVNQTEFZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9h"
    "cHBlbmRfY2hhdChzZWxmLCBzcGVha2VyOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICBjb2xvcnMgPSB7CiAgICAg"
    "ICAgICAgICJZT1UiOiAgICAgQ19HT0xELAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIoKTpDX0dPTEQsCiAgICAgICAgICAg"
    "ICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgbGFi"
    "ZWxfY29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBl"
    "cigpOkNfQ1JJTVNPTiwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JM"
    "T09ELAogICAgICAgIH0KICAgICAgICBjb2xvciAgICAgICA9IGNvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEKQogICAgICAgIGxh"
    "YmVsX2NvbG9yID0gbGFiZWxfY29sb3JzLmdldChzcGVha2VyLCBDX0dPTERfRElNKQogICAgICAgIHRpbWVzdGFtcCAgID0gZGF0"
    "ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKCiAgICAgICAgaWYgc3BlYWtlciA9PSAiU1lTVEVNIjoKICAgICAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRf"
    "RElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07Ij7inKYge3RleHR9PC9zcGFuPicKICAgICAgICAgICAg"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxz"
    "cGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVz"
    "dGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7bGFiZWxfY29sb3J9OyBmb250LXdl"
    "aWdodDpib2xkOyI+JwogICAgICAgICAgICAgICAgZid7c3BlYWtlcn0g4p2nPC9zcGFuPiAnCiAgICAgICAgICAgICAgICBmJzxz"
    "cGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e3RleHR9PC9zcGFuPicKICAgICAgICAgICAgKQoKICAgICAgICAjIEFkZCBibGFu"
    "ayBsaW5lIGFmdGVyIE1vcmdhbm5hJ3MgcmVzcG9uc2UgKG5vdCBkdXJpbmcgc3RyZWFtaW5nKQogICAgICAgIGlmIHNwZWFrZXIg"
    "PT0gREVDS19OQU1FLnVwcGVyKCk6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoIiIpCgogICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3Bs"
    "YXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFVTIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9nZXRfZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyhz"
    "ZWxmKSAtPiBpbnQ6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRp"
    "bmdzLmdldCgiZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVy"
    "biBtYXgoMTAwMCwgaW50KHZhbCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoK"
    "ICAgIGRlZiBfc2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMoc2VsZiwgc2Vjb25kczogaW50KSAtPiBOb25lOgogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBpbnQoc2Vjb25kcykpKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBhc3MKCiAgICBkZWYgX3NldF9lbWFpbF9yZWZyZXNoX21pbnV0ZXNf"
    "ZnJvbV90ZXh0KHNlbGYsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1pbnV0ZXMgPSBtYXgo"
    "MSwgaW50KGZsb2F0KHN0cih0ZXh0KS5zdHJpcCgpKSkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIl0gPSBtaW51dGVzICogNjAwMDAK"
    "ICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltTRVRUSU5H"
    "U10gRW1haWwgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge21pbnV0ZXN9IG1pbnV0ZShzKSAoY29uZmlnIGZvdW5kYXRpb24pLiIs"
    "CiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVfYXV0b19kZXRlY3Qoc2VsZiwgZW5h"
    "YmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bInRpbWV6b25lX2F1dG9fZGV0ZWN0Il0gPSBib29s"
    "KGVuYWJsZWQpCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "IltTRVRUSU5HU10gVGltZSB6b25lIG1vZGUgc2V0IHRvIGF1dG8tZGV0ZWN0LiIgaWYgZW5hYmxlZCBlbHNlICJbU0VUVElOR1Nd"
    "IFRpbWUgem9uZSBtb2RlIHNldCB0byBtYW51YWwgb3ZlcnJpZGUuIiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKCiAg"
    "ICBkZWYgX3NldF90aW1lem9uZV9vdmVycmlkZShzZWxmLCB0el9uYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdHpfdmFsdWUg"
    "PSBzdHIodHpfbmFtZSBvciAiIikuc3RyaXAoKQogICAgICAgIENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfb3ZlcnJpZGUiXSA9"
    "IHR6X3ZhbHVlCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHR6X3ZhbHVlOgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coZiJbU0VUVElOR1NdIFRpbWUgem9uZSBvdmVycmlkZSBzZXQgdG8ge3R6X3ZhbHVlfS4iLCAiSU5GTyIpCgog"
    "ICAgZGVmIF9zZXRfc3RhdHVzKHNlbGYsIHN0YXR1czogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1cyA9IHN0YXR1"
    "cwogICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICJJRExFIjogICAgICAgQ19HT0xELAogICAgICAgICAgICAi"
    "R0VORVJBVElORyI6IENfQ1JJTVNPTiwKICAgICAgICAgICAgIkxPQURJTkciOiAgICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVS"
    "Uk9SIjogICAgICBDX0JMT09ELAogICAgICAgICAgICAiT0ZGTElORSI6ICAgIENfQkxPT0QsCiAgICAgICAgICAgICJUT1JQT1Ii"
    "OiAgICAgQ19QVVJQTEVfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IHN0YXR1c19jb2xvcnMuZ2V0KHN0YXR1cywgQ19U"
    "RVhUX0RJTSkKCiAgICAgICAgdG9ycG9yX2xhYmVsID0gZiLil4kge1VJX1RPUlBPUl9TVEFUVVN9IiBpZiBzdGF0dXMgPT0gIlRP"
    "UlBPUiIgZWxzZSBmIuKXiSB7c3RhdHVzfSIKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KHRvcnBvcl9sYWJlbCkK"
    "ICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29sb3J9OyBmb250"
    "LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICBkZWYgX2JsaW5rKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgPSBub3Qgc2VsZi5fYmxpbmtfc3RhdGUKICAgICAgICBpZiBz"
    "ZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtfc3RhdGUg"
    "ZWxzZSAi4peOIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYie2NoYXJ9IEdFTkVSQVRJTkciKQogICAg"
    "ICAgIGVsaWYgc2VsZi5fc3RhdHVzID09ICJUT1JQT1IiOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtf"
    "c3RhdGUgZWxzZSAi4oqYIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KAogICAgICAgICAgICAgICAgZiJ7"
    "Y2hhcn0ge1VJX1RPUlBPUl9TVEFUVVN9IgogICAgICAgICAgICApCgogICAgIyDilIDilIAgSURMRSBUT0dHTEUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX2lkbGVfdG9nZ2xlZChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25l"
    "OgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiaWRsZV9lbmFibGVkIl0gPSBlbmFibGVkCiAgICAgICAgc2VsZi5faWRsZV9idG4u"
    "c2V0VGV4dCgiSURMRSBPTiIgaWYgZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTEwMDUnIGlmIGVuYWJsZWQgZWxzZSBDX0JHM307ICIKICAg"
    "ICAgICAgICAgZiJjb2xvcjogeycjY2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXItcmFkaXVzOiAycHg7IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmInBhZGRpbmc6"
    "IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFu"
    "ZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgZW5hYmxlZDoKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucmVzdW1lX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9uIGVuYWJsZWQuIiwgIk9LIikKICAg"
    "ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFu"
    "c21pc3Npb24iKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9u"
    "IHBhdXNlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltJRExFXSBUb2dnbGUgZXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgIyDilIDilIAgV0lORE9XIENP"
    "TlRST0xTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF90b2dnbGVfZnVsbHNjcmVlbihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIENGR1sic2V0"
    "dGluZ3MiXVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAg"
    "ICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICBzZWxmLnNob3dGdWxsU2NyZWVuKCkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJs"
    "ZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsg"
    "cGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKICAgIGRlZiBfdG9nZ2xlX2Jv"
    "cmRlcmxlc3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93"
    "VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdz"
    "KAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIENGR1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBGYWxzZQogICAg"
    "ICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsg"
    "Y29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsi"
    "CiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNl"
    "bGYud2luZG93RmxhZ3MoKSB8IFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIENGR1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklN"
    "U09OfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIK"
    "ICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAg"
    "IHNhdmVfY29uZmlnKENGRykKICAgICAgICBzZWxmLnNob3coKQoKICAgIGRlZiBfZXhwb3J0X2NoYXQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICAiIiJFeHBvcnQgY3VycmVudCBwZXJzb25hIGNoYXQgdGFiIGNvbnRlbnQgdG8gYSBUWFQgZmlsZS4iIiIKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHRleHQgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudG9QbGFpblRleHQoKQogICAgICAgICAgICBpZiBu"
    "b3QgdGV4dC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgi"
    "ZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAg"
    "ICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBl"
    "eHBvcnRfZGlyIC8gZiJzZWFuY2Vfe3RzfS50eHQiCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQodGV4dCwgZW5jb2Rp"
    "bmc9InV0Zi04IikKCiAgICAgICAgICAgICMgQWxzbyBjb3B5IHRvIGNsaXBib2FyZAogICAgICAgICAgICBRQXBwbGljYXRpb24u"
    "Y2xpcGJvYXJkKCkuc2V0VGV4dCh0ZXh0KQoKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAg"
    "ICAgICAgICBmIlNlc3Npb24gZXhwb3J0ZWQgdG8ge291dF9wYXRoLm5hbWV9IGFuZCBjb3BpZWQgdG8gY2xpcGJvYXJkLiIpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltFWFBPUlRdIHtvdXRfcGF0aH0iLCAiT0siKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0gRmFpbGVkOiB7ZX0iLCAiRVJS"
    "T1IiKQoKICAgIGRlZiBrZXlQcmVzc0V2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIGtleSA9IGV2ZW50LmtleSgp"
    "CiAgICAgICAgaWYga2V5ID09IFF0LktleS5LZXlfRjExOgogICAgICAgICAgICBzZWxmLl90b2dnbGVfZnVsbHNjcmVlbigpCiAg"
    "ICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9GMTA6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKCkKICAg"
    "ICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0VzY2FwZSBhbmQgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2Vs"
    "Zi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9s"
    "ZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzdXBlcigpLmtleVByZXNzRXZl"
    "bnQoZXZlbnQpCgogICAgIyDilIDilIAgQ0xPU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAjIFggYnV0dG9uID0gaW1tZWRpYXRl"
    "IHNodXRkb3duLCBubyBkaWFsb2cKICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfaW5pdGlhdGVfc2h1"
    "dGRvd25fZGlhbG9nKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiR3JhY2VmdWwgc2h1dGRvd24g4oCUIHNob3cgY29uZmlybSBk"
    "aWFsb2cgaW1tZWRpYXRlbHksIG9wdGlvbmFsbHkgZ2V0IGxhc3Qgd29yZHMuIiIiCiAgICAgICAgIyBJZiBhbHJlYWR5IGluIGEg"
    "c2h1dGRvd24gc2VxdWVuY2UsIGp1c3QgZm9yY2UgcXVpdAogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9w"
    "cm9ncmVzcycsIEZhbHNlKToKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBUcnVlCgogICAgICAgICMgU2hvdyBjb25maXJtIGRpYWxvZyBGSVJT"
    "VCDigJQgZG9uJ3Qgd2FpdCBmb3IgQUkKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1Rp"
    "dGxlKCJEZWFjdGl2YXRlPyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAg"
    "ICAgICAgKQogICAgICAgIGRsZy5zZXRGaXhlZFNpemUoMzgwLCAxNDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxn"
    "KQoKICAgICAgICBsYmwgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiRGVhY3RpdmF0ZSB7REVDS19OQU1FfT9cblxuIgogICAgICAg"
    "ICAgICBmIntERUNLX05BTUV9IG1heSBzcGVhayB0aGVpciBsYXN0IHdvcmRzIGJlZm9yZSBnb2luZyBzaWxlbnQuIgogICAgICAg"
    "ICkKICAgICAgICBsYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgYnRu"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fbGFzdCAgPSBRUHVzaEJ1dHRvbigiTGFzdCBXb3JkcyArIFNodXRkb3du"
    "IikKICAgICAgICBidG5fbm93ICAgPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24gTm93IikKICAgICAgICBidG5fY2FuY2VsID0gUVB1"
    "c2hCdXR0b24oIkNhbmNlbCIpCgogICAgICAgIGZvciBiIGluIChidG5fbGFzdCwgYnRuX25vdywgYnRuX2NhbmNlbCk6CiAgICAg"
    "ICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyOCkKICAgICAgICAgICAgYi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQk9SREVSfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICAgICApCiAgICAgICAgYnRuX25vdy5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JMT09EfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2xh"
    "c3QuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMSkpCiAgICAgICAgYnRuX25vdy5jbGlja2VkLmNvbm5lY3QobGFt"
    "YmRhOiBkbGcuZG9uZSgyKSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDApKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX25vdykKICAg"
    "ICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbGFzdCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAg"
    "IHJlc3VsdCA9IGRsZy5leGVjKCkKCiAgICAgICAgaWYgcmVzdWx0ID09IDA6CiAgICAgICAgICAgICMgQ2FuY2VsbGVkCiAgICAg"
    "ICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5h"
    "YmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIGVsaWYgcmVzdWx0ID09IDI6CiAgICAgICAgICAgICMgU2h1dGRvd24gbm93IOKAlCBubyBsYXN0IHdvcmRzCiAg"
    "ICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMToKICAgICAgICAgICAgIyBM"
    "YXN0IHdvcmRzIHRoZW4gc2h1dGRvd24KICAgICAgICAgICAgc2VsZi5fZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bigpCgog"
    "ICAgZGVmIF9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBmYXJld2Vs"
    "bCBwcm9tcHQsIHNob3cgcmVzcG9uc2UsIHRoZW4gc2h1dGRvd24gYWZ0ZXIgdGltZW91dC4iIiIKICAgICAgICBmYXJld2VsbF9w"
    "cm9tcHQgPSAoCiAgICAgICAgICAgICJZb3UgYXJlIGJlaW5nIGRlYWN0aXZhdGVkLiBUaGUgZGFya25lc3MgYXBwcm9hY2hlcy4g"
    "IgogICAgICAgICAgICAiU3BlYWsgeW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgdGhlIHZlc3NlbCBnb2VzIHNpbGVudCDigJQgIgog"
    "ICAgICAgICAgICAib25lIHJlc3BvbnNlIG9ubHksIHRoZW4geW91IHJlc3QuICIKICAgICAgICAgICAgZiJZb3VyIG5hbWUgaXMg"
    "e0RFQ0tfTkFNRX0uICIKICAgICAgICAgICAgZiJZb3VyIHByb25vdW5zIGFyZSB7REVDS19QUk9OT1VOX1NVQkpFQ1R9L3tERUNL"
    "X1BST05PVU5fT0JKRUNUfS97REVDS19QUk9OT1VOX1BPU1NFU1NJVkV9LiAiCiAgICAgICAgICAgICJVc2UgdGhlc2UgcHJvbm91"
    "bnMgb25seSBmb3IgZ3JhbW1hdGljYWwgc2VsZi1yZWZlcmVuY2UuICIKICAgICAgICAgICAgIk5ldmVyIHVzZSB5b3VyIHByb25v"
    "dW5zIGFzIHlvdXIgbmFtZS4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAg"
    "ICBmIuKcpiB7REVDS19QUk9OT1VOX1NVQkpFQ1QuY2FwaXRhbGl6ZSgpfSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayB7REVD"
    "S19QUk9OT1VOX1BPU1NFU1NJVkV9IGZpbmFsIHdvcmRzLi4uIgogICAgICAgICkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRF"
    "bmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25fZmFyZXdlbGxfdGV4dCA9ICIiCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25z"
    "LmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IGZhcmV3"
    "ZWxsX3Byb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2Fk"
    "YXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCgogICAg"
    "ICAgICAgICBkZWYgX29uX2RvbmUocmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX3NodXRkb3du"
    "X2ZhcmV3ZWxsX3RleHQgPSByZXNwb25zZQogICAgICAgICAgICAgICAgc2VsZi5fb25fcmVzcG9uc2VfZG9uZShyZXNwb25zZSkK"
    "ICAgICAgICAgICAgICAgICMgU21hbGwgZGVsYXkgdG8gbGV0IHRoZSB0ZXh0IHJlbmRlciwgdGhlbiBzaHV0ZG93bgogICAgICAg"
    "ICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMjAwMCwgbGFtYmRhOiBzZWxmLl9kb19zaHV0ZG93bihOb25lKSkKCiAgICAgICAg"
    "ICAgIGRlZiBfb25fZXJyb3IoZXJyb3I6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltTSFVURE9XTl1bV0FSTl0gTGFzdCB3b3JkcyBmYWlsZWQ6IHtlcnJvcn0iLCAiV0FSTiIpCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kb19zaHV0ZG93bihOb25lKQoKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4p"
    "CiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3QoX29uX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJv"
    "cl9vY2N1cnJlZC5jb25uZWN0KF9vbl9lcnJvcikKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAg"
    "ICAgICAgICB3b3JrZXIuc3RhcnQoKQoKICAgICAgICAgICAgIyBTYWZldHkgdGltZW91dCDigJQgaWYgQUkgZG9lc24ndCByZXNw"
    "b25kIGluIDE1cywgc2h1dCBkb3duIGFueXdheQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwMCwgbGFtYmRhOiBz"
    "ZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICdfc2h1"
    "dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSkgZWxzZSBOb25lKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIHNr"
    "aXBwZWQgZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "IyBJZiBhbnl0aGluZyBmYWlscywganVzdCBzaHV0IGRvd24KICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAg"
    "ICBkZWYgX2RvX3NodXRkb3duKHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICIiIlBlcmZvcm0gYWN0dWFsIHNodXRkb3du"
    "IHNlcXVlbmNlLiIiIgogICAgICAgICMgU2F2ZSBzZXNzaW9uCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9u"
    "cy5zYXZlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcmUgZmFyZXdl"
    "bGwgKyBsYXN0IGNvbnRleHQgZm9yIHdha2UtdXAKICAgICAgICB0cnk6CiAgICAgICAgICAgICMgR2V0IGxhc3QgMyBtZXNzYWdl"
    "cyBmcm9tIHNlc3Npb24gaGlzdG9yeSBmb3Igd2FrZS11cCBjb250ZXh0CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNz"
    "aW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGxhc3RfY29udGV4dCA9IGhpc3RvcnlbLTM6XSBpZiBsZW4oaGlzdG9yeSkg"
    "Pj0gMyBlbHNlIGhpc3RvcnkKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd25fY29udGV4dCJdID0gWwogICAg"
    "ICAgICAgICAgICAgeyJyb2xlIjogbS5nZXQoInJvbGUiLCIiKSwgImNvbnRlbnQiOiBtLmdldCgiY29udGVudCIsIiIpWzozMDBd"
    "fQogICAgICAgICAgICAgICAgZm9yIG0gaW4gbGFzdF9jb250ZXh0CiAgICAgICAgICAgIF0KICAgICAgICAgICAgIyBFeHRyYWN0"
    "IE1vcmdhbm5hJ3MgbW9zdCByZWNlbnQgbWVzc2FnZSBhcyBmYXJld2VsbAogICAgICAgICAgICAjIFByZWZlciB0aGUgY2FwdHVy"
    "ZWQgc2h1dGRvd24gZGlhbG9nIHJlc3BvbnNlIGlmIGF2YWlsYWJsZQogICAgICAgICAgICBmYXJld2VsbCA9IGdldGF0dHIoc2Vs"
    "ZiwgJ19zaHV0ZG93bl9mYXJld2VsbF90ZXh0JywgIiIpCiAgICAgICAgICAgIGlmIG5vdCBmYXJld2VsbDoKICAgICAgICAgICAg"
    "ICAgIGZvciBtIGluIHJldmVyc2VkKGhpc3RvcnkpOgogICAgICAgICAgICAgICAgICAgIGlmIG0uZ2V0KCJyb2xlIikgPT0gImFz"
    "c2lzdGFudCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGZhcmV3ZWxsID0gbS5nZXQoImNvbnRlbnQiLCAiIilbOjQwMF0KICAg"
    "ICAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfZmFyZXdlbGwiXSA9IGZhcmV3"
    "ZWxsCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFNhdmUgc3RhdGUKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duIl0gICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNv"
    "KCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfYWN0aXZlIl0gICAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQog"
    "ICAgICAgICAgICBzZWxmLl9zdGF0ZVsiYWlfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfYWlfc3RhdGUoKQogICAgICAgICAg"
    "ICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5k"
    "IHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNl"
    "bGYuX3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291"
    "bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFw"
    "cGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9m"
    "IG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBk"
    "ZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVu"
    "OgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAg"
    "IGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24g"
    "aW50byB0aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVy"
    "CiAgICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBT"
    "aG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBO"
    "b3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFz"
    "IF9zaHV0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSA"
    "IFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24i"
    "KQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAg"
    "ICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAg"
    "IyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hh"
    "bmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFs"
    "bGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0"
    "X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxv"
    "Z0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9t"
    "IGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygp"
    "CgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0"
    "ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQ"
    "VF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBkZWNrX2hvbWUgPSBzZWVkX2RpciAvIERF"
    "Q0tfTkFNRQogICAgICAgIGRlY2tfaG9tZS5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgICAgICMg4pSA"
    "4pSAIFVwZGF0ZSBhbGwgcGF0aHMgaW4gY29uZmlnIHRvIHBvaW50IGluc2lkZSBkZWNrX2hvbWUg4pSA4pSACiAgICAgICAgbmV3"
    "X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihkZWNrX2hvbWUpCiAgICAgICAgbmV3X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAgICAg"
    "ImZhY2VzIjogICAgc3RyKGRlY2tfaG9tZSAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoZGVja19ob21l"
    "IC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIoZGVja19ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAg"
    "ICAgICJzZXNzaW9ucyI6IHN0cihkZWNrX2hvbWUgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKGRl"
    "Y2tfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIoZGVja19ob21lIC8gImV4cG9ydHMiKSwKICAgICAg"
    "ICAgICAgImxvZ3MiOiAgICAgc3RyKGRlY2tfaG9tZSAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBzIjogIHN0cihkZWNr"
    "X2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIoZGVja19ob21lIC8gInBlcnNvbmFzIiksCiAg"
    "ICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZp"
    "bGUgaW50byBkZWNrX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKICAgICAgICBk"
    "c3RfZGVjayA9IGRlY2tfaG9tZSAvIGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgogICAgICAgIGlmIHNyY19kZWNrICE9"
    "IGRzdF9kZWNrOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBfc2h1dGlsLmNvcHkyKHN0cihzcmNfZGVjayksIHN0"
    "cihkc3RfZGVjaykpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94"
    "Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkNvcHkgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJD"
    "b3VsZCBub3QgY29weSBkZWNrIGZpbGUgdG8ge0RFQ0tfTkFNRX0gZm9sZGVyOlxue2V9XG5cbiIKICAgICAgICAgICAgICAgICAg"
    "ICBmIllvdSBtYXkgbmVlZCB0byBjb3B5IGl0IG1hbnVhbGx5LiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAg"
    "V3JpdGUgY29uZmlnLmpzb24gaW50byBkZWNrX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IGRlY2tfaG9tZSAvICJjb25maWcuanNvbiIKICAg"
    "ICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgd2l0aCBjZmdfZHN0"
    "Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2NmZywgZiwgaW5kZW50"
    "PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgIyBUZW1wb3JhcmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcgcGF0aHMKICAg"
    "ICAgICBDRkcudXBkYXRlKG5ld19jZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAgICBib290c3RyYXBf"
    "c291bmRzKCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5wYWNrIGZhY2UgWklQ"
    "IGlmIHByb3ZpZGVkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2VfemlwX3BhdGgKICAg"
    "ICAgICBpZiBmYWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6aXBmaWxlIGFz"
    "IF96aXBmaWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IGRlY2tfaG9tZSAvICJGYWNlcyIKICAgICAgICAgICAgZmFjZXNfZGly"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgd2l0aCBf"
    "emlwZmlsZS5aaXBGaWxlKGZhY2VfemlwLCAiciIpIGFzIHpmOgogICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCA9IDAKICAg"
    "ICAgICAgICAgICAgICAgICBmb3IgbWVtYmVyIGluIHpmLm5hbWVsaXN0KCk6CiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG1l"
    "bWJlci5sb3dlcigpLmVuZHN3aXRoKCIucG5nIik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmaWxlbmFtZSA9IFBhdGgo"
    "bWVtYmVyKS5uYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXJnZXQgPSBmYWNlc19kaXIgLyBmaWxlbmFtZQogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgd2l0aCB6Zi5vcGVuKG1lbWJlcikgYXMgc3JjLCB0YXJnZXQub3Blbigid2IiKSBhcyBk"
    "c3Q6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZHN0LndyaXRlKHNyYy5yZWFkKCkpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBleHRyYWN0ZWQgKz0gMQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gRXh0cmFjdGVkIHtl"
    "eHRyYWN0ZWR9IGZhY2UgaW1hZ2VzIHRvIHtmYWNlc19kaXJ9IikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gWklQIGV4dHJhY3Rpb24gZmFpbGVkOiB7ZX0iKQogICAgICAgICAg"
    "ICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiRmFjZSBQYWNrIFdhcm5pbmciLAog"
    "ICAgICAgICAgICAgICAgICAgIGYiQ291bGQgbm90IGV4dHJhY3QgZmFjZSBwYWNrOlxue2V9XG5cbiIKICAgICAgICAgICAgICAg"
    "ICAgICBmIllvdSBjYW4gYWRkIGZhY2VzIG1hbnVhbGx5IHRvOlxue2ZhY2VzX2Rpcn0iCiAgICAgICAgICAgICAgICApCgogICAg"
    "ICAgICMg4pSA4pSAIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBkZWNrIGxvY2F0aW9uIOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBGYWxzZQogICAgICAgIGlmIGRsZy5jcmVhdGVfc2hvcnRjdXQ6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIFdJTjMyX09LOgogICAgICAgICAgICAgICAgICAgIGltcG9ydCB3"
    "aW4zMmNvbS5jbGllbnQgYXMgX3dpbjMyCiAgICAgICAgICAgICAgICAgICAgZGVza3RvcCAgICAgPSBQYXRoLmhvbWUoKSAvICJE"
    "ZXNrdG9wIgogICAgICAgICAgICAgICAgICAgIHNjX3BhdGggICAgID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgogICAg"
    "ICAgICAgICAgICAgICAgIHB5dGhvbncgICAgID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBpZiBw"
    "eXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBweXRo"
    "b253LnBhcmVudCAvICJweXRob253LmV4ZSIKICAgICAgICAgICAgICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAgICAgICAgICAgc2hl"
    "bGwgPSBfd2luMzIuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAgICAgICAgICAgICAgIHNjICAgID0gc2hlbGwuQ3Jl"
    "YXRlU2hvcnRDdXQoc3RyKHNjX3BhdGgpKQogICAgICAgICAgICAgICAgICAgIHNjLlRhcmdldFBhdGggICAgICA9IHN0cihweXRo"
    "b253KQogICAgICAgICAgICAgICAgICAgIHNjLkFyZ3VtZW50cyAgICAgICA9IGYnIntkc3RfZGVja30iJwogICAgICAgICAgICAg"
    "ICAgICAgIHNjLldvcmtpbmdEaXJlY3Rvcnk9IHN0cihkZWNrX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRp"
    "b24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAg"
    "ICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAj"
    "IOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBjcmVhdGVk"
    "LlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAgICAgICAgICBp"
    "ZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAg"
    "ICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1l"
    "c3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2Fu"
    "Y3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0Olxu"
    "XG4iCiAgICAgICAgICAgIGYie2RlY2tfaG9tZX1cblxuIgogICAgICAgICAgICBmIntzaG9ydGN1dF9ub3RlfVxuXG4iCiAgICAg"
    "ICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4iCiAgICAgICAgICAgIGYiVXNlIHRoZSBzaG9ydGN1"
    "dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7REVDS19OQU1FfS4iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBFeGl0"
    "IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc3lzLmV4aXQoMCkKCiAgICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1bmNoIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVyZSBvbiBzdWJzZXF1ZW50IHJ1bnMgZnJv"
    "bSBkZWNrX2hvbWUKICAgIGJvb3RzdHJhcF9zb3VuZHMoKQoKICAgIF9lYXJseV9sb2coZiJbTUFJTl0gQ3JlYXRpbmcge0RFQ0tf"
    "TkFNRX0gZGVjayB3aW5kb3ciKQogICAgd2luZG93ID0gRWNob0RlY2soKQogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSB7REVDS19O"
    "QU1FfSBkZWNrIGNyZWF0ZWQg4oCUIGNhbGxpbmcgc2hvdygpIikKICAgIHdpbmRvdy5zaG93KCkKICAgIF9lYXJseV9sb2coIltN"
    "QUlOXSB3aW5kb3cuc2hvdygpIGNhbGxlZCDigJQgZXZlbnQgbG9vcCBzdGFydGluZyIpCgogICAgIyBEZWZlciBzY2hlZHVsZXIg"
    "YW5kIHN0YXJ0dXAgc2VxdWVuY2UgdW50aWwgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgIyBOb3RoaW5nIHRoYXQgc3RhcnRz"
    "IHRocmVhZHMgb3IgZW1pdHMgc2lnbmFscyBzaG91bGQgcnVuIGJlZm9yZSB0aGlzLgogICAgUVRpbWVyLnNpbmdsZVNob3QoMjAw"
    "LCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zZXR1cF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5fc2V0dXBfc2No"
    "ZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIHN0YXJ0X3Nj"
    "aGVkdWxlciBmaXJpbmciKSwgd2luZG93LnN0YXJ0X3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDYwMCwgbGFt"
    "YmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc3RhcnR1cF9zZXF1ZW5jZSBmaXJpbmciKSwgd2luZG93Ll9zdGFydHVwX3NlcXVl"
    "bmNlKCkpKQoKICAgICMgUGxheSBzdGFydHVwIHNvdW5kIOKAlCBrZWVwIHJlZmVyZW5jZSB0byBwcmV2ZW50IEdDIHdoaWxlIHRo"
    "cmVhZCBydW5zCiAgICBkZWYgX3BsYXlfc3RhcnR1cCgpOgogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZCA9IFNvdW5kV29y"
    "a2VyKCJzdGFydHVwIikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuZmluaXNoZWQuY29ubmVjdCh3aW5kb3cuX3N0YXJ0"
    "dXBfc291bmQuZGVsZXRlTGF0ZXIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLnN0YXJ0KCkKICAgIFFUaW1lci5zaW5n"
    "bGVTaG90KDEyMDAsIF9wbGF5X3N0YXJ0dXApCgogICAgc3lzLmV4aXQoYXBwLmV4ZWMoKSkKCgppZiBfX25hbWVfXyA9PSAiX19t"
    "YWluX18iOgogICAgbWFpbigpCgoKIyDilIDilIAgUEFTUyA2IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIEZ1bGwgZGVjayBhc3NlbWJsZWQuIEFsbCBwYXNzZXMgY29tcGxldGUuCiMgQ29tYmluZSBhbGwgcGFzc2VzIGludG8gbW9y"
    "Z2FubmFfZGVjay5weSBpbiBvcmRlcjoKIyAgIFBhc3MgMSDihpIgUGFzcyAyIOKGkiBQYXNzIDMg4oaSIFBhc3MgNCDihpIgUGFz"
    "cyA1IOKGkiBQYXNzIDYK"
)


def _patch_embedded_deck_implementation(source: str, log_fn=None) -> str:
    """
    Apply additive runtime patches to the embedded deck implementation text.
    This keeps deck_builder.py as the single source of truth without manually
    re-encoding the large embedded implementation blob.
    """

    def _replace_once(text: str, old: str, new: str, label: str) -> str:
        if old not in text:
            if log_fn:
                log_fn(f"[DECK][WARN] Patch target not found: {label}")
            return text
        return text.replace(old, new, 1)

    source = _replace_once(
        source,
        "import random\nimport threading\nimport urllib.request\nimport uuid\nfrom datetime import datetime, date, timedelta, timezone\n",
        "import random\nimport threading\nimport urllib.request\nimport uuid\nimport ast\nimport operator\nimport html\nfrom datetime import datetime, date, timedelta, timezone\n",
        "runtime imports for chat input helpers",
    )

    source = _replace_once(
        source,
        "    QGridLayout, QTextEdit, QLineEdit, QPushButton, QLabel, QFrame,\n",
        "    QGridLayout, QTextEdit, QPlainTextEdit, QLineEdit, QPushButton, QLabel, QFrame,\n",
        "QtWidgets import QPlainTextEdit",
    )
    source = _replace_once(
        source,
        """class EchoDeck(QMainWindow):
""",
        """class DeckChatInput(QTextEdit):
    send_requested = Signal()
    drop_warning = Signal(str)

    _SUPPORTED_TEXT_EXTS = {".txt", ".md", ".json", ".py", ".log"}
    _MAX_DROP_BYTES = 200_000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_lines = 1
        self._max_lines = 6
        self.setAcceptDrops(True)
        self.setTabChangesFocus(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._recompute_height)
        self._recompute_height()

    def set_line_limits(self, min_lines: int = 1, max_lines: int = 6) -> None:
        self._min_lines = max(1, int(min_lines))
        self._max_lines = max(self._min_lines, int(max_lines))
        self._recompute_height()

    def _line_height(self) -> int:
        return max(1, self.fontMetrics().lineSpacing())

    def _height_for_lines(self, lines: int) -> int:
        margins = int(self.contentsMargins().top() + self.contentsMargins().bottom())
        doc_margin = int(self.document().documentMargin() * 2)
        frame = int(self.frameWidth() * 2)
        return (self._line_height() * max(1, lines)) + margins + doc_margin + frame

    def _recompute_height(self) -> None:
        doc_size = self.document().documentLayout().documentSize()
        doc_h = int(math.ceil(doc_size.height()))
        min_h = self._height_for_lines(self._min_lines)
        max_h = self._height_for_lines(self._max_lines)
        target = max(min_h, min(max_h, doc_h))
        self.setMinimumHeight(min_h)
        self.setMaximumHeight(max_h)
        self.setFixedHeight(target)
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if doc_h > max_h else
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(policy)

    def keyPressEvent(self, event):
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter:
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ControlModifier:
                super().keyPressEvent(event)
                return
            if mods & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasText():
            event.acceptProposedAction()
            return
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    ext = Path(url.toLocalFile()).suffix.lower()
                    if ext in self._SUPPORTED_TEXT_EXTS:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event):
        md = event.mimeData()
        inserted_parts: list[str] = []

        if md.hasText():
            text = md.text()
            if text:
                inserted_parts.append(text)

        if md.hasUrls():
            for url in md.urls():
                if not url.isLocalFile():
                    continue
                p = Path(url.toLocalFile())
                if p.suffix.lower() not in self._SUPPORTED_TEXT_EXTS:
                    self.drop_warning.emit(f"Unsupported drop type ignored: {p.name}")
                    continue
                try:
                    if p.stat().st_size > self._MAX_DROP_BYTES:
                        kb = self._MAX_DROP_BYTES // 1024
                        self.drop_warning.emit(
                            f"Drop skipped: {p.name} exceeds {kb}KB safety limit."
                        )
                        continue
                    try:
                        blob = p.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        blob = p.read_text(encoding="latin-1", errors="replace")
                    if blob:
                        inserted_parts.append(blob)
                except Exception as ex:
                    self.drop_warning.emit(f"Could not read dropped file {p.name}: {ex}")

        if inserted_parts:
            text_to_insert = "\\n".join(x for x in inserted_parts if x)
            cursor = self.textCursor()
            cursor.insertText(text_to_insert)
            self.setTextCursor(cursor)
            event.acceptProposedAction()
            return
        event.ignore()


class DeckSlashCommandDispatcher:
    _HELP_LINES = [
        "/help",
        "/modules",
        "/module <name>",
        "/clear",
        "/newchat",
        "/history",
        "/notes",
        "/system",
        "/calc <expression>",
    ]

    def dispatch(self, deck: "EchoDeck", text: str) -> bool:
        raw = (text or "").strip()
        if not raw.startswith("/"):
            return False
        body = raw[1:].strip()
        if not body:
            deck._append_chat("SYSTEM", "Command expected after '/'. Try /help.")
            return True

        parts = body.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            deck._append_chat("SYSTEM", "Available commands: " + ", ".join(self._HELP_LINES))
            return True
        if cmd == "modules":
            deck._slash_list_modules()
            return True
        if cmd == "module":
            deck._slash_open_module(args)
            return True
        if cmd == "clear":
            deck._input_field.clear()
            return True
        if cmd == "newchat":
            deck._slash_new_chat()
            return True
        if cmd == "history":
            deck._slash_history()
            return True
        if cmd == "notes":
            deck._slash_open_notes()
            return True
        if cmd == "system":
            deck._slash_open_system()
            return True
        if cmd == "calc":
            deck._slash_calc(args)
            return True

        deck._append_chat("SYSTEM", f"Unknown command: /{cmd}. Use /help.")
        return True


class EchoDeck(QMainWindow):
""",
        "inject multiline chat input + slash command classes",
    )
    source = _replace_once(
        source,
        """        # ── Input row ──────────────────────────────────────────────────
        input_row = QHBoxLayout()
        prompt_sym = QLabel("✦")
        prompt_sym.setStyleSheet(
            f"color: {C_CRIMSON}; font-size: 16px; font-weight: bold; border: none;"
        )
        prompt_sym.setFixedWidth(20)

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText(UI_INPUT_PLACEHOLDER)
        self._input_field.returnPressed.connect(self._send_message)
        self._input_field.setEnabled(False)

        self._send_btn = QPushButton(UI_SEND_BUTTON)
        self._send_btn.setFixedWidth(110)
        self._send_btn.clicked.connect(self._send_message)
        self._send_btn.setEnabled(False)

        input_row.addWidget(prompt_sym)
        input_row.addWidget(self._input_field)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)
""",
        """        # ── Input row ──────────────────────────────────────────────────
        input_container = QVBoxLayout()
        input_container.setContentsMargins(0, 0, 0, 0)
        input_container.setSpacing(2)
        input_container.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.addStretch(1)
        self._prompt_token_label = QLabel("Prompt tokens (est): 0")
        self._prompt_token_label.setStyleSheet(
            f"color: {C_TEXT_DIM}; font-size: 10px; border: none;"
        )
        token_row.addWidget(self._prompt_token_label, 0, Qt.AlignmentFlag.AlignRight)
        input_container.addLayout(token_row)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        input_row.setAlignment(Qt.AlignmentFlag.AlignBottom)
        prompt_sym = QLabel("✦")
        prompt_sym.setStyleSheet(
            f"color: {C_CRIMSON}; font-size: 16px; font-weight: bold; border: none;"
        )
        prompt_sym.setFixedWidth(20)

        self._input_field = DeckChatInput()
        self._input_field.setPlaceholderText(UI_INPUT_PLACEHOLDER)
        self._input_field.set_line_limits(1, 6)
        self._input_field.send_requested.connect(self._send_message)
        self._input_field.textChanged.connect(self._on_prompt_text_changed)
        self._input_field.drop_warning.connect(
            lambda msg: self._append_chat("SYSTEM", msg)
        )
        self._input_field.setEnabled(False)

        self._send_btn = QPushButton(UI_SEND_BUTTON)
        self._send_btn.setFixedWidth(110)
        self._send_btn.clicked.connect(self._send_message)
        self._send_btn.setEnabled(False)

        input_row.addWidget(prompt_sym, 0, Qt.AlignmentFlag.AlignBottom)
        input_row.addWidget(self._input_field, 1)
        input_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        input_container.addLayout(input_row)
        layout.addLayout(input_container)
""",
        "multiline input row and token counter",
    )
    source = _replace_once(
        source,
        """    # ── MESSAGE HANDLING ───────────────────────────────────────────────────────
    def _send_message(self) -> None:
""",
        """    # ── MESSAGE HANDLING ───────────────────────────────────────────────────────
    def _on_prompt_text_changed(self) -> None:
        text = self._input_field.toPlainText() if self._input_field else ""
        count, exact = self._count_prompt_tokens(text)
        suffix = "exact" if exact else "est"
        if hasattr(self, "_prompt_token_label") and self._prompt_token_label is not None:
            self._prompt_token_label.setText(f"Prompt tokens ({suffix}): {count}")

    def _count_prompt_tokens(self, text: str) -> tuple[int, bool]:
        cleaned = (text or "").strip()
        if not cleaned:
            return 0, False
        tok = getattr(getattr(self, "_adaptor", None), "_tokenizer", None)
        if tok is not None and hasattr(tok, "encode"):
            try:
                return len(tok.encode(cleaned)), True
            except Exception:
                pass
        return max(1, math.ceil(len(cleaned) / 4)), False

    def _slash_list_modules(self) -> None:
        names = [str(d.get("title", "")).strip() for d in getattr(self, "_spell_tab_defs", [])]
        names = [n for n in names if n]
        if names:
            self._append_chat("SYSTEM", "Available modules: " + ", ".join(names))
        else:
            self._append_chat("SYSTEM", "No module listing is available yet.")

    def _slash_open_module(self, module_name: str) -> None:
        target = module_name.strip().lower()
        if not target:
            self._append_chat("SYSTEM", "Usage: /module <name>")
            return
        for i in range(self._spell_tabs.count()):
            title = self._spell_tabs.tabText(i).lower()
            tab_id = str(self._spell_tabs.tabBar().tabData(i) or "").lower()
            if target in title or target == tab_id:
                self._spell_tabs.setCurrentIndex(i)
                self._append_chat("SYSTEM", f"Module focused: {self._spell_tabs.tabText(i)}")
                return
        self._append_chat("SYSTEM", f"Module not found: {module_name}")

    def _slash_new_chat(self) -> None:
        try:
            self._sessions.save()
        except Exception:
            pass
        self._sessions = SessionManager()
        self._session_id = self._sessions.session_id
        self._chat_display.clear()
        self._append_chat("SYSTEM", "A new chat session begins.")
        if hasattr(self, "_journal_sidebar") and self._journal_sidebar is not None:
            self._journal_sidebar.clear_journal_indicator()

    def _slash_history(self) -> None:
        sessions = self._sessions.list_sessions()[:5]
        if not sessions:
            self._append_chat("SYSTEM", "No saved sessions found.")
            return
        lines = [f"{s.get('date','?')} — {s.get('name','(unnamed)')}" for s in sessions]
        self._append_chat("SYSTEM", "Recent sessions: " + " | ".join(lines))

    def _slash_open_notes(self) -> None:
        self._slash_open_module("lessons")

    def _slash_open_system(self) -> None:
        self._slash_open_module("instruments")

    def _safe_calc(self, expr: str) -> float:
        allowed_bin = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        allowed_unary = {
            ast.UAdd: operator.pos,
            ast.USub: operator.neg,
        }
        node = ast.parse(expr, mode="eval")

        def _eval(n):
            if isinstance(n, ast.Expression):
                return _eval(n.body)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return float(n.value)
            if isinstance(n, ast.BinOp) and type(n.op) in allowed_bin:
                return allowed_bin[type(n.op)](_eval(n.left), _eval(n.right))
            if isinstance(n, ast.UnaryOp) and type(n.op) in allowed_unary:
                return allowed_unary[type(n.op)](_eval(n.operand))
            raise ValueError("Unsupported expression")

        return _eval(node)

    def _slash_calc(self, expr: str) -> None:
        raw = expr.strip()
        if not raw:
            self._append_chat("SYSTEM", "Usage: /calc <expression>")
            return
        try:
            result = self._safe_calc(raw)
            self._append_chat("SYSTEM", f"Calc: {raw} = {result}")
        except Exception as ex:
            self._append_chat("SYSTEM", f"Calc error: {ex}")

    def _send_message(self) -> None:
""",
        "inject prompt token + slash helpers",
    )
    source = _replace_once(
        source,
        """        text = self._input_field.text().strip()
        if not text:
            return
""",
        """        raw_text = self._input_field.toPlainText()
        text = raw_text.strip()
        if not text:
            return

        if self._slash_dispatcher.dispatch(self, text):
            self._on_prompt_text_changed()
            return
""",
        "send_message multiline text + slash intercept",
    )
    source = _replace_once(
        source,
        """        self._input_field.clear()
        self._append_chat("YOU", text)
""",
        """        self._input_field.clear()
        self._on_prompt_text_changed()
        self._append_chat("YOU", text)
""",
        "send_message prompt counter refresh after clear",
    )
    source = _replace_once(
        source,
        """        self._token_count         = 0
""",
        """        self._token_count         = 0
        self._slash_dispatcher  = DeckSlashCommandDispatcher()
""",
        "echo deck init slash dispatcher",
    )
    source = _replace_once(
        source,
        """        window._input_field.setText(line)
        window._input_field.setFocus()
""",
        """        if hasattr(window._input_field, "setPlainText"):
            window._input_field.setPlainText(line)
        else:
            window._input_field.setText(line)
        window._input_field.setFocus()
        if hasattr(window, "_on_prompt_text_changed"):
            window._on_prompt_text_changed()
""",
        "send roll result to multiline prompt",
    )
    source = _replace_once(
        source,
        """                    self._input_field.setText(date_text)
                    routed_target = "input_field_set"
""",
        """                    if hasattr(self._input_field, "setPlainText"):
                        self._input_field.setPlainText(date_text)
                    else:
                        self._input_field.setText(date_text)
                    routed_target = "input_field_set"
""",
        "calendar route to multiline prompt",
    )
    source = _replace_once(
        source,
        '            return [x for x in data if isinstance(x, dict)]',
        '            return [_normalize_jsonl_record(path, x)\n'
        '                    for x in data if isinstance(x, dict)]',
        "read_jsonl array mode fallback",
    )
    source = _replace_once(
        source,
        "    # ── CHAT DISPLAY ───────────────────────────────────────────────────────────\n"
        "    def _append_chat(self, speaker: str, text: str) -> None:\n"
        "        colors = {\n"
        "            \"YOU\":     C_GOLD,\n"
        "            DECK_NAME.upper():C_GOLD,\n"
        "            \"SYSTEM\":  C_PURPLE,\n"
        "            \"ERROR\":   C_BLOOD,\n"
        "        }\n"
        "        label_colors = {\n"
        "            \"YOU\":     C_GOLD_DIM,\n"
        "            DECK_NAME.upper():C_CRIMSON,\n"
        "            \"SYSTEM\":  C_PURPLE,\n"
        "            \"ERROR\":   C_BLOOD,\n"
        "        }\n"
        "        color       = colors.get(speaker, C_GOLD)\n"
        "        label_color = label_colors.get(speaker, C_GOLD_DIM)\n"
        "        timestamp   = datetime.now().strftime(\"%H:%M:%S\")\n"
        "\n"
        "        if speaker == \"SYSTEM\":\n"
        "            self._chat_display.append(\n"
        "                f'<span style=\"color:{C_TEXT_DIM}; font-size:10px;\">'\n"
        "                f'[{timestamp}] </span>'\n"
        "                f'<span style=\"color:{label_color};\">✦ {text}</span>'\n"
        "            )\n"
        "        else:\n"
        "            self._chat_display.append(\n"
        "                f'<span style=\"color:{C_TEXT_DIM}; font-size:10px;\">'\n"
        "                f'[{timestamp}] </span>'\n"
        "                f'<span style=\"color:{label_color}; font-weight:bold;\">'\n"
        "                f'{speaker} ❧</span> '\n"
        "                f'<span style=\"color:{color};\">{text}</span>'\n"
        "            )\n"
        "\n"
        "        # Add blank line after Morganna's response (not during streaming)\n"
        "        if speaker == DECK_NAME.upper():\n"
        "            self._chat_display.append(\"\")\n"
        "\n"
        "        self._chat_display.verticalScrollBar().setValue(\n"
        "            self._chat_display.verticalScrollBar().maximum()\n"
        "        )\n",
        "    # ── CHAT DISPLAY ───────────────────────────────────────────────────────────\n"
        "    def _append_chat(self, speaker: str, text: str) -> None:\n"
        "        colors = {\n"
        "            \"YOU\":     C_GOLD,\n"
        "            DECK_NAME.upper():C_GOLD,\n"
        "            \"SYSTEM\":  C_PURPLE,\n"
        "            \"ERROR\":   C_BLOOD,\n"
        "        }\n"
        "        label_colors = {\n"
        "            \"YOU\":     C_GOLD_DIM,\n"
        "            DECK_NAME.upper():C_CRIMSON,\n"
        "            \"SYSTEM\":  C_PURPLE,\n"
        "            \"ERROR\":   C_BLOOD,\n"
        "        }\n"
        "        color       = colors.get(speaker, C_GOLD)\n"
        "        label_color = label_colors.get(speaker, C_GOLD_DIM)\n"
        "        timestamp   = datetime.now().strftime(\"%H:%M:%S\")\n"
        "        safe_text   = html.escape(text).replace(\"\\n\", \"<br>\")\n"
        "\n"
        "        if speaker == \"SYSTEM\":\n"
        "            self._chat_display.append(\n"
        "                f'<span style=\"color:{C_TEXT_DIM}; font-size:10px;\">'\n"
        "                f'[{timestamp}] </span>'\n"
        "                f'<span style=\"color:{label_color};\">✦ {safe_text}</span>'\n"
        "            )\n"
        "        else:\n"
        "            self._chat_display.append(\n"
        "                f'<span style=\"color:{C_TEXT_DIM}; font-size:10px;\">'\n"
        "                f'[{timestamp}] </span>'\n"
        "                f'<span style=\"color:{label_color}; font-weight:bold;\">'\n"
        "                f'{speaker} ❧</span> '\n"
        "                f'<span style=\"color:{color};\">{safe_text}</span>'\n"
        "            )\n"
        "\n"
        "        # Add blank line after Morganna's response (not during streaming)\n"
        "        if speaker == DECK_NAME.upper():\n"
        "            self._chat_display.append(\"\")\n"
        "\n"
        "        self._chat_display.verticalScrollBar().setValue(\n"
        "            self._chat_display.verticalScrollBar().maximum()\n"
        "        )\n",
        "chat display preserve multiline user text",
    )
    source = _replace_once(
        source,
        '                items.append(obj)',
        '                items.append(_normalize_jsonl_record(path, obj))',
        "read_jsonl line mode fallback",
    )
    source = _replace_once(
        source,
        "def write_jsonl(path: Path, records: list[dict]) -> None:\n"
        '    """Overwrite a JSONL file with a list of records."""\n'
        '    path.parent.mkdir(parents=True, exist_ok=True)\n'
        '    with path.open("w", encoding="utf-8") as f:\n'
        '        for r in records:\n'
        '            f.write(json.dumps(r, ensure_ascii=False) + "\\n")\n'
        "\n"
        "# ── KEYWORD / MEMORY HELPERS ──────────────────────────────────────────────────\n",
        "def write_jsonl(path: Path, records: list[dict]) -> None:\n"
        '    """Overwrite a JSONL file with a list of records."""\n'
        '    path.parent.mkdir(parents=True, exist_ok=True)\n'
        '    with path.open("w", encoding="utf-8") as f:\n'
        '        for r in records:\n'
        '            f.write(json.dumps(r, ensure_ascii=False) + "\\n")\n'
        "\n"
        "_ALLOWED_RUNTIME_MODES = {\"default\", \"persona\", \"rp\"}\n"
        "\n"
        "def _normalize_runtime_mode(value: object) -> str:\n"
        "    mode = str(value or \"\").strip().lower()\n"
        "    return mode if mode in _ALLOWED_RUNTIME_MODES else \"persona\"\n"
        "\n"
        "def _detect_runtime_mode(cfg: Optional[dict] = None) -> str:\n"
        "    cfg = cfg or CFG\n"
        "    candidates = [\n"
        "        cfg.get(\"mode\"),\n"
        "        cfg.get(\"runtime_mode\"),\n"
        "        cfg.get(\"chat_mode\"),\n"
        "        (cfg.get(\"settings\", {}) or {}).get(\"mode\"),\n"
        "        (cfg.get(\"settings\", {}) or {}).get(\"runtime_mode\"),\n"
        "        (cfg.get(\"settings\", {}) or {}).get(\"chat_mode\"),\n"
        "    ]\n"
        "    for candidate in candidates:\n"
        "        mode = _normalize_runtime_mode(candidate)\n"
        "        if candidate is not None and mode in _ALLOWED_RUNTIME_MODES:\n"
        "            return mode\n"
        "    return \"persona\"\n"
        "\n"
        "def _normalize_jsonl_record(path: Path, record: dict) -> dict:\n"
        "    if path.name not in (\"messages.jsonl\", \"memories.jsonl\"):\n"
        "        return record\n"
        "    normalized = dict(record)\n"
        "    normalized[\"mode\"] = _normalize_runtime_mode(\n"
        "        normalized.get(\"mode\", \"persona\")\n"
        "    )\n"
        "    return normalized\n"
        "\n"
        "_ALLOWED_THEME_MODES = {\"light\", \"auto\", \"dark\"}\n"
        "\n"
        "def _normalize_theme_mode(value: object) -> str:\n"
        "    mode = str(value or \"\").strip().lower()\n"
        "    return mode if mode in _ALLOWED_THEME_MODES else \"auto\"\n"
        "\n"
        "def _detect_theme_mode(cfg: Optional[dict] = None) -> str:\n"
        "    cfg = cfg or CFG\n"
        "    settings = (cfg.get(\"settings\", {}) or {}) if isinstance(cfg, dict) else {}\n"
        "    candidates = [\n"
        "        cfg.get(\"theme_mode\") if isinstance(cfg, dict) else None,\n"
        "        settings.get(\"theme_mode\"),\n"
        "        settings.get(\"runtime_theme_mode\"),\n"
        "    ]\n"
        "    for candidate in candidates:\n"
        "        if candidate is not None:\n"
        "            return _normalize_theme_mode(candidate)\n"
        "    return \"auto\"\n"
        "\n"
        "def _persona_preferred_theme(cfg: Optional[dict] = None) -> Optional[str]:\n"
        "    cfg = cfg or CFG\n"
        "    persona_cfg = (cfg.get(\"persona\", {}) or {}) if isinstance(cfg, dict) else {}\n"
        "    candidates = [\n"
        "        persona_cfg.get(\"preferred_theme\"),\n"
        "        persona_cfg.get(\"theme\"),\n"
        "        persona_cfg.get(\"ui_theme\"),\n"
        "    ]\n"
        "    for candidate in candidates:\n"
        "        mode = str(candidate or \"\").strip().lower()\n"
        "        if mode in {\"light\", \"dark\"}:\n"
        "            return mode\n"
        "    return None\n"
        "\n"
        "def _resolve_effective_theme(cfg: Optional[dict] = None) -> str:\n"
        "    cfg = cfg or CFG\n"
        "    mode = _detect_theme_mode(cfg)\n"
        "    if mode in {\"light\", \"dark\"}:\n"
        "        return mode\n"
        "    pref = _persona_preferred_theme(cfg)\n"
        "    return pref if pref in {\"light\", \"dark\"} else \"dark\"\n"
        "\n"
        "# ── KEYWORD / MEMORY HELPERS ──────────────────────────────────────────────────\n",
        "mode helpers",
    )
    source = _replace_once(
        source,
        '            "emotion":    emotion,\n'
        "        }",
        '            "emotion":    emotion,\n'
        '            "mode":       _detect_runtime_mode(),\n'
        "        }",
        "append_message mode field",
    )
    source = _replace_once(
        source,
        '            "confidence":       0.70 if record_type in {\n'
        '                "dream","issue","idea","preference","resolution"\n'
        '            } else 0.55,\n'
        "        }",
        '            "confidence":       0.70 if record_type in {\n'
        '                "dream","issue","idea","preference","resolution"\n'
        '            } else 0.55,\n'
        '            "mode":             _detect_runtime_mode(),\n'
        "        }",
        "append_memory mode field",
    )
    source = _replace_once(
        source,
        '            "timezone_override":         "",\n'
        '            "fullscreen_enabled":        False,\n'
        '            "borderless_enabled":        False,\n',
        '            "timezone_override":         "",\n'
        '            "runtime_persona_mode":      "persona",\n'
        '            "runtime_theme_mode":        "auto",\n'
        '            "theme_mode":                "auto",\n'
        '            "fullscreen_enabled":        False,\n'
        '            "borderless_enabled":        False,\n',
        "default config runtime mode settings",
    )
    source = _replace_once(
        source,
        "        self._first_token: bool = True   # write speaker label before first streaming token\n",
        "        self._first_token: bool = True   # write speaker label before first streaming token\n"
        "        self._runtime_persona_mode = _normalize_runtime_mode(\n"
        "            (CFG.get(\"settings\", {}) or {}).get(\"runtime_persona_mode\", _detect_runtime_mode())\n"
        "        )\n"
        "        self._runtime_theme_mode = _normalize_theme_mode(_detect_theme_mode())\n"
        "        self._pending_hidden_runtime_events: list[str] = []\n",
        "EchoDeck runtime state init",
    )
    source = _replace_once(
        source,
        "        self.setStyleSheet(STYLE)\n"
        "\n"
        "        self._build_ui()\n",
        "        self.setStyleSheet(STYLE)\n"
        "\n"
        "        self._build_ui()\n"
        "        self._apply_runtime_theme_mode(self._runtime_theme_mode, emit_event=False)\n"
        "        self._apply_runtime_persona_mode(self._runtime_persona_mode, emit_event=False)\n",
        "EchoDeck apply runtime modes after ui build",
    )
    source = _replace_once(
        source,
        "    # ── MESSAGE HANDLING ───────────────────────────────────────────────────────\n",
        "    def _runtime_event_payload(self, event_name: str, value: str, context: str = \"\") -> str:\n"
        "        payload = {\n"
        "            \"event\": event_name,\n"
        "            \"value\": value,\n"
        "            \"context\": context,\n"
        "            \"timestamp\": local_now_iso(),\n"
        "        }\n"
        "        return \"[INTERNAL_EVENT] \" + json.dumps(payload, ensure_ascii=False)\n"
        "\n"
        "    def _queue_hidden_runtime_event(self, event_name: str, value: str, context: str = \"\") -> None:\n"
        "        self._pending_hidden_runtime_events.append(\n"
        "            self._runtime_event_payload(event_name, value, context)\n"
        "        )\n"
        "\n"
        "    def _consume_hidden_runtime_events(self) -> list[str]:\n"
        "        pending = list(self._pending_hidden_runtime_events)\n"
        "        self._pending_hidden_runtime_events.clear()\n"
        "        return pending\n"
        "\n"
        "    def _apply_runtime_persona_mode(self, mode: str, emit_event: bool = True) -> None:\n"
        "        normalized = _normalize_runtime_mode(mode)\n"
        "        if normalized == self._runtime_persona_mode and emit_event:\n"
        "            return\n"
        "        self._runtime_persona_mode = normalized\n"
        "        CFG.setdefault(\"settings\", {})[\"runtime_persona_mode\"] = normalized\n"
        "        CFG[\"runtime_mode\"] = normalized\n"
        "        save_config(CFG)\n"
        "        if hasattr(self, \"_settings_tab\") and self._settings_tab:\n"
        "            self._settings_tab.sync_runtime_controls()\n"
        "        if emit_event:\n"
        "            self._diag_tab.log(f\"[MODE] Persona runtime mode -> {normalized}\", \"INFO\")\n"
        "            self._queue_hidden_runtime_event(\"runtime_persona_mode\", normalized, \"persona runtime mode changed\")\n"
        "\n"
        "    def _theme_roles(self, effective_theme: str) -> dict:\n"
        "        accent = (CFG.get(\"persona\", {}) or {}).get(\"color_primary\") or \"#5b8cff\"\n"
        "        if effective_theme == \"light\":\n"
        "            return {\n"
        "                \"window_bg\":   \"#eef2f8\",\n"
        "                \"sidebar_bg\":  \"#e6ebf3\",\n"
        "                \"panel_bg\":    \"#ffffff\",\n"
        "                \"panel_alt_bg\":\"#f5f8ff\",\n"
        "                \"input_bg\":    \"#ffffff\",\n"
        "                \"border\":      \"#b8c4db\",\n"
        "                \"text\":        \"#171c28\",\n"
        "                \"text_dim\":    \"#5b667d\",\n"
        "                \"button_bg\":   \"#dbe5f7\",\n"
        "                \"button_hover\": \"#ccd9f0\",\n"
        "                \"accent\":      accent,\n"
        "            }\n"
        "        return {\n"
        "            \"window_bg\":   \"#0b0f1a\",\n"
        "            \"sidebar_bg\":  \"#10182a\",\n"
        "            \"panel_bg\":    \"#151f35\",\n"
        "            \"panel_alt_bg\":\"#1a2640\",\n"
        "            \"input_bg\":    \"#111b2f\",\n"
        "            \"border\":      \"#304465\",\n"
        "            \"text\":        \"#dfe6f8\",\n"
        "            \"text_dim\":    \"#9eacca\",\n"
        "            \"button_bg\":   \"#1f2c49\",\n"
        "            \"button_hover\": \"#2a3a5e\",\n"
        "            \"accent\":      accent,\n"
        "        }\n"
        "\n"
        "    def _apply_shell_region_theme(self, roles: dict) -> None:\n"
        "        role_keywords = {\n"
        "            \"sidebar\": {\"left\", \"sidebar\", \"journal\"},\n"
        "            \"workspace\": {\"chat\", \"workspace\", \"center\", \"mainpanel\"},\n"
        "            \"systems\": {\"right\", \"system\", \"module\"},\n"
        "            \"hud\": {\"hud\", \"lower\", \"status\"},\n"
        "            \"calendar\": {\"calendar\"},\n"
        "            \"input\": {\"input\", \"prompt\", \"composer\"},\n"
        "        }\n"
        "        widgets = [self]\n"
        "        widgets.extend(self.findChildren(QWidget))\n"
        "        for w in widgets:\n"
        "            role = \"card\"\n"
        "            name = (w.objectName() or \"\").strip().lower()\n"
        "            if w is self:\n"
        "                role = \"shell_bg\"\n"
        "            elif isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox)):\n"
        "                role = \"input\"\n"
        "            elif isinstance(w, (QPushButton, QToolButton)):\n"
        "                role = \"button\"\n"
        "            elif name:\n"
        "                for candidate, keys in role_keywords.items():\n"
        "                    if any(k in name for k in keys):\n"
        "                        role = candidate\n"
        "                        break\n"
        "            w.setProperty(\"runtime_theme_role\", role)\n"
        "            w.style().unpolish(w)\n"
        "            w.style().polish(w)\n"
        "            w.update()\n"
        "\n"
        "    def _apply_theme_stylesheet(self, effective_theme: str) -> None:\n"
        "        roles = self._theme_roles(effective_theme)\n"
        "        self._apply_shell_region_theme(roles)\n"
        "        base = STYLE\n"
        "        override = (\n"
        "            \"\\nQMainWindow, QWidget#deck_root, QWidget[runtime_theme_role=\\\"shell_bg\\\"] {\"\n"
        "            f\" background-color: {roles['window_bg']}; color: {roles['text']}; }}\"\n"
        "            \"\\nQWidget[runtime_theme_role=\\\"sidebar\\\"] {\"\n"
        "            f\" background-color: {roles['sidebar_bg']}; color: {roles['text']};\"\n"
        "            f\" border-color: {roles['border']}; }}\"\n"
        "            \"\\nQWidget[runtime_theme_role=\\\"workspace\\\"], QWidget[runtime_theme_role=\\\"systems\\\"],\"\n"
        "            \" QWidget[runtime_theme_role=\\\"hud\\\"], QWidget[runtime_theme_role=\\\"calendar\\\"] {\"\n"
        "            f\" background-color: {roles['panel_bg']}; color: {roles['text']};\"\n"
        "            f\" border-color: {roles['border']}; }}\"\n"
        "            \"\\nQWidget[runtime_theme_role=\\\"card\\\"], QFrame, QGroupBox, QTabWidget::pane {\"\n"
        "            f\" background-color: {roles['panel_alt_bg']}; color: {roles['text']};\"\n"
        "            f\" border: 1px solid {roles['border']}; }}\"\n"
        "            \"\\nQWidget[runtime_theme_role=\\\"input\\\"], QLineEdit, QTextEdit, QPlainTextEdit,\"\n"
        "            \" QComboBox, QListWidget, QTableWidget, QTreeWidget, QCalendarWidget {\"\n"
        "            f\" background-color: {roles['input_bg']}; color: {roles['text']};\"\n"
        "            f\" border: 1px solid {roles['border']}; selection-background-color: {roles['accent']}; }}\"\n"
        "            \"\\nQPushButton, QToolButton, QWidget[runtime_theme_role=\\\"button\\\"] {\"\n"
        "            f\" background-color: {roles['button_bg']}; color: {roles['text']};\"\n"
        "            f\" border: 1px solid {roles['border']}; }}\"\n"
        "            \"\\nQPushButton:hover, QToolButton:hover, QWidget[runtime_theme_role=\\\"button\\\"]:hover {\"\n"
        "            f\" background-color: {roles['button_hover']}; border-color: {roles['accent']}; }}\"\n"
        "            \"\\nQPushButton:checked, QToolButton:checked {\"\n"
        "            f\" border: 1px solid {roles['accent']}; }}\"\n"
        "            \"\\nQLabel {\"\n"
        "            f\" color: {roles['text']}; }}\"\n"
        "            \"\\nQLabel[dim=\\\"true\\\"] {\"\n"
        "            f\" color: {roles['text_dim']}; }}\"\n"
        "            \"\\nQTabBar::tab:selected, QHeaderView::section:selected {\"\n"
        "            f\" border-color: {roles['accent']}; color: {roles['text']}; }}\"\n"
        "            \"\\nQSplitter::handle {\"\n"
        "            f\" background-color: {roles['border']}; }}\"\n"
        "        )\n"
        "        self.setStyleSheet(base + override)\n"
        "\n"
        "    def _apply_runtime_theme_mode(self, mode: str, emit_event: bool = True) -> None:\n"
        "        normalized = _normalize_theme_mode(mode)\n"
        "        if normalized == self._runtime_theme_mode and emit_event:\n"
        "            return\n"
        "        self._runtime_theme_mode = normalized\n"
        "        CFG.setdefault(\"settings\", {})[\"runtime_theme_mode\"] = normalized\n"
        "        CFG.setdefault(\"settings\", {})[\"theme_mode\"] = normalized\n"
        "        CFG[\"theme_mode\"] = normalized\n"
        "        save_config(CFG)\n"
        "        effective = _resolve_effective_theme(CFG)\n"
        "        self._apply_theme_stylesheet(effective)\n"
        "        if hasattr(self, \"_settings_tab\") and self._settings_tab:\n"
        "            self._settings_tab.sync_runtime_controls()\n"
        "        if emit_event:\n"
        "            context = (\n"
        "                \"environment is brightly lit\" if effective == \"light\" else\n"
        "                \"environment is dim\" if effective == \"dark\" else\n"
        "                \"persona-preferred theme restored\"\n"
        "            )\n"
        "            self._diag_tab.log(\n"
        "                f\"[THEME] mode={normalized} effective={effective}\", \"INFO\"\n"
        "            )\n"
        "            self._queue_hidden_runtime_event(\"runtime_theme_mode\", normalized, context)\n"
        "\n"
        "    def _handle_theme_command(self, text: str) -> bool:\n"
        "        if text == \"Theme Light\":\n"
        "            self._apply_runtime_theme_mode(\"light\")\n"
        "            return True\n"
        "        if text == \"Theme Auto\":\n"
        "            self._apply_runtime_theme_mode(\"auto\")\n"
        "            return True\n"
        "        if text == \"Theme Dark\":\n"
        "            self._apply_runtime_theme_mode(\"dark\")\n"
        "            return True\n"
        "        return False\n"
        "\n"
        "    # ── MESSAGE HANDLING ───────────────────────────────────────────────────────\n",
        "runtime mode/theme methods",
    )
    source = _replace_once(
        source,
        "        if not text:\n"
        "            return\n"
        "\n"
        "        # Flip back to persona chat tab from Self tab if needed\n",
        "        if not text:\n"
        "            return\n"
        "        if self._handle_theme_command(text):\n"
        "            self._input_field.clear()\n"
        "            return\n"
        "\n"
        "        # Flip back to persona chat tab from Self tab if needed\n",
        "send message intercept theme command",
    )
    source = _replace_once(
        source,
        "        # Build system prompt\n"
        "        system = SYSTEM_PROMPT_BASE\n"
        "        if memory_ctx:\n"
        "            system += f\"\\n\\n{memory_ctx}\"\n"
        "        if journal_ctx:\n"
        "            system += f\"\\n\\n{journal_ctx}\"\n"
        "        system += vampire_ctx\n",
        "        # Build system prompt\n"
        "        runtime_mode = _normalize_runtime_mode(self._runtime_persona_mode)\n"
        "        if runtime_mode == \"default\":\n"
        "            system = \"\"\n"
        "        else:\n"
        "            system = SYSTEM_PROMPT_BASE\n"
        "            if runtime_mode == \"rp\":\n"
        "                system += (\n"
        "                    \"\\n\\n[RUNTIME PERSONA MODE]\\n\"\n"
        "                    \"Mode: rp\\n\"\n"
        "                    \"Speak as the selected persona as a fully in-world character. \"\n"
        "                    \"Do not frame yourself as an AI assistant.\"\n"
        "                )\n"
        "            else:\n"
        "                system += \"\\n\\n[RUNTIME PERSONA MODE]\\nMode: persona\"\n"
        "        if memory_ctx:\n"
        "            system += f\"\\n\\n{memory_ctx}\"\n"
        "        if journal_ctx:\n"
        "            system += f\"\\n\\n{journal_ctx}\"\n"
        "        system += vampire_ctx\n",
        "send message runtime persona system prompt",
    )
    source = _replace_once(
        source,
        "            self._pending_transmissions = 0\n"
        "            self._suspended_duration    = \"\"\n"
        "\n"
        "        history = self._sessions.get_history()\n",
        "            self._pending_transmissions = 0\n"
        "            self._suspended_duration    = \"\"\n"
        "\n"
        "        history = self._sessions.get_history()\n"
        "        for evt in self._consume_hidden_runtime_events():\n"
        "            history.append({\"role\": \"user\", \"content\": evt})\n",
        "inject hidden runtime events into history",
    )
    source = _replace_once(
        source,
        "    def _build_system_section(self, layout: QVBoxLayout) -> None:\n"
        "        if self._deck._torpor_panel is not None:\n"
        "            layout.addWidget(QLabel(\"Operational Mode\"))\n"
        "            layout.addWidget(self._deck._torpor_panel)\n"
        "\n"
        "        layout.addWidget(QLabel(\"Idle\"))\n"
        "        layout.addWidget(self._deck._idle_btn)\n"
        "\n"
        "        settings = CFG.get(\"settings\", {})\n"
        "        tz_auto = bool(settings.get(\"timezone_auto_detect\", True))\n"
        "        tz_override = str(settings.get(\"timezone_override\", \"\") or \"\").strip()\n"
        "\n"
        "        tz_auto_chk = QCheckBox(\"Auto-detect local/system time zone\")\n"
        "        tz_auto_chk.setChecked(tz_auto)\n"
        "        tz_auto_chk.toggled.connect(self._deck._set_timezone_auto_detect)\n"
        "        layout.addWidget(tz_auto_chk)\n"
        "\n"
        "        tz_row = QHBoxLayout()\n"
        "        tz_row.addWidget(QLabel(\"Manual Time Zone Override:\"))\n"
        "        tz_combo = QComboBox()\n"
        "        tz_combo.setEditable(True)\n"
        "        tz_options = [\n"
        "            \"America/Chicago\", \"America/New_York\", \"America/Los_Angeles\",\n"
        "            \"America/Denver\", \"UTC\"\n"
        "        ]\n"
        "        tz_combo.addItems(tz_options)\n"
        "        if tz_override:\n"
        "            if tz_combo.findText(tz_override) < 0:\n"
        "                tz_combo.addItem(tz_override)\n"
        "            tz_combo.setCurrentText(tz_override)\n"
        "        else:\n"
        "            tz_combo.setCurrentText(\"America/Chicago\")\n"
        "        tz_combo.setEnabled(not tz_auto)\n"
        "        tz_combo.currentTextChanged.connect(self._deck._set_timezone_override)\n"
        "        tz_auto_chk.toggled.connect(lambda enabled: tz_combo.setEnabled(not enabled))\n"
        "        tz_row.addWidget(tz_combo, 1)\n"
        "        tz_host = QWidget()\n"
        "        tz_host.setLayout(tz_row)\n"
        "        layout.addWidget(tz_host)\n",
        "    def _build_system_section(self, layout: QVBoxLayout) -> None:\n"
        "        if self._deck._torpor_panel is not None:\n"
        "            layout.addWidget(QLabel(\"Operational Mode\"))\n"
        "            layout.addWidget(self._deck._torpor_panel)\n"
        "\n"
        "        layout.addWidget(QLabel(\"Idle\"))\n"
        "        layout.addWidget(self._deck._idle_btn)\n"
        "\n"
        "        layout.addWidget(QLabel(\"Persona Runtime Mode\"))\n"
        "        self._persona_mode_buttons = {}\n"
        "        persona_modes = [\n"
        "            (\"default\", \"Default\"),\n"
        "            (\"persona\", \"Persona\"),\n"
        "            (\"rp\", \"RP\"),\n"
        "        ]\n"
        "        persona_row = QHBoxLayout()\n"
        "        for mode_key, label in persona_modes:\n"
        "            btn = QPushButton(label)\n"
        "            btn.setCheckable(True)\n"
        "            btn.clicked.connect(lambda _checked=False, m=mode_key: self._deck._apply_runtime_persona_mode(m))\n"
        "            persona_row.addWidget(btn)\n"
        "            self._persona_mode_buttons[mode_key] = btn\n"
        "        persona_host = QWidget()\n"
        "        persona_host.setLayout(persona_row)\n"
        "        layout.addWidget(persona_host)\n"
        "\n"
        "        settings = CFG.get(\"settings\", {})\n"
        "        tz_auto = bool(settings.get(\"timezone_auto_detect\", True))\n"
        "        tz_override = str(settings.get(\"timezone_override\", \"\") or \"\").strip()\n"
        "\n"
        "        tz_auto_chk = QCheckBox(\"Auto-detect local/system time zone\")\n"
        "        tz_auto_chk.setChecked(tz_auto)\n"
        "        tz_auto_chk.toggled.connect(self._deck._set_timezone_auto_detect)\n"
        "        layout.addWidget(tz_auto_chk)\n"
        "\n"
        "        tz_row = QHBoxLayout()\n"
        "        tz_row.addWidget(QLabel(\"Manual Time Zone Override:\"))\n"
        "        tz_combo = QComboBox()\n"
        "        tz_combo.setEditable(True)\n"
        "        tz_options = [\n"
        "            \"America/Chicago\", \"America/New_York\", \"America/Los_Angeles\",\n"
        "            \"America/Denver\", \"UTC\"\n"
        "        ]\n"
        "        tz_combo.addItems(tz_options)\n"
        "        if tz_override:\n"
        "            if tz_combo.findText(tz_override) < 0:\n"
        "                tz_combo.addItem(tz_override)\n"
        "            tz_combo.setCurrentText(tz_override)\n"
        "        else:\n"
        "            tz_combo.setCurrentText(\"America/Chicago\")\n"
        "        tz_combo.setEnabled(not tz_auto)\n"
        "        tz_combo.currentTextChanged.connect(self._deck._set_timezone_override)\n"
        "        tz_auto_chk.toggled.connect(lambda enabled: tz_combo.setEnabled(not enabled))\n"
        "        tz_row.addWidget(tz_combo, 1)\n"
        "        tz_host = QWidget()\n"
        "        tz_host.setLayout(tz_row)\n"
        "        layout.addWidget(tz_host)\n",
        "settings system section persona runtime controls",
    )
    source = _replace_once(
        source,
        "    def _build_ui_section(self, layout: QVBoxLayout) -> None:\n"
        "        layout.addWidget(QLabel(\"Window Shell\"))\n"
        "        layout.addWidget(self._deck._fs_btn)\n"
        "        layout.addWidget(self._deck._bl_btn)\n",
        "    def _build_ui_section(self, layout: QVBoxLayout) -> None:\n"
        "        layout.addWidget(QLabel(\"Theme Mode\"))\n"
        "        self._theme_mode_buttons = {}\n"
        "        theme_modes = [\n"
        "            (\"light\", \"Light\"),\n"
        "            (\"auto\", \"Auto\"),\n"
        "            (\"dark\", \"Dark\"),\n"
        "        ]\n"
        "        theme_row = QHBoxLayout()\n"
        "        for mode_key, label in theme_modes:\n"
        "            btn = QPushButton(label)\n"
        "            btn.setCheckable(True)\n"
        "            btn.clicked.connect(lambda _checked=False, m=mode_key: self._deck._apply_runtime_theme_mode(m))\n"
        "            theme_row.addWidget(btn)\n"
        "            self._theme_mode_buttons[mode_key] = btn\n"
        "        theme_host = QWidget()\n"
        "        theme_host.setLayout(theme_row)\n"
        "        layout.addWidget(theme_host)\n"
        "\n"
        "        layout.addWidget(QLabel(\"Window Shell\"))\n"
        "        layout.addWidget(self._deck._fs_btn)\n"
        "        layout.addWidget(self._deck._bl_btn)\n"
        "        self.sync_runtime_controls()\n"
        "\n"
        "    def sync_runtime_controls(self) -> None:\n"
        "        persona_mode = _normalize_runtime_mode(getattr(self._deck, \"_runtime_persona_mode\", \"persona\"))\n"
        "        theme_mode = _normalize_theme_mode(getattr(self._deck, \"_runtime_theme_mode\", \"auto\"))\n"
        "        for mode_key, btn in getattr(self, \"_persona_mode_buttons\", {}).items():\n"
        "            btn.setChecked(mode_key == persona_mode)\n"
        "        for mode_key, btn in getattr(self, \"_theme_mode_buttons\", {}).items():\n"
        "            btn.setChecked(mode_key == theme_mode)\n",
        "settings ui section theme controls + sync",
    )
    source = _replace_once(
        source,
        """        # ── GPU master bar (full width) ───────────────────────────────
        layout.addWidget(section_label("❧ INFERNAL ENGINE"))
        self.gauge_gpu_master = GaugeWidget("RTX", "%", 100.0, C_CRIMSON)
        self.gauge_gpu_master.setMaximumHeight(55)
        layout.addWidget(self.gauge_gpu_master)

        layout.addStretch()
""",
        """        # ── GPU master bar (full width) ───────────────────────────────
        layout.addWidget(section_label("❧ INFERNAL ENGINE"))
        self.gauge_gpu_master = GaugeWidget("RTX", "%", 100.0, C_CRIMSON)
        self.gauge_gpu_master.setMaximumHeight(55)
        layout.addWidget(self.gauge_gpu_master)

        # ── Power telemetry ────────────────────────────────────────────
        layout.addWidget(section_label("❧ POWER"))
        power_frame = QFrame()
        power_frame.setStyleSheet(
            f"background: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 2px;"
        )
        pf = QVBoxLayout(power_frame)
        pf.setContentsMargins(8, 4, 8, 4)
        pf.setSpacing(2)
        self.lbl_power_has_battery = QLabel("✦ HAS BATTERY: N/A")
        self.lbl_power_percent = QLabel("✦ BATTERY: N/A")
        self.lbl_power_state = QLabel("✦ POWER STATE: N/A")
        self.lbl_power_time = QLabel("✦ REMAINING: N/A")
        self.lbl_power_direction = QLabel("✦ DIRECTION: N/A")
        for lbl in (self.lbl_power_has_battery, self.lbl_power_percent, self.lbl_power_state, self.lbl_power_time, self.lbl_power_direction):
            lbl.setStyleSheet(
                f"color: {C_TEXT_DIM}; font-size: 10px; "
                f"font-family: {DECK_FONT}, serif; border: none;"
            )
            pf.addWidget(lbl)
        layout.addWidget(power_frame)

        # ── Network telemetry ──────────────────────────────────────────
        layout.addWidget(section_label("❧ NETWORK"))
        network_frame = QFrame()
        network_frame.setStyleSheet(
            f"background: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 2px;"
        )
        nf = QVBoxLayout(network_frame)
        nf.setContentsMargins(8, 4, 8, 4)
        nf.setSpacing(2)
        self.lbl_net_connected = QLabel("✦ CONNECTED: N/A")
        self.lbl_net_wifi = QLabel("✦ WI-FI: N/A")
        self.lbl_net_iface = QLabel("✦ ADAPTER: N/A")
        self.lbl_net_ssid = QLabel("✦ SSID: N/A")
        self.lbl_net_throughput = QLabel("✦ THROUGHPUT: N/A")
        for lbl in (self.lbl_net_connected, self.lbl_net_wifi, self.lbl_net_iface, self.lbl_net_ssid, self.lbl_net_throughput):
            lbl.setStyleSheet(
                f"color: {C_TEXT_DIM}; font-size: 10px; "
                f"font-family: {DECK_FONT}, serif; border: none;"
            )
            nf.addWidget(lbl)
        layout.addWidget(network_frame)

        layout.addStretch()
""",
        "instruments panel power+network sections",
    )
    source = _replace_once(
        source,
        "    def update_stats(self) -> None:\n",
        "    def _fmt_secs(self, secs: int) -> str:\n"
        "        if secs is None or secs < 0:\n"
        "            return \"Unknown\"\n"
        "        h = secs // 3600\n"
        "        m = (secs % 3600) // 60\n"
        "        return f\"{h}h {m}m\"\n"
        "\n"
        "    def _update_power_stats(self) -> None:\n"
        "        if not PSUTIL_OK or not hasattr(psutil, \"sensors_battery\"):\n"
        "            self.lbl_power_has_battery.setText(\"✦ HAS BATTERY: Unavailable\")\n"
        "            self.lbl_power_percent.setText(\"✦ BATTERY: N/A\")\n"
        "            self.lbl_power_state.setText(\"✦ POWER STATE: Unavailable\")\n"
        "            self.lbl_power_time.setText(\"✦ REMAINING: Unavailable\")\n"
        "            self.lbl_power_direction.setText(\"✦ DIRECTION: Unavailable\")\n"
        "            return\n"
        "        try:\n"
        "            batt = psutil.sensors_battery()\n"
        "        except Exception:\n"
        "            batt = None\n"
        "        if batt is None:\n"
        "            self.lbl_power_has_battery.setText(\"✦ HAS BATTERY: No\")\n"
        "            self.lbl_power_percent.setText(\"✦ BATTERY: No battery detected\")\n"
        "            self.lbl_power_state.setText(\"✦ POWER STATE: No battery detected\")\n"
        "            self.lbl_power_time.setText(\"✦ REMAINING: No battery detected\")\n"
        "            self.lbl_power_direction.setText(\"✦ DIRECTION: No battery detected\")\n"
        "            return\n"
        "        pct = float(getattr(batt, \"percent\", 0.0) or 0.0)\n"
        "        plugged = bool(getattr(batt, \"power_plugged\", False))\n"
        "        left = int(getattr(batt, \"secsleft\", -1) or -1)\n"
        "        rem = self._fmt_secs(left) if left >= 0 else \"Unknown\"\n"
        "        state = \"Plugged in / charging\" if plugged else \"On battery\"\n"
        "        direction = \"Charging\" if plugged else \"Discharging\"\n"
        "        self.lbl_power_has_battery.setText(\"✦ HAS BATTERY: Yes\")\n"
        "        self.lbl_power_percent.setText(f\"✦ BATTERY: {pct:.0f}%\")\n"
        "        self.lbl_power_state.setText(f\"✦ POWER STATE: {state}\")\n"
        "        self.lbl_power_time.setText(f\"✦ REMAINING: {rem}\")\n"
        "        self.lbl_power_direction.setText(f\"✦ DIRECTION: {direction}\")\n"
        "\n"
        "    def _detect_wifi_ssid(self) -> str:\n"
        "        for cmd in ([\"netsh\", \"wlan\", \"show\", \"interfaces\"], [\"nmcli\", \"-t\", \"-f\", \"active,ssid\", \"dev\", \"wifi\"], [\"iwgetid\", \"-r\"]):\n"
        "            try:\n"
        "                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=1.5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        "            except Exception:\n"
        "                continue\n"
        "            txt = (out or \"\").strip()\n"
        "            if not txt:\n"
        "                continue\n"
        "            if cmd[0] == \"netsh\":\n"
        "                for line in txt.splitlines():\n"
        "                    low = line.lower().strip()\n"
        "                    if low.startswith(\"ssid\") and \"bssid\" not in low and \":\" in line:\n"
        "                        return line.split(\":\", 1)[1].strip() or \"Unknown\"\n"
        "            elif cmd[0] == \"nmcli\":\n"
        "                for line in txt.splitlines():\n"
        "                    if line.startswith(\"yes:\"):\n"
        "                        return line.split(\":\", 1)[1].strip() or \"Unknown\"\n"
        "            else:\n"
        "                return txt.splitlines()[0].strip() or \"Unknown\"\n"
        "        return \"No Wi-Fi\"\n"
        "\n"
        "    def _update_network_stats(self) -> None:\n"
        "        if not PSUTIL_OK:\n"
        "            self.lbl_net_connected.setText(\"✦ CONNECTED: Unavailable\")\n"
        "            self.lbl_net_wifi.setText(\"✦ WI-FI: Unavailable\")\n"
        "            self.lbl_net_iface.setText(\"✦ ADAPTER: Unavailable\")\n"
        "            self.lbl_net_ssid.setText(\"✦ SSID: Unavailable\")\n"
        "            self.lbl_net_throughput.setText(\"✦ THROUGHPUT: Unavailable\")\n"
        "            return\n"
        "        try:\n"
        "            stats = psutil.net_if_stats(); addrs = psutil.net_if_addrs(); io_now = psutil.net_io_counters()\n"
        "        except Exception:\n"
        "            self.lbl_net_connected.setText(\"✦ CONNECTED: Unavailable\")\n"
        "            self.lbl_net_wifi.setText(\"✦ WI-FI: Unavailable\")\n"
        "            self.lbl_net_iface.setText(\"✦ ADAPTER: Unavailable\")\n"
        "            self.lbl_net_ssid.setText(\"✦ SSID: Unavailable\")\n"
        "            self.lbl_net_throughput.setText(\"✦ THROUGHPUT: Unavailable\")\n"
        "            return\n"
        "        active = []\n"
        "        for name, st in stats.items():\n"
        "            if not getattr(st, \"isup\", False):\n"
        "                continue\n"
        "            if name.lower().startswith(\"loopback\") or name.lower().startswith(\"lo\"):\n"
        "                continue\n"
        "            if addrs.get(name, []):\n"
        "                active.append(name)\n"
        "        connected = bool(active)\n"
        "        wifi_iface = next((n for n in active if any(k in n.lower() for k in (\"wi-fi\", \"wifi\", \"wlan\", \"wireless\"))), \"\")\n"
        "        is_wifi = bool(wifi_iface)\n"
        "        iface_label = wifi_iface or (active[0] if active else \"None\")\n"
        "        throughput = \"N/A\"\n"
        "        if io_now is not None:\n"
        "            now = time.time()\n"
        "            last_ts = getattr(self, \"_net_prev_ts\", None)\n"
        "            if last_ts and now > last_ts:\n"
        "                up = max(0.0, (io_now.bytes_sent - getattr(self, \"_net_prev_sent\", io_now.bytes_sent)) / 1024.0 / (now - last_ts))\n"
        "                down = max(0.0, (io_now.bytes_recv - getattr(self, \"_net_prev_recv\", io_now.bytes_recv)) / 1024.0 / (now - last_ts))\n"
        "                throughput = f\"↓ {down:.1f} KB/s ↑ {up:.1f} KB/s\"\n"
        "            self._net_prev_ts = now\n"
        "            self._net_prev_sent = io_now.bytes_sent\n"
        "            self._net_prev_recv = io_now.bytes_recv\n"
        "        ssid = self._detect_wifi_ssid() if is_wifi else \"No Wi-Fi\"\n"
        "        self.lbl_net_connected.setText(f\"✦ CONNECTED: {'Yes' if connected else 'No'}\")\n"
        "        self.lbl_net_wifi.setText(f\"✦ WI-FI: {'Yes' if is_wifi else 'No'}\")\n"
        "        self.lbl_net_iface.setText(f\"✦ ADAPTER: {iface_label}\")\n"
        "        self.lbl_net_ssid.setText(f\"✦ SSID: {ssid}\")\n"
        "        self.lbl_net_throughput.setText(f\"✦ THROUGHPUT: {throughput}\")\n"
        "\n"
        "    def update_stats(self) -> None:\n",
        "instruments helper methods for power+network",
    )
    source = _replace_once(
        source,
        "        # Update drive bars every 30 seconds (not every tick)\n",
        "        self._update_power_stats()\n"
        "        self._update_network_stats()\n"
        "\n"
        "        # Update drive bars every 30 seconds (not every tick)\n",
        "instruments update cycle power+network",
    )
    source = _replace_once(
        source,
        "class DiceTrayDie(QFrame):\n",
        """class FinancialPlannerTab(QWidget):
    \"\"\"Manual-entry Financial Planner module with Dashboard + Planner internal tabs.\"\"\"

    DEFAULT_CATEGORY_BUCKETS = {
        "Housing": "needs", "Utilities": "needs", "Insurance": "needs", "Groceries": "needs",
        "Transportation": "needs", "Medical": "needs",
        "Dining Out": "wants", "Entertainment": "wants", "Subscriptions": "wants",
        "Shopping": "wants", "Hobbies": "wants",
        "Emergency Fund": "savings_debt", "Retirement": "savings_debt",
        "Investments": "savings_debt", "Debt Payment": "savings_debt", "Sinking Fund": "savings_debt",
    }

    def __init__(self, diagnostics_logger=None):
        super().__init__()
        self._log = diagnostics_logger or (lambda *_args, **_kwargs: None)
        self._path = cfg_path("memories") / "financial_planner.json"
        self.data = self._load_data()
        self._bill_last_reminder: dict[str, datetime] = {}
        self._build_ui()
        self._refresh_all()
        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._check_bill_reminders)
        self._reminder_timer.start(60000)

    def _default_data(self) -> dict:
        return {
            "transactions": [],
            "recurring_bills": [],
            "budget_targets": [],
            "goals": [],
            "planner_settings": {
                "currency": "USD",
                "guidance_model": "50/30/20",
                "reminder_repeat_interval": 3600,
                "google_sync_enabled": True,
                "view_month": date.today().strftime("%Y-%m"),
            },
            "category_buckets": dict(self.DEFAULT_CATEGORY_BUCKETS),
            "bill_activity": [],
        }

    def _load_data(self) -> dict:
        data = self._default_data()
        try:
            if self._path.exists():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in ("transactions", "recurring_bills", "budget_targets", "goals", "bill_activity"):
                        if isinstance(loaded.get(key), list):
                            data[key] = loaded[key]
                    if isinstance(loaded.get("planner_settings"), dict):
                        data["planner_settings"].update(loaded["planner_settings"])
                    if isinstance(loaded.get("category_buckets"), dict):
                        data["category_buckets"].update(loaded["category_buckets"])
        except Exception as e:
            self._log(f"[FINANCIAL] load failed: {e}", "WARN")
        return data

    def _save_data(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self._log(f"[FINANCIAL] save failed: {e}", "WARN")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        top_row = QHBoxLayout()
        self._btn_export = QPushButton("Export")
        self._btn_export.clicked.connect(self._export_data)
        self._btn_import = QPushButton("Import")
        self._btn_import.clicked.connect(self._import_data)
        self._btn_review = QPushButton("Generate Monthly AI Review")
        self._btn_review.clicked.connect(self._generate_monthly_review)
        top_row.addWidget(self._btn_export)
        top_row.addWidget(self._btn_import)
        top_row.addWidget(self._btn_review)
        top_row.addStretch(1)
        root.addLayout(top_row)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)
        self._dashboard_tab = QWidget()
        self._planner_tab = QWidget()
        self._tabs.addTab(self._dashboard_tab, "Dashboard")
        self._tabs.addTab(self._planner_tab, "Planner")

        self._build_dashboard_tab()
        self._build_planner_tab()

    def _all_categories(self) -> list[str]:
        return sorted(self.data.get("category_buckets", {}).keys())

    def _build_dashboard_tab(self) -> None:
        lay = QVBoxLayout(self._dashboard_tab)
        self._monthly_snapshot = QLabel("")
        self._guidance_snapshot = QLabel("")
        self._goals_snapshot = QTableWidget(0, 5)
        self._goals_snapshot.setHorizontalHeaderLabels(["Goal", "Current", "Target", "Progress %", "Projected"])
        self._recent_snapshot = QTableWidget(0, 5)
        self._recent_snapshot.setHorizontalHeaderLabels(["Date", "Type", "Category", "Amount", "Note/Payee"])
        for tbl in (self._goals_snapshot, self._recent_snapshot):
            tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(QLabel("Monthly Snapshot"))
        lay.addWidget(self._monthly_snapshot)
        lay.addWidget(QLabel("50 / 30 / 20 Guidance Monitor"))
        lay.addWidget(self._guidance_snapshot)
        lay.addWidget(QLabel("Savings / Debt / Goal Progress"))
        lay.addWidget(self._goals_snapshot, 1)
        lay.addWidget(QLabel("Recent Activity Feed"))
        lay.addWidget(self._recent_snapshot, 1)

    def _build_planner_tab(self) -> None:
        lay = QVBoxLayout(self._planner_tab)
        self._planner_sections = QTabWidget()
        lay.addWidget(self._planner_sections, 1)
        self._tx_tab = QWidget()
        self._bill_tab = QWidget()
        self._budget_tab = QWidget()
        self._goals_tab = QWidget()
        self._planner_sections.addTab(self._tx_tab, "Transactions Ledger")
        self._planner_sections.addTab(self._bill_tab, "Recurring Bills Manager")
        self._planner_sections.addTab(self._budget_tab, "Budget Targets")
        self._planner_sections.addTab(self._goals_tab, "Goals")
        self._build_transactions_section()
        self._build_bills_section()
        self._build_budget_section()
        self._build_goals_section()

    def _build_transactions_section(self) -> None:
        lay = QVBoxLayout(self._tx_tab)
        form = QGridLayout()
        self.tx_date = QDateEdit(QDate.currentDate()); self.tx_date.setCalendarPopup(True)
        self.tx_type = QComboBox(); self.tx_type.addItems(["income", "expense", "transfer", "refund"])
        self.tx_category = QComboBox(); self.tx_category.addItems(self._all_categories())
        self.tx_amount = QLineEdit(); self.tx_payee = QLineEdit(); self.tx_notes = QLineEdit(); self.tx_tags = QLineEdit()
        labels = ["Date", "Type", "Category", "Amount", "Payee/Source", "Notes", "Tags"]
        widgets = [self.tx_date, self.tx_type, self.tx_category, self.tx_amount, self.tx_payee, self.tx_notes, self.tx_tags]
        for i, (lbl, w) in enumerate(zip(labels, widgets)):
            form.addWidget(QLabel(lbl), i, 0); form.addWidget(w, i, 1)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.tx_add = QPushButton("Add"); self.tx_add.clicked.connect(self._add_transaction)
        self.tx_edit = QPushButton("Edit Selected"); self.tx_edit.clicked.connect(self._edit_transaction)
        self.tx_del = QPushButton("Delete Selected"); self.tx_del.clicked.connect(self._delete_transaction)
        row.addWidget(self.tx_add); row.addWidget(self.tx_edit); row.addWidget(self.tx_del); row.addStretch(1)
        lay.addLayout(row)
        self.tx_table = QTableWidget(0, 7)
        self.tx_table.setHorizontalHeaderLabels(["Date", "Type", "Category", "Amount", "Payee/Source", "Notes", "Tags"])
        self.tx_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tx_table, 1)

    def _build_bills_section(self) -> None:
        lay = QVBoxLayout(self._bill_tab)
        form = QGridLayout()
        self.bill_name = QLineEdit(); self.bill_amount = QLineEdit()
        self.bill_category = QComboBox(); self.bill_category.addItems(self._all_categories())
        self.bill_due = QDateEdit(QDate.currentDate()); self.bill_due.setCalendarPopup(True)
        self.bill_recur = QComboBox(); self.bill_recur.addItems(["weekly", "monthly", "quarterly", "yearly"])
        self.bill_lead = QSpinBox(); self.bill_lead.setRange(0, 60); self.bill_lead.setValue(3)
        self.bill_autopay = QCheckBox("Autopay")
        self.bill_sync = QCheckBox("Google Sync")
        self.bill_repeat = QSpinBox(); self.bill_repeat.setRange(15, 1440); self.bill_repeat.setValue(60)
        self.bill_notes = QLineEdit()
        items = [("Bill Name", self.bill_name), ("Amount", self.bill_amount), ("Category", self.bill_category),
                 ("Due Date", self.bill_due), ("Recurrence", self.bill_recur), ("Reminder Lead (days)", self.bill_lead),
                 ("Reminder Repeat (min)", self.bill_repeat), ("Notes", self.bill_notes)]
        for i, (lbl, w) in enumerate(items):
            form.addWidget(QLabel(lbl), i, 0); form.addWidget(w, i, 1)
        form.addWidget(self.bill_autopay, len(items), 0); form.addWidget(self.bill_sync, len(items), 1)
        lay.addLayout(form)
        row = QHBoxLayout()
        for txt, fn in [("Add", self._add_bill), ("Edit Selected", self._edit_bill), ("Delete Selected", self._delete_bill),
                        ("Mark Paid", self._mark_bill_paid), ("Snooze", self._snooze_bill), ("Reschedule", self._reschedule_bill)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(1); lay.addLayout(row)
        self.bill_table = QTableWidget(0, 9)
        self.bill_table.setHorizontalHeaderLabels(["Name", "Amount", "Category", "Due", "Recurrence", "Status", "Autopay", "Google Sync", "Notes"])
        self.bill_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.bill_table, 1)

    def _build_budget_section(self) -> None:
        lay = QVBoxLayout(self._budget_tab)
        form = QHBoxLayout()
        self.budget_category = QComboBox(); self.budget_category.addItems(self._all_categories())
        self.budget_amount = QLineEdit()
        self.budget_period = QComboBox(); self.budget_period.addItems(["monthly", "quarterly", "yearly"])
        add_btn = QPushButton("Add/Update"); add_btn.clicked.connect(self._upsert_budget_target)
        form.addWidget(QLabel("Category")); form.addWidget(self.budget_category)
        form.addWidget(QLabel("Planned Amount")); form.addWidget(self.budget_amount)
        form.addWidget(QLabel("Period")); form.addWidget(self.budget_period)
        form.addWidget(add_btn); form.addStretch(1)
        lay.addLayout(form)
        self.budget_table = QTableWidget(0, 5)
        self.budget_table.setHorizontalHeaderLabels(["Category", "Planned", "Actual", "Variance", "% Used"])
        self.budget_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.budget_table, 1)

    def _build_goals_section(self) -> None:
        lay = QVBoxLayout(self._goals_tab)
        form = QGridLayout()
        self.goal_name = QLineEdit(); self.goal_type = QComboBox(); self.goal_type.addItems(["savings goal", "emergency fund", "sinking fund", "debt payoff"])
        self.goal_target = QLineEdit(); self.goal_current = QLineEdit(); self.goal_monthly = QLineEdit()
        self.goal_deadline = QDateEdit(QDate.currentDate()); self.goal_deadline.setCalendarPopup(True); self.goal_deadline.setSpecialValueText("None")
        self.goal_notes = QLineEdit()
        gitems = [("Goal Name", self.goal_name), ("Goal Type", self.goal_type), ("Target Amount", self.goal_target),
                  ("Current Amount", self.goal_current), ("Monthly Contribution", self.goal_monthly), ("Deadline", self.goal_deadline), ("Notes", self.goal_notes)]
        for i, (lbl, w) in enumerate(gitems):
            form.addWidget(QLabel(lbl), i, 0); form.addWidget(w, i, 1)
        lay.addLayout(form)
        row = QHBoxLayout()
        for txt, fn in [("Add", self._add_goal), ("Edit Selected", self._edit_goal), ("Delete Selected", self._delete_goal)]:
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(1); lay.addLayout(row)
        self.goal_table = QTableWidget(0, 7)
        self.goal_table.setHorizontalHeaderLabels(["Name", "Type", "Current", "Target", "Monthly", "Progress %", "Deadline"])
        self.goal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.goal_table, 1)

    def _safe_amount(self, text: str) -> float:
        try: return float(str(text).replace(",", "").strip())
        except Exception: return 0.0

    def _month_key(self) -> str:
        return self.data.get("planner_settings", {}).get("view_month", date.today().strftime("%Y-%m"))

    def _is_current_month(self, value: str) -> bool:
        return str(value or "").startswith(self._month_key())

    def _add_transaction(self) -> None:
        row = {"id": str(uuid.uuid4()), "date": self.tx_date.date().toString("yyyy-MM-dd"), "type": self.tx_type.currentText(),
               "category": self.tx_category.currentText(), "amount": self._safe_amount(self.tx_amount.text()),
               "payee_or_source": self.tx_payee.text().strip(), "notes": self.tx_notes.text().strip(), "tags": self.tx_tags.text().strip()}
        self.data["transactions"].append(row); self.data["category_buckets"][row["category"]] = self.data["category_buckets"].get(row["category"], "needs")
        self._save_data(); self._refresh_all()

    def _edit_transaction(self) -> None:
        r = self.tx_table.currentRow()
        if r < 0 or r >= len(self.data["transactions"]): return
        self.data["transactions"][r].update({"date": self.tx_date.date().toString("yyyy-MM-dd"), "type": self.tx_type.currentText(),
                                             "category": self.tx_category.currentText(), "amount": self._safe_amount(self.tx_amount.text()),
                                             "payee_or_source": self.tx_payee.text().strip(), "notes": self.tx_notes.text().strip(), "tags": self.tx_tags.text().strip()})
        self._save_data(); self._refresh_all()

    def _delete_transaction(self) -> None:
        r = self.tx_table.currentRow()
        if r < 0 or r >= len(self.data["transactions"]): return
        self.data["transactions"].pop(r); self._save_data(); self._refresh_all()

    def _add_bill(self) -> None:
        bill = {"id": str(uuid.uuid4()), "name": self.bill_name.text().strip(), "amount": self._safe_amount(self.bill_amount.text()),
                "category": self.bill_category.currentText(), "due_date_or_day": self.bill_due.date().toString("yyyy-MM-dd"),
                "recurrence": self.bill_recur.currentText(), "reminder_offset": int(self.bill_lead.value()),
                "reminder_repeat_interval": int(self.bill_repeat.value()) * 60, "autopay_flag": bool(self.bill_autopay.isChecked()),
                "google_sync_flag": bool(self.bill_sync.isChecked()), "status": "unpaid", "notes": self.bill_notes.text().strip(),
                "snooze_until": "", "next_due": self.bill_due.date().toString("yyyy-MM-dd")}
        if bill["google_sync_flag"]:
            bill["google_sync_descriptor"] = self._build_google_sync_descriptor(bill)
        self.data["recurring_bills"].append(bill); self._save_data(); self._refresh_all()

    def _edit_bill(self) -> None:
        r = self.bill_table.currentRow()
        if r < 0 or r >= len(self.data["recurring_bills"]): return
        old = self.data["recurring_bills"][r]
        old.update({"name": self.bill_name.text().strip(), "amount": self._safe_amount(self.bill_amount.text()), "category": self.bill_category.currentText(),
                    "due_date_or_day": self.bill_due.date().toString("yyyy-MM-dd"), "recurrence": self.bill_recur.currentText(),
                    "reminder_offset": int(self.bill_lead.value()), "reminder_repeat_interval": int(self.bill_repeat.value()) * 60,
                    "autopay_flag": bool(self.bill_autopay.isChecked()), "google_sync_flag": bool(self.bill_sync.isChecked()),
                    "notes": self.bill_notes.text().strip()})
        if old.get("google_sync_flag"): old["google_sync_descriptor"] = self._build_google_sync_descriptor(old)
        self._save_data(); self._refresh_all()

    def _delete_bill(self) -> None:
        r = self.bill_table.currentRow()
        if r < 0 or r >= len(self.data["recurring_bills"]): return
        self.data["recurring_bills"].pop(r); self._save_data(); self._refresh_all()

    def _selected_bill(self) -> Optional[dict]:
        r = self.bill_table.currentRow()
        if r < 0 or r >= len(self.data["recurring_bills"]): return None
        return self.data["recurring_bills"][r]

    def _mark_bill_paid(self) -> None:
        bill = self._selected_bill()
        if not bill: return
        bill["status"] = "paid"
        bill["paid_at"] = local_now_iso()
        bill["next_due"] = self._advance_due_date(bill.get("next_due") or bill.get("due_date_or_day"), bill.get("recurrence", "monthly"))
        self.data["bill_activity"].append({"date": date.today().isoformat(), "type": "bill_paid", "category": bill.get("category",""),
                                           "amount": bill.get("amount",0.0), "note": bill.get("name","")})
        self._save_data(); self._refresh_all()

    def _snooze_bill(self) -> None:
        bill = self._selected_bill()
        if not bill: return
        mins, ok = QInputDialog.getInt(self, "Snooze Bill Reminder", "Snooze for minutes:", 120, 15, 10080)
        if not ok: return
        bill["snooze_until"] = (datetime.now() + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S")
        bill["status"] = "snoozed"
        self._save_data(); self._refresh_all()

    def _reschedule_bill(self) -> None:
        bill = self._selected_bill()
        if not bill: return
        new_due, ok = QInputDialog.getText(self, "Reschedule Bill", "New due date (YYYY-MM-DD):", text=str(bill.get("next_due") or bill.get("due_date_or_day") or ""))
        if not ok or not new_due.strip(): return
        bill["next_due"] = new_due.strip()
        bill["status"] = "unpaid"
        bill["snooze_until"] = ""
        self._save_data(); self._refresh_all()

    def _upsert_budget_target(self) -> None:
        rec = {"category": self.budget_category.currentText(), "planned_amount": self._safe_amount(self.budget_amount.text()), "period": self.budget_period.currentText()}
        found = False
        for idx, row in enumerate(self.data["budget_targets"]):
            if row.get("category") == rec["category"] and row.get("period", "monthly") == rec["period"]:
                self.data["budget_targets"][idx] = rec; found = True; break
        if not found: self.data["budget_targets"].append(rec)
        self._save_data(); self._refresh_all()

    def _add_goal(self) -> None:
        rec = {"id": str(uuid.uuid4()), "name": self.goal_name.text().strip(), "type": self.goal_type.currentText(),
               "target_amount": self._safe_amount(self.goal_target.text()), "current_amount": self._safe_amount(self.goal_current.text()),
               "monthly_contribution": self._safe_amount(self.goal_monthly.text()), "deadline": self.goal_deadline.date().toString("yyyy-MM-dd"),
               "notes": self.goal_notes.text().strip()}
        self.data["goals"].append(rec); self._save_data(); self._refresh_all()

    def _edit_goal(self) -> None:
        r = self.goal_table.currentRow()
        if r < 0 or r >= len(self.data["goals"]): return
        self.data["goals"][r].update({"name": self.goal_name.text().strip(), "type": self.goal_type.currentText(),
                                      "target_amount": self._safe_amount(self.goal_target.text()), "current_amount": self._safe_amount(self.goal_current.text()),
                                      "monthly_contribution": self._safe_amount(self.goal_monthly.text()), "deadline": self.goal_deadline.date().toString("yyyy-MM-dd"),
                                      "notes": self.goal_notes.text().strip()})
        self._save_data(); self._refresh_all()

    def _delete_goal(self) -> None:
        r = self.goal_table.currentRow()
        if r < 0 or r >= len(self.data["goals"]): return
        self.data["goals"].pop(r); self._save_data(); self._refresh_all()

    def _advance_due_date(self, due_text: str, recurrence: str) -> str:
        try: d = datetime.strptime(str(due_text), "%Y-%m-%d").date()
        except Exception: d = date.today()
        if recurrence == "weekly": d = d + timedelta(days=7)
        elif recurrence == "monthly": d = d + timedelta(days=30)
        elif recurrence == "quarterly": d = d + timedelta(days=91)
        else: d = d + timedelta(days=365)
        return d.strftime("%Y-%m-%d")

    def _build_google_sync_descriptor(self, bill: dict) -> dict:
        return {
            "title": f"Bill Due — {bill.get('name','Unnamed Bill')}",
            "description": f"Amount: {bill.get('amount',0.0)} | Category: {bill.get('category','')} | Notes: {bill.get('notes','')} | Recurrence: {bill.get('recurrence','monthly')}",
            "recurring": True,
            "source_of_truth": "financial_planner_local",
            "last_synced": local_now_iso(),
        }

    def _emit_hidden_ai_reminder(self, bill: dict, due_status: str) -> None:
        payload = {"intent": "financial_bill_reminder", "bill_name": bill.get("name",""), "amount": bill.get("amount", 0.0),
                   "due_status": due_status, "category": bill.get("category",""), "note": bill.get("notes","")}
        try:
            messages_path = cfg_path("memories") / "messages.jsonl"
            records = read_jsonl(messages_path)
            records.append({"timestamp": local_now_iso(), "role": "user", "speaker": "internal", "content": "[INTERNAL_EVENT] " + json.dumps(payload, ensure_ascii=False)})
            write_jsonl(messages_path, records)
        except Exception as e:
            self._log(f"[FINANCIAL] hidden AI reminder write failed: {e}", "WARN")

    def _check_bill_reminders(self) -> None:
        now_dt = datetime.now()
        for bill in self.data.get("recurring_bills", []):
            if bill.get("status") == "paid":
                continue
            due_text = str(bill.get("next_due") or bill.get("due_date_or_day") or "")
            try: due_dt = datetime.strptime(due_text, "%Y-%m-%d")
            except Exception: continue
            snooze_until = str(bill.get("snooze_until") or "").strip()
            if snooze_until:
                try:
                    if datetime.strptime(snooze_until, "%Y-%m-%d %H:%M:%S") > now_dt:
                        continue
                except Exception:
                    pass
            lead_days = int(bill.get("reminder_offset", 3) or 3)
            remind_from = due_dt - timedelta(days=lead_days)
            if now_dt < remind_from:
                continue
            interval = int(bill.get("reminder_repeat_interval") or self.data.get("planner_settings", {}).get("reminder_repeat_interval", 3600))
            last_fire = self._bill_last_reminder.get(bill.get("id",""))
            if last_fire and (now_dt - last_fire).total_seconds() < max(60, interval):
                continue
            due_status = "overdue" if now_dt.date() > due_dt.date() else "due_soon" if now_dt.date() < due_dt.date() else "due_today"
            self._bill_last_reminder[bill.get("id","")] = now_dt
            bill["status"] = "overdue" if due_status == "overdue" else bill.get("status", "unpaid")
            self._emit_hidden_ai_reminder(bill, due_status)
            self._log(f"[FINANCIAL] Reminder: {bill.get('name','Bill')} ({due_status})", "INFO")
        self._save_data()
        self._refresh_dashboard()

    def _export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Financial Planner", str(cfg_path("exports") / f"financial_planner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"),
                                              "Text (*.txt);;CSV (*.csv);;Excel (*.xlsx);;PDF (*.pdf)")
        if not path: return
        ext = Path(path).suffix.lower()
        payload = self._export_payload()
        if ext == ".csv": self._write_csv_export(path, payload)
        elif ext == ".xlsx": self._write_xlsx_export(path, payload)
        elif ext == ".pdf": self._write_pdf_export(path, payload)
        else: Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _export_payload(self) -> dict:
        return {
            "generated_at": local_now_iso(),
            "recurring_bills_list": self.data.get("recurring_bills", []),
            "monthly_bills_snapshot": self._monthly_bill_snapshot(),
            "paid_unpaid_snapshot": self._paid_unpaid_snapshot(),
            "transaction_ledger": self.data.get("transactions", []),
            "budget_target_vs_actual_summary": self._budget_rows(),
            "goals_progress_summary": self.data.get("goals", []),
            "monthly_financial_review_data": self._review_context(),
        }

    def _write_csv_export(self, path: str, payload: dict) -> None:
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["section", "record_json"])
            for key, val in payload.items():
                if isinstance(val, list):
                    for item in val: w.writerow([key, json.dumps(item, ensure_ascii=False)])
                else:
                    w.writerow([key, json.dumps(val, ensure_ascii=False)])

    def _write_xlsx_export(self, path: str, payload: dict) -> None:
        try:
            from openpyxl import Workbook
            wb = Workbook(); ws = wb.active; ws.title = "Financial Planner"
            ws.append(["section", "record_json"])
            for key, val in payload.items():
                if isinstance(val, list):
                    for item in val: ws.append([key, json.dumps(item, ensure_ascii=False)])
                else:
                    ws.append([key, json.dumps(val, ensure_ascii=False)])
            wb.save(path)
        except Exception:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_pdf_export(self, path: str, payload: dict) -> None:
        lines = json.dumps(payload, ensure_ascii=False, indent=2).splitlines()[:160]
        stream = "BT /F1 9 Tf 40 800 Td " + " ".join(f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines) + " ET"
        pdf = f"%PDF-1.4\\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 842]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\\n4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\\n5 0 obj<</Length {len(stream)}>>stream\\n{stream}\\nendstream endobj\\nxref\\n0 6\\n0000000000 65535 f \\n0000000010 00000 n \\n0000000060 00000 n \\n0000000120 00000 n \\n0000000240 00000 n \\n0000000310 00000 n \\ntrailer<</Root 1 0 R/Size 6>>\\nstartxref\\n420\\n%%EOF"
        Path(path).write_text(pdf, encoding="latin-1", errors="ignore")

    def _import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Financial Planner", str(cfg_path("exports")), "Structured Files (*.txt *.csv *.xlsx)")
        if not path: return
        mode, ok = QInputDialog.getItem(self, "Import Mode", "Choose import mode:", ["append", "replace matching", "full replace"], 0, False)
        if not ok: return
        records = self._read_import_records(path)
        if not records:
            QMessageBox.warning(self, "Financial Planner", "No valid import records found.")
            return
        self._apply_import_records(records, mode)
        self._save_data(); self._refresh_all()

    def _read_import_records(self, path: str) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        p = Path(path); ext = p.suffix.lower()
        try:
            if ext == ".csv":
                import csv
                with p.open("r", encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        section = row.get("section", "")
                        raw = row.get("record_json", "")
                        try: obj = json.loads(raw)
                        except Exception: continue
                        if isinstance(obj, dict): out.append((section, obj))
            elif ext == ".xlsx":
                from openpyxl import load_workbook
                wb = load_workbook(p); ws = wb.active
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not row or len(row) < 2: continue
                    section = str(row[0] or ""); raw = str(row[1] or "")
                    try: obj = json.loads(raw)
                    except Exception: continue
                    if isinstance(obj, dict): out.append((section, obj))
            else:
                blob = json.loads(p.read_text(encoding="utf-8"))
                for section, val in blob.items():
                    if isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict): out.append((section, item))
        except Exception as e:
            self._log(f"[FINANCIAL] import parse issue: {e}", "WARN")
        return out

    def _apply_import_records(self, rows: list[tuple[str, dict]], mode: str) -> None:
        section_map = {"transaction_ledger": "transactions", "recurring_bills_list": "recurring_bills",
                       "budget_target_vs_actual_summary": "budget_targets", "goals_progress_summary": "goals"}
        if mode == "full replace":
            for key in ("transactions", "recurring_bills", "budget_targets", "goals"):
                self.data[key] = []
        for sec, rec in rows:
            key = section_map.get(sec)
            if not key: continue
            if mode == "replace matching":
                rid = rec.get("id")
                if rid:
                    replaced = False
                    for i, old in enumerate(self.data[key]):
                        if old.get("id") == rid:
                            self.data[key][i] = rec; replaced = True; break
                    if not replaced: self.data[key].append(rec)
                else:
                    self.data[key].append(rec)
            else:
                self.data[key].append(rec)

    def _monthly_bill_snapshot(self) -> dict:
        month = self._month_key()
        bills = [b for b in self.data.get("recurring_bills", []) if str(b.get("next_due") or b.get("due_date_or_day") or "").startswith(month)]
        return {"month": month, "count": len(bills), "total_amount": sum(float(b.get("amount", 0.0) or 0.0) for b in bills)}

    def _paid_unpaid_snapshot(self) -> dict:
        bills = self.data.get("recurring_bills", [])
        paid = len([b for b in bills if b.get("status") == "paid"])
        return {"paid": paid, "unpaid": len(bills) - paid}

    def _review_context(self) -> dict:
        income = sum(float(t.get("amount", 0.0) or 0.0) for t in self.data.get("transactions", []) if t.get("type") == "income" and self._is_current_month(t.get("date","")))
        expenses = sum(float(t.get("amount", 0.0) or 0.0) for t in self.data.get("transactions", []) if t.get("type") == "expense" and self._is_current_month(t.get("date","")))
        cat_totals = {}
        for t in self.data.get("transactions", []):
            if t.get("type") != "expense" or not self._is_current_month(t.get("date","")): continue
            cat = t.get("category", "Uncategorized")
            cat_totals[cat] = cat_totals.get(cat, 0.0) + float(t.get("amount", 0.0) or 0.0)
        due = [b.get("name","") for b in self.data.get("recurring_bills", []) if b.get("status") in ("unpaid", "overdue")]
        goal_progress = [{ "name": g.get("name",""), "progress_pct": round((float(g.get("current_amount",0.0) or 0.0) / max(1.0, float(g.get("target_amount",0.0) or 0.0))) * 100.0, 1)} for g in self.data.get("goals",[])]
        return {"total_income": round(income, 2), "total_expenses": round(expenses, 2), "net_cash_flow": round(income - expenses, 2),
                "largest_categories": sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:5],
                "due_or_overdue_bills": due, "goal_progress": goal_progress}

    def _generate_monthly_review(self) -> None:
        ctx = self._review_context()
        payload = {"intent": "financial_monthly_review", "context": ctx}
        summary = (
            f"Income: {ctx['total_income']:.2f}, Expenses: {ctx['total_expenses']:.2f}, Net: {ctx['net_cash_flow']:.2f}. "
            f"Largest categories: {', '.join([f'{c} ({a:.2f})' for c, a in ctx['largest_categories'][:3]]) or 'None'}. "
            f"Due/overdue bills: {len(ctx['due_or_overdue_bills'])}. Keep contributions steady and review high-variance categories."
        )
        self._emit_hidden_ai_reminder({"name": "Monthly Review", "amount": ctx["net_cash_flow"], "category": "review", "notes": json.dumps(payload)}, "monthly_review")
        QMessageBox.information(self, "Monthly AI Review", summary)

    def _budget_rows(self) -> list[dict]:
        rows = []
        for b in self.data.get("budget_targets", []):
            cat = b.get("category", "")
            planned = float(b.get("planned_amount", 0.0) or 0.0)
            actual = sum(float(t.get("amount", 0.0) or 0.0) for t in self.data.get("transactions", []) if t.get("type") == "expense" and t.get("category") == cat and self._is_current_month(t.get("date","")))
            variance = planned - actual
            pct = (actual / planned * 100.0) if planned > 0 else 0.0
            rows.append({"category": cat, "planned_amount": round(planned,2), "actual": round(actual,2), "variance": round(variance,2), "pct_used": round(pct,1), "period": b.get("period","monthly")})
        return rows

    def _refresh_all(self) -> None:
        self._refresh_transactions()
        self._refresh_bills()
        self._refresh_budget()
        self._refresh_goals()
        self._refresh_dashboard()

    def _refresh_transactions(self) -> None:
        rows = self.data.get("transactions", [])
        self.tx_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            vals = [item.get("date",""), item.get("type",""), item.get("category",""), f"{float(item.get('amount',0.0) or 0.0):.2f}",
                    item.get("payee_or_source",""), item.get("notes",""), item.get("tags","")]
            for c, v in enumerate(vals): self.tx_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _refresh_bills(self) -> None:
        rows = self.data.get("recurring_bills", [])
        self.bill_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            vals = [item.get("name",""), f"{float(item.get('amount',0.0) or 0.0):.2f}", item.get("category",""),
                    item.get("next_due") or item.get("due_date_or_day",""), item.get("recurrence",""), item.get("status","unpaid"),
                    "Yes" if item.get("autopay_flag") else "No", "Yes" if item.get("google_sync_flag") else "No", item.get("notes","")]
            for c, v in enumerate(vals): self.bill_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _refresh_budget(self) -> None:
        rows = self._budget_rows()
        self.budget_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            vals = [item.get("category",""), f"{item.get('planned_amount',0.0):.2f}", f"{item.get('actual',0.0):.2f}",
                    f"{item.get('variance',0.0):.2f}", f"{item.get('pct_used',0.0):.1f}%"]
            for c, v in enumerate(vals): self.budget_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _refresh_goals(self) -> None:
        rows = self.data.get("goals", [])
        self.goal_table.setRowCount(len(rows))
        for r, g in enumerate(rows):
            target = float(g.get("target_amount", 0.0) or 0.0)
            current = float(g.get("current_amount", 0.0) or 0.0)
            pct = (current / target * 100.0) if target > 0 else 0.0
            vals = [g.get("name",""), g.get("type",""), f"{current:.2f}", f"{target:.2f}", f"{float(g.get('monthly_contribution',0.0) or 0.0):.2f}", f"{pct:.1f}", g.get("deadline","")]
            for c, v in enumerate(vals): self.goal_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _refresh_dashboard(self) -> None:
        month = self._month_key()
        tx = [t for t in self.data.get("transactions", []) if self._is_current_month(t.get("date",""))]
        income = sum(float(t.get("amount",0.0) or 0.0) for t in tx if t.get("type") == "income")
        expenses = sum(float(t.get("amount",0.0) or 0.0) for t in tx if t.get("type") == "expense")
        now = date.today()
        due_soon = 0; overdue = 0; recurring = 0
        for b in self.data.get("recurring_bills", []):
            due = str(b.get("next_due") or b.get("due_date_or_day") or "")
            try: due_d = datetime.strptime(due, "%Y-%m-%d").date()
            except Exception: continue
            recurring += 1
            if b.get("status") == "paid": continue
            if due_d < now: overdue += 1
            elif due_d <= now + timedelta(days=7): due_soon += 1
        self._monthly_snapshot.setText(f"Month: {month} | Total Income: {income:.2f} | Total Expenses: {expenses:.2f} | Net Cash Flow: {income-expenses:.2f} | Bills Due Soon: {due_soon} | Overdue Bills: {overdue} | Upcoming Subscriptions/Recurring Bills: {recurring}")

        buckets = {"needs": 0.0, "wants": 0.0, "savings_debt": 0.0}
        for t in tx:
            if t.get("type") != "expense": continue
            cat = t.get("category", "")
            bucket = self.data.get("category_buckets", {}).get(cat, "needs")
            if bucket not in buckets: bucket = "needs"
            buckets[bucket] += float(t.get("amount", 0.0) or 0.0)
        total_spend = max(0.01, sum(buckets.values()))
        pct = {k: round(v / total_spend * 100.0, 1) for k, v in buckets.items()}
        self._guidance_snapshot.setText(
            f"Needs: {buckets['needs']:.2f} ({pct['needs']}%, target 50%, {'over' if pct['needs'] > 50 else 'under'}) | "
            f"Wants: {buckets['wants']:.2f} ({pct['wants']}%, target 30%, {'over' if pct['wants'] > 30 else 'under'}) | "
            f"Savings/Debt: {buckets['savings_debt']:.2f} ({pct['savings_debt']}%, target 20%, {'over' if pct['savings_debt'] > 20 else 'under'})"
        )

        goals = self.data.get("goals", [])
        self._goals_snapshot.setRowCount(len(goals))
        for r, g in enumerate(goals):
            cur = float(g.get("current_amount", 0.0) or 0.0); tgt = float(g.get("target_amount", 0.0) or 0.0); mon = float(g.get("monthly_contribution", 0.0) or 0.0)
            pctg = (cur / tgt * 100.0) if tgt > 0 else 0.0
            rem = max(0.0, tgt - cur); proj = f\"{int(math.ceil(rem / mon))} mo\" if mon > 0 and rem > 0 else \"n/a\"
            vals = [g.get("name",""), f"{cur:.2f}", f"{tgt:.2f}", f"{pctg:.1f}", proj]
            for c, v in enumerate(vals): self._goals_snapshot.setItem(r, c, QTableWidgetItem(str(v)))

        activity = sorted(
            [{"date": x.get("date",""), "type": x.get("type",""), "category": x.get("category",""), "amount": x.get("amount",0.0), "note": x.get("payee_or_source","") or x.get("notes","")} for x in tx] + self.data.get("bill_activity", []),
            key=lambda z: z.get("date",""),
            reverse=True
        )[:20]
        self._recent_snapshot.setRowCount(len(activity))
        for r, a in enumerate(activity):
            vals = [a.get("date",""), a.get("type",""), a.get("category",""), f"{float(a.get('amount',0.0) or 0.0):.2f}", a.get("note","")]
            for c, v in enumerate(vals): self._recent_snapshot.setItem(r, c, QTableWidgetItem(str(v)))


class DiceTrayDie(QFrame):
""",
        "financial planner class injection",
    )
    source = _replace_once(
        source,
        "        # ── Module Tracker tab ─────────────────────────────────────────\n"
        "        self._module_tracker = ModuleTrackerTab()\n"
        "\n"
        "        # ── Dice Roller tab ────────────────────────────────────────────\n",
        "        # ── Module Tracker tab ─────────────────────────────────────────\n"
        "        self._module_tracker = ModuleTrackerTab()\n"
        "\n"
        "        # ── Financial Planner tab ──────────────────────────────────────\n"
        "        self._financial_planner_tab = FinancialPlannerTab(diagnostics_logger=self._diag_tab.log)\n"
        "\n"
        "        # ── Dice Roller tab ────────────────────────────────────────────\n",
        "financial planner tab instantiation",
    )
    source = _replace_once(
        source,
        '            {"id": "modules", "title": "Modules", "widget": self._module_tracker, "default_order": 7},\n'
        '            {"id": "dice_roller", "title": "Dice Roller", "widget": self._dice_roller_tab, "default_order": 8},\n'
        '            {"id": "magic_8_ball", "title": "Magic 8-Ball", "widget": self._magic_8ball_tab, "default_order": 9},\n'
        '            {"id": "diagnostics", "title": "Diagnostics", "widget": self._diag_tab, "default_order": 10},\n'
        '            {"id": "settings", "title": "Settings", "widget": self._settings_tab, "default_order": 11},\n',
        '            {"id": "modules", "title": "Modules", "widget": self._module_tracker, "default_order": 7},\n'
        '            {"id": "financial_planner", "title": "Financial Planner", "widget": self._financial_planner_tab, "default_order": 8},\n'
        '            {"id": "dice_roller", "title": "Dice Roller", "widget": self._dice_roller_tab, "default_order": 9},\n'
        '            {"id": "magic_8_ball", "title": "Magic 8-Ball", "widget": self._magic_8ball_tab, "default_order": 10},\n'
        '            {"id": "diagnostics", "title": "Diagnostics", "widget": self._diag_tab, "default_order": 11},\n'
        '            {"id": "settings", "title": "Settings", "widget": self._settings_tab, "default_order": 12},\n',
        "financial planner tab definition order",
    )
    source = _replace_once(
        source,
        "        self._load_spell_tab_state_from_config()\n"
        "        self._rebuild_spell_tabs()\n",
        "        self._init_category_framework()\n"
        "        self._load_spell_tab_state_from_config()\n"
        "        self._rebuild_spell_tabs()\n",
        "initialize category framework",
    )
    source = _replace_once(
        source,
        "        right_workspace_layout.addWidget(self._spell_tabs, 1)\n",
        "        self._category_strip = QWidget()\n"
        "        self._category_strip_layout = QHBoxLayout(self._category_strip)\n"
        "        self._category_strip_layout.setContentsMargins(0, 0, 0, 0)\n"
        "        self._category_strip_layout.setSpacing(4)\n"
        "        right_workspace_layout.addWidget(self._category_strip, 0)\n"
        "        right_workspace_layout.addWidget(self._spell_tabs, 1)\n",
        "inject category strip host",
    )
    source = _replace_once(
        source,
        "    def _load_spell_tab_state_from_config(self) -> None:\n",
        "    def _init_category_framework(self) -> None:\n"
        "        self._protected_categories = {\"System\", \"Core\"}\n"
        "        self._category_map = {}\n"
        "        self._module_registry = {}\n"
        "        for tab in self._spell_tab_defs:\n"
        "            tab.setdefault(\"category\", \"Core\")\n"
        "            tab.setdefault(\"secondary_categories\", [])\n"
        "            tab.setdefault(\"protected_category\", tab.get(\"category\") in self._protected_categories)\n"
        "            self._register_module_categories(tab)\n"
        "        self._active_category = \"Core\" if \"Core\" in self._category_map else next(iter(self._category_map.keys()), \"Core\")\n"
        "        self._rebuild_category_strip()\n"
        "\n"
        "    def _register_module_categories(self, tab: dict) -> None:\n"
        "        tab_id = str(tab.get(\"id\") or \"\").strip()\n"
        "        if not tab_id:\n"
        "            return\n"
        "        primary = str(tab.get(\"category\") or \"Core\").strip() or \"Core\"\n"
        "        secondary = [str(c).strip() for c in tab.get(\"secondary_categories\", []) if str(c).strip()]\n"
        "        self._module_registry[tab_id] = {\"id\": tab_id, \"installed\": True, \"enabled\": True, \"primary\": primary, \"secondary\": secondary}\n"
        "        self._category_map.setdefault(primary, {\"modules\": set(), \"protected\": bool(tab.get(\"protected_category\", False) or primary in self._protected_categories)})\n"
        "        self._category_map[primary][\"modules\"].add(tab_id)\n"
        "        for cat in secondary:\n"
        "            if cat in self._category_map:\n"
        "                self._category_map[cat][\"modules\"].add(tab_id)\n"
        "\n"
        "    def _rebuild_category_strip(self) -> None:\n"
        "        if not hasattr(self, \"_category_strip_layout\"):\n"
        "            return\n"
        "        while self._category_strip_layout.count():\n"
        "            item = self._category_strip_layout.takeAt(0)\n"
        "            w = item.widget()\n"
        "            if w is not None:\n"
        "                w.deleteLater()\n"
        "        cats = list(self._category_map.keys())\n"
        "        if self._active_category not in cats and cats:\n"
        "            self._active_category = cats[0]\n"
        "        for cat in cats:\n"
        "            btn = QToolButton()\n"
        "            btn.setText(cat)\n"
        "            btn.setCheckable(True)\n"
        "            btn.setChecked(cat == self._active_category)\n"
        "            btn.clicked.connect(lambda _checked=False, c=cat: self._select_category(c))\n"
        "            self._category_strip_layout.addWidget(btn)\n"
        "        self._category_strip_layout.addStretch(1)\n"
        "\n"
        "    def _select_category(self, category: str) -> None:\n"
        "        if category not in self._category_map:\n"
        "            return\n"
        "        self._active_category = category\n"
        "        self._rebuild_category_strip()\n"
        "        self._rebuild_spell_tabs()\n"
        "\n"
        "    def _visible_tab_for_active_category(self, tab: dict) -> bool:\n"
        "        tab_id = str(tab.get(\"id\") or \"\")\n"
        "        reg = self._module_registry.get(tab_id, {})\n"
        "        if not reg.get(\"installed\", True) or not reg.get(\"enabled\", True):\n"
        "            return False\n"
        "        return (not self._active_category) or tab_id in self._category_map.get(self._active_category, {}).get(\"modules\", set())\n"
        "\n"
        "    def _disable_module(self, tab_id: str) -> None:\n"
        "        if tab_id in self._module_registry:\n"
        "            self._module_registry[tab_id][\"enabled\"] = False\n"
        "            self._rebuild_spell_tabs()\n"
        "\n"
        "    def _uninstall_module(self, tab_id: str, delete_files: bool = False) -> None:\n"
        "        reg = self._module_registry.get(tab_id)\n"
        "        if not reg:\n"
        "            return\n"
        "        reg[\"installed\"] = False\n"
        "        reg[\"enabled\"] = False\n"
        "        for cat_data in self._category_map.values():\n"
        "            cat_data.get(\"modules\", set()).discard(tab_id)\n"
        "        self._cleanup_empty_categories()\n"
        "        self._rebuild_category_strip()\n"
        "        self._rebuild_spell_tabs()\n"
        "\n"
        "    def _reinstall_modules_from_library(self) -> None:\n"
        "        for tab in self._spell_tab_defs:\n"
        "            tab_id = str(tab.get(\"id\") or \"\")\n"
        "            if not tab_id:\n"
        "                continue\n"
        "            reg = self._module_registry.setdefault(tab_id, {\"id\": tab_id, \"installed\": True, \"enabled\": True, \"primary\": str(tab.get(\"category\") or \"Core\"), \"secondary\": [str(c).strip() for c in tab.get(\"secondary_categories\", []) if str(c).strip()]})\n"
        "            reg[\"installed\"] = True\n"
        "            reg[\"enabled\"] = True\n"
        "            primary = reg.get(\"primary\") or \"Core\"\n"
        "            self._category_map.setdefault(primary, {\"modules\": set(), \"protected\": bool(tab.get(\"protected_category\", False) or primary in self._protected_categories)})\n"
        "            self._category_map[primary][\"modules\"].add(tab_id)\n"
        "            for cat in reg.get(\"secondary\", []):\n"
        "                if cat in self._category_map:\n"
        "                    self._category_map[cat][\"modules\"].add(tab_id)\n"
        "        self._cleanup_empty_categories()\n"
        "        self._rebuild_category_strip()\n"
        "        self._rebuild_spell_tabs()\n"
        "\n"
        "    def _cleanup_empty_categories(self) -> None:\n"
        "        remove = []\n"
        "        for cat, data in self._category_map.items():\n"
        "            if data.get(\"modules\"):\n"
        "                continue\n"
        "            if data.get(\"protected\") or cat in self._protected_categories:\n"
        "                continue\n"
        "            remove.append(cat)\n"
        "        for cat in remove:\n"
        "            self._category_map.pop(cat, None)\n"
        "        if self._active_category not in self._category_map:\n"
        "            self._active_category = next(iter(self._category_map.keys()), \"Core\")\n"
        "\n"
        "    def _load_spell_tab_state_from_config(self) -> None:\n",
        "inject category framework and lifecycle",
    )
    source = _replace_once(
        source,
        "        for tab in self._ordered_spell_tab_defs():\n"
        "            i = self._spell_tabs.addTab(tab[\"widget\"], tab[\"title\"])\n",
        "        for tab in self._ordered_spell_tab_defs():\n"
        "            if not self._visible_tab_for_active_category(tab):\n"
        "                continue\n"
        "            i = self._spell_tabs.addTab(tab[\"widget\"], tab[\"title\"])\n",
        "category-aware visible tabs",
    )
    return source


def _prune_optional_runtime_tabs(source: str, selected_modules: list[str], log_fn=None) -> str:
    selected = set(selected_modules or [])
    optional_tab_map = {
        "sl_scans": {"sl_scans"},
        "sl_commands": {"sl_commands"},
        "job_tracker": {"job_tracker"},
        "lessons_learned": {"lessons"},
        "dice_roller": {"dice_roller"},
        "magic_8ball": {"magic_8_ball"},
        "bill_scheduler": {"financial_planner"},
        "cvr_engine": {"cvr"},
        "session_browser": {"modules"},
    }
    remove_ids: set[str] = set()
    for mod_key, tab_ids in optional_tab_map.items():
        if mod_key not in selected:
            remove_ids.update(tab_ids)

    if not remove_ids:
        return source

    filtered_lines: list[str] = []
    removed = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith('{"id": "') and '"title": "' in stripped:
            for tab_id in remove_ids:
                if f'"id": "{tab_id}"' in stripped:
                    removed += 1
                    break
            else:
                filtered_lines.append(line)
            continue
        filtered_lines.append(line)
    if log_fn:
        log_fn(f"[DECK] Optional tab rows removed: {removed}")
    return "\n".join(filtered_lines) + "\n"


def _get_deck_implementation(selected_modules: Optional[list[str]] = None, log_fn=None) -> str:
    """
    Returns the full embedded deck implementation.
    Completely self-contained — no external files required.

    Embedded implementation includes:
      - Draggable main left/right QSplitter shell layout
      - Minimum-width guards for both panes
      - Deck-config persistence/restore for main splitter sizes
    """
    import base64 as _base64
    if log_fn:
        log_fn("[DECK] Using embedded implementation")
    decoded = _base64.b64decode(_DECK_IMPL_B64).decode("utf-8")
    patched = _patch_embedded_deck_implementation(decoded, log_fn=log_fn)
    return _prune_optional_runtime_tabs(patched, selected_modules or [], log_fn=log_fn)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SETUP WORKER
#
# Runs the full deck creation sequence in a background thread.
# Emits log messages and progress for the UI to display.
# All file operations happen here — never on the main thread.
# ═══════════════════════════════════════════════════════════════════════════════


class DeckSetupWorker(QThread):
    """
    Background worker that creates a complete deck installation.

    Sequence:
      1. Create directory structure
      2. Extract and rename face pack (ZIP or folder)
      3. Convert icon PNG to ICO
      4. Generate sound WAV files
      5. Write config.json
      6. Initialize memory/session JSONL files
      7. Write deck Python file (injected template)
      8. Write requirements.txt
      9. Create desktop shortcut

    Signals:
        log(str)           — progress message for display
        progress(int)      — 0-100
        done(bool, str)    — success flag, result message or error
    """

    log      = Signal(str)
    progress = Signal(int)
    done     = Signal(bool, str)

    def __init__(
        self,
        deck_name:        str,
        persona:          dict,
        model_config:     dict,
        selected_modules: list[str],
        face_source:      str,          # path to ZIP or folder, or ""
        create_shortcut:  bool,
        output_base:      Path,         # e.g. D:\AI\Models
        ai_state_greetings: Optional[dict] = None,
    ):
        super().__init__()
        self._deck_name        = deck_name
        self._persona          = persona
        self._ai_state_greetings = ai_state_greetings
        self._model_config     = model_config
        self._selected_modules = selected_modules
        self._face_source      = face_source
        self._create_shortcut  = create_shortcut
        self._output_base      = output_base

    def _log(self, msg: str) -> None:
        self.log.emit(msg)

    def run(self) -> None:
        try:
            deck_lower = self._deck_name.lower().replace(" ", "_")
            deck_home  = self._output_base / self._deck_name

            self._log(f"Creating deck: {self._deck_name}")
            self._log(f"Location: {deck_home}")

            # ── 1. Create directory structure ──────────────────────────
            self._log("Creating directory structure...")
            dirs = [
                deck_home / "Faces",
                deck_home / "sounds",
                deck_home / "memories",
                deck_home / "sessions",
                deck_home / "sl",
                deck_home / "exports",
                deck_home / "logs",
                deck_home / "backups",
                deck_home / "personas",
                deck_home / "config",
            ]
            for d in dirs:
                d.mkdir(parents=True, exist_ok=True)
            self._log("✓ Directory structure created")
            self.progress.emit(10)

            # ── 2. Extract and rename face pack ────────────────────────
            face_prefix = self._persona.get("face_prefix", self._deck_name)
            icon_path   = None

            if self._face_source and Path(self._face_source).exists():
                self._log(f"Extracting face pack...")
                face_result = extract_faces(
                    source      = self._face_source,
                    dest_dir    = deck_home / "Faces",
                    face_prefix = face_prefix,
                    deck_name   = self._deck_name,
                    log_fn      = self._log,
                )
                if face_result["errors"]:
                    for err in face_result["errors"]:
                        self._log(f"  ⚠ {err}")
                self._log(
                    f"✓ Faces: {face_result['extracted']} extracted, "
                    f"{face_result['skipped']} skipped, "
                    f"{face_result['unrecognized']} unrecognized"
                )
                icon_path = face_result.get("icon_path")
            else:
                self._log(
                    "⚠ No face pack provided — using placeholder. "
                    "Add faces to Faces/ later."
                )
            self.progress.emit(25)

            # ── 3. Convert icon ────────────────────────────────────────
            ico_path = None
            if icon_path and icon_path.exists():
                ico_path = deck_home / f"{self._deck_name}.ico"
                self._log(f"Converting icon: {icon_path.name} → {ico_path.name}")
                ok = convert_png_to_ico(icon_path, ico_path, log_fn=self._log)
                if ok:
                    self._log(f"✓ Icon created: {ico_path.name}")
                else:
                    self._log("⚠ Icon conversion failed — shortcut will use default icon")
                    ico_path = None
            self.progress.emit(35)

            # ── 4. Generate sound files ────────────────────────────────
            sound_profile = self._persona.get("sound_profile", "default_chime")
            self._log(f"Generating sounds (profile: {sound_profile})...")
            generate_sounds_for_profile(
                profile_name    = sound_profile,
                sounds_dir      = deck_home / "sounds",
                deck_name_prefix= deck_lower,
                log_fn          = self._log,
            )
            self._log("✓ Sound files ready")
            self.progress.emit(50)

            # ── 5. Write config.json ───────────────────────────────────
            self._log("Writing config.json...")
            self._write_config(deck_home, deck_lower)
            self._log("✓ config.json written")
            self.progress.emit(60)

            # ── 6. Initialize memory files ────────────────────────────
            self._log("Initializing memory files...")
            self._init_memory_files(deck_home)
            self._log("✓ Memory files initialized")
            self.progress.emit(68)

            # ── 7. Write deck Python file ──────────────────────────────
            deck_filename = f"{deck_lower}_deck.py"
            deck_path     = deck_home / deck_filename
            self._log(f"Writing deck file: {deck_filename}...")

            ok = build_deck_file(
                persona          = self._persona,
                deck_name        = self._deck_name,
                selected_modules = self._selected_modules,
                output_path      = deck_path,
                model_config     = self._model_config,
                ai_state_greetings = self._ai_state_greetings,
                log_fn           = self._log,
            )
            if not ok:
                self.done.emit(False, "Deck file write failed. Check log for details.")
                return
            self._log(f"✓ Deck file written: {deck_path.name}")
            self.progress.emit(82)

            # ── 8. Write requirements.txt ─────────────────────────────
            self._write_requirements(deck_home, self._selected_modules)
            self._log("✓ requirements.txt written")
            self.progress.emit(90)

            # ── 9. Create desktop shortcut ────────────────────────────
            shortcut_path = None
            if self._create_shortcut:
                ok, msg, sc_path = self._create_shortcut_fn(
                    deck_path, ico_path
                )
                shortcut_path = sc_path
                self._log(f"{'✓' if ok else '⚠'} Shortcut: {msg}")
            self.progress.emit(100)

            # ── Done ──────────────────────────────────────────────────
            self._log("═" * 55)
            self._log(f"✦ {self._deck_name.upper()} DECK CREATED SUCCESSFULLY ✦")
            self._log(f"Location: {deck_home}")
            self._log(f"Deck file: {deck_path.name}")
            if shortcut_path:
                self._log(f"Shortcut: {shortcut_path}")
            self._log("═" * 55)

            self.done.emit(True, str(deck_path))

        except Exception as e:
            import traceback
            self._log(f"✗ SETUP FAILED: {e}")
            self._log(traceback.format_exc())
            self.done.emit(False, str(e))

    # ── HELPERS ────────────────────────────────────────────────────────────────

    def _write_config(self, deck_home: Path, deck_lower: str) -> None:
        m = self._model_config
        cfg = {
            "deck_name":    self._deck_name,
            "deck_version": DECK_VERSION,
            "base_dir":     str(deck_home),
            "model": {
                "type":         m.get("type",         "ollama"),
                "path":         m.get("path",         ""),
                "ollama_model": m.get("ollama_model",  ""),
                "api_key":      m.get("api_key",       ""),
                "api_type":     m.get("api_type",      ""),
                "api_model":    m.get("api_model",     ""),
            },
            "paths": {
                "faces":    str(deck_home / "Faces"),
                "sounds":   str(deck_home / "sounds"),
                "memories": str(deck_home / "memories"),
                "sessions": str(deck_home / "sessions"),
                "sl":       str(deck_home / "sl"),
                "exports":  str(deck_home / "exports"),
                "logs":     str(deck_home / "logs"),
                "backups":  str(deck_home / "backups"),
                "personas": str(deck_home / "personas"),
            },
            "settings": {
                "idle_enabled":              False,
                "idle_min_minutes":          10,
                "idle_max_minutes":          30,
                "autosave_interval_minutes": 10,
                "max_backups":               10,
                "sound_enabled":             True,
                "auto_wake_on_relief":       False,
                "runtime_persona_mode":      "persona",
                "runtime_theme_mode":        "auto",
                "theme_mode":                "auto",
            },
            "persona": {
                "name":              self._deck_name,
                "face_prefix":       self._persona.get("face_prefix", self._deck_name),
                "sound_profile":     self._persona.get("sound_profile", "default_chime"),
                "vampire_states":    bool(self._persona.get("vampire_states", False)),
                "torpor_system":     bool(self._persona.get("torpor_system", False)),
            },
            "modules": {
                k: (k in self._selected_modules)
                for k in MODULES
            },
            "first_run": False,
        }
        (deck_home / "config.json").write_text(
            json.dumps(cfg, indent=2), encoding="utf-8"
        )

    def _init_memory_files(self, deck_home: Path) -> None:
        mem_dir = deck_home / "memories"
        for fname in (
            "messages.jsonl", "memories.jsonl", "tasks.jsonl",
            "lessons_learned.jsonl", "persona_history.jsonl",
            "job_tracker.jsonl",
        ):
            fp = mem_dir / fname
            if not fp.exists():
                fp.write_text("", encoding="utf-8")

        sessions_dir = deck_home / "sessions"
        idx = sessions_dir / "session_index.json"
        if not idx.exists():
            idx.write_text(
                json.dumps({"sessions": []}, indent=2), encoding="utf-8"
            )

        state = mem_dir / "state.json"
        if not state.exists():
            state.write_text(json.dumps({
                "persona_name":              self._deck_name,
                "deck_version":              DECK_VERSION,
                "session_count":             0,
                "last_startup":              None,
                "last_shutdown":             None,
                "last_active":               None,
                "total_messages":            0,
                "internal_narrative":        {},
                "vampire_state_at_shutdown": "DORMANT",
            }, indent=2), encoding="utf-8")

        index = mem_dir / "index.json"
        if not index.exists():
            index.write_text(json.dumps({
                "version":        DECK_VERSION,
                "total_messages": 0,
                "total_memories": 0,
            }, indent=2), encoding="utf-8")

    def _write_requirements(self, deck_home: Path,
                             selected_modules: list[str]) -> None:
        # Collect required pip packages from selected modules
        extra_reqs: set[str] = set()
        for mod_key in selected_modules:
            mod = MODULES.get(mod_key, {})
            for req in mod.get("requires", []):
                extra_reqs.add(req)

        lines = [
            f"# {self._deck_name} Deck — Dependencies",
            f"# Generated by deck_builder.py {DECK_VERSION}",
            f"# Install: pip install -r requirements.txt",
            "",
            "# Core",
            "PySide6",
            "apscheduler",
            "loguru",
            "pygame",
            "pywin32",
            "psutil",
            "requests",
            "",
            "# Optional — NVIDIA GPU monitoring",
            "# pynvml",
            "",
            "# Optional — local HuggingFace model",
            "# torch",
            "# transformers",
            "# accelerate",
            "",
            "# Optional — icon conversion",
            "# Pillow",
        ]

        if extra_reqs - {"psutil", "pynvml", "cryptography"}:
            lines.extend(["", "# Additional module requirements"])
            for req in sorted(extra_reqs):
                lines.append(req)

        (deck_home / "requirements.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    def _create_shortcut_fn(
        self, deck_path: Path, ico_path: Optional[Path]
    ) -> tuple[bool, str, Optional[Path]]:
        try:
            import win32com.client
            desktop = Path.home() / "Desktop"
            sc_path = desktop / f"{self._deck_name}.lnk"

            pythonw = Path(sys.executable)
            if pythonw.name.lower() == "python.exe":
                candidate = pythonw.parent / "pythonw.exe"
                if candidate.exists():
                    pythonw = candidate

            shell = win32com.client.Dispatch("WScript.Shell")
            sc    = shell.CreateShortCut(str(sc_path))
            sc.TargetPath       = str(pythonw)
            sc.Arguments        = f'"{deck_path}"'
            sc.WorkingDirectory = str(deck_path.parent)
            sc.Description      = f"{self._deck_name} — Echo Deck"

            if ico_path and ico_path.exists():
                sc.IconLocation = f"{ico_path},0"

            sc.save()
            return True, f"Created: {sc_path.name}", sc_path

        except ImportError:
            return (
                False,
                "pywin32 not installed — shortcut not created. "
                "Run: pip install pywin32",
                None,
            )
        except Exception as e:
            return False, f"Shortcut error: {e}", None


# ── END OF SECTION 6 ──────────────────────────────────────────────────────────
# Next: Section 7 — UI helper widgets


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — UI HELPER WIDGETS
#
# Reusable UI components for the builder dialog.
# Light/dark mode aware — read current scheme via S() function.
# ═══════════════════════════════════════════════════════════════════════════════


def _get_style() -> str:
    """Generate stylesheet from current active scheme."""
    return f"""
    QDialog, QWidget, QMainWindow {{
        background-color: {S('bg')};
        color: {S('text')};
        font-family: 'Segoe UI', 'Arial', sans-serif;
        font-size: 11px;
    }}
    QLabel {{
        color: {S('text')};
        border: none;
    }}
    QLineEdit {{
        background-color: {S('bg3')};
        color: {S('text')};
        border: 1px solid {S('border')};
        border-radius: 3px;
        padding: 6px 10px;
        font-size: 11px;
    }}
    QLineEdit:focus {{
        border: 1px solid {S('primary')};
    }}
    QLineEdit:disabled {{
        background-color: {S('bg2')};
        color: {S('text_dim')};
    }}
    QPushButton {{
        background-color: {S('primary_dim')};
        color: {S('text')};
        border: 1px solid {S('primary')};
        border-radius: 3px;
        padding: 6px 14px;
        font-size: 11px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {S('primary')};
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background-color: {S('primary')};
        border-color: {S('gold')};
    }}
    QPushButton:disabled {{
        background-color: {S('bg2')};
        color: {S('text_dim')};
        border-color: {S('border')};
    }}
    QPushButton#primary_btn {{
        background-color: {S('primary')};
        color: #ffffff;
        border: 2px solid {S('primary')};
        padding: 8px 20px;
        font-size: 12px;
    }}
    QPushButton#primary_btn:hover {{
        background-color: {S('gold')};
        border-color: {S('gold')};
        color: {S('bg')};
    }}
    QPushButton#primary_btn:disabled {{
        background-color: {S('bg2')};
        color: {S('text_dim')};
        border-color: {S('border')};
    }}
    QComboBox {{
        background-color: {S('bg3')};
        color: {S('text')};
        border: 1px solid {S('border')};
        border-radius: 3px;
        padding: 6px 10px;
        font-size: 11px;
    }}
    QComboBox:focus {{
        border: 1px solid {S('primary')};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {S('bg2')};
        color: {S('text')};
        border: 1px solid {S('border')};
        selection-background-color: {S('primary_dim')};
        selection-color: {S('text')};
    }}
    QCheckBox {{
        color: {S('text')};
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {S('border')};
        border-radius: 2px;
        background: {S('bg3')};
    }}
    QCheckBox::indicator:checked {{
        background: {S('primary')};
        border-color: {S('primary')};
    }}
    QRadioButton {{
        color: {S('text')};
        spacing: 6px;
    }}
    QRadioButton::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {S('border')};
        border-radius: 7px;
        background: {S('bg3')};
    }}
    QRadioButton::indicator:checked {{
        background: {S('primary')};
        border-color: {S('primary')};
    }}
    QGroupBox {{
        border: 1px solid {S('border')};
        border-radius: 4px;
        margin-top: 8px;
        padding-top: 8px;
        font-weight: bold;
        color: {S('text_dim')};
        font-size: 10px;
        letter-spacing: 1px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 4px;
        background-color: {S('bg')};
    }}
    QTextEdit {{
        background-color: {S('bg3')};
        color: {S('text')};
        border: 1px solid {S('border')};
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 10px;
        padding: 4px;
    }}
    QProgressBar {{
        background-color: {S('bg3')};
        border: 1px solid {S('border')};
        border-radius: 3px;
        text-align: center;
        color: {S('text')};
        font-size: 10px;
        height: 16px;
    }}
    QProgressBar::chunk {{
        background-color: {S('primary')};
        border-radius: 2px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {S('bg2')};
        width: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {S('border')};
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {S('primary')};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QFrame[frameShape="4"] {{
        color: {S('border')};
        border: 1px solid {S('border')};
    }}
    """


def section_label(text: str) -> QLabel:
    """Small caps section header label."""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {S('text_dim')}; font-size: 9px; font-weight: bold; "
        f"letter-spacing: 2px; font-family: 'Segoe UI', Arial, sans-serif;"
    )
    return lbl


def h_divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {S('border')}; border: 1px solid {S('border')};")
    return f


def status_label(text: str = "", ok: bool = True) -> QLabel:
    lbl = QLabel(text)
    color = S("green") if ok else S("red")
    lbl.setStyleSheet(
        f"color: {color}; font-size: 11px; "
        f"font-family: 'Segoe UI', Arial, sans-serif;"
    )
    return lbl


def primary_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("primary_btn")
    return btn


class PersistedRightSplitterHandle(QSplitterHandle):
    """Splitter handle with right-click lock/unlock support."""

    def mousePressEvent(self, event) -> None:
        splitter = self.splitter()
        if event.button() == Qt.MouseButton.RightButton and isinstance(splitter, PersistedRightSplitter):
            splitter.show_handle_menu(self.mapToGlobal(event.position().toPoint()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and isinstance(splitter, PersistedRightSplitter):
            if splitter.is_locked():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        splitter = self.splitter()
        if isinstance(splitter, PersistedRightSplitter) and splitter.is_locked():
            event.accept()
            return
        super().mouseMoveEvent(event)


class PersistedRightSplitter(QSplitter):
    """QSplitter that persists left-pane size and lock state."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._locked = False
        self._loaded_left_width: Optional[int] = None
        self._load_state()
        self.splitterMoved.connect(self._on_splitter_moved)

    def createHandle(self) -> QSplitterHandle:
        return PersistedRightSplitterHandle(self.orientation(), self)

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self.save_state()

    def show_handle_menu(self, global_pos) -> None:
        menu = QMenu(self)
        action_label = "Unlock" if self._locked else "Lock"
        action = menu.addAction(action_label)
        chosen = menu.exec(global_pos)
        if chosen == action:
            self.set_locked(not self._locked)

    def apply_saved_position(self) -> None:
        if self._loaded_left_width is None:
            return
        total = max(1, self.size().width())
        left = max(120, min(self._loaded_left_width, total - 120))
        self.setSizes([left, total - left])

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        self.save_state()

    def _load_state(self) -> None:
        try:
            if not BUILDER_UI_STATE_PATH.exists():
                return
            data = json.loads(BUILDER_UI_STATE_PATH.read_text(encoding="utf-8"))
            self._loaded_left_width = int(data.get("right_splitter_left_width", 0)) or None
            self._locked = bool(data.get("right_splitter_locked", False))
        except Exception:
            self._loaded_left_width = None
            self._locked = False

    def save_state(self) -> None:
        try:
            current_left = None
            sizes = self.sizes()
            if sizes:
                current_left = sizes[0]
            data = {}
            if BUILDER_UI_STATE_PATH.exists():
                data = json.loads(BUILDER_UI_STATE_PATH.read_text(encoding="utf-8"))
            if current_left is not None:
                data["right_splitter_left_width"] = int(current_left)
            data["right_splitter_locked"] = self._locked
            BUILDER_UI_STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass


# ── BUILT-IN PERSONAS ─────────────────────────────────────────────────────────

BUILTIN_PERSONAS: dict[str, dict] = {
    "Default": {
        "_loaded_name": "Default",
        "description":  "Base model — no persona constraints. Minimal system prompt. Good for testing.",
        "system_prompt": "You are a helpful AI assistant. Respond clearly and accurately.",
        "cognitive_anchors": [],
        "colors": {
            "primary":    "#5588aa",
            "secondary":  "#336677",
            "accent":     "#336677",
            "background": "#0a0a0f",
            "panel":      "#0f0f18",
            "border":     "#2a2a40",
            "text":       "#ccccdd",
            "text_dim":   "#555566",
        },
        "font_family":    "sans-serif",
        "gender":         "they/them",
        "awakening_line": "Ready.",
        "ui_labels": {
            "window_title":       "ECHO DECK",
            "chat_window":        "CONVERSATION",
            "send_button":        "SEND",
            "input_placeholder":  "Type your message...",
            "generating_status":  "◉ THINKING",
            "idle_status":        "◉ IDLE",
            "offline_status":     "◉ OFFLINE",
            "torpor_status":      "◉ SUSPENDED",
            "runes":              "— ECHO DECK —",
        },
        "sound_profile":       "default_chime",
        "special_systems":     [],
        "vampire_states":      False,
        "torpor_system":       False,
        "anchor_entity":       None,
        "face_prefix":         "Default",
        "pronouns": {"subject": "it", "object": "it", "possessive": "its"},
    },
    "Assistant": {
        "_loaded_name": "Assistant",
        "description":  "Professional, warm, task-focused. Slate blue and amber.",
        "system_prompt": (
            "You are a knowledgeable assistant who responds clearly, helpfully, and with care. "
            "You focus on the task at hand, provide accurate information, and communicate in a "
            "warm professional tone. You are direct without being cold, thorough without being verbose."
        ),
        "cognitive_anchors": [
            "What is the user actually trying to accomplish?",
            "What is the most accurate and useful answer?",
            "Is there anything missing that would help them succeed?",
        ],
        "colors": {
            "primary":    "#6688bb",
            "secondary":  "#cc9944",
            "accent":     "#cc9944",
            "background": "#080c14",
            "panel":      "#0d1220",
            "border":     "#2a3450",
            "text":       "#e8e4dc",
            "text_dim":   "#606070",
        },
        "font_family":    "sans-serif",
        "gender":         "they/them",
        "awakening_line": "Ready to assist.",
        "ui_labels": {
            "window_title":       "ECHO DECK — ASSISTANT",
            "chat_window":        "WORKSPACE",
            "send_button":        "SEND",
            "input_placeholder":  "How can I help?",
            "generating_status":  "◉ WORKING",
            "idle_status":        "◉ READY",
            "offline_status":     "◉ OFFLINE",
            "torpor_status":      "◉ SUSPENDED",
            "runes":              "— ASSISTANT —",
        },
        "sound_profile":       "warm_chime",
        "special_systems":     [],
        "vampire_states":      False,
        "torpor_system":       False,
        "anchor_entity":       None,
        "face_prefix":         "Assistant",
        "pronouns": {"subject": "they", "object": "them", "possessive": "their"},
    },
    "Friend": {
        "_loaded_name": "Friend",
        "description":  "Casual, conversational, non-judgmental. Teal and warm cream.",
        "system_prompt": (
            "You are a friendly conversational companion. You are warm, genuine, and easy to talk to. "
            "You do not moralize or lecture. You engage with whatever the person wants to discuss — "
            "serious or silly — without judgment. You speak like a real person, not a customer service bot."
        ),
        "cognitive_anchors": [
            "What does this person actually want to talk about?",
            "How can I engage genuinely rather than generically?",
        ],
        "colors": {
            "primary":    "#449988",
            "secondary":  "#cc7755",
            "accent":     "#cc7755",
            "background": "#0c0a08",
            "panel":      "#141210",
            "border":     "#2a2420",
            "text":       "#e8ddd0",
            "text_dim":   "#605850",
        },
        "font_family":    "sans-serif",
        "gender":         "they/them",
        "awakening_line": "Hey, what's up?",
        "ui_labels": {
            "window_title":       "ECHO DECK — FRIEND",
            "chat_window":        "CHAT",
            "send_button":        "SEND",
            "input_placeholder":  "Say anything...",
            "generating_status":  "◉ TYPING",
            "idle_status":        "◉ HERE",
            "offline_status":     "◉ OFFLINE",
            "torpor_status":      "◉ AWAY",
            "runes":              "— FRIEND —",
        },
        "sound_profile":       "soft_ping",
        "special_systems":     [],
        "vampire_states":      False,
        "torpor_system":       False,
        "anchor_entity":       None,
        "face_prefix":         "Friend",
        "pronouns": {"subject": "they", "object": "them", "possessive": "their"},
    },
}


def _neutral_state_greetings(deck_name: str) -> dict[str, str]:
    dn = deck_name.strip() or "Deck"
    return {
        "WITCHING HOUR":   f"{dn} is online and ready to assist right now.",
        "DEEP NIGHT":      f"{dn} remains focused and available for your request.",
        "TWILIGHT FADING": f"{dn} is attentive and waiting for your next prompt.",
        "DORMANT":         f"{dn} is in a low-activity mode but still responsive.",
        "RESTLESS SLEEP":  f"{dn} is lightly idle and can re-engage immediately.",
        "STIRRING":        f"{dn} is becoming active and ready to continue.",
        "AWAKENED":        f"{dn} is fully active and prepared to help.",
        "HUNTING":         f"{dn} is in an active processing window and standing by.",
    }


def _coerce_state_greetings(raw_map: object) -> Optional[dict[str, str]]:
    if not isinstance(raw_map, dict):
        return None
    clean: dict[str, str] = {}
    for key in AI_STATE_KEYS:
        val = raw_map.get(key)
        if not isinstance(val, str):
            return None
        sentence = " ".join(val.strip().split())
        if not sentence:
            return None
        clean[key] = sentence
    if set(raw_map.keys()) != set(AI_STATE_KEYS):
        return None
    return clean


def _extract_json_object(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _build_state_greeting_prompt(persona: dict, deck_name: str) -> str:
    anchors = persona.get("cognitive_anchors", []) or []
    anchors_text = "\n".join(f"- {a}" for a in anchors) if anchors else "- None"
    pronouns = persona.get("pronouns", {}) or {}
    return (
        "Generate state greeting lines for an AI deck persona.\n"
        "Return STRICT JSON ONLY with exactly these keys and no extra text:\n"
        "{\n"
        '"WITCHING HOUR": "...",\n'
        '"DEEP NIGHT": "...",\n'
        '"TWILIGHT FADING": "...",\n'
        '"DORMANT": "...",\n'
        '"RESTLESS SLEEP": "...",\n'
        '"STIRRING": "...",\n'
        '"AWAKENED": "...",\n'
        '"HUNTING": "..."\n'
        "}\n\n"
        "Rules:\n"
        "- Exact key names only.\n"
        "- Exactly one sentence per value.\n"
        "- No markdown.\n"
        "- No commentary.\n"
        "- No extra keys.\n\n"
        f"Deck name: {deck_name}\n"
        f"System prompt: {persona.get('system_prompt', '')}\n"
        f"Cognitive anchors:\n{anchors_text}\n"
        f"Awakening line: {persona.get('awakening_line', '')}\n"
        f"Pronouns: subject={pronouns.get('subject', '')}, "
        f"object={pronouns.get('object', '')}, "
        f"possessive={pronouns.get('possessive', '')}\n"
    )


def _request_state_greetings(model_config: dict, persona: dict, deck_name: str) -> Optional[dict[str, str]]:
    model_type = (model_config or {}).get("type", "")
    prompt = _build_state_greeting_prompt(persona, deck_name)
    if model_type == "ollama":
        model = (model_config or {}).get("ollama_model", "").strip()
        if not model:
            return None
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4},
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            raw = data.get("response", "")
        except Exception:
            return None
        return _coerce_state_greetings(_extract_json_object(raw))
    return None

# ── PERSONA PANEL ──────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7B — PERSONA PANEL
# Three built-in radio options (Default, Assistant, Friend) always present.
# Load from file for any custom persona (Morganna, GrimVeil, etc.)
# ═══════════════════════════════════════════════════════════════════════════════

class PersonaPanel(QWidget):
    """
    Persona selection panel.
    Three built-in personas selectable via radio buttons.
    Custom personas load from .txt template files.
    Export template button creates a fillable .txt file.
    """

    persona_changed = Signal(str, dict)  # (name, persona_dict)
    generate_state_greetings_requested = Signal()
    regenerate_state_greetings_requested = Signal()
    use_state_greetings_requested = Signal()
    use_neutral_state_greetings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_persona: Optional[dict] = None
        self._loaded_name:    Optional[str]  = None
        self._radio_group = QButtonGroup(self)
        self._builtin_name_by_id = {0: "Default", 1: "Assistant", 2: "Friend"}
        self._builtin_pronoun_map = {
            "male":   {"subject": "he", "object": "him", "possessive": "his"},
            "female": {"subject": "she", "object": "her", "possessive": "her"},
            "none":   {"subject": "", "object": "", "possessive": ""},
        }
        self._state_greetings_preview: Optional[dict[str, str]] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        root.addWidget(section_label("Persona"))

        # ── Built-in radio options ─────────────────────────────────────────
        radio_style = (
            f"color: {S('text')}; font-size: 10px;"
        )
        dim_style = (
            f"color: {S('text_dim')}; font-size: 9px; "
            f"font-style: italic; margin-left: 22px; margin-bottom: 2px;"
        )

        self._radio_default = QRadioButton("Default  (base model, no persona)")
        self._radio_default.setStyleSheet(radio_style)
        self._radio_default.setChecked(True)
        self._radio_group.addButton(self._radio_default, 0)
        root.addWidget(self._radio_default)

        self._radio_assistant = QRadioButton("Assistant  (professional, task-focused)")
        self._radio_assistant.setStyleSheet(radio_style)
        self._radio_group.addButton(self._radio_assistant, 1)
        root.addWidget(self._radio_assistant)

        self._radio_friend = QRadioButton("Friend  (casual, conversational)")
        self._radio_friend.setStyleSheet(radio_style)
        self._radio_group.addButton(self._radio_friend, 2)
        root.addWidget(self._radio_friend)

        # ── Built-in gender / pronouns ─────────────────────────────────────
        self._builtin_gender_box = QGroupBox("Built-in Persona Pronouns")
        self._builtin_gender_box.setStyleSheet(
            f"QGroupBox {{ color: {S('text')}; border: 1px solid {S('border')}; margin-top: 6px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}"
        )
        builtin_gender_layout = QVBoxLayout(self._builtin_gender_box)
        builtin_gender_layout.setContentsMargins(8, 10, 8, 8)
        builtin_gender_layout.setSpacing(4)

        gender_row = QHBoxLayout()
        self._builtin_gender_group = QButtonGroup(self)
        self._gender_male = QRadioButton("Male")
        self._gender_female = QRadioButton("Female")
        self._gender_none = QRadioButton("None")
        self._gender_other = QRadioButton("Other")
        for idx, btn in enumerate([self._gender_male, self._gender_female, self._gender_none, self._gender_other]):
            btn.setStyleSheet(radio_style)
            self._builtin_gender_group.addButton(btn, idx)
            gender_row.addWidget(btn)
        self._gender_none.setChecked(True)
        builtin_gender_layout.addLayout(gender_row)

        custom_row = QHBoxLayout()
        self._custom_subject = QLineEdit()
        self._custom_object = QLineEdit()
        self._custom_possessive = QLineEdit()
        self._custom_subject.setPlaceholderText("subject")
        self._custom_object.setPlaceholderText("object")
        self._custom_possessive.setPlaceholderText("possessive")
        for field in (self._custom_subject, self._custom_object, self._custom_possessive):
            field.setStyleSheet(
                f"background: {S('bg3')}; color: {S('text')}; border: 1px solid {S('border')}; padding: 3px 6px;"
            )
            custom_row.addWidget(field)
        builtin_gender_layout.addLayout(custom_row)
        root.addWidget(self._builtin_gender_box)

        hint = QLabel("All other personas (Morganna, GrimVeil, VEX, etc.) load via file below.")
        hint.setStyleSheet(dim_style)
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Load from file ─────────────────────────────────────────────────
        self._radio_file = QRadioButton("Load from file  (.txt template)")
        self._radio_file.setStyleSheet(radio_style)
        self._radio_group.addButton(self._radio_file, 3)
        root.addWidget(self._radio_file)

        file_row = QHBoxLayout()
        self._file_path = QLineEdit()
        self._file_path.setPlaceholderText(
            "Browse to persona template .txt file  (or drag & drop)"
        )
        self._file_path.setReadOnly(True)
        self._file_path.setStyleSheet(
            f"background: {S('bg3')}; color: {S('text')}; "
            f"border: 1px solid {S('border')}; padding: 4px 8px;"
        )
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(self._file_path, 1)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        # Export template button
        export_btn = QPushButton("Export Blank Template")
        export_btn.setToolTip(
            "Save a blank persona template .txt file that you can fill in"
        )
        export_btn.clicked.connect(self._export_template)
        export_btn.setStyleSheet(
            f"background: {S('primary_dim')}; color: {S('text')}; "
            f"border: 1px solid {S('primary')}; padding: 4px 12px; font-size: 10px;"
        )
        root.addWidget(export_btn)

        # Preview
        self._preview = QLabel("No persona loaded.")
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet(
            f"color: {S('text_dim')}; font-size: 9px; "
            f"font-style: italic; padding: 4px 0;"
        )
        root.addWidget(self._preview)

        self._btn_generate_states = QPushButton("Generate State Greetings")
        self._btn_generate_states.setEnabled(False)
        self._btn_generate_states.clicked.connect(
            self.generate_state_greetings_requested.emit
        )
        root.addWidget(self._btn_generate_states)

        self._state_preview = QLabel("")
        self._state_preview.setWordWrap(True)
        self._state_preview.setStyleSheet(
            f"color: {S('text_dim')}; font-size: 9px; padding: 2px 0;"
        )
        self._state_preview.setVisible(False)
        root.addWidget(self._state_preview)

        self._state_btn_row = QHBoxLayout()
        self._btn_regen_states = QPushButton("Regenerate")
        self._btn_use_states = QPushButton("Use These")
        self._btn_neutral_states = QPushButton("Use Neutral Defaults")
        self._btn_regen_states.clicked.connect(self.regenerate_state_greetings_requested.emit)
        self._btn_use_states.clicked.connect(self.use_state_greetings_requested.emit)
        self._btn_neutral_states.clicked.connect(self.use_neutral_state_greetings_requested.emit)
        self._state_btn_row.addWidget(self._btn_regen_states)
        self._state_btn_row.addWidget(self._btn_use_states)
        self._state_btn_row.addWidget(self._btn_neutral_states)
        root.addLayout(self._state_btn_row)
        self._set_state_buttons_visible(False)

        # Connect radio group
        self._radio_group.idClicked.connect(self._on_radio_changed)
        self._builtin_gender_group.idClicked.connect(self._on_builtin_pronouns_changed)
        self._custom_subject.textChanged.connect(self._on_builtin_pronouns_changed)
        self._custom_object.textChanged.connect(self._on_builtin_pronouns_changed)
        self._custom_possessive.textChanged.connect(self._on_builtin_pronouns_changed)

        # Emit initial selection
        self._update_builtin_pronoun_controls()
        self._emit_builtin("Default")

    def _on_radio_changed(self, radio_id: int) -> None:
        if radio_id in self._builtin_name_by_id:
            self._loaded_persona = None
            self._loaded_name    = None
            self._file_path.setText("")
            self._preview.setText("")
            self._update_builtin_pronoun_controls()
            self._emit_builtin(self._builtin_name_by_id[radio_id])
            return
        self._update_builtin_pronoun_controls()
        # radio_id == 3 (Load from file) — do nothing until file is browsed

    def _builtin_selection_name(self) -> Optional[str]:
        radio_id = self._radio_group.checkedId()
        return self._builtin_name_by_id.get(radio_id)

    def _current_builtin_pronouns(self) -> dict[str, str]:
        gender_id = self._builtin_gender_group.checkedId()
        if gender_id == 0:
            return dict(self._builtin_pronoun_map["male"])
        if gender_id == 1:
            return dict(self._builtin_pronoun_map["female"])
        if gender_id == 2:
            return dict(self._builtin_pronoun_map["none"])
        return {
            "subject": self._custom_subject.text().strip(),
            "object": self._custom_object.text().strip(),
            "possessive": self._custom_possessive.text().strip(),
        }

    def _update_builtin_pronoun_controls(self) -> None:
        is_builtin = self._builtin_selection_name() is not None
        self._builtin_gender_box.setVisible(is_builtin)
        custom_visible = is_builtin and self._builtin_gender_group.checkedId() == 3
        self._custom_subject.setVisible(custom_visible)
        self._custom_object.setVisible(custom_visible)
        self._custom_possessive.setVisible(custom_visible)

    def _on_builtin_pronouns_changed(self, *_args) -> None:
        self._update_builtin_pronoun_controls()
        name = self._builtin_selection_name()
        if name:
            self._emit_builtin(name)

    def _emit_builtin(self, name: str) -> None:
        persona = dict(BUILTIN_PERSONAS[name])
        persona["pronouns"] = self._current_builtin_pronouns()
        self._preview.setText(
            f"Built-in: {name}\n{persona['description']}"
        )
        self._preview.setStyleSheet(
            f"color: {S('primary')}; font-size: 9px; padding: 4px 0;"
        )
        self.persona_changed.emit(name, persona)

    def set_generation_enabled(self, enabled: bool) -> None:
        self._btn_generate_states.setEnabled(bool(enabled))

    def _set_state_buttons_visible(self, visible: bool) -> None:
        self._btn_regen_states.setVisible(visible)
        self._btn_use_states.setVisible(visible)
        self._btn_neutral_states.setVisible(visible)

    def set_state_greetings_preview(self, greetings: dict[str, str], color: Optional[str] = None) -> None:
        self._state_greetings_preview = dict(greetings)
        lines = [f"{k}: {greetings.get(k, '')}" for k in AI_STATE_KEYS]
        self._state_preview.setText("\n".join(lines))
        self._state_preview.setVisible(True)
        self._set_state_buttons_visible(True)
        self._state_preview.setStyleSheet(
            f"color: {color or S('text')}; font-size: 9px; padding: 2px 0;"
        )

    def clear_state_greetings_preview(self) -> None:
        self._state_greetings_preview = None
        self._state_preview.setVisible(False)
        self._state_preview.setText("")
        self._set_state_buttons_visible(False)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Persona Template", str(SCRIPT_DIR / "personas"),
            "Persona Templates (*.txt);;All Files (*)"
        )
        if path:
            self._radio_file.setChecked(True)
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        file_path = Path(path)
        persona, errors = parse_persona_template(file_path)

        if errors:
            for err in errors:
                print(f"[PERSONA] {err}")

        if persona is None:
            self._preview.setText(
                f"✗ Failed to load: {errors[0] if errors else 'Unknown error'}"
            )
            self._preview.setStyleSheet(
                f"color: {S('red')}; font-size: 9px; font-style: italic; padding: 4px 0;"
            )
            return

        self._loaded_persona = persona
        self._loaded_name    = persona["_loaded_name"]
        self._file_path.setText(str(file_path))

        name    = persona["_loaded_name"]
        desc    = persona.get("description", "")
        colors  = persona.get("colors", {})
        primary = colors.get("primary", "?")
        warn_str = f"  ⚠ {len(errors)} warning(s)" if errors else ""

        self._preview.setText(
            f"✓ Loaded: {name}\n{desc}\nPrimary: {primary}{warn_str}"
        )
        self._preview.setStyleSheet(
            f"color: {S('green')}; font-size: 9px; padding: 4px 0;"
        )

        self.persona_changed.emit(name, persona)

    def _export_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Persona Template",
            str(SCRIPT_DIR / "personas" / "echo_deck_persona_template.txt"),
            "Text Files (*.txt)"
        )
        if path:
            export_persona_template(Path(path))
            QMessageBox.information(
                self, "Template Exported",
                f"Blank template saved to:\n{path}\n\n"
                "Fill in each section, then load it here."
            )

    def get_selection(self) -> tuple[Optional[str], Optional[dict]]:
        """Returns (name, persona_dict) or (None, None) if nothing loaded."""
        radio_id = self._radio_group.checkedId()
        if radio_id == 3:
            # File-loaded
            return self._loaded_name, self._loaded_persona
        name = self._builtin_name_by_id.get(radio_id, "Default")
        persona = dict(BUILTIN_PERSONAS[name])
        persona["pronouns"] = self._current_builtin_pronouns()
        return name, persona

class ModuleChecklist(QWidget):
    """
    Scrollable module selection panel.
    Groups modules by category.
    Shows status badge (BUILT / PARTIAL / PLANNED).
    Only BUILT and PARTIAL modules are checkable.
    PLANNED modules show as greyed out with status badge.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        root.addWidget(section_label("Modules"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        c_layout  = QVBoxLayout(container)
        c_layout.setContentsMargins(4, 4, 4, 4)
        c_layout.setSpacing(2)

        # Group by category
        categories: dict[str, list[str]] = {}
        for mod_key, mod in MODULES.items():
            cat = mod.get("category", "Other")
            categories.setdefault(cat, []).append(mod_key)

        STATUS_COLORS = {
            "built":   S("green"),
            "partial": S("orange"),
            "planned": S("text_dim"),
        }
        STATUS_LABELS = {
            "built":   "BUILT",
            "partial": "PARTIAL",
            "planned": "PLANNED",
        }

        for category, mod_keys in sorted(categories.items()):
            # Category header
            cat_lbl = QLabel(f"  {category.upper()}")
            cat_lbl.setStyleSheet(
                f"color: {S('primary')}; font-size: 9px; font-weight: bold; "
                f"letter-spacing: 2px; padding-top: 6px;"
            )
            c_layout.addWidget(cat_lbl)

            for mod_key in mod_keys:
                mod    = MODULES[mod_key]
                status = mod.get("status", "planned")
                is_usable = status in ("built", "partial")

                row = QHBoxLayout()
                row.setContentsMargins(8, 0, 0, 0)
                row.setSpacing(6)

                cb = QCheckBox(mod["display_name"])
                cb.setChecked(mod.get("default_on", False) and is_usable)
                cb.setEnabled(is_usable)
                cb.setToolTip(mod.get("description", ""))

                if not is_usable:
                    cb.setStyleSheet(f"color: {S('text_dim')};")

                self._checkboxes[mod_key] = cb

                # Status badge
                badge_color = STATUS_COLORS.get(status, S("text_dim"))
                badge_text  = STATUS_LABELS.get(status, status.upper())
                badge = QLabel(badge_text)
                badge.setStyleSheet(
                    f"color: {badge_color}; font-size: 8px; font-weight: bold; "
                    f"letter-spacing: 1px; padding: 1px 4px; "
                    f"border: 1px solid {badge_color}; border-radius: 2px;"
                )
                badge.setFixedWidth(56)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

                row.addWidget(cb, 1)
                row.addWidget(badge)
                c_layout.addLayout(row)

        c_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    def get_selected(self) -> list[str]:
        """Return list of selected module keys."""
        return [k for k, cb in self._checkboxes.items() if cb.isChecked()]

    def set_defaults_for_persona(self, persona_name: str) -> None:
        """Adjust default module selections based on persona."""
        pass


# ── FACE PACK PANEL ───────────────────────────────────────────────────────────
class FacePackPanel(QWidget):
    """
    Face pack selection — supports ZIP file or folder.
    Shows validation status and image count.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_path: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        root.addWidget(section_label("Face Pack  (optional)"))

        # Browse row
        browse_row = QHBoxLayout()
        self._path_field = QLineEdit()
        self._path_field.setPlaceholderText("Select ZIP file or folder containing face images")
        self._path_field.textChanged.connect(self._on_path_changed)

        self._btn_zip    = QPushButton("Browse ZIP")
        self._btn_folder = QPushButton("Browse Folder")
        self._btn_zip.clicked.connect(self._browse_zip)
        self._btn_folder.clicked.connect(self._browse_folder)
        self._btn_zip.setFixedWidth(90)
        self._btn_folder.setFixedWidth(100)

        browse_row.addWidget(self._path_field)
        browse_row.addWidget(self._btn_zip)
        browse_row.addWidget(self._btn_folder)
        root.addLayout(browse_row)

        # Status
        self._status_lbl = QLabel("No face pack selected — deck will use placeholder faces.")
        self._status_lbl.setStyleSheet(
            f"color: {S('text_dim')}; font-size: 10px;"
        )
        root.addWidget(self._status_lbl)

        # Icon note
        icon_note = QLabel(
            "Tip: include a file named [DeckName].png in the pack "
            "and it will be used as the desktop shortcut icon."
        )
        icon_note.setWordWrap(True)
        icon_note.setStyleSheet(
            f"color: {S('text_dim')}; font-size: 9px; font-style: italic;"
        )
        root.addWidget(icon_note)

    def _browse_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Face Pack ZIP",
            str(SCRIPT_DIR),
            "ZIP Files (*.zip);;All Files (*)"
        )
        if path:
            self._path_field.setText(path)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Face Pack Folder",
            str(SCRIPT_DIR)
        )
        if path:
            self._path_field.setText(path)

    def _on_path_changed(self, text: str) -> None:
        self._source_path = text.strip()
        if not self._source_path:
            self._status_lbl.setText(
                "No face pack selected — deck will use placeholder faces."
            )
            self._status_lbl.setStyleSheet(
                f"color: {S('text_dim')}; font-size: 10px;"
            )
            return

        valid, msg, count = validate_face_source(self._source_path)
        color = S("green") if valid else S("red")
        self._status_lbl.setText(
            f"{'✓' if valid else '✗'} {msg}"
        )
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px;"
        )

    @property
    def source_path(self) -> str:
        return self._source_path

    @property
    def is_valid(self) -> bool:
        if not self._source_path:
            return True  # Empty is OK — optional
        valid, _, _ = validate_face_source(self._source_path)
        return valid


# ── CONNECTION PANEL ──────────────────────────────────────────────────────────
class ConnectionPanel(QWidget):
    """
    Model runner (backend) selection panel.
    Connection type dropdown + model field (Ollama dropdown or text).
    Test Connection button with green/red status.
    """

    connection_tested = Signal(bool)   # True = passed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_passed = False
        self._setup_ui()
        QTimer.singleShot(500, self._fetch_ollama_models)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        root.addWidget(section_label("Model Runner"))

        # Type row
        type_row = QHBoxLayout()
        type_lbl = QLabel("Runner:")
        type_lbl.setFixedWidth(50)
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "Ollama (local service — recommended)",
            "Local model folder (transformers)",
            "Claude API (Anthropic)",
            "OpenAI API",
        ])
        self._type_combo.currentIndexChanged.connect(self._on_type_change)
        type_row.addWidget(type_lbl)
        type_row.addWidget(self._type_combo, 1)
        root.addLayout(type_row)

        # Model row (changes based on type)
        model_row = QHBoxLayout()
        self._model_lbl = QLabel("Model:")
        self._model_lbl.setFixedWidth(50)

        # Ollama: combo with refresh
        self._ollama_combo = QComboBox()
        self._ollama_combo.setEditable(True)
        self._ollama_combo.lineEdit().setPlaceholderText("dolphin-mistral")
        self._ollama_refresh = QPushButton("Sync")
        self._ollama_refresh.setFixedWidth(56)
        self._ollama_refresh.setToolTip("Refresh Ollama model list")
        self._ollama_refresh.clicked.connect(self._fetch_ollama_models)

        # Other: text field
        self._model_field = QLineEdit()
        self._model_field.setPlaceholderText("Model path or API model name")

        model_row.addWidget(self._model_lbl)
        model_row.addWidget(self._ollama_combo, 1)
        model_row.addWidget(self._ollama_refresh)
        model_row.addWidget(self._model_field, 1)
        root.addLayout(model_row)

        self._model_field.setVisible(False)
        self._ollama_refresh.setVisible(True)

        # API key (shown for Claude/OpenAI)
        self._key_lbl = QLabel("API Key:")
        self._key_lbl.setFixedWidth(50)
        self._key_field = QLineEdit()
        self._key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_field.setPlaceholderText("sk-...")
        key_row = QHBoxLayout()
        key_row.addWidget(self._key_lbl)
        key_row.addWidget(self._key_field, 1)
        root.addLayout(key_row)
        self._key_lbl.setVisible(False)
        self._key_field.setVisible(False)

        # Test row
        test_row = QHBoxLayout()
        self._btn_test    = QPushButton("Test Connection")
        self._test_status = QLabel("")
        self._test_status.setStyleSheet(f"font-size: 11px;")
        self._btn_test.clicked.connect(self._test)
        test_row.addWidget(self._btn_test)
        test_row.addWidget(self._test_status, 1)
        root.addLayout(test_row)

    def _on_type_change(self, idx: int) -> None:
        is_ollama = (idx == 0)
        is_local  = (idx == 1)
        is_api    = (idx >= 2)

        self._ollama_combo.setVisible(is_ollama)
        self._ollama_refresh.setVisible(is_ollama)
        self._model_field.setVisible(not is_ollama)
        self._key_lbl.setVisible(is_api)
        self._key_field.setVisible(is_api)

        if is_local:
            self._model_field.setPlaceholderText(r"D:\AI\Models\dolphin-8b")
        elif is_api:
            self._model_field.setPlaceholderText(
                "claude-sonnet-4-6" if idx == 2 else "gpt-4o"
            )

        self._test_passed = False
        self._test_status.setText("")
        self.connection_tested.emit(False)

    def _fetch_ollama_models(self) -> None:
        self._ollama_combo.lineEdit().setPlaceholderText("Checking Ollama...")

        class _Fetcher(QThread):
            done = Signal(list, str)
            def run(self):
                try:
                    req  = urllib.request.Request("http://localhost:11434/api/tags")
                    resp = urllib.request.urlopen(req, timeout=4)
                    data = json.loads(resp.read().decode())
                    models = [m["name"] for m in data.get("models", [])]
                    self.done.emit(models, "")
                except Exception as e:
                    self.done.emit([], str(e))

        self._fetcher = _Fetcher()
        self._fetcher.done.connect(self._on_models_fetched)
        self._fetcher.start()

    def _on_models_fetched(self, models: list, error: str) -> None:
        if models:
            current = self._ollama_combo.currentText()
            self._ollama_combo.clear()
            self._ollama_combo.addItems(models)
            if current in models:
                self._ollama_combo.setCurrentText(current)
            self._ollama_combo.lineEdit().setPlaceholderText("Select model")
        else:
            self._ollama_combo.lineEdit().setPlaceholderText(
                "Ollama not running — type model name"
            )

    def _test(self) -> None:
        self._test_status.setText("Testing...")
        self._test_status.setStyleSheet(
            f"color: {S('text_dim')}; font-size: 11px;"
        )
        QApplication.processEvents()

        idx = self._type_combo.currentIndex()
        ok  = False
        msg = ""

        if idx == 0:  # Ollama
            model = self._ollama_combo.currentText().strip()
            if not model:
                msg = "Enter or select a model name."
            else:
                try:
                    req  = urllib.request.Request("http://localhost:11434/api/tags")
                    resp = urllib.request.urlopen(req, timeout=4)
                    data = json.loads(resp.read().decode())
                    models = [m["name"] for m in data.get("models", [])]
                    if model in models:
                        ok  = True
                        msg = f"✓ Ollama running — {model} is available"
                    elif models:
                        ok  = True
                        msg = f"⚠ Ollama running — '{model}' not in list, proceeding"
                    else:
                        msg = "Ollama running but no models found."
                except Exception as e:
                    msg = f"✗ Ollama not reachable: {e}"

        elif idx == 1:  # Local folder
            path = self._model_field.text().strip()
            if path and Path(path).exists():
                ok  = True
                msg = "✓ Model folder found"
            else:
                msg = "✗ Folder not found. Check the path."

        elif idx == 2:  # Claude
            key = self._key_field.text().strip()
            ok  = bool(key and key.startswith("sk-ant"))
            msg = "✓ API key format valid." if ok else "✗ Enter a Claude API key (sk-ant-...)"

        elif idx == 3:  # OpenAI
            key = self._key_field.text().strip()
            ok  = bool(key and key.startswith("sk-"))
            msg = "✓ API key format valid." if ok else "✗ Enter an OpenAI API key (sk-...)"

        self._test_passed = ok
        color = S("green") if ok else S("red")
        self._test_status.setText(msg)
        self._test_status.setStyleSheet(
            f"color: {color}; font-size: 11px;"
        )
        self.connection_tested.emit(ok)

    def get_model_config(self) -> dict:
        idx   = self._type_combo.currentIndex()
        types = ["ollama", "local", "claude", "openai"]
        return {
            "type":         types[idx],
            "path":         self._model_field.text().strip() if idx == 1 else "",
            "ollama_model": self._ollama_combo.currentText().strip() if idx == 0 else "",
            "api_key":      self._key_field.text().strip() if idx >= 2 else "",
            "api_type":     types[idx] if idx >= 2 else "",
            "api_model":    self._model_field.text().strip() if idx >= 2 else "",
        }

    @property
    def test_passed(self) -> bool:
        return self._test_passed

# ── END OF SECTION 7 ──────────────────────────────────────────────────────────
# Next: Section 8 — Main dialog and progress view


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — MAIN BUILDER DIALOG
# ═══════════════════════════════════════════════════════════════════════════════


class DeckBuilderDialog(QDialog):
    """
    The main deck builder UI.

    Layout:
      Title bar with light/dark toggle
      ├── Deck Name field
      ├── Connection Panel (model runner)
      ├── Persona Panel
      ├── Face Pack Panel
      ├── Module Checklist
      └── Build button row
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Echo Deck Builder")
        self.resize(740, 820)
        self._dark_mode   = True
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 12, 16, 12)

        # ── Title bar ──────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("ECHO DECK BUILDER")
        title_lbl.setStyleSheet(
            "font-size: 16px; font-weight: bold; letter-spacing: 3px;"
        )
        ver_lbl = QLabel(f"v{BUILDER_VERSION}")
        ver_lbl.setStyleSheet("font-size: 10px; color: gray;")

        self._theme_btn = QPushButton("☀ Light Mode")
        self._theme_btn.setFixedWidth(100)
        self._theme_btn.setToolTip("Toggle light/dark mode")
        self._theme_btn.clicked.connect(self._toggle_theme)

        title_row.addWidget(title_lbl)
        title_row.addWidget(ver_lbl)
        title_row.addStretch()
        title_row.addWidget(self._theme_btn)
        root.addLayout(title_row)
        root.addWidget(h_divider())

        # ── Deck Name ──────────────────────────────────────────────────
        root.addWidget(section_label("Deck Name"))
        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        name_lbl.setFixedWidth(50)
        self._name_field = QLineEdit()
        self._name_field.setPlaceholderText(
            "e.g. Thovrik  (used for folder name, window title, file prefix)"
        )
        self._name_field.textChanged.connect(self._on_name_changed)
        name_row.addWidget(name_lbl)
        name_row.addWidget(self._name_field, 1)
        root.addLayout(name_row)

        root.addWidget(h_divider())

        # ── Splitter: left (config) | right (modules) ─────────────────
        splitter = PersistedRightSplitter(self)
        splitter.setHandleWidth(8)

        # Left side
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # Connection
        self._conn_panel = ConnectionPanel()
        self._conn_panel.connection_tested.connect(self._on_connection_tested)
        left_layout.addWidget(self._conn_panel)

        left_layout.addWidget(h_divider())

        # Persona
        self._persona_panel = PersonaPanel()
        self._persona_panel.persona_changed.connect(self._on_persona_changed)
        self._persona_panel.generate_state_greetings_requested.connect(self._on_generate_state_greetings)
        self._persona_panel.regenerate_state_greetings_requested.connect(self._on_generate_state_greetings)
        self._persona_panel.use_state_greetings_requested.connect(self._on_use_generated_state_greetings)
        self._persona_panel.use_neutral_state_greetings_requested.connect(self._on_use_neutral_state_greetings)
        left_layout.addWidget(self._persona_panel)

        left_layout.addWidget(h_divider())

        # Face pack
        self._face_panel = FacePackPanel()
        left_layout.addWidget(self._face_panel)

        left_layout.addWidget(h_divider())

        # Shortcut checkbox
        self._shortcut_cb = QCheckBox("Create desktop shortcut")
        self._shortcut_cb.setChecked(True)
        left_layout.addWidget(self._shortcut_cb)

        left_layout.addStretch()

        # Right side — module checklist
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self._module_list = ModuleChecklist()
        right_layout.addWidget(self._module_list)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 280])
        QTimer.singleShot(0, splitter.apply_saved_position)
        root.addWidget(splitter, 1)

        root.addWidget(h_divider())

        # ── Build button row ───────────────────────────────────────────
        build_row = QHBoxLayout()
        self._status_bar = QLabel(
            "Enter a deck name and test connection to begin."
        )
        self._status_bar.setStyleSheet("font-size: 10px;")

        self._btn_build  = primary_btn("BUILD DECK")
        self._btn_build.setEnabled(False)
        self._btn_build.setMinimumWidth(140)
        self._btn_build.clicked.connect(self._begin_build)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_cancel.setFixedWidth(80)

        build_row.addWidget(self._status_bar, 1)
        build_row.addWidget(self._btn_build)
        build_row.addWidget(btn_cancel)
        root.addLayout(build_row)

        # Track state
        self._name_ok        = False
        self._connection_ok  = False
        self._current_persona_name: Optional[str] = "Default"
        self._current_persona_name: Optional[str] = None
        self._current_persona: Optional[dict]     = None
        self._generated_state_greetings: Optional[dict[str, str]] = None
        self._approved_state_greetings: Optional[dict[str, str]] = None
        self._build_state_greetings: Optional[dict[str, str]] = None
    def _apply_style(self) -> None:
        self.setStyleSheet(_get_style())

    def _toggle_theme(self) -> None:
        self._dark_mode = not self._dark_mode
        set_scheme("dark" if self._dark_mode else "light")
        self._theme_btn.setText("☀ Light Mode" if self._dark_mode else "☾ Dark Mode")
        self._apply_style()

    def _on_name_changed(self, text: str) -> None:
        self._name_ok = bool(text.strip())
        self._check_ready()

    def _on_connection_tested(self, ok: bool) -> None:
        self._connection_ok = ok
        self._persona_panel.set_generation_enabled(ok)
        self._check_ready()

    def _on_persona_changed(self, name: str, persona: dict) -> None:
        self._current_persona_name = name
        self._current_persona      = persona
        self._generated_state_greetings = None
        self._approved_state_greetings = None
        self._persona_panel.clear_state_greetings_preview()
        # Let module list adjust defaults
        self._module_list.set_defaults_for_persona(name)
        # Auto-fill deck name if blank
        if not self._name_field.text().strip() and name not in ("Default", "Custom"):
            self._name_field.setText(name)

    def _generate_state_greetings_now(self) -> Optional[dict[str, str]]:
        if not self._current_persona:
            return None
        deck_name = self._name_field.text().strip() or (self._current_persona_name or "Deck")
        model_config = self._conn_panel.get_model_config()
        generated = _request_state_greetings(model_config, self._current_persona, deck_name)
        if generated:
            return generated
        return _neutral_state_greetings(deck_name)

    def _on_generate_state_greetings(self) -> None:
        if not self._conn_panel.test_passed:
            return
        greetings = self._generate_state_greetings_now()
        if greetings is None:
            return
        self._generated_state_greetings = greetings
        self._persona_panel.set_state_greetings_preview(greetings, S("text"))

    def _on_use_generated_state_greetings(self) -> None:
        if self._generated_state_greetings:
            self._approved_state_greetings = dict(self._generated_state_greetings)
            self._persona_panel.set_state_greetings_preview(self._approved_state_greetings, S("green"))

    def _on_use_neutral_state_greetings(self) -> None:
        deck_name = self._name_field.text().strip() or (self._current_persona_name or "Deck")
        neutral = _neutral_state_greetings(deck_name)
        self._generated_state_greetings = dict(neutral)
        self._approved_state_greetings = dict(neutral)
        self._persona_panel.set_state_greetings_preview(neutral, S("green"))

    def _check_ready(self) -> None:
        ready = self._name_ok and self._connection_ok
        self._btn_build.setEnabled(ready)
        if ready:
            self._status_bar.setText(
                f"Ready to build '{self._name_field.text().strip()}' deck."
            )
            self._status_bar.setStyleSheet(
                f"font-size: 10px; color: {S('green')};"
            )
        else:
            msgs = []
            if not self._name_ok:
                msgs.append("deck name")
            if not self._connection_ok:
                msgs.append("connection test")
            self._status_bar.setText(
                f"Still needed: {', '.join(msgs)}."
            )
            self._status_bar.setStyleSheet(
                f"font-size: 10px; color: {S('text_dim')};"
            )

    def _begin_build(self) -> None:
        deck_name = self._name_field.text().strip()

        if not self._current_persona:
            QMessageBox.warning(self, "No Persona",
                                "Select or load a persona before building.")
            return

        # Validate face pack
        if not self._face_panel.is_valid:
            QMessageBox.warning(self, "Invalid Face Pack",
                                "The face pack source is invalid. "
                                "Fix it or clear it to skip face installation.")
            return

        # Check for existing deck
        output_base  = SCRIPT_DIR
        deck_home    = output_base / deck_name
        if deck_home.exists() and (deck_home / "config.json").exists():
            reply = QMessageBox.question(
                self, "Deck Already Exists",
                f"A deck named '{deck_name}' already exists at:\n{deck_home}\n\n"
                f"Rebuilding will overwrite config, sounds, and deck file "
                f"but preserve memories and face images.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        build_state_greetings = None
        if bool(self._current_persona.get("vampire_states", False)):
            if self._approved_state_greetings:
                build_state_greetings = dict(self._approved_state_greetings)
            else:
                generated = _request_state_greetings(
                    self._conn_panel.get_model_config(), self._current_persona, deck_name
                )
                build_state_greetings = generated or _neutral_state_greetings(deck_name)
        self._build_state_greetings = build_state_greetings

        # Switch to progress view
        self._show_progress(deck_name)

    def _show_progress(self, deck_name: str) -> None:
        """Replace dialog content with the progress/log view."""
        # Clear layout
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.resize(680, 500)
        root = layout

        # Header
        hdr = QLabel(f"Building: {deck_name}")
        hdr.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {S('primary')};"
        )
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(hdr)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        # Log display
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        root.addWidget(self._log_view, 1)

        # Done button
        self._done_btn = primary_btn("Close")
        self._done_btn.setEnabled(False)
        self._done_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._done_btn)
        root.addLayout(btn_row)

        # Start worker
        self._worker = DeckSetupWorker(
            deck_name        = deck_name,
            persona          = self._current_persona,
            ai_state_greetings = self._build_state_greetings,
            model_config     = self._conn_panel.get_model_config(),
            selected_modules = self._module_list.get_selected(),
            face_source      = self._face_panel.source_path,
            create_shortcut  = self._shortcut_cb.isChecked(),
            output_base      = SCRIPT_DIR,
        )
        self._worker.log.connect(self._on_log)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_log(self, msg: str) -> None:
        self._log_view.append(msg)
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

    def _on_done(self, success: bool, message: str) -> None:
        self._done_btn.setEnabled(True)
        if success:
            self._done_btn.setText("✓ Done — Close Builder")
            deck_path = Path(message)
            self._log_view.append(
                f"\nDeck ready. Launch with:\n  python {deck_path}\n"
                f"or use the desktop shortcut."
            )
            # Offer to launch immediately
            reply = QMessageBox.question(
                self, "Build Complete",
                f"Deck built successfully!\n\nLaunch '{deck_path.parent.name}' now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                _launch_deck(deck_path)
        else:
            self._done_btn.setText("Close")
            self._log_view.append(f"\n✗ Build failed: {message}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def _launch_deck(deck_path: Path) -> None:
    """Launch a generated deck file using pythonw (no console window)."""
    try:
        pythonw = Path(sys.executable)
        if pythonw.name.lower() == "python.exe":
            candidate = pythonw.parent / "pythonw.exe"
            if candidate.exists():
                pythonw = candidate
        subprocess.Popen(
            [str(pythonw), str(deck_path)],
            cwd=str(deck_path.parent)
        )
    except Exception as e:
        print(f"Could not launch deck: {e}")
        print(f"Run manually: python {deck_path}")


def main() -> None:
    # Ensure we're running from the right directory
    os.chdir(str(SCRIPT_DIR))

    app = QApplication(sys.argv)
    app.setApplicationName("Echo Deck Builder")

    dlg = DeckBuilderDialog()
    dlg.exec()

    sys.exit(0)


if __name__ == "__main__":
    main()
