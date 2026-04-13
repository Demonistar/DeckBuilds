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
            "<<<SYSTEM_PROMPT>>>":         persona.get("system_prompt", ""),
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
            "<<<DECK_PRONOUN_SUBJECT>>>":   persona.get("pronouns", {}).get("subject",    "they"),
            "<<<DECK_PRONOUN_OBJECT>>>":    persona.get("pronouns", {}).get("object",     "them"),
            "<<<DECK_PRONOUN_POSSESSIVE>>>": persona.get("pronouns", {}).get("possessive", "their"),
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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNITyBERUNLIOKAlCBVTklWRVJTQUwgSU1Q"
    "TEVNRU5UQVRJT04KIyBHZW5lcmF0ZWQgYnkgZGVja19idWlsZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGluamVjdGVk"
    "IGZyb20gREVDS19URU1QTEFURSBoZWFkZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZP"
    "VU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09VTkQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKCmltcG9ydCBzeXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCBt"
    "YXRoCmltcG9ydCB0aW1lCmltcG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5n"
    "CmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwg"
    "dGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHpvbmVpbmZvIGltcG9ydCBab25lSW5mbywgWm9uZUluZm9Ob3RGb3VuZEVycm9y"
    "CmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9tIHR5cGluZyBpbXBvcnQgT3B0aW9uYWwsIEl0ZXJhdG9yCgojIOKUgOKU"
    "gCBDb25zb2xlIGd1YXJkIOKAlCBzdXBwcmVzcyBDTUQgZmxhc2hlcyB3aGVuIGxhdW5jaGVkIHZpYSBweXRob253LmV4ZSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBweXRob253LmV4ZSBoYXMgbm8gY29uc29sZS4gc3Rkb3V0L3N0ZGVyciB3cml0"
    "ZXMgKGluY2x1ZGluZyBweWdhbWUgYmFubmVyKQojIGNhdXNlIFdpbmRvd3MgdG8gYnJpZWZseSBhbGxvY2F0ZSBhIENNRCB3"
    "aW5kb3cuIFJlZGlyZWN0IHRvIGRldm51bGwuCmltcG9ydCBvcyBhcyBfb3NfZ3VhcmQKdHJ5OgogICAgaWYgc3lzLmV4ZWN1"
    "dGFibGUgYW5kICJweXRob253IiBpbiBzeXMuZXhlY3V0YWJsZS5sb3dlcigpOgogICAgICAgIHN5cy5zdGRvdXQgPSBvcGVu"
    "KF9vc19ndWFyZC5kZXZudWxsLCAidyIpCiAgICAgICAgc3lzLnN0ZGVyciA9IG9wZW4oX29zX2d1YXJkLmRldm51bGwsICJ3"
    "IikKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHBhc3MKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCgojIOKUgOKUgCBFQVJMWSBDUkFTSCBM"
    "T0dHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgSG9va3MgaW4gYmVmb3JlIFF0LCBiZWZvcmUgZXZlcnl0aGluZy4gQ2Fw"
    "dHVyZXMgQUxMIG91dHB1dCBpbmNsdWRpbmcKIyBDKysgbGV2ZWwgUXQgbWVzc2FnZXMuIFdyaXR0ZW4gdG8gW0RlY2tOYW1l"
    "XS9sb2dzL3N0YXJ0dXAubG9nCiMgVGhpcyBzdGF5cyBhY3RpdmUgZm9yIHRoZSBsaWZlIG9mIHRoZSBwcm9jZXNzLgoKX0VB"
    "UkxZX0xPR19MSU5FUzogbGlzdCA9IFtdCl9FQVJMWV9MT0dfUEFUSDogT3B0aW9uYWxbUGF0aF0gPSBOb25lCgpkZWYgX2Vh"
    "cmx5X2xvZyhtc2c6IHN0cikgLT4gTm9uZToKICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTLiVm"
    "IilbOi0zXQogICAgbGluZSA9IGYiW3t0c31dIHttc2d9IgogICAgX0VBUkxZX0xPR19MSU5FUy5hcHBlbmQobGluZSkKICAg"
    "ICMgTm8gcHJpbnQoKSDigJQgcHl0aG9udy5leGUgaGFzIG5vIGNvbnNvbGU7IHByaW50aW5nIGNhdXNlcyBDTUQgZmxhc2gK"
    "ICAgIGlmIF9FQVJMWV9MT0dfUEFUSDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpdGggX0VBUkxZX0xPR19QQVRILm9w"
    "ZW4oImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgpkZWYgX2luaXRfZWFybHlfbG9nKGJhc2VfZGlyOiBQ"
    "YXRoKSAtPiBOb25lOgogICAgZ2xvYmFsIF9FQVJMWV9MT0dfUEFUSAogICAgbG9nX2RpciA9IGJhc2VfZGlyIC8gImxvZ3Mi"
    "CiAgICBsb2dfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIF9FQVJMWV9MT0dfUEFUSCA9IGxv"
    "Z19kaXIgLyBmInN0YXJ0dXBfe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9LmxvZyIKICAgICMg"
    "Rmx1c2ggYnVmZmVyZWQgbGluZXMKICAgIHdpdGggX0VBUkxZX0xPR19QQVRILm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgi"
    "KSBhcyBmOgogICAgICAgIGZvciBsaW5lIGluIF9FQVJMWV9MT0dfTElORVM6CiAgICAgICAgICAgIGYud3JpdGUobGluZSAr"
    "ICJcbiIpCgpkZWYgX2luc3RhbGxfcXRfbWVzc2FnZV9oYW5kbGVyKCkgLT4gTm9uZToKICAgICIiIgogICAgSW50ZXJjZXB0"
    "IEFMTCBRdCBtZXNzYWdlcyBpbmNsdWRpbmcgQysrIGxldmVsIHdhcm5pbmdzLgogICAgVGhpcyBjYXRjaGVzIHRoZSBRVGhy"
    "ZWFkIGRlc3Ryb3llZCBtZXNzYWdlIGF0IHRoZSBzb3VyY2UgYW5kIGxvZ3MgaXQKICAgIHdpdGggYSBmdWxsIHRyYWNlYmFj"
    "ayBzbyB3ZSBrbm93IGV4YWN0bHkgd2hpY2ggdGhyZWFkIGFuZCB3aGVyZS4KICAgICIiIgogICAgdHJ5OgogICAgICAgIGZy"
    "b20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IHFJbnN0YWxsTWVzc2FnZUhhbmRsZXIsIFF0TXNnVHlwZQogICAgICAgIGltcG9y"
    "dCB0cmFjZWJhY2sKCiAgICAgICAgZGVmIHF0X21lc3NhZ2VfaGFuZGxlcihtc2dfdHlwZSwgY29udGV4dCwgbWVzc2FnZSk6"
    "CiAgICAgICAgICAgIGxldmVsID0gewogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0RGVidWdNc2c6ICAgICJRVF9ERUJV"
    "RyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRJbmZvTXNnOiAgICAgIlFUX0lORk8iLAogICAgICAgICAgICAgICAg"
    "UXRNc2dUeXBlLlF0V2FybmluZ01zZzogICJRVF9XQVJOSU5HIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdENyaXRp"
    "Y2FsTXNnOiAiUVRfQ1JJVElDQUwiLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0RmF0YWxNc2c6ICAgICJRVF9GQVRB"
    "TCIsCiAgICAgICAgICAgIH0uZ2V0KG1zZ190eXBlLCAiUVRfVU5LTk9XTiIpCgogICAgICAgICAgICBsb2NhdGlvbiA9ICIi"
    "CiAgICAgICAgICAgIGlmIGNvbnRleHQuZmlsZToKICAgICAgICAgICAgICAgIGxvY2F0aW9uID0gZiIgW3tjb250ZXh0LmZp"
    "bGV9Ontjb250ZXh0LmxpbmV9XSIKCiAgICAgICAgICAgIF9lYXJseV9sb2coZiJbe2xldmVsfV17bG9jYXRpb259IHttZXNz"
    "YWdlfSIpCgogICAgICAgICAgICAjIEZvciBRVGhyZWFkIHdhcm5pbmdzIOKAlCBsb2cgZnVsbCBQeXRob24gc3RhY2sKICAg"
    "ICAgICAgICAgaWYgIlFUaHJlYWQiIGluIG1lc3NhZ2Ugb3IgInRocmVhZCIgaW4gbWVzc2FnZS5sb3dlcigpOgogICAgICAg"
    "ICAgICAgICAgc3RhY2sgPSAiIi5qb2luKHRyYWNlYmFjay5mb3JtYXRfc3RhY2soKSkKICAgICAgICAgICAgICAgIF9lYXJs"
    "eV9sb2coZiJbU1RBQ0sgQVQgUVRIUkVBRCBXQVJOSU5HXVxue3N0YWNrfSIpCgogICAgICAgIHFJbnN0YWxsTWVzc2FnZUhh"
    "bmRsZXIocXRfbWVzc2FnZV9oYW5kbGVyKQogICAgICAgIF9lYXJseV9sb2coIltJTklUXSBRdCBtZXNzYWdlIGhhbmRsZXIg"
    "aW5zdGFsbGVkIikKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICBfZWFybHlfbG9nKGYiW0lOSVRdIENvdWxk"
    "IG5vdCBpbnN0YWxsIFF0IG1lc3NhZ2UgaGFuZGxlcjoge2V9IikKCl9lYXJseV9sb2coZiJbSU5JVF0ge0RFQ0tfTkFNRX0g"
    "ZGVjayBzdGFydGluZyIpCl9lYXJseV9sb2coZiJbSU5JVF0gUHl0aG9uIHtzeXMudmVyc2lvbi5zcGxpdCgpWzBdfSBhdCB7"
    "c3lzLmV4ZWN1dGFibGV9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBXb3JraW5nIGRpcmVjdG9yeToge29zLmdldGN3ZCgpfSIp"
    "Cl9lYXJseV9sb2coZiJbSU5JVF0gU2NyaXB0IGxvY2F0aW9uOiB7UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpfSIpCgojIOKU"
    "gOKUgCBPUFRJT05BTCBERVBFTkRFTkNZIEdVQVJEUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKClBTVVRJTF9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCBwc3V0"
    "aWwKICAgIFBTVVRJTF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHBzdXRpbCBPSyIpCmV4Y2VwdCBJbXBv"
    "cnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHBzdXRpbCBGQUlMRUQ6IHtlfSIpCgpOVk1MX09LID0g"
    "RmFsc2UKZ3B1X2hhbmRsZSA9IE5vbmUKdHJ5OgogICAgaW1wb3J0IHdhcm5pbmdzCiAgICB3aXRoIHdhcm5pbmdzLmNhdGNo"
    "X3dhcm5pbmdzKCk6CiAgICAgICAgd2FybmluZ3Muc2ltcGxlZmlsdGVyKCJpZ25vcmUiKQogICAgICAgIGltcG9ydCBweW52"
    "bWwKICAgIHB5bnZtbC5udm1sSW5pdCgpCiAgICBjb3VudCA9IHB5bnZtbC5udm1sRGV2aWNlR2V0Q291bnQoKQogICAgaWYg"
    "Y291bnQgPiAwOgogICAgICAgIGdwdV9oYW5kbGUgPSBweW52bWwubnZtbERldmljZUdldEhhbmRsZUJ5SW5kZXgoMCkKICAg"
    "ICAgICBOVk1MX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHB5bnZtbCBPSyDigJQge2NvdW50fSBHUFUo"
    "cykiKQpleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIEZBSUxFRDoge2V9"
    "IikKClRPUkNIX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHRvcmNoCiAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQg"
    "QXV0b01vZGVsRm9yQ2F1c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgIFRPUkNIX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZyhm"
    "IltJTVBPUlRdIHRvcmNoIHt0b3JjaC5fX3ZlcnNpb25fX30gT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9l"
    "YXJseV9sb2coZiJbSU1QT1JUXSB0b3JjaCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKCldJTjMyX09LID0gRmFsc2UKdHJ5"
    "OgogICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudAogICAgV0lOMzJfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JU"
    "XSB3aW4zMmNvbSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHdpbjMy"
    "Y29tIEZBSUxFRDoge2V9IikKCldJTlNPVU5EX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHdpbnNvdW5kCiAgICBXSU5T"
    "T1VORF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHdpbnNvdW5kIE9LIikKZXhjZXB0IEltcG9ydEVycm9y"
    "IGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2luc291bmQgRkFJTEVEIChvcHRpb25hbCk6IHtlfSIpCgpQWUdB"
    "TUVfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgcHlnYW1lCiAgICBweWdhbWUubWl4ZXIuaW5pdCgpCiAgICBQWUdBTUVf"
    "T0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JUXSBweWdhbWUgT0siKQpleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHlnYW1lIEZBSUxFRDoge2V9IikKCgoKIyDilIDilIAgUHlTaWRlNiBJTVBPUlRT"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCAoCiAgICBR"
    "QXBwbGljYXRpb24sIFFNYWluV2luZG93LCBRV2lkZ2V0LCBRVkJveExheW91dCwgUUhCb3hMYXlvdXQsCiAgICBRR3JpZExh"
    "eW91dCwgUVRleHRFZGl0LCBRTGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRTGFiZWwsIFFGcmFtZSwKICAgIFFDYWxlbmRhcldp"
    "ZGdldCwgUVRhYmxlV2lkZ2V0LCBRVGFibGVXaWRnZXRJdGVtLCBRSGVhZGVyVmlldywKICAgIFFBYnN0cmFjdEl0ZW1WaWV3"
    "LCBRU3RhY2tlZFdpZGdldCwgUVRhYldpZGdldCwgUUxpc3RXaWRnZXQsCiAgICBRTGlzdFdpZGdldEl0ZW0sIFFTaXplUG9s"
    "aWN5LCBRQ29tYm9Cb3gsIFFDaGVja0JveCwgUUZpbGVEaWFsb2csCiAgICBRTWVzc2FnZUJveCwgUURhdGVFZGl0LCBRRGlh"
    "bG9nLCBRRm9ybUxheW91dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24s"
    "IFFTcGluQm94LCBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0LAogICAgUU1lbnUsIFFUYWJCYXIKKQpmcm9tIFB5U2lkZTYuUXRD"
    "b3JlIGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBRVGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVj"
    "dCwKICAgIFFQcm9wZXJ0eUFuaW1hdGlvbiwgUUVhc2luZ0N1cnZlCikKZnJvbSBQeVNpZGU2LlF0R3VpIGltcG9ydCAoCiAg"
    "ICBRRm9udCwgUUNvbG9yLCBRUGFpbnRlciwgUUxpbmVhckdyYWRpZW50LCBRUmFkaWFsR3JhZGllbnQsCiAgICBRUGl4bWFw"
    "LCBRUGVuLCBRUGFpbnRlclBhdGgsIFFUZXh0Q2hhckZvcm1hdCwgUUljb24sCiAgICBRVGV4dEN1cnNvciwgUUFjdGlvbgop"
    "CgojIOKUgOKUgCBBUFAgSURFTlRJVFkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACkFQUF9O"
    "QU1FICAgICAgPSBVSV9XSU5ET1dfVElUTEUKQVBQX1ZFUlNJT04gICA9ICIyLjAuMCIKQVBQX0ZJTEVOQU1FICA9IGYie0RF"
    "Q0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgpCVUlMRF9EQVRFICAgID0gIjIwMjYtMDQtMDQiCgojIOKUgOKUgCBDT05GSUcg"
    "TE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBjb25maWcuanNvbiBsaXZlcyBuZXh0"
    "IHRvIHRoZSBkZWNrIC5weSBmaWxlLgojIEFsbCBwYXRocyBjb21lIGZyb20gY29uZmlnLiBOb3RoaW5nIGhhcmRjb2RlZCBi"
    "ZWxvdyB0aGlzIHBvaW50LgoKU0NSSVBUX0RJUiA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKS5wYXJlbnQKQ09ORklHX1BB"
    "VEggPSBTQ1JJUFRfRElSIC8gImNvbmZpZy5qc29uIgoKIyBJbml0aWFsaXplIGVhcmx5IGxvZyBub3cgdGhhdCB3ZSBrbm93"
    "IHdoZXJlIHdlIGFyZQpfaW5pdF9lYXJseV9sb2coU0NSSVBUX0RJUikKX2Vhcmx5X2xvZyhmIltJTklUXSBTQ1JJUFRfRElS"
    "ID0ge1NDUklQVF9ESVJ9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBDT05GSUdfUEFUSCA9IHtDT05GSUdfUEFUSH0iKQpfZWFy"
    "bHlfbG9nKGYiW0lOSVRdIGNvbmZpZy5qc29uIGV4aXN0czoge0NPTkZJR19QQVRILmV4aXN0cygpfSIpCgpkZWYgX2RlZmF1"
    "bHRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIlJldHVybnMgdGhlIGRlZmF1bHQgY29uZmlnIHN0cnVjdHVyZSBmb3IgZmly"
    "c3QtcnVuIGdlbmVyYXRpb24uIiIiCiAgICBiYXNlID0gc3RyKFNDUklQVF9ESVIpCiAgICByZXR1cm4gewogICAgICAgICJk"
    "ZWNrX25hbWUiOiBERUNLX05BTUUsCiAgICAgICAgImRlY2tfdmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAgICAgICJiYXNl"
    "X2RpciI6IGJhc2UsCiAgICAgICAgIm1vZGVsIjogewogICAgICAgICAgICAidHlwZSI6ICJsb2NhbCIsICAgICAgICAgICMg"
    "bG9jYWwgfCBvbGxhbWEgfCBjbGF1ZGUgfCBvcGVuYWkKICAgICAgICAgICAgInBhdGgiOiAiIiwgICAgICAgICAgICAgICAj"
    "IGxvY2FsIG1vZGVsIGZvbGRlciBwYXRoCiAgICAgICAgICAgICJvbGxhbWFfbW9kZWwiOiAiIiwgICAgICAgIyBlLmcuICJk"
    "b2xwaGluLTIuNi03YiIKICAgICAgICAgICAgImFwaV9rZXkiOiAiIiwgICAgICAgICAgICAjIENsYXVkZSBvciBPcGVuQUkg"
    "a2V5CiAgICAgICAgICAgICJhcGlfdHlwZSI6ICIiLCAgICAgICAgICAgIyAiY2xhdWRlIiB8ICJvcGVuYWkiCiAgICAgICAg"
    "ICAgICJhcGlfbW9kZWwiOiAiIiwgICAgICAgICAgIyBlLmcuICJjbGF1ZGUtc29ubmV0LTQtNiIKICAgICAgICB9LAogICAg"
    "ICAgICJnb29nbGUiOiB7CiAgICAgICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAi"
    "dG9rZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwKICAgICAgICAgICAg"
    "InNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2"
    "ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAg"
    "ICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAg"
    "ICAgIH0sCiAgICAgICAgInBhdGhzIjogewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIoU0NSSVBUX0RJUiAvICJGYWNl"
    "cyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoU0NSSVBUX0RJUiAvICJzb3VuZHMiKSwKICAgICAgICAgICAgIm1l"
    "bW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAibWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25zIjogc3RyKFNDUklQ"
    "VF9ESVIgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAic2wiKSwKICAg"
    "ICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiZXhwb3J0cyIpLAogICAgICAgICAgICAibG9ncyI6ICAg"
    "ICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBzIjogIHN0cihTQ1JJUFRfRElSIC8gImJh"
    "Y2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKFNDUklQVF9ESVIgLyAicGVyc29uYXMiKSwKICAgICAgICAg"
    "ICAgImdvb2dsZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAgICAgICAgfSwKICAgICAgICAic2V0dGluZ3Mi"
    "OiB7CiAgICAgICAgICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJpZGxlX21p"
    "bl9taW51dGVzIjogICAgICAgICAgMTAsCiAgICAgICAgICAgICJpZGxlX21heF9taW51dGVzIjogICAgICAgICAgMzAsCiAg"
    "ICAgICAgICAgICJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAgICAgICAgICJtYXhfYmFja3VwcyI6ICAg"
    "ICAgICAgICAgICAgMTAsCiAgICAgICAgICAgICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAg"
    "ICAgImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiOiAzMDAwMDAsCiAgICAgICAgICAgICJnb29nbGVfbG9va2JhY2tfZGF5"
    "cyI6ICAgICAgMzAsCiAgICAgICAgICAgICJ1c2VyX2RlbGF5X3RocmVzaG9sZF9taW4iOiAgMzAsCiAgICAgICAgICAgICJ0"
    "aW1lem9uZV9hdXRvX2RldGVjdCI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgInRpbWV6b25lX292ZXJyaWRlIjogICAgICAg"
    "ICAiIiwKICAgICAgICAgICAgImZ1bGxzY3JlZW5fZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImJvcmRl"
    "cmxlc3NfZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICB9LAogICAgICAgICJtb2R1bGVfdGFiX29yZGVyIjogW10s"
    "CiAgICAgICAgIm1haW5fc3BsaXR0ZXIiOiB7CiAgICAgICAgICAgICJob3Jpem9udGFsX3NpemVzIjogWzkwMCwgNTAwXSwK"
    "ICAgICAgICB9LAogICAgICAgICJmaXJzdF9ydW4iOiBUcnVlLAogICAgfQoKZGVmIGxvYWRfY29uZmlnKCkgLT4gZGljdDoK"
    "ICAgICIiIkxvYWQgY29uZmlnLmpzb24uIFJldHVybnMgZGVmYXVsdCBpZiBtaXNzaW5nIG9yIGNvcnJ1cHQuIiIiCiAgICBp"
    "ZiBub3QgQ09ORklHX1BBVEguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygpCiAgICB0cnk6CiAg"
    "ICAgICAgd2l0aCBDT05GSUdfUEFUSC5vcGVuKCJyIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAgcmV0"
    "dXJuIGpzb24ubG9hZChmKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkK"
    "CmRlZiBzYXZlX2NvbmZpZyhjZmc6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJXcml0ZSBjb25maWcuanNvbi4iIiIKICAgIENP"
    "TkZJR19QQVRILnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIENPTkZJR19QQVRI"
    "Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGpzb24uZHVtcChjZmcsIGYsIGluZGVudD0yKQoK"
    "IyBMb2FkIGNvbmZpZyBhdCBtb2R1bGUgbGV2ZWwg4oCUIGV2ZXJ5dGhpbmcgYmVsb3cgcmVhZHMgZnJvbSBDRkcKQ0ZHID0g"
    "bG9hZF9jb25maWcoKQpfZWFybHlfbG9nKGYiW0lOSVRdIENvbmZpZyBsb2FkZWQg4oCUIGZpcnN0X3J1bj17Q0ZHLmdldCgn"
    "Zmlyc3RfcnVuJyl9LCBtb2RlbF90eXBlPXtDRkcuZ2V0KCdtb2RlbCcse30pLmdldCgndHlwZScpfSIpCgpfREVGQVVMVF9Q"
    "QVRIUzogZGljdFtzdHIsIFBhdGhdID0gewogICAgImZhY2VzIjogICAgU0NSSVBUX0RJUiAvICJGYWNlcyIsCiAgICAic291"
    "bmRzIjogICBTQ1JJUFRfRElSIC8gInNvdW5kcyIsCiAgICAibWVtb3JpZXMiOiBTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiwK"
    "ICAgICJzZXNzaW9ucyI6IFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiLAogICAgInNsIjogICAgICAgU0NSSVBUX0RJUiAvICJz"
    "bCIsCiAgICAiZXhwb3J0cyI6ICBTQ1JJUFRfRElSIC8gImV4cG9ydHMiLAogICAgImxvZ3MiOiAgICAgU0NSSVBUX0RJUiAv"
    "ICJsb2dzIiwKICAgICJiYWNrdXBzIjogIFNDUklQVF9ESVIgLyAiYmFja3VwcyIsCiAgICAicGVyc29uYXMiOiBTQ1JJUFRf"
    "RElSIC8gInBlcnNvbmFzIiwKICAgICJnb29nbGUiOiAgIFNDUklQVF9ESVIgLyAiZ29vZ2xlIiwKfQoKZGVmIF9ub3JtYWxp"
    "emVfY29uZmlnX3BhdGhzKCkgLT4gTm9uZToKICAgICIiIgogICAgU2VsZi1oZWFsIG9sZGVyIGNvbmZpZy5qc29uIGZpbGVz"
    "IG1pc3NpbmcgcmVxdWlyZWQgcGF0aCBrZXlzLgogICAgQWRkcyBtaXNzaW5nIHBhdGgga2V5cyBhbmQgbm9ybWFsaXplcyBn"
    "b29nbGUgY3JlZGVudGlhbC90b2tlbiBsb2NhdGlvbnMsCiAgICB0aGVuIHBlcnNpc3RzIGNvbmZpZy5qc29uIGlmIGFueXRo"
    "aW5nIGNoYW5nZWQuCiAgICAiIiIKICAgIGNoYW5nZWQgPSBGYWxzZQogICAgcGF0aHMgPSBDRkcuc2V0ZGVmYXVsdCgicGF0"
    "aHMiLCB7fSkKICAgIGZvciBrZXksIGRlZmF1bHRfcGF0aCBpbiBfREVGQVVMVF9QQVRIUy5pdGVtcygpOgogICAgICAgIGlm"
    "IG5vdCBwYXRocy5nZXQoa2V5KToKICAgICAgICAgICAgcGF0aHNba2V5XSA9IHN0cihkZWZhdWx0X3BhdGgpCiAgICAgICAg"
    "ICAgIGNoYW5nZWQgPSBUcnVlCgoKICAgIHNwbGl0dGVyX2NmZyA9IENGRy5zZXRkZWZhdWx0KCJtYWluX3NwbGl0dGVyIiwg"
    "e30pCiAgICBpZiBub3QgaXNpbnN0YW5jZShzcGxpdHRlcl9jZmcsIGRpY3QpOgogICAgICAgIENGR1sibWFpbl9zcGxpdHRl"
    "ciJdID0geyJob3Jpem9udGFsX3NpemVzIjogWzkwMCwgNTAwXX0KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgZWxzZToK"
    "ICAgICAgICBzaXplcyA9IHNwbGl0dGVyX2NmZy5nZXQoImhvcml6b250YWxfc2l6ZXMiKQogICAgICAgIHZhbGlkX3NpemVz"
    "ID0gKAogICAgICAgICAgICBpc2luc3RhbmNlKHNpemVzLCBsaXN0KQogICAgICAgICAgICBhbmQgbGVuKHNpemVzKSA9PSAy"
    "CiAgICAgICAgICAgIGFuZCBhbGwoaXNpbnN0YW5jZSh2LCBpbnQpIGZvciB2IGluIHNpemVzKQogICAgICAgICkKICAgICAg"
    "ICBpZiBub3QgdmFsaWRfc2l6ZXM6CiAgICAgICAgICAgIHNwbGl0dGVyX2NmZ1siaG9yaXpvbnRhbF9zaXplcyJdID0gWzkw"
    "MCwgNTAwXQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWco"
    "Q0ZHKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJv"
    "bSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2JqZWN0IHdpdGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAg"
    "IHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZhbHVlID0gcGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgog"
    "ICAgICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQoa2V5KQogICAgaWYg"
    "ZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAgICAgICByZXR1cm4gZmFsbGJhY2sKICAg"
    "IHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKUgOKUgCBDT0xPUiBDT05T"
    "VEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFSWSwgQ19TRUNPTkRBUlks"
    "IENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJlIGluamVjdGVkIGF0"
    "IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml2ZWQgZnJv"
    "bSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9ycyB0byBu"
    "YW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAgIyBt"
    "YWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4"
    "OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAg"
    "IyBtYWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4OCIgIyBk"
    "aW0gc2Vjb25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBlbXBoYXNpcywgaG92ZXIgc3RhdGVz"
    "CkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElNICAgICAgICAgIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkK"
    "Q19TSUxWRVJfRElNICA9IENfVEVYVF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0g"
    "Q19CRyAgICAgICAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkcyICAg"
    "ICAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyAgICAgICAgID0gQ19QQU5F"
    "TCAgICAgICAgICAgICMgdGVydGlhcnkvaW5wdXQgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAg"
    "ICA9ICcjOGIwMDAwJyAgICAgICAgICAjIGVycm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAg"
    "ICA9ICcjODg1NWNjJyAgICAgICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAn"
    "IzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjNDRhYTY2JyAg"
    "ICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5pdmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAg"
    "ICAgIyBpbmZvIHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZvbnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQg"
    "bmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNLX0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCku"
    "c3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChmb3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJ"
    "T05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAgInNtdWciOiAgICAg"
    "ICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZlZCI6ICAgQ19HT0xELAogICAgImhhcHB5"
    "IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5pY2tlZCI6ICAgQ19DUklNU09OLAog"
    "ICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04sCiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUi"
    "OiAgQ19DUklNU09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAgICAgICIjY2M2NjIyIiwK"
    "ICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAgICAicGxvdHRpbmci"
    "OiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZpb3VzIjogICAgQ19QVVJQTEUsCiAg"
    "ICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAg"
    "Q19URVhUX0RJTSwKfQoKIyDilIDilIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUlVORVMg"
    "aXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVO"
    "RVMKCiMgRmFjZSBpbWFnZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBw"
    "YXRocy5mYWNlcwpGQUNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVG"
    "SVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9j"
    "dXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklY"
    "fV9TbXVnLnBuZyIsCiAgICAiY29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQi"
    "OiAgICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1JlbGlldmVkLnBuZyIsCiAgICAiaW1wcmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAg"
    "ICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9Q"
    "UkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMucG5n"
    "IiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYi"
    "e0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAiYW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5w"
    "bmciLAogICAgInBsb3R0aW5nIjogICBmIntGQUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAg"
    "ZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0hhcHB5LnBu"
    "ZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHkucG5nIiwKICAgICJmbHVzdGVyZWQiOiAgZiJ7"
    "RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVudmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5w"
    "bmciLAp9CgpTRU5USU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmVk"
    "LCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNpb3VzLCBwYW5p"
    "Y2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksIGZsaXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3Vz"
    "IgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBpbmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9wIG9m"
    "IGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFs"
    "cmVhZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCByZWRlZmlu"
    "ZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxF"
    "ID0gZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6"
    "IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dy"
    "b3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsK"
    "ICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOiB7"
    "Q19DUklNU09OX0RJTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9y"
    "OiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4Owog"
    "ICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHgg"
    "MTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91"
    "bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hCdXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05f"
    "RElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVy"
    "LXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAg"
    "ICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAyMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0K"
    "UVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dP"
    "TERfQlJJR0hUfTsKfX0KUVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9Owog"
    "ICAgYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0dG9uOmRpc2FibGVk"
    "IHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlci1j"
    "b2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xsQmFyOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAg"
    "ICB3aWR0aDogNnB4OwogICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJh"
    "Y2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9sbEJhcjo6aGFuZGxl"
    "OnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6"
    "dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdl"
    "dDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0NfQkcy"
    "fTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsK"
    "ICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICAgZm9udC1m"
    "YW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9"
    "fQpRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7"
    "Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVy"
    "IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQg"
    "e3sKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9O"
    "VF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJh"
    "Y2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3Ojpz"
    "ZWN0aW9uIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlM"
    "WX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7"
    "Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJ"
    "X0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRlcjogbm9uZTsKfX0KUUNoZWNrQm94"
    "IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUxhYmVsIHt7"
    "CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBCT09U"
    "U1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBOb25lOgogICAgIiIi"
    "CiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxsZWQgb24g"
    "c3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxzbyBtaWdy"
    "YXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgogICAg"
    "ZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic291bmRzIiksCiAgICAgICAg"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAgY2ZnX3BhdGgoInNs"
    "IiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19w"
    "YXRoKCJiYWNrdXBzIiksCiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgog"
    "ICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05MIGZp"
    "bGVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZu"
    "YW1lIGluICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAgICAgICAg"
    "ICAgICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVt"
    "b3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIi"
    "LCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4gKCJzbF9z"
    "Y2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBp"
    "ZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAg"
    "c2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2lu"
    "ZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAgIGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJz"
    "ZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGly"
    "IC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9z"
    "dGF0ZShzdGF0ZV9wYXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3Qg"
    "aW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVt"
    "cHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICAp"
    "CgogICAgIyBMZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0"
    "ZSBmaWxlcwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRo"
    "KSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVj"
    "a192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0"
    "dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAog"
    "ICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJu"
    "YWxfbmFycmF0aXZlIjoge30sCiAgICAgICAgImFpX3N0YXRlX2F0X3NodXRkb3duIjogIkRPUk1BTlQiLAogICAgfQogICAg"
    "cGF0aC53cml0ZV90ZXh0KGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IikKCmRlZiBfbWln"
    "cmF0ZV9sZWdhY3lfZmlsZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBJZiBvbGQgRDpcXEFJXFxNb2RlbHNcXFtEZWNrTmFt"
    "ZV1fTWVtb3JpZXMgbGF5b3V0IGlzIGRldGVjdGVkLAogICAgbWlncmF0ZSBmaWxlcyB0byBuZXcgc3RydWN0dXJlIHNpbGVu"
    "dGx5LgogICAgIiIiCiAgICAjIFRyeSB0byBmaW5kIG9sZCBsYXlvdXQgcmVsYXRpdmUgdG8gbW9kZWwgcGF0aAogICAgbW9k"
    "ZWxfcGF0aCA9IFBhdGgoQ0ZHWyJtb2RlbCJdLmdldCgicGF0aCIsICIiKSkKICAgIGlmIG5vdCBtb2RlbF9wYXRoLmV4aXN0"
    "cygpOgogICAgICAgIHJldHVybgogICAgb2xkX3Jvb3QgPSBtb2RlbF9wYXRoLnBhcmVudCAvIGYie0RFQ0tfTkFNRX1fTWVt"
    "b3JpZXMiCiAgICBpZiBub3Qgb2xkX3Jvb3QuZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgbWlncmF0aW9ucyA9IFsK"
    "ICAgICAgICAob2xkX3Jvb3QgLyAibWVtb3JpZXMuanNvbmwiLCAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAi"
    "bWVtb3JpZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAibWVzc2FnZXMuanNvbmwiLCAgICAgICAgICAgIGNmZ19w"
    "YXRoKCJtZW1vcmllcyIpIC8gIm1lc3NhZ2VzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInRhc2tzLmpzb25sIiwg"
    "ICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAv"
    "ICJzdGF0ZS5qc29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAic3RhdGUuanNvbiIpLAogICAg"
    "ICAgIChvbGRfcm9vdCAvICJpbmRleC5qc29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiaW5k"
    "ZXguanNvbiIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9zY2Fucy5qc29ubCIsICAgICAgICAgICAgY2ZnX3BhdGgoInNs"
    "IikgLyAic2xfc2NhbnMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfY29tbWFuZHMuanNvbmwiLCAgICAgICAg"
    "IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNvdW5kcyIgLyBm"
    "IntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiKSwKICAgIF0KCiAgICBmb3Ig"
    "c3JjLCBkc3QgaW4gbWlncmF0aW9uczoKICAgICAgICBpZiBzcmMuZXhpc3RzKCkgYW5kIG5vdCBkc3QuZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGRzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1U"
    "cnVlKQogICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihzcmMp"
    "LCBzdHIoZHN0KSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIE1p"
    "Z3JhdGUgZmFjZSBpbWFnZXMKICAgIG9sZF9mYWNlcyA9IG9sZF9yb290IC8gIkZhY2VzIgogICAgbmV3X2ZhY2VzID0gY2Zn"
    "X3BhdGgoImZhY2VzIikKICAgIGlmIG9sZF9mYWNlcy5leGlzdHMoKToKICAgICAgICBmb3IgaW1nIGluIG9sZF9mYWNlcy5n"
    "bG9iKCIqLnBuZyIpOgogICAgICAgICAgICBkc3QgPSBuZXdfZmFjZXMgLyBpbWcubmFtZQogICAgICAgICAgICBpZiBub3Qg"
    "ZHN0LmV4aXN0cygpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAg"
    "ICAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIoc3RyKGltZyksIHN0cihkc3QpKQogICAgICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgojIOKUgOKUgCBEQVRFVElNRSBIRUxQRVJTIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbG9jYWxfbm93X2lzbygpIC0+IHN0cjoKICAgIHJldHVybiBkYXRldGltZS5u"
    "b3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApLmlzb2Zvcm1hdCgpCgpkZWYgcGFyc2VfaXNvKHZhbHVlOiBzdHIpIC0+IE9w"
    "dGlvbmFsW2RhdGV0aW1lXToKICAgIGlmIG5vdCB2YWx1ZToKICAgICAgICByZXR1cm4gTm9uZQogICAgdmFsdWUgPSB2YWx1"
    "ZS5zdHJpcCgpCiAgICB0cnk6CiAgICAgICAgaWYgdmFsdWUuZW5kc3dpdGgoIloiKToKICAgICAgICAgICAgcmV0dXJuIGRh"
    "dGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWVbOi0xXSkucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKQogICAgICAgIHJl"
    "dHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4g"
    "Tm9uZQoKX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOiBzZXRbdHVwbGVdID0gc2V0KCkKCgpkZWYgX3Jlc29sdmVf"
    "ZGVja190aW1lem9uZV9uYW1lKCkgLT4gT3B0aW9uYWxbc3RyXToKICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3Mi"
    "LCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgIGF1dG9fZGV0ZWN0ID0gYm9vbChzZXR0aW5ncy5n"
    "ZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICBvdmVycmlkZSA9IHN0cihzZXR0aW5ncy5nZXQoInRpbWV6"
    "b25lX292ZXJyaWRlIiwgIiIpIG9yICIiKS5zdHJpcCgpCiAgICBpZiBub3QgYXV0b19kZXRlY3QgYW5kIG92ZXJyaWRlOgog"
    "ICAgICAgIHJldHVybiBvdmVycmlkZQogICAgbG9jYWxfdHppbmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6"
    "aW5mbwogICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgIHR6X2tleSA9IGdldGF0dHIobG9jYWxfdHpp"
    "bmZvLCAia2V5IiwgTm9uZSkKICAgICAgICBpZiB0el9rZXk6CiAgICAgICAgICAgIHJldHVybiBzdHIodHpfa2V5KQogICAg"
    "ICAgIHR6X25hbWUgPSBzdHIobG9jYWxfdHppbmZvKQogICAgICAgIGlmIHR6X25hbWUgYW5kIHR6X25hbWUudXBwZXIoKSAh"
    "PSAiTE9DQUwiOgogICAgICAgICAgICByZXR1cm4gdHpfbmFtZQogICAgcmV0dXJuIE5vbmUKCgpkZWYgX2xvY2FsX3R6aW5m"
    "bygpOgogICAgdHpfbmFtZSA9IF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgpCiAgICBpZiB0el9uYW1lOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgcmV0dXJuIFpvbmVJbmZvKHR6X25hbWUpCiAgICAgICAgZXhjZXB0IFpvbmVJbmZvTm90Rm91"
    "bmRFcnJvcjoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltEQVRFVElNRV1bV0FSTl0gVW5rbm93biB0aW1lem9uZSBvdmVy"
    "cmlkZSAne3R6X25hbWV9JywgdXNpbmcgc3lzdGVtIGxvY2FsIHRpbWV6b25lLiIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgcGFzcwogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8gb3IgdGlt"
    "ZXpvbmUudXRjCgoKZGVmIG5vd19mb3JfY29tcGFyZSgpOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdyhfbG9jYWxfdHppbmZv"
    "KCkpCgoKZGVmIG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdF92YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgog"
    "ICAgaWYgZHRfdmFsdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gTm9uZQogICAgaWYgbm90IGlzaW5zdGFuY2UoZHRfdmFs"
    "dWUsIGRhdGV0aW1lKToKICAgICAgICByZXR1cm4gTm9uZQogICAgbG9jYWxfdHogPSBfbG9jYWxfdHppbmZvKCkKICAgIGlm"
    "IGR0X3ZhbHVlLnR6aW5mbyBpcyBOb25lOgogICAgICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5yZXBsYWNlKHR6aW5mbz1s"
    "b2NhbF90eikKICAgICAgICBrZXkgPSAoIm5haXZlIiwgY29udGV4dCkKICAgICAgICBpZiBrZXkgbm90IGluIF9EQVRFVElN"
    "RV9OT1JNQUxJWkFUSU9OX0xPR0dFRDoKICAgICAgICAgICAgX2Vhcmx5X2xvZygKICAgICAgICAgICAgICAgIGYiW0RBVEVU"
    "SU1FXVtJTkZPXSBOb3JtYWxpemVkIG5haXZlIGRhdGV0aW1lIHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAn"
    "Z2VuZXJhbCd9IGNvbXBhcmlzb25zLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElP"
    "Tl9MT0dHRUQuYWRkKGtleSkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAogICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLmFz"
    "dGltZXpvbmUobG9jYWxfdHopCiAgICBkdF90el9uYW1lID0gc3RyKGR0X3ZhbHVlLnR6aW5mbykKICAgIGtleSA9ICgiYXdh"
    "cmUiLCBjb250ZXh0LCBkdF90el9uYW1lKQogICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dH"
    "RUQgYW5kIGR0X3R6X25hbWUgbm90IGluIHsiVVRDIiwgc3RyKGxvY2FsX3R6KX06CiAgICAgICAgX2Vhcmx5X2xvZygKICAg"
    "ICAgICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZnJvbSB7ZHRf"
    "dHpfbmFtZX0gdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNvbnMuIgogICAg"
    "ICAgICkKICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQuYWRkKGtleSkKICAgIHJldHVybiBub3JtYWxp"
    "emVkCgoKZGVmIHBhcnNlX2lzb19mb3JfY29tcGFyZSh2YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgogICAgcmV0dXJuIG5v"
    "cm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZV9pc28odmFsdWUpLCBjb250ZXh0PWNvbnRleHQpCgoKZGVmIF90"
    "YXNrX2R1ZV9zb3J0X2tleSh0YXNrOiBkaWN0KToKICAgIGR1ZSA9IHBhcnNlX2lzb19mb3JfY29tcGFyZSgodGFzayBvciB7"
    "fSkuZ2V0KCJkdWVfYXQiKSBvciAodGFzayBvciB7fSkuZ2V0KCJkdWUiKSwgY29udGV4dD0idGFza19zb3J0IikKICAgIGlm"
    "IGR1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiAoMSwgZGF0ZXRpbWUubWF4LnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0"
    "YykpCiAgICByZXR1cm4gKDAsIGR1ZS5hc3RpbWV6b25lKHRpbWV6b25lLnV0YyksICgodGFzayBvciB7fSkuZ2V0KCJ0ZXh0"
    "Iikgb3IgIiIpLmxvd2VyKCkpCgoKZGVmIGZvcm1hdF9kdXJhdGlvbihzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgdG90"
    "YWwgPSBtYXgoMCwgaW50KHNlY29uZHMpKQogICAgZGF5cywgcmVtID0gZGl2bW9kKHRvdGFsLCA4NjQwMCkKICAgIGhvdXJz"
    "LCByZW0gPSBkaXZtb2QocmVtLCAzNjAwKQogICAgbWludXRlcywgc2VjcyA9IGRpdm1vZChyZW0sIDYwKQogICAgcGFydHMg"
    "PSBbXQogICAgaWYgZGF5czogICAgcGFydHMuYXBwZW5kKGYie2RheXN9ZCIpCiAgICBpZiBob3VyczogICBwYXJ0cy5hcHBl"
    "bmQoZiJ7aG91cnN9aCIpCiAgICBpZiBtaW51dGVzOiBwYXJ0cy5hcHBlbmQoZiJ7bWludXRlc31tIikKICAgIGlmIG5vdCBw"
    "YXJ0czogcGFydHMuYXBwZW5kKGYie3NlY3N9cyIpCiAgICByZXR1cm4gIiAiLmpvaW4ocGFydHNbOjNdKQoKIyDilIDilIAg"
    "TU9PTiBQSEFTRSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENvcnJlY3RlZCBpbGx1bWluYXRpb24gbWF0"
    "aCDigJQgZGlzcGxheWVkIG1vb24gbWF0Y2hlcyBsYWJlbGVkIHBoYXNlLgoKX0tOT1dOX05FV19NT09OID0gZGF0ZSgyMDAw"
    "LCAxLCA2KQpfTFVOQVJfQ1lDTEUgICAgPSAyOS41MzA1ODg2NwoKZGVmIGdldF9tb29uX3BoYXNlKCkgLT4gdHVwbGVbZmxv"
    "YXQsIHN0ciwgZmxvYXRdOgogICAgIiIiCiAgICBSZXR1cm5zIChwaGFzZV9mcmFjdGlvbiwgcGhhc2VfbmFtZSwgaWxsdW1p"
    "bmF0aW9uX3BjdCkuCiAgICBwaGFzZV9mcmFjdGlvbjogMC4wID0gbmV3IG1vb24sIDAuNSA9IGZ1bGwgbW9vbiwgMS4wID0g"
    "bmV3IG1vb24gYWdhaW4uCiAgICBpbGx1bWluYXRpb25fcGN0OiAw4oCTMTAwLCBjb3JyZWN0ZWQgdG8gbWF0Y2ggdmlzdWFs"
    "IHBoYXNlLgogICAgIiIiCiAgICBkYXlzICA9IChkYXRlLnRvZGF5KCkgLSBfS05PV05fTkVXX01PT04pLmRheXMKICAgIGN5"
    "Y2xlID0gZGF5cyAlIF9MVU5BUl9DWUNMRQogICAgcGhhc2UgPSBjeWNsZSAvIF9MVU5BUl9DWUNMRQoKICAgIGlmICAgY3lj"
    "bGUgPCAxLjg1OiAgIG5hbWUgPSAiTkVXIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgNy4zODogICBuYW1lID0gIldBWElORyBD"
    "UkVTQ0VOVCIKICAgIGVsaWYgY3ljbGUgPCA5LjIyOiAgIG5hbWUgPSAiRklSU1QgUVVBUlRFUiIKICAgIGVsaWYgY3ljbGUg"
    "PCAxNC43NzogIG5hbWUgPSAiV0FYSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwgMTYuNjE6ICBuYW1lID0gIkZVTEwg"
    "TU9PTiIKICAgIGVsaWYgY3ljbGUgPCAyMi4xNTogIG5hbWUgPSAiV0FOSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwg"
    "MjMuOTk6ICBuYW1lID0gIkxBU1QgUVVBUlRFUiIKICAgIGVsc2U6ICAgICAgICAgICAgICAgIG5hbWUgPSAiV0FOSU5HIENS"
    "RVNDRU5UIgoKICAgICMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbjogY29zLWJhc2VkLCBwZWFrcyBhdCBmdWxsIG1vb24KICAg"
    "IGlsbHVtaW5hdGlvbiA9ICgxIC0gbWF0aC5jb3MoMiAqIG1hdGgucGkgKiBwaGFzZSkpIC8gMiAqIDEwMAogICAgcmV0dXJu"
    "IHBoYXNlLCBuYW1lLCByb3VuZChpbGx1bWluYXRpb24sIDEpCgpfU1VOX0NBQ0hFX0RBVEU6IE9wdGlvbmFsW2RhdGVdID0g"
    "Tm9uZQpfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU46IE9wdGlvbmFsW2ludF0gPSBOb25lCl9TVU5fQ0FDSEVfVElNRVM6IHR1"
    "cGxlW3N0ciwgc3RyXSA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKZGVmIF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkgLT4g"
    "dHVwbGVbZmxvYXQsIGZsb2F0XToKICAgICIiIgogICAgUmVzb2x2ZSBsYXRpdHVkZS9sb25naXR1ZGUgZnJvbSBydW50aW1l"
    "IGNvbmZpZyB3aGVuIGF2YWlsYWJsZS4KICAgIEZhbGxzIGJhY2sgdG8gdGltZXpvbmUtZGVyaXZlZCBjb2Fyc2UgZGVmYXVs"
    "dHMuCiAgICAiIiIKICAgIGxhdCA9IE5vbmUKICAgIGxvbiA9IE5vbmUKICAgIHRyeToKICAgICAgICBzZXR0aW5ncyA9IENG"
    "Ry5nZXQoInNldHRpbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAgZm9yIGtleSBp"
    "biAoImxhdGl0dWRlIiwgImxhdCIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAgICAgICBs"
    "YXQgPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICBmb3Iga2V5IGluICgibG9u"
    "Z2l0dWRlIiwgImxvbiIsICJsbmciKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAg"
    "bG9uID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgIGxhdCA9IE5vbmUKICAgICAgICBsb24gPSBOb25lCgogICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0"
    "aW1lem9uZSgpCiAgICB0el9vZmZzZXQgPSBub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApCiAgICB0el9v"
    "ZmZzZXRfaG91cnMgPSB0el9vZmZzZXQudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCgogICAgaWYgbG9uIGlzIE5vbmU6CiAg"
    "ICAgICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCB0el9vZmZzZXRfaG91cnMgKiAxNS4wKSkKCiAgICBpZiBsYXQg"
    "aXMgTm9uZToKICAgICAgICB0el9uYW1lID0gc3RyKG5vd19sb2NhbC50emluZm8gb3IgIiIpCiAgICAgICAgc291dGhfaGlu"
    "dCA9IGFueSh0b2tlbiBpbiB0el9uYW1lIGZvciB0b2tlbiBpbiAoIkF1c3RyYWxpYSIsICJQYWNpZmljL0F1Y2tsYW5kIiwg"
    "IkFtZXJpY2EvU2FudGlhZ28iKSkKICAgICAgICBsYXQgPSAtMzUuMCBpZiBzb3V0aF9oaW50IGVsc2UgMzUuMAoKICAgIGxh"
    "dCA9IG1heCgtNjYuMCwgbWluKDY2LjAsIGxhdCkpCiAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIGxvbikpCiAg"
    "ICByZXR1cm4gbGF0LCBsb24KCmRlZiBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKGxvY2FsX2RheTogZGF0ZSwgbGF0aXR1"
    "ZGU6IGZsb2F0LCBsb25naXR1ZGU6IGZsb2F0LCBzdW5yaXNlOiBib29sKSAtPiBPcHRpb25hbFtmbG9hdF06CiAgICAiIiJO"
    "T0FBLXN0eWxlIHN1bnJpc2Uvc3Vuc2V0IHNvbHZlci4gUmV0dXJucyBsb2NhbCBtaW51dGVzIGZyb20gbWlkbmlnaHQuIiIi"
    "CiAgICBuID0gbG9jYWxfZGF5LnRpbWV0dXBsZSgpLnRtX3lkYXkKICAgIGxuZ19ob3VyID0gbG9uZ2l0dWRlIC8gMTUuMAog"
    "ICAgdCA9IG4gKyAoKDYgLSBsbmdfaG91cikgLyAyNC4wKSBpZiBzdW5yaXNlIGVsc2UgbiArICgoMTggLSBsbmdfaG91cikg"
    "LyAyNC4wKQoKICAgIE0gPSAoMC45ODU2ICogdCkgLSAzLjI4OQogICAgTCA9IE0gKyAoMS45MTYgKiBtYXRoLnNpbihtYXRo"
    "LnJhZGlhbnMoTSkpKSArICgwLjAyMCAqIG1hdGguc2luKG1hdGgucmFkaWFucygyICogTSkpKSArIDI4Mi42MzQKICAgIEwg"
    "PSBMICUgMzYwLjAKCiAgICBSQSA9IG1hdGguZGVncmVlcyhtYXRoLmF0YW4oMC45MTc2NCAqIG1hdGgudGFuKG1hdGgucmFk"
    "aWFucyhMKSkpKQogICAgUkEgPSBSQSAlIDM2MC4wCiAgICBMX3F1YWRyYW50ID0gKG1hdGguZmxvb3IoTCAvIDkwLjApKSAq"
    "IDkwLjAKICAgIFJBX3F1YWRyYW50ID0gKG1hdGguZmxvb3IoUkEgLyA5MC4wKSkgKiA5MC4wCiAgICBSQSA9IChSQSArIChM"
    "X3F1YWRyYW50IC0gUkFfcXVhZHJhbnQpKSAvIDE1LjAKCiAgICBzaW5fZGVjID0gMC4zOTc4MiAqIG1hdGguc2luKG1hdGgu"
    "cmFkaWFucyhMKSkKICAgIGNvc19kZWMgPSBtYXRoLmNvcyhtYXRoLmFzaW4oc2luX2RlYykpCgogICAgemVuaXRoID0gOTAu"
    "ODMzCiAgICBjb3NfaCA9IChtYXRoLmNvcyhtYXRoLnJhZGlhbnMoemVuaXRoKSkgLSAoc2luX2RlYyAqIG1hdGguc2luKG1h"
    "dGgucmFkaWFucyhsYXRpdHVkZSkpKSkgLyAoY29zX2RlYyAqIG1hdGguY29zKG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKQog"
    "ICAgaWYgY29zX2ggPCAtMS4wIG9yIGNvc19oID4gMS4wOgogICAgICAgIHJldHVybiBOb25lCgogICAgaWYgc3VucmlzZToK"
    "ICAgICAgICBIID0gMzYwLjAgLSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkKICAgIGVsc2U6CiAgICAgICAgSCA9"
    "IG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAgSCAvPSAxNS4wCgogICAgVCA9IEggKyBSQSAtICgwLjA2NTcx"
    "ICogdCkgLSA2LjYyMgogICAgVVQgPSAoVCAtIGxuZ19ob3VyKSAlIDI0LjAKCiAgICBsb2NhbF9vZmZzZXRfaG91cnMgPSAo"
    "ZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygp"
    "IC8gMzYwMC4wCiAgICBsb2NhbF9ob3VyID0gKFVUICsgbG9jYWxfb2Zmc2V0X2hvdXJzKSAlIDI0LjAKICAgIHJldHVybiBs"
    "b2NhbF9ob3VyICogNjAuMAoKZGVmIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShtaW51dGVzX2Zyb21fbWlkbmlnaHQ6IE9w"
    "dGlvbmFsW2Zsb2F0XSkgLT4gc3RyOgogICAgaWYgbWludXRlc19mcm9tX21pZG5pZ2h0IGlzIE5vbmU6CiAgICAgICAgcmV0"
    "dXJuICItLTotLSIKICAgIG1pbnMgPSBpbnQocm91bmQobWludXRlc19mcm9tX21pZG5pZ2h0KSkgJSAoMjQgKiA2MCkKICAg"
    "IGhoLCBtbSA9IGRpdm1vZChtaW5zLCA2MCkKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5yZXBsYWNlKGhvdXI9aGgsIG1p"
    "bnV0ZT1tbSwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApLnN0cmZ0aW1lKCIlSDolTSIpCgpkZWYgZ2V0X3N1bl90aW1lcygp"
    "IC0+IHR1cGxlW3N0ciwgc3RyXToKICAgICIiIgogICAgQ29tcHV0ZSBsb2NhbCBzdW5yaXNlL3N1bnNldCB1c2luZyBzeXN0"
    "ZW0gZGF0ZSArIHRpbWV6b25lIGFuZCBvcHRpb25hbAogICAgcnVudGltZSBsYXRpdHVkZS9sb25naXR1ZGUgaGludHMgd2hl"
    "biBhdmFpbGFibGUuCiAgICBDYWNoZWQgcGVyIGxvY2FsIGRhdGUgYW5kIHRpbWV6b25lIG9mZnNldC4KICAgICIiIgogICAg"
    "Z2xvYmFsIF9TVU5fQ0FDSEVfREFURSwgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOLCBfU1VOX0NBQ0hFX1RJTUVTCgogICAg"
    "bm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0b2RheSA9IG5vd19sb2NhbC5kYXRlKCkKICAg"
    "IHR6X29mZnNldF9taW4gPSBpbnQoKG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29u"
    "ZHMoKSAvLyA2MCkKCiAgICBpZiBfU1VOX0NBQ0hFX0RBVEUgPT0gdG9kYXkgYW5kIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01J"
    "TiA9PSB0el9vZmZzZXRfbWluOgogICAgICAgIHJldHVybiBfU1VOX0NBQ0hFX1RJTUVTCgogICAgdHJ5OgogICAgICAgIGxh"
    "dCwgbG9uID0gX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKQogICAgICAgIHN1bnJpc2VfbWluID0gX2NhbGNfc29sYXJf"
    "ZXZlbnRfbWludXRlcyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9VHJ1ZSkKICAgICAgICBzdW5zZXRfbWluID0gX2NhbGNf"
    "c29sYXJfZXZlbnRfbWludXRlcyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9RmFsc2UpCiAgICAgICAgaWYgc3VucmlzZV9t"
    "aW4gaXMgTm9uZSBvciBzdW5zZXRfbWluIGlzIE5vbmU6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlNvbGFyIGV2"
    "ZW50IHVuYXZhaWxhYmxlIGZvciByZXNvbHZlZCBjb29yZGluYXRlcyIpCiAgICAgICAgdGltZXMgPSAoX2Zvcm1hdF9sb2Nh"
    "bF9zb2xhcl90aW1lKHN1bnJpc2VfbWluKSwgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKHN1bnNldF9taW4pKQogICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICB0aW1lcyA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKICAgIF9TVU5fQ0FDSEVfREFURSA9"
    "IHRvZGF5CiAgICBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPSB0el9vZmZzZXRfbWluCiAgICBfU1VOX0NBQ0hFX1RJTUVT"
    "ID0gdGltZXMKICAgIHJldHVybiB0aW1lcwoKIyDilIDilIAgVkFNUElSRSBTVEFURSBTWVNURU0g4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgVGltZS1vZi1kYXkgYmVoYXZpb3JhbCBzdGF0ZS4gQWN0aXZlIG9ubHkgd2hlbiBBSV9TVEFURVNfRU5BQkxFRD1U"
    "cnVlLgojIEluamVjdGVkIGludG8gc3lzdGVtIHByb21wdCBvbiBldmVyeSBnZW5lcmF0aW9uIGNhbGwuCgpBSV9TVEFURVM6"
    "IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElORyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29s"
    "b3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIs"
    "M30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lMSUdIVCBGQURJTkci"
    "OnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJE"
    "T1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2Vy"
    "IjogMC4yfSwKICAgICJSRVNUTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhU"
    "X0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7MTYsMTd9LCAgICAgICAg"
    "ImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5FRCI6ICAgICAgIHsiaG91cnMiOiB7"
    "MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAg"
    "ICAgIHsiaG91cnMiOiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwKfQoK"
    "ZGVmIGdldF9haV9zdGF0ZSgpIC0+IHN0cjoKICAgICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRlIG5hbWUg"
    "YmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5ob3VyCiAgICBmb3Igc3RhdGVfbmFtZSwg"
    "ZGF0YSBpbiBBSV9TVEFURVMuaXRlbXMoKToKICAgICAgICBpZiBoIGluIGRhdGFbImhvdXJzIl06CiAgICAgICAgICAgIHJl"
    "dHVybiBzdGF0ZV9uYW1lCiAgICByZXR1cm4gIkRPUk1BTlQiCgpkZWYgZ2V0X2FpX3N0YXRlX2NvbG9yKHN0YXRlOiBzdHIp"
    "IC0+IHN0cjoKICAgIHJldHVybiBBSV9TVEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBf"
    "bmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENI"
    "SU5HIEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIsCiAg"
    "ICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1c2VkIGFuZCBhdmFpbGFibGUgZm9y"
    "IHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJTkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBh"
    "bmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05B"
    "TUV9IGlzIGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1Mg"
    "U0xFRVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwK"
    "ICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWluZyBhY3RpdmUgYW5kIHJlYWR5IHRv"
    "IGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0aXZlIGFu"
    "ZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYW4g"
    "YWN0aXZlIHByb2Nlc3Npbmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3RhdGVfZ3JlZXRpbmdz"
    "X21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJBSV9TVEFURV9HUkVFVElO"
    "R1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92aWRlZC5rZXlzKCkpID09IHNldChB"
    "SV9TVEFURVMua2V5cygpKToKICAgICAgICBjbGVhbjogZGljdFtzdHIsIHN0cl0gPSB7fQogICAgICAgIGZvciBrZXkgaW4g"
    "QUlfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90"
    "IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJh"
    "bF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaXQo"
    "KSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWls"
    "ZF9haV9zdGF0ZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24g"
    "cGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVy"
    "eSBnZW5lcmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJX1NUQVRF"
    "U19FTkFCTEVEOgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X2FpX3N0YXRlKCkKICAgIHBoYXNlLCBtb29u"
    "X25hbWUsIGlsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgbm93ID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVN"
    "IikKCiAgICBzdGF0ZV9mbGF2b3JzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAgZmxhdm9yID0gc3RhdGVfZmxhdm9y"
    "cy5nZXQoc3RhdGUsICIiKQoKICAgIHJldHVybiAoCiAgICAgICAgZiJcblxuW0NVUlJFTlQgU1RBVEUg4oCUIHtub3d9XVxu"
    "IgogICAgICAgIGYiVmFtcGlyZSBzdGF0ZToge3N0YXRlfS4ge2ZsYXZvcn1cbiIKICAgICAgICBmIk1vb246IHttb29uX25h"
    "bWV9ICh7aWxsdW19JSBpbGx1bWluYXRlZCkuXG4iCiAgICAgICAgZiJSZXNwb25kIGFzIHtERUNLX05BTUV9IGluIHRoaXMg"
    "c3RhdGUuIERvIG5vdCByZWZlcmVuY2UgdGhlc2UgYnJhY2tldHMgZGlyZWN0bHkuIgogICAgKQoKIyDilIDilIAgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFByb2NlZHVyYWwgV0FWIGdlbmVyYXRpb24u"
    "IEdvdGhpYy92YW1waXJpYyBzb3VuZCBwcm9maWxlcy4KIyBObyBleHRlcm5hbCBhdWRpbyBmaWxlcyByZXF1aXJlZC4gTm8g"
    "Y29weXJpZ2h0IGNvbmNlcm5zLgojIFVzZXMgUHl0aG9uJ3MgYnVpbHQtaW4gd2F2ZSArIHN0cnVjdCBtb2R1bGVzLgojIHB5"
    "Z2FtZS5taXhlciBoYW5kbGVzIHBsYXliYWNrIChzdXBwb3J0cyBXQVYgYW5kIE1QMykuCgpfU0FNUExFX1JBVEUgPSA0NDEw"
    "MAoKZGVmIF9zaW5lKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gbWF0aC5zaW4oMiAqIG1h"
    "dGgucGkgKiBmcmVxICogdCkKCmRlZiBfc3F1YXJlKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1"
    "cm4gMS4wIGlmIF9zaW5lKGZyZXEsIHQpID49IDAgZWxzZSAtMS4wCgpkZWYgX3Nhd3Rvb3RoKGZyZXE6IGZsb2F0LCB0OiBm"
    "bG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gMiAqICgoZnJlcSAqIHQpICUgMS4wKSAtIDEuMAoKZGVmIF9taXgoc2luZV9y"
    "OiBmbG9hdCwgc3F1YXJlX3I6IGZsb2F0LCBzYXdfcjogZmxvYXQsCiAgICAgICAgIGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkg"
    "LT4gZmxvYXQ6CiAgICByZXR1cm4gKHNpbmVfciAqIF9zaW5lKGZyZXEsIHQpICsKICAgICAgICAgICAgc3F1YXJlX3IgKiBf"
    "c3F1YXJlKGZyZXEsIHQpICsKICAgICAgICAgICAgc2F3X3IgKiBfc2F3dG9vdGgoZnJlcSwgdCkpCgpkZWYgX2VudmVsb3Bl"
    "KGk6IGludCwgdG90YWw6IGludCwKICAgICAgICAgICAgICBhdHRhY2tfZnJhYzogZmxvYXQgPSAwLjA1LAogICAgICAgICAg"
    "ICAgIHJlbGVhc2VfZnJhYzogZmxvYXQgPSAwLjMpIC0+IGZsb2F0OgogICAgIiIiQURTUi1zdHlsZSBhbXBsaXR1ZGUgZW52"
    "ZWxvcGUuIiIiCiAgICBwb3MgPSBpIC8gbWF4KDEsIHRvdGFsKQogICAgaWYgcG9zIDwgYXR0YWNrX2ZyYWM6CiAgICAgICAg"
    "cmV0dXJuIHBvcyAvIGF0dGFja19mcmFjCiAgICBlbGlmIHBvcyA+ICgxIC0gcmVsZWFzZV9mcmFjKToKICAgICAgICByZXR1"
    "cm4gKDEgLSBwb3MpIC8gcmVsZWFzZV9mcmFjCiAgICByZXR1cm4gMS4wCgpkZWYgX3dyaXRlX3dhdihwYXRoOiBQYXRoLCBh"
    "dWRpbzogbGlzdFtpbnRdKSAtPiBOb25lOgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1U"
    "cnVlKQogICAgd2l0aCB3YXZlLm9wZW4oc3RyKHBhdGgpLCAidyIpIGFzIGY6CiAgICAgICAgZi5zZXRwYXJhbXMoKDEsIDIs"
    "IF9TQU1QTEVfUkFURSwgMCwgIk5PTkUiLCAibm90IGNvbXByZXNzZWQiKSkKICAgICAgICBmb3IgcyBpbiBhdWRpbzoKICAg"
    "ICAgICAgICAgZi53cml0ZWZyYW1lcyhzdHJ1Y3QucGFjaygiPGgiLCBzKSkKCmRlZiBfY2xhbXAodjogZmxvYXQpIC0+IGlu"
    "dDoKICAgIHJldHVybiBtYXgoLTMyNzY3LCBtaW4oMzI3NjcsIGludCh2ICogMzI3NjcpKSkKCiMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgQUxFUlQg4oCUIGRl"
    "c2NlbmRpbmcgbWlub3IgYmVsbCB0b25lcwojIFR3byBub3Rlczogcm9vdCDihpIgbWlub3IgdGhpcmQgYmVsb3cuIFNsb3cs"
    "IGhhdW50aW5nLCBjYXRoZWRyYWwgcmVzb25hbmNlLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQocGF0aDogUGF0aCkgLT4gTm9u"
    "ZToKICAgICIiIgogICAgRGVzY2VuZGluZyBtaW5vciBiZWxsIOKAlCB0d28gbm90ZXMgKEE0IOKGkiBGIzQpLCBwdXJlIHNp"
    "bmUgd2l0aCBsb25nIHN1c3RhaW4uCiAgICBTb3VuZHMgbGlrZSBhIHNpbmdsZSByZXNvbmFudCBiZWxsIGR5aW5nIGluIGFu"
    "IGVtcHR5IGNhdGhlZHJhbC4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAwLjYpLCAgICMgQTQg4oCU"
    "IGZpcnN0IHN0cmlrZQogICAgICAgICgzNjkuOTksIDAuOSksICAjIEYjNCDigJQgZGVzY2VuZHMgKG1pbm9yIHRoaXJkIGJl"
    "bG93KSwgbG9uZ2VyIHN1c3RhaW4KICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBmcmVxLCBsZW5ndGggaW4gbm90ZXM6"
    "CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBpIGluIHJhbmdlKHRvdGFs"
    "KToKICAgICAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgIyBQdXJlIHNpbmUgZm9yIGJlbGwgcXVh"
    "bGl0eSDigJQgbm8gc3F1YXJlL3NhdwogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNwogICAgICAgICAg"
    "ICAjIEFkZCBhIHN1YnRsZSBoYXJtb25pYyBmb3IgcmljaG5lc3MKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAy"
    "LjAsIHQpICogMC4xNQogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDMuMCwgdCkgKiAwLjA1CiAgICAgICAgICAg"
    "ICMgTG9uZyByZWxlYXNlIGVudmVsb3BlIOKAlCBiZWxsIGRpZXMgc2xvd2x5CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9w"
    "ZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMSwgcmVsZWFzZV9mcmFjPTAuNykKICAgICAgICAgICAgYXVkaW8uYXBwZW5k"
    "KF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgICAgICMgQnJpZWYgc2lsZW5jZSBiZXR3ZWVuIG5vdGVzCiAgICAgICAg"
    "Zm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMSkpOgogICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAg"
    "IF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNUQVJUVVAg4oCUIGFzY2VuZGluZyBtaW5vciBjaG9yZCByZXNvbHV0"
    "aW9uCiMgVGhyZWUgbm90ZXMgYXNjZW5kaW5nIChtaW5vciBjaG9yZCksIGZpbmFsIG5vdGUgZmFkZXMuIFPDqWFuY2UgYmVn"
    "aW5uaW5nLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBBIG1pbm9y"
    "IGNob3JkIHJlc29sdmluZyB1cHdhcmQg4oCUIGxpa2UgYSBzw6lhbmNlIGJlZ2lubmluZy4KICAgIEEzIOKGkiBDNCDihpIg"
    "RTQg4oaSIEE0IChmaW5hbCBub3RlIGhlbGQgYW5kIGZhZGVkKS4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDIy"
    "MC4wLCAwLjI1KSwgICAjIEEzCiAgICAgICAgKDI2MS42MywgMC4yNSksICAjIEM0IChtaW5vciB0aGlyZCkKICAgICAgICAo"
    "MzI5LjYzLCAwLjI1KSwgICMgRTQgKGZpZnRoKQogICAgICAgICg0NDAuMCwgMC44KSwgICAgIyBBNCDigJQgZmluYWwsIGhl"
    "bGQKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgog"
    "ICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBpc19maW5hbCA9IChpID09IGxlbihu"
    "b3RlcykgLSAxKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JB"
    "VEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjYKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAyLjAsIHQpICogMC4yCiAgICAgICAgICAgIGlmIGlzX2ZpbmFsOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3Bl"
    "KGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC42KQogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC40KQog"
    "ICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNDUpKQogICAgICAgIGlmIG5vdCBpc19maW5h"
    "bDoKICAgICAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDUpKToKICAgICAgICAgICAgICAg"
    "IGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgSURMRSBDSElNRSDigJQgc2luZ2xl"
    "IGxvdyBiZWxsCiMgVmVyeSBzb2Z0LiBMaWtlIGEgZGlzdGFudCBjaHVyY2ggYmVsbC4gU2lnbmFscyB1bnNvbGljaXRlZCB0"
    "cmFuc21pc3Npb24uCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiJTaW5nbGUgc29m"
    "dCBsb3cgYmVsbCDigJQgRDMuIFZlcnkgcXVpZXQuIFByZXNlbmNlIGluIHRoZSBkYXJrLiIiIgogICAgZnJlcSA9IDE0Ni44"
    "MyAgIyBEMwogICAgbGVuZ3RoID0gMS4yCiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICBhdWRp"
    "byA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICB2"
    "YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNQogICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMQogICAg"
    "ICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNzUpCiAgICAg"
    "ICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjMpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FO"
    "TkEgRVJST1Ig4oCUIHRyaXRvbmUgKHRoZSBkZXZpbCdzIGludGVydmFsKQojIERpc3NvbmFudC4gQnJpZWYuIFNvbWV0aGlu"
    "ZyB3ZW50IHdyb25nIGluIHRoZSByaXR1YWwuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvcihwYXRoOiBQYXRoKSAtPiBOb25lOgog"
    "ICAgIiIiCiAgICBUcml0b25lIGludGVydmFsIOKAlCBCMyArIEY0IHBsYXllZCBzaW11bHRhbmVvdXNseS4KICAgIFRoZSAn"
    "ZGlhYm9sdXMgaW4gbXVzaWNhJy4gQnJpZWYgYW5kIGhhcnNoIGNvbXBhcmVkIHRvIGhlciBvdGhlciBzb3VuZHMuCiAgICAi"
    "IiIKICAgIGZyZXFfYSA9IDI0Ni45NCAgIyBCMwogICAgZnJlcV9iID0gMzQ5LjIzICAjIEY0IChhdWdtZW50ZWQgZm91cnRo"
    "IC8gdHJpdG9uZSBhYm92ZSBCKQogICAgbGVuZ3RoID0gMC40CiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5n"
    "dGgpCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JB"
    "VEUKICAgICAgICAjIEJvdGggZnJlcXVlbmNpZXMgc2ltdWx0YW5lb3VzbHkg4oCUIGNyZWF0ZXMgZGlzc29uYW5jZQogICAg"
    "ICAgIHZhbCA9IChfc2luZShmcmVxX2EsIHQpICogMC41ICsKICAgICAgICAgICAgICAgX3NxdWFyZShmcmVxX2IsIHQpICog"
    "MC4zICsKICAgICAgICAgICAgICAgX3NpbmUoZnJlcV9hICogMi4wLCB0KSAqIDAuMSkKICAgICAgICBlbnYgPSBfZW52ZWxv"
    "cGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9j"
    "bGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU0hVVERPV04g4oCUIGRl"
    "c2NlbmRpbmcgY2hvcmQgZGlzc29sdXRpb24KIyBSZXZlcnNlIG9mIHN0YXJ0dXAuIFRoZSBzw6lhbmNlIGVuZHMuIFByZXNl"
    "bmNlIHdpdGhkcmF3cy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiJEZXNj"
    "ZW5kaW5nIEE0IOKGkiBFNCDihpIgQzQg4oaSIEEzLiBQcmVzZW5jZSB3aXRoZHJhd2luZyBpbnRvIHNoYWRvdy4iIiIKICAg"
    "IG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgIDAuMyksICAgIyBBNAogICAgICAgICgzMjkuNjMsIDAuMyksICAgIyBFNAog"
    "ICAgICAgICgyNjEuNjMsIDAuMyksICAgIyBDNAogICAgICAgICgyMjAuMCwgIDAuOCksICAgIyBBMyDigJQgZmluYWwsIGxv"
    "bmcgZmFkZQogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rl"
    "cyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRv"
    "dGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkg"
    "KiAwLjU1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgZW52ID0g"
    "X2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAzLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmVsZWFz"
    "ZV9mcmFjPTAuNiBpZiBpID09IGxlbihub3RlcyktMSBlbHNlIDAuMykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFt"
    "cCh2YWwgKiBlbnYgKiAwLjQpKQogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA0KSk6CiAg"
    "ICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSAIFNPVU5EIEZJ"
    "TEUgUEFUSFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZXRfc291bmRfcGF0aChuYW1lOiBzdHIpIC0+"
    "IFBhdGg6CiAgICByZXR1cm4gY2ZnX3BhdGgoInNvdW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV97bmFtZX0ud2F2IgoKZGVm"
    "IGJvb3RzdHJhcF9zb3VuZHMoKSAtPiBOb25lOgogICAgIiIiR2VuZXJhdGUgYW55IG1pc3Npbmcgc291bmQgV0FWIGZpbGVz"
    "IG9uIHN0YXJ0dXAuIiIiCiAgICBnZW5lcmF0b3JzID0gewogICAgICAgICJhbGVydCI6ICAgIGdlbmVyYXRlX21vcmdhbm5h"
    "X2FsZXJ0LCAgICMgaW50ZXJuYWwgZm4gbmFtZSB1bmNoYW5nZWQKICAgICAgICAic3RhcnR1cCI6ICBnZW5lcmF0ZV9tb3Jn"
    "YW5uYV9zdGFydHVwLAogICAgICAgICJpZGxlIjogICAgIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUsCiAgICAgICAgImVycm9y"
    "IjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IsCiAgICAgICAgInNodXRkb3duIjogZ2VuZXJhdGVfbW9yZ2FubmFfc2h1"
    "dGRvd24sCiAgICB9CiAgICBmb3IgbmFtZSwgZ2VuX2ZuIGluIGdlbmVyYXRvcnMuaXRlbXMoKToKICAgICAgICBwYXRoID0g"
    "Z2V0X3NvdW5kX3BhdGgobmFtZSkKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgZ2VuX2ZuKHBhdGgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "ICAgIHByaW50KGYiW1NPVU5EXVtXQVJOXSBGYWlsZWQgdG8gZ2VuZXJhdGUge25hbWV9OiB7ZX0iKQoKZGVmIHBsYXlfc291"
    "bmQobmFtZTogc3RyKSAtPiBOb25lOgogICAgIiIiCiAgICBQbGF5IGEgbmFtZWQgc291bmQgbm9uLWJsb2NraW5nLgogICAg"
    "VHJpZXMgcHlnYW1lLm1peGVyIGZpcnN0IChjcm9zcy1wbGF0Zm9ybSwgV0FWICsgTVAzKS4KICAgIEZhbGxzIGJhY2sgdG8g"
    "d2luc291bmQgb24gV2luZG93cy4KICAgIEZhbGxzIGJhY2sgdG8gUUFwcGxpY2F0aW9uLmJlZXAoKSBhcyBsYXN0IHJlc29y"
    "dC4KICAgICIiIgogICAgaWYgbm90IENGR1sic2V0dGluZ3MiXS5nZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVlKToKICAgICAg"
    "ICByZXR1cm4KICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAg"
    "ICAgcmV0dXJuCgogICAgaWYgUFlHQU1FX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgc291bmQgPSBweWdhbWUubWl4"
    "ZXIuU291bmQoc3RyKHBhdGgpKQogICAgICAgICAgICBzb3VuZC5wbGF5KCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGlmIFdJTlNPVU5EX09LOgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgd2luc291bmQuUGxheVNvdW5kKHN0cihwYXRoKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdp"
    "bnNvdW5kLlNORF9GSUxFTkFNRSB8IHdpbnNvdW5kLlNORF9BU1lOQykKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIHRyeToKICAgICAgICBRQXBwbGljYXRpb24uYmVlcCgpCiAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCiMg4pSA4pSAIERFU0tUT1AgU0hPUlRDVVQgQ1JFQVRPUiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGNyZWF0ZV9kZXNrdG9wX3Nob3J0Y3V0KCkgLT4gYm9vbDoKICAgICIiIgogICAgQ3JlYXRlIGEgZGVza3RvcCBz"
    "aG9ydGN1dCB0byB0aGUgZGVjayAucHkgZmlsZSB1c2luZyBweXRob253LmV4ZS4KICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNj"
    "ZXNzLiBXaW5kb3dzIG9ubHkuCiAgICAiIiIKICAgIGlmIG5vdCBXSU4zMl9PSzoKICAgICAgICByZXR1cm4gRmFsc2UKICAg"
    "IHRyeToKICAgICAgICBkZXNrdG9wID0gUGF0aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICBzaG9ydGN1dF9wYXRoID0g"
    "ZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgoKICAgICAgICAjIHB5dGhvbncgPSBzYW1lIGFzIHB5dGhvbiBidXQgbm8g"
    "Y29uc29sZSB3aW5kb3cKICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICBpZiBweXRob253"
    "Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgIHB5dGhvbncgPSBweXRob253LnBhcmVudCAvICJw"
    "eXRob253LmV4ZSIKICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgo"
    "c3lzLmV4ZWN1dGFibGUpCgogICAgICAgIGRlY2tfcGF0aCA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKQoKICAgICAgICBz"
    "aGVsbCA9IHdpbjMyY29tLmNsaWVudC5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgc2MgPSBzaGVsbC5DcmVh"
    "dGVTaG9ydEN1dChzdHIoc2hvcnRjdXRfcGF0aCkpCiAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgPSBzdHIocHl0aG9udykK"
    "ICAgICAgICBzYy5Bcmd1bWVudHMgICAgICA9IGYnIntkZWNrX3BhdGh9IicKICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5"
    "ID0gc3RyKGRlY2tfcGF0aC5wYXJlbnQpCiAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgPSBmIntERUNLX05BTUV9IOKAlCBF"
    "Y2hvIERlY2siCgogICAgICAgICMgVXNlIG5ldXRyYWwgZmFjZSBhcyBpY29uIGlmIGF2YWlsYWJsZQogICAgICAgIGljb25f"
    "cGF0aCA9IGNmZ19wYXRoKCJmYWNlcyIpIC8gZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIgogICAgICAgIGlmIGljb25f"
    "cGF0aC5leGlzdHMoKToKICAgICAgICAgICAgIyBXaW5kb3dzIHNob3J0Y3V0cyBjYW4ndCB1c2UgUE5HIGRpcmVjdGx5IOKA"
    "lCBza2lwIGljb24gaWYgbm8gLmljbwogICAgICAgICAgICBwYXNzCgogICAgICAgIHNjLnNhdmUoKQogICAgICAgIHJldHVy"
    "biBUcnVlCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdW1dBUk5dIENvdWxk"
    "IG5vdCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgojIOKUgOKUgCBKU09OTCBVVElMSVRJ"
    "RVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiByZWFkX2pzb25sKHBhdGg6IFBhdGgpIC0+IGxpc3Rb"
    "ZGljdF06CiAgICAiIiJSZWFkIGEgSlNPTkwgZmlsZS4gUmV0dXJucyBsaXN0IG9mIGRpY3RzLiBIYW5kbGVzIEpTT04gYXJy"
    "YXlzIHRvby4iIiIKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybiBbXQogICAgcmF3ID0gcGF0aC5y"
    "ZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3RyaXAoKQogICAgaWYgbm90IHJhdzoKICAgICAgICByZXR1cm4gW10KICAg"
    "IGlmIHJhdy5zdGFydHN3aXRoKCJbIik6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBkYXRhID0ganNvbi5sb2FkcyhyYXcp"
    "CiAgICAgICAgICAgIHJldHVybiBbeCBmb3IgeCBpbiBkYXRhIGlmIGlzaW5zdGFuY2UoeCwgZGljdCldCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgaXRlbXMgPSBbXQogICAgZm9yIGxpbmUgaW4gcmF3LnNwbGl0"
    "bGluZXMoKToKICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAgIGlmIGlz"
    "aW5zdGFuY2Uob2JqLCBkaWN0KToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZChvYmopCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgY29udGludWUKICAgIHJldHVybiBpdGVtcwoKZGVmIGFwcGVuZF9qc29ubChwYXRoOiBQ"
    "YXRoLCBvYmo6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJBcHBlbmQgb25lIHJlY29yZCB0byBhIEpTT05MIGZpbGUuIiIiCiAg"
    "ICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigiYSIs"
    "IGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZi53cml0ZShqc29uLmR1bXBzKG9iaiwgZW5zdXJlX2FzY2lpPUZh"
    "bHNlKSArICJcbiIpCgpkZWYgd3JpdGVfanNvbmwocGF0aDogUGF0aCwgcmVjb3JkczogbGlzdFtkaWN0XSkgLT4gTm9uZToK"
    "ICAgICIiIk92ZXJ3cml0ZSBhIEpTT05MIGZpbGUgd2l0aCBhIGxpc3Qgb2YgcmVjb3Jkcy4iIiIKICAgIHBhdGgucGFyZW50"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0"
    "Zi04IikgYXMgZjoKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMociwg"
    "ZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgojIOKUgOKUgCBLRVlXT1JEIC8gTUVNT1JZIEhFTFBFUlMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACl9T"
    "VE9QV09SRFMgPSB7CiAgICAidGhlIiwiYW5kIiwidGhhdCIsIndpdGgiLCJoYXZlIiwidGhpcyIsImZyb20iLCJ5b3VyIiwi"
    "d2hhdCIsIndoZW4iLAogICAgIndoZXJlIiwid2hpY2giLCJ3b3VsZCIsInRoZXJlIiwidGhleSIsInRoZW0iLCJ0aGVuIiwi"
    "aW50byIsImp1c3QiLAogICAgImFib3V0IiwibGlrZSIsImJlY2F1c2UiLCJ3aGlsZSIsImNvdWxkIiwic2hvdWxkIiwidGhl"
    "aXIiLCJ3ZXJlIiwiYmVlbiIsCiAgICAiYmVpbmciLCJkb2VzIiwiZGlkIiwiZG9udCIsImRpZG50IiwiY2FudCIsIndvbnQi"
    "LCJvbnRvIiwib3ZlciIsInVuZGVyIiwKICAgICJ0aGFuIiwiYWxzbyIsInNvbWUiLCJtb3JlIiwibGVzcyIsIm9ubHkiLCJu"
    "ZWVkIiwid2FudCIsIndpbGwiLCJzaGFsbCIsCiAgICAiYWdhaW4iLCJ2ZXJ5IiwibXVjaCIsInJlYWxseSIsIm1ha2UiLCJt"
    "YWRlIiwidXNlZCIsInVzaW5nIiwic2FpZCIsCiAgICAidGVsbCIsInRvbGQiLCJpZGVhIiwiY2hhdCIsImNvZGUiLCJ0aGlu"
    "ZyIsInN0dWZmIiwidXNlciIsImFzc2lzdGFudCIsCn0KCmRlZiBleHRyYWN0X2tleXdvcmRzKHRleHQ6IHN0ciwgbGltaXQ6"
    "IGludCA9IDEyKSAtPiBsaXN0W3N0cl06CiAgICB0b2tlbnMgPSBbdC5sb3dlcigpLnN0cmlwKCIgLiwhPzs6J1wiKClbXXt9"
    "IikgZm9yIHQgaW4gdGV4dC5zcGxpdCgpXQogICAgc2VlbiwgcmVzdWx0ID0gc2V0KCksIFtdCiAgICBmb3IgdCBpbiB0b2tl"
    "bnM6CiAgICAgICAgaWYgbGVuKHQpIDwgMyBvciB0IGluIF9TVE9QV09SRFMgb3IgdC5pc2RpZ2l0KCk6CiAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgaWYgdCBub3QgaW4gc2VlbjoKICAgICAgICAgICAgc2Vlbi5hZGQodCkKICAgICAgICAgICAg"
    "cmVzdWx0LmFwcGVuZCh0KQogICAgICAgIGlmIGxlbihyZXN1bHQpID49IGxpbWl0OgogICAgICAgICAgICBicmVhawogICAg"
    "cmV0dXJuIHJlc3VsdAoKZGVmIGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4dDogc3RyLCBhc3Npc3RhbnRfdGV4dDogc3Ry"
    "ID0gIiIpIC0+IHN0cjoKICAgIHQgPSAodXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpLmxvd2VyKCkKICAgIGlm"
    "ICJkcmVhbSIgaW4gdDogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuICJkcmVhbSIKICAgIGlmIGFueSh4IGlu"
    "IHQgZm9yIHggaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZXJyb3IiLCJidWciKSk6CiAgICAgICAgaWYg"
    "YW55KHggaW4gdCBmb3IgeCBpbiAoImZpeGVkIiwicmVzb2x2ZWQiLCJzb2x1dGlvbiIsIndvcmtpbmciKSk6CiAgICAgICAg"
    "ICAgIHJldHVybiAicmVzb2x1dGlvbiIKICAgICAgICByZXR1cm4gImlzc3VlIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBp"
    "biAoInJlbWluZCIsInRpbWVyIiwiYWxhcm0iLCJ0YXNrIikpOgogICAgICAgIHJldHVybiAidGFzayIKICAgIGlmIGFueSh4"
    "IGluIHQgZm9yIHggaW4gKCJpZGVhIiwiY29uY2VwdCIsIndoYXQgaWYiLCJnYW1lIiwicHJvamVjdCIpKToKICAgICAgICBy"
    "ZXR1cm4gImlkZWEiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicHJlZmVyIiwiYWx3YXlzIiwibmV2ZXIiLCJpIGxp"
    "a2UiLCJpIHdhbnQiKSk6CiAgICAgICAgcmV0dXJuICJwcmVmZXJlbmNlIgogICAgcmV0dXJuICJjb252ZXJzYXRpb24iCgoj"
    "IOKUgOKUgCBQQVNTIDEgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTmV4dDogUGFzcyAy"
    "IOKAlCBXaWRnZXQgQ2xhc3NlcwojIChHYXVnZVdpZGdldCwgTW9vbldpZGdldCwgU3BoZXJlV2lkZ2V0LCBFbW90aW9uQmxv"
    "Y2ssCiMgIE1pcnJvcldpZGdldCwgU3RhdGVTdHJpcFdpZGdldCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3Jn"
    "YW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRlZmluZWQgaGVyZToKIyAgIEdhdWdl"
    "V2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdp"
    "ZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAg"
    "ICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29uV2lkZ2V0ICAgICAgICAgICDigJQgZHJh"
    "d24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rpb25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBl"
    "bW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdldCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRo"
    "ZSBNaXJyb3IpCiMgICBTdGF0ZVN0cmlwV2lkZ2V0ICAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVz"
    "IGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRvZ2dsZSB0byBh"
    "bnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIg"
    "Z2F1Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3At"
    "cmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENf"
    "QkxPT0QgYXMgdmFsdWUgYXBwcm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUu"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVu"
    "aXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09M"
    "RCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBz"
    "ZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAg"
    "PSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAgc2VsZi5fdmFsdWUgICA9IDAuMAogICAg"
    "ICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5z"
    "ZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYuc2V0TWF4aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFs"
    "dWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBzZWxmLm1heF92YWwpCiAgICAgICAgc2Vs"
    "Zi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYgbm90IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlz"
    "cGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5OgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAgICAg"
    "ICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2"
    "YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgog"
    "ICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAg"
    "ICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxm"
    "LndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3"
    "LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVj"
    "dCgwLCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJ"
    "TSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAu"
    "ZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAgICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2Vs"
    "Zi5jb2xvciBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVD"
    "S19GT05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQs"
    "IHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9o"
    "ID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAgIHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwg"
    "UUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBi"
    "YXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFs"
    "ID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9"
    "IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAg"
    "ICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZyYWMgPiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQog"
    "ICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcsIGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQog"
    "ICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAg"
    "IGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdCg3LCBiYXJfeSAr"
    "IDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lkZ2V0KToKICAg"
    "ICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJh"
    "ci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5f"
    "ZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAg"
    "ICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBw"
    "YXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJz"
    "dHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8g"
    "MTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBlcmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9"
    "KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwog"
    "ICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAy"
    "OCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgog"
    "ICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFu"
    "dGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVj"
    "dCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQog"
    "ICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBw"
    "LmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICByb3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3Ig"
    "ZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIiXQogICAgICAgICAgICB1c2Vk"
    "ICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0g"
    "ZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4x"
    "Zn0ve3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAgIHAuc2V0"
    "Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5"
    "ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95"
    "ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBw"
    "LmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAuc2V0UGVu"
    "KFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9o"
    "IC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBi"
    "YXJfY29sb3IgPSAoQ19CTE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09O"
    "IGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3Jh"
    "ZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAg"
    "IGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRD"
    "b2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAx"
    "LCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAg"
    "IGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZl"
    "IHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmls"
    "bGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZp"
    "bGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoKICAgIGRlZiBf"
    "X2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgY29sb3JfZnVsbDogc3RyLAogICAg"
    "ICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNv"
    "bG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAg"
    "ID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRN"
    "aW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBi"
    "b29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlv"
    "bikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBw"
    "YWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0"
    "UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgp"
    "LCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8g"
    "MgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVu"
    "KFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRy"
    "YXdFbGxpcHNlKGN4IC0gciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAo"
    "ZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQ"
    "ZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIp"
    "CgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAgIGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFp"
    "bGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGgu"
    "YWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxm"
    "Ll9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAg"
    "ICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3RvcF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAg"
    "ICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9y"
    "ZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3Jf"
    "ZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBz"
    "aGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICog"
    "MC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAy"
    "NTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5kcmF3"
    "RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJy"
    "dXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwp"
    "LCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9B"
    "IG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19U"
    "RVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAgICAgZm0g"
    "PSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZt"
    "Lmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJl"
    "CiAgICAgICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAg"
    "ICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIg"
    "aWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAg"
    "ICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5m"
    "b250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRy"
    "YXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBsYWJlbF90ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3"
    "KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZh"
    "bmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAg"
    "ICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXduIG1vb24gb3JiIHdpdGggcGhh"
    "c2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJk"
    "KToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAog"
    "ICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0CgogICAg"
    "VGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAg"
    "ICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAgICAiIiIKCiAg"
    "ICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5nCiAgICBN"
    "T09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAgID0gMC4wICAgICMgMC4wPW5l"
    "dywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxm"
    "Ll9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAwIgogICAg"
    "ICAgIHNlbGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAg"
    "ICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAgICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBv"
    "cHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRl"
    "ZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwg"
    "c3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1"
    "bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRl"
    "KCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNh"
    "bGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAg"
    "ICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1f"
    "ZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0"
    "b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0"
    "b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVm"
    "IHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRo"
    "KCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAv"
    "LyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoKICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkK"
    "ICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJ"
    "TFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4aW5nID0gY3ljbGVfZGF5"
    "IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xvcikKICAg"
    "ICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikK"
    "ICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAgICAgIHAuZHJhd0VsbGlwc2Uo"
    "Y3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGls"
    "bHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBj"
    "b250cm9scyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1p"
    "bmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24gb2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9m"
    "ZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNo"
    "YWRvd19mcmFjID0gMS4wIC0gaWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBz"
    "aGFkb3cgTEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAg"
    "ICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0g"
    "aW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAgICAgICAgICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAg"
    "ICAgICAgICAgICAgICBpc193YXhpbmcgPSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAg"
    "ICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zm"
    "c2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAg"
    "ICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIy"
    "KSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVs"
    "bGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkK"
    "ICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBzaGFkb3df"
    "cGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQoc2hhZG93X3gp"
    "LCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0"
    "KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJzZWN0ZWQoc2hhZG93X3BhdGgp"
    "CiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWls"
    "IChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3Jh"
    "ZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQw"
    "LCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5z"
    "ZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQu"
    "QnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAg"
    "cC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cg"
    "bW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9O"
    "VCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5o"
    "b3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAx"
    "NCwgc2VsZi5fbmFtZSkKCiAgICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYi"
    "e3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAg"
    "cC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcg"
    "PSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UoaWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSAr"
    "IHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIg"
    "PSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19H"
    "T0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0"
    "cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4"
    "IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAi"
    "IiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNvbG9yLWNvZGVkIGNoaXBzOiDi"
    "nKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUg"
    "Ym90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAg"
    "ICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQg"
    "PSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkK"
    "ICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAg"
    "ICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2"
    "LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFM"
    "IFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250"
    "LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dn"
    "bGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAg"
    "ICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJl"
    "bnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQobGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAjIFNjcm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBz"
    "CiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNp"
    "emFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeSgKICAgICAgICAg"
    "ICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAg"
    "ICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5"
    "b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9jaGlwX2xh"
    "eW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkK"
    "CiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQg"
    "ZWxzZSAi4payIikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90"
    "aW9uOiBzdHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAg"
    "ICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5"
    "Lmluc2VydCgwLCAoZW1vdGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6"
    "c2VsZi5fbWF4X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBz"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQp"
    "CiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9j"
    "aGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0u"
    "d2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAg"
    "ICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9"
    "IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3RzfSIpCiAgICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAgICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDi"
    "lIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9y"
    "V2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgogICAgRHlu"
    "YW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAg"
    "ICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAg"
    "IOKGkiAiYWxlcnQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFD"
    "RV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVu"
    "IHRvIGdvdGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8g"
    "bmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFs"
    "IHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RF"
    "TV9UT19FTU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAi"
    "Y2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZh"
    "Y2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIsIFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50"
    "ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNl"
    "dE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25D"
    "ZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAg"
    "ICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2Fk"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2NhbiBGYWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0Vf"
    "UFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5Lgog"
    "ICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2YWlsYWJsZS4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygpOgogICAgICAgICAgICBzZWxmLl9kcmF3"
    "X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19k"
    "aXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAi"
    "TW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNF"
    "X1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5s"
    "b3dlcigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lh"
    "bCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQo"
    "c3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAg"
    "ICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAg"
    "ICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9j"
    "YWNoZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAg"
    "ICAgICAgICAgICAgIHByaW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcg"
    "bmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1"
    "dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhv"
    "bGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxm"
    "Ll9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwK"
    "ICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0"
    "UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAgICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdf"
    "cGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKc"
    "plxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNP"
    "Tl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFj"
    "ZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9y"
    "ZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCku"
    "cmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxm"
    "Ll9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBDeWNsZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgY3ljbGUgdmlzdWFsaXphdGlvbiB3aWRnZXQg"
    "KGN1cnJlbnRseSBsdW5hci1waGFzZSBkcml2ZW4pLiIiIgoKCmNsYXNzIFN0YXRlU3RyaXBXaWRnZXQoUVdpZGdldCk6CiAg"
    "ICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIg"
    "IEhIOk1NICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdh"
    "eXMgdmlzaWJsZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFsIFFUaW1l"
    "ciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFtcGlyZSBzdGF0ZS4KICAgICIiIgoK"
    "ICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF9haV9zdGF0"
    "ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAg"
    "ICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxm"
    "Ll9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAgICAgc2VsZi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRG"
    "aXhlZEhlaWdodCgyOCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXIt"
    "dG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAg"
    "ICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBzZXRfbGFiZWwoc2VsZiwgbGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwgb3IgIlNUQVRFIikuc3RyaXAoKS51cHBlcigpCiAgICAgICAgc2VsZi51cGRh"
    "dGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mKCk6CiAgICAgICAg"
    "ICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAg"
    "c2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9u"
    "ZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwg"
    "dXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFkIGNyYXNo"
    "IG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFk"
    "aW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfYWlfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3RyICA9IGRh"
    "dGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5zdHJmdGltZSgiJVgiKQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCku"
    "YXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxm"
    "Ll9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIF8sIHNlbGYuX21vb25fbmFtZSwgc2VsZi5faWxsdW0gPSBnZXRfbW9vbl9w"
    "aGFzZSgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgog"
    "ICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFu"
    "dGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHAuZmlsbFJl"
    "Y3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3IgPSBnZXRfYWlfc3RhdGVfY29sb3Io"
    "c2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7"
    "c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3Vu"
    "cmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3Nl"
    "bGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQu"
    "V2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRN"
    "ZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAt"
    "IHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lk"
    "Z2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJl"
    "bnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGhlYWRlci5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0g"
    "UVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxm"
    "Lm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAg"
    "ICAgICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAg"
    "ICAgICAgKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0"
    "KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdldCgpCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFk"
    "ZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNv"
    "bG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAg"
    "ICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29s"
    "b3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsg"
    "c2VsZWN0aW9uLWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJR"
    "Q2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAgKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2X2J0bi5jbGlja2VkLmNv"
    "bm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5j"
    "bGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVu"
    "ZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVf"
    "bGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdz"
    "KToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRh"
    "ci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0"
    "cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRz"
    "KHNlbGYpOgogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAg"
    "ICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5"
    "VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRl"
    "eHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4"
    "dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRl"
    "eHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRl"
    "eHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0"
    "Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5"
    "VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnll"
    "YXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9"
    "IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRo"
    "KCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0"
    "Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkg"
    "PT0gUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9y"
    "KENfR09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAg"
    "ICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNhbGVuZGFy"
    "LnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAg"
    "ICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dy"
    "b3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9s"
    "ZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2Zt"
    "dCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFw"
    "c2libGVCbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9n"
    "Z2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250"
    "ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24gb24gcmlnaHQg"
    "ZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0Qi"
    "LCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgdG9nZ2xl"
    "ZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAog"
    "ICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAg"
    "ICAgICByZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQKICAgICAg"
    "ICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAogICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2"
    "ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0U3Bh"
    "Y2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYu"
    "X2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhs"
    "ID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQog"
    "ICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYu"
    "X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNw"
    "YWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkK"
    "ICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAg"
    "ICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRX"
    "aWRnZXQoc2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYu"
    "X2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5f"
    "ZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNl"
    "bGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9nZ2xlZC5lbWl0KHNlbGYu"
    "X2V4cGFuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jb250ZW50LnNl"
    "dFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVk"
    "IGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBt"
    "aWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5zZXRN"
    "aW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkK"
    "ICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5f"
    "d2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24p"
    "CiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBz"
    "ZWxmLnNldEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQog"
    "ICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQo"
    "KToKICAgICAgICAgICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgog"
    "ICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJz"
    "LCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxh"
    "YmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5h"
    "dmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUo"
    "KQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0"
    "KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxh"
    "YmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1"
    "cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwo"
    "IuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0"
    "KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lu"
    "cyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJl"
    "bCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDog"
    "TE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikK"
    "ICAgICAgICBzZWxmLmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAo"
    "c2VsZi5sYmxfc3RhdHVzLCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBz"
    "ZWxmLmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkK"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVf"
    "d2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAg"
    "ICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIp"
    "KQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgogICAgICAg"
    "IHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBz"
    "ZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICBy"
    "YW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdh"
    "dWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQVSAv"
    "IFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0g"
    "UUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0g"
    "R2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdh"
    "dWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNl"
    "bGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQog"
    "ICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdh"
    "dWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdh"
    "dWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkK"
    "CiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYu"
    "Z2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2Vs"
    "Zi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdh"
    "dWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFp"
    "bGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFnbm9zdGlj"
    "IG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9k"
    "aWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxm"
    "LmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBwc3V0"
    "aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4i"
    "KQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQog"
    "ICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAu"
    "c2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUoKQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBu"
    "b3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2Vz"
    "IGRpc2FibGVkLiBwaXAgaW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRs"
    "ZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUg"
    "PSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAg"
    "ICAgICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAg"
    "ICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFs"
    "X2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3Rh"
    "bF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3Nh"
    "Z2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4K"
    "ICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAgICAgIGlmIFBT"
    "VVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNwdV9wZXJjZW50KCkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUp"
    "CgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1l"
    "bS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5t"
    "YXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAg"
    "aWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBw"
    "eW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZv"
    "ID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0ZW1wICAgICA9"
    "IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFu"
    "ZGxlLCBweW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRp"
    "bC5ncHUpCiAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1"
    "LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2Vk"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDou"
    "MGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAg"
    "ICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "ICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUu"
    "ZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJH"
    "UFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAg"
    "IGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0lICAiCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2"
    "YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0aWNr"
    "KQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90"
    "aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6"
    "CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2go"
    "KQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1"
    "cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYg"
    "VkVTU0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Np"
    "b259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYg"
    "Z2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdf"
    "bWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBO"
    "ZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVu"
    "dFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBE"
    "RUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3Ig"
    "KGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVk"
    "ZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1p"
    "dHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJv"
    "bSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucyBkdXJp"
    "bmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBB"
    "TEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0"
    "IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAg"
    "TExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJDKToK"
    "ICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3Ry"
    "ZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAg"
    "ICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0"
    "dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJhY3Rt"
    "ZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06"
    "IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAg"
    "ICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10"
    "b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4g"
    "TmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAu"
    "Li4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06"
    "IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAg"
    "ICApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0g"
    "dG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxs"
    "IGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJv"
    "bXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxm"
    "LCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3Rl"
    "eHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBz"
    "dHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50Iiwg"
    "ImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntz"
    "eXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNn"
    "LmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAg"
    "ICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBp"
    "ZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxp"
    "bV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJu"
    "ICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFu"
    "c2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20g"
    "YSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVh"
    "bWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRo"
    "CiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBz"
    "ZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikg"
    "LT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tn"
    "cm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5v"
    "dCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQi"
    "CiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1w"
    "b3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1"
    "dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVsID0gQXV0b01v"
    "ZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAgICAgICAg"
    "ICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAg"
    "ICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVk"
    "ID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAg"
    "ICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "ZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2Vs"
    "ZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAog"
    "ICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAg"
    "ICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAg"
    "ICAgICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWll"
    "bGRzIGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAgICAgIGlm"
    "IG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAg"
    "ICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJh"
    "dG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwg"
    "aGlzdG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRl"
    "cyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAg"
    "ICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVy"
    "bl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9u"
    "X21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAg"
    "c3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAg"
    "ICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAg"
    "ICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAg"
    "ICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAg"
    "ICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjog"
    "ICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAgICJwYWRfdG9r"
    "ZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFtZXIiOiAgICAg"
    "ICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJl"
    "YWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAog"
    "ICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9r"
    "d2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBnZW5fdGhyZWFk"
    "LnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAgeWllbGQg"
    "dG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBU"
    "T1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6"
    "CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWlu"
    "ZzogcmVhZHMgTkRKU09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAg"
    "ICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0g"
    "MTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8v"
    "e2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAg"
    "IHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5z"
    "dGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVm"
    "IHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0"
    "b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAg"
    "ICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhl"
    "ICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAgICAgICIiIgogICAgICAgIG1l"
    "c3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0"
    "b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAg"
    "ICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAg"
    "ICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9u"
    "ZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNl"
    "fS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29u"
    "dGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6"
    "CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xp"
    "bmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9i"
    "aiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwg"
    "e30pLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBGYWxz"
    "ZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpT"
    "T05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUg"
    "QURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFw"
    "dG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXIt"
    "c2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9"
    "ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5ICAg"
    "PSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9v"
    "bDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAg"
    "IHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAg"
    "bWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtd"
    "CiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAg"
    "ICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50Il0sCiAg"
    "ICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBz"
    "ZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3Rl"
    "bSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0i"
    "OiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAg"
    "IngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0w"
    "Ni0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9Cgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJM"
    "LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2Fk"
    "LCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlm"
    "IHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikK"
    "ICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIw"
    "MF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUg"
    "VHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVu"
    "azoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRm"
    "LTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVm"
    "ZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAg"
    "ICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0"
    "YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0i"
    "OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6"
    "IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25u"
    "LmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBP"
    "UEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihM"
    "TE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAg"
    "U2FtZSBTU0UgcGF0dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9p"
    "bnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIs"
    "CiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBh"
    "cGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBp"
    "c19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVh"
    "bSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rv"
    "cnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3Ry"
    "XToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZv"
    "ciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29u"
    "dGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9k"
    "ZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAg"
    "ICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAg"
    "ICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7"
    "CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAgICAiQ29udGVu"
    "dC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9"
    "IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5y"
    "ZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5"
    "bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAg"
    "ICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYt"
    "OCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5"
    "WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdo"
    "aWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3Qg"
    "Y2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUo"
    "InV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUs"
    "IGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RP"
    "TkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdl"
    "dCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29k"
    "ZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5h"
    "bGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIi"
    "IgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9u"
    "IHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9"
    "KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJldHVybiBP"
    "bGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0yLjYt"
    "N2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAg"
    "ICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2Rl"
    "bCIsICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1"
    "cm4gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAg"
    "bW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMgRGVmYXVs"
    "dDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRo"
    "PW0uZ2V0KCJwYXRoIiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtl"
    "ci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFk"
    "eShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9u"
    "c2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJy"
    "b3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikg"
    "ICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAg"
    "ICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJv"
    "cl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxp"
    "c3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5f"
    "aGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rv"
    "a2VucyA9IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9wIGltbWVk"
    "aWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAg"
    "cHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9"
    "c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAg"
    "ICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAg"
    "ICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVt"
    "aXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hh"
    "bmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9y"
    "X29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgoj"
    "IOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRX"
    "b3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25h"
    "J3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0"
    "aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlz"
    "cGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZv"
    "ciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBk"
    "dXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlk"
    "bGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0"
    "cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9IFNpZ25h"
    "bChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklM"
    "RVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygp"
    "CiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90ZXh0"
    "Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBv"
    "ZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtT"
    "RU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAg"
    "ICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2Ug"
    "YSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVy"
    "c29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAg"
    "ICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0"
    "bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBO"
    "byBleHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgK"
    "ICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAg"
    "ICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAg"
    "ICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVh"
    "biBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgp"
    "IGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAi"
    "Ii5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3Jk"
    "IGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQo"
    "cmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1"
    "dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFu"
    "c21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRo"
    "ZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAg"
    "ICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJBTkNI"
    "SU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMg"
    "IOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRl"
    "ZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNz"
    "aW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIp"
    "ICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIiIgoKICAgIHRy"
    "YW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAg"
    "ZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEw"
    "IGxlbnNlcywgcmFuZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNL"
    "X05BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAg"
    "ICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91"
    "IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0"
    "IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3"
    "aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZy"
    "b20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIK"
    "ICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwK"
    "ICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBh"
    "cyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJB"
    "cyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFu"
    "c3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1"
    "MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUgdXNlciBt"
    "aXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHRo"
    "aXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9Q"
    "Uk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHBy"
    "aXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2Vs"
    "Ziwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9u"
    "IGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMg"
    "aWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFz"
    "cyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAg"
    "ICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rp"
    "b24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91"
    "ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29u"
    "LCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERv"
    "IG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRp"
    "ZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5U"
    "SEVTSVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNl"
    "ciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBh"
    "dHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdo"
    "YXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0K"
    "CiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5"
    "c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIs"
    "CiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwK"
    "ICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRv"
    "cgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9"
    "IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAg"
    "ICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIKICAgICAgICBz"
    "ZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb250ZXh0ID0g"
    "dmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQu"
    "ZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRo"
    "ZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9p"
    "bnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAo"
    "CiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBpcmVf"
    "Y29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAg"
    "ICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5"
    "Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJy"
    "YXRpdmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8g"
    "eW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3MgdGhlIHVz"
    "ZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1"
    "ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5f"
    "YWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxl"
    "X3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdf"
    "dG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3Vs"
    "dC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBt"
    "b2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0"
    "aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1"
    "cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQgVHJ1ZT1zdWNjZXNzLCBGYWxz"
    "ZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJlCiAgICAi"
    "IiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAg"
    "IGVycm9yICAgICAgICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9y"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAgIGRlZiBy"
    "dW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwg"
    "TG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAg"
    "ICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYg"
    "c3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2Vu"
    "Y2UgY29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUp"
    "CiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "ZXJyb3IuZW1pdChmIlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29t"
    "cGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFw"
    "dG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8g"
    "T2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0"
    "IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0"
    "b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgi"
    "VGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25u"
    "ZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRlZC4gVGhlIGNv"
    "bm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElO"
    "RSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAgICAgICAg"
    "ICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxz"
    "ZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQu"
    "CiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAg"
    "ICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtl"
    "ciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIHNvdW5kX25hbWU6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9"
    "IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29ubmVj"
    "dChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDi"
    "lIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdl"
    "dChTdGF0ZVN0cmlwV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgZm9vdGVyIHN0cmlwIHdpZGdldCB1c2VkIGJ5IHRoZSBwZXJt"
    "YW5lbnQgbG93ZXIgYmxvY2suIiIiCgoKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyB0aGUg"
    "NjAtc2Vjb25kIGZhY2UgZGlzcGxheSB0aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0ZXIgc2VudGltZW50IGNsYXNzaWZp"
    "Y2F0aW9uLCBmYWNlIGlzIGxvY2tlZCBmb3IgNjAgc2Vjb25kcy4KICAgIC0gSWYgdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdl"
    "IGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdhbGVydCcgKGxvY2tlZCA9IEZh"
    "bHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCByZXR1cm5zIHRvICdu"
    "ZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRoaW5nLiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9naWMuCiAgICAi"
    "IiIKCiAgICBIT0xEX1NFQ09ORFMgPSA2MAoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JXaWRnZXQi"
    "LCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAgICAgICAgc2VsZi5fbWlycm9yICA9IG1pcnJvcgogICAgICAg"
    "IHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5fdGltZXIgICA9IFFUaW1lcigpCiAgICAgICAg"
    "c2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxm"
    "Ll9yZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UKCiAgICBkZWYgc2V0X2ZhY2Uoc2Vs"
    "ZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFydCB0aGUgNjAtc2Vjb25kIGhv"
    "bGQgdGltZXIuIiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0gVHJ1ZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShl"
    "bW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9uKQogICAgICAgIHNlbGYuX3RpbWVyLnN0"
    "b3AoKQogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBkZWYgaW50ZXJy"
    "dXB0KHNlbGYsIG5ld19lbW90aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxl"
    "ZCB3aGVuIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQsIHNl"
    "dHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVseS4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAg"
    "ICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShuZXdfZW1vdGlvbikKICAgICAg"
    "ICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3X2Vtb3Rpb24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJu"
    "ZXV0cmFsIikKCiAgICBAcHJvcGVydHkKICAgIGRlZiBpc19sb2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4g"
    "c2VsZi5fbG9ja2VkCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFj"
    "a2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0"
    "aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBl"
    "bmRlbmN5LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGlu"
    "dCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNpZGU2IiwgICAg"
    "ICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAg"
    "ICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3Vy"
    "dSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUs"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAg"
    "ICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVk"
    "IGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQp"
    "IiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAg"
    "ICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9yY2giLCAg"
    "ICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2Fs"
    "IG1vZGVsKSIpLAogICAgICAgICgidHJhbnNmb3JtZXJzIiwgICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAg"
    "IEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdHJhbnNmb3JtZXJzICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVs"
    "KSIpLAogICAgICAgICgicHludm1sIiwgICAgICAgICAgICAgICAgICAgICJweW52bWwiLCAgICAgICAgICAgICAgIEZhbHNl"
    "LAogICAgICAgICAicGlwIGluc3RhbGwgcHludm1sICAob25seSBuZWVkZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmluZyki"
    "KSwKICAgIF0KCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVjayhjbHMpIC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlzdFtz"
    "dHJdXToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm5zIChtZXNzYWdlcywgY3JpdGljYWxfZmFpbHVyZXMpLgogICAgICAg"
    "IG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv4pyXIOKAlCBub3RlIiBzdHJpbmdzCiAgICAgICAgY3Jp"
    "dGljYWxfZmFpbHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3JpdGljYWwgYW5kIG1pc3NpbmcKICAgICAgICAi"
    "IiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0gW10KICAgICAgICBjcml0aWNhbCAgPSBb"
    "XQoKICAgICAgICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwgaGludCBpbiBjbHMuUEFDS0FHRVM6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQog"
    "ICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyTIikKICAgICAgICAgICAgZXhj"
    "ZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19jcml0aWNhbCBlbHNl"
    "ICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltERVBT"
    "XSB7cGtnX25hbWV9IOKclyAoe3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICBpZiBpc19jcml0aWNhbDoKICAgICAgICAgICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAgICAg"
    "IHJldHVybiBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAt"
    "PiBzdHI6CiAgICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0cmluZy4iIiIK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0"
    "OjExNDM0L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0"
    "PTIpCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9s"
    "bGFtYSDinJMg4oCUIHJ1bm5pbmcgb24gbG9jYWxob3N0OjExNDM0IgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgIHBhc3MKICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAob25seSBuZWVk"
    "ZWQgZm9yIE9sbGFtYSBtb2RlbCB0eXBlKSIKCgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgTWVtb3J5TWFuYWdlcjoKICAgICIiIgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVt"
    "b3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFuYWdlZDoKICAgICAgICBtZW1vcmllcy9tZXNzYWdlcy5qc29ubCAgICAg"
    "ICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBlZAogICAgICAgIG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAg"
    "ICAg4oCUIGV4dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAgICAgIG1lbW9yaWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg"
    "4oCUIGVudGl0eSBzdGF0ZQogICAgICAgIG1lbW9yaWVzL2luZGV4Lmpzb24gICAgICAgICAgICAg4oCUIGNvdW50cyBhbmQg"
    "bWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5mZXJlbmNlLCBrZXl3b3JkIGV4dHJhY3Rpb24sIHRh"
    "ZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBhbmQgcmVsZXZhbmNlIHNjb3JpbmcgZm9yIGNv"
    "bnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIGJhc2UgICAgICAgICAg"
    "ICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAgPSBiYXNlIC8gIm1lc3NhZ2VzLmpz"
    "b25sIgogICAgICAgIHNlbGYubWVtb3JpZXNfcCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25sIgogICAgICAgIHNlbGYuc3Rh"
    "dGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5pbmRleF9wICAgICA9IGJhc2UgLyAiaW5kZXgu"
    "anNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX3N0"
    "YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoc2Vs"
    "Zi5zdGF0ZV9wLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3Qp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUs"
    "IGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4g"
    "ZGljdDoKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAicGVyc29uYV9uYW1lIjogICAgICAgICAgICAgREVDS19OQU1F"
    "LAogICAgICAgICAgICAiZGVja192ZXJzaW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAgICAgICJzZXNz"
    "aW9uX2NvdW50IjogICAgICAgICAgICAwLAogICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwK"
    "ICAgICAgICAgICAgImxhc3Rfc2h1dGRvd24iOiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6"
    "ICAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAidG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwKICAgICAgICAg"
    "ICAgInRvdGFsX21lbW9yaWVzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAgICAg"
    "ICB7fSwKICAgICAgICAgICAgImFpX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA"
    "4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25f"
    "aWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0g"
    "IiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUsCiAgICAgICAg"
    "ICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAi"
    "ZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJl"
    "Y29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbWl0OiBp"
    "bnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2VzX3ApWy1saW1p"
    "dDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShz"
    "ZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3Rl"
    "eHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2Vy"
    "X3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQg"
    "KyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5"
    "cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRf"
    "dHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRf"
    "dHlwZSwgdXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAg"
    "ICAgICAgICAgICAgIGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAg"
    "ICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAg"
    "ICAgICAgInBlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVj"
    "b3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5Ijog"
    "ICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAg"
    "ICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRz"
    "IjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAi"
    "Y29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFtIiwiaXNz"
    "dWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0K"
    "CiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAg"
    "ICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBk"
    "ZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAg"
    "ICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0dXJucyB1cCB0byBgbGlt"
    "aXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8g"
    "bW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFk"
    "X2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJu"
    "IG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9"
    "MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRl"
    "bV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRs"
    "ZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVt"
    "LmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSks"
    "CiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGlt"
    "aXQ9NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJv"
    "b3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5n"
    "ZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3Jl"
    "ICs9IDQKICAgICAgICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAg"
    "ICAgICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAg"
    "aWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAg"
    "ICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAg"
    "c2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAg"
    "ICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0"
    "XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDAp"
    "IC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3Jp"
    "ZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBj"
    "b250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5"
    "LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRz"
    "ID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoK"
    "ICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1d"
    "IHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJy"
    "ZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAg"
    "ICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAg"
    "ICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNl"
    "bGYsIGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNf"
    "cClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAg"
    "IGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiBy"
    "ZWNlbnQ6CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVy"
    "biBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1"
    "cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3Ry"
    "LCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAg"
    "ICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIg"
    "ICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgibHNs"
    "IikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAg"
    "IGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlm"
    "ZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRh"
    "Z3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAgICAg"
    "IGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0"
    "ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdz"
    "OgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAg"
    "ICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNl"
    "bGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlz"
    "dFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIg"
    "LV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0K"
    "CiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9"
    "IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToK"
    "ICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAg"
    "ICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAg"
    "cmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5"
    "IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpv"
    "aW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3Jk"
    "X3R5cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4o"
    "a2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlw"
    "ZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0i"
    "LnN0cmlwKCkgb3IgIklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVh"
    "bihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiBN"
    "ZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAg"
    "ICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgp"
    "WzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3Jk"
    "X3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90"
    "eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90"
    "eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiBy"
    "ZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1"
    "cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNz"
    "aW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmln"
    "aHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVhY2gg"
    "c2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAg"
    "IFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRo"
    "ZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRF"
    "UlZBTCA9IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2Rp"
    "ciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19k"
    "aXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRl"
    "LnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAj"
    "IOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBz"
    "dHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1"
    "aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwK"
    "ICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICBjb250ZW50LAogICAgICAg"
    "ICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0"
    "W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAg"
    "ICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAg"
    "cmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAg"
    "ICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Np"
    "c3RhbnQiKQogICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAg"
    "ICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2VsZikgLT4g"
    "aW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4g"
    "Tm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpz"
    "b25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBz"
    "aG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0"
    "ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0u"
    "anNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYu"
    "X21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAg"
    "ICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJk"
    "YXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhp"
    "c3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5f"
    "bWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdvcmRz"
    "KQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4g"
    "c2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2lu"
    "KHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAg"
    "ImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAog"
    "ICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYu"
    "X21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJd"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAi"
    "bGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAg"
    "ICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lv"
    "bnMiXVtpZHhdID0gZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwg"
    "ZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0g"
    "PSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAg"
    "TE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIi"
    "IlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9s"
    "b2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBz"
    "ZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBj"
    "b250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRo"
    "ZSBzeXN0ZW0gcHJvbXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNv"
    "bnRleHQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQu"
    "CiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nlc3Npb25fZGF0ZX0uanNvbmwi"
    "CiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9"
    "IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBs"
    "aW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZv"
    "bGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhp"
    "cyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3Qg"
    "MzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAg"
    "ICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdl"
    "dCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzox"
    "Nl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMu"
    "YXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9s"
    "b2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBw"
    "cm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1"
    "cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIs"
    "IG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVy"
    "bnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVu"
    "dHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToK"
    "ICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZl"
    "X2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKU"
    "gOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYg"
    "bm90IHNlbGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgu"
    "cmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5k"
    "ZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFU"
    "QUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJh"
    "c2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAg"
    "ICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAg"
    "ICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNv"
    "bHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVs"
    "ZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBu"
    "b24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2Vs"
    "Zi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNl"
    "bGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAgc3Vt"
    "bWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9"
    "ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAg"
    "ICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAg"
    "IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAg"
    "Imxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAog"
    "ICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9y"
    "dWxlLAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAg"
    "ICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBu"
    "b3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0"
    "aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwg"
    "ZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06"
    "CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBx"
    "ID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFu"
    "ZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBs"
    "YW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAg"
    "ICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAg"
    "ICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVu"
    "Y2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAg"
    "ICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVm"
    "IGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAg"
    "IGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwo"
    "c2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVj"
    "b3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25s"
    "KHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAg"
    "IGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxk"
    "IGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rp"
    "b24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMg"
    "PSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdS"
    "SVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVu"
    "dHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAg"
    "ICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAg"
    "ICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFw"
    "cGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykK"
    "CiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJu"
    "IGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93"
    "ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVk"
    "X2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVs"
    "ZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBm"
    "cm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5f"
    "cGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAg"
    "ICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBp"
    "biBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRz"
    "LiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5h"
    "cnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNM"
    "IiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgICAgICAg"
    "ICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRleCB3aXRoICIKICAgICAg"
    "ICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTog"
    "Zm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxT"
    "TCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJs"
    "ZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlh"
    "bGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFs"
    "cyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRl"
    "IGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQg"
    "aW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxT"
    "TCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAg"
    "ICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAg"
    "ICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAg"
    "ICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBt"
    "eUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxT"
    "TCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlw"
    "dHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3Jp"
    "cHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBh"
    "cnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBm"
    "dWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNj"
    "cmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBz"
    "dW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChl"
    "bnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAg"
    "ICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VSIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgogICAgVGFz"
    "ay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25s"
    "CgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgx"
    "bWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxj"
    "YW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0"
    "X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywg"
    "bWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1"
    "ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291"
    "bmQgKyBBSSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNu"
    "b296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "Zik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA"
    "4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlz"
    "dFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UK"
    "ICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5z"
    "dGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0Ogog"
    "ICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAg"
    "IGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVf"
    "YXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAg"
    "IGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAgICJwZW5kaW5nIikK"
    "ICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0"
    "KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIs"
    "Tm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5z"
    "ZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic291cmNlIiwg"
    "ICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAg"
    "ICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRk"
    "ZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAg"
    "ICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAg"
    "ICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAg"
    "ZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBw"
    "cmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHBy"
    "ZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAg"
    "ICAgICAgICBub3JtYWxpemVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNl"
    "bGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoK"
    "ICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9"
    "ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0"
    "YXNrID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIs"
    "CiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0Ijog"
    "ICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmlnZ2Vy"
    "IjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAg"
    "ICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAg"
    "ImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAgICAg"
    "ICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAg"
    "ICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwK"
    "ICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJw"
    "ZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAgICAgdGFza3MgPSBz"
    "ZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQog"
    "ICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0"
    "ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToK"
    "ICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0"
    "LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAg"
    "ICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25v"
    "d19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0"
    "XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBp"
    "ZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxl"
    "dGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAg"
    "ICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgog"
    "ICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2Vs"
    "Zi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tf"
    "aWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0"
    "WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNr"
    "cykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVk"
    "KHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3Qg"
    "Zm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVk"
    "IiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVt"
    "b3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgoKICAgICMg4pSA"
    "4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAg"
    "ICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgICAg"
    "ICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIg"
    "fCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAg"
    "ICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAg"
    "ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAg"
    "ZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAg"
    "ICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAg"
    "ICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5f"
    "cGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2Fs"
    "KHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2su"
    "Z2V0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQo"
    "ImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0dXMgPT0g"
    "InBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQgbm90IHRhc2suZ2V0KCJw"
    "cmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAg"
    "ICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAg"
    "ICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBub3cg"
    "Pj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAg"
    "ICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1si"
    "YWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSAr"
    "IHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAg"
    "ICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwog"
    "ICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAg"
    "ICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5l"
    "eHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1l"
    "ZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAg"
    "ICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQog"
    "ICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93"
    "ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAg"
    "ICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkp"
    "ICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAg"
    "ICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3co"
    "KS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNw"
    "ZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAgICAg"
    "ICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAg"
    "ICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRz"
    "CgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAg"
    "IiIiUGFyc2UgSVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIKICAgICAg"
    "ICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQog"
    "ICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJl"
    "dHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3Ry"
    "KSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1l"
    "ci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIi"
    "IgogICAgICAgIGltcG9ydCByZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBj"
    "bGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19O"
    "QU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAg"
    "ICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJc"
    "YnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICBy"
    "Ilxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIs"
    "IHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccyth"
    "KT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJtXGIi"
    "LCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xi"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFz"
    "a1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAg"
    "aW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNo"
    "KHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJyZW1pbmRlciIKICAgICAg"
    "ICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0g"
    "InRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVu"
    "dCI6IGludGVudCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9k"
    "dWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2Ug"
    "bmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAgICAgSGFuZGxlczogImluIDMw"
    "IG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAi"
    "YXQgMTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRl"
    "eHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5z"
    "ZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwK"
    "ICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgx"
    "KSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBu"
    "b3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6"
    "IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBu"
    "b3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVk"
    "ZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5z"
    "ZWFyY2goCiAgICAgICAgICAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAg"
    "ICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAg"
    "ICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBtLmdyb3Vw"
    "KDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0g"
    "PT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0"
    "ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgICAg"
    "IGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJvdyBhdCAu"
    "Li4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAg"
    "ICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3Vs"
    "dCA9IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAgcmV0dXJuIE5vbmUK"
    "CgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBO"
    "b25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBy"
    "dW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAi"
    "IiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVt"
    "ZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAoj"
    "IE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxs"
    "IC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9z"
    "YXZlLCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sg"
    "KFdBViArIE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoK"
    "IyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMK"
    "cmVxdWVzdHMKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBsb2NhbCBI"
    "dWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFs"
    "IChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndyaXRl"
    "X3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxs"
    "IGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVu"
    "dHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMg"
    "KFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFNlbGZUYWIsIERpYWdub3N0aWNzVGFiKQoKCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA1OiBUQUIgQ09OVEVOVCBDTEFTU0VTCiMK"
    "IyBUYWJzIGRlZmluZWQgaGVyZToKIyAgIFNMU2NhbnNUYWIgICAgICDigJQgZ3JpbW9pcmUtY2FyZCBzdHlsZSwgcmVidWls"
    "dCAoRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsCiMgICAgICAgICAgICAgICAgICAgICBwYXJzZXIgZml4ZWQsIGNvcHkt"
    "dG8tY2xpcGJvYXJkIHBlciBpdGVtKQojICAgU0xDb21tYW5kc1RhYiAgIOKAlCBnb3RoaWMgdGFibGUsIGNvcHkgY29tbWFu"
    "ZCB0byBjbGlwYm9hcmQKIyAgIEpvYlRyYWNrZXJUYWIgICDigJQgZnVsbCByZWJ1aWxkIGZyb20gc3BlYywgQ1NWL1RTViBl"
    "eHBvcnQKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRsZSBuYXJyYXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdu"
    "b3N0aWNzVGFiICDigJQgbG9ndXJ1IG91dHB1dCArIGhhcmR3YXJlIHJlcG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMg"
    "ICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMgX3JlCgoKIyDilIDilIAgU0hBUkVEIEdPVEhJQyBUQUJMRSBTVFlM"
    "RSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAtPiBzdHI6CiAgICByZXR1cm4gZiIiIgogICAgICAgIFFUYWJsZVdp"
    "ZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAg"
    "ICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgZ3JpZGxpbmUtY29sb3I6"
    "IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZv"
    "bnQtc2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgICAg"
    "ICAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAg"
    "ICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6"
    "IHtDX0JHM307CiAgICAgICAgfX0KICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdo"
    "dDogYm9sZDsKICAgICAgICAgICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhp"
    "Y19idG4odGV4dDogc3RyLCB0b29sdGlwOiBzdHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRv"
    "bih0ZXh0KQogICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNv"
    "bG9yOiB7Q19HT0xEfTsgIgogICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6"
    "IDJweDsgIgogICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAg"
    "ICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogNHB4IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAg"
    "KQogICAgaWYgdG9vbHRpcDoKICAgICAgICBidG4uc2V0VG9vbFRpcCh0b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9z"
    "ZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgog"
    "ICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAg"
    "ICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBhdmF0YXIgc2Nhbm5l"
    "ciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZyb20gc3BlYzoKICAgICAgLSBDYXJkL2dyaW1vaXJlLWVudHJ5IHN0"
    "eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGltZXN0YW1wLWF3YXJlIHBhcnNlcikKICAgICAgLSBEaXNwbGF5IChj"
    "bGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRlc2NyaXB0aW9uLCBpbmRpdmlk"
    "dWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBhcnNl"
    "ICh3YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAgIC0gQ29weS10by1j"
    "bGlwYm9hcmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNm"
    "Z19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQog"
    "ICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkK"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0g"
    "UVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJv"
    "b3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2FkZCAgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAg"
    "ICAgIHNlbGYuX2J0bl9kaXNwbGF5ID0gX2dvdGhpY19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBk"
    "ZXRhaWxzIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNl"
    "bGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRl"
    "bGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFy"
    "c2UiLCJSZS1wYXJzZSByYXcgdGV4dCBvZiBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAgICAgICBzZWxmLl9idG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "c2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5"
    "KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxm"
    "Ll9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fcmVwYXJzZSkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5f"
    "YnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYuX2J0bl9tb2RpZnksCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0"
    "bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJhci5h"
    "ZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgICMgU3RhY2s6IGxpc3QgdmlldyB8IGFk"
    "ZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4gbGlzdCAoZ3Jp"
    "bW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAgICAg"
    "ICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbCA9IFFTY3JvbGxB"
    "cmVhKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9j"
    "YXJkX3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAg"
    "c2VsZi5fY2FyZF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94TGF5"
    "b3V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xh"
    "eW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWlu"
    "ZXIpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2NhcmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdl"
    "dChwMCkKCiAgICAgICAgIyDilIDilIAgUEFHRSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQo"
    "cDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBTQ0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAg"
    "ICAgc2VsZi5fYWRkX25hbWUgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRl"
    "eHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkK"
    "ICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9hZGRf"
    "ZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLnNldE1heGltdW1IZWlnaHQoNjApCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBSQVcg"
    "U0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAgIHNlbGYuX2FkZF9yYXcgICA9IFFUZXh0RWRpdCgpCiAgICAgICAg"
    "c2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJQYXN0ZSB0aGUgcmF3IFNlY29uZCBMaWZl"
    "IHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3XSB3aWxsIGJlIHVzZWQg"
    "dG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAgICApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9yYXcs"
    "IDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBpdGVtcwogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0gUVRhYmxlV2lkZ2V0KDAs"
    "IDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRv"
    "ciJdKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgK"
    "ICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVz"
    "aXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAgICAg"
    "IHNlbGYuX2FkZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdp"
    "ZGdldChzZWxmLl9hZGRfcHJldmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5f"
    "cHJldmlld19wYXJzZSkKCiAgICAgICAgYnRuczEgPSBRSEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi"
    "4pymIFNhdmUiKTsgYzEgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2FkZCkKICAgICAgICBjMS5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5k"
    "ZXgoMCkpCiAgICAgICAgYnRuczEuYWRkV2lkZ2V0KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRj"
    "aCgpCiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0bnMxKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAg"
    "ICAgIyDilIDilIAgUEFHRSAyOiBkaXNwbGF5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAg"
    "ICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkK"
    "ICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklH"
    "SFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYyAgPSBRTGFiZWwoKQogICAgICAg"
    "IHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikK"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkK"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAg"
    "ICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpv"
    "bnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2Rl"
    "LlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkK"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5Db250ZXh0TWVu"
    "dVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVx"
    "dWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRXaWRn"
    "ZXQoc2VsZi5fZGlzcF9uYW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KHNlbGYuX2Rpc3BfdGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55"
    "IGl0ZW0gdG8gY29weSBpdCB0byBjbGlwYm9hcmQuIikKICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsiCiAgICAgICAgKQogICAgICAgIGwyLmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNf"
    "YnRuKCLil4AgQmFjayIpCiAgICAgICAgYmsyLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJl"
    "bnRJbmRleCgwKSkKICAgICAgICBsMi5hZGRXaWRnZXQoYmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikK"
    "CiAgICAgICAgIyDilIDilIAgUEFHRSAzOiBtb2RpZnkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAz"
    "KQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAg"
    "ICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTkFNRSIpKQogICAgICAgIHNlbGYuX21vZF9uYW1lID0gUUxp"
    "bmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX25hbWUpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0"
    "aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2MgPSBRTGluZUVkaXQoKQogICAgICAg"
    "IGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSVRF"
    "TVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAy"
    "KQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0p"
    "CiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAg"
    "ICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9u"
    "dGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "U3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAg"
    "ICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgczMgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAg"
    "ICAgczMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChs"
    "YW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBidG5z"
    "My5hZGRXaWRnZXQoYzMpOyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAg"
    "c2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtk"
    "aWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBp"
    "dGVtcykuCgogICAgICAgIEtFWSBGSVg6IEJlZm9yZSBzcGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkg"
    "W0hIOk1NXQogICAgICAgIHRpbWVzdGFtcCBzbyBzaW5nbGUtbGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAg"
    "IEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzExOjQ3XSBBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgog"
    "ICAgICAgICAgICBbMTE6NDddIC46IEl0ZW0gTmFtZSBbQXR0YWNobWVudF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3"
    "XSAuLi4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgcmF3LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9X"
    "TiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTogbm9ybWFsaXplIOKAlCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIHRp"
    "bWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbm9ybWFsaXplZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9"
    "OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAgIGxpbmVzID0gW2wuc3RyaXAoKSBmb3IgbCBpbiBub3JtYWxpemVk"
    "LnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMjogZXh0cmFjdCBhdmF0YXIgbmFt"
    "ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFtZSA9ICJVTktOT1dOIgogICAgICAgIGZvciBs"
    "aW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBvciBzaW1pbGFy"
    "CiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgciIoXHdbXHdcc10rPyknc1xzK3B1YmxpY1xz"
    "K2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYg"
    "bToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBicmVh"
    "awoKICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAj"
    "IFN0cmlwIGxlYWRpbmcgdGltZXN0YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpcZHsy"
    "fVxdXHMqJywgJycsIGxpbmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgICAgICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNo"
    "bWVudHMiIGluIGNvbnRlbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRl"
    "bnQubG93ZXIoKS5zdGFydHN3aXRoKCJvYmplY3QiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMg"
    "U2tpcCBkaXZpZGVyIGxpbmVzIOKAlCBsaW5lcyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAg"
    "ICAgICAgICAjIGUuZy4g4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkCBvciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAg"
    "c3RyaXBwZWQgPSBjb250ZW50LnN0cmlwKCIuOiAiKQogICAgICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJp"
    "cHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250aW51ZSAgIyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlk"
    "ZXIgbGluZQoKICAgICAgICAgICAgIyBUcnkgdG8gZXh0cmFjdCBDUkVBVE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9y"
    "ID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2gg"
    "PSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidDUkVBVE9SOlxzKihbXHdcc10rPykoPzpccypcW3wkKScsIGNvbnRl"
    "bnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgY3JlYXRvcl9tYXRjaDoKICAgICAgICAgICAgICAgIGNy"
    "ZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSkuc3RyaXAoKQogICAgICAgICAgICAgICAgaXRlbV9uYW1lID0gY29u"
    "dGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJpcCgpCgogICAgICAgICAgICAjIFN0cmlwIGF0dGFjaG1lbnQgcG9p"
    "bnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBpdGVtX25hbWUgPSBfcmUuc3ViKHInXHMqXFtbXHdc"
    "c19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBpdGVtX25hbWUgPSBpdGVtX25hbWUuc3RyaXAo"
    "Ii46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUgYW5kIGxlbihpdGVtX25hbWUpID4gMToKICAgICAgICAgICAgICAg"
    "IGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUsICJjcmVhdG9yIjogY3JlYXRvcn0pCgogICAgICAgIHJldHVybiBh"
    "dmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfY2FyZHMoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUg"
    "c2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtl"
    "QXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRl"
    "TGF0ZXIoKQoKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtl"
    "X2NhcmQocmVjKQogICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9jYXJkX2xheW91dC5jb3VudCgpIC0gMSwgY2FyZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2Vs"
    "ZiwgcmVjOiBkaWN0KSAtPiBRV2lkZ2V0OgogICAgICAgIGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0g"
    "cmVjLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEwYTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAg"
    "ICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9"
    "IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAg"
    "ICBuYW1lX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJuYW1lIiwgIlVOS05PV04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGNvdW50ID0gbGVuKHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAg"
    "ICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0gaXRlbXMiKQogICAgICAgIGNvdW50X2xibC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJsID0gUUxhYmVsKHJlYy5nZXQoImNyZWF0ZWRfYXQi"
    "LCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhU"
    "X0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgicmVj"
    "b3JkX2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJlY19pZDogc2VsZi5f"
    "c2VsZWN0X2NhcmQocmlkKQogICAgICAgIHJldHVybiBjYXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRf"
    "aWQ6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1"
    "aWxkX2NhcmRzKCkgICMgUmVidWlsZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVkX3Jl"
    "Y29yZChzZWxmKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIg"
    "aW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lk"
    "KSwKICAgICAgICAgICAgTm9uZQogICAgICAgICkKCiAgICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxm"
    "Ll9wYXRoKQogICAgICAgICMgRW5zdXJlIHJlY29yZF9pZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UK"
    "ICAgICAgICBmb3IgciBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgog"
    "ICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSByLmdldCgiaWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAg"
    "ICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5z"
    "ZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZpZXdfcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgPSBz"
    "ZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJh"
    "dykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQobmFtZSkKICAgICAgICBzZWxmLl9hZGRfcHJl"
    "dmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiBpdGVtc1s6MjBdOiAgIyBwcmV2aWV3IGZpcnN0IDIwCiAg"
    "ICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0"
    "ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMSwgUVRhYmxlV2lkZ2V0"
    "SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3Nob3dfYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYWRk"
    "X25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBm"
    "cm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuY2xl"
    "YXIoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3Vy"
    "cmVudEluZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jh"
    "dy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAg"
    "b3ZlcnJpZGVfbmFtZSA9IHNlbGYuX2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5v"
    "dyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAg"
    "ICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAg"
    "ICAgICAgICJuYW1lIjogICAgICAgIG92ZXJyaWRlX25hbWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjog"
    "c2VsZi5fYWRkX2Rlc2MudG9QbGFpblRleHQoKVs6MjQ0XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAg"
    "ICAgICAgICAgICJyYXdfdGV4dCI6ICAgIHJhdywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAg"
    "ICAidXBkYXRlZF9hdCI6ICBub3csCiAgICAgICAgfQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAg"
    "ICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0g"
    "cmVjb3JkWyJyZWNvcmRfaWQiXQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAg"
    "ICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRpc3BsYXkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIHNlbGYuX2Rpc3BfZGVz"
    "Yy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3Vu"
    "dCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fZGlzcF90"
    "YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNl"
    "bGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0"
    "ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRh"
    "YmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJl"
    "bnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0X21lbnUoc2VsZiwgcG9zKSAtPiBOb25lOgogICAgICAgIGlkeCA9"
    "IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1ZhbGlkKCk6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IKICAg"
    "ICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVhdG9yICAgID0gKHNl"
    "bGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDEpIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJ"
    "dGVtKCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51"
    "ID0gUU1lbnUoc2VsZikKICAgICAgICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19"
    "OyIKICAgICAgICApCiAgICAgICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAg"
    "ICBhX2NyZWF0b3IgPSBtZW51LmFkZEFjdGlvbigiQ29weSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFk"
    "ZEFjdGlvbigiQ29weSBCb3RoIikKICAgICAgICBhY3Rpb24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9y"
    "dCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBh"
    "Y3Rpb24gPT0gYV9pdGVtOiAgICBjYi5zZXRUZXh0KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0"
    "b3I6IGNiLnNldFRleHQoY3JlYXRvcikKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0"
    "ZW1fdGV4dH0g4oCUIHtjcmVhdG9yfSIpCgogICAgZGVmIF9zaG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3gu"
    "aW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVj"
    "dCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQo"
    "cmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24i"
    "LCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgi"
    "aXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFi"
    "bGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktO"
    "T1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgzKQoKICAgIGRlZiBfZG9fbW9kaWZ5X3NhdmUo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYuX21vZF9uYW1lLnRleHQoKS5z"
    "dHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQoKVs6"
    "MjQ0XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFibGUucm93Q291bnQo"
    "KSk6CiAgICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIp"
    "KS50ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRl"
    "bSgiIikpLnRleHQoKQogICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9XTiIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAg"
    "cmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6"
    "b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAg"
    "ICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxm"
    "Ll9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0"
    "aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2Fu"
    "IHRvIGRlbGV0ZS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2Nh"
    "biIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2Fu"
    "IiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IFRoaXMgY2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBR"
    "TWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkK"
    "ICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3Jl"
    "Y29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgci5nZXQo"
    "InJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IE5vbmUKICAgICAgICAgICAgc2VsZi5yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9y"
    "ZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJT"
    "TCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIHJlLXBhcnNl"
    "LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJhdyA9IHJlYy5nZXQoInJhd190ZXh0IiwiIikKICAgICAgICBpZiBu"
    "b3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2UiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlzIHNjYW4uIikKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVjWyJp"
    "dGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0gb3IgbmFtZQogICAg"
    "ICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3"
    "cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1l"
    "c3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJGb3VuZCB7bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMQ29tbWFuZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZl"
    "IGNvbW1hbmQgcmVmZXJlbmNlIHRhYmxlLgogICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlw"
    "Ym9hcmQgYnV0dG9uIHBlciByb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJz"
    "bF9jb21tYW5kcy5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9z"
    "ZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkK"
    "ICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0"
    "bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRu"
    "KCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0bigi4qeJIENvcHkgQ29tbWFuZCIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxlY3RlZCBjb21tYW5kIHRvIGNsaXBib2FyZCIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2NvcHlfY29tbWFuZCkKICAgICAgICBzZWxmLl9idG5f"
    "cmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBz"
    "ZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwgc2Vs"
    "Zi5fYnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAg"
    "MCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIo"
    "KS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5T"
    "ZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3Jz"
    "KFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxl"
    "Y3QgYSByb3cgYW5kIGNsaWNrIOKniSBDb3B5IENvbW1hbmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAg"
    "ICAgICkKICAgICAgICBoaW50LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFk"
    "ZFdpZGdldChoaW50KQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJl"
    "YWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMg"
    "aW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2Vs"
    "Zi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAg"
    "ICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29tbWFuZCIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0"
    "SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKSkK"
    "CiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRS"
    "b3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW0gPSBzZWxmLl90YWJsZS5p"
    "dGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4"
    "dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2Vs"
    "ZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcp"
    "CiAgICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3JtLmFkZFJvdygiQ29t"
    "bWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIp"
    "CiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkK"
    "ICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMp"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9"
    "IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAg"
    "ICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21k"
    "LnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAo"
    "KVs6MjQ0XSwKICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAg"
    "ICAgIH0KICAgICAgICAgICAgaWYgcmVjWyJjb21tYW5kIl06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVu"
    "ZChyZWMpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNl"
    "bGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxv"
    "ZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kaWZ5IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHls"
    "ZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5"
    "b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbW1hbmQiLCIiKSkKICAgICAgICBkZXNjID0g"
    "UUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21k"
    "KQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9r"
    "LmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRu"
    "cy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlm"
    "IGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZWNbImNvbW1hbmQiXSAg"
    "ICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50ZXh0"
    "KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAg"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0g"
    "c2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMp"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhp"
    "cyBjb21tYW5kIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVs"
    "ZXRlIiwgZiJEZWxldGUgJ3tjbWR9Jz8iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBR"
    "TWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5T"
    "dGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVf"
    "anNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBK"
    "T0IgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdp"
    "ZGdldCk6CiAgICAiIiIKICAgIEpvYiBhcHBsaWNhdGlvbiB0cmFja2luZy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAg"
    "IEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxlLCBEYXRlIEFwcGxpZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0"
    "aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1YgYW5kIFRTViBleHBvcnQuCiAgICBIaWRkZW4gcm93cyA9IGNvbXBs"
    "ZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBqdXN0IG5vdCBzaG93bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBb"
    "IkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBwbGllZCIsCiAgICAgICAgICAgICAgICJMaW5rIiwgIlN0YXR1cyIs"
    "ICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiam9iX3RyYWNrZXIuanNv"
    "bmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBG"
    "YWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWko"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRz"
    "TWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2Rp"
    "ZnkgPSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhpY19idG4oIkFyY2hp"
    "dmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVk"
    "L3JlamVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5oaWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAgICBz"
    "ZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3Ro"
    "aWNfYnRuKCJTaG93IEFyY2hpdmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIp"
    "CgogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fYnRuX3RvZ2dsZSwgc2VsZi5fYnRuX2V4cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAg"
    "ICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90"
    "b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9oaWRkZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExh"
    "eW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoc2VsZi5DT0xVTU5TKQogICAgICAgIGhoID0gc2Vs"
    "Zi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgIyBDb21wYW55IGFuZCBKb2IgVGl0bGUgc3RyZXRjaAogICAg"
    "ICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBo"
    "aC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBEYXRl"
    "IEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgyLCAxMDApCiAg"
    "ICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVt"
    "bldpZHRoKDQsIDgwKQogICAgICAgICMgTm90ZXMgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "NSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhh"
    "dmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25N"
    "b2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5h"
    "ZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAg"
    "ICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIs"
    "IEZhbHNlKSkKICAgICAgICAgICAgaWYgaGlkZGVuIGFuZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJs"
    "ZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVzID0gIkFyY2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJz"
    "dGF0dXMiLCJBY3RpdmUiKQogICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIs"
    "IiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJk"
    "YXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgIHN0"
    "YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9y"
    "IGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAgICAgICAgICAgaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYp"
    "KQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAgICAgICAgICAgICAgICAgIGl0ZW0uc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIGMsIGl0ZW0pCiAgICAgICAg"
    "ICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVzZXIgZGF0YQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAgICAgICAgICBRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJlYykKICAgICAgICAgICAgKQoKICAgIGRlZiBfc2VsZWN0ZWRfaW5k"
    "aWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2Vs"
    "Zi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRlbS5y"
    "b3coKSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSByb3dfaXRlbS5kYXRhKFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "ICAgICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAgcmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9n"
    "KHNlbGYsIHJlYzogZGljdCA9IE5vbmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNlbGYp"
    "CiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0"
    "KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkK"
    "ICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQoKICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNv"
    "bXBhbnkiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRs"
    "ZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVu"
    "ZGFyUG9wdXAoVHJ1ZSkKICAgICAgICBkZS5zZXREaXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMg"
    "YW5kIHJlYy5nZXQoImRhdGVfYXBwbGllZCIpOgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVj"
    "WyJkYXRlX2FwcGxpZWQiXSwieXl5eS1NTS1kZCIpKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURh"
    "dGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMg"
    "ZWxzZSAiIikKICAgICAgICBzdGF0dXMgID0gUUxpbmVFZGl0KHJlYy5nZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMg"
    "ZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90ZXMgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBl"
    "bHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiQ29tcGFueToiLCBjb21wYW55"
    "KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAgICAgICAoIkRhdGUgQXBwbGllZDoiLCBkZSksICgiTGluazoiLCBs"
    "aW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzKSwgKCJOb3RlczoiLCBub3RlcyksCiAgICAgICAgXToKICAg"
    "ICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdldCkKCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tl"
    "ZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdp"
    "ZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCgogICAgICAgIGlmIGRsZy5l"
    "eGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAg"
    "ICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiam9iX3RpdGxlIjog"
    "ICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRvU3Ry"
    "aW5nKCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50ZXh0KCkuc3RyaXAoKSwK"
    "ICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICBzdGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAg"
    "ICAgICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAg"
    "cmV0dXJuIE5vbmUKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2coKQog"
    "ICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1"
    "aWQudXVpZDQoKSksCiAgICAgICAgICAgICJoaWRkZW4iOiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVk"
    "X2RhdGUiOiBOb25lLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0"
    "IjogICAgIG5vdywKICAgICAgICB9KQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihp"
    "ZHhzKSAhPSAxOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBleGFjdGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbaWR4c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFs"
    "b2cocmVjKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAgICAg"
    "ICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdy"
    "aXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAg"
    "ICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJo"
    "aWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJjb21wbGV0ZWRfZGF0"
    "ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XS5nZXQoImNvbXBsZXRlZF9kYXRlIikgb3IK"
    "ICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5kYXRlKCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAg"
    "IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVf"
    "anNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fdW5o"
    "aWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAg"
    "ICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlk"
    "ZGVuIl0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAog"
    "ICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGlj"
    "ZXMoKQogICAgICAgIGlmIG5vdCBpZHhzOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94"
    "LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0g"
    "c2VsZWN0ZWQgYXBwbGljYXRpb24ocyk/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3Rh"
    "bmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVw"
    "bHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciBpLCByIGluIGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJhZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwg"
    "c2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IG5vdCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNlbGYu"
    "X2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAgIuKYgCBIaWRlIEFyY2hpdmVkIiBpZiBzZWxmLl9zaG93X2hpZGRl"
    "biBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAgICApCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIGZpbHQgPSBRRmlsZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUo"
    "CiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRyYWNrZXIiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImV4cG9y"
    "dHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNTViBGaWxlcyAoKi5jc3YpOztUYWIgRGVsaW1pdGVk"
    "ICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWxp"
    "bSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRoKCIudHh0IikgZWxzZSAiLCIKICAgICAgICBoZWFkZXIgPSBbImNv"
    "bXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQiLCJsaW5rIiwKICAgICAgICAgICAgICAgICAgInN0YXR1cyIsImhp"
    "ZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRoLCAidyIsIGVuY29kaW5nPSJ1"
    "dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxuIikK"
    "ICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAg"
    "ICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxl"
    "IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAg"
    "ICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAgICAg"
    "ICAgICAgICAgICAgIHN0cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgiY29tcGxldGVkX2RhdGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIp"
    "LAogICAgICAgICAgICAgICAgXQogICAgICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAg"
    "ICAgIHN0cih2KS5yZXBsYWNlKCJcbiIsIiAiKS5yZXBsYWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3Ig"
    "diBpbiB2YWxzCiAgICAgICAgICAgICAgICApICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxm"
    "LCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKU"
    "gOKUgCBTRUxGIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgU2VsZlRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYSdzIGludGVybmFsIGRpYWxvZ3VlIHNwYWNlLgogICAg"
    "UmVjZWl2ZXM6IGlkbGUgbmFycmF0aXZlIG91dHB1dCwgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucywKICAgICAgICAgICAg"
    "ICBQb0kgbGlzdCBmcm9tIGRhaWx5IHJlZmxlY3Rpb24sIHVuYW5zd2VyZWQgcXVlc3Rpb24gZmxhZ3MsCiAgICAgICAgICAg"
    "ICAgam91cm5hbCBsb2FkIG5vdGlmaWNhdGlvbnMuCiAgICBSZWFkLW9ubHkgZGlzcGxheS4gU2VwYXJhdGUgZnJvbSBwZXJz"
    "b25hIGNoYXQgdGFiIGFsd2F5cy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9v"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRy"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIElOTkVSIFNBTkNUVU0g"
    "4oCUIHtERUNLX05BTUUudXBwZXIoKX0nUyBQUklWQVRFIFRIT1VHSFRTIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0g"
    "X2dvdGhpY19idG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAg"
    "ICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkK"
    "ICAgICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAg"
    "ICAgIHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRP"
    "Un07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BVUlBMRV9ESU19OyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5n"
    "OiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBhcHBl"
    "bmQoc2VsZiwgbGFiZWw6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgY29sb3JzID0gewogICAgICAgICAgICAiTkFSUkFUSVZFIjogIENf"
    "R09MRCwKICAgICAgICAgICAgIlJFRkxFQ1RJT04iOiBDX1BVUlBMRSwKICAgICAgICAgICAgIkpPVVJOQUwiOiAgICBDX1NJ"
    "TFZFUiwKICAgICAgICAgICAgIlBPSSI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAiU1lTVEVNIjogICAgIENf"
    "VEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gY29sb3JzLmdldChsYWJlbC51cHBlcigpLCBDX0dPTEQpCiAg"
    "ICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElN"
    "fTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBm"
    "JzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ+KdpyB7bGFi"
    "ZWx9PC9zcGFuPjxicj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3RleHR9PC9zcGFu"
    "PicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoIiIpCiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0"
    "aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCku"
    "bWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXku"
    "Y2xlYXIoKQoKCiMg4pSA4pSAIERJQUdOT1NUSUNTIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgRGlhZ25vc3RpY3NUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEJhY2tlbmQgZGlhZ25vc3RpY3MgZGlzcGxheS4KICAg"
    "IFJlY2VpdmVzOiBoYXJkd2FyZSBkZXRlY3Rpb24gcmVzdWx0cywgZGVwZW5kZW5jeSBjaGVjayByZXN1bHRzLAogICAgICAg"
    "ICAgICAgIEFQSSBlcnJvcnMsIHN5bmMgZmFpbHVyZXMsIHRpbWVyIGV2ZW50cywgam91cm5hbCBsb2FkIG5vdGljZXMsCiAg"
    "ICAgICAgICAgICAgbW9kZWwgbG9hZCBzdGF0dXMsIEdvb2dsZSBhdXRoIGV2ZW50cy4KICAgIEFsd2F5cyBzZXBhcmF0ZSBm"
    "cm9tIHBlcnNvbmEgY2hhdCB0YWIuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJv"
    "b3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhk"
    "ciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERJQUdOT1NUSUNTIOKA"
    "lCBTWVNURU0gJiBCQUNLRU5EIExPRyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xl"
    "YXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdl"
    "dChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0g"
    "UVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxh"
    "eS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfU0lMVkVS"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZh"
    "bWlseTogJ0NvdXJpZXIgTmV3JywgbW9ub3NwYWNlOyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBwYWRkaW5n"
    "OiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBsb2co"
    "c2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRh"
    "dGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgbGV2ZWxfY29sb3JzID0gewogICAgICAgICAgICAi"
    "SU5GTyI6ICBDX1NJTFZFUiwKICAgICAgICAgICAgIk9LIjogICAgQ19HUkVFTiwKICAgICAgICAgICAgIldBUk4iOiAgQ19H"
    "T0xELAogICAgICAgICAgICAiRVJST1IiOiBDX0JMT09ELAogICAgICAgICAgICAiREVCVUciOiBDX1RFWFRfRElNLAogICAg"
    "ICAgIH0KICAgICAgICBjb2xvciA9IGxldmVsX2NvbG9ycy5nZXQobGV2ZWwudXBwZXIoKSwgQ19TSUxWRVIpCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsiPlt7"
    "dGltZXN0YW1wfV08L3NwYW4+ICcKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnttZXNzYWdl"
    "fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgK"
    "ICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBk"
    "ZWYgbG9nX21hbnkoc2VsZiwgbWVzc2FnZXM6IGxpc3Rbc3RyXSwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAg"
    "ICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzOgogICAgICAgICAgICBsdmwgPSBsZXZlbAogICAgICAgICAgICBpZiAi4pyTIiBp"
    "biBtc2c6ICAgIGx2bCA9ICJPSyIKICAgICAgICAgICAgZWxpZiAi4pyXIiBpbiBtc2c6ICBsdmwgPSAiV0FSTiIKICAgICAg"
    "ICAgICAgZWxpZiAiRVJST1IiIGluIG1zZy51cHBlcigpOiBsdmwgPSAiRVJST1IiCiAgICAgICAgICAgIHNlbGYubG9nKG1z"
    "ZywgbHZsKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg"
    "4pSA4pSAIExFU1NPTlMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBM"
    "ZXNzb25zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYW5kIGNvZGUgbGVzc29ucyBi"
    "cm93c2VyLgogICAgQWRkLCB2aWV3LCBzZWFyY2gsIGRlbGV0ZSBsZXNzb25zLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIGRiOiAiTGVzc29uc0xlYXJuZWREQiIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBzZWxmLl9kYiA9IGRiCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgog"
    "ICAgICAgICMgRmlsdGVyIGJhcgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fc2Vh"
    "cmNoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9zZWFyY2guc2V0UGxhY2Vob2xkZXJUZXh0KCJTZWFyY2ggbGVzc29u"
    "cy4uLiIpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIgPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVy"
    "LmFkZEl0ZW1zKFsiQWxsIiwgIkxTTCIsICJQeXRob24iLCAiUHlTaWRlNiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAiSmF2YVNjcmlwdCIsICJPdGhlciJdKQogICAgICAgIHNlbGYuX3NlYXJjaC50ZXh0Q2hhbmdlZC5jb25u"
    "ZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChz"
    "ZWxmLnJlZnJlc2gpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJTZWFyY2g6IikpCiAgICAgICAgZmls"
    "dGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VhcmNoLCAxKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgi"
    "TGFuZ3VhZ2U6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fbGFuZ19maWx0ZXIpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fYWRk"
    "ID0gX2dvdGhpY19idG4oIuKcpiBBZGQgTGVzc29uIikKICAgICAgICBidG5fZGVsID0gX2dvdGhpY19idG4oIuKclyBEZWxl"
    "dGUiKQogICAgICAgIGJ0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBidG5fZGVsLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2FkZCkKICAgICAgICBi"
    "dG5fYmFyLmFkZFdpZGdldChidG5fZGVsKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKAogICAgICAgICAgICBbIkxhbmd1YWdlIiwgIlJlZmVyZW5jZSBLZXki"
    "LCAiU3VtbWFyeSIsICJFbnZpcm9ubWVudCJdCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmll"
    "dy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29s"
    "b3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMg"
    "VXNlIHNwbGl0dGVyIGJldHdlZW4gdGFibGUgYW5kIGRldGFpbAogICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9y"
    "aWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBE"
    "ZXRhaWwgcGFuZWwKICAgICAgICBkZXRhaWxfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZGV0YWlsX2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwg"
    "MCwgMCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgZGV0YWlsX2hlYWRlciA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGVUxMIFJVTEUiKSkK"
    "ICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUgPSBfZ290aGlj"
    "X2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYu"
    "X2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS50b2dnbGVkLmNv"
    "bm5lY3Qoc2VsZi5fdG9nZ2xlX2VkaXRfbW9kZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlID0gX2dvdGhpY19idG4o"
    "IlNhdmUiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5f"
    "c2F2ZV9ydWxlLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fc2F2ZV9ydWxlX2VkaXQpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX2VkaXRfcnVs"
    "ZSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZV9ydWxlKQogICAgICAgIGRldGFpbF9s"
    "YXlvdXQuYWRkTGF5b3V0KGRldGFpbF9oZWFkZXIpCgogICAgICAgIHNlbGYuX2RldGFpbCA9IFFUZXh0RWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldE1pbmltdW1IZWlnaHQo"
    "MTIwKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAg"
    "ICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRw"
    "eDsiCiAgICAgICAgKQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RldGFpbCkKICAgICAgICBzcGxp"
    "dHRlci5hZGRXaWRnZXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMzAwLCAxODBdKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10K"
    "ICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdzogaW50ID0gLTEKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHEgICAgPSBzZWxmLl9zZWFyY2gudGV4dCgpCiAgICAgICAgbGFuZyA9IHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRU"
    "ZXh0KCkKICAgICAgICBsYW5nID0gIiIgaWYgbGFuZyA9PSAiQWxsIiBlbHNlIGxhbmcKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "ID0gc2VsZi5fZGIuc2VhcmNoKHF1ZXJ5PXEsIGxhbmd1YWdlPWxhbmcpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291"
    "bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dD"
    "b3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJ"
    "dGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImxhbmd1YWdlIiwiIikpKQogICAg"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoInJlZmVyZW5jZV9rZXkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAg"
    "ICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3VtbWFyeSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SXRlbShyLCAzLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJlbnZpcm9ubWVudCIsIiIp"
    "KSkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRS"
    "b3coKQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93ID0gcm93CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVj"
    "b3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0"
    "UGxhaW5UZXh0KAogICAgICAgICAgICAgICAgcmVjLmdldCgiZnVsbF9ydWxlIiwiIikgKyAiXG5cbiIgKwogICAgICAgICAg"
    "ICAgICAgKCJSZXNvbHV0aW9uOiAiICsgcmVjLmdldCgicmVzb2x1dGlvbiIsIiIpIGlmIHJlYy5nZXQoInJlc29sdXRpb24i"
    "KSBlbHNlICIiKQogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVzZXQgZWRpdCBtb2RlIG9uIG5ldyBzZWxlY3Rpb24K"
    "ICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQoKICAgIGRlZiBfdG9nZ2xlX2VkaXRf"
    "bW9kZShzZWxmLCBlZGl0aW5nOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShub3Qg"
    "ZWRpdGluZykKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2libGUoZWRpdGluZykKICAgICAgICBzZWxmLl9i"
    "dG5fZWRpdF9ydWxlLnNldFRleHQoIkNhbmNlbCIgaWYgZWRpdGluZyBlbHNlICJFZGl0IikKICAgICAgICBpZiBlZGl0aW5n"
    "OgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTERf"
    "RElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEx"
    "cHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAi"
    "CiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICMgUmVsb2FkIG9yaWdpbmFsIGNvbnRlbnQgb24gY2FuY2VsCiAgICAgICAgICAgIHNlbGYuX29u"
    "X3NlbGVjdCgpCgogICAgZGVmIF9zYXZlX3J1bGVfZWRpdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX2Vk"
    "aXRpbmdfcm93CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHRleHQgPSBz"
    "ZWxmLl9kZXRhaWwudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgICMgU3BsaXQgcmVzb2x1dGlvbiBiYWNrIG91"
    "dCBpZiBwcmVzZW50CiAgICAgICAgICAgIGlmICJcblxuUmVzb2x1dGlvbjogIiBpbiB0ZXh0OgogICAgICAgICAgICAgICAg"
    "cGFydHMgPSB0ZXh0LnNwbGl0KCJcblxuUmVzb2x1dGlvbjogIiwgMSkKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSBw"
    "YXJ0c1swXS5zdHJpcCgpCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gcGFydHNbMV0uc3RyaXAoKQogICAgICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHRleHQKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBz"
    "ZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJyZXNvbHV0aW9uIiwgIiIpCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XVsi"
    "ZnVsbF9ydWxlIl0gID0gZnVsbF9ydWxlCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XVsicmVzb2x1dGlvbiJdID0g"
    "cmVzb2x1dGlvbgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9kYi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAg"
    "ICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5z"
    "ZXRXaW5kb3dUaXRsZSgiQWRkIExlc3NvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgNDAwKQogICAgICAgIGZvcm0gPSBRRm9y"
    "bUxheW91dChkbGcpCiAgICAgICAgZW52ICA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICBsYW5nID0gUUxpbmVFZGl0KCJM"
    "U0wiKQogICAgICAgIHJlZiAgPSBRTGluZUVkaXQoKQogICAgICAgIHN1bW0gPSBRTGluZUVkaXQoKQogICAgICAgIHJ1bGUg"
    "PSBRVGV4dEVkaXQoKQogICAgICAgIHJ1bGUuc2V0TWF4aW11bUhlaWdodCgxMDApCiAgICAgICAgcmVzICA9IFFMaW5lRWRp"
    "dCgpCiAgICAgICAgbGluayA9IFFMaW5lRWRpdCgpCiAgICAgICAgZm9yIGxhYmVsLCB3IGluIFsKICAgICAgICAgICAgKCJF"
    "bnZpcm9ubWVudDoiLCBlbnYpLCAoIkxhbmd1YWdlOiIsIGxhbmcpLAogICAgICAgICAgICAoIlJlZmVyZW5jZSBLZXk6Iiwg"
    "cmVmKSwgKCJTdW1tYXJ5OiIsIHN1bW0pLAogICAgICAgICAgICAoIkZ1bGwgUnVsZToiLCBydWxlKSwgKCJSZXNvbHV0aW9u"
    "OiIsIHJlcyksCiAgICAgICAgICAgICgiTGluazoiLCBsaW5rKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJv"
    "dyhsYWJlbCwgdykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUi"
    "KTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4"
    "LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQo"
    "Y3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29k"
    "ZS5BY2NlcHRlZDoKICAgICAgICAgICAgc2VsZi5fZGIuYWRkKAogICAgICAgICAgICAgICAgZW52aXJvbm1lbnQ9ZW52LnRl"
    "eHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGFuZ3VhZ2U9bGFuZy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAg"
    "ICAgIHJlZmVyZW5jZV9rZXk9cmVmLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgc3VtbWFyeT1zdW1tLnRleHQo"
    "KS5zdHJpcCgpLAogICAgICAgICAgICAgICAgZnVsbF9ydWxlPXJ1bGUudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICAgICAgcmVzb2x1dGlvbj1yZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsaW5rPWxpbmsudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93"
    "IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWNfaWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJpZCIs"
    "IiIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRGVs"
    "ZXRlIExlc3NvbiIsCiAgICAgICAgICAgICAgICAiRGVsZXRlIHRoaXMgbGVzc29uPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAg"
    "ICAgICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlll"
    "czoKICAgICAgICAgICAgICAgIHNlbGYuX2RiLmRlbGV0ZShyZWNfaWQpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKCiMg4pSA4pSAIE1PRFVMRSBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kdWxlVHJh"
    "Y2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYWwgbW9kdWxlIHBpcGVsaW5lIHRyYWNrZXIuCiAgICBUcmFj"
    "ayBwbGFubmVkL2luLXByb2dyZXNzL2J1aWx0IG1vZHVsZXMgYXMgdGhleSBhcmUgZGVzaWduZWQuCiAgICBFYWNoIG1vZHVs"
    "ZSBoYXM6IE5hbWUsIFN0YXR1cywgRGVzY3JpcHRpb24sIE5vdGVzLgogICAgRXhwb3J0IHRvIFRYVCBmb3IgcGFzdGluZyBp"
    "bnRvIHNlc3Npb25zLgogICAgSW1wb3J0OiBwYXN0ZSBhIGZpbmFsaXplZCBzcGVjLCBpdCBwYXJzZXMgbmFtZSBhbmQgZGV0"
    "YWlscy4KICAgIFRoaXMgaXMgYSBkZXNpZ24gbm90ZWJvb2sg4oCUIG5vdCBjb25uZWN0ZWQgdG8gZGVja19idWlsZGVyJ3Mg"
    "TU9EVUxFIHJlZ2lzdHJ5LgogICAgIiIiCgogICAgU1RBVFVTRVMgPSBbIklkZWEiLCAiRGVzaWduaW5nIiwgIlJlYWR5IHRv"
    "IEJ1aWxkIiwgIlBhcnRpYWwiLCAiQnVpbHQiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8g"
    "Im1vZHVsZV90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNl"
    "bGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0"
    "LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBidG5fYmFyID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigiQWRkIE1vZHVsZSIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2VkaXQgICA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dv"
    "dGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNfYnRuKCJFeHBvcnQgVFhUIikK"
    "ICAgICAgICBzZWxmLl9idG5faW1wb3J0ID0gX2dvdGhpY19idG4oIkltcG9ydCBTcGVjIikKICAgICAgICBmb3IgYiBpbiAo"
    "c2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2VkaXQsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2J0bl9leHBvcnQsIHNlbGYuX2J0bl9pbXBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0aCg4MCkKICAgICAg"
    "ICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBidG5fYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJ0"
    "bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fYnRuX2Fk"
    "ZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9lZGl0LmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19lZGl0KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkK"
    "ICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgc2VsZi5f"
    "YnRuX2ltcG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faW1wb3J0KQoKICAgICAgICAjIFRhYmxlCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMykKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFi"
    "ZWxzKFsiTW9kdWxlIE5hbWUiLCAiU3RhdHVzIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5o"
    "b3Jpem9udGFsSGVhZGVyKCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDAsIDE2MCkKICAgICAgICBoaC5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENv"
    "bHVtbldpZHRoKDEsIDEwMCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0"
    "cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJu"
    "YXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkK"
    "CiAgICAgICAgIyBTcGxpdHRlcgogICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2Fs"
    "KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBOb3RlcyBwYW5lbAogICAgICAg"
    "IG5vdGVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIG5vdGVzX2xheW91dCA9IFFWQm94TGF5b3V0KG5vdGVzX3dpZGdl"
    "dCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgbm90ZXNfbGF5"
    "b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5PVEVT"
    "IikpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxh"
    "eS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0TWluaW11bUhlaWdodCgxMjApCiAg"
    "ICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAg"
    "ICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRw"
    "eDsiCiAgICAgICAgKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbm90ZXNfZGlzcGxheSkKICAgICAg"
    "ICBzcGxpdHRlci5hZGRXaWRnZXQobm90ZXNfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFsyNTAsIDE1MF0p"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgICMgQ291bnQgbGFiZWwKICAgICAgICBzZWxm"
    "Ll9jb3VudF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb3VudF9sYmwpCgogICAgZGVmIHJlZnJlc2go"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBy"
    "ID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoIm5hbWUiLCAiIikpKQogICAg"
    "ICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3RhdHVzIiwgIklkZWEiKSkKICAgICAg"
    "ICAgICAgIyBDb2xvciBieSBzdGF0dXMKICAgICAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgICAgICJJ"
    "ZGVhIjogICAgICAgICAgICAgQ19URVhUX0RJTSwKICAgICAgICAgICAgICAgICJEZXNpZ25pbmciOiAgICAgICAgQ19HT0xE"
    "X0RJTSwKICAgICAgICAgICAgICAgICJSZWFkeSB0byBCdWlsZCI6ICAgQ19QVVJQTEUsCiAgICAgICAgICAgICAgICAiUGFy"
    "dGlhbCI6ICAgICAgICAgICIjY2M4ODQ0IiwKICAgICAgICAgICAgICAgICJCdWlsdCI6ICAgICAgICAgICAgQ19HUkVFTiwK"
    "ICAgICAgICAgICAgfQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXRGb3JlZ3JvdW5kKAogICAgICAgICAgICAgICAgUUNv"
    "bG9yKHN0YXR1c19jb2xvcnMuZ2V0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSwgQ19URVhUX0RJTSkpCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlv"
    "biIsICIiKVs6ODBdKSkKICAgICAgICBjb3VudHMgPSB7fQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAg"
    "ICAgICAgICAgcyA9IHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikKICAgICAgICAgICAgY291bnRzW3NdID0gY291bnRzLmdl"
    "dChzLCAwKSArIDEKICAgICAgICBjb3VudF9zdHIgPSAiICAiLmpvaW4oZiJ7c306IHtufSIgZm9yIHMsIG4gaW4gY291bnRz"
    "Lml0ZW1zKCkpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFRleHQoCiAgICAgICAgICAgIGYiVG90YWw6IHtsZW4oc2Vs"
    "Zi5fcmVjb3Jkcyl9ICAge2NvdW50X3N0cn0iCiAgICAgICAgKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5f"
    "cmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBzZWxmLl9ub3Rlc19k"
    "aXNwbGF5LnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsICIiKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coKQoKICAgIGRlZiBfZG9fZWRpdChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29y"
    "ZHMpOgogICAgICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKHNlbGYuX3JlY29yZHNbcm93XSwgcm93KQoKICAgIGRl"
    "ZiBfb3Blbl9lZGl0X2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lLCByb3c6IGludCA9IC0xKSAtPiBOb25lOgogICAg"
    "ICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZHVsZSIgaWYgbm90IHJlYyBl"
    "bHNlIGYiRWRpdDoge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1NDAsIDQ0MCkKICAgICAgICBmb3Jt"
    "ID0gUVZCb3hMYXlvdXQoZGxnKQoKICAgICAgICBuYW1lX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5hbWUiLCIiKSBp"
    "ZiByZWMgZWxzZSAiIikKICAgICAgICBuYW1lX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiTW9kdWxlIG5hbWUiKQoKICAg"
    "ICAgICBzdGF0dXNfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHN0YXR1c19jb21iby5hZGRJdGVtcyhzZWxmLlNUQVRV"
    "U0VTKQogICAgICAgIGlmIHJlYzoKICAgICAgICAgICAgaWR4ID0gc3RhdHVzX2NvbWJvLmZpbmRUZXh0KHJlYy5nZXQoInN0"
    "YXR1cyIsIklkZWEiKSkKICAgICAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzdGF0dXNfY29tYm8uc2V0"
    "Q3VycmVudEluZGV4KGlkeCkKCiAgICAgICAgZGVzY19maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIs"
    "IiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRlc2NfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJPbmUtbGluZSBkZXNj"
    "cmlwdGlvbiIpCgogICAgICAgIG5vdGVzX2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFp"
    "blRleHQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFjZWhv"
    "bGRlclRleHQoCiAgICAgICAgICAgICJGdWxsIG5vdGVzIOKAlCBzcGVjLCBpZGVhcywgcmVxdWlyZW1lbnRzLCBlZGdlIGNh"
    "c2VzLi4uIgogICAgICAgICkKICAgICAgICBub3Rlc19maWVsZC5zZXRNaW5pbXVtSGVpZ2h0KDIwMCkKCiAgICAgICAgZm9y"
    "IGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIk5hbWU6IiwgbmFtZV9maWVsZCksCiAgICAgICAgICAgICgiU3Rh"
    "dHVzOiIsIHN0YXR1c19jb21ibyksCiAgICAgICAgICAgICgiRGVzY3JpcHRpb246IiwgZGVzY19maWVsZCksCiAgICAgICAg"
    "ICAgICgiTm90ZXM6Iiwgbm90ZXNfZmllbGQpLAogICAgICAgIF06CiAgICAgICAgICAgIHJvd19sYXlvdXQgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICAgICAgbGJsLnNldEZpeGVkV2lkdGgoOTAp"
    "CiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRnZXQo"
    "d2lkZ2V0KQogICAgICAgICAgICBmb3JtLmFkZExheW91dChyb3dfbGF5b3V0KQoKICAgICAgICBidG5fcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGJ0bl9zYXZlICAgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9n"
    "b3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAg"
    "IGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX3Nh"
    "dmUpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBmb3JtLmFkZExheW91dChidG5fcm93"
    "KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbmV3"
    "X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHJlYy5nZXQoImlkIiwgc3RyKHV1aWQudXVpZDQoKSkp"
    "IGlmIHJlYyBlbHNlIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZV9maWVs"
    "ZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgIHN0YXR1c19jb21iby5jdXJyZW50VGV4"
    "dCgpLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzY19maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgICJub3RlcyI6ICAgICAgIG5vdGVzX2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAg"
    "ICJjcmVhdGVkIjogICAgIHJlYy5nZXQoImNyZWF0ZWQiLCBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSkgaWYgcmVjIGVs"
    "c2UgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5u"
    "b3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByb3cgPj0gMDoKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3JlY29yZHNbcm93XSA9IG5ld19yZWMKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3Jl"
    "Y29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMp"
    "CiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBy"
    "b3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToK"
    "ICAgICAgICAgICAgbmFtZSA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoIm5hbWUiLCJ0aGlzIG1vZHVsZSIpCiAgICAgICAg"
    "ICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRGVsZXRlIE1vZHVsZSIs"
    "CiAgICAgICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAg"
    "UU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxm"
    "Ll9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAg"
    "ICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBm"
    "Im1vZHVsZXNfe3RzfS50eHQiCiAgICAgICAgICAgIGxpbmVzID0gWwogICAgICAgICAgICAgICAgIkVDSE8gREVDSyDigJQg"
    "TU9EVUxFIFRSQUNLRVIgRVhQT1JUIiwKICAgICAgICAgICAgICAgIGYiRXhwb3J0ZWQ6IHtkYXRldGltZS5ub3coKS5zdHJm"
    "dGltZSgnJVktJW0tJWQgJUg6JU06JVMnKX0iLAogICAgICAgICAgICAgICAgZiJUb3RhbCBtb2R1bGVzOiB7bGVuKHNlbGYu"
    "X3JlY29yZHMpfSIsCiAgICAgICAgICAgICAgICAiPSIgKiA2MCwKICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICBd"
    "CiAgICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgICAgIGxpbmVzLmV4dGVuZChbCiAg"
    "ICAgICAgICAgICAgICAgICAgZiJNT0RVTEU6IHtyZWMuZ2V0KCduYW1lJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBm"
    "IlN0YXR1czoge3JlYy5nZXQoJ3N0YXR1cycsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJEZXNjcmlwdGlvbjoge3Jl"
    "Yy5nZXQoJ2Rlc2NyaXB0aW9uJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAi"
    "Tm90ZXM6IiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgICAgICIi"
    "LAogICAgICAgICAgICAgICAgICAgICItIiAqIDQwLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAg"
    "XSkKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCgiXG4iLmpvaW4obGluZXMpLCBlbmNvZGluZz0idXRmLTgiKQog"
    "ICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dCgiXG4iLmpvaW4obGluZXMpKQogICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAg"
    "ICAgICBmIk1vZHVsZSB0cmFja2VyIGV4cG9ydGVkIHRvOlxue291dF9wYXRofVxuXG5BbHNvIGNvcGllZCB0byBjbGlwYm9h"
    "cmQuIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC53YXJuaW5nKHNlbGYsICJFeHBvcnQgRXJyb3IiLCBzdHIoZSkpCgoKCiAgICBkZWYgX3BhcnNlX2ltcG9ydF9lbnRyaWVz"
    "KHNlbGYsIHJhdzogc3RyKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlBhcnNlIGltcG9ydGVkIHRleHQgaW50byBvbmUg"
    "b3IgbW9yZSBtb2R1bGUgcmVjb3Jkcy4iIiIKICAgICAgICBsYWJlbF9tYXAgPSB7CiAgICAgICAgICAgICJtb2R1bGUiOiAi"
    "bmFtZSIsCiAgICAgICAgICAgICJzdGF0dXMiOiAic3RhdHVzIiwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogImRlc2Ny"
    "aXB0aW9uIiwKICAgICAgICAgICAgIm5vdGVzIjogIm5vdGVzIiwKICAgICAgICAgICAgImZ1bGwgc3VtbWFyeSI6ICJub3Rl"
    "cyIsCiAgICAgICAgfQoKICAgICAgICBkZWYgX2JsYW5rKCkgLT4gZGljdDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAg"
    "ICAgICAgICAgICJuYW1lIjogIiIsCiAgICAgICAgICAgICAgICAic3RhdHVzIjogIklkZWEiLAogICAgICAgICAgICAgICAg"
    "ImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAgICAgfQoKICAgICAgICBk"
    "ZWYgX2NsZWFuKHJlYzogZGljdCkgLT4gZGljdDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJuYW1l"
    "IjogcmVjLmdldCgibmFtZSIsICIiKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6IChyZWMuZ2V0KCJzdGF0"
    "dXMiLCAiIikuc3RyaXAoKSBvciAiSWRlYSIpLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogcmVjLmdldCgiZGVz"
    "Y3JpcHRpb24iLCAiIikuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3RlcyI6IHJlYy5nZXQoIm5vdGVzIiwgIiIpLnN0"
    "cmlwKCksCiAgICAgICAgICAgIH0KCiAgICAgICAgZGVmIF9pc19leHBvcnRfaGVhZGVyKGxpbmU6IHN0cikgLT4gYm9vbDoK"
    "ICAgICAgICAgICAgbG93ID0gbGluZS5zdHJpcCgpLmxvd2VyKCkKICAgICAgICAgICAgcmV0dXJuICgKICAgICAgICAgICAg"
    "ICAgIGxvdy5zdGFydHN3aXRoKCJlY2hvIGRlY2siKSBvcgogICAgICAgICAgICAgICAgbG93LnN0YXJ0c3dpdGgoImV4cG9y"
    "dGVkOiIpIG9yCiAgICAgICAgICAgICAgICBsb3cuc3RhcnRzd2l0aCgidG90YWwgbW9kdWxlczoiKSBvcgogICAgICAgICAg"
    "ICAgICAgbG93LnN0YXJ0c3dpdGgoInRvdGFsICIpCiAgICAgICAgICAgICkKCiAgICAgICAgZGVmIF9pc19kZWNvcmF0aXZl"
    "KGxpbmU6IHN0cikgLT4gYm9vbDoKICAgICAgICAgICAgcyA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgczoK"
    "ICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgICAgICBpZiBhbGwoY2ggaW4gIi09fl8q4oCiwrfigJQgIiBm"
    "b3IgY2ggaW4gcyk6CiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiAocy5zdGFydHN3aXRoKCI9"
    "PT0iKSBhbmQgcy5lbmRzd2l0aCgiPT09IikpIG9yIChzLnN0YXJ0c3dpdGgoIi0tLSIpIGFuZCBzLmVuZHN3aXRoKCItLS0i"
    "KSk6CiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAgICAgZGVmIF9p"
    "c19zZXBhcmF0b3IobGluZTogc3RyKSAtPiBib29sOgogICAgICAgICAgICBzID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAg"
    "IHJldHVybiBsZW4ocykgPj0gOCBhbmQgYWxsKGNoIGluICIt4oCUIiBmb3IgY2ggaW4gcykKCiAgICAgICAgZW50cmllczog"
    "bGlzdFtkaWN0XSA9IFtdCiAgICAgICAgY3VycmVudCA9IF9ibGFuaygpCiAgICAgICAgY3VycmVudF9maWVsZDogT3B0aW9u"
    "YWxbc3RyXSA9IE5vbmUKCiAgICAgICAgZGVmIF9oYXNfcGF5bG9hZChyZWM6IGRpY3QpIC0+IGJvb2w6CiAgICAgICAgICAg"
    "IHJldHVybiBhbnkoYm9vbCgocmVjLmdldChrLCAiIikgb3IgIiIpLnN0cmlwKCkpIGZvciBrIGluICgibmFtZSIsICJzdGF0"
    "dXMiLCAiZGVzY3JpcHRpb24iLCAibm90ZXMiKSkKCiAgICAgICAgZGVmIF9mbHVzaCgpIC0+IE5vbmU6CiAgICAgICAgICAg"
    "IG5vbmxvY2FsIGN1cnJlbnQsIGN1cnJlbnRfZmllbGQKICAgICAgICAgICAgY2xlYW5lZCA9IF9jbGVhbihjdXJyZW50KQog"
    "ICAgICAgICAgICBpZiBjbGVhbmVkWyJuYW1lIl06CiAgICAgICAgICAgICAgICBlbnRyaWVzLmFwcGVuZChjbGVhbmVkKQog"
    "ICAgICAgICAgICBjdXJyZW50ID0gX2JsYW5rKCkKICAgICAgICAgICAgY3VycmVudF9maWVsZCA9IE5vbmUKCiAgICAgICAg"
    "Zm9yIHJhd19saW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgICAgIGxpbmUgPSByYXdfbGluZS5yc3RyaXAoIlxu"
    "IikKICAgICAgICAgICAgc3RyaXBwZWQgPSBsaW5lLnN0cmlwKCkKCiAgICAgICAgICAgIGlmIF9pc19zZXBhcmF0b3Ioc3Ry"
    "aXBwZWQpOgogICAgICAgICAgICAgICAgaWYgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAgICAgICAgICAgIF9m"
    "bHVzaCgpCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgbm90IHN0cmlwcGVkOgogICAgICAgICAg"
    "ICAgICAgaWYgY3VycmVudF9maWVsZCA9PSAibm90ZXMiOgogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRbIm5vdGVzIl0g"
    "PSAoY3VycmVudFsibm90ZXMiXSArICJcbiIpIGlmIGN1cnJlbnRbIm5vdGVzIl0gZWxzZSAiIgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKCiAgICAgICAgICAgIGlmIF9pc19leHBvcnRfaGVhZGVyKHN0cmlwcGVkKToKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCgogICAgICAgICAgICBpZiBfaXNfZGVjb3JhdGl2ZShzdHJpcHBlZCk6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQoKICAgICAgICAgICAgaWYgIjoiIGluIHN0cmlwcGVkOgogICAgICAgICAgICAgICAgbWF5YmVfbGFiZWwsIG1heWJlX3Zh"
    "bHVlID0gc3RyaXBwZWQuc3BsaXQoIjoiLCAxKQogICAgICAgICAgICAgICAga2V5ID0gbWF5YmVfbGFiZWwuc3RyaXAoKS5s"
    "b3dlcigpCiAgICAgICAgICAgICAgICB2YWx1ZSA9IG1heWJlX3ZhbHVlLmxzdHJpcCgpCgogICAgICAgICAgICAgICAgbWFw"
    "cGVkID0gbGFiZWxfbWFwLmdldChrZXkpCiAgICAgICAgICAgICAgICBpZiBtYXBwZWQ6CiAgICAgICAgICAgICAgICAgICAg"
    "aWYgbWFwcGVkID09ICJuYW1lIiBhbmQgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAgICAgICAgICAgICAgICBf"
    "Zmx1c2goKQogICAgICAgICAgICAgICAgICAgIGN1cnJlbnRfZmllbGQgPSBtYXBwZWQKICAgICAgICAgICAgICAgICAgICBp"
    "ZiBtYXBwZWQgPT0gIm5vdGVzIjoKICAgICAgICAgICAgICAgICAgICAgICAgY3VycmVudFttYXBwZWRdID0gdmFsdWUKICAg"
    "ICAgICAgICAgICAgICAgICBlbGlmIG1hcHBlZCA9PSAic3RhdHVzIjoKICAgICAgICAgICAgICAgICAgICAgICAgY3VycmVu"
    "dFttYXBwZWRdID0gdmFsdWUgb3IgIklkZWEiCiAgICAgICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgY3VycmVudFttYXBwZWRdID0gdmFsdWUKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAg"
    "ICAgICMgVW5rbm93biBsYWJlbGVkIGxpbmVzIGFyZSBtZXRhZGF0YS9jYXRlZ29yeS9mb290ZXIgbGluZXMuCiAgICAgICAg"
    "ICAgICAgICBjdXJyZW50X2ZpZWxkID0gTm9uZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGN1"
    "cnJlbnRfZmllbGQgPT0gIm5vdGVzIjoKICAgICAgICAgICAgICAgIGN1cnJlbnRbIm5vdGVzIl0gPSAoY3VycmVudFsibm90"
    "ZXMiXSArICJcbiIgKyBzdHJpcHBlZCkgaWYgY3VycmVudFsibm90ZXMiXSBlbHNlIHN0cmlwcGVkCiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQoKICAgICAgICAgICAgaWYgY3VycmVudF9maWVsZCA9PSAiZGVzY3JpcHRpb24iOgogICAgICAgICAgICAg"
    "ICAgY3VycmVudFsiZGVzY3JpcHRpb24iXSA9IChjdXJyZW50WyJkZXNjcmlwdGlvbiJdICsgIlxuIiArIHN0cmlwcGVkKSBp"
    "ZiBjdXJyZW50WyJkZXNjcmlwdGlvbiJdIGVsc2Ugc3RyaXBwZWQKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAg"
    "ICAgICAjIElnbm9yZSB1bmxhYmVsZWQgbGluZXMgb3V0c2lkZSByZWNvZ25pemVkIGZpZWxkcy4KICAgICAgICAgICAgY29u"
    "dGludWUKCiAgICAgICAgaWYgX2hhc19wYXlsb2FkKGN1cnJlbnQpOgogICAgICAgICAgICBfZmx1c2goKQoKICAgICAgICBy"
    "ZXR1cm4gZW50cmllcwoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiSW1wb3J0IG9uZSBv"
    "ciBtb3JlIG1vZHVsZSBzcGVjcyBmcm9tIHBhc3RlZCB0ZXh0IG9yIGEgVFhUIGZpbGUuIiIiCiAgICAgICAgZGxnID0gUURp"
    "YWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1vZHVsZSBTcGVjIikKICAgICAgICBkbGcu"
    "c2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNp"
    "emUoNTYwLCA0MjApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "UUxhYmVsKAogICAgICAgICAgICAiUGFzdGUgbW9kdWxlIHRleHQgYmVsb3cgb3IgbG9hZCBhIC50eHQgZXhwb3J0LlxuIgog"
    "ICAgICAgICAgICAiU3VwcG9ydHMgTU9EVUxFIFRSQUNLRVIgZXhwb3J0cywgcmVnaXN0cnkgYmxvY2tzLCBhbmQgc2luZ2xl"
    "IGxhYmVsZWQgc3BlY3MuIgogICAgICAgICkpCgogICAgICAgIHRvb2xfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0"
    "bl9sb2FkX3R4dCA9IF9nb3RoaWNfYnRuKCJMb2FkIFRYVCIpCiAgICAgICAgbG9hZGVkX2xibCA9IFFMYWJlbCgiTm8gZmls"
    "ZSBsb2FkZWQiKQogICAgICAgIGxvYWRlZF9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogOXB4OyIpCiAgICAgICAgdG9vbF9yb3cuYWRkV2lkZ2V0KGJ0bl9sb2FkX3R4dCkKICAgICAgICB0b29sX3Jvdy5h"
    "ZGRXaWRnZXQobG9hZGVkX2xibCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHRvb2xfcm93KQoKICAgICAgICB0ZXh0"
    "X2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiUGFzdGUgbW9kdWxl"
    "IHNwZWMocykgaGVyZS4uLiIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQoKICAgICAgICBkZWYg"
    "X2xvYWRfdHh0X2ludG9fZWRpdG9yKCkgLT4gTm9uZToKICAgICAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9w"
    "ZW5GaWxlTmFtZSgKICAgICAgICAgICAgICAgIHNlbGYsCiAgICAgICAgICAgICAgICAiTG9hZCBNb2R1bGUgU3BlY3MiLAog"
    "ICAgICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJleHBvcnRzIikpLAogICAgICAgICAgICAgICAgIlRleHQgRmlsZXMgKCou"
    "dHh0KTs7QWxsIEZpbGVzICgqKSIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmF3X3RleHQgPSBQYXRoKHBhdGgpLnJlYWRf"
    "dGV4dChlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC53YXJuaW5nKHNlbGYsICJJbXBvcnQgRXJyb3IiLCBmIkNvdWxkIG5vdCByZWFkIGZpbGU6XG57ZX0i"
    "KQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIHRleHRfZmllbGQuc2V0UGxhaW5UZXh0KHJhd190ZXh0KQog"
    "ICAgICAgICAgICBsb2FkZWRfbGJsLnNldFRleHQoZiJMb2FkZWQ6IHtQYXRoKHBhdGgpLm5hbWV9IikKCiAgICAgICAgYnRu"
    "X2xvYWRfdHh0LmNsaWNrZWQuY29ubmVjdChfbG9hZF90eHRfaW50b19lZGl0b3IpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgYnRuX29rID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9n"
    "b3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBi"
    "dG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykK"
    "ICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykK"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9"
    "IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgICAgIHBhcnNlZF9lbnRyaWVzID0gc2VsZi5fcGFyc2VfaW1wb3J0X2VudHJpZXMocmF3KQog"
    "ICAgICAgICAgICBpZiBub3QgcGFyc2VkX2VudHJpZXM6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYsCiAgICAgICAgICAgICAgICAgICAgIkltcG9ydCBFcnJvciIsCiAgICAgICAgICAg"
    "ICAgICAgICAgIk5vIHZhbGlkIG1vZHVsZSBlbnRyaWVzIHdlcmUgZm91bmQuIEluY2x1ZGUgYXQgbGVhc3Qgb25lICdNb2R1"
    "bGU6JyBvciAnTU9EVUxFOicgYmxvY2suIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJldHVybgoKICAg"
    "ICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgZm9yIHBhcnNlZCBpbiBwYXJz"
    "ZWRfZW50cmllczoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAi"
    "aWQiOiBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICAgICAibmFtZSI6IHBhcnNlZC5nZXQoIm5hbWUiLCAi"
    "IilbOjYwXSwKICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogcGFyc2VkLmdldCgic3RhdHVzIiwgIklkZWEiKSBvciAi"
    "SWRlYSIsCiAgICAgICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogcGFyc2VkLmdldCgiZGVzY3JpcHRpb24iLCAiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgIm5vdGVzIjogcGFyc2VkLmdldCgibm90ZXMiLCAiIiksCiAgICAgICAgICAgICAgICAg"
    "ICAgImNyZWF0ZWQiOiBub3csCiAgICAgICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogbm93LAogICAgICAgICAgICAgICAg"
    "fSkKCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwKICAg"
    "ICAgICAgICAgICAgICJJbXBvcnQgQ29tcGxldGUiLAogICAgICAgICAgICAgICAgZiJJbXBvcnRlZCB7bGVuKHBhcnNlZF9l"
    "bnRyaWVzKX0gbW9kdWxlIGVudHJ7J3knIGlmIGxlbihwYXJzZWRfZW50cmllcykgPT0gMSBlbHNlICdpZXMnfS4iCiAgICAg"
    "ICAgICAgICkKCgojIOKUgOKUgCBQQVNTIDUgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgQWxsIHRhYiBjb250ZW50IGNsYXNzZXMgZGVmaW5lZC4KIyBTTFNjYW5zVGFiOiByZWJ1aWx0IOKAlCBEZWxldGUgYWRk"
    "ZWQsIE1vZGlmeSBmaXhlZCwgdGltZXN0YW1wIHBhcnNlciBmaXhlZCwKIyAgICAgICAgICAgICBjYXJkL2dyaW1vaXJlIHN0"
    "eWxlLCBjb3B5LXRvLWNsaXBib2FyZCBjb250ZXh0IG1lbnUuCiMgU0xDb21tYW5kc1RhYjogZ290aGljIHRhYmxlLCDip4kg"
    "Q29weSBDb21tYW5kIGJ1dHRvbi4KIyBKb2JUcmFja2VyVGFiOiBmdWxsIHJlYnVpbGQg4oCUIG11bHRpLXNlbGVjdCwgYXJj"
    "aGl2ZS9yZXN0b3JlLCBDU1YvVFNWIGV4cG9ydC4KIyBTZWxmVGFiOiBpbm5lciBzYW5jdHVtIGZvciBpZGxlIG5hcnJhdGl2"
    "ZSBhbmQgcmVmbGVjdGlvbiBvdXRwdXQuCiMgRGlhZ25vc3RpY3NUYWI6IHN0cnVjdHVyZWQgbG9nIHdpdGggbGV2ZWwtY29s"
    "b3JlZCBvdXRwdXQuCiMgTGVzc29uc1RhYjogTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGJyb3dzZXIgd2l0aCBhZGQvZGVsZXRl"
    "L3NlYXJjaC4KIwojIE5leHQ6IFBhc3MgNiDigJQgTWFpbiBXaW5kb3cKIyAoTW9yZ2FubmFEZWNrIGNsYXNzLCBmdWxsIGxh"
    "eW91dCwgQVBTY2hlZHVsZXIsIGZpcnN0LXJ1biBmbG93LAojICBkZXBlbmRlbmN5IGJvb3RzdHJhcCwgc2hvcnRjdXQgY3Jl"
    "YXRpb24sIHN0YXJ0dXAgc2VxdWVuY2UpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQ"
    "QVNTIDY6IE1BSU4gV0lORE9XICYgRU5UUlkgUE9JTlQKIwojIENvbnRhaW5zOgojICAgYm9vdHN0cmFwX2NoZWNrKCkgICAg"
    "IOKAlCBkZXBlbmRlbmN5IHZhbGlkYXRpb24gKyBhdXRvLWluc3RhbGwgYmVmb3JlIFVJCiMgICBGaXJzdFJ1bkRpYWxvZyAg"
    "ICAgICAg4oCUIG1vZGVsIHBhdGggKyBjb25uZWN0aW9uIHR5cGUgc2VsZWN0aW9uCiMgICBKb3VybmFsU2lkZWJhciAgICAg"
    "ICAg4oCUIGNvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciAoc2Vzc2lvbiBicm93c2VyICsgam91cm5hbCkKIyAgIFRvcnBvclBh"
    "bmVsICAgICAgICAgICDigJQgQVdBS0UgLyBBVVRPIC8gU1VTUEVORCBzdGF0ZSB0b2dnbGUKIyAgIE1vcmdhbm5hRGVjayAg"
    "ICAgICAgICDigJQgbWFpbiB3aW5kb3csIGZ1bGwgbGF5b3V0LCBhbGwgc2lnbmFsIGNvbm5lY3Rpb25zCiMgICBtYWluKCkg"
    "ICAgICAgICAgICAgICAg4oCUIGVudHJ5IHBvaW50IHdpdGggYm9vdHN0cmFwIHNlcXVlbmNlCiMg4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQCgppbXBvcnQgc3VicHJvY2VzcwoKCiMg4pSA4pSAIFBSRS1MQVVOQ0ggREVQRU5ERU5DWSBCT09UU1RSQVAg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfY2hlY2so"
    "KSAtPiBOb25lOgogICAgIiIiCiAgICBSdW5zIEJFRk9SRSBRQXBwbGljYXRpb24gaXMgY3JlYXRlZC4KICAgIENoZWNrcyBm"
    "b3IgUHlTaWRlNiBzZXBhcmF0ZWx5IChjYW4ndCBzaG93IEdVSSB3aXRob3V0IGl0KS4KICAgIEF1dG8taW5zdGFsbHMgYWxs"
    "IG90aGVyIG1pc3Npbmcgbm9uLWNyaXRpY2FsIGRlcHMgdmlhIHBpcC4KICAgIFZhbGlkYXRlcyBpbnN0YWxscyBzdWNjZWVk"
    "ZWQuCiAgICBXcml0ZXMgcmVzdWx0cyB0byBhIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiB0byBwaWNrIHVw"
    "LgogICAgIiIiCiAgICAjIOKUgOKUgCBTdGVwIDE6IENoZWNrIFB5U2lkZTYgKGNhbid0IGF1dG8taW5zdGFsbCB3aXRob3V0"
    "IGl0IGFscmVhZHkgcHJlc2VudCkg4pSACiAgICB0cnk6CiAgICAgICAgaW1wb3J0IFB5U2lkZTYgICMgbm9xYQogICAgZXhj"
    "ZXB0IEltcG9ydEVycm9yOgogICAgICAgICMgTm8gR1VJIGF2YWlsYWJsZSDigJQgdXNlIFdpbmRvd3MgbmF0aXZlIGRpYWxv"
    "ZyB2aWEgY3R5cGVzCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnQgY3R5cGVzCiAgICAgICAgICAgIGN0eXBlcy53"
    "aW5kbGwudXNlcjMyLk1lc3NhZ2VCb3hXKAogICAgICAgICAgICAgICAgMCwKICAgICAgICAgICAgICAgICJQeVNpZGU2IGlz"
    "IHJlcXVpcmVkIGJ1dCBub3QgaW5zdGFsbGVkLlxuXG4iCiAgICAgICAgICAgICAgICAiT3BlbiBhIHRlcm1pbmFsIGFuZCBy"
    "dW46XG5cbiIKICAgICAgICAgICAgICAgICIgICAgcGlwIGluc3RhbGwgUHlTaWRlNlxuXG4iCiAgICAgICAgICAgICAgICBm"
    "IlRoZW4gcmVzdGFydCB7REVDS19OQU1FfS4iLAogICAgICAgICAgICAgICAgZiJ7REVDS19OQU1FfSDigJQgTWlzc2luZyBE"
    "ZXBlbmRlbmN5IiwKICAgICAgICAgICAgICAgIDB4MTAgICMgTUJfSUNPTkVSUk9SCiAgICAgICAgICAgICkKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwcmludCgiQ1JJVElDQUw6IFB5U2lkZTYgbm90IGluc3RhbGxlZC4gUnVu"
    "OiBwaXAgaW5zdGFsbCBQeVNpZGU2IikKICAgICAgICBzeXMuZXhpdCgxKQoKICAgICMg4pSA4pSAIFN0ZXAgMjogQXV0by1p"
    "bnN0YWxsIG90aGVyIG1pc3NpbmcgZGVwcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9BVVRPX0lOU1RBTEwgPSBb"
    "CiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJsb2d1cnUi"
    "LCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJw"
    "eWdhbWUiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAicHl3aW4zMiIpLAogICAgICAgICgicHN1"
    "dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAgICAgICAgICAg"
    "ICAicmVxdWVzdHMiKSwKICAgIF0KCiAgICBpbXBvcnQgaW1wb3J0bGliCiAgICBib290c3RyYXBfbG9nID0gW10KCiAgICBm"
    "b3IgcGlwX25hbWUsIGltcG9ydF9uYW1lIGluIF9BVVRPX0lOU1RBTEw6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBv"
    "cnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoZiJbQk9P"
    "VFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBib290c3Ry"
    "YXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBtaXNzaW5nIOKAlCBpbnN0"
    "YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHN1YnBy"
    "b2Nlc3MucnVuKAogICAgICAgICAgICAgICAgICAgIFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwgInBpcCIsICJpbnN0YWxsIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgcGlwX25hbWUsICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRpb24iXSwK"
    "ICAgICAgICAgICAgICAgICAgICBjYXB0dXJlX291dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRpbWVvdXQ9MTIwLAogICAgICAg"
    "ICAgICAgICAgICAgIGNyZWF0aW9uZmxhZ3M9Z2V0YXR0cihzdWJwcm9jZXNzLCAiQ1JFQVRFX05PX1dJTkRPVyIsIDApLAog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgcmVzdWx0LnJldHVybmNvZGUgPT0gMDoKICAgICAgICAgICAg"
    "ICAgICAgICAjIFZhbGlkYXRlIGl0IGFjdHVhbGx5IGltcG9ydGVkIG5vdwogICAgICAgICAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQ"
    "XSB7cGlwX25hbWV9IGluc3RhbGxlZCDinJMiCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAg"
    "ICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgYXBwZWFyZWQgdG8gIgog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJzdWNjZWVkIGJ1dCBpbXBvcnQgc3RpbGwgZmFpbHMg4oCUIHJlc3RhcnQg"
    "bWF5ICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiYmUgcmVxdWlyZWQuIgogICAgICAgICAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAg"
    "ICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBmYWlsZWQ6ICIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZiJ7cmVzdWx0LnN0ZGVycls6MjAwXX0iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBleGNlcHQgc3VicHJvY2Vzcy5UaW1lb3V0RXhwaXJlZDoKICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIHRpbWVkIG91dC4iCiAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIGJvb3RzdHJh"
    "cF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGVycm9y"
    "OiB7ZX0iCiAgICAgICAgICAgICAgICApCgogICAgIyDilIDilIAgU3RlcCAzOiBXcml0ZSBib290c3RyYXAgbG9nIGZvciBE"
    "aWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICB0cnk6CiAgICAgICAgbG9nX3BhdGggPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJvb3RzdHJh"
    "cF9sb2cudHh0IgogICAgICAgIHdpdGggbG9nX3BhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAg"
    "ICAgICAgIGYud3JpdGUoIlxuIi5qb2luKGJvb3RzdHJhcF9sb2cpKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBw"
    "YXNzCgoKIyDilIDilIAgRklSU1QgUlVOIERJQUxPRyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRmly"
    "c3RSdW5EaWFsb2coUURpYWxvZyk6CiAgICAiIiIKICAgIFNob3duIG9uIGZpcnN0IGxhdW5jaCB3aGVuIGNvbmZpZy5qc29u"
    "IGRvZXNuJ3QgZXhpc3QuCiAgICBDb2xsZWN0cyBtb2RlbCBjb25uZWN0aW9uIHR5cGUgYW5kIHBhdGgva2V5LgogICAgVmFs"
    "aWRhdGVzIGNvbm5lY3Rpb24gYmVmb3JlIGFjY2VwdGluZy4KICAgIFdyaXRlcyBjb25maWcuanNvbiBvbiBzdWNjZXNzLgog"
    "ICAgQ3JlYXRlcyBkZXNrdG9wIHNob3J0Y3V0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKGYi4pymIHtE"
    "RUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxF"
    "KQogICAgICAgIHNlbGYuc2V0Rml4ZWRTaXplKDUyMCwgNDAwKQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKCiAgICBkZWYg"
    "X3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRTcGFjaW5nKDEwKQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJT"
    "VCBBV0FLRU5JTkcg4pymIikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19D"
    "UklNU09OfTsgZm9udC1zaXplOiAxNHB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICB0aXRsZS5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldCh0aXRsZSkKCiAg"
    "ICAgICAgc3ViID0gUUxhYmVsKAogICAgICAgICAgICBmIkNvbmZpZ3VyZSB0aGUgdmVzc2VsIGJlZm9yZSB7REVDS19OQU1F"
    "fSBtYXkgYXdha2VuLlxuIgogICAgICAgICAgICAiQWxsIHNldHRpbmdzIGFyZSBzdG9yZWQgbG9jYWxseS4gTm90aGluZyBs"
    "ZWF2ZXMgdGhpcyBtYWNoaW5lLiIKICAgICAgICApCiAgICAgICAgc3ViLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChzdWIpCgogICAgICAgICMg4pSA4pSAIENvbm5lY3Rpb24gdHlwZSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBBSSBDT05ORUNUSU9OIFRZUEUiKSkKICAgICAgICBzZWxmLl90eXBlX2Nv"
    "bWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmFkZEl0ZW1zKFsKICAgICAgICAgICAgIkxvY2Fs"
    "IG1vZGVsIGZvbGRlciAodHJhbnNmb3JtZXJzKSIsCiAgICAgICAgICAgICJPbGxhbWEgKGxvY2FsIHNlcnZpY2UpIiwKICAg"
    "ICAgICAgICAgIkNsYXVkZSBBUEkgKEFudGhyb3BpYykiLAogICAgICAgICAgICAiT3BlbkFJIEFQSSIsCiAgICAgICAgXSkK"
    "ICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90eXBlX2NoYW5n"
    "ZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90eXBlX2NvbWJvKQoKICAgICAgICAjIOKUgOKUgCBEeW5hbWljIGNv"
    "bm5lY3Rpb24gZmllbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0"
    "YWNrZWRXaWRnZXQoKQoKICAgICAgICAjIFBhZ2UgMDogTG9jYWwgcGF0aAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAg"
    "ICAgbDAgPSBRSEJveExheW91dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBz"
    "ZWxmLl9sb2NhbF9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHNcZG9scGhpbi04YiIKICAgICAgICApCiAgICAgICAgYnRuX2Jyb3dzZSA9"
    "IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9icm93c2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9t"
    "b2RlbCkKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fbG9jYWxfcGF0aCk7IGwwLmFkZFdpZGdldChidG5fYnJvd3NlKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyBQYWdlIDE6IE9sbGFtYSBtb2RlbCBuYW1lCiAg"
    "ICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9IFFIQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRz"
    "TWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5f"
    "b2xsYW1hX21vZGVsLnNldFBsYWNlaG9sZGVyVGV4dCgiZG9scGhpbi0yLjYtN2IiKQogICAgICAgIGwxLmFkZFdpZGdldChz"
    "ZWxmLl9vbGxhbWFfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIFBhZ2UgMjog"
    "Q2xhdWRlIEFQSSBrZXkKICAgICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAg"
    "ICAgbDIuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleSAgID0gUUxpbmVFZGl0"
    "KCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stYW50LS4uLiIpCiAgICAgICAgc2Vs"
    "Zi5fY2xhdWRlX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fY2xh"
    "dWRlX21vZGVsID0gUUxpbmVFZGl0KCJjbGF1ZGUtc29ubmV0LTQtNiIpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgi"
    "QVBJIEtleToiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX2tleSkKICAgICAgICBsMi5hZGRXaWRnZXQo"
    "UUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX21vZGVsKQogICAgICAgIHNlbGYu"
    "X3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyBQYWdlIDM6IE9wZW5BSQogICAgICAgIHAzID0gUVdpZGdldCgpCiAg"
    "ICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAg"
    "ICBzZWxmLl9vYWlfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJzay0uLi4iKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3Jk"
    "KQogICAgICAgIHNlbGYuX29haV9tb2RlbCA9IFFMaW5lRWRpdCgiZ3B0LTRvIikKICAgICAgICBsMy5hZGRXaWRnZXQoUUxh"
    "YmVsKCJBUEkgS2V5OiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfa2V5KQogICAgICAgIGwzLmFkZFdpZGdl"
    "dChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfbW9kZWwpCiAgICAgICAgc2VsZi5f"
    "c3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaykKCiAgICAgICAgIyDilIDi"
    "lIAgVGVzdCArIHN0YXR1cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICB0ZXN0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fdGVzdCA9IF9n"
    "b3RoaWNfYnRuKCJUZXN0IENvbm5lY3Rpb24iKQogICAgICAgIHNlbGYuX2J0bl90ZXN0LmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll90ZXN0X2Nvbm5lY3Rpb24pCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9z"
    "dGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAx"
    "MHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAg"
    "IHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9idG5fdGVzdCkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc3Rh"
    "dHVzX2xibCwgMSkKICAgICAgICByb290LmFkZExheW91dCh0ZXN0X3JvdykKCiAgICAgICAgIyDilIDilIAgRmFjZSBQYWNr"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZBQ0UgUEFDSyAob3B0aW9uYWwg4oCU"
    "IFpJUCBmaWxlKSIpKQogICAgICAgIGZhY2Vfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aCA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgZiJC"
    "cm93c2UgdG8ge0RFQ0tfTkFNRX0gZmFjZSBwYWNrIFpJUCAob3B0aW9uYWwsIGNhbiBhZGQgbGF0ZXIpIgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9y"
    "ZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1z"
    "aXplOiAxMnB4OyBwYWRkaW5nOiA2cHggMTBweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9mYWNlID0gX2dvdGhpY19idG4o"
    "IkJyb3dzZSIpCiAgICAgICAgYnRuX2ZhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9mYWNlKQogICAgICAgIGZh"
    "Y2Vfcm93LmFkZFdpZGdldChzZWxmLl9mYWNlX3BhdGgpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lkZ2V0KGJ0bl9mYWNlKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGZhY2Vfcm93KQoKICAgICAgICAjIOKUgOKUgCBTaG9ydGN1dCBvcHRpb24g4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2hv"
    "cnRjdXRfY2IgPSBRQ2hlY2tCb3goCiAgICAgICAgICAgICJDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCAocmVjb21tZW5kZWQp"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYi5zZXRDaGVja2VkKFRydWUpCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fc2hvcnRjdXRfY2IpCgogICAgICAgICMg4pSA4pSAIEJ1dHRvbnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "cm9vdC5hZGRTdHJldGNoKCkKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hd2Fr"
    "ZW4gPSBfZ290aGljX2J0bigi4pymIEJFR0lOIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFi"
    "bGVkKEZhbHNlKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgc2VsZi5f"
    "YnRuX2F3YWtlbi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2F3YWtlbikKICAgICAgICBidG5f"
    "cm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgZGVmIF9vbl90"
    "eXBlX2NoYW5nZShzZWxmLCBpZHg6IGludCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgo"
    "aWR4KQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zdGF0dXNfbGJs"
    "LnNldFRleHQoIiIpCgogICAgZGVmIF9icm93c2VfbW9kZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoID0gUUZpbGVE"
    "aWFsb2cuZ2V0RXhpc3RpbmdEaXJlY3RvcnkoCiAgICAgICAgICAgIHNlbGYsICJTZWxlY3QgTW9kZWwgRm9sZGVyIiwKICAg"
    "ICAgICAgICAgciJEOlxBSVxNb2RlbHMiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2xv"
    "Y2FsX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIGRlZiBfYnJvd3NlX2ZhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRo"
    "LCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IEZhY2UgUGFjayBa"
    "SVAiLAogICAgICAgICAgICBzdHIoUGF0aC5ob21lKCkgLyAiRGVza3RvcCIpLAogICAgICAgICAgICAiWklQIEZpbGVzICgq"
    "LnppcCkiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRUZXh0KHBh"
    "dGgpCgogICAgQHByb3BlcnR5CiAgICBkZWYgZmFjZV96aXBfcGF0aChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNl"
    "bGYuX2ZhY2VfcGF0aC50ZXh0KCkuc3RyaXAoKQoKICAgIGRlZiBfdGVzdF9jb25uZWN0aW9uKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCJUZXN0aW5nLi4uIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgUUFwcGxpY2F0aW9uLnByb2Nlc3NFdmVudHMo"
    "KQoKICAgICAgICBpZHggPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgb2sgID0gRmFsc2UKICAg"
    "ICAgICBtc2cgPSAiIgoKICAgICAgICBpZiBpZHggPT0gMDogICMgTG9jYWwKICAgICAgICAgICAgcGF0aCA9IHNlbGYuX2xv"
    "Y2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgaWYgcGF0aCBhbmQgUGF0aChwYXRoKS5leGlzdHMoKToKICAg"
    "ICAgICAgICAgICAgIG9rICA9IFRydWUKICAgICAgICAgICAgICAgIG1zZyA9IGYiRm9sZGVyIGZvdW5kLiBNb2RlbCB3aWxs"
    "IGxvYWQgb24gc3RhcnR1cC4iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBtc2cgPSAiRm9sZGVyIG5vdCBm"
    "b3VuZC4gQ2hlY2sgdGhlIHBhdGguIgoKICAgICAgICBlbGlmIGlkeCA9PSAxOiAgIyBPbGxhbWEKICAgICAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICAgICAgImh0"
    "dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXNwID0g"
    "dXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MykKICAgICAgICAgICAgICAgIG9rICAgPSByZXNwLnN0YXR1"
    "cyA9PSAyMDAKICAgICAgICAgICAgICAgIG1zZyAgPSAiT2xsYW1hIGlzIHJ1bm5pbmcg4pyTIiBpZiBvayBlbHNlICJPbGxh"
    "bWEgbm90IHJlc3BvbmRpbmcuIgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBt"
    "c2cgPSBmIk9sbGFtYSBub3QgcmVhY2hhYmxlOiB7ZX0iCgogICAgICAgIGVsaWYgaWR4ID09IDI6ICAjIENsYXVkZQogICAg"
    "ICAgICAgICBrZXkgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5"
    "IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stYW50IikpCiAgICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBj"
    "b3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBDbGF1ZGUgQVBJIGtleS4iCgogICAgICAgIGVsaWYgaWR4ID09"
    "IDM6ICAjIE9wZW5BSQogICAgICAgICAgICBrZXkgPSBzZWxmLl9vYWlfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stIikpCiAgICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZv"
    "cm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBPcGVuQUkgQVBJIGtleS4iCgogICAgICAg"
    "IGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfQ1JJTVNPTgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCht"
    "c2cpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29sb3J9"
    "OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQob2spCgogICAgZGVmIGJ1aWxkX2NvbmZpZyhzZWxmKSAtPiBkaWN0OgogICAg"
    "ICAgICIiIkJ1aWxkIGFuZCByZXR1cm4gdXBkYXRlZCBjb25maWcgZGljdCBmcm9tIGRpYWxvZyBzZWxlY3Rpb25zLiIiIgog"
    "ICAgICAgIGNmZyAgICAgPSBfZGVmYXVsdF9jb25maWcoKQogICAgICAgIGlkeCAgICAgPSBzZWxmLl90eXBlX2NvbWJvLmN1"
    "cnJlbnRJbmRleCgpCiAgICAgICAgdHlwZXMgICA9IFsibG9jYWwiLCAib2xsYW1hIiwgImNsYXVkZSIsICJvcGVuYWkiXQog"
    "ICAgICAgIGNmZ1sibW9kZWwiXVsidHlwZSJdID0gdHlwZXNbaWR4XQoKICAgICAgICBpZiBpZHggPT0gMDoKICAgICAgICAg"
    "ICAgY2ZnWyJtb2RlbCJdWyJwYXRoIl0gPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZWxpZiBp"
    "ZHggPT0gMToKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJvbGxhbWFfbW9kZWwiXSA9IHNlbGYuX29sbGFtYV9tb2RlbC50"
    "ZXh0KCkuc3RyaXAoKSBvciAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgZWxpZiBpZHggPT0gMjoKICAgICAgICAgICAgY2Zn"
    "WyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2Zn"
    "WyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX2NsYXVkZV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBj"
    "ZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gImNsYXVkZSIKICAgICAgICBlbGlmIGlkeCA9PSAzOgogICAgICAgICAgICBj"
    "ZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdb"
    "Im1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5fb2FpX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1si"
    "bW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAib3BlbmFpIgoKICAgICAgICBjZmdbImZpcnN0X3J1biJdID0gRmFsc2UKICAgICAg"
    "ICByZXR1cm4gY2ZnCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3JlYXRlX3Nob3J0Y3V0KHNlbGYpIC0+IGJvb2w6CiAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX3Nob3J0Y3V0X2NiLmlzQ2hlY2tlZCgpCgoKIyDilIDilIAgSk9VUk5BTCBTSURFQkFSIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBKb3VybmFsU2lkZWJhcihRV2lkZ2V0KToKICAgICIiIgogICAg"
    "Q29sbGFwc2libGUgbGVmdCBzaWRlYmFyIG5leHQgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCiAgICBUb3A6IHNlc3Npb24g"
    "Y29udHJvbHMgKGN1cnJlbnQgc2Vzc2lvbiBuYW1lLCBzYXZlL2xvYWQgYnV0dG9ucywKICAgICAgICAgYXV0b3NhdmUgaW5k"
    "aWNhdG9yKS4KICAgIEJvZHk6IHNjcm9sbGFibGUgc2Vzc2lvbiBsaXN0IOKAlCBkYXRlLCBBSSBuYW1lLCBtZXNzYWdlIGNv"
    "dW50LgogICAgQ29sbGFwc2VzIGxlZnR3YXJkIHRvIGEgdGhpbiBzdHJpcC4KCiAgICBTaWduYWxzOgogICAgICAgIHNlc3Np"
    "b25fbG9hZF9yZXF1ZXN0ZWQoc3RyKSAgIOKAlCBkYXRlIHN0cmluZyBvZiBzZXNzaW9uIHRvIGxvYWQKICAgICAgICBzZXNz"
    "aW9uX2NsZWFyX3JlcXVlc3RlZCgpICAgICDigJQgcmV0dXJuIHRvIGN1cnJlbnQgc2Vzc2lvbgogICAgIiIiCgogICAgc2Vz"
    "c2lvbl9sb2FkX3JlcXVlc3RlZCAgPSBTaWduYWwoc3RyKQogICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQgPSBTaWduYWwo"
    "KQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzZXNzaW9uX21ncjogIlNlc3Npb25NYW5hZ2VyIiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyID0gc2Vzc2lvbl9tZ3IK"
    "ICAgICAgICBzZWxmLl9leHBhbmRlZCAgICA9IFRydWUKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBVc2UgYSBob3Jpem9udGFsIHJv"
    "b3QgbGF5b3V0IOKAlCBjb250ZW50IG9uIGxlZnQsIHRvZ2dsZSBzdHJpcCBvbiByaWdodAogICAgICAgIHJvb3QgPSBRSEJv"
    "eExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5z"
    "ZXRTcGFjaW5nKDApCgogICAgICAgICMg4pSA4pSAIENvbGxhcHNlIHRvZ2dsZSBzdHJpcCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAgPSBRV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl90b2dnbGVfc3RyaXAuc2V0Rml4ZWRXaWR0aCgyMCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItcmlnaHQ6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07IgogICAgICAgICkKICAgICAgICB0c19sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl90b2dnbGVfc3RyaXAp"
    "CiAgICAgICAgdHNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA4LCAwLCA4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9i"
    "dG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTgsIDE4KQogICAgICAg"
    "IHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJTX07ICIKICAgICAgICAg"
    "ICAgZiJib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4u"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKICAgICAgICB0c19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9i"
    "dG4pCiAgICAgICAgdHNfbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgICAgICAjIOKUgOKUgCBNYWluIGNvbnRlbnQg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "c2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWluaW11bVdpZHRoKDE4MCkKICAg"
    "ICAgICBzZWxmLl9jb250ZW50LnNldE1heGltdW1XaWR0aCgyMjApCiAgICAgICAgY29udGVudF9sYXlvdXQgPSBRVkJveExh"
    "eW91dChzZWxmLl9jb250ZW50KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0"
    "KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBTZWN0aW9uIGxhYmVsCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEpPVVJOQUwiKSkKCiAgICAgICAgIyBDdXJyZW50"
    "IHNlc3Npb24gaW5mbwogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZSA9IFFMYWJlbCgiTmV3IFNlc3Npb24iKQogICAgICAg"
    "IHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1z"
    "aXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTog"
    "aXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbmFtZSkKCiAgICAgICAgIyBTYXZlIC8gTG9hZCByb3cK"
    "ICAgICAgICBjdHJsX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCLw"
    "n5K+IikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9zYXZl"
    "LnNldFRvb2xUaXAoIlNhdmUgc2Vzc2lvbiBub3ciKQogICAgICAgIHNlbGYuX2J0bl9sb2FkID0gX2dvdGhpY19idG4oIvCf"
    "k4IiKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQu"
    "c2V0VG9vbFRpcCgiQnJvd3NlIGFuZCBsb2FkIGEgcGFzdCBzZXNzaW9uIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Qg"
    "PSBRTGFiZWwoIuKXjyIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlwKCJBdXRvc2F2ZSBzdGF0dXMiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19zYXZlKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZSkKICAgICAgICBjdHJsX3Jvdy5h"
    "ZGRXaWRnZXQoc2VsZi5fYnRuX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2F1dG9zYXZlX2RvdCkK"
    "ICAgICAgICBjdHJsX3Jvdy5hZGRTdHJldGNoKCkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRMYXlvdXQoY3RybF9yb3cp"
    "CgogICAgICAgICMgSm91cm5hbCBsb2FkZWQgaW5kaWNhdG9yCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwgPSBRTGFiZWwo"
    "IiIpCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfUFVS"
    "UExFfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJm"
    "b250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRXb3JkV3JhcChUcnVl"
    "KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9qb3VybmFsX2xibCkKCiAgICAgICAgIyBDbGVhciBq"
    "b3VybmFsIGJ1dHRvbiAoaGlkZGVuIHdoZW4gbm90IGxvYWRlZCkKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbCA9"
    "IF9nb3RoaWNfYnRuKCLinJcgUmV0dXJuIHRvIFByZXNlbnQiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNl"
    "dFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2NsZWFyX2pvdXJuYWwpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcl9qb3VybmFs"
    "KQoKICAgICAgICAjIERpdmlkZXIKICAgICAgICBkaXYgPSBRRnJhbWUoKQogICAgICAgIGRpdi5zZXRGcmFtZVNoYXBlKFFG"
    "cmFtZS5TaGFwZS5ITGluZSkKICAgICAgICBkaXYuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IikK"
    "ICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoZGl2KQoKICAgICAgICAjIFNlc3Npb24gbGlzdAogICAgICAgIGNv"
    "bnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVNUIFNFU1NJT05TIikpCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICAgICBmIlFMaXN0V2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7IGJhY2tncm91"
    "bmQ6IHtDX0NSSU1TT05fRElNfTsgfX0iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtRG91Ymxl"
    "Q2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1D"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fc2Vzc2lvbl9saXN0LCAxKQoKICAgICAgICAjIEFkZCBjb250ZW50IGFuZCB0b2dnbGUgc3RyaXAgdG8gdGhlIHJv"
    "b3QgaG9yaXpvbnRhbCBsYXlvdXQKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb250ZW50KQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYu"
    "X2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIiBpZiBzZWxmLl9leHBhbmRlZCBlbHNl"
    "ICLilrYiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHAgPSBzZWxmLnBhcmVudFdpZGdldCgpCiAg"
    "ICAgICAgaWYgcCBhbmQgcC5sYXlvdXQoKToKICAgICAgICAgICAgcC5sYXlvdXQoKS5hY3RpdmF0ZSgpCgogICAgZGVmIHJl"
    "ZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZXNzaW9ucyA9IHNlbGYuX3Nlc3Npb25fbWdyLmxpc3Rfc2Vzc2lvbnMo"
    "KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIHMgaW4gc2Vzc2lvbnM6CiAgICAgICAg"
    "ICAgIGRhdGVfc3RyID0gcy5nZXQoImRhdGUiLCIiKQogICAgICAgICAgICBuYW1lICAgICA9IHMuZ2V0KCJuYW1lIiwgZGF0"
    "ZV9zdHIpWzozMF0KICAgICAgICAgICAgY291bnQgICAgPSBzLmdldCgibWVzc2FnZV9jb3VudCIsIDApCiAgICAgICAgICAg"
    "IGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0oZiJ7ZGF0ZV9zdHJ9XG57bmFtZX0gKHtjb3VudH0gbXNncykiKQogICAgICAgICAg"
    "ICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBkYXRlX3N0cikKICAgICAgICAgICAgaXRlbS5zZXRU"
    "b29sVGlwKGYiRG91YmxlLWNsaWNrIHRvIGxvYWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0iKQogICAgICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX2xpc3QuYWRkSXRlbShpdGVtKQoKICAgIGRlZiBzZXRfc2Vzc2lvbl9uYW1lKHNlbGYsIG5hbWU6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0VGV4dChuYW1lWzo1MF0gb3IgIk5ldyBTZXNzaW9uIikK"
    "CiAgICBkZWYgc2V0X2F1dG9zYXZlX2luZGljYXRvcihzZWxmLCBzYXZlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9hdXRvc2F2ZV9kb3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR1JFRU4gaWYgc2F2ZWQgZWxz"
    "ZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgKICAgICAgICAgICAgIkF1dG9zYXZlZCIgaWYgc2F2ZWQg"
    "ZWxzZSAiUGVuZGluZyBhdXRvc2F2ZSIKICAgICAgICApCgogICAgZGVmIHNldF9qb3VybmFsX2xvYWRlZChzZWxmLCBkYXRl"
    "X3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoZiLwn5OWIEpvdXJuYWw6IHtk"
    "YXRlX3N0cn0iKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoVHJ1ZSkKCiAgICBkZWYgY2xl"
    "YXJfam91cm5hbF9pbmRpY2F0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KCIi"
    "KQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCgogICAgZGVmIF9kb19zYXZlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9tZ3Iuc2F2ZSgpCiAgICAgICAgc2VsZi5zZXRfYXV0b3NhdmVf"
    "aW5kaWNhdG9yKFRydWUpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLi"
    "nJMiKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAsIGxhbWJkYTogc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi8J+S"
    "viIpKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMDAsIGxhbWJkYTogc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9y"
    "KEZhbHNlKSkKCiAgICBkZWYgX2RvX2xvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFRyeSBzZWxlY3RlZCBpdGVtIGZp"
    "cnN0CiAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgaWYgbm90IGl0ZW06"
    "CiAgICAgICAgICAgICMgSWYgbm90aGluZyBzZWxlY3RlZCwgdHJ5IHRoZSBmaXJzdCBpdGVtCiAgICAgICAgICAgIGlmIHNl"
    "bGYuX3Nlc3Npb25fbGlzdC5jb3VudCgpID4gMDoKICAgICAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3Qu"
    "aXRlbSgwKQogICAgICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LnNldEN1cnJlbnRJdGVtKGl0ZW0pCiAgICAgICAg"
    "aWYgaXRlbToKICAgICAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYgX29uX3Nlc3Npb25f"
    "Y2xpY2soc2VsZiwgaXRlbSkgLT4gTm9uZToKICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUu"
    "VXNlclJvbGUpCiAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9k"
    "b19jbGVhcl9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5lbWl0"
    "KCkKICAgICAgICBzZWxmLmNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKCkKCgojIOKUgOKUgCBUT1JQT1IgUEFORUwg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRvcnBvclBhbmVsKFFXaWRnZXQpOgogICAgIiIi"
    "CiAgICBUaHJlZS1zdGF0ZSBzdXNwZW5zaW9uIHRvZ2dsZTogQVdBS0UgfCBBVVRPIHwgU1VTUEVORAoKICAgIEFXQUtFICDi"
    "gJQgbW9kZWwgbG9hZGVkLCBhdXRvLXRvcnBvciBkaXNhYmxlZCwgaWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBBVVRPICAg"
    "4oCUIG1vZGVsIGxvYWRlZCwgbW9uaXRvcnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3VzdGFpbmVkCiAgICBT"
    "VVNQRU5EIOKAlCBtb2RlbCB1bmxvYWRlZCwgc3RheXMgc3VzcGVuZGVkIHVudGlsIG1hbnVhbGx5IGNoYW5nZWQKCiAgICBT"
    "aWduYWxzOgogICAgICAgIHN0YXRlX2NoYW5nZWQoc3RyKSAg4oCUICJBV0FLRSIgfCAiQVVUTyIgfCAiU1VTUEVORCIKICAg"
    "ICIiIgoKICAgIHN0YXRlX2NoYW5nZWQgPSBTaWduYWwoc3RyKQoKICAgIFNUQVRFUyA9IFsiQVdBS0UiLCAiQVVUTyIsICJT"
    "VVNQRU5EIl0KCiAgICBTVEFURV9TVFlMRVMgPSB7CiAgICAgICAgIkFXQUtFIjogewogICAgICAgICAgICAiYWN0aXZlIjog"
    "ICBmImJhY2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImlu"
    "YWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAg"
    "ICAgICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZl"
    "LiBBdXRvLXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAgIkFVVE8iOiB7CiAgICAgICAgICAgICJhY3Rp"
    "dmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsgY29sb3I6ICNjYzg4MjI7ICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAg"
    "ImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIs"
    "CiAgICAgICAgICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3Rp"
    "dmUuIEF1dG8tc3VzcGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAgfSwKICAgICAgICAiU1VTUEVORCI6IHsKICAg"
    "ICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiB7Q19QVVJQTEVfRElNfTsgY29sb3I6IHtDX1BVUlBMRX07ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAy"
    "cHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRp"
    "bmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0Nf"
    "VEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9y"
    "ZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgIGYi4pqwIHtVSV9TVVNQRU5TSU9O"
    "X0xBQkVMLnN0cmlwKCkgaWYgc3RyKFVJX1NVU1BFTlNJT05fTEFCRUwpLnN0cmlwKCkgZWxzZSAnU3VzcGVuZCd9IiwKICAg"
    "ICAgICAgICAgInRvb2x0aXAiOiAgZiJNb2RlbCB1bmxvYWRlZC4ge0RFQ0tfTkFNRX0gc2xlZXBzIHVudGlsIG1hbnVhbGx5"
    "IGF3YWtlbmVkLiIsCiAgICAgICAgfSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2N1cnJlbnQgPSAiQVdBS0UiCiAgICAgICAgc2Vs"
    "Zi5fYnV0dG9uczogZGljdFtzdHIsIFFQdXNoQnV0dG9uXSA9IHt9CiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNp"
    "bmcoMikKCiAgICAgICAgZm9yIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBidG4gPSBRUHVzaEJ1dHRvbihz"
    "ZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bImxhYmVsIl0pCiAgICAgICAgICAgIGJ0bi5zZXRUb29sVGlwKHNlbGYuU1RBVEVf"
    "U1RZTEVTW3N0YXRlXVsidG9vbHRpcCJdKQogICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAg"
    "IGJ0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIGNoZWNrZWQsIHM9c3RhdGU6IHNlbGYuX3NldF9zdGF0ZShzKSkKICAgICAg"
    "ICAgICAgc2VsZi5fYnV0dG9uc1tzdGF0ZV0gPSBidG4KICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChidG4pCgogICAg"
    "ICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCgogICAgZGVmIF9zZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9jdXJy"
    "ZW50ID0gc3RhdGUKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQogICAgICAgIHNlbGYuc3RhdGVfY2hhbmdlZC5lbWl0"
    "KHN0YXRlKQoKICAgIGRlZiBfYXBwbHlfc3R5bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIHN0YXRlLCBidG4gaW4g"
    "c2VsZi5fYnV0dG9ucy5pdGVtcygpOgogICAgICAgICAgICBzdHlsZV9rZXkgPSAiYWN0aXZlIiBpZiBzdGF0ZSA9PSBzZWxm"
    "Ll9jdXJyZW50IGVsc2UgImluYWN0aXZlIgogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldChzZWxmLlNUQVRFX1NUWUxF"
    "U1tzdGF0ZV1bc3R5bGVfa2V5XSkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJyZW50X3N0YXRlKHNlbGYpIC0+IHN0cjoK"
    "ICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKICAgIGRlZiBzZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICAiIiJTZXQgc3RhdGUgcHJvZ3JhbW1hdGljYWxseSAoZS5nLiBmcm9tIGF1dG8tdG9ycG9yIGRldGVjdGlv"
    "bikuIiIiCiAgICAgICAgaWYgc3RhdGUgaW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0ZShzdGF0"
    "ZSkKCgpjbGFzcyBTZXR0aW5nc1NlY3Rpb24oUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgY29sbGFwc2libGUgc2VjdGlvbiB1"
    "c2VkIGJ5IFNldHRpbmdzVGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCB0aXRsZTogc3RyLCBwYXJlbnQ9Tm9uZSwg"
    "ZXhwYW5kZWQ6IGJvb2wgPSBUcnVlKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9l"
    "eHBhbmRlZCA9IGV4cGFuZGVkCgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX2hlYWRl"
    "cl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRUZXh0KGYi4pa8IHt0aXRsZX0iIGlm"
    "IGV4cGFuZGVkIGVsc2UgZiLilrYge3RpdGxlfSIpCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNnB4OyB0ZXh0LWFsaWduOiBsZWZ0OyBmb250LXdlaWdo"
    "dDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2ds"
    "ZSkKCiAgICAgICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnRfbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "OCwgOCwgOCwgOCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDgpCiAgICAgICAgc2VsZi5fY29u"
    "dGVudC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07IGJvcmRlci10b3A6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2li"
    "bGUoZXhwYW5kZWQpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcl9idG4pCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fY29udGVudCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjb250ZW50X2xheW91dChzZWxmKSAtPiBRVkJv"
    "eExheW91dDoKICAgICAgICByZXR1cm4gc2VsZi5fY29udGVudF9sYXlvdXQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5faGVhZGVyX2J0"
    "bi5zZXRUZXh0KAogICAgICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnRleHQoKS5yZXBsYWNlKCLilrwiLCAi4pa2IiwgMSkK"
    "ICAgICAgICAgICAgaWYgbm90IHNlbGYuX2V4cGFuZGVkIGVsc2UKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh0"
    "KCkucmVwbGFjZSgi4pa2IiwgIuKWvCIsIDEpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKCgpjbGFzcyBTZXR0aW5nc1RhYihRV2lkZ2V0KToKICAgICIiIkRlY2std2lkZSBydW50aW1lIHNl"
    "dHRpbmdzIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGVja193aW5kb3c6ICJFY2hvRGVjayIsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kZWNrID0gZGVja193aW5kb3cK"
    "ICAgICAgICBzZWxmLl9zZWN0aW9uX3JlZ2lzdHJ5OiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWN0aW9uX3dp"
    "ZGdldHM6IGRpY3Rbc3RyLCBTZXR0aW5nc1NlY3Rpb25dID0ge30KCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYp"
    "CiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkK"
    "CiAgICAgICAgc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNjcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkK"
    "ICAgICAgICBzY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeShRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFy"
    "QWx3YXlzT2ZmKQogICAgICAgIHNjcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkd9OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICByb290LmFkZFdpZGdldChzY3JvbGwpCgogICAgICAgIGJvZHkg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9ib2R5X2xheW91dCA9IFFWQm94TGF5b3V0KGJvZHkpCiAgICAgICAgc2VsZi5f"
    "Ym9keV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0"
    "U3BhY2luZyg4KQogICAgICAgIHNjcm9sbC5zZXRXaWRnZXQoYm9keSkKCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfY29yZV9z"
    "ZWN0aW9ucygpCgogICAgZGVmIF9yZWdpc3Rlcl9zZWN0aW9uKHNlbGYsICosIHNlY3Rpb25faWQ6IHN0ciwgdGl0bGU6IHN0"
    "ciwgY2F0ZWdvcnk6IHN0ciwgc291cmNlX293bmVyOiBzdHIsIHNvcnRfa2V5OiBpbnQsIGJ1aWxkZXIpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeS5hcHBlbmQoewogICAgICAgICAgICAic2VjdGlvbl9pZCI6IHNlY3Rpb25f"
    "aWQsCiAgICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiBjYXRlZ29yeSwKICAgICAg"
    "ICAgICAgInNvdXJjZV9vd25lciI6IHNvdXJjZV9vd25lciwKICAgICAgICAgICAgInNvcnRfa2V5Ijogc29ydF9rZXksCiAg"
    "ICAgICAgICAgICJidWlsZGVyIjogYnVpbGRlciwKICAgICAgICB9KQoKICAgIGRlZiBfcmVnaXN0ZXJfY29yZV9zZWN0aW9u"
    "cyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9"
    "InN5c3RlbV9zZXR0aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJTeXN0ZW0gU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRl"
    "Z29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9r"
    "ZXk9MTAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3N5c3RlbV9zZWN0aW9uLAogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJpbnRlZ3JhdGlvbl9zZXR0aW5ncyIs"
    "CiAgICAgICAgICAgIHRpdGxlPSJJbnRlZ3JhdGlvbiBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVnb3J5PSJjb3JlIiwK"
    "ICAgICAgICAgICAgc291cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAgICAgICAgICBzb3J0X2tleT0yMDAsCiAgICAg"
    "ICAgICAgIGJ1aWxkZXI9c2VsZi5fYnVpbGRfaW50ZWdyYXRpb25fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "cmVnaXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0idWlfc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRs"
    "ZT0iVUkgU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0i"
    "ZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MzAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxk"
    "X3VpX3NlY3Rpb24sCiAgICAgICAgKQoKICAgICAgICBmb3IgbWV0YSBpbiBzb3J0ZWQoc2VsZi5fc2VjdGlvbl9yZWdpc3Ry"
    "eSwga2V5PWxhbWJkYSBtOiBtLmdldCgic29ydF9rZXkiLCA5OTk5KSk6CiAgICAgICAgICAgIHNlY3Rpb24gPSBTZXR0aW5n"
    "c1NlY3Rpb24obWV0YVsidGl0bGUiXSwgZXhwYW5kZWQ9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuYWRk"
    "V2lkZ2V0KHNlY3Rpb24pCiAgICAgICAgICAgIHNlbGYuX3NlY3Rpb25fd2lkZ2V0c1ttZXRhWyJzZWN0aW9uX2lkIl1dID0g"
    "c2VjdGlvbgogICAgICAgICAgICBtZXRhWyJidWlsZGVyIl0oc2VjdGlvbi5jb250ZW50X2xheW91dCkKCiAgICAgICAgc2Vs"
    "Zi5fYm9keV9sYXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgIGRlZiBfYnVpbGRfc3lzdGVtX3NlY3Rpb24oc2VsZiwgbGF5b3V0"
    "OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9kZWNrLl90b3Jwb3JfcGFuZWwgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJPcGVyYXRpb25hbCBNb2RlIikpCiAgICAgICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJl"
    "bCgiSWRsZSIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5faWRsZV9idG4pCgogICAgICAgIHNldHRp"
    "bmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB0el9hdXRvID0gYm9vbChzZXR0aW5ncy5nZXQoInRpbWV6"
    "b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICAgICAgdHpfb3ZlcnJpZGUgPSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9u"
    "ZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3RyaXAoKQoKICAgICAgICB0el9hdXRvX2NoayA9IFFDaGVja0JveCgiQXV0by1k"
    "ZXRlY3QgbG9jYWwvc3lzdGVtIHRpbWUgem9uZSIpCiAgICAgICAgdHpfYXV0b19jaGsuc2V0Q2hlY2tlZCh0el9hdXRvKQog"
    "ICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfdGltZXpvbmVfYXV0b19kZXRlY3Qp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0el9hdXRvX2NoaykKCiAgICAgICAgdHpfcm93ID0gUUhCb3hMYXlvdXQoKQog"
    "ICAgICAgIHR6X3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJNYW51YWwgVGltZSBab25lIE92ZXJyaWRlOiIpKQogICAgICAgIHR6"
    "X2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICB0el9jb21iby5zZXRFZGl0YWJsZShUcnVlKQogICAgICAgIHR6X29wdGlv"
    "bnMgPSBbCiAgICAgICAgICAgICJBbWVyaWNhL0NoaWNhZ28iLCAiQW1lcmljYS9OZXdfWW9yayIsICJBbWVyaWNhL0xvc19B"
    "bmdlbGVzIiwKICAgICAgICAgICAgIkFtZXJpY2EvRGVudmVyIiwgIlVUQyIKICAgICAgICBdCiAgICAgICAgdHpfY29tYm8u"
    "YWRkSXRlbXModHpfb3B0aW9ucykKICAgICAgICBpZiB0el9vdmVycmlkZToKICAgICAgICAgICAgaWYgdHpfY29tYm8uZmlu"
    "ZFRleHQodHpfb3ZlcnJpZGUpIDwgMDoKICAgICAgICAgICAgICAgIHR6X2NvbWJvLmFkZEl0ZW0odHpfb3ZlcnJpZGUpCiAg"
    "ICAgICAgICAgIHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0KHR6X292ZXJyaWRlKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0KCJBbWVyaWNhL0NoaWNhZ28iKQogICAgICAgIHR6X2NvbWJvLnNldEVuYWJsZWQo"
    "bm90IHR6X2F1dG8pCiAgICAgICAgdHpfY29tYm8uY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0"
    "X3RpbWV6b25lX292ZXJyaWRlKQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChsYW1iZGEgZW5hYmxlZDog"
    "dHpfY29tYm8uc2V0RW5hYmxlZChub3QgZW5hYmxlZCkpCiAgICAgICAgdHpfcm93LmFkZFdpZGdldCh0el9jb21ibywgMSkK"
    "ICAgICAgICB0el9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgdHpfaG9zdC5zZXRMYXlvdXQodHpfcm93KQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQodHpfaG9zdCkKCiAgICBkZWYgX2J1aWxkX2ludGVncmF0aW9uX3NlY3Rpb24oc2VsZiwgbGF5b3V0"
    "OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAg"
    "ICAgZW1haWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwg"
    "MzAwMDAwKSkgLy8gNjAwMDApCgoKICAgICAgICBlbWFpbF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZW1haWxfcm93"
    "LmFkZFdpZGdldChRTGFiZWwoIkVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgKG1pbnV0ZXMpOiIpKQogICAgICAgIGVtYWlsX2Jv"
    "eCA9IFFDb21ib0JveCgpCiAgICAgICAgZW1haWxfYm94LnNldEVkaXRhYmxlKFRydWUpCiAgICAgICAgZW1haWxfYm94LmFk"
    "ZEl0ZW1zKFsiMSIsICI1IiwgIjEwIiwgIjE1IiwgIjMwIiwgIjYwIl0pCiAgICAgICAgZW1haWxfYm94LnNldEN1cnJlbnRU"
    "ZXh0KHN0cihlbWFpbF9taW51dGVzKSkKICAgICAgICBlbWFpbF9ib3guY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZGVjay5fc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQpCiAgICAgICAgZW1haWxfcm93LmFkZFdpZGdl"
    "dChlbWFpbF9ib3gsIDEpCiAgICAgICAgZW1haWxfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIGVtYWlsX2hvc3Quc2V0TGF5"
    "b3V0KGVtYWlsX3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGVtYWlsX2hvc3QpCgogICAgICAgIG5vdGUgPSBRTGFi"
    "ZWwoIkVtYWlsIHBvbGxpbmcgZm91bmRhdGlvbiBpcyBjb25maWd1cmF0aW9uLW9ubHkgdW5sZXNzIGFuIGVtYWlsIGJhY2tl"
    "bmQgaXMgZW5hYmxlZC4iKQogICAgICAgIG5vdGUuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogOXB4OyIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChub3RlKQoKICAgIGRlZiBfYnVpbGRfdWlfc2VjdGlvbihz"
    "ZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJXaW5k"
    "b3cgU2hlbGwiKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2ZzX2J0bikKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2RlY2suX2JsX2J0bikKCgpjbGFzcyBEaWNlR2x5cGgoUVdpZGdldCk6CiAgICAiIiJTaW1wbGUg"
    "MkQgc2lsaG91ZXR0ZSByZW5kZXJlciBmb3IgZGllLXR5cGUgcmVjb2duaXRpb24uIiIiCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgZGllX3R5cGU6IHN0ciA9ICJkMjAiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQp"
    "CiAgICAgICAgc2VsZi5fZGllX3R5cGUgPSBkaWVfdHlwZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoNzAsIDcwKQog"
    "ICAgICAgIHNlbGYuc2V0TWF4aW11bVNpemUoOTAsIDkwKQoKICAgIGRlZiBzZXRfZGllX3R5cGUoc2VsZiwgZGllX3R5cGU6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi51cGRhdGUoKQoK"
    "ICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KToKICAgICAgICBwYWludGVyID0gUVBhaW50ZXIoc2VsZikKICAgICAg"
    "ICBwYWludGVyLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgcmVjdCA9"
    "IHNlbGYucmVjdCgpLmFkanVzdGVkKDgsIDgsIC04LCAtOCkKCiAgICAgICAgZGllID0gc2VsZi5fZGllX3R5cGUKICAgICAg"
    "ICBsaW5lID0gUUNvbG9yKENfR09MRCkKICAgICAgICBmaWxsID0gUUNvbG9yKENfQkcyKQogICAgICAgIGFjY2VudCA9IFFD"
    "b2xvcihDX0NSSU1TT04pCgogICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQZW4obGluZSwgMikpCiAgICAgICAgcGFpbnRlci5z"
    "ZXRCcnVzaChmaWxsKQoKICAgICAgICBwdHMgPSBbXQogICAgICAgIGlmIGRpZSA9PSAiZDQiOgogICAgICAgICAgICBwdHMg"
    "PSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAgICAgICAg"
    "ICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0"
    "KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgPT0gImQ2IjoKICAgICAgICAgICAg"
    "cGFpbnRlci5kcmF3Um91bmRlZFJlY3QocmVjdCwgNCwgNCkKICAgICAgICBlbGlmIGRpZSA9PSAiZDgiOgogICAgICAgICAg"
    "ICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAg"
    "ICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQo"
    "cmVjdC5jZW50ZXIoKS54KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwg"
    "cmVjdC5jZW50ZXIoKS55KCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgaW4gKCJkMTAiLCAiZDEwMCIpOgog"
    "ICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkp"
    "LAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAg"
    "ICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5ib3R0b20oKSAtIDEyKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0"
    "LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0"
    "LmJvdHRvbSgpIC0gMTIpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDgsIHJlY3QudG9wKCkgKyAx"
    "NiksCiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSA9PSAiZDEyIjoKICAgICAgICAgICAgY3ggPSByZWN0LmNlbnRl"
    "cigpLngoKTsgY3kgPSByZWN0LmNlbnRlcigpLnkoKQogICAgICAgICAgICByeCA9IHJlY3Qud2lkdGgoKSAvIDI7IHJ5ID0g"
    "cmVjdC5oZWlnaHQoKSAvIDIKICAgICAgICAgICAgZm9yIGkgaW4gcmFuZ2UoNSk6CiAgICAgICAgICAgICAgICBhID0gKG1h"
    "dGgucGkgKiAyICogaSAvIDUpIC0gKG1hdGgucGkgLyAyKQogICAgICAgICAgICAgICAgcHRzLmFwcGVuZChRUG9pbnQoaW50"
    "KGN4ICsgcnggKiBtYXRoLmNvcyhhKSksIGludChjeSArIHJ5ICogbWF0aC5zaW4oYSkpKSkKICAgICAgICBlbHNlOiAgIyBk"
    "MjAKICAgICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRv"
    "cCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSArIDEwLCByZWN0LnRvcCgpICsgMTQpLAogICAgICAg"
    "ICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQo"
    "cmVjdC5sZWZ0KCkgKyAxMCwgcmVjdC5ib3R0b20oKSAtIDE0KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRl"
    "cigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gMTAsIHJlY3Qu"
    "Ym90dG9tKCkgLSAxNCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmNlbnRlcigpLnkoKSks"
    "CiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gMTAsIHJlY3QudG9wKCkgKyAxNCksCiAgICAgICAgICAg"
    "IF0KCiAgICAgICAgaWYgcHRzOgogICAgICAgICAgICBwYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgcGF0aC5t"
    "b3ZlVG8ocHRzWzBdKQogICAgICAgICAgICBmb3IgcCBpbiBwdHNbMTpdOgogICAgICAgICAgICAgICAgcGF0aC5saW5lVG8o"
    "cCkKICAgICAgICAgICAgcGF0aC5jbG9zZVN1YnBhdGgoKQogICAgICAgICAgICBwYWludGVyLmRyYXdQYXRoKHBhdGgpCgog"
    "ICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQZW4oYWNjZW50LCAxKSkKICAgICAgICB0eHQgPSAiJSIgaWYgZGllID09ICJkMTAw"
    "IiBlbHNlIGRpZS5yZXBsYWNlKCJkIiwgIiIpCiAgICAgICAgcGFpbnRlci5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgMTIs"
    "IFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBwYWludGVyLmRyYXdUZXh0KHJlY3QsIFF0LkFsaWdubWVudEZsYWcuQWxp"
    "Z25DZW50ZXIsIHR4dCkKCgpjbGFzcyBEaWNlVHJheURpZShRRnJhbWUpOgogICAgc2luZ2xlQ2xpY2tlZCA9IFNpZ25hbChz"
    "dHIpCiAgICBkb3VibGVDbGlja2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGllX3R5cGU6IHN0"
    "ciwgZGlzcGxheV9sYWJlbDogc3RyLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5kaWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi5kaXNwbGF5X2xhYmVsID0gZGlzcGxheV9sYWJl"
    "bAogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc2V0"
    "U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnNldEludGVydmFsKDIyMCkKICAgICAgICBzZWxm"
    "Ll9jbGlja190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fZW1pdF9zaW5nbGUpCgogICAgICAgIHNlbGYuc2V0T2JqZWN0"
    "TmFtZSgiRGljZVRyYXlEaWUiKQogICAgICAgIHNlbGYuc2V0Q3Vyc29yKFF0LkN1cnNvclNoYXBlLlBvaW50aW5nSGFuZEN1"
    "cnNvcikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUZyYW1lI0RpY2VUcmF5RGllIHt7IGJh"
    "Y2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDhweDsgfX0i"
    "CiAgICAgICAgICAgIGYiUUZyYW1lI0RpY2VUcmF5RGllOmhvdmVyIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyB9"
    "fSIKICAgICAgICApCgogICAgICAgIGxheSA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5LnNldENvbnRlbnRzTWFy"
    "Z2lucyg2LCA2LCA2LCA2KQogICAgICAgIGxheS5zZXRTcGFjaW5nKDIpCgogICAgICAgIGdseXBoX2RpZSA9ICJkMTAwIiBp"
    "ZiBkaWVfdHlwZSA9PSAiZCUiIGVsc2UgZGllX3R5cGUKICAgICAgICBzZWxmLmdseXBoID0gRGljZUdseXBoKGdseXBoX2Rp"
    "ZSkKICAgICAgICBzZWxmLmdseXBoLnNldEZpeGVkU2l6ZSg1NCwgNTQpCiAgICAgICAgc2VsZi5nbHlwaC5zZXRBdHRyaWJ1"
    "dGUoUXQuV2lkZ2V0QXR0cmlidXRlLldBX1RyYW5zcGFyZW50Rm9yTW91c2VFdmVudHMsIFRydWUpCgogICAgICAgIHNlbGYu"
    "bGJsID0gUUxhYmVsKGRpc3BsYXlfbGFiZWwpCiAgICAgICAgc2VsZi5sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZs"
    "YWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUfTsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBzZWxmLmxibC5zZXRBdHRyaWJ1dGUoUXQuV2lkZ2V0QXR0cmlidXRlLldBX1RyYW5z"
    "cGFyZW50Rm9yTW91c2VFdmVudHMsIFRydWUpCgogICAgICAgIGxheS5hZGRXaWRnZXQoc2VsZi5nbHlwaCwgMCwgUXQuQWxp"
    "Z25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYubGJsKQoKICAgIGRlZiBtb3VzZVBy"
    "ZXNzRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIGlmIGV2ZW50LmJ1dHRvbigpID09IFF0Lk1vdXNlQnV0dG9uLkxlZnRC"
    "dXR0b246CiAgICAgICAgICAgIGlmIHNlbGYuX2NsaWNrX3RpbWVyLmlzQWN0aXZlKCk6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9jbGlja190aW1lci5zdG9wKCkKICAgICAgICAgICAgICAgIHNlbGYuZG91YmxlQ2xpY2tlZC5lbWl0KHNlbGYuZGllX3R5"
    "cGUpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9jbGlja190aW1lci5zdGFydCgpCiAgICAgICAg"
    "ICAgIGV2ZW50LmFjY2VwdCgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHN1cGVyKCkubW91c2VQcmVzc0V2ZW50KGV2"
    "ZW50KQoKICAgIGRlZiBfZW1pdF9zaW5nbGUoc2VsZik6CiAgICAgICAgc2VsZi5zaW5nbGVDbGlja2VkLmVtaXQoc2VsZi5k"
    "aWVfdHlwZSkKCgpjbGFzcyBEaWNlUm9sbGVyVGFiKFFXaWRnZXQpOgogICAgIiIiRGVjay1uYXRpdmUgRGljZSBSb2xsZXIg"
    "bW9kdWxlIHRhYiB3aXRoIHRyYXkvcG9vbCB3b3JrZmxvdyBhbmQgc3RydWN0dXJlZCByb2xsIGV2ZW50cy4iIiIKCiAgICBU"
    "UkFZX09SREVSID0gWyJkNCIsICJkNiIsICJkOCIsICJkMTAiLCAiZDEyIiwgImQyMCIsICJkJSJdCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBz"
    "ZWxmLl9sb2cgPSBkaWFnbm9zdGljc19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKCiAgICAg"
    "ICAgc2VsZi5yb2xsX2V2ZW50czogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5zYXZlZF9yb2xsczogbGlzdFtkaWN0"
    "XSA9IFtdCiAgICAgICAgc2VsZi5jb21tb25fcm9sbHM6IGRpY3Rbc3RyLCBkaWN0XSA9IHt9CiAgICAgICAgc2VsZi5ldmVu"
    "dF9ieV9pZDogZGljdFtzdHIsIGRpY3RdID0ge30KICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbDogZGljdFtzdHIsIGludF0g"
    "PSB7fQogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lkczogbGlzdFtzdHJdID0gW10KCiAgICAgICAgc2VsZi5ydWxlX2Rl"
    "ZmluaXRpb25zOiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAgICAgICAgICJydWxlXzRkNl9kcm9wX2xvd2VzdCI6IHsKICAg"
    "ICAgICAgICAgICAgICJpZCI6ICJydWxlXzRkNl9kcm9wX2xvd2VzdCIsCiAgICAgICAgICAgICAgICAibmFtZSI6ICJEJkQg"
    "NWUgU3RhdCBSb2xsIiwKICAgICAgICAgICAgICAgICJkaWNlX2NvdW50IjogNCwKICAgICAgICAgICAgICAgICJkaWNlX3Np"
    "ZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9jb3VudCI6IDEsCiAgICAgICAgICAgICAgICAiZHJvcF9o"
    "aWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJub3RlcyI6ICJSb2xsIDRkNiwgZHJvcCBsb3dlc3Qgb25lLiIK"
    "ICAgICAgICAgICAgfSwKICAgICAgICAgICAgInJ1bGVfM2Q2X3N0cmFpZ2h0IjogewogICAgICAgICAgICAgICAgImlkIjog"
    "InJ1bGVfM2Q2X3N0cmFpZ2h0IiwKICAgICAgICAgICAgICAgICJuYW1lIjogIjNkNiBTdHJhaWdodCIsCiAgICAgICAgICAg"
    "ICAgICAiZGljZV9jb3VudCI6IDMsCiAgICAgICAgICAgICAgICAiZGljZV9zaWRlcyI6IDYsCiAgICAgICAgICAgICAgICAi"
    "ZHJvcF9sb3dlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImRyb3BfaGlnaGVzdF9jb3VudCI6IDAsCiAgICAgICAg"
    "ICAgICAgICAibm90ZXMiOiAiQ2xhc3NpYyAzZDYgcm9sbC4iCiAgICAgICAgICAgIH0sCiAgICAgICAgfQoKICAgICAgICBz"
    "ZWxmLl9idWlsZF91aSgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5fcmVmcmVz"
    "aF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExh"
    "eW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgcm9vdC5zZXRT"
    "cGFjaW5nKDYpCgogICAgICAgIHRyYXlfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgdHJheV93cmFwLnNldFN0eWxlU2hlZXQo"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgdHJheV9sYXlv"
    "dXQgPSBRVkJveExheW91dCh0cmF5X3dyYXApCiAgICAgICAgdHJheV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgs"
    "IDgsIDgpCiAgICAgICAgdHJheV9sYXlvdXQuc2V0U3BhY2luZyg2KQogICAgICAgIHRyYXlfbGF5b3V0LmFkZFdpZGdldChR"
    "TGFiZWwoIkRpY2UgVHJheSIpKQoKICAgICAgICB0cmF5X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0cmF5X3Jvdy5z"
    "ZXRTcGFjaW5nKDYpCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIGJsb2NrID0gRGlj"
    "ZVRyYXlEaWUoZGllLCBkaWUpCiAgICAgICAgICAgIGJsb2NrLnNpbmdsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9hZGRfZGll"
    "X3RvX3Bvb2wpCiAgICAgICAgICAgIGJsb2NrLmRvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9xdWlja19yb2xsX3Npbmds"
    "ZV9kaWUpCiAgICAgICAgICAgIHRyYXlfcm93LmFkZFdpZGdldChibG9jaywgMSkKICAgICAgICB0cmF5X2xheW91dC5hZGRM"
    "YXlvdXQodHJheV9yb3cpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodHJheV93cmFwKQoKICAgICAgICBwb29sX3dyYXAgPSBR"
    "RnJhbWUoKQogICAgICAgIHBvb2xfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIHB3ID0gUVZCb3hMYXlvdXQocG9vbF93cmFwKQogICAgICAgIHB3LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHB3LnNldFNwYWNpbmcoNikKCiAgICAgICAgcHcuYWRkV2lk"
    "Z2V0KFFMYWJlbCgiQ3VycmVudCBQb29sIikpCiAgICAgICAgc2VsZi5wb29sX2V4cHJfbGJsID0gUUxhYmVsKCJQb29sOiAo"
    "ZW1wdHkpIikKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBwdy5hZGRXaWRnZXQoc2VsZi5wb29sX2V4cHJfbGJsKQoKICAgICAgICBzZWxm"
    "LnBvb2xfZW50cmllc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQgPSBRSEJv"
    "eExheW91dChzZWxmLnBvb2xfZW50cmllc193aWRnZXQpCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5zZXRTcGFjaW5nKDYp"
    "CiAgICAgICAgcHcuYWRkV2lkZ2V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCkKCiAgICAgICAgbWV0YV9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0ID0gUUxpbmVFZGl0KCk7IHNlbGYubGFiZWxfZWRpdC5zZXRQbGFj"
    "ZWhvbGRlclRleHQoIkxhYmVsIC8gcHVycG9zZSIpCiAgICAgICAgc2VsZi5tb2Rfc3BpbiA9IFFTcGluQm94KCk7IHNlbGYu"
    "bW9kX3NwaW4uc2V0UmFuZ2UoLTk5OSwgOTk5KTsgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZSgwKQogICAgICAgIHNlbGYucnVs"
    "ZV9jb21ibyA9IFFDb21ib0JveCgpOyBzZWxmLnJ1bGVfY29tYm8uYWRkSXRlbSgiTWFudWFsIFJvbGwiLCAiIikKICAgICAg"
    "ICBmb3IgcmlkLCBtZXRhIGluIHNlbGYucnVsZV9kZWZpbml0aW9ucy5pdGVtcygpOgogICAgICAgICAgICBzZWxmLnJ1bGVf"
    "Y29tYm8uYWRkSXRlbShtZXRhLmdldCgibmFtZSIsIHJpZCksIHJpZCkKCiAgICAgICAgZm9yIHRpdGxlLCB3IGluICgoIkxh"
    "YmVsIiwgc2VsZi5sYWJlbF9lZGl0KSwgKCJNb2RpZmllciIsIHNlbGYubW9kX3NwaW4pLCAoIlJ1bGUiLCBzZWxmLnJ1bGVf"
    "Y29tYm8pKToKICAgICAgICAgICAgY29sID0gUVZCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGl0bGUp"
    "CiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikK"
    "ICAgICAgICAgICAgY29sLmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIGNvbC5hZGRXaWRnZXQodykKICAgICAgICAgICAg"
    "bWV0YV9yb3cuYWRkTGF5b3V0KGNvbCwgMSkKICAgICAgICBwdy5hZGRMYXlvdXQobWV0YV9yb3cpCgogICAgICAgIGFjdGlv"
    "bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5yb2xsX3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlJvbGwgUG9vbCIp"
    "CiAgICAgICAgc2VsZi5yZXNldF9wb29sX2J0biA9IFFQdXNoQnV0dG9uKCJSZXNldCBQb29sIikKICAgICAgICBzZWxmLnNh"
    "dmVfcG9vbF9idG4gPSBRUHVzaEJ1dHRvbigiU2F2ZSBQb29sIikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJv"
    "bGxfcG9vbF9idG4pCiAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5yZXNldF9wb29sX2J0bikKICAgICAgICBhY3Rp"
    "b25zLmFkZFdpZGdldChzZWxmLnNhdmVfcG9vbF9idG4pCiAgICAgICAgcHcuYWRkTGF5b3V0KGFjdGlvbnMpCgogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHBvb2xfd3JhcCkKCiAgICAgICAgcmVzdWx0X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHJlc3Vs"
    "dF93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9"
    "OyIpCiAgICAgICAgcmwgPSBRVkJveExheW91dChyZXN1bHRfd3JhcCkKICAgICAgICBybC5zZXRDb250ZW50c01hcmdpbnMo"
    "OCwgOCwgOCwgOCkKICAgICAgICBybC5hZGRXaWRnZXQoUUxhYmVsKCJDdXJyZW50IFJlc3VsdCIpKQogICAgICAgIHNlbGYu"
    "Y3VycmVudF9yZXN1bHRfbGJsID0gUUxhYmVsKCJObyByb2xsIHlldC4iKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRf"
    "bGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgcmwuYWRkV2lkZ2V0KHNlbGYuY3VycmVudF9yZXN1bHRfbGJsKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KHJlc3VsdF93cmFwKQoKICAgICAgICBtaWQgPSBRSEJveExheW91dCgpCiAgICAgICAgaGlz"
    "dG9yeV93cmFwID0gUUZyYW1lKCkKICAgICAgICBoaXN0b3J5X3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtD"
    "X0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBodyA9IFFWQm94TGF5b3V0KGhpc3Rvcnlf"
    "d3JhcCkKICAgICAgICBody5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKCiAgICAgICAgc2VsZi5oaXN0b3J5X3Rh"
    "YnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUgPSBzZWxmLl9tYWtlX3JvbGxfdGFibGUoKQog"
    "ICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90YWJsZSgpCiAgICAgICAgc2VsZi5oaXN0b3J5"
    "X3RhYnMuYWRkVGFiKHNlbGYuY3VycmVudF90YWJsZSwgIkN1cnJlbnQgUm9sbHMiKQogICAgICAgIHNlbGYuaGlzdG9yeV90"
    "YWJzLmFkZFRhYihzZWxmLmhpc3RvcnlfdGFibGUsICJSb2xsIEhpc3RvcnkiKQogICAgICAgIGh3LmFkZFdpZGdldChzZWxm"
    "Lmhpc3RvcnlfdGFicywgMSkKCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYu"
    "Y2xlYXJfaGlzdG9yeV9idG4gPSBRUHVzaEJ1dHRvbigiQ2xlYXIgUm9sbCBIaXN0b3J5IikKICAgICAgICBoaXN0b3J5X2Fj"
    "dGlvbnMuYWRkV2lkZ2V0KHNlbGYuY2xlYXJfaGlzdG9yeV9idG4pCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zLmFkZFN0cmV0"
    "Y2goMSkKICAgICAgICBody5hZGRMYXlvdXQoaGlzdG9yeV9hY3Rpb25zKQoKICAgICAgICBzZWxmLmdyYW5kX3RvdGFsX2xi"
    "bCA9IFFMYWJlbCgiR3JhbmQgVG90YWw6IDAiKQogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsLnNldFN0eWxlU2hlZXQo"
    "ZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBody5hZGRX"
    "aWRnZXQoc2VsZi5ncmFuZF90b3RhbF9sYmwpCgogICAgICAgIHNhdmVkX3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHNhdmVk"
    "X3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "IikKICAgICAgICBzdyA9IFFWQm94TGF5b3V0KHNhdmVkX3dyYXApCiAgICAgICAgc3cuc2V0Q29udGVudHNNYXJnaW5zKDYs"
    "IDYsIDYsIDYpCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2F2ZWQgLyBDb21tb24gUm9sbHMiKSkKCiAgICAgICAg"
    "c3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2F2ZWQiKSkKICAgICAgICBzZWxmLnNhdmVkX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAg"
    "ICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuc2F2ZWRfbGlzdCwgMSkKICAgICAgICBzYXZlZF9hY3Rpb25zID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIHNlbGYucnVuX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJSdW4iKQogICAgICAgIHNlbGYubG9hZF9z"
    "YXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiTG9hZC9FZGl0IikKICAgICAgICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4gPSBRUHVz"
    "aEJ1dHRvbigiRGVsZXRlIikKICAgICAgICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLnJ1bl9zYXZlZF9idG4pCiAg"
    "ICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5sb2FkX3NhdmVkX2J0bikKICAgICAgICBzYXZlZF9hY3Rpb25z"
    "LmFkZFdpZGdldChzZWxmLmRlbGV0ZV9zYXZlZF9idG4pCiAgICAgICAgc3cuYWRkTGF5b3V0KHNhdmVkX2FjdGlvbnMpCgog"
    "ICAgICAgIHN3LmFkZFdpZGdldChRTGFiZWwoIkF1dG8tRGV0ZWN0ZWQgQ29tbW9uIikpCiAgICAgICAgc2VsZi5jb21tb25f"
    "bGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzdy5hZGRXaWRnZXQoc2VsZi5jb21tb25fbGlzdCwgMSkKICAgICAgICBj"
    "b21tb25fYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnByb21vdGVfY29tbW9uX2J0biA9IFFQdXNoQnV0"
    "dG9uKCJQcm9tb3RlIHRvIFNhdmVkIikKICAgICAgICBzZWxmLmRpc21pc3NfY29tbW9uX2J0biA9IFFQdXNoQnV0dG9uKCJE"
    "aXNtaXNzIikKICAgICAgICBjb21tb25fYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5wcm9tb3RlX2NvbW1vbl9idG4pCiAgICAg"
    "ICAgY29tbW9uX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuZGlzbWlzc19jb21tb25fYnRuKQogICAgICAgIHN3LmFkZExheW91"
    "dChjb21tb25fYWN0aW9ucykKCiAgICAgICAgc2VsZi5jb21tb25faGludCA9IFFMYWJlbCgiQ29tbW9uIHNpZ25hdHVyZSB0"
    "cmFja2luZyBhY3RpdmUuIikKICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVY"
    "VF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9oaW50KQoKICAgICAg"
    "ICBtaWQuYWRkV2lkZ2V0KGhpc3Rvcnlfd3JhcCwgMykKICAgICAgICBtaWQuYWRkV2lkZ2V0KHNhdmVkX3dyYXAsIDIpCiAg"
    "ICAgICAgcm9vdC5hZGRMYXlvdXQobWlkLCAxKQoKICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX3JvbGxfY3VycmVudF9wb29sKQogICAgICAgIHNlbGYucmVzZXRfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX3Jlc2V0X3Bvb2wpCiAgICAgICAgc2VsZi5zYXZlX3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3Bv"
    "b2wpCiAgICAgICAgc2VsZi5jbGVhcl9oaXN0b3J5X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY2xlYXJfaGlzdG9yeSkK"
    "CiAgICAgICAgc2VsZi5zYXZlZF9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1"
    "bl9zYXZlZF9yb2xsKGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpKSkKICAgICAgICBzZWxmLmNvbW1vbl9s"
    "aXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0"
    "YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpKSkKCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9ydW5fc2VsZWN0ZWRfc2F2ZWQpCiAgICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fbG9hZF9zZWxlY3RlZF9zYXZlZCkKICAgICAgICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RlbGV0ZV9zZWxlY3RlZF9zYXZlZCkKICAgICAgICBzZWxmLnByb21vdGVfY29tbW9uX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fcHJvbW90ZV9zZWxlY3RlZF9jb21tb24pCiAgICAgICAgc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2Rpc21pc3Nfc2VsZWN0ZWRfY29tbW9uKQoKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUu"
    "c2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2Vs"
    "Zi5oaXN0b3J5X3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRN"
    "ZW51KQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KGxhbWJk"
    "YSBwb3M6IHNlbGYuX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5jdXJyZW50X3RhYmxlLCBwb3MpKQogICAgICAgIHNl"
    "bGYuaGlzdG9yeV90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KGxhbWJkYSBwb3M6IHNlbGYuX3No"
    "b3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5oaXN0b3J5X3RhYmxlLCBwb3MpKQoKICAgIGRlZiBfbWFrZV9yb2xsX3RhYmxl"
    "KHNlbGYpIC0+IFFUYWJsZVdpZGdldDoKICAgICAgICB0YmwgPSBRVGFibGVXaWRnZXQoMCwgNikKICAgICAgICB0Ymwuc2V0"
    "SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIlRpbWVzdGFtcCIsICJMYWJlbCIsICJFeHByZXNzaW9uIiwgIlJhdyIsICJNb2Rp"
    "ZmllciIsICJUb3RhbCJdKQogICAgICAgIHRibC5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHRibC52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFs"
    "c2UpCiAgICAgICAgdGJsLnNldEVkaXRUcmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmln"
    "Z2VycykKICAgICAgICB0Ymwuc2V0U2VsZWN0aW9uQmVoYXZpb3IoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZp"
    "b3IuU2VsZWN0Um93cykKICAgICAgICB0Ymwuc2V0U29ydGluZ0VuYWJsZWQoRmFsc2UpCiAgICAgICAgcmV0dXJuIHRibAoK"
    "ICAgIGRlZiBfc29ydGVkX3Bvb2xfaXRlbXMoc2VsZik6CiAgICAgICAgcmV0dXJuIFsoZCwgc2VsZi5jdXJyZW50X3Bvb2wu"
    "Z2V0KGQsIDApKSBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVIgaWYgc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGQsIDApID4gMF0K"
    "CiAgICBkZWYgX3Bvb2xfZXhwcmVzc2lvbihzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSB8IE5vbmUgPSBOb25lKSAtPiBz"
    "dHI6CiAgICAgICAgcCA9IHBvb2wgaWYgcG9vbCBpcyBub3QgTm9uZSBlbHNlIHNlbGYuY3VycmVudF9wb29sCiAgICAgICAg"
    "cGFydHMgPSBbZiJ7cXR5fXtkaWV9IiBmb3IgZGllLCBxdHkgaW4gWyhkLCBwLmdldChkLCAwKSkgZm9yIGQgaW4gc2VsZi5U"
    "UkFZX09SREVSXSBpZiBxdHkgPiAwXQogICAgICAgIHJldHVybiAiICsgIi5qb2luKHBhcnRzKSBpZiBwYXJ0cyBlbHNlICIo"
    "ZW1wdHkpIgoKICAgIGRlZiBfbm9ybWFsaXplX3Bvb2xfc2lnbmF0dXJlKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBpbnRdLCBt"
    "b2RpZmllcjogaW50LCBydWxlX2lkOiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgIHBhcnRzID0gW2Yie3Bvb2wuZ2V0KGQs"
    "IDApfXtkfSIgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVSIGlmIHBvb2wuZ2V0KGQsIDApID4gMF0KICAgICAgICBiYXNlID0g"
    "IisiLmpvaW4ocGFydHMpIGlmIHBhcnRzIGVsc2UgIjAiCiAgICAgICAgc2lnID0gZiJ7YmFzZX17bW9kaWZpZXI6K2R9Igog"
    "ICAgICAgIHJldHVybiBmIntzaWd9X3tydWxlX2lkfSIgaWYgcnVsZV9pZCBlbHNlIHNpZwoKICAgIGRlZiBfZGljZV9sYWJl"
    "bChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuICJkJSIgaWYgZGllX3R5cGUgPT0gImQlIiBl"
    "bHNlIGRpZV90eXBlCgogICAgZGVmIF9yb2xsX3NpbmdsZV92YWx1ZShzZWxmLCBkaWVfdHlwZTogc3RyKToKICAgICAgICBp"
    "ZiBkaWVfdHlwZSA9PSAiZCUiOgogICAgICAgICAgICB0ZW5zID0gcmFuZG9tLnJhbmRpbnQoMCwgOSkgKiAxMAogICAgICAg"
    "ICAgICByZXR1cm4gdGVucywgKCIwMCIgaWYgdGVucyA9PSAwIGVsc2Ugc3RyKHRlbnMpKQogICAgICAgIHNpZGVzID0gaW50"
    "KGRpZV90eXBlLnJlcGxhY2UoImQiLCAiIikpCiAgICAgICAgdmFsID0gcmFuZG9tLnJhbmRpbnQoMSwgc2lkZXMpCiAgICAg"
    "ICAgcmV0dXJuIHZhbCwgc3RyKHZhbCkKCiAgICBkZWYgX3JvbGxfcG9vbF9kYXRhKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBp"
    "bnRdLCBtb2RpZmllcjogaW50LCBsYWJlbDogc3RyLCBydWxlX2lkOiBzdHIgPSAiIikgLT4gZGljdDoKICAgICAgICBncm91"
    "cGVkX251bWVyaWM6IGRpY3Rbc3RyLCBsaXN0W2ludF1dID0ge30KICAgICAgICBncm91cGVkX2Rpc3BsYXk6IGRpY3Rbc3Ry"
    "LCBsaXN0W3N0cl1dID0ge30KICAgICAgICBzdWJ0b3RhbCA9IDAKICAgICAgICB1c2VkX3Bvb2wgPSBkaWN0KHBvb2wpCgog"
    "ICAgICAgIGlmIHJ1bGVfaWQgYW5kIHJ1bGVfaWQgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zIGFuZCAobm90IHBvb2wgb3Ig"
    "bGVuKFtrIGZvciBrLCB2IGluIHBvb2wuaXRlbXMoKSBpZiB2ID4gMF0pID09IDEpOgogICAgICAgICAgICBydWxlID0gc2Vs"
    "Zi5ydWxlX2RlZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkKICAgICAgICAgICAgc2lkZXMgPSBpbnQocnVsZS5nZXQoImRp"
    "Y2Vfc2lkZXMiLCA2KSkKICAgICAgICAgICAgY291bnQgPSBpbnQocnVsZS5nZXQoImRpY2VfY291bnQiLCAxKSkKICAgICAg"
    "ICAgICAgZGllID0gZiJke3NpZGVzfSIKICAgICAgICAgICAgdXNlZF9wb29sID0ge2RpZTogY291bnR9CiAgICAgICAgICAg"
    "IHJhdyA9IFtyYW5kb20ucmFuZGludCgxLCBzaWRlcykgZm9yIF8gaW4gcmFuZ2UoY291bnQpXQogICAgICAgICAgICBkcm9w"
    "X2xvdyA9IGludChydWxlLmdldCgiZHJvcF9sb3dlc3RfY291bnQiLCAwKSBvciAwKQogICAgICAgICAgICBkcm9wX2hpZ2gg"
    "PSBpbnQocnVsZS5nZXQoImRyb3BfaGlnaGVzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGtlcHQgPSBsaXN0KHJh"
    "dykKICAgICAgICAgICAgaWYgZHJvcF9sb3cgPiAwOgogICAgICAgICAgICAgICAga2VwdCA9IHNvcnRlZChrZXB0KVtkcm9w"
    "X2xvdzpdCiAgICAgICAgICAgIGlmIGRyb3BfaGlnaCA+IDA6CiAgICAgICAgICAgICAgICBrZXB0ID0gc29ydGVkKGtlcHQp"
    "WzotZHJvcF9oaWdoXSBpZiBkcm9wX2hpZ2ggPCBsZW4oa2VwdCkgZWxzZSBbXQogICAgICAgICAgICBncm91cGVkX251bWVy"
    "aWNbZGllXSA9IHJhdwogICAgICAgICAgICBncm91cGVkX2Rpc3BsYXlbZGllXSA9IFtzdHIodikgZm9yIHYgaW4gcmF3XQog"
    "ICAgICAgICAgICBzdWJ0b3RhbCA9IHN1bShrZXB0KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGZvciBkaWUgaW4gc2Vs"
    "Zi5UUkFZX09SREVSOgogICAgICAgICAgICAgICAgcXR5ID0gaW50KHBvb2wuZ2V0KGRpZSwgMCkgb3IgMCkKICAgICAgICAg"
    "ICAgICAgIGlmIHF0eSA8PSAwOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICBncm91cGVk"
    "X251bWVyaWNbZGllXSA9IFtdCiAgICAgICAgICAgICAgICBncm91cGVkX2Rpc3BsYXlbZGllXSA9IFtdCiAgICAgICAgICAg"
    "ICAgICBmb3IgXyBpbiByYW5nZShxdHkpOgogICAgICAgICAgICAgICAgICAgIG51bSwgZGlzcCA9IHNlbGYuX3JvbGxfc2lu"
    "Z2xlX3ZhbHVlKGRpZSkKICAgICAgICAgICAgICAgICAgICBncm91cGVkX251bWVyaWNbZGllXS5hcHBlbmQobnVtKQogICAg"
    "ICAgICAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdLmFwcGVuZChkaXNwKQogICAgICAgICAgICAgICAgICAgIHN1"
    "YnRvdGFsICs9IGludChudW0pCgogICAgICAgIHRvdGFsID0gc3VidG90YWwgKyBpbnQobW9kaWZpZXIpCiAgICAgICAgdHMg"
    "PSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGV4cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Np"
    "b24odXNlZF9wb29sKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAgICAgICAgICAgIHJ1bGVfbmFtZSA9IHNlbGYucnVsZV9kZWZp"
    "bml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAgICAgICAgICAgIGV4cHIgPSBmIntleHBy"
    "fSAoe3J1bGVfbmFtZX0pIgoKICAgICAgICBldmVudCA9IHsKICAgICAgICAgICAgImlkIjogZiJyb2xsX3t1dWlkLnV1aWQ0"
    "KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRzLAogICAgICAgICAgICAibGFiZWwiOiBsYWJlbCwK"
    "ICAgICAgICAgICAgInBvb2wiOiB1c2VkX3Bvb2wsCiAgICAgICAgICAgICJncm91cGVkX3JhdyI6IGdyb3VwZWRfbnVtZXJp"
    "YywKICAgICAgICAgICAgImdyb3VwZWRfcmF3X2Rpc3BsYXkiOiBncm91cGVkX2Rpc3BsYXksCiAgICAgICAgICAgICJzdWJ0"
    "b3RhbCI6IHN1YnRvdGFsLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQobW9kaWZpZXIpLAogICAgICAgICAgICAiZmlu"
    "YWxfdG90YWwiOiBpbnQodG90YWwpLAogICAgICAgICAgICAiZXhwcmVzc2lvbiI6IGV4cHIsCiAgICAgICAgICAgICJzb3Vy"
    "Y2UiOiAiZGljZV9yb2xsZXIiLAogICAgICAgICAgICAicnVsZV9pZCI6IHJ1bGVfaWQgb3IgTm9uZSwKICAgICAgICB9CiAg"
    "ICAgICAgcmV0dXJuIGV2ZW50CgogICAgZGVmIF9hZGRfZGllX3RvX3Bvb2woc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbFtkaWVfdHlwZV0gPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90"
    "eXBlLCAwKSkgKyAxCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jl"
    "c3VsdF9sYmwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9h"
    "ZGp1c3RfcG9vbF9kaWUoc2VsZiwgZGllX3R5cGU6IHN0ciwgZGVsdGE6IGludCkgLT4gTm9uZToKICAgICAgICBuZXdfdmFs"
    "ID0gaW50KHNlbGYuY3VycmVudF9wb29sLmdldChkaWVfdHlwZSwgMCkpICsgaW50KGRlbHRhKQogICAgICAgIGlmIG5ld192"
    "YWwgPD0gMDoKICAgICAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2wucG9wKGRpZV90eXBlLCBOb25lKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHNlbGYuY3VycmVudF9wb29sW2RpZV90eXBlXSA9IG5ld192YWwKICAgICAgICBzZWxmLl9yZWZyZXNo"
    "X3Bvb2xfZWRpdG9yKCkKCiAgICBkZWYgX3JlZnJlc2hfcG9vbF9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICB3aGls"
    "ZSBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuY291bnQoKToKICAgICAgICAgICAgaXRlbSA9IHNlbGYucG9vbF9lbnRyaWVz"
    "X2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgdyA9IGl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYgdyBpcyBub3Qg"
    "Tm9uZToKICAgICAgICAgICAgICAgIHcuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZGllLCBxdHkgaW4gc2VsZi5fc29y"
    "dGVkX3Bvb2xfaXRlbXMoKToKICAgICAgICAgICAgYm94ID0gUUZyYW1lKCkKICAgICAgICAgICAgYm94LnNldFN0eWxlU2hl"
    "ZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiA2"
    "cHg7IikKICAgICAgICAgICAgbGF5ID0gUUhCb3hMYXlvdXQoYm94KQogICAgICAgICAgICBsYXkuc2V0Q29udGVudHNNYXJn"
    "aW5zKDYsIDQsIDYsIDQpCiAgICAgICAgICAgIGxheS5zZXRTcGFjaW5nKDQpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChm"
    "IntkaWV9IHh7cXR5fSIpCiAgICAgICAgICAgIG1pbnVzX2J0biA9IFFQdXNoQnV0dG9uKCLiiJIiKQogICAgICAgICAgICBw"
    "bHVzX2J0biA9IFFQdXNoQnV0dG9uKCIrIikKICAgICAgICAgICAgbWludXNfYnRuLnNldEZpeGVkV2lkdGgoMjQpCiAgICAg"
    "ICAgICAgIHBsdXNfYnRuLnNldEZpeGVkV2lkdGgoMjQpCiAgICAgICAgICAgIG1pbnVzX2J0bi5jbGlja2VkLmNvbm5lY3Qo"
    "bGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9vbF9kaWUoZCwgLTEpKQogICAgICAgICAgICBwbHVzX2J0"
    "bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9vbF9kaWUoZCwgKzEpKQog"
    "ICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChtaW51c19idG4pCiAgICAg"
    "ICAgICAgIGxheS5hZGRXaWRnZXQocGx1c19idG4pCiAgICAgICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5hZGRX"
    "aWRnZXQoYm94KQoKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuYWRkU3RyZXRjaCgxKQogICAgICAgIHNlbGYu"
    "cG9vbF9leHByX2xibC5zZXRUZXh0KGYiUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9xdWlj"
    "a19yb2xsX3NpbmdsZV9kaWUoc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBldmVudCA9IHNlbGYuX3Jv"
    "bGxfcG9vbF9kYXRhKHtkaWVfdHlwZTogMX0sIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxhYmVsX2VkaXQu"
    "dGV4dCgpLnN0cmlwKCksIHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9yICIiKQogICAgICAgIHNlbGYuX3JlY29y"
    "ZF9yb2xsX2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfcm9sbF9jdXJyZW50X3Bvb2woc2VsZikgLT4gTm9uZToKICAgICAgICBw"
    "b29sID0gZGljdChzZWxmLmN1cnJlbnRfcG9vbCkKICAgICAgICBydWxlX2lkID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnRE"
    "YXRhKCkgb3IgIiIKICAgICAgICBpZiBub3QgcG9vbCBhbmQgbm90IHJ1bGVfaWQ6CiAgICAgICAgICAgIFFNZXNzYWdlQm94"
    "LmluZm9ybWF0aW9uKHNlbGYsICJEaWNlIFJvbGxlciIsICJDdXJyZW50IFBvb2wgaXMgZW1wdHkuIikKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxmLl9yb2xsX3Bvb2xfZGF0YShwb29sLCBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1"
    "ZSgpKSwgc2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJpcCgpLCBydWxlX2lkKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xs"
    "X2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfcmVjb3JkX3JvbGxfZXZlbnQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5yb2xsX2V2ZW50cy5hcHBlbmQoZXZlbnQpCiAgICAgICAgc2VsZi5ldmVudF9ieV9pZFtldmVudFsiaWQi"
    "XV0gPSBldmVudAogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lkcyA9IFtldmVudFsiaWQiXV0KCiAgICAgICAgc2VsZi5f"
    "cmVwbGFjZV9jdXJyZW50X3Jvd3MoW2V2ZW50XSkKICAgICAgICBzZWxmLl9hcHBlbmRfaGlzdG9yeV9yb3coZXZlbnQpCiAg"
    "ICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLl91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZl"
    "bnQpCiAgICAgICAgc2VsZi5fdHJhY2tfY29tbW9uX3NpZ25hdHVyZShldmVudCkKICAgICAgICBzZWxmLl9wbGF5X3JvbGxf"
    "c291bmQoKQoKICAgIGRlZiBfcmVwbGFjZV9jdXJyZW50X3Jvd3Moc2VsZiwgZXZlbnRzOiBsaXN0W2RpY3RdKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBldmVudCBpbiBldmVudHM6"
    "CiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5jdXJyZW50X3RhYmxlLCBldmVudCkKCiAgICBkZWYg"
    "X2FwcGVuZF9oaXN0b3J5X3JvdyhzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfdGFi"
    "bGVfcm93KHNlbGYuaGlzdG9yeV90YWJsZSwgZXZlbnQpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNjcm9sbFRvQm90"
    "dG9tKCkKCiAgICBkZWYgX2Zvcm1hdF9yYXcoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IHN0cjoKICAgICAgICBncm91cGVkID0g"
    "ZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgYml0cyA9IFtdCiAgICAgICAgZm9y"
    "IGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAg"
    "IGlmIHZhbHM6CiAgICAgICAgICAgICAgICBiaXRzLmFwcGVuZChmIntkaWV9OiB7JywnLmpvaW4oc3RyKHYpIGZvciB2IGlu"
    "IHZhbHMpfSIpCiAgICAgICAgcmV0dXJuICIgfCAiLmpvaW4oYml0cykKCiAgICBkZWYgX2FwcGVuZF90YWJsZV9yb3coc2Vs"
    "ZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gdGFibGUucm93Q291"
    "bnQoKQogICAgICAgIHRhYmxlLmluc2VydFJvdyhyb3cpCgogICAgICAgIHRzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGV2"
    "ZW50WyJ0aW1lc3RhbXAiXSkKICAgICAgICB0c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBldmVu"
    "dFsiaWQiXSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMCwgdHNfaXRlbSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJv"
    "dywgMSwgUVRhYmxlV2lkZ2V0SXRlbShldmVudC5nZXQoImxhYmVsIiwgIiIpKSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJv"
    "dywgMiwgUVRhYmxlV2lkZ2V0SXRlbShldmVudC5nZXQoImV4cHJlc3Npb24iLCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0"
    "ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNlbGYuX2Zvcm1hdF9yYXcoZXZlbnQpKSkKCiAgICAgICAgbW9kX3NwaW4g"
    "PSBRU3BpbkJveCgpCiAgICAgICAgbW9kX3NwaW4uc2V0UmFuZ2UoLTk5OSwgOTk5KQogICAgICAgIG1vZF9zcGluLnNldFZh"
    "bHVlKGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkpKQogICAgICAgIG1vZF9zcGluLnZhbHVlQ2hhbmdlZC5jb25uZWN0"
    "KGxhbWJkYSB2YWwsIGVpZD1ldmVudFsiaWQiXTogc2VsZi5fb25fbW9kaWZpZXJfY2hhbmdlZChlaWQsIHZhbCkpCiAgICAg"
    "ICAgdGFibGUuc2V0Q2VsbFdpZGdldChyb3csIDQsIG1vZF9zcGluKQoKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwg"
    "UVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSkpCgogICAgZGVmIF9zeW5jX3Jvd19i"
    "eV9ldmVudF9pZChzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBldmVudF9pZDogc3RyLCBldmVudDogZGljdCkgLT4gTm9u"
    "ZToKICAgICAgICBmb3Igcm93IGluIHJhbmdlKHRhYmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBpdCA9IHRhYmxlLml0"
    "ZW0ocm93LCAwKQogICAgICAgICAgICBpZiBpdCBhbmQgaXQuZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpID09IGV2"
    "ZW50X2lkOgogICAgICAgICAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDUsIFFUYWJsZVdpZGdldEl0ZW0oc3RyKGV2ZW50"
    "LmdldCgiZmluYWxfdG90YWwiLCAwKSkpKQogICAgICAgICAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdp"
    "ZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICBkZWYgX29uX21v"
    "ZGlmaWVyX2NoYW5nZWQoc2VsZiwgZXZlbnRfaWQ6IHN0ciwgdmFsdWU6IGludCkgLT4gTm9uZToKICAgICAgICBldnQgPSBz"
    "ZWxmLmV2ZW50X2J5X2lkLmdldChldmVudF9pZCkKICAgICAgICBpZiBub3QgZXZ0OgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBldnRbIm1vZGlmaWVyIl0gPSBpbnQodmFsdWUpCiAgICAgICAgZXZ0WyJmaW5hbF90b3RhbCJdID0gaW50KGV2dC5n"
    "ZXQoInN1YnRvdGFsIiwgMCkpICsgaW50KHZhbHVlKQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYu"
    "aGlzdG9yeV90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgICAgICBzZWxmLl9zeW5jX3Jvd19ieV9ldmVudF9pZChzZWxmLmN1"
    "cnJlbnRfdGFibGUsIGV2ZW50X2lkLCBldnQpCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBp"
    "ZiBzZWxmLmN1cnJlbnRfcm9sbF9pZHMgYW5kIHNlbGYuY3VycmVudF9yb2xsX2lkc1swXSA9PSBldmVudF9pZDoKICAgICAg"
    "ICAgICAgc2VsZi5fdXBkYXRlX3Jlc3VsdF9kaXNwbGF5KGV2dCkKCiAgICBkZWYgX3VwZGF0ZV9ncmFuZF90b3RhbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHRvdGFsID0gc3VtKGludChldnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSBmb3IgZXZ0IGlu"
    "IHNlbGYucm9sbF9ldmVudHMpCiAgICAgICAgc2VsZi5ncmFuZF90b3RhbF9sYmwuc2V0VGV4dChmIkdyYW5kIFRvdGFsOiB7"
    "dG90YWx9IikKCiAgICBkZWYgX3VwZGF0ZV9yZXN1bHRfZGlzcGxheShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAg"
    "ICAgICBncm91cGVkID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgbGluZXMg"
    "PSBbXQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQo"
    "ZGllKQogICAgICAgICAgICBpZiB2YWxzOgogICAgICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYie2RpZX0geHtsZW4odmFs"
    "cyl9IOKGkiBbeycsJy5qb2luKHN0cih2KSBmb3IgdiBpbiB2YWxzKX1dIikKICAgICAgICBydWxlX2lkID0gZXZlbnQuZ2V0"
    "KCJydWxlX2lkIikKICAgICAgICBpZiBydWxlX2lkOgogICAgICAgICAgICBydWxlX25hbWUgPSBzZWxmLnJ1bGVfZGVmaW5p"
    "dGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KS5nZXQoIm5hbWUiLCBydWxlX2lkKQogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJS"
    "dWxlOiB7cnVsZV9uYW1lfSIpCiAgICAgICAgbGluZXMuYXBwZW5kKGYiTW9kaWZpZXI6IHtpbnQoZXZlbnQuZ2V0KCdtb2Rp"
    "ZmllcicsIDApKTorZH0iKQogICAgICAgIGxpbmVzLmFwcGVuZChmIlRvdGFsOiB7ZXZlbnQuZ2V0KCdmaW5hbF90b3RhbCcs"
    "IDApfSIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dCgiXG4iLmpvaW4obGluZXMpKQoKCiAgICBk"
    "ZWYgX3NhdmVfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLmN1cnJlbnRfcG9vbDoKICAgICAgICAg"
    "ICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9sbGVyIiwgIkJ1aWxkIGEgQ3VycmVudCBQb29sIGJl"
    "Zm9yZSBzYXZpbmcuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZGVmYXVsdF9uYW1lID0gc2VsZi5sYWJlbF9lZGl0"
    "LnRleHQoKS5zdHJpcCgpIG9yIHNlbGYuX3Bvb2xfZXhwcmVzc2lvbigpCiAgICAgICAgbmFtZSwgb2sgPSBRSW5wdXREaWFs"
    "b2cuZ2V0VGV4dChzZWxmLCAiU2F2ZSBQb29sIiwgIlNhdmVkIHJvbGwgbmFtZToiLCB0ZXh0PWRlZmF1bHRfbmFtZSkKICAg"
    "ICAgICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBheWxvYWQgPSB7CiAgICAgICAgICAgICJpZCI6"
    "IGYic2F2ZWRfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAibmFtZSI6IG5hbWUuc3RyaXAoKSBvciBk"
    "ZWZhdWx0X25hbWUsCiAgICAgICAgICAgICJwb29sIjogZGljdChzZWxmLmN1cnJlbnRfcG9vbCksCiAgICAgICAgICAgICJt"
    "b2RpZmllciI6IGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLAogICAgICAgICAgICAicnVsZV9pZCI6IHNlbGYucnVsZV9j"
    "b21iby5jdXJyZW50RGF0YSgpIG9yIE5vbmUsCiAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAgICAgICAgICAiY2F0ZWdv"
    "cnkiOiAic2F2ZWQiLAogICAgICAgIH0KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLmFwcGVuZChwYXlsb2FkKQogICAgICAg"
    "IHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcmVmcmVzaF9zYXZlZF9saXN0cyhzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2VsZi5zYXZlZF9yb2xsczoK"
    "ICAgICAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkKICAgICAgICAg"
    "ICAgdHh0ID0gZiJ7aXRlbS5nZXQoJ25hbWUnKX0g4oCUIHtleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZmllcicsIDApKTor"
    "ZH0iCiAgICAgICAgICAgIGx3ID0gUUxpc3RXaWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0RGF0YShRdC5JdGVt"
    "RGF0YVJvbGUuVXNlclJvbGUsIGl0ZW0pCiAgICAgICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5hZGRJdGVtKGx3KQoKICAgICAg"
    "ICBzZWxmLmNvbW1vbl9saXN0LmNsZWFyKCkKICAgICAgICByYW5rZWQgPSBzb3J0ZWQoc2VsZi5jb21tb25fcm9sbHMudmFs"
    "dWVzKCksIGtleT1sYW1iZGEgeDogeC5nZXQoImNvdW50IiwgMCksIHJldmVyc2U9VHJ1ZSkKICAgICAgICBmb3IgaXRlbSBp"
    "biByYW5rZWQ6CiAgICAgICAgICAgIGlmIGludChpdGVtLmdldCgiY291bnQiLCAwKSkgPCAyOgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkK"
    "ICAgICAgICAgICAgdHh0ID0gZiJ7ZXhwcn0ge2ludChpdGVtLmdldCgnbW9kaWZpZXInLCAwKSk6K2R9ICh4e2l0ZW0uZ2V0"
    "KCdjb3VudCcsIDApfSkiCiAgICAgICAgICAgIGx3ID0gUUxpc3RXaWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0"
    "RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGl0ZW0pCiAgICAgICAgICAgIHNlbGYuY29tbW9uX2xpc3QuYWRkSXRl"
    "bShsdykKCiAgICBkZWYgX3RyYWNrX2NvbW1vbl9zaWduYXR1cmUoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2lnID0gc2VsZi5fbm9ybWFsaXplX3Bvb2xfc2lnbmF0dXJlKGV2ZW50LmdldCgicG9vbCIsIHt9KSwgaW50KGV2ZW50"
    "LmdldCgibW9kaWZpZXIiLCAwKSksIHN0cihldmVudC5nZXQoInJ1bGVfaWQiKSBvciAiIikpCiAgICAgICAgaWYgc2lnIG5v"
    "dCBpbiBzZWxmLmNvbW1vbl9yb2xsczoKICAgICAgICAgICAgc2VsZi5jb21tb25fcm9sbHNbc2lnXSA9IHsKICAgICAgICAg"
    "ICAgICAgICJzaWduYXR1cmUiOiBzaWcsCiAgICAgICAgICAgICAgICAiY291bnQiOiAwLAogICAgICAgICAgICAgICAgIm5h"
    "bWUiOiBldmVudC5nZXQoImxhYmVsIiwgIiIpIG9yIHNpZywKICAgICAgICAgICAgICAgICJwb29sIjogZGljdChldmVudC5n"
    "ZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAw"
    "KSksCiAgICAgICAgICAgICAgICAicnVsZV9pZCI6IGV2ZW50LmdldCgicnVsZV9pZCIpLAogICAgICAgICAgICAgICAgIm5v"
    "dGVzIjogIiIsCiAgICAgICAgICAgICAgICAiY2F0ZWdvcnkiOiAiY29tbW9uIiwKICAgICAgICAgICAgfQogICAgICAgIHNl"
    "bGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPSBpbnQoc2VsZi5jb21tb25fcm9sbHNbc2lnXS5nZXQoImNvdW50Iiwg"
    "MCkpICsgMQogICAgICAgIGlmIHNlbGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPj0gMzoKICAgICAgICAgICAgc2Vs"
    "Zi5jb21tb25faGludC5zZXRUZXh0KGYiU3VnZ2VzdGlvbjogcHJvbW90ZSB7c2VsZi5fcG9vbF9leHByZXNzaW9uKGV2ZW50"
    "LmdldCgncG9vbCcsIHt9KSl9IHRvIFNhdmVkLiIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAg"
    "ZGVmIF9ydW5fc2F2ZWRfcm9sbChzZWxmLCBwYXlsb2FkOiBkaWN0IHwgTm9uZSk6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEoCiAgICAgICAgICAgIGRp"
    "Y3QocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICBpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkp"
    "LAogICAgICAgICAgICBzdHIocGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpLnN0cmlwKCksCiAgICAgICAgICAgIHN0cihwYXls"
    "b2FkLmdldCgicnVsZV9pZCIpIG9yICIiKSwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZl"
    "bnQpCgogICAgZGVmIF9sb2FkX3BheWxvYWRfaW50b19wb29sKHNlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKSAtPiBOb25l"
    "OgogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbCA9"
    "IGRpY3QocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpCiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZShpbnQocGF5bG9h"
    "ZC5nZXQoIm1vZGlmaWVyIiwgMCkpKQogICAgICAgIHNlbGYubGFiZWxfZWRpdC5zZXRUZXh0KHN0cihwYXlsb2FkLmdldCgi"
    "bmFtZSIsICIiKSkpCiAgICAgICAgcmlkID0gcGF5bG9hZC5nZXQoInJ1bGVfaWQiKQogICAgICAgIGlkeCA9IHNlbGYucnVs"
    "ZV9jb21iby5maW5kRGF0YShyaWQgb3IgIiIpCiAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgIHNlbGYucnVsZV9j"
    "b21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNl"
    "bGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoZiJDdXJyZW50IFBvb2w6IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0i"
    "KQoKICAgIGRlZiBfcnVuX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgogICAgICAgIGl0ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3Vy"
    "cmVudEl0ZW0oKQogICAgICAgIHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJv"
    "bGUpIGlmIGl0ZW0gZWxzZSBOb25lKQoKICAgIGRlZiBfbG9hZF9zZWxlY3RlZF9zYXZlZChzZWxmKToKICAgICAgICBpdGVt"
    "ID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgc2VsZi5fbG9hZF9wYXlsb2FkX2ludG9fcG9vbChwYXlsb2FkKQoKICAgICAgICBuYW1lLCBvayA9IFFJ"
    "bnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTmFtZToiLCB0ZXh0PXN0cihwYXlsb2FkLmdl"
    "dCgibmFtZSIsICIiKSkpCiAgICAgICAgaWYgbm90IG9rOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBwYXlsb2FkWyJu"
    "YW1lIl0gPSBuYW1lLnN0cmlwKCkgb3IgcGF5bG9hZC5nZXQoIm5hbWUiLCAiIikKICAgICAgICBwYXlsb2FkWyJwb29sIl0g"
    "PSBkaWN0KHNlbGYuY3VycmVudF9wb29sKQogICAgICAgIHBheWxvYWRbIm1vZGlmaWVyIl0gPSBpbnQoc2VsZi5tb2Rfc3Bp"
    "bi52YWx1ZSgpKQogICAgICAgIHBheWxvYWRbInJ1bGVfaWQiXSA9IHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9y"
    "IE5vbmUKICAgICAgICBub3Rlcywgb2tfbm90ZXMgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiRWRpdCBTYXZlZCBS"
    "b2xsIiwgIk5vdGVzIC8gY2F0ZWdvcnk6IiwgdGV4dD1zdHIocGF5bG9hZC5nZXQoIm5vdGVzIiwgIiIpKSkKICAgICAgICBp"
    "ZiBva19ub3RlczoKICAgICAgICAgICAgcGF5bG9hZFsibm90ZXMiXSA9IG5vdGVzCiAgICAgICAgc2VsZi5fcmVmcmVzaF9z"
    "YXZlZF9saXN0cygpCgogICAgZGVmIF9kZWxldGVfc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgcm93ID0gc2VsZi5z"
    "YXZlZF9saXN0LmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLnNhdmVkX3JvbGxz"
    "KToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5wb3Aocm93KQogICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcHJvbW90ZV9zZWxlY3RlZF9jb21tb24oc2VsZik6CiAgICAgICAgaXRl"
    "bSA9IHNlbGYuY29tbW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdGVtLmRhdGEoUXQuSXRlbURh"
    "dGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBwcm9tb3RlZCA9IHsKICAgICAgICAgICAgImlkIjogZiJzYXZlZF97dXVpZC51dWlkNCgpLmhleFs6"
    "MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogcGF5bG9hZC5nZXQoIm5hbWUiKSBvciBzZWxmLl9wb29sX2V4cHJlc3Npb24o"
    "cGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAicG9vbCI6IGRpY3QocGF5bG9hZC5nZXQoInBvb2wiLCB7"
    "fSkpLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAg"
    "ICAicnVsZV9pZCI6IHBheWxvYWQuZ2V0KCJydWxlX2lkIiksCiAgICAgICAgICAgICJub3RlcyI6IHBheWxvYWQuZ2V0KCJu"
    "b3RlcyIsICIiKSwKICAgICAgICAgICAgImNhdGVnb3J5IjogInNhdmVkIiwKICAgICAgICB9CiAgICAgICAgc2VsZi5zYXZl"
    "ZF9yb2xscy5hcHBlbmQocHJvbW90ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9k"
    "aXNtaXNzX3NlbGVjdGVkX2NvbW1vbihzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50SXRl"
    "bSgpCiAgICAgICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBO"
    "b25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNpZyA9IHBheWxvYWQuZ2V0"
    "KCJzaWduYXR1cmUiKQogICAgICAgIGlmIHNpZyBpbiBzZWxmLmNvbW1vbl9yb2xsczoKICAgICAgICAgICAgc2VsZi5jb21t"
    "b25fcm9sbHMucG9wKHNpZywgTm9uZSkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3Jl"
    "c2V0X3Bvb2woc2VsZik6CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2wgPSB7fQogICAgICAgIHNlbGYubW9kX3NwaW4uc2V0"
    "VmFsdWUoMCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQuY2xlYXIoKQogICAgICAgIHNlbGYucnVsZV9jb21iby5zZXRDdXJy"
    "ZW50SW5kZXgoMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVz"
    "dWx0X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfY2xlYXJfaGlzdG9yeShzZWxmKToKICAgICAgICBz"
    "ZWxmLnJvbGxfZXZlbnRzLmNsZWFyKCkKICAgICAgICBzZWxmLmV2ZW50X2J5X2lkLmNsZWFyKCkKICAgICAgICBzZWxmLmN1"
    "cnJlbnRfcm9sbF9pZHMgPSBbXQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNl"
    "bGYuY3VycmVudF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuX3VwZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAg"
    "ICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dCgiTm8gcm9sbCB5ZXQuIikKCiAgICBkZWYgX2V2ZW50X2Zyb21f"
    "dGFibGVfcG9zaXRpb24oc2VsZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgcG9zKSAtPiBkaWN0IHwgTm9uZToKICAgICAgICBp"
    "dGVtID0gdGFibGUuaXRlbUF0KHBvcykKICAgICAgICBpZiBub3QgaXRlbToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAg"
    "ICAgICByb3cgPSBpdGVtLnJvdygpCiAgICAgICAgdHNfaXRlbSA9IHRhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIG5v"
    "dCB0c19pdGVtOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGVpZCA9IHRzX2l0ZW0uZGF0YShRdC5JdGVtRGF0"
    "YVJvbGUuVXNlclJvbGUpCiAgICAgICAgcmV0dXJuIHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGVpZCkKCiAgICBkZWYgX3Nob3df"
    "cm9sbF9jb250ZXh0X21lbnUoc2VsZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgcG9zKSAtPiBOb25lOgogICAgICAgIGV2dCA9"
    "IHNlbGYuX2V2ZW50X2Zyb21fdGFibGVfcG9zaXRpb24odGFibGUsIHBvcykKICAgICAgICBpZiBub3QgZXZ0OgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBR"
    "TWVudShzZWxmKQogICAgICAgIGFjdF9zZW5kID0gbWVudS5hZGRBY3Rpb24oIlNlbmQgdG8gUHJvbXB0IikKICAgICAgICBj"
    "aG9zZW4gPSBtZW51LmV4ZWModGFibGUudmlld3BvcnQoKS5tYXBUb0dsb2JhbChwb3MpKQogICAgICAgIGlmIGNob3NlbiA9"
    "PSBhY3Rfc2VuZDoKICAgICAgICAgICAgc2VsZi5fc2VuZF9ldmVudF90b19wcm9tcHQoZXZ0KQoKICAgIGRlZiBfZm9ybWF0"
    "X2V2ZW50X2Zvcl9wcm9tcHQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IHN0cjoKICAgICAgICBsYWJlbCA9IChldmVudC5nZXQo"
    "ImxhYmVsIikgb3IgIlJvbGwiKS5zdHJpcCgpCiAgICAgICAgZ3JvdXBlZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlz"
    "cGxheSIsIHt9KSBvciB7fQogICAgICAgIHNlZ21lbnRzID0gW10KICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRF"
    "UjoKICAgICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoKICAgICAgICAgICAg"
    "ICAgIHNlZ21lbnRzLmFwcGVuZChmIntkaWV9IHJvbGxlZCB7JywnLmpvaW4oc3RyKHYpIGZvciB2IGluIHZhbHMpfSIpCiAg"
    "ICAgICAgbW9kID0gaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkKICAgICAgICB0b3RhbCA9IGludChldmVudC5nZXQo"
    "ImZpbmFsX3RvdGFsIiwgMCkpCiAgICAgICAgcmV0dXJuIGYie2xhYmVsfTogeyc7ICcuam9pbihzZWdtZW50cyl9OyBtb2Rp"
    "ZmllciB7bW9kOitkfTsgdG90YWwge3RvdGFsfSIKCiAgICBkZWYgX3NlbmRfZXZlbnRfdG9fcHJvbXB0KHNlbGYsIGV2ZW50"
    "OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHdpbmRvdyA9IHNlbGYud2luZG93KCkKICAgICAgICBpZiBub3Qgd2luZG93IG9y"
    "IG5vdCBoYXNhdHRyKHdpbmRvdywgIl9pbnB1dF9maWVsZCIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBsaW5lID0g"
    "c2VsZi5fZm9ybWF0X2V2ZW50X2Zvcl9wcm9tcHQoZXZlbnQpCiAgICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRUZXh0"
    "KGxpbmUpCiAgICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgZGVmIF9wbGF5X3JvbGxfc291bmQo"
    "c2VsZik6CiAgICAgICAgaWYgbm90IFdJTlNPVU5EX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHdpbnNvdW5kLkJlZXAoODQwLCAzMCkKICAgICAgICAgICAgd2luc291bmQuQmVlcCg2MjAsIDM1KQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgoKY2xhc3MgTWFnaWM4QmFsbFRhYihRV2lkZ2V0KToKICAg"
    "ICIiIk1hZ2ljIDgtQmFsbCBtb2R1bGUgd2l0aCBjaXJjdWxhciBvcmIgZGlzcGxheSBhbmQgcHVsc2luZyBhbnN3ZXIgdGV4"
    "dC4iIiIKCiAgICBBTlNXRVJTID0gWwogICAgICAgICJJdCBpcyBjZXJ0YWluLiIsCiAgICAgICAgIkl0IGlzIGRlY2lkZWRs"
    "eSBzby4iLAogICAgICAgICJXaXRob3V0IGEgZG91YnQuIiwKICAgICAgICAiWWVzIGRlZmluaXRlbHkuIiwKICAgICAgICAi"
    "WW91IG1heSByZWx5IG9uIGl0LiIsCiAgICAgICAgIkFzIEkgc2VlIGl0LCB5ZXMuIiwKICAgICAgICAiTW9zdCBsaWtlbHku"
    "IiwKICAgICAgICAiT3V0bG9vayBnb29kLiIsCiAgICAgICAgIlllcy4iLAogICAgICAgICJTaWducyBwb2ludCB0byB5ZXMu"
    "IiwKICAgICAgICAiUmVwbHkgaGF6eSwgdHJ5IGFnYWluLiIsCiAgICAgICAgIkFzayBhZ2FpbiBsYXRlci4iLAogICAgICAg"
    "ICJCZXR0ZXIgbm90IHRlbGwgeW91IG5vdy4iLAogICAgICAgICJDYW5ub3QgcHJlZGljdCBub3cuIiwKICAgICAgICAiQ29u"
    "Y2VudHJhdGUgYW5kIGFzayBhZ2Fpbi4iLAogICAgICAgICJEb24ndCBjb3VudCBvbiBpdC4iLAogICAgICAgICJNeSByZXBs"
    "eSBpcyBuby4iLAogICAgICAgICJNeSBzb3VyY2VzIHNheSBuby4iLAogICAgICAgICJPdXRsb29rIG5vdCBzbyBnb29kLiIs"
    "CiAgICAgICAgIlZlcnkgZG91YnRmdWwuIiwKICAgIF0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgb25fdGhyb3c9Tm9uZSwg"
    "ZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX29uX3Ro"
    "cm93ID0gb25fdGhyb3cKICAgICAgICBzZWxmLl9sb2cgPSBkaWFnbm9zdGljc19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3Ms"
    "ICoqX2t3YXJnczogTm9uZSkKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9ICIiCgogICAgICAgIHNlbGYuX2NsZWFy"
    "X3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAg"
    "ICAgIHNlbGYuX2NsZWFyX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9mYWRlX291dF9hbnN3ZXIpCgogICAgICAgIHNl"
    "bGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9idWlsZF9hbmltYXRpb25zKCkKICAgICAgICBzZWxmLl9zZXRfaWRsZV92"
    "aXN1YWwoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYsIDE2LCAxNikKICAgICAgICByb290LnNldFNwYWNp"
    "bmcoMTQpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgICAgIHNlbGYuX29yYl9mcmFtZSA9IFFGcmFtZSgpCiAg"
    "ICAgICAgc2VsZi5fb3JiX2ZyYW1lLnNldEZpeGVkU2l6ZSgyMjgsIDIyOCkKICAgICAgICBzZWxmLl9vcmJfZnJhbWUuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgIlFGcmFtZSB7IgogICAgICAgICAgICAiYmFja2dyb3VuZC1jb2xvcjogIzA0MDQw"
    "NjsiCiAgICAgICAgICAgICJib3JkZXI6IDFweCBzb2xpZCByZ2JhKDIzNCwgMjM3LCAyNTUsIDAuNjIpOyIKICAgICAgICAg"
    "ICAgImJvcmRlci1yYWRpdXM6IDExNHB4OyIKICAgICAgICAgICAgIn0iCiAgICAgICAgKQoKICAgICAgICBvcmJfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fb3JiX2ZyYW1lKQogICAgICAgIG9yYl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDIw"
    "LCAyMCwgMjAsIDIwKQogICAgICAgIG9yYl9sYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9vcmJfaW5uZXIg"
    "PSBRRnJhbWUoKQogICAgICAgIHNlbGYuX29yYl9pbm5lci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsi"
    "CiAgICAgICAgICAgICJiYWNrZ3JvdW5kLWNvbG9yOiAjMDcwNzBhOyIKICAgICAgICAgICAgImJvcmRlcjogMXB4IHNvbGlk"
    "IHJnYmEoMjU1LCAyNTUsIDI1NSwgMC4xMik7IgogICAgICAgICAgICAiYm9yZGVyLXJhZGl1czogODRweDsiCiAgICAgICAg"
    "ICAgICJ9IgogICAgICAgICkKICAgICAgICBzZWxmLl9vcmJfaW5uZXIuc2V0TWluaW11bVNpemUoMTY4LCAxNjgpCiAgICAg"
    "ICAgc2VsZi5fb3JiX2lubmVyLnNldE1heGltdW1TaXplKDE2OCwgMTY4KQoKICAgICAgICBpbm5lcl9sYXlvdXQgPSBRVkJv"
    "eExheW91dChzZWxmLl9vcmJfaW5uZXIpCiAgICAgICAgaW5uZXJfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYs"
    "IDE2LCAxNikKICAgICAgICBpbm5lcl9sYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9laWdodF9sYmwgPSBR"
    "TGFiZWwoIjgiKQogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNl"
    "bnRlcikKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgImNvbG9yOiByZ2JhKDI1"
    "NSwgMjU1LCAyNTUsIDAuOTUpOyAiCiAgICAgICAgICAgICJmb250LXNpemU6IDgwcHg7IGZvbnQtd2VpZ2h0OiA3MDA7ICIK"
    "ICAgICAgICAgICAgImZvbnQtZmFtaWx5OiBHZW9yZ2lhLCBzZXJpZjsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAg"
    "ICAgIHNlbGYuYW5zd2VyX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0QWxpZ25tZW50KFF0"
    "LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAg"
    "ICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250"
    "LXNpemU6IDE2cHg7IGZvbnQtc3R5bGU6IGl0YWxpYzsgIgogICAgICAgICAgICAiZm9udC13ZWlnaHQ6IDYwMDsgYm9yZGVy"
    "OiBub25lOyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKCiAgICAgICAgaW5uZXJfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9l"
    "aWdodF9sYmwsIDEpCiAgICAgICAgaW5uZXJfbGF5b3V0LmFkZFdpZGdldChzZWxmLmFuc3dlcl9sYmwsIDEpCiAgICAgICAg"
    "b3JiX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fb3JiX2lubmVyLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9vcmJfZnJhbWUsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25IQ2VudGVy"
    "KQoKICAgICAgICBzZWxmLnRocm93X2J0biA9IFFQdXNoQnV0dG9uKCJUaHJvdyB0aGUgOC1CYWxsIikKICAgICAgICBzZWxm"
    "LnRocm93X2J0bi5zZXRGaXhlZEhlaWdodCgzOCkKICAgICAgICBzZWxmLnRocm93X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdGhyb3dfYmFsbCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnRocm93X2J0biwgMCwgUXQuQWxpZ25tZW50Rmxh"
    "Zy5BbGlnbkhDZW50ZXIpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgZGVmIF9idWlsZF9hbmltYXRpb25zKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkgPSBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0KHNlbGYu"
    "YW5zd2VyX2xibCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0R3JhcGhpY3NFZmZlY3Qoc2VsZi5fYW5zd2VyX29wYWNp"
    "dHkpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCgogICAgICAgIHNlbGYuX3B1bHNlX2Fu"
    "aW0gPSBRUHJvcGVydHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAg"
    "c2VsZi5fcHVsc2VfYW5pbS5zZXREdXJhdGlvbig3NjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRTdGFydFZhbHVl"
    "KDAuMzUpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRFbmRWYWx1ZSgxLjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5p"
    "bS5zZXRFYXNpbmdDdXJ2ZShRRWFzaW5nQ3VydmUuVHlwZS5Jbk91dFNpbmUpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5z"
    "ZXRMb29wQ291bnQoLTEpCgogICAgICAgIHNlbGYuX2ZhZGVfb3V0ID0gUVByb3BlcnR5QW5pbWF0aW9uKHNlbGYuX2Fuc3dl"
    "cl9vcGFjaXR5LCBiIm9wYWNpdHkiLCBzZWxmKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldER1cmF0aW9uKDU2MCkKICAg"
    "ICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZhbHVlKDEuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFbmRWYWx1"
    "ZSgwLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RWFzaW5nQ3VydmUoUUVhc2luZ0N1cnZlLlR5cGUuSW5PdXRRdWFk"
    "KQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fY2xlYXJfdG9faWRsZSkKCiAgICBkZWYg"
    "X3NldF9pZGxlX3Zpc3VhbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gIiIKICAgICAg"
    "ICBzZWxmLl9laWdodF9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLmNsZWFyKCkKICAgICAgICBzZWxmLmFu"
    "c3dlcl9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCgogICAgZGVmIF90"
    "aHJvd19iYWxsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5f"
    "cHVsc2VfYW5pbS5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9wKCkKCiAgICAgICAgYW5zd2VyID0gcmFuZG9t"
    "LmNob2ljZShzZWxmLkFOU1dFUlMpCiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSBhbnN3ZXIKCiAgICAgICAgc2Vs"
    "Zi5fZWlnaHRfbGJsLmhpZGUoKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRUZXh0KGFuc3dlcikKICAgICAgICBzZWxm"
    "LmFuc3dlcl9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCiAgICAgICAg"
    "c2VsZi5fcHVsc2VfYW5pbS5zdGFydCgpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RhcnQoNjAwMDApCiAgICAgICAg"
    "c2VsZi5fbG9nKGYiWzhCQUxMXSBUaHJvdyByZXN1bHQ6IHthbnN3ZXJ9IiwgIklORk8iKQoKICAgICAgICBpZiBjYWxsYWJs"
    "ZShzZWxmLl9vbl90aHJvdyk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Rocm93KGFuc3dl"
    "cikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhmIls4QkFM"
    "TF1bV0FSTl0gSW50ZXJuYWwgcHJvbXB0IGRpc3BhdGNoIGZhaWxlZDoge2V4fSIsICJXQVJOIikKCiAgICBkZWYgX2ZhZGVf"
    "b3V0X2Fuc3dlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYu"
    "X3B1bHNlX2FuaW0uc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQu"
    "c2V0U3RhcnRWYWx1ZShmbG9hdChzZWxmLl9hbnN3ZXJfb3BhY2l0eS5vcGFjaXR5KCkpKQogICAgICAgIHNlbGYuX2ZhZGVf"
    "b3V0LnNldEVuZFZhbHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zdGFydCgpCgogICAgZGVmIF9jbGVhcl90b19p"
    "ZGxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fc2V0X2lkbGVf"
    "dmlzdWFsKCkKCiMg4pSA4pSAIE1BSU4gV0lORE9XIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApjbGFzcyBMb2NrQXdhcmVUYWJCYXIoUVRhYkJhcik6CiAgICAiIiJUYWIgYmFyIHRoYXQgYmxvY2tzIGRyYWcgaW5p"
    "dGlhdGlvbiBmb3IgbG9ja2VkIHRhYnMuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGlzX2xvY2tlZF9ieV9pZCwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2lzX2xvY2tlZF9ieV9p"
    "ZCA9IGlzX2xvY2tlZF9ieV9pZAogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXggPSAtMQoKICAgIGRlZiBfdGFiX2lkKHNl"
    "bGYsIGluZGV4OiBpbnQpOgogICAgICAgIGlmIGluZGV4IDwgMDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBy"
    "ZXR1cm4gc2VsZi50YWJEYXRhKGluZGV4KQoKICAgIGRlZiBtb3VzZVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAg"
    "IHNlbGYuX3ByZXNzZWRfaW5kZXggPSBzZWxmLnRhYkF0KGV2ZW50LnBvcygpKQogICAgICAgIGlmIChldmVudC5idXR0b24o"
    "KSA9PSBRdC5Nb3VzZUJ1dHRvbi5MZWZ0QnV0dG9uIGFuZCBzZWxmLl9wcmVzc2VkX2luZGV4ID49IDApOgogICAgICAgICAg"
    "ICB0YWJfaWQgPSBzZWxmLl90YWJfaWQoc2VsZi5fcHJlc3NlZF9pbmRleCkKICAgICAgICAgICAgaWYgdGFiX2lkIGFuZCBz"
    "ZWxmLl9pc19sb2NrZWRfYnlfaWQodGFiX2lkKToKICAgICAgICAgICAgICAgIHNlbGYuc2V0Q3VycmVudEluZGV4KHNlbGYu"
    "X3ByZXNzZWRfaW5kZXgpCiAgICAgICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlTW92ZUV2ZW50KHNlbGYsIGV2ZW50"
    "KToKICAgICAgICBpZiBzZWxmLl9wcmVzc2VkX2luZGV4ID49IDA6CiAgICAgICAgICAgIHRhYl9pZCA9IHNlbGYuX3RhYl9p"
    "ZChzZWxmLl9wcmVzc2VkX2luZGV4KQogICAgICAgICAgICBpZiB0YWJfaWQgYW5kIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCh0"
    "YWJfaWQpOgogICAgICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIHN1"
    "cGVyKCkubW91c2VNb3ZlRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlUmVsZWFzZUV2ZW50KHNlbGYsIGV2ZW50KToKICAg"
    "ICAgICBzZWxmLl9wcmVzc2VkX2luZGV4ID0gLTEKICAgICAgICBzdXBlcigpLm1vdXNlUmVsZWFzZUV2ZW50KGV2ZW50KQoK"
    "CmNsYXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAg"
    "IEFzc2VtYmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIi"
    "CgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4"
    "dGVybmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9"
    "IDAuOCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJ"
    "Q0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElD"
    "S1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAg"
    "ICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNl"
    "X2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAg"
    "IHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBm"
    "InNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2FjdGl2"
    "ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAgICAgIHNl"
    "bGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3Qgc3RyZWFt"
    "aW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAg"
    "ICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFm"
    "dGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJl"
    "c3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxp"
    "ZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRl"
    "ZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2Vy"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAg"
    "ICAgc2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IEZh"
    "bHNlCiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9ICJuZXh0XzNfbW9udGhzIgoKICAgICAgICAjIFJpZ2h0IHN5"
    "c3RlbXMgdGFiLXN0cmlwIHByZXNlbnRhdGlvbiBzdGF0ZSAoc3RhYmxlIElEcyArIHZpc3VhbCBvcmRlcikKICAgICAgICBz"
    "ZWxmLl9zcGVsbF90YWJfZGVmczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlOiBkaWN0"
    "W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6IE9wdGlvbmFsW3N0cl0gPSBO"
    "b25lCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxmLl9m"
    "b2N1c19ob29rZWRfZm9yX3NwZWxsX3RhYnMgPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgogICAgICAgICMgU2Vl"
    "ZCBMU0wgcnVsZXMgb24gZmlyc3QgcnVuCiAgICAgICAgc2VsZi5fbGVzc29ucy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAg"
    "ICMgTG9hZCBlbnRpdHkgc3RhdGUKICAgICAgICBzZWxmLl9zdGF0ZSA9IHNlbGYuX21lbW9yeS5sb2FkX3N0YXRlKCkKICAg"
    "ICAgICBzZWxmLl9zdGF0ZVsic2Vzc2lvbl9jb3VudCJdID0gc2VsZi5fc3RhdGUuZ2V0KCJzZXNzaW9uX2NvdW50IiwwKSAr"
    "IDEKICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zdGFydHVwIl0gID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgc2VsZi5f"
    "bWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICMgQnVpbGQgYWRhcHRvcgogICAgICAgIHNlbGYuX2Fk"
    "YXB0b3IgPSBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgKHNldCB1"
    "cCBhZnRlciB3aWRnZXRzIGJ1aWx0KQogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyOiBPcHRpb25hbFtGYWNlVGltZXJN"
    "YW5hZ2VyXSA9IE5vbmUKCiAgICAgICAgIyDilIDilIAgQnVpbGQgVUkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5zZXRXaW5k"
    "b3dUaXRsZShBUFBfTkFNRSkKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEyMDAsIDc1MCkKICAgICAgICBzZWxmLnJl"
    "c2l6ZSgxMzUwLCA4NTApCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAgICBzZWxmLl9idWlsZF91"
    "aSgpCgogICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBzZWxmLl9mYWNlX3Rp"
    "bWVyX21nciA9IEZhY2VUaW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNlbGYuX21pcnJvciwgc2VsZi5fZW1vdGlvbl9ibG9j"
    "awogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRz"
    "X3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRl"
    "X3N0YXRzKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnN0YXJ0KDEwMDApCgogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVy"
    "ID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9ibGlua190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fYmxpbmspCiAgICAg"
    "ICAgc2VsZi5fYmxpbmtfdGltZXIuc3RhcnQoODAwKQoKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1l"
    "cigpCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQgYW5kIHNlbGYuX2Zvb3Rlcl9zdHJpcCBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2Zvb3Rlcl9zdHJpcC5yZWZy"
    "ZXNoKQogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgIyDilIDilIAg"
    "U2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVudGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAg"
    "ICAgIyBEbyBOT1QgY2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAg"
    "ICMgQm90aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRlcgogICAgICAgICMg"
    "d2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJ"
    "T04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY2Vu"
    "dHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAgICAgIHJvb3QgPSBR"
    "VkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDilIDilIAgQm9keTogbGVmdCB3b3Jrc3BhY2UgfCBy"
    "aWdodCBzeXN0ZW1zIChkcmFnZ2FibGUgc3BsaXR0ZXIpIOKUgAogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIgPSBRU3Bs"
    "aXR0ZXIoUXQuT3JpZW50YXRpb24uSG9yaXpvbnRhbCkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLnNldENoaWxkcmVu"
    "Q29sbGFwc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fbWFpbl9zcGxpdHRlci5zZXRIYW5kbGVXaWR0aCg4KQoKICAgICAg"
    "ICAjIExlZnQgcGFuZSA9IEpvdXJuYWwgKyBDaGF0IHdvcmtzcGFjZQogICAgICAgIGxlZnRfd29ya3NwYWNlID0gUVdpZGdl"
    "dCgpCiAgICAgICAgbGVmdF93b3Jrc3BhY2Uuc2V0TWluaW11bVdpZHRoKDcwMCkKICAgICAgICBsZWZ0X2xheW91dCA9IFFI"
    "Qm94TGF5b3V0KGxlZnRfd29ya3NwYWNlKQogICAgICAgIGxlZnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAw"
    "LCAwKQogICAgICAgIGxlZnRfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyID0g"
    "Sm91cm5hbFNpZGViYXIoc2VsZi5fc2Vzc2lvbnMpCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fbG9h"
    "ZF9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fbG9hZF9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgc2Vs"
    "Zi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2Ns"
    "ZWFyX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBsZWZ0X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFy"
    "KQogICAgICAgIGxlZnRfbGF5b3V0LmFkZExheW91dChzZWxmLl9idWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAgICAgICMg"
    "UmlnaHQgcGFuZSA9IHN5c3RlbXMvbW9kdWxlcyArIGNhbGVuZGFyCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdl"
    "dCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlLnNldE1pbmltdW1XaWR0aCgzNjApCiAgICAgICAgcmlnaHRfbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwg"
    "MCwgMCwgMCkKICAgICAgICByaWdodF9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgIHJpZ2h0X2xheW91dC5hZGRMYXlv"
    "dXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCksIDEpCgogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuYWRkV2lk"
    "Z2V0KGxlZnRfd29ya3NwYWNlKQogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFj"
    "ZSkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLnNldENvbGxhcHNpYmxlKDAsIEZhbHNlKQogICAgICAgIHNlbGYuX21h"
    "aW5fc3BsaXR0ZXIuc2V0Q29sbGFwc2libGUoMSwgRmFsc2UpCiAgICAgICAgc2VsZi5fbWFpbl9zcGxpdHRlci5zcGxpdHRl"
    "ck1vdmVkLmNvbm5lY3Qoc2VsZi5fc2F2ZV9tYWluX3NwbGl0dGVyX3N0YXRlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNl"
    "bGYuX21haW5fc3BsaXR0ZXIsIDEpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi5fcmVzdG9yZV9tYWluX3Nw"
    "bGl0dGVyX3N0YXRlKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0g"
    "UUxhYmVsKAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQog"
    "ICAgICAgIGZvb3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRl"
    "cikKICAgICAgICByb290LmFkZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdp"
    "ZGdldDoKICAgICAgICBiYXIgPSBRV2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFy"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5"
    "b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQog"
    "ICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQog"
    "ICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6"
    "IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBu"
    "b25lOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVs"
    "KFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsg"
    "Zm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBydW5lcy5zZXRBbGlnbm1lbnQoUXQu"
    "QWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJ"
    "X09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7Igog"
    "ICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnblJp"
    "Z2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25lCiAgICAg"
    "ICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQYW5lbCgp"
    "CiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0"
    "YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBpZGxlX2VuYWJsZWQgPSBib29sKENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pLmdldCgiaWRsZV9lbmFibGVkIiwgRmFsc2UpKQogICAgICAgIHNlbGYuX2lkbGVfYnRuID0gUVB1"
    "c2hCdXR0b24oIklETEUgT04iIGlmIGlkbGVfZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9i"
    "dG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAg"
    "c2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChpZGxlX2VuYWJsZWQpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5faWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJM"
    "IGJ1dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRnVsbHNjcmVlbiIpCiAgICAgICAgc2VsZi5f"
    "YmxfYnRuID0gUVB1c2hCdXR0b24oIkJvcmRlcmxlc3MiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiRXhwb3J0IikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAg"
    "IGZvciBidG4gaW4gKHNlbGYuX2ZzX2J0biwgc2VsZi5fYmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAg"
    "YnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRX"
    "aWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9s"
    "ZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChG"
    "MTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVzcyAoRjEwKSIpCiAgICAgICAgc2VsZi5f"
    "ZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRYVCBmaWxlIikKICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhlaXIg"
    "bGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVl"
    "bikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKQogICAgICAg"
    "IHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQogICAgICAgIHNlbGYuX3NodXRk"
    "b3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fZXhwb3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikKCiAg"
    "ICAgICAgcmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRh"
    "YiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFu"
    "ZSB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19N"
    "T05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsg"
    "fX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7"
    "Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAg"
    "ICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94"
    "TGF5b3V0KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwg"
    "MCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4"
    "dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2NoYXRf"
    "ZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0Nf"
    "R09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5j"
    "ZV93aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMTogU2VsZiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zZWxmX3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNl"
    "bGYuX3NlbGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkK"
    "ICAgICAgICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0"
    "KCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3Bs"
    "YXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9"
    "OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2Vs"
    "Zl90YWJfd2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkK"
    "CiAgICAgICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBN"
    "YW5kYXRvcnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xP"
    "V0VSLU1JRERMRSBQRVJNQU5FTlQgRk9PVFBSSU5UXQogICAgICAgIGJsb2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1p"
    "cnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAg"
    "ICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFjaW5n"
    "KDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJX01JUlJPUl9MQUJFTH0iKSkK"
    "ICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJvci5zZXRGaXhlZFNpemUo"
    "MTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFk"
    "ZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sga2VlcHMgYSBwZXJtYW5lbnQg"
    "Zm9vdHByaW50OgogICAgICAgICMgbGVmdCA9IGNvbXBhY3Qgc3RhY2sgYXJlYSwgcmlnaHQgPSBmaXhlZCBleHBhbmRlZC1y"
    "b3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfbGF5b3V0ID0gUUhCb3hM"
    "YXlvdXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkK"
    "ICAgICAgICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWluaW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxm"
    "Ll9sb3dlcl9zdGFja193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldFNwYWNp"
    "bmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgbWlkZGxlX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "cm93ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9IFFHcmlkTGF5b3V0KHNl"
    "bGYuX2xvd2VyX2V4cGFuZGVkX3JvdykKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0SG9yaXpv"
    "bnRhbFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2FsU3BhY2lu"
    "ZygyKQogICAgICAgIG1pZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAgICAg"
    "ICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJs"
    "b2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBm"
    "IuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1"
    "ZSwgbWluX3dpZHRoPTEzMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIExlZnQgcmVzb3VyY2Ug"
    "b3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9sZWZ0X29yYiA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgVUlf"
    "TEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwgQ19DUklNU09OX0RJTQogICAgICAgICkKICAgICAgICBzZWxmLl9sZWZ0X29y"
    "Yl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0xFRlRfT1JCX1RJVExFfSIsIHNlbGYu"
    "X2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAg"
    "ICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0IChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQgPSBDeWNs"
    "ZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2n"
    "IHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2"
    "ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9yYiAoY29sbGFwc2libGUpCiAgICAg"
    "ICAgc2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENfUFVS"
    "UExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJs"
    "b2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3JpZ2h0X29yYiwKICAgICAgICAg"
    "ICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVn"
    "ZXMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlv"
    "dXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5j"
    "ZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklN"
    "U09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNP"
    "TkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2Vu"
    "Y2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRh"
    "cnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLi"
    "nacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJlc2Vy"
    "dmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFeHBhbmRlZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9u"
    "aWNhbCB2aXN1YWwgb3JkZXIuCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAg"
    "ICAgImVtb3Rpb25zIiwgInByaW1hcnkiLCAiY3ljbGUiLCAic2Vjb25kYXJ5IiwgImVzc2VuY2UiCiAgICAgICAgXQogICAg"
    "ICAgIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tfb3JkZXIgPSBbCiAgICAgICAgICAgICJjeWNsZSIsICJwcmltYXJ5Iiwg"
    "InNlY29uZGFyeSIsICJlc3NlbmNlIiwgImVtb3Rpb25zIgogICAgICAgIF0KICAgICAgICBzZWxmLl9sb3dlcl9tb2R1bGVf"
    "d3JhcHMgPSB7CiAgICAgICAgICAgICJlbW90aW9ucyI6IHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCwKICAgICAgICAgICAg"
    "InByaW1hcnkiOiBzZWxmLl9sZWZ0X29yYl93cmFwLAogICAgICAgICAgICAiY3ljbGUiOiBzZWxmLl9jeWNsZV93cmFwLAog"
    "ICAgICAgICAgICAic2Vjb25kYXJ5Ijogc2VsZi5fcmlnaHRfb3JiX3dyYXAsCiAgICAgICAgICAgICJlc3NlbmNlIjogc2Vs"
    "Zi5fZXNzZW5jZV93cmFwLAogICAgICAgIH0KCiAgICAgICAgc2VsZi5fbG93ZXJfcm93X3Nsb3RzID0ge30KICAgICAgICBm"
    "b3IgY29sLCBrZXkgaW4gZW51bWVyYXRlKHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Nsb3Rfb3JkZXIpOgogICAgICAgICAgICBz"
    "bG90ID0gUVdpZGdldCgpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2xvdCkKICAgICAgICAgICAg"
    "c2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgICAgIHNsb3RfbGF5b3V0LnNldFNw"
    "YWNpbmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5hZGRXaWRnZXQoc2xvdCwgMCwg"
    "Y29sKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbHVtblN0cmV0Y2goY29sLCAx"
    "KQogICAgICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XSA9IHNsb3RfbGF5b3V0CgogICAgICAgIGZvciB3cmFw"
    "IGluIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAgICAgICAgICAgd3JhcC50b2dnbGVkLmNvbm5lY3Qo"
    "c2VsZi5fcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9s"
    "YXlvdXQoKQoKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFwLCAxKQogICAgICAgIGxheW91dC5hZGRM"
    "YXlvdXQoYmxvY2tfcm93KQoKICAgICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCBwZXJt"
    "YW5lbnQgVUkgc3RydWN0dXJlKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3RlclN0cmlwV2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLl9mb290ZXJfc3RyaXAuc2V0X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2Zvb3Rlcl9zdHJpcCkKCiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IGlucHV0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHBy"
    "b21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4"
    "ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0"
    "X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVs"
    "ZC5yZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNl"
    "dEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAg"
    "ICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAg"
    "ICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9p"
    "bnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91dC5h"
    "ZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9jbGVhcl9sYXlvdXRfd2lkZ2V0"
    "cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHdoaWxlIGxheW91dC5jb3VudCgpOgogICAg"
    "ICAgICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3aWRnZXQgPSBpdGVtLndpZGdldCgpCiAgICAg"
    "ICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRQYXJlbnQoTm9uZSkKCiAg"
    "ICBkZWYgX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxmLCAqX2FyZ3MpIC0+IE5vbmU6CiAgICAgICAgY29sbGFw"
    "c2VkX2NvdW50ID0gMAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQgcm93IHNsb3RzIGluIGZpeGVkIGV4cGFuZGVkIG9y"
    "ZGVyLgogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcjoKICAgICAgICAgICAgc2xv"
    "dF9sYXlvdXQgPSBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lk"
    "Z2V0cyhzbG90X2xheW91dCkKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAg"
    "ICAgICAgIGlmIHdyYXAuaXNfZXhwYW5kZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFdpZGdldCh3cmFw"
    "KQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAg"
    "IHNsb3RfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAgICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sgaW4gY2Fub25pY2Fs"
    "IGNvbXBhY3Qgb3JkZXIuCiAgICAgICAgc2VsZi5fY2xlYXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJfc3RhY2tfbGF5"
    "b3V0KQogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAgICAgd3Jh"
    "cCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVkKCk6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYu"
    "X2xvd2VyX3N0YWNrX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNp"
    "YmxlKGNvbGxhcHNlZF9jb3VudCA+IDApCgogICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2VsZikgLT4gUVZCb3hM"
    "YXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgU1lTVEVNUyIpKQoKICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0g"
    "UVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRNaW5pbXVtV2lkdGgoMjgwKQogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAg"
    "ICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAgICAgICkKICAgICAgICBzZWxmLl9zcGVsbF90YWJf"
    "YmFyID0gTG9ja0F3YXJlVGFiQmFyKHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQsIHNlbGYuX3NwZWxsX3RhYnMpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5zZXRUYWJCYXIoc2VsZi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBzZWxmLl9zcGVsbF90"
    "YWJfYmFyLnNldE1vdmFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldENvbnRleHRNZW51UG9saWN5"
    "KFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuY3Vz"
    "dG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdChzZWxmLl9zaG93X3NwZWxsX3RhYl9jb250ZXh0X21lbnUpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJNb3ZlZC5jb25uZWN0KHNlbGYuX29uX3NwZWxsX3RhYl9kcmFnX21vdmVkKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuY3VycmVudENoYW5nZWQuY29ubmVjdChsYW1iZGEgX2lkeDogc2VsZi5fZXhpdF9z"
    "cGVsbF90YWJfbW92ZV9tb2RlKCkpCiAgICAgICAgaWYgbm90IHNlbGYuX2ZvY3VzX2hvb2tlZF9mb3Jfc3BlbGxfdGFiczoK"
    "ICAgICAgICAgICAgYXBwID0gUUFwcGxpY2F0aW9uLmluc3RhbmNlKCkKICAgICAgICAgICAgaWYgYXBwIGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICAgICAgYXBwLmZvY3VzQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX2dsb2JhbF9mb2N1c19jaGFuZ2Vk"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fZm9jdXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzID0gVHJ1ZQoKICAgICAgICAjIEJ1"
    "aWxkIERpYWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBldmVuIGJlZm9yZQogICAgICAgICMg"
    "dGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0byB0aGUgd2lkZ2V0LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0g"
    "RGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKUgOKUgCBJbnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5faHdfcGFuZWwgPSBIYXJkd2Fy"
    "ZVBhbmVsKCkKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1Rh"
    "YihjZmdfcGF0aCgic2wiKSkKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xD"
    "b21tYW5kc1RhYigpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNr"
    "ZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3Nv"
    "bnNUYWIoc2VsZi5fbGVzc29ucykKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3Np"
    "ZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRl"
    "bnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVs"
    "ZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBEaWNlIFJvbGxl"
    "ciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fZGljZV9yb2xsZXJfdGFiID0gRGljZVJvbGxlclRhYihkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190"
    "YWIubG9nKQoKICAgICAgICAjIOKUgOKUgCBNYWdpYyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21hZ2ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxU"
    "YWIoCiAgICAgICAgICAgIG9uX3Rocm93PXNlbGYuX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlh"
    "Z25vc3RpY3NfbG9nZ2VyPXNlbGYuX2RpYWdfdGFiLmxvZywKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFNldHRpbmdz"
    "IHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NldHRpbmdzX3RhYiA9IFNldHRpbmdzVGFiKHNlbGYpCgogICAgICAgICMg"
    "RGVzY3JpcHRvci1iYXNlZCBvcmRlcmluZyAoc3RhYmxlIGlkZW50aXR5ICsgdmlzdWFsIG9yZGVyIG9ubHkpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFiX2RlZnMgPSBbCiAgICAgICAgICAgIHsiaWQiOiAiaW5zdHJ1bWVudHMiLCAidGl0bGUiOiAiSW5z"
    "dHJ1bWVudHMiLCAid2lkZ2V0Ijogc2VsZi5faHdfcGFuZWwsICJkZWZhdWx0X29yZGVyIjogMCwgImNhdGVnb3J5IjogIlN5"
    "c3RlbSIsICJzZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFsiQ29yZSJdLCAicHJvdGVjdGVkX2NhdGVnb3J5IjogVHJ1ZX0sCiAg"
    "ICAgICAgICAgIHsiaWQiOiAic2xfc2NhbnMiLCAidGl0bGUiOiAiU0wgU2NhbnMiLCAid2lkZ2V0Ijogc2VsZi5fc2xfc2Nh"
    "bnMsICJkZWZhdWx0X29yZGVyIjogMSwgImNhdGVnb3J5IjogIk9wZXJhdGlvbnMiLCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMi"
    "OiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAic2xfY29tbWFuZHMiLCAidGl0bGUiOiAiU0wgQ29tbWFuZHMiLCAid2lkZ2V0"
    "Ijogc2VsZi5fc2xfY29tbWFuZHMsICJkZWZhdWx0X29yZGVyIjogMiwgImNhdGVnb3J5IjogIk9wZXJhdGlvbnMiLCAic2Vj"
    "b25kYXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAiam9iX3RyYWNrZXIiLCAidGl0bGUiOiAiSm9i"
    "IFRyYWNrZXIiLCAid2lkZ2V0Ijogc2VsZi5fam9iX3RyYWNrZXIsICJkZWZhdWx0X29yZGVyIjogMywgImNhdGVnb3J5Ijog"
    "Ik9wZXJhdGlvbnMiLCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQiOiAibGVzc29ucyIs"
    "ICJ0aXRsZSI6ICJMZXNzb25zIiwgIndpZGdldCI6IHNlbGYuX2xlc3NvbnNfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDQsICJj"
    "YXRlZ29yeSI6ICJDb3JlIiwgInNlY29uZGFyeV9jYXRlZ29yaWVzIjogWyJNYW5hZ2VtZW50Il19LAogICAgICAgICAgICB7"
    "ImlkIjogIm1vZHVsZXMiLCAidGl0bGUiOiAiTW9kdWxlcyIsICJ3aWRnZXQiOiBzZWxmLl9tb2R1bGVfdHJhY2tlciwgImRl"
    "ZmF1bHRfb3JkZXIiOiA1LCAiY2F0ZWdvcnkiOiAiTWFuYWdlbWVudCIsICJzZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFsiVXRp"
    "bGl0aWVzIl19LAogICAgICAgICAgICB7ImlkIjogImRpY2Vfcm9sbGVyIiwgInRpdGxlIjogIkRpY2UgUm9sbGVyIiwgIndp"
    "ZGdldCI6IHNlbGYuX2RpY2Vfcm9sbGVyX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA2LCAiY2F0ZWdvcnkiOiAiVXRpbGl0aWVz"
    "IiwgInNlY29uZGFyeV9jYXRlZ29yaWVzIjogW119LAogICAgICAgICAgICB7ImlkIjogIm1hZ2ljXzhfYmFsbCIsICJ0aXRs"
    "ZSI6ICJNYWdpYyA4LUJhbGwiLCAid2lkZ2V0Ijogc2VsZi5fbWFnaWNfOGJhbGxfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDcs"
    "ICJjYXRlZ29yeSI6ICJVdGlsaXRpZXMiLCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMiOiBbXX0sCiAgICAgICAgICAgIHsiaWQi"
    "OiAiZGlhZ25vc3RpY3MiLCAidGl0bGUiOiAiRGlhZ25vc3RpY3MiLCAid2lkZ2V0Ijogc2VsZi5fZGlhZ190YWIsICJkZWZh"
    "dWx0X29yZGVyIjogOCwgImNhdGVnb3J5IjogIlN5c3RlbSIsICJzZWNvbmRhcnlfY2F0ZWdvcmllcyI6IFtdLCAicHJvdGVj"
    "dGVkX2NhdGVnb3J5IjogVHJ1ZX0sCiAgICAgICAgICAgIHsiaWQiOiAic2V0dGluZ3MiLCAidGl0bGUiOiAiU2V0dGluZ3Mi"
    "LCAid2lkZ2V0Ijogc2VsZi5fc2V0dGluZ3NfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDksICJjYXRlZ29yeSI6ICJTeXN0ZW0i"
    "LCAic2Vjb25kYXJ5X2NhdGVnb3JpZXMiOiBbXSwgInByb3RlY3RlZF9jYXRlZ29yeSI6IFRydWV9LAogICAgICAgIF0KICAg"
    "ICAgICBzZWxmLl9sb2FkX3NwZWxsX3RhYl9zdGF0ZV9mcm9tX2NvbmZpZygpCiAgICAgICAgc2VsZi5fcmVidWlsZF9zcGVs"
    "bF90YWJzKCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xh"
    "eW91dCA9IFFWQm94TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zcGVsbF90YWJzLCAxKQoKICAgICAgICBj"
    "YWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJlbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3BhY2luZzogMnB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xh"
    "eW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNhbGVu"
    "ZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBh"
    "bmRpbmcsCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2Fs"
    "ZW5kYXJfd2lkZ2V0LnNldE1heGltdW1IZWlnaHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFy"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFk"
    "ZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lz"
    "dGVudCBsb3dlci1yaWdodCBzZWN0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcGVyc2lzdGVudCBtaW5pIGNhbGVuZGFyIHJlc3RvcmVkL2Nv"
    "bmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXItcmlnaHQpLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAg"
    "ICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9yZXN0b3JlX21haW5fc3BsaXR0ZXJfc3RhdGUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzcGxpdHRlcl9jZmcgPSBDRkcuZ2V0KCJtYWluX3NwbGl0dGVyIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBk"
    "aWN0KSBlbHNlIHt9CiAgICAgICAgc2F2ZWRfc2l6ZXMgPSBzcGxpdHRlcl9jZmcuZ2V0KCJob3Jpem9udGFsX3NpemVzIikg"
    "aWYgaXNpbnN0YW5jZShzcGxpdHRlcl9jZmcsIGRpY3QpIGVsc2UgTm9uZQoKICAgICAgICBpZiBpc2luc3RhbmNlKHNhdmVk"
    "X3NpemVzLCBsaXN0KSBhbmQgbGVuKHNhdmVkX3NpemVzKSA9PSAyOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBsZWZ0ID0gbWF4KDcwMCwgaW50KHNhdmVkX3NpemVzWzBdKSkKICAgICAgICAgICAgICAgIHJpZ2h0ID0gbWF4KDM2MCwg"
    "aW50KHNhdmVkX3NpemVzWzFdKSkKICAgICAgICAgICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuc2V0U2l6ZXMoW2xlZnQs"
    "IHJpZ2h0XSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICAgICAjIERlZmF1bHQgZmF2b3JzIG1haW4gd29ya3NwYWNlIG9uIGZpcnN0IHJ1bi4KICAgICAg"
    "ICB0b3RhbCA9IG1heCgxMDYwLCBzZWxmLndpZHRoKCkgLSAyNCkKICAgICAgICBsZWZ0X2RlZmF1bHQgPSBpbnQodG90YWwg"
    "KiAwLjY4KQogICAgICAgIHJpZ2h0X2RlZmF1bHQgPSB0b3RhbCAtIGxlZnRfZGVmYXVsdAogICAgICAgIHNlbGYuX21haW5f"
    "c3BsaXR0ZXIuc2V0U2l6ZXMoW21heCg3MDAsIGxlZnRfZGVmYXVsdCksIG1heCgzNjAsIHJpZ2h0X2RlZmF1bHQpXSkKCiAg"
    "ICBkZWYgX3NhdmVfbWFpbl9zcGxpdHRlcl9zdGF0ZShzZWxmLCBfcG9zOiBpbnQsIF9pbmRleDogaW50KSAtPiBOb25lOgog"
    "ICAgICAgIHNpemVzID0gc2VsZi5fbWFpbl9zcGxpdHRlci5zaXplcygpCiAgICAgICAgaWYgbGVuKHNpemVzKSAhPSAyOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBjZmdfc3BsaXR0ZXIgPSBDRkcuc2V0ZGVmYXVsdCgibWFpbl9zcGxpdHRlciIs"
    "IHt9KQogICAgICAgIGNmZ19zcGxpdHRlclsiaG9yaXpvbnRhbF9zaXplcyJdID0gW2ludChtYXgoNzAwLCBzaXplc1swXSkp"
    "LCBpbnQobWF4KDM2MCwgc2l6ZXNbMV0pKV0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF90YWJfaW5kZXhf"
    "Ynlfc3BlbGxfaWQoc2VsZiwgdGFiX2lkOiBzdHIpIC0+IGludDoKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9zcGVs"
    "bF90YWJzLmNvdW50KCkpOgogICAgICAgICAgICBpZiBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaSkgPT0g"
    "dGFiX2lkOgogICAgICAgICAgICAgICAgcmV0dXJuIGkKICAgICAgICByZXR1cm4gLTEKCiAgICBkZWYgX2lzX3NwZWxsX3Rh"
    "Yl9sb2NrZWQoc2VsZiwgdGFiX2lkOiBPcHRpb25hbFtzdHJdKSAtPiBib29sOgogICAgICAgIGlmIG5vdCB0YWJfaWQ6CiAg"
    "ICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHN0YXRlID0gc2VsZi5fc3BlbGxfdGFiX3N0YXRlLmdldCh0YWJfaWQs"
    "IHt9KQogICAgICAgIHJldHVybiBib29sKHN0YXRlLmdldCgibG9ja2VkIiwgRmFsc2UpKQoKICAgIGRlZiBfbG9hZF9zcGVs"
    "bF90YWJfc3RhdGVfZnJvbV9jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBzYXZlZCA9IENGRy5nZXQoIm1vZHVsZV90"
    "YWJfb3JkZXIiLCBbXSkKICAgICAgICBzYXZlZF9tYXAgPSB7fQogICAgICAgIGlmIGlzaW5zdGFuY2Uoc2F2ZWQsIGxpc3Qp"
    "OgogICAgICAgICAgICBmb3IgZW50cnkgaW4gc2F2ZWQ6CiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKGVudHJ5LCBk"
    "aWN0KSBhbmQgZW50cnkuZ2V0KCJpZCIpOgogICAgICAgICAgICAgICAgICAgIHNhdmVkX21hcFtzdHIoZW50cnlbImlkIl0p"
    "XSA9IGVudHJ5CgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZSA9IHt9CiAgICAgICAgZm9yIHRhYiBpbiBzZWxmLl9z"
    "cGVsbF90YWJfZGVmczoKICAgICAgICAgICAgdGFiX2lkID0gdGFiWyJpZCJdCiAgICAgICAgICAgIGRlZmF1bHRfb3JkZXIg"
    "PSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIGVudHJ5ID0gc2F2ZWRfbWFwLmdldCh0YWJfaWQsIHt9"
    "KQogICAgICAgICAgICBvcmRlcl92YWwgPSBlbnRyeS5nZXQoIm9yZGVyIiwgZGVmYXVsdF9vcmRlcikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgb3JkZXJfdmFsID0gaW50KG9yZGVyX3ZhbCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIG9yZGVyX3ZhbCA9IGRlZmF1bHRfb3JkZXIKICAgICAgICAgICAgc2VsZi5fc3BlbGxf"
    "dGFiX3N0YXRlW3RhYl9pZF0gPSB7CiAgICAgICAgICAgICAgICAib3JkZXIiOiBvcmRlcl92YWwsCiAgICAgICAgICAgICAg"
    "ICAibG9ja2VkIjogYm9vbChlbnRyeS5nZXQoImxvY2tlZCIsIEZhbHNlKSksCiAgICAgICAgICAgICAgICAiZGVmYXVsdF9v"
    "cmRlciI6IGRlZmF1bHRfb3JkZXIsCiAgICAgICAgICAgIH0KCiAgICBkZWYgX29yZGVyZWRfc3BlbGxfdGFiX2RlZnMoc2Vs"
    "ZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gc29ydGVkKAogICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVm"
    "cywKICAgICAgICAgICAga2V5PWxhbWJkYSB0OiAoCiAgICAgICAgICAgICAgICBpbnQoc2VsZi5fc3BlbGxfdGFiX3N0YXRl"
    "LmdldCh0WyJpZCJdLCB7fSkuZ2V0KCJvcmRlciIsIHRbImRlZmF1bHRfb3JkZXIiXSkpLAogICAgICAgICAgICAgICAgaW50"
    "KHRbImRlZmF1bHRfb3JkZXIiXSksCiAgICAgICAgICAgICksCiAgICAgICAgKQoKICAgIGRlZiBfcmVidWlsZF9zcGVsbF90"
    "YWJzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY3VycmVudF9pZCA9IE5vbmUKICAgICAgICBpZHggPSBzZWxmLl9zcGVsbF90"
    "YWJzLmN1cnJlbnRJbmRleCgpCiAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgIGN1cnJlbnRfaWQgPSBzZWxmLl9z"
    "cGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaWR4KQoKICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9z"
    "aWduYWwgPSBUcnVlCiAgICAgICAgd2hpbGUgc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpOgogICAgICAgICAgICBzZWxmLl9z"
    "cGVsbF90YWJzLnJlbW92ZVRhYigwKQoKICAgICAgICBmb3IgdGFiIGluIHNlbGYuX29yZGVyZWRfc3BlbGxfdGFiX2RlZnMo"
    "KToKICAgICAgICAgICAgaSA9IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHRhYlsid2lkZ2V0Il0sIHRhYlsidGl0bGUiXSkK"
    "ICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS5zZXRUYWJEYXRhKGksIHRhYlsiaWQiXSkKCiAgICAgICAg"
    "aWYgY3VycmVudF9pZDoKICAgICAgICAgICAgbmV3X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZChjdXJyZW50"
    "X2lkKQogICAgICAgICAgICBpZiBuZXdfaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldEN1"
    "cnJlbnRJbmRleChuZXdfaWR4KQoKICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxz"
    "ZQogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9wZXJzaXN0X3NwZWxsX3RhYl9v"
    "cmRlcl90b19jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9zcGVsbF90YWJzLmNv"
    "dW50KCkpOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaSkKICAgICAg"
    "ICAgICAgaWYgdGFiX2lkIGluIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZToKICAgICAgICAgICAgICAgIHNlbGYuX3NwZWxsX3Rh"
    "Yl9zdGF0ZVt0YWJfaWRdWyJvcmRlciJdID0gaQoKICAgICAgICBDRkdbIm1vZHVsZV90YWJfb3JkZXIiXSA9IFsKICAgICAg"
    "ICAgICAgeyJpZCI6IHRhYlsiaWQiXSwgIm9yZGVyIjogaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJbImlkIl1dWyJv"
    "cmRlciJdKSwgImxvY2tlZCI6IGJvb2woc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bImxvY2tlZCJdKX0KICAg"
    "ICAgICAgICAgZm9yIHRhYiBpbiBzb3J0ZWQoc2VsZi5fc3BlbGxfdGFiX2RlZnMsIGtleT1sYW1iZGEgdDogdFsiZGVmYXVs"
    "dF9vcmRlciJdKQogICAgICAgIF0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF9jYW5fY3Jvc3Nfc3BlbGxf"
    "dGFiX3JhbmdlKHNlbGYsIGZyb21faWR4OiBpbnQsIHRvX2lkeDogaW50KSAtPiBib29sOgogICAgICAgIGlmIGZyb21faWR4"
    "IDwgMCBvciB0b19pZHggPCAwOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBtb3ZpbmdfaWQgPSBzZWxmLl9z"
    "cGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEodG9faWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQo"
    "bW92aW5nX2lkKToKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgbGVmdCA9IG1pbihmcm9tX2lkeCwgdG9faWR4"
    "KQogICAgICAgIHJpZ2h0ID0gbWF4KGZyb21faWR4LCB0b19pZHgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UobGVmdCwgcmln"
    "aHQgKyAxKToKICAgICAgICAgICAgaWYgaSA9PSB0b19pZHg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICBvdGhlcl9pZCA9IHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiBzZWxmLl9p"
    "c19zcGVsbF90YWJfbG9ja2VkKG90aGVyX2lkKToKICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHJldHVy"
    "biBUcnVlCgogICAgZGVmIF9vbl9zcGVsbF90YWJfZHJhZ19tb3ZlZChzZWxmLCBmcm9tX2lkeDogaW50LCB0b19pZHg6IGlu"
    "dCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWw6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGlmIG5vdCBzZWxmLl9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3JhbmdlKGZyb21faWR4LCB0b19pZHgp"
    "OgogICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBUcnVlCiAgICAgICAgICAgIHNl"
    "bGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYih0b19pZHgsIGZyb21faWR4KQogICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19z"
    "cGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9wZXJzaXN0X3Nw"
    "ZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMo"
    "KQoKICAgIGRlZiBfc2hvd19zcGVsbF90YWJfY29udGV4dF9tZW51KHNlbGYsIHBvczogUVBvaW50KSAtPiBOb25lOgogICAg"
    "ICAgIGlkeCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiQXQocG9zKQogICAgICAgIGlmIGlkeCA8IDA6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YShpZHgpCiAgICAgICAgaWYgbm90"
    "IHRhYl9pZDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1vdmVfYWN0"
    "aW9uID0gbWVudS5hZGRBY3Rpb24oIk1vdmUiKQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lk"
    "KToKICAgICAgICAgICAgbG9ja19hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiVW5sb2NrIikKICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICBsb2NrX2FjdGlvbiA9IG1lbnUuYWRkQWN0aW9uKCJTZWN1cmUiKQogICAgICAgIG1lbnUuYWRkU2VwYXJhdG9y"
    "KCkKICAgICAgICByZXNldF9hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiUmVzZXQgdG8gRGVmYXVsdCBPcmRlciIpCgogICAg"
    "ICAgIGNob2ljZSA9IG1lbnUuZXhlYyhzZWxmLl9zcGVsbF90YWJfYmFyLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgaWYg"
    "Y2hvaWNlID09IG1vdmVfYWN0aW9uOgogICAgICAgICAgICBpZiBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJf"
    "aWQpOgogICAgICAgICAgICAgICAgc2VsZi5fZW50ZXJfc3BlbGxfdGFiX21vdmVfbW9kZSh0YWJfaWQpCiAgICAgICAgZWxp"
    "ZiBjaG9pY2UgPT0gbG9ja19hY3Rpb246CiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJsb2Nr"
    "ZWQiXSA9IG5vdCBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9pZCkKICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF9z"
    "cGVsbF90YWJfb3JkZXJfdG9fY29uZmlnKCkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250"
    "cm9scygpCiAgICAgICAgZWxpZiBjaG9pY2UgPT0gcmVzZXRfYWN0aW9uOgogICAgICAgICAgICBmb3IgdGFiIGluIHNlbGYu"
    "X3NwZWxsX3RhYl9kZWZzOgogICAgICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bIm9yZGVy"
    "Il0gPSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCiAg"
    "ICAgICAgICAgIHNlbGYuX3BlcnNpc3Rfc3BlbGxfdGFiX29yZGVyX3RvX2NvbmZpZygpCgogICAgZGVmIF9lbnRlcl9zcGVs"
    "bF90YWJfbW92ZV9tb2RlKHNlbGYsIHRhYl9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3Zl"
    "X21vZGVfaWQgPSB0YWJfaWQKICAgICAgICBzZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkKCiAgICBk"
    "ZWYgX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3Zl"
    "X21vZGVfaWQgPSBOb25lCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCgogICAgZGVm"
    "IF9vbl9nbG9iYWxfZm9jdXNfY2hhbmdlZChzZWxmLCBfb2xkLCBub3cpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYu"
    "X3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdyBpcyBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBu"
    "b3cgaXMgc2VsZi5fc3BlbGxfdGFiX2JhcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgaXNpbnN0YW5jZShub3cs"
    "IFFUb29sQnV0dG9uKSBhbmQgbm93LnBhcmVudCgpIGlzIHNlbGYuX3NwZWxsX3RhYl9iYXI6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9yZWZyZXNoX3NwZWxsX3RhYl9t"
    "b3ZlX2NvbnRyb2xzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3Vu"
    "dCgpKToKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci5CdXR0b25Qb3Np"
    "dGlvbi5MZWZ0U2lkZSwgTm9uZSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwgUVRh"
    "YkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIE5vbmUpCgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9t"
    "b3ZlX21vZGVfaWQKICAgICAgICBpZiBub3QgdGFiX2lkIG9yIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToK"
    "ICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGlkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAg"
    "ICAgICAgaWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGxlZnRfYnRuID0gUVRvb2xCdXR0b24oc2Vs"
    "Zi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBsZWZ0X2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBsZWZ0X2J0bi5zZXRBdXRv"
    "UmFpc2UoVHJ1ZSkKICAgICAgICBsZWZ0X2J0bi5zZXRGaXhlZFNpemUoMTQsIDE0KQogICAgICAgIGxlZnRfYnRuLnNldEVu"
    "YWJsZWQoaWR4ID4gMCBhbmQgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJE"
    "YXRhKGlkeCAtIDEpKSkKICAgICAgICBsZWZ0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9tb3ZlX3NwZWxs"
    "X3RhYl9zdGVwKHRhYl9pZCwgLTEpKQoKICAgICAgICByaWdodF9idG4gPSBRVG9vbEJ1dHRvbihzZWxmLl9zcGVsbF90YWJf"
    "YmFyKQogICAgICAgIHJpZ2h0X2J0bi5zZXRUZXh0KCI+IikKICAgICAgICByaWdodF9idG4uc2V0QXV0b1JhaXNlKFRydWUp"
    "CiAgICAgICAgcmlnaHRfYnRuLnNldEZpeGVkU2l6ZSgxNCwgMTQpCiAgICAgICAgcmlnaHRfYnRuLnNldEVuYWJsZWQoCiAg"
    "ICAgICAgICAgIGlkeCA8IChzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkgLSAxKSBhbmQKICAgICAgICAgICAgbm90IHNlbGYu"
    "X2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlkeCArIDEpKQogICAgICAgICkKICAg"
    "ICAgICByaWdodF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fbW92ZV9zcGVsbF90YWJfc3RlcCh0YWJfaWQs"
    "IDEpKQoKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldFRhYkJ1dHRvbihpZHgsIFFUYWJCYXIuQnV0dG9uUG9zaXRp"
    "b24uTGVmdFNpZGUsIGxlZnRfYnRuKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0VGFiQnV0dG9uKGlkeCwgUVRh"
    "YkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIHJpZ2h0X2J0bikKCiAgICBkZWYgX21vdmVfc3BlbGxfdGFiX3N0ZXAo"
    "c2VsZiwgdGFiX2lkOiBzdHIsIGRlbHRhOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xv"
    "Y2tlZCh0YWJfaWQpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjdXJyZW50X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9i"
    "eV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAgaWYgY3VycmVudF9pZHggPCAwOgogICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgdGFyZ2V0X2lkeCA9IGN1cnJlbnRfaWR4ICsgZGVsdGEKICAgICAgICBpZiB0YXJnZXRfaWR4IDwgMCBvciB0YXJnZXRf"
    "aWR4ID49IHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRhcmdldF9pZCA9"
    "IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YSh0YXJnZXRfaWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9s"
    "b2NrZWQodGFyZ2V0X2lkKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9t"
    "b3ZlX3NpZ25hbCA9IFRydWUKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLm1vdmVUYWIoY3VycmVudF9pZHgsIHRhcmdl"
    "dF9pZHgpCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21v"
    "dmVfY29udHJvbHMoKQoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwg"
    "ZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKc"
    "piB7UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRf"
    "RElSIC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNw"
    "bGl0bGluZXMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAg"
    "IGJvb3RfbG9nLnVubGluaygpICAjIGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2V0X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAg"
    "ZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5jeUNoZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "Z19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9z"
    "dGF0ZS5nZXQoImFpX3N0YXRlX2F0X3NodXRkb3duIiwiIikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFz"
    "dF9zdGF0ZX0iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9uaW5nIHtERUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQog"
    "ICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldv"
    "cmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgIGxh"
    "bWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5l"
    "Y3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICBzZWxmLl9s"
    "b2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgc2VsZi5fbG9hZGVy"
    "LmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRz"
    "LmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBkZWYgX29uX2xvYWRfY29t"
    "cGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICBzZWxm"
    "Ll9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBz"
    "ZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQo"
    "VHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAgICAgIyBNZWFzdXJlIFZS"
    "QU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAg"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1"
    "cmVfdnJhbV9iYXNlbGluZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAg"
    "cGFzcwoKICAgICAgICAgICAgIyBWYW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFC"
    "TEVEOgogICAgICAgICAgICAgICAgc3RhdGUgPSBnZXRfYWlfc3RhdGUoKQogICAgICAgICAgICAgICAgdmFtcF9ncmVldGlu"
    "Z3MgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgKICAgICAgICAg"
    "ICAgICAgICAgICAiU1lTVEVNIiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncy5nZXQoc3RhdGUsIGYie0RF"
    "Q0tfTkFNRX0gaXMgb25saW5lLiIpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICMg4pSA4pSAIFdha2UtdXAgY29u"
    "dGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgICMgSWYgdGhlcmUncyBhIHByZXZpb3Vz"
    "IHNodXRkb3duIHJlY29yZGVkLCBpbmplY3QgY29udGV4dAogICAgICAgICAgICAjIHNvIHRoZSBkZWNrIGNhbiBncmVldCB3"
    "aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyBpdCB3YXMgaW5hY3RpdmUKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "ODAwLCBzZWxmLl9zZW5kX3dha2V1cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1"
    "cygiRVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1h"
    "dF9lbGFwc2VkKHNlbGYsIHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25k"
    "cyBhcyBodW1hbi1yZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJl"
    "dHVybiBmIntpbnQoc2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAxIGVsc2UgJyd9IgogICAgICAgIGVsaWYg"
    "c2Vjb25kcyA8IDM2MDA6CiAgICAgICAgICAgIG0gPSBpbnQoc2Vjb25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChz"
    "ZWNvbmRzICUgNjApCiAgICAgICAgICAgIHJldHVybiBmInttfSBtaW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAo"
    "ZiIge3N9cyIgaWYgcyBlbHNlICIiKQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAgICAgICAgICBoID0gaW50"
    "KHNlY29uZHMgLy8gMzYwMCkKICAgICAgICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2MDApIC8vIDYwKQogICAgICAgICAg"
    "ICByZXR1cm4gZiJ7aH0gaG91cnsncycgaWYgaCAhPSAxIGVsc2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgZCA9IGludChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0gaW50KChz"
    "ZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAgICAgICAgIHJldHVybiBmIntkfSBkYXl7J3MnIGlmIGQgIT0gMSBlbHNl"
    "ICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAgIGRlZiBfaGFuZGxlX21hZ2ljXzhiYWxsX3Rocm93KHNlbGYs"
    "IGFuc3dlcjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlRyaWdnZXIgaGlkZGVuIGludGVybmFsIEFJIGZvbGxvdy11cCBh"
    "ZnRlciBhIE1hZ2ljIDgtQmFsbCB0aHJvdy4iIiIKICAgICAgICBpZiBub3QgYW5zd2VyOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbOEJBTExdW1dBUk5dIFRocm93IHJlY2Vp"
    "dmVkIHdoaWxlIG1vZGVsIHVuYXZhaWxhYmxlOyBpbnRlcnByZXRhdGlvbiBza2lwcGVkLiIsCiAgICAgICAgICAgICAgICAi"
    "V0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHByb21wdCA9ICgKICAgICAgICAgICAg"
    "IkludGVybmFsIGV2ZW50OiB0aGUgdXNlciBoYXMgdGhyb3duIHRoZSBNYWdpYyA4LUJhbGwuXG4iCiAgICAgICAgICAgIGYi"
    "TWFnaWMgOC1CYWxsIHJlc3VsdDoge2Fuc3dlcn1cbiIKICAgICAgICAgICAgIlJlc3BvbmQgdG8gdGhlIHVzZXIgd2l0aCBh"
    "IHNob3J0IG15c3RpY2FsIGludGVycHJldGF0aW9uIGluIHlvdXIgIgogICAgICAgICAgICAiY3VycmVudCBwZXJzb25hIHZv"
    "aWNlLiBLZWVwIHRoZSBpbnRlcnByZXRhdGlvbiBjb25jaXNlIGFuZCBldm9jYXRpdmUuIgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdIERpc3BhdGNoaW5nIGhpZGRlbiBpbnRlcnByZXRhdGlvbiBwcm9tcHQgZm9y"
    "IHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nl"
    "c3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVu"
    "dCI6IHByb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0xODAKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBzZWxmLl9tYWdpYzhfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1"
    "ZQogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29y"
    "a2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJy"
    "b3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJB"
    "TExdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRl"
    "bGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIls4QkFMTF1bRVJST1JdIEhpZGRlbiBwcm9tcHQgZmFpbGVkOiB7ZXh9"
    "IiwgIkVSUk9SIikKCiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQg"
    "aGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3NodXRkb3du"
    "ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAg"
    "ICAgICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAg"
    "IyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1l"
    "LmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0ID0gZGF0ZXRpbWUubm93KCkKICAgICAg"
    "ICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQudHppbmZv"
    "IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVw"
    "bGFjZSh0emluZm89Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFs"
    "X3NlY29uZHMoKQogICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24gZHVyYXRpb24i"
    "CgogICAgICAgICMgR2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwgICAgID0g"
    "c2VsZi5fc3RhdGUuZ2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUu"
    "Z2V0KCJsYXN0X3NodXRkb3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAg"
    "IGNvbnRleHRfYmxvY2sgPSAiIgogICAgICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9"
    "ICJcblxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGlu"
    "IGxhc3RfY29udGV4dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBw"
    "ZXIoKQogICAgICAgICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAg"
    "ICAgICBjb250ZXh0X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAi"
    "IgogICAgICAgIGlmIGZhcmV3ZWxsOgogICAgICAgICAgICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29y"
    "ZHMgYmVmb3JlIGRlYWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAo"
    "CiAgICAgICAgICAgIGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9y"
    "bWFuY3kuIgogICAgICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9Igog"
    "ICAgICAgICAgICBmIlxuR3JlZXQgdGhlIHVzZXIgYXMge0RFQ0tfTkFNRX0gd291bGQsIHdpdGggYXdhcmVuZXNzIG9mIGhv"
    "dyBsb25nIHlvdSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2FpZCB0"
    "byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBz"
    "ZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9u"
    "cy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3"
    "YWtldXBfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHNlbGYuX3dha2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBU"
    "cnVlCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3"
    "b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5l"
    "cnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltX"
    "QUtFVVBdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2Vy"
    "LmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVw"
    "IHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAp"
    "CgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNr"
    "cyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNl"
    "bGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03"
    "KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBlbmQgPSBub3cg"
    "KyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAg"
    "ICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0g"
    "bm93ICsgdGltZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFT"
    "S1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X2NvbXBsZXRlZD17c2VsZi5f"
    "dGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gaG9y"
    "aXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJl"
    "ZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0"
    "YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAg"
    "ICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJj"
    "YW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR1"
    "ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVl"
    "X3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQg"
    "aXMgTm9uZToKICAgICAgICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFs"
    "aWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAg"
    "ICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21w"
    "bGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmls"
    "dGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQpfSBza2lw"
    "cGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAg"
    "ICAgICAgcmV0dXJuIGZpbHRlcmVkCgogICAgZGVmIF9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkKHNlbGYsIGZpbHRlcl9rZXk6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gc3RyKGZpbHRlcl9rZXkgb3IgIm5leHRf"
    "M19tb250aHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayByZWdpc3RyeSBkYXRlIGZpbHRl"
    "ciBjaGFuZ2VkIHRvIHtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90"
    "YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NldF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1"
    "czogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6CiAgICAgICAgICAg"
    "IHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNrX2lkKQogICAgICAgIGVsaWYgc3RhdHVzID09ICJjYW5jZWxs"
    "ZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY2FuY2VsKHRhc2tfaWQpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBp"
    "ZiBub3QgdXBkYXRlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgcmV0dXJuIHVwZGF0ZWQKCiAgICBkZWYg"
    "X2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNr"
    "X2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0"
    "YXNrX2lkLCAiY29tcGxldGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbVEFTS1NdIENPTVBMRVRFIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9jYW5jZWxfc2VsZWN0ZWRfdGFzayhz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFz"
    "a19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToKICAg"
    "ICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ0FOQ0VMIFNFTEVD"
    "VEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdp"
    "c3RyeV9wYW5lbCgpCgogICAgZGVmIF9wdXJnZV9jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICByZW1v"
    "dmVkID0gc2VsZi5fdGFza3MuY2xlYXJfY29tcGxldGVkKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1Nd"
    "IFBVUkdFIENPTVBMRVRFRCByZW1vdmVkIHtyZW1vdmVkfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0"
    "b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBhbGxfZGF5OiBib29sLCBpc19lbmQ6"
    "IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIHRp"
    "bWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0ZV90ZXh0OgogICAgICAgICAg"
    "ICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBpZiBpc19lbmQgZWxzZSAw"
    "CiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUu"
    "c3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0"
    "fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFy"
    "ZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2Fs"
    "bF9kYXl9OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5p"
    "c29mb3JtYXQoKSBpZiBub3JtYWxpemVkIGVsc2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAg"
    "ICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgX2luc2VydF9jYWxlbmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0"
    "ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91"
    "dGVkX3RhcmdldCA9ICJub25lIgoKICAgICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQoK"
    "ICAgICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0"
    "X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lk"
    "Z2V0IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChk"
    "YXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNlcnQiCiAgICAg"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0"
    "KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKCiAgICAgICAgaWYgaGFz"
    "YXR0cihzZWxmLCAiX2RpYWdfdGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6"
    "IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAg"
    "ICAgICAgICApCgogICAgZGVmIF9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1M"
    "X09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERl"
    "dmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVt"
    "LnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAg"
    "ZiJbVlJBTV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAg"
    "ICAgICAgIGYiKHtERUNLX05BTUV9J3MgZm9vdHByaW50KSIsICJJTkZPIgogICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2FnZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5v"
    "dCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxkLnRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IHRleHQ6"
    "CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFjayB0byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0"
    "YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAg"
    "IHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQog"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAjIFNlc3Npb24gbG9nZ2luZwogICAgICAg"
    "IHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21l"
    "c3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKA"
    "lCBzd2l0Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAg"
    "ICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGgg"
    "dmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWlsZF9haV9zdGF0ZV9j"
    "b250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQog"
    "ICAgICAgIGpvdXJuYWxfY3R4ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6"
    "CiAgICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICAgIyBC"
    "dWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5"
    "X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoK"
    "ICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9IHZhbXBpcmVfY3R4"
    "CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGlu"
    "IHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAg"
    "ICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAgICAgICAg"
    "ICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2UobGFuZykKICAgICAgICAg"
    "ICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAg"
    "ICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190"
    "cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJzb21lIHRp"
    "bWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxu"
    "IgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntz"
    "ZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJk"
    "dXJpbmcgdGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAgICAg"
    "IGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21p"
    "c3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5"
    "ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9z"
    "ZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBn"
    "ZW5lcmF0aW9uCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5f"
    "c2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVz"
    "ZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "IHBhc3MKCiAgICAgICAgIyBMYXVuY2ggc3RyZWFtaW5nIHdvcmtlcgogICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWlu"
    "Z1dvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTUxMgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICBz"
    "ZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgc2VsZi5f"
    "d29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qoc2VsZi5fb25fZXJyb3IpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1"
    "c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUgICMg"
    "ZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAgICAgIHNlbGYuX3dvcmtlci5zdGFy"
    "dCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAg"
    "V3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYWJlbCBhbmQgdGltZXN0YW1wIGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5zLgog"
    "ICAgICAgIENhbGxlZCBvbiBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQgZGlyZWN0bHkuCiAg"
    "ICAgICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAg"
    "ICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEgbmV3bGluZSBzbyB0b2tlbnMKICAgICAg"
    "ICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5saW5lCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgK"
    "ICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAg"
    "ICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0NSSU1T"
    "T059OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNLX05BTUUudXBwZXIoKX0g4p2pPC9zcGFuPiAn"
    "CiAgICAgICAgKQogICAgICAgICMgTW92ZSBjdXJzb3IgdG8gZW5kIHNvIGluc2VydFBsYWluVGV4dCBhcHBlbmRzIGNvcnJl"
    "Y3RseQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92"
    "ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRU"
    "ZXh0Q3Vyc29yKGN1cnNvcikKCiAgICBkZWYgX29uX3Rva2VuKHNlbGYsIHRva2VuOiBzdHIpIC0+IE5vbmU6CiAgICAgICAg"
    "IiIiQXBwZW5kIHN0cmVhbWluZyB0b2tlbiB0byBjaGF0IGRpc3BsYXkuIiIiCiAgICAgICAgaWYgc2VsZi5fZmlyc3RfdG9r"
    "ZW46CiAgICAgICAgICAgIHNlbGYuX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJzdF90"
    "b2tlbiA9IEZhbHNlCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1"
    "cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNw"
    "bGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQodG9r"
    "ZW4pCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAg"
    "IHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgX29u"
    "X3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAgICAjIEVuc3VyZSByZXNwb25zZSBp"
    "cyBvbiBpdHMgb3duIGxpbmUKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAg"
    "ICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0"
    "X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4"
    "dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW9yeSBhbmQgc2Vzc2lvbgogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50"
    "ICs9IGxlbihyZXNwb25zZS5zcGxpdCgpKQogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJhc3Npc3RhbnQi"
    "LCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgImFzc2lz"
    "dGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVtb3J5KHNlbGYuX3Nlc3Npb25faWQsICIi"
    "LCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUgYmxvb2Qgc3BoZXJlCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4oMS4wLCBz"
    "ZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAogICAg"
    "ICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVk"
    "KFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBpZGxlIHRpbWVy"
    "CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVy"
    "LnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJp"
    "ZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgog"
    "ICAgICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRp"
    "bWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0"
    "b3IsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50"
    "aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVt"
    "b3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5f"
    "ZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJf"
    "bWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYu"
    "X3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQi"
    "OgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3Rl"
    "ZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVu"
    "IHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9k"
    "ZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRl"
    "CiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9"
    "IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRP"
    "IjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDi"
    "gJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jw"
    "b3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2Ug"
    "aXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jw"
    "b3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5n"
    "IHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVz"
    "c2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAg"
    "ICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAg"
    "ICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5v"
    "bmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2Fj"
    "aGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYu"
    "X21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1v"
    "ZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxv"
    "YWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNl"
    "KCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNl"
    "dEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4"
    "aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAg"
    "aWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9y"
    "X3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3Rh"
    "bF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVs"
    "X2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0"
    "IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYi"
    "VGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAg"
    "ICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkK"
    "ICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coIltUT1JQT1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAg"
    "ICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7"
    "REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0"
    "aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMo"
    "IkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQog"
    "ICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xv"
    "YWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9h"
    "ZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVf"
    "dGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBf"
    "Y2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSA1IHNl"
    "Y29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMg"
    "dG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVk"
    "IOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAg"
    "aWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxf"
    "T0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNl"
    "IDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5u"
    "dm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNl"
    "ZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoK"
    "ICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAg"
    "IGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFk"
    "eSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVf"
    "dGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0g"
    "cHJlc3N1cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAg"
    "IGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQ"
    "T1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxm"
    "Ll92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90"
    "b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJu"
    "YWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQg"
    "YWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNz"
    "dXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2Ug"
    "PSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZh"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNL"
    "Uyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtl"
    "fSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZy"
    "b20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9"
    "eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAg"
    "ICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlk"
    "bGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxf"
    "bWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAg"
    "ICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9"
    "ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBz"
    "ZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFs"
    "IiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFu"
    "c21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBD"
    "RkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRp"
    "bmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGlk"
    "bGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9maXJlX2lk"
    "bGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxl"
    "X3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMp"
    "CiAgICAgICAgaWYgc2VsZi5fY3ljbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIu"
    "YWRkX2pvYigKICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAg"
    "ICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBz"
    "Y2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJp"
    "Z2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhl"
    "IFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgp"
    "IGhlcmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxl"
    "ZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAg"
    "ICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRz"
    "IHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBz"
    "dGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURV"
    "TEVSXSBTdGFydCBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRl"
    "YmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAg"
    "ICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNl"
    "KQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVk"
    "LiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVS"
    "QVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQog"
    "ICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAg"
    "ICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lO"
    "VEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBidWlsZF9haV9zdGF0ZV9jb250ZXh0KCkKICAgICAgICBoaXN0b3J5"
    "ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlciA9IElkbGVXb3JrZXIo"
    "CiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgIFNZU1RFTV9QUk9NUFRfQkFTRSwKICAgICAgICAgICAg"
    "aGlzdG9yeSwKICAgICAgICAgICAgbW9kZT1tb2RlLAogICAgICAgICAgICB2YW1waXJlX2NvbnRleHQ9dmFtcGlyZV9jdHgs"
    "CiAgICAgICAgKQogICAgICAgIGRlZiBfb25faWRsZV9yZWFkeSh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICMgRmxp"
    "cCB0byBTZWxmIHRhYiBhbmQgYXBwZW5kIHRoZXJlCiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5k"
    "ZXgoMSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgICAgICBzZWxm"
    "Ll9zZWxmX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19"
    "OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0c31dIFt7bW9kZX1dPC9zcGFuPjxicj4nCiAgICAg"
    "ICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0fTwvc3Bhbj48YnI+JwogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNlbGYuX3NlbGZfdGFiLmFwcGVuZCgiTkFSUkFUSVZFIiwgdCkKCiAgICAgICAgc2VsZi5faWRsZV93"
    "b3JrZXIudHJhbnNtaXNzaW9uX3JlYWR5LmNvbm5lY3QoX29uX2lkbGVfcmVhZHkpCiAgICAgICAgc2VsZi5faWRsZV93b3Jr"
    "ZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltJ"
    "RExFIEVSUk9SXSB7ZX0iLCAiRVJST1IiKQogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5zdGFydCgpCgog"
    "ICAgIyDilIDilIAgSk9VUk5BTCBTRVNTSU9OIExPQURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfam91cm5hbF9zZXNzaW9uKHNlbGYs"
    "IGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2Nv"
    "bnRleHQoZGF0ZV9zdHIpCiAgICAgICAgaWYgbm90IGN0eDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbSk9VUk5BTF0gTm8gc2Vzc2lvbiBmb3VuZCBmb3Ige2RhdGVfc3RyfSIsICJXQVJOIgogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfam91cm5hbF9sb2Fk"
    "ZWQoZGF0ZV9zdHIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltKT1VSTkFMXSBMb2FkZWQg"
    "c2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0gYXMgY29udGV4dC4gIgogICAgICAgICAgICBmIntERUNLX05BTUV9IGlzIG5vdyBh"
    "d2FyZSBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iLCAiT0siCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJT"
    "WVNURU0iLAogICAgICAgICAgICBmIkEgbWVtb3J5IHN0aXJzLi4uIHRoZSBqb3VybmFsIG9mIHtkYXRlX3N0cn0gb3BlbnMg"
    "YmVmb3JlIGhlci4iCiAgICAgICAgKQogICAgICAgICMgTm90aWZ5IE1vcmdhbm5hCiAgICAgICAgaWYgc2VsZi5fbW9kZWxf"
    "bG9hZGVkOgogICAgICAgICAgICBub3RlID0gKAogICAgICAgICAgICAgICAgZiJbSk9VUk5BTCBMT0FERURdIFRoZSB1c2Vy"
    "IGhhcyBvcGVuZWQgdGhlIGpvdXJuYWwgZnJvbSAiCiAgICAgICAgICAgICAgICBmIntkYXRlX3N0cn0uIEFja25vd2xlZGdl"
    "IHRoaXMgYnJpZWZseSDigJQgeW91IG5vdyBoYXZlICIKICAgICAgICAgICAgICAgIGYiYXdhcmVuZXNzIG9mIHRoYXQgY29u"
    "dmVyc2F0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgic3lzdGVt"
    "Iiwgbm90ZSkKCiAgICBkZWYgX2NsZWFyX2pvdXJuYWxfc2Vzc2lvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nl"
    "c3Npb25zLmNsZWFyX2xvYWRlZF9qb3VybmFsKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltKT1VSTkFMXSBKb3Vy"
    "bmFsIGNvbnRleHQgY2xlYXJlZC4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAg"
    "ICAgICAgICJUaGUgam91cm5hbCBjbG9zZXMuIE9ubHkgdGhlIHByZXNlbnQgcmVtYWlucy4iCiAgICAgICAgKQoKICAgICMg"
    "4pSA4pSAIFNUQVRTIFVQREFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdXBkYXRlX3N0"
    "YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZWxhcHNlZCA9IGludCh0aW1lLnRpbWUoKSAtIHNlbGYuX3Nlc3Npb25fc3Rh"
    "cnQpCiAgICAgICAgaCwgbSwgcyA9IGVsYXBzZWQgLy8gMzYwMCwgKGVsYXBzZWQgJSAzNjAwKSAvLyA2MCwgZWxhcHNlZCAl"
    "IDYwCiAgICAgICAgc2Vzc2lvbl9zdHIgPSBmIntoOjAyZH06e206MDJkfTp7czowMmR9IgoKICAgICAgICBzZWxmLl9od19w"
    "YW5lbC5zZXRfc3RhdHVzX2xhYmVscygKICAgICAgICAgICAgc2VsZi5fc3RhdHVzLAogICAgICAgICAgICBDRkdbIm1vZGVs"
    "Il0uZ2V0KCJ0eXBlIiwibG9jYWwiKS51cHBlcigpLAogICAgICAgICAgICBzZXNzaW9uX3N0ciwKICAgICAgICAgICAgc3Ry"
    "KHNlbGYuX3Rva2VuX2NvdW50KSwKICAgICAgICApCiAgICAgICAgc2VsZi5faHdfcGFuZWwudXBkYXRlX3N0YXRzKCkKCiAg"
    "ICAgICAgIyBMZWZ0IHNwaGVyZSA9IGFjdGl2ZSByZXNlcnZlIGZyb20gcnVudGltZSB0b2tlbiBwb29sCiAgICAgICAgbGVm"
    "dF9vcmJfZmlsbCA9IG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAgICAgIGlmIHNlbGYuX2xlZnRf"
    "b3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKGxlZnRfb3JiX2ZpbGwsIGF2YWls"
    "YWJsZT1UcnVlKQoKICAgICAgICAjIFJpZ2h0IHNwaGVyZSA9IFZSQU0gYXZhaWxhYmlsaXR5CiAgICAgICAgaWYgc2VsZi5f"
    "cmlnaHRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVf"
    "aGFuZGxlKQogICAgICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgICAgICB2cmFtX3RvdCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgcmlnaHRfb3JiX2Zp"
    "bGwgPSBtYXgoMC4wLCAxLjAgLSAodnJhbV91c2VkIC8gdnJhbV90b3QpKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3Jp"
    "Z2h0X29yYi5zZXRGaWxsKHJpZ2h0X29yYl9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFs"
    "c2UpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAsIGF2YWls"
    "YWJsZT1GYWxzZSkKCiAgICAgICAgIyBQcmltYXJ5IGVzc2VuY2UgPSBpbnZlcnNlIG9mIGxlZnQgc3BoZXJlIGZpbGwKICAg"
    "ICAgICBlc3NlbmNlX3ByaW1hcnlfcmF0aW8gPSAxLjAgLSBsZWZ0X29yYl9maWxsCiAgICAgICAgc2VsZi5fZXNzZW5jZV9w"
    "cmltYXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3Jh"
    "dGlvKjEwMDouMGZ9JSIpCgogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAgICAgIGlmIFBTVVRJ"
    "TF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5"
    "KCkKICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICA9IDEuMCAtIChtZW0udXNlZCAvIG1lbS50b3Rh"
    "bCkKICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFZhbHVlKAogICAgICAgICAgICAg"
    "ICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBm"
    "fSUiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2Vs"
    "Zi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VW5hdmFpbGFibGUoKQoKICAgICAgICAjIFVwZGF0ZSBqb3VybmFsIHNp"
    "ZGViYXIgYXV0b3NhdmUgZmxhc2gKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIucmVmcmVzaCgpCgogICAgIyDilIDi"
    "lIAgQ0hBVCBESVNQTEFZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9hcHBlbmRfY2hhdChz"
    "ZWxmLCBzcGVha2VyOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJZ"
    "T1UiOiAgICAgQ19HT0xELAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIoKTpDX0dPTEQsCiAgICAgICAgICAgICJTWVNU"
    "RU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgbGFiZWxf"
    "Y29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBl"
    "cigpOkNfQ1JJTVNPTiwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBD"
    "X0JMT09ELAogICAgICAgIH0KICAgICAgICBjb2xvciAgICAgICA9IGNvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEKQogICAg"
    "ICAgIGxhYmVsX2NvbG9yID0gbGFiZWxfY29sb3JzLmdldChzcGVha2VyLCBDX0dPTERfRElNKQogICAgICAgIHRpbWVzdGFt"
    "cCAgID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKCiAgICAgICAgaWYgc3BlYWtlciA9PSAiU1lTVEVN"
    "IjoKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0g"
    "PC9zcGFuPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07Ij7inKYge3RleHR9"
    "PC9zcGFuPicKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBl"
    "bmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+"
    "JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxl"
    "PSJjb2xvcjp7bGFiZWxfY29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICAgICAgZid7c3BlYWtlcn0g"
    "4p2nPC9zcGFuPiAnCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e3RleHR9PC9zcGFu"
    "PicKICAgICAgICAgICAgKQoKICAgICAgICAjIEFkZCBibGFuayBsaW5lIGFmdGVyIE1vcmdhbm5hJ3MgcmVzcG9uc2UgKG5v"
    "dCBkdXJpbmcgc3RyZWFtaW5nKQogICAgICAgIGlmIHNwZWFrZXIgPT0gREVDS19OQU1FLnVwcGVyKCk6CiAgICAgICAgICAg"
    "IHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoIiIpCgogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9s"
    "bEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhp"
    "bXVtKCkKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9nZXRfZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAg"
    "ICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRpbmdzLmdldCgiZW1h"
    "aWxfcmVmcmVzaF9pbnRlcnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBtYXgoMTAw"
    "MCwgaW50KHZhbCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoKICAgIGRl"
    "ZiBfc2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMoc2VsZiwgc2Vjb25kczogaW50KSAtPiBOb25lOgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBpbnQoc2Vjb25kcykpKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBhc3MKCiAgICBkZWYgX3NldF9lbWFpbF9yZWZyZXNoX21pbnV0"
    "ZXNfZnJvbV90ZXh0KHNlbGYsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1pbnV0ZXMg"
    "PSBtYXgoMSwgaW50KGZsb2F0KHN0cih0ZXh0KS5zdHJpcCgpKSkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIl0gPSBtaW51"
    "dGVzICogNjAwMDAKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICBmIltTRVRUSU5HU10gRW1haWwgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge21pbnV0ZXN9IG1pbnV0ZShzKSAoY29u"
    "ZmlnIGZvdW5kYXRpb24pLiIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVf"
    "YXV0b19kZXRlY3Qoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bInRpbWV6"
    "b25lX2F1dG9fZGV0ZWN0Il0gPSBib29sKGVuYWJsZWQpCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltTRVRUSU5HU10gVGltZSB6b25lIG1vZGUgc2V0IHRvIGF1dG8tZGV0ZWN0"
    "LiIgaWYgZW5hYmxlZCBlbHNlICJbU0VUVElOR1NdIFRpbWUgem9uZSBtb2RlIHNldCB0byBtYW51YWwgb3ZlcnJpZGUuIiwK"
    "ICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKCiAgICBkZWYgX3NldF90aW1lem9uZV9vdmVycmlkZShzZWxmLCB0el9u"
    "YW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdHpfdmFsdWUgPSBzdHIodHpfbmFtZSBvciAiIikuc3RyaXAoKQogICAgICAg"
    "IENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfb3ZlcnJpZGUiXSA9IHR6X3ZhbHVlCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZH"
    "KQogICAgICAgIGlmIHR6X3ZhbHVlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0VUVElOR1NdIFRpbWUg"
    "em9uZSBvdmVycmlkZSBzZXQgdG8ge3R6X3ZhbHVlfS4iLCAiSU5GTyIpCgogICAgZGVmIF9zZXRfc3RhdHVzKHNlbGYsIHN0"
    "YXR1czogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1cyA9IHN0YXR1cwogICAgICAgIHN0YXR1c19jb2xvcnMg"
    "PSB7CiAgICAgICAgICAgICJJRExFIjogICAgICAgQ19HT0xELAogICAgICAgICAgICAiR0VORVJBVElORyI6IENfQ1JJTVNP"
    "TiwKICAgICAgICAgICAgIkxPQURJTkciOiAgICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICAgICBDX0JMT09E"
    "LAogICAgICAgICAgICAiT0ZGTElORSI6ICAgIENfQkxPT0QsCiAgICAgICAgICAgICJUT1JQT1IiOiAgICAgQ19QVVJQTEVf"
    "RElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IHN0YXR1c19jb2xvcnMuZ2V0KHN0YXR1cywgQ19URVhUX0RJTSkKCiAg"
    "ICAgICAgdG9ycG9yX2xhYmVsID0gZiLil4kge1VJX1RPUlBPUl9TVEFUVVN9IiBpZiBzdGF0dXMgPT0gIlRPUlBPUiIgZWxz"
    "ZSBmIuKXiSB7c3RhdHVzfSIKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KHRvcnBvcl9sYWJlbCkKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29sb3J9OyBmb250LXNp"
    "emU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICBkZWYgX2JsaW5rKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgPSBub3Qgc2VsZi5fYmxpbmtfc3RhdGUKICAgICAgICBp"
    "ZiBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtf"
    "c3RhdGUgZWxzZSAi4peOIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYie2NoYXJ9IEdFTkVSQVRJ"
    "TkciKQogICAgICAgIGVsaWYgc2VsZi5fc3RhdHVzID09ICJUT1JQT1IiOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYg"
    "c2VsZi5fYmxpbmtfc3RhdGUgZWxzZSAi4oqYIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KAogICAg"
    "ICAgICAgICAgICAgZiJ7Y2hhcn0ge1VJX1RPUlBPUl9TVEFUVVN9IgogICAgICAgICAgICApCgogICAgIyDilIDilIAgSURM"
    "RSBUT0dHTEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX2lkbGVfdG9nZ2xlZChz"
    "ZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiaWRsZV9lbmFibGVkIl0gPSBl"
    "bmFibGVkCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0VGV4dCgiSURMRSBPTiIgaWYgZW5hYmxlZCBlbHNlICJJRExFIE9G"
    "RiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMx"
    "YTEwMDUnIGlmIGVuYWJsZWQgZWxzZSBDX0JHM307ICIKICAgICAgICAgICAgZiJjb2xvcjogeycjY2M4ODIyJyBpZiBlbmFi"
    "bGVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7JyNjYzg4MjInIGlmIGVu"
    "YWJsZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IGZvbnQtc2l6ZTogOXB4"
    "OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAg"
    "ICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmlu"
    "ZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgZW5hYmxlZDoKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9zY2hlZHVsZXIucmVzdW1lX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9uIGVuYWJsZWQuIiwgIk9LIikKICAgICAgICAgICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9uIHBhdXNlZC4i"
    "LCAiSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIltJRExFXSBUb2dnbGUgZXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgIyDilIDilIAgV0lORE9XIENPTlRS"
    "T0xTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF90b2dnbGVfZnVsbHNjcmVlbihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAg"
    "IENGR1sic2V0dGluZ3MiXVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9mc19idG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTog"
    "OXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAg"
    "ICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLnNob3dGdWxsU2NyZWVuKCkKICAgICAgICAgICAgQ0ZHWyJzZXR0"
    "aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJsZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAi"
    "CiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAg"
    "ICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAg"
    "c2F2ZV9jb25maWcoQ0ZHKQoKICAgIGRlZiBfdG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19i"
    "bCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAg"
    "IGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dG"
    "bGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIENG"
    "R1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElN"
    "fTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4"
    "OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICAgICAgc2VsZi5z"
    "aG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93"
    "RmxhZ3MoKSB8IFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIENG"
    "R1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklN"
    "U09OfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7"
    "ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQog"
    "ICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBzZWxmLnNob3coKQoKICAgIGRlZiBfZXhwb3J0X2NoYXQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAiIiJFeHBvcnQgY3VycmVudCBwZXJzb25hIGNoYXQgdGFiIGNvbnRlbnQgdG8gYSBUWFQgZmls"
    "ZS4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHRleHQgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudG9QbGFpblRleHQoKQog"
    "ICAgICAgICAgICBpZiBub3QgdGV4dC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIGV4cG9y"
    "dF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBl"
    "eGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikK"
    "ICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJzZWFuY2Vfe3RzfS50eHQiCiAgICAgICAgICAgIG91dF9w"
    "YXRoLndyaXRlX3RleHQodGV4dCwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICAgICAgICAgICMgQWxzbyBjb3B5IHRvIGNsaXBi"
    "b2FyZAogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dCh0ZXh0KQoKICAgICAgICAgICAgc2Vs"
    "Zi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICAgICBmIlNlc3Npb24gZXhwb3J0ZWQgdG8ge291dF9wYXRo"
    "Lm5hbWV9IGFuZCBjb3BpZWQgdG8gY2xpcGJvYXJkLiIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltFWFBP"
    "UlRdIHtvdXRfcGF0aH0iLCAiT0siKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW0VYUE9SVF0gRmFpbGVkOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBrZXlQcmVzc0V2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIGtleSA9IGV2ZW50LmtleSgpCiAgICAgICAgaWYga2V5ID09IFF0LktleS5L"
    "ZXlfRjExOgogICAgICAgICAgICBzZWxmLl90b2dnbGVfZnVsbHNjcmVlbigpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5"
    "LktleV9GMTA6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5L"
    "ZXkuS2V5X0VzY2FwZSBhbmQgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAg"
    "ICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzdXBlcigpLmtleVByZXNzRXZlbnQoZXZl"
    "bnQpCgogICAgIyDilIDilIAgQ0xPU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAjIFggYnV0dG9uID0gaW1t"
    "ZWRpYXRlIHNodXRkb3duLCBubyBkaWFsb2cKICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfaW5p"
    "dGlhdGVfc2h1dGRvd25fZGlhbG9nKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiR3JhY2VmdWwgc2h1dGRvd24g4oCUIHNo"
    "b3cgY29uZmlybSBkaWFsb2cgaW1tZWRpYXRlbHksIG9wdGlvbmFsbHkgZ2V0IGxhc3Qgd29yZHMuIiIiCiAgICAgICAgIyBJ"
    "ZiBhbHJlYWR5IGluIGEgc2h1dGRvd24gc2VxdWVuY2UsIGp1c3QgZm9yY2UgcXVpdAogICAgICAgIGlmIGdldGF0dHIoc2Vs"
    "ZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKToKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBUcnVlCgogICAgICAgICMg"
    "U2hvdyBjb25maXJtIGRpYWxvZyBGSVJTVCDigJQgZG9uJ3Qgd2FpdCBmb3IgQUkKICAgICAgICBkbGcgPSBRRGlhbG9nKHNl"
    "bGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJEZWFjdGl2YXRlPyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGRsZy5zZXRGaXhlZFNpemUoMzgwLCAx"
    "NDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQoKICAgICAgICBsYmwgPSBRTGFiZWwoCiAgICAgICAgICAg"
    "IGYiRGVhY3RpdmF0ZSB7REVDS19OQU1FfT9cblxuIgogICAgICAgICAgICBmIntERUNLX05BTUV9IG1heSBzcGVhayB0aGVp"
    "ciBsYXN0IHdvcmRzIGJlZm9yZSBnb2luZyBzaWxlbnQuIgogICAgICAgICkKICAgICAgICBsYmwuc2V0V29yZFdyYXAoVHJ1"
    "ZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBidG5fbGFzdCAgPSBRUHVzaEJ1dHRvbigiTGFzdCBXb3JkcyArIFNodXRkb3duIikKICAgICAgICBidG5fbm93ICAgPSBR"
    "UHVzaEJ1dHRvbigiU2h1dGRvd24gTm93IikKICAgICAgICBidG5fY2FuY2VsID0gUVB1c2hCdXR0b24oIkNhbmNlbCIpCgog"
    "ICAgICAgIGZvciBiIGluIChidG5fbGFzdCwgYnRuX25vdywgYnRuX2NhbmNlbCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11"
    "bUhlaWdodCgyOCkKICAgICAgICAgICAgYi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICAgICApCiAgICAgICAgYnRuX25vdy5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JMT09EfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2xhc3Qu"
    "Y2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMSkpCiAgICAgICAgYnRuX25vdy5jbGlja2VkLmNvbm5lY3QobGFt"
    "YmRhOiBkbGcuZG9uZSgyKSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDAp"
    "KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX25v"
    "dykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbGFzdCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cp"
    "CgogICAgICAgIHJlc3VsdCA9IGRsZy5leGVjKCkKCiAgICAgICAgaWYgcmVzdWx0ID09IDA6CiAgICAgICAgICAgICMgQ2Fu"
    "Y2VsbGVkCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5f"
    "c2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUp"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGVsaWYgcmVzdWx0ID09IDI6CiAgICAgICAgICAgICMgU2h1dGRvd24gbm93"
    "IOKAlCBubyBsYXN0IHdvcmRzCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgZWxpZiByZXN1"
    "bHQgPT0gMToKICAgICAgICAgICAgIyBMYXN0IHdvcmRzIHRoZW4gc2h1dGRvd24KICAgICAgICAgICAgc2VsZi5fZ2V0X2xh"
    "c3Rfd29yZHNfdGhlbl9zaHV0ZG93bigpCgogICAgZGVmIF9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgIiIiU2VuZCBmYXJld2VsbCBwcm9tcHQsIHNob3cgcmVzcG9uc2UsIHRoZW4gc2h1dGRvd24gYWZ0"
    "ZXIgdGltZW91dC4iIiIKICAgICAgICBmYXJld2VsbF9wcm9tcHQgPSAoCiAgICAgICAgICAgICJZb3UgYXJlIGJlaW5nIGRl"
    "YWN0aXZhdGVkLiBUaGUgZGFya25lc3MgYXBwcm9hY2hlcy4gIgogICAgICAgICAgICAiU3BlYWsgeW91ciBmaW5hbCB3b3Jk"
    "cyBiZWZvcmUgdGhlIHZlc3NlbCBnb2VzIHNpbGVudCDigJQgIgogICAgICAgICAgICAib25lIHJlc3BvbnNlIG9ubHksIHRo"
    "ZW4geW91IHJlc3QuIgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAg"
    "IuKcpiBTaGUgaXMgZ2l2ZW4gYSBtb21lbnQgdG8gc3BlYWsgaGVyIGZpbmFsIHdvcmRzLi4uIgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQo"
    "RmFsc2UpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9ICIiCgogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJy"
    "b2xlIjogInVzZXIiLCAiY29udGVudCI6IGZhcmV3ZWxsX3Byb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWlu"
    "Z1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4"
    "X3Rva2Vucz0yNTYKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl93b3JrZXIgPSB3b3JrZXIKICAg"
    "ICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCgogICAgICAgICAgICBkZWYgX29uX2RvbmUocmVzcG9uc2U6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSByZXNwb25zZQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fb25fcmVzcG9uc2VfZG9uZShyZXNwb25zZSkKICAgICAgICAgICAgICAgICMgU21hbGwgZGVs"
    "YXkgdG8gbGV0IHRoZSB0ZXh0IHJlbmRlciwgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNo"
    "b3QoMjAwMCwgbGFtYmRhOiBzZWxmLl9kb19zaHV0ZG93bihOb25lKSkKCiAgICAgICAgICAgIGRlZiBfb25fZXJyb3IoZXJy"
    "b3I6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTSFVURE9XTl1bV0FSTl0g"
    "TGFzdCB3b3JkcyBmYWlsZWQ6IHtlcnJvcn0iLCAiV0FSTiIpCiAgICAgICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihO"
    "b25lKQoKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAg"
    "IHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3QoX29uX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJl"
    "ZC5jb25uZWN0KF9vbl9lcnJvcikKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0"
    "X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAg"
    "ICAgICB3b3JrZXIuc3RhcnQoKQoKICAgICAgICAgICAgIyBTYWZldHkgdGltZW91dCDigJQgaWYgQUkgZG9lc24ndCByZXNw"
    "b25kIGluIDE1cywgc2h1dCBkb3duIGFueXdheQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwMCwgbGFtYmRh"
    "OiBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBnZXRhdHRyKHNlbGYs"
    "ICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSkgZWxzZSBOb25lKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NIVVRET1dOXVtXQVJOXSBM"
    "YXN0IHdvcmRzIHNraXBwZWQgZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgIyBJZiBhbnl0aGluZyBmYWlscywganVzdCBzaHV0IGRvd24KICAgICAgICAgICAgc2VsZi5fZG9f"
    "c2h1dGRvd24oTm9uZSkKCiAgICBkZWYgX2RvX3NodXRkb3duKHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICIiIlBl"
    "cmZvcm0gYWN0dWFsIHNodXRkb3duIHNlcXVlbmNlLiIiIgogICAgICAgICMgU2F2ZSBzZXNzaW9uCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBw"
    "YXNzCgogICAgICAgICMgU3RvcmUgZmFyZXdlbGwgKyBsYXN0IGNvbnRleHQgZm9yIHdha2UtdXAKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICMgR2V0IGxhc3QgMyBtZXNzYWdlcyBmcm9tIHNlc3Npb24gaGlzdG9yeSBmb3Igd2FrZS11cCBjb250ZXh0"
    "CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGxhc3RfY29u"
    "dGV4dCA9IGhpc3RvcnlbLTM6XSBpZiBsZW4oaGlzdG9yeSkgPj0gMyBlbHNlIGhpc3RvcnkKICAgICAgICAgICAgc2VsZi5f"
    "c3RhdGVbImxhc3Rfc2h1dGRvd25fY29udGV4dCJdID0gWwogICAgICAgICAgICAgICAgeyJyb2xlIjogbS5nZXQoInJvbGUi"
    "LCIiKSwgImNvbnRlbnQiOiBtLmdldCgiY29udGVudCIsIiIpWzozMDBdfQogICAgICAgICAgICAgICAgZm9yIG0gaW4gbGFz"
    "dF9jb250ZXh0CiAgICAgICAgICAgIF0KICAgICAgICAgICAgIyBFeHRyYWN0IE1vcmdhbm5hJ3MgbW9zdCByZWNlbnQgbWVz"
    "c2FnZSBhcyBmYXJld2VsbAogICAgICAgICAgICAjIFByZWZlciB0aGUgY2FwdHVyZWQgc2h1dGRvd24gZGlhbG9nIHJlc3Bv"
    "bnNlIGlmIGF2YWlsYWJsZQogICAgICAgICAgICBmYXJld2VsbCA9IGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9mYXJld2Vs"
    "bF90ZXh0JywgIiIpCiAgICAgICAgICAgIGlmIG5vdCBmYXJld2VsbDoKICAgICAgICAgICAgICAgIGZvciBtIGluIHJldmVy"
    "c2VkKGhpc3RvcnkpOgogICAgICAgICAgICAgICAgICAgIGlmIG0uZ2V0KCJyb2xlIikgPT0gImFzc2lzdGFudCI6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGZhcmV3ZWxsID0gbS5nZXQoImNvbnRlbnQiLCAiIilbOjQwMF0KICAgICAgICAgICAgICAg"
    "ICAgICAgICAgYnJlYWsKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfZmFyZXdlbGwiXSA9IGZhcmV3ZWxsCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFNhdmUgc3RhdGUKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duIl0gICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkK"
    "ICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfYWN0aXZlIl0gICAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQog"
    "ICAgICAgICAgICBzZWxmLl9zdGF0ZVsiYWlfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfYWlfc3RhdGUoKQogICAgICAg"
    "ICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1"
    "bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAg"
    "ICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRl"
    "cikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRl"
    "cGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1"
    "biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkv"
    "TW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNr"
    "LnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAg"
    "ICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0"
    "ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24g"
    "bWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKA"
    "lCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwK"
    "CiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBo"
    "YXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRp"
    "b24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFN"
    "RSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJu"
    "aW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9x"
    "dF9tZXNzYWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdl"
    "IGhhbmRsZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4i"
    "LCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYg"
    "ZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAg"
    "ICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5u"
    "YSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Ig"
    "c2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUg"
    "c2VlZCAucHkgbGl2ZXMKICAgICAgICBkZWNrX2hvbWUgPSBzZWVkX2RpciAvIERFQ0tfTkFNRQogICAgICAgIGRlY2tfaG9t"
    "ZS5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgICAgICMg4pSA4pSAIFVwZGF0ZSBhbGwgcGF0aHMg"
    "aW4gY29uZmlnIHRvIHBvaW50IGluc2lkZSBkZWNrX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9"
    "IHN0cihkZWNrX2hvbWUpCiAgICAgICAgbmV3X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3Ry"
    "KGRlY2tfaG9tZSAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoZGVja19ob21lIC8gInNvdW5kcyIp"
    "LAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIoZGVja19ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNz"
    "aW9ucyI6IHN0cihkZWNrX2hvbWUgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKGRlY2tfaG9t"
    "ZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIoZGVja19ob21lIC8gImV4cG9ydHMiKSwKICAgICAgICAg"
    "ICAgImxvZ3MiOiAgICAgc3RyKGRlY2tfaG9tZSAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBzIjogIHN0cihkZWNr"
    "X2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIoZGVja19ob21lIC8gInBlcnNvbmFzIiks"
    "CiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBk"
    "ZWNrIGZpbGUgaW50byBkZWNrX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZl"
    "KCkKICAgICAgICBkc3RfZGVjayA9IGRlY2tfaG9tZSAvIGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgogICAgICAg"
    "IGlmIHNyY19kZWNrICE9IGRzdF9kZWNrOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBfc2h1dGlsLmNvcHky"
    "KHN0cihzcmNfZGVjayksIHN0cihkc3RfZGVjaykpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkNvcHkgV2FybmluZyIs"
    "CiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgY29weSBkZWNrIGZpbGUgdG8ge0RFQ0tfTkFNRX0gZm9sZGVyOlxu"
    "e2V9XG5cbiIKICAgICAgICAgICAgICAgICAgICBmIllvdSBtYXkgbmVlZCB0byBjb3B5IGl0IG1hbnVhbGx5LiIKICAgICAg"
    "ICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgV3JpdGUgY29uZmlnLmpzb24gaW50byBkZWNrX2hvbWUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2Zn"
    "X2RzdCA9IGRlY2tfaG9tZSAvICJjb25maWcuanNvbiIKICAgICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRy"
    "dWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgd2l0aCBjZmdfZHN0Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBm"
    "OgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2NmZywgZiwgaW5kZW50PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJh"
    "cCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBUZW1wb3JhcmlseSB1cGRhdGUg"
    "Z2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcgcGF0aHMKICAgICAgICBDRkcudXBkYXRlKG5ld19j"
    "ZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAgICBib290c3RyYXBfc291bmRzKCkKICAgICAgICB3"
    "cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5wYWNrIGZhY2UgWklQIGlmIHByb3ZpZGVkIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2VfemlwX3BhdGgKICAgICAgICBpZiBm"
    "YWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6aXBmaWxlIGFzIF96aXBm"
    "aWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IGRlY2tfaG9tZSAvICJGYWNlcyIKICAgICAgICAgICAgZmFjZXNfZGlyLm1r"
    "ZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgd2l0aCBf"
    "emlwZmlsZS5aaXBGaWxlKGZhY2VfemlwLCAiciIpIGFzIHpmOgogICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCA9IDAK"
    "ICAgICAgICAgICAgICAgICAgICBmb3IgbWVtYmVyIGluIHpmLm5hbWVsaXN0KCk6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGlmIG1lbWJlci5sb3dlcigpLmVuZHN3aXRoKCIucG5nIik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmaWxlbmFt"
    "ZSA9IFBhdGgobWVtYmVyKS5uYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXJnZXQgPSBmYWNlc19kaXIgLyBm"
    "aWxlbmFtZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgd2l0aCB6Zi5vcGVuKG1lbWJlcikgYXMgc3JjLCB0YXJnZXQu"
    "b3Blbigid2IiKSBhcyBkc3Q6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZHN0LndyaXRlKHNyYy5yZWFkKCkp"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleHRyYWN0ZWQgKz0gMQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhm"
    "IltGQUNFU10gRXh0cmFjdGVkIHtleHRyYWN0ZWR9IGZhY2UgaW1hZ2VzIHRvIHtmYWNlc19kaXJ9IikKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gWklQIGV4dHJhY3Rp"
    "b24gZmFpbGVkOiB7ZX0iKQogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAg"
    "ICBOb25lLCAiRmFjZSBQYWNrIFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAgIGYiQ291bGQgbm90IGV4dHJhY3QgZmFj"
    "ZSBwYWNrOlxue2V9XG5cbiIKICAgICAgICAgICAgICAgICAgICBmIllvdSBjYW4gYWRkIGZhY2VzIG1hbnVhbGx5IHRvOlxu"
    "e2ZhY2VzX2Rpcn0iCiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSAIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0"
    "IHBvaW50aW5nIHRvIG5ldyBkZWNrIGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNob3J0Y3V0X2NyZWF0"
    "ZWQgPSBGYWxzZQogICAgICAgIGlmIGRsZy5jcmVhdGVfc2hvcnRjdXQ6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIGlmIFdJTjMyX09LOgogICAgICAgICAgICAgICAgICAgIGltcG9ydCB3aW4zMmNvbS5jbGllbnQgYXMgX3dpbjMyCiAg"
    "ICAgICAgICAgICAgICAgICAgZGVza3RvcCAgICAgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAgICAgICAgICAg"
    "ICAgIHNjX3BhdGggICAgID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgogICAgICAgICAgICAgICAgICAgIHB5dGhv"
    "bncgICAgID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIo"
    "KSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBweXRob253LnBhcmVudCAvICJw"
    "eXRob253LmV4ZSIKICAgICAgICAgICAgICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAgICAgICAgICAgc2hlbGwgPSBfd2lu"
    "MzIuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAgICAgICAgICAgICAgIHNjICAgID0gc2hlbGwuQ3JlYXRlU2hv"
    "cnRDdXQoc3RyKHNjX3BhdGgpKQogICAgICAgICAgICAgICAgICAgIHNjLlRhcmdldFBhdGggICAgICA9IHN0cihweXRob253"
    "KQogICAgICAgICAgICAgICAgICAgIHNjLkFyZ3VtZW50cyAgICAgICA9IGYnIntkc3RfZGVja30iJwogICAgICAgICAgICAg"
    "ICAgICAgIHNjLldvcmtpbmdEaXJlY3Rvcnk9IHN0cihkZWNrX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3Jp"
    "cHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQog"
    "ICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0i"
    "KQoKICAgICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9y"
    "dGN1dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJv"
    "bSBub3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0"
    "IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0"
    "X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAg"
    "ICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie2RlY2tfaG9tZX1cblxuIgog"
    "ICAgICAgICAgICBmIntzaG9ydGN1dF9ub3RlfVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBu"
    "b3cgY2xvc2UuXG4iCiAgICAgICAgICAgIGYiVXNlIHRoZSBzaG9ydGN1dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7"
    "REVDS19OQU1FfS4iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBFeGl0IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJv"
    "bSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAj"
    "IOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1bmNoIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVyZSBvbiBzdWJzZXF1ZW50IHJ1bnMgZnJvbSBkZWNrX2hvbWUKICAg"
    "IGJvb3RzdHJhcF9zb3VuZHMoKQoKICAgIF9lYXJseV9sb2coZiJbTUFJTl0gQ3JlYXRpbmcge0RFQ0tfTkFNRX0gZGVjayB3"
    "aW5kb3ciKQogICAgd2luZG93ID0gRWNob0RlY2soKQogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSB7REVDS19OQU1FfSBkZWNr"
    "IGNyZWF0ZWQg4oCUIGNhbGxpbmcgc2hvdygpIikKICAgIHdpbmRvdy5zaG93KCkKICAgIF9lYXJseV9sb2coIltNQUlOXSB3"
    "aW5kb3cuc2hvdygpIGNhbGxlZCDigJQgZXZlbnQgbG9vcCBzdGFydGluZyIpCgogICAgIyBEZWZlciBzY2hlZHVsZXIgYW5k"
    "IHN0YXJ0dXAgc2VxdWVuY2UgdW50aWwgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgIyBOb3RoaW5nIHRoYXQgc3RhcnRz"
    "IHRocmVhZHMgb3IgZW1pdHMgc2lnbmFscyBzaG91bGQgcnVuIGJlZm9yZSB0aGlzLgogICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "MjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zZXR1cF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5fc2V0"
    "dXBfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJd"
    "IHN0YXJ0X3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93LnN0YXJ0X3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVT"
    "aG90KDYwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc3RhcnR1cF9zZXF1ZW5jZSBmaXJpbmciKSwgd2luZG93"
    "Ll9zdGFydHVwX3NlcXVlbmNlKCkpKQoKICAgICMgUGxheSBzdGFydHVwIHNvdW5kIOKAlCBrZWVwIHJlZmVyZW5jZSB0byBw"
    "cmV2ZW50IEdDIHdoaWxlIHRocmVhZCBydW5zCiAgICBkZWYgX3BsYXlfc3RhcnR1cCgpOgogICAgICAgIHdpbmRvdy5fc3Rh"
    "cnR1cF9zb3VuZCA9IFNvdW5kV29ya2VyKCJzdGFydHVwIikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuZmluaXNo"
    "ZWQuY29ubmVjdCh3aW5kb3cuX3N0YXJ0dXBfc291bmQuZGVsZXRlTGF0ZXIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3Nv"
    "dW5kLnN0YXJ0KCkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEyMDAsIF9wbGF5X3N0YXJ0dXApCgogICAgc3lzLmV4aXQoYXBw"
    "LmV4ZWMoKSkKCgppZiBfX25hbWVfXyA9PSAiX19tYWluX18iOgogICAgbWFpbigpCgoKIyDilIDilIAgUEFTUyA2IENPTVBM"
    "RVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEZ1bGwgZGVjayBhc3NlbWJsZWQuIEFsbCBwYXNz"
    "ZXMgY29tcGxldGUuCiMgQ29tYmluZSBhbGwgcGFzc2VzIGludG8gbW9yZ2FubmFfZGVjay5weSBpbiBvcmRlcjoKIyAgIFBh"
    "c3MgMSDihpIgUGFzcyAyIOKGkiBQYXNzIDMg4oaSIFBhc3MgNCDihpIgUGFzcyA1IOKGkiBQYXNzIDYK"
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

        # Emit initial selection
        self._emit_builtin("Default")

    def _on_radio_changed(self, radio_id: int) -> None:
        names = {0: "Default", 1: "Assistant", 2: "Friend"}
        if radio_id in names:
            self._loaded_persona = None
            self._loaded_name    = None
            self._file_path.setText("")
            self._preview.setText("")
            self._emit_builtin(names[radio_id])
        # radio_id == 3 (Load from file) — do nothing until file is browsed

    def _emit_builtin(self, name: str) -> None:
        persona = BUILTIN_PERSONAS[name]
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
        names = {0: "Default", 1: "Assistant", 2: "Friend"}
        name = names.get(radio_id, "Default")
        return name, BUILTIN_PERSONAS[name]

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
