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
# Every module the Echo Deck system supports.
# STATUS: "built" | "partial" | "planned"
# Only "built" modules are selectable in the UI.
# "partial" modules show with a warning indicator.
# "planned" modules show greyed out (future reference).
#
# TO ADD A NEW MODULE:
#   1. Add entry here with status="planned"
#   2. When code is ready, set status="built", fill tab_name and slot_key
#   3. Immediately available in the builder — no other changes needed.
# ═══════════════════════════════════════════════════════════════════════════════

MODULES: dict[str, dict] = {

    # ── GOOGLE INTEGRATION ────────────────────────────────────────────────────
    "google_calendar": {
        "display_name": "Google Calendar + Tasks",
        "category":     "Google",
        "status":       "built",
        "description":  "Bi-directional Google Calendar sync. Task registry. Reminder parser.",
        "tab_name":     "Tasks",
        "slot_key":     "MODULE_GOOGLE_CALENDAR",
        "requires":     ["google-api-python-client", "google-auth-oauthlib"],
        "default_on":   True,
    },
    "google_drive": {
        "display_name": "Google Drive + Docs",
        "category":     "Google",
        "status":       "built",
        "description":  "Records tab. Folder nav, doc create/open/delete/export.",
        "tab_name":     "Records",
        "slot_key":     "MODULE_GOOGLE_DRIVE",
        "requires":     ["google-api-python-client"],
        "default_on":   True,
    },
    "gmail": {
        "display_name": "Gmail Integration",
        "category":     "Google",
        "status":       "planned",
        "description":  "Inbox panel. AI summarize, flag, draft replies. Opt-in.",
        "tab_name":     "Gmail",
        "slot_key":     "MODULE_GMAIL",
        "requires":     ["google-api-python-client"],
        "default_on":   False,
    },

    # ── SECOND LIFE ───────────────────────────────────────────────────────────
    "sl_scans": {
        "display_name": "SL Scans",
        "category":     "Second Life",
        "status":       "built",
        "description":  "Avatar scanner results. Card/grimoire style. Add/display/modify/delete.",
        "tab_name":     "SL Scans",
        "slot_key":     "MODULE_SL_SCANS",
        "requires":     [],
        "default_on":   False,
    },
    "sl_commands": {
        "display_name": "SL Commands",
        "category":     "Second Life",
        "status":       "built",
        "description":  "SL command reference table. Copy command to clipboard.",
        "tab_name":     "SL Commands",
        "slot_key":     "MODULE_SL_COMMANDS",
        "requires":     [],
        "default_on":   False,
    },
    "sl_vault": {
        "display_name": "SL Vault (Password Manager)",
        "category":     "Second Life",
        "status":       "planned",
        "description":  "Encrypted local password manager for SL bot accounts.",
        "tab_name":     "Vault",
        "slot_key":     "MODULE_SL_VAULT",
        "requires":     ["cryptography"],
        "default_on":   False,
    },

    # ── CAREER ────────────────────────────────────────────────────────────────
    "job_tracker": {
        "display_name": "Job Tracker",
        "category":     "Career",
        "status":       "built",
        "description":  "Application tracking. Archive/restore. CSV/TSV export.",
        "tab_name":     "Job Tracker",
        "slot_key":     "MODULE_JOB_TRACKER",
        "requires":     [],
        "default_on":   False,
    },

    # ── KNOWLEDGE ─────────────────────────────────────────────────────────────
    "lessons_learned": {
        "display_name": "Lessons Learned",
        "category":     "Knowledge",
        "status":       "partial",
        "description":  "Code lessons DB. LSL Forbidden Ruleset. Search by language/environment.",
        "tab_name":     "Lessons",
        "slot_key":     "MODULE_LESSONS_LEARNED",
        "requires":     [],
        "default_on":   False,
    },
    "sticky_notes": {
        "display_name": "Sticky Notes",
        "category":     "Knowledge",
        "status":       "partial",
        "description":  "Quick notes with color tags, pin, hide, export.",
        "tab_name":     "Notes",
        "slot_key":     "MODULE_STICKY_NOTES",
        "requires":     [],
        "default_on":   False,
    },

    # ── KITCHEN ───────────────────────────────────────────────────────────────
    "cookbook": {
        "display_name": "Cookbook",
        "category":     "Kitchen",
        "status":       "planned",
        "description":  "Recipe parser (paste/URL). Cook Mode. Serving scaler. Ratings.",
        "tab_name":     "Cookbook",
        "slot_key":     "MODULE_COOKBOOK",
        "requires":     [],
        "default_on":   False,
    },
    "shopping_list": {
        "display_name": "Shopping List",
        "category":     "Kitchen",
        "status":       "planned",
        "description":  "Staple detection. In Stock toggle. Ingredient intelligence.",
        "tab_name":     "Shopping",
        "slot_key":     "MODULE_SHOPPING_LIST",
        "requires":     [],
        "default_on":   False,
    },
    "meal_planner": {
        "display_name": "Meal Planner",
        "category":     "Kitchen",
        "status":       "planned",
        "description":  "Weekly/monthly calendar. Pattern detection. Taco intelligence.",
        "tab_name":     "Meal Planner",
        "slot_key":     "MODULE_MEAL_PLANNER",
        "requires":     [],
        "default_on":   False,
    },

    # ── PROFESSIONAL ──────────────────────────────────────────────────────────
    "project_manager": {
        "display_name": "Project Manager",
        "category":     "Professional",
        "status":       "planned",
        "description":  "Goals/milestones/phases. Risk register. SMP stakeholders. CMP.",
        "tab_name":     "Projects",
        "slot_key":     "MODULE_PROJECT_MANAGER",
        "requires":     [],
        "default_on":   False,
    },
    "csm_workspace": {
        "display_name": "CSM Workspace",
        "category":     "Professional",
        "status":       "planned",
        "description":  "Account management. Health scores. Renewal tracking. QBR logging.",
        "tab_name":     "CSM",
        "slot_key":     "MODULE_CSM_WORKSPACE",
        "requires":     [],
        "default_on":   False,
    },
    "bill_scheduler": {
        "display_name": "Bill Scheduler + Budget",
        "category":     "Professional",
        "status":       "planned",
        "description":  "Bills, budget, APScheduler reminders. No bank integration.",
        "tab_name":     "Budget",
        "slot_key":     "MODULE_BILL_SCHEDULER",
        "requires":     [],
        "default_on":   False,
    },

    # ── D&D / TTRPG ───────────────────────────────────────────────────────────
    "dnd_suite": {
        "display_name": "D&D / TTRPG Suite",
        "category":     "Gaming",
        "status":       "planned",
        "description":  "Session Chronicler. Combat Tracker. Campaign Memory. Bard Feature.",
        "tab_name":     "D&D",
        "slot_key":     "MODULE_DND_SUITE",
        "requires":     [],
        "default_on":   False,
    },

    # ── EDUCATION ─────────────────────────────────────────────────────────────
    "teacher_toolkit": {
        "display_name": "Teacher Toolkit",
        "category":     "Education",
        "status":       "planned",
        "description":  "Class roster. CRISPE prompt builder. Fun-5/Serious-6. Quiz generator.",
        "tab_name":     "Classroom",
        "slot_key":     "MODULE_TEACHER_TOOLKIT",
        "requires":     [],
        "default_on":   False,
    },

    # ── TOOLS ─────────────────────────────────────────────────────────────────
    "sovcit_cvr": {
        "display_name": "Claim vs Reality Engine",
        "category":     "Tools",
        "status":       "built",
        "description":  "SovCit + Flat Earth + Conspiracy packs. Three modes. Copy functions.",
        "tab_name":     "CvR",
        "slot_key":     "MODULE_CVR_ENGINE",
        "requires":     [],
        "default_on":   False,
    },
    "dice_roller": {
        "display_name": "Dice Roller",
        "category":     "Tools",
        "status":       "built",
        "description":  "Structured roll events, history, common rolls, and rules foundation.",
        "tab_name":     "Dice Roller",
        "slot_key":     "MODULE_DICE_ROLLER",
        "requires":     [],
        "default_on":   False,
    },
    "magic_8ball": {
        "display_name": "Magic 8-Ball",
        "category":     "Tools",
        "status":       "built",
        "description":  "Classic Magic 8-Ball panel. Standard answers + hidden persona interpretation.",
        "tab_name":     "Magic 8-Ball",
        "slot_key":     "MODULE_MAGIC_8BALL",
        "requires":     [],
        "default_on":   False,
    },
    "celestial": {
        "display_name": "Celestial + Holiday",
        "category":     "Tools",
        "status":       "planned",
        "description":  "Moon phase. Eclipse predictions (Meeus). 5 O'Clock. Santa tracker.",
        "tab_name":     "Celestial",
        "slot_key":     "MODULE_CELESTIAL",
        "requires":     [],
        "default_on":   False,
    },
    "session_browser": {
        "display_name": "Session Browser",
        "category":     "Tools",
        "status":       "partial",
        "description":  "Browse past sessions by date. AI naming. Group/label. Export.",
        "tab_name":     "Sessions",
        "slot_key":     "MODULE_SESSION_BROWSER",
        "requires":     [],
        "default_on":   True,
    },
    "system_monitor_ext": {
        "display_name": "System Monitor Extended",
        "category":     "Tools",
        "status":       "partial",
        "description":  "Full RAM breakdown. Per-drive storage. Network spike detection.",
        "tab_name":     "System",
        "slot_key":     "MODULE_SYSTEM_MONITOR_EXT",
        "requires":     ["psutil", "pynvml"],
        "default_on":   True,
    },
}



# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1D — SOUND PROFILES
#
# Each profile defines WAV generation parameters.
# Sound files are procedurally generated — no external audio needed.
# STATUS: "built" | "stub"
#
# TO ADD A NEW PROFILE:
#   1. Add entry here
#   2. Add generation function in Section 4
#   3. Reference in a persona's sound_profile field
# ═══════════════════════════════════════════════════════════════════════════════

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

MODULE_CODE: dict[str, Optional[str]] = {
    "google_calendar":    "# [MODULE: google_calendar — BUILT — see GoogleCalendarModule class]",
    "google_drive":       "# [MODULE: google_drive — BUILT — see GoogleDriveModule class]",
    "gmail":              None,
    "sl_scans":           "# [MODULE: sl_scans — BUILT — see SLScansTab class]",
    "sl_commands":        "# [MODULE: sl_commands — BUILT — see SLCommandsTab class]",
    "sl_vault":           None,
    "job_tracker":        "# [MODULE: job_tracker — BUILT — see JobTrackerTab class]",
    "lessons_learned":    "# [MODULE: lessons_learned — PARTIAL — see LessonsTab class]",
    "sticky_notes":       None,
    "cookbook":           None,
    "shopping_list":      None,
    "meal_planner":       None,
    "project_manager":    None,
    "csm_workspace":      None,
    "bill_scheduler":     None,
    "dnd_suite":          None,
    "teacher_toolkit":    None,
    "cvr_engine":         "# [MODULE: cvr_engine — BUILT — see CvRTab class]",
    "dice_roller":        "# [MODULE: dice_roller — BUILT — see DiceRollerTab class]",
    "magic_8ball":        "# [MODULE: magic_8ball — BUILT — see Magic8BallTab class]",
    "celestial":          "# [MODULE: celestial — BUILT — see MoonWidget/VampireStateStrip]",
    "session_browser":    "# [MODULE: session_browser — PARTIAL — see JournalSidebar]",
    "system_monitor_ext": "# [MODULE: system_monitor_ext — PARTIAL — see HardwarePanel]",
}

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

# ── MODULE INSTALLATION RECORD ────────────────────────────────────────────────
# Slots below show which modules are installed in this deck.
# [INSTALLED] = active    [NOT INSTALLED] = placeholder only

# ===SLOT:MODULE_GOOGLE_CALENDAR===
<<<MODULE_GOOGLE_CALENDAR>>>
# ===SLOT:MODULE_GOOGLE_DRIVE===
<<<MODULE_GOOGLE_DRIVE>>>
# ===SLOT:MODULE_GMAIL===
<<<MODULE_GMAIL>>>
# ===SLOT:MODULE_SL_SCANS===
<<<MODULE_SL_SCANS>>>
# ===SLOT:MODULE_SL_COMMANDS===
<<<MODULE_SL_COMMANDS>>>
# ===SLOT:MODULE_SL_VAULT===
<<<MODULE_SL_VAULT>>>
# ===SLOT:MODULE_JOB_TRACKER===
<<<MODULE_JOB_TRACKER>>>
# ===SLOT:MODULE_LESSONS_LEARNED===
<<<MODULE_LESSONS_LEARNED>>>
# ===SLOT:MODULE_STICKY_NOTES===
<<<MODULE_STICKY_NOTES>>>
# ===SLOT:MODULE_COOKBOOK===
<<<MODULE_COOKBOOK>>>
# ===SLOT:MODULE_SHOPPING_LIST===
<<<MODULE_SHOPPING_LIST>>>
# ===SLOT:MODULE_MEAL_PLANNER===
<<<MODULE_MEAL_PLANNER>>>
# ===SLOT:MODULE_PROJECT_MANAGER===
<<<MODULE_PROJECT_MANAGER>>>
# ===SLOT:MODULE_CSM_WORKSPACE===
<<<MODULE_CSM_WORKSPACE>>>
# ===SLOT:MODULE_BILL_SCHEDULER===
<<<MODULE_BILL_SCHEDULER>>>
# ===SLOT:MODULE_DND_SUITE===
<<<MODULE_DND_SUITE>>>
# ===SLOT:MODULE_TEACHER_TOOLKIT===
<<<MODULE_TEACHER_TOOLKIT>>>
# ===SLOT:MODULE_CVR_ENGINE===
<<<MODULE_CVR_ENGINE>>>
# ===SLOT:MODULE_DICE_ROLLER===
<<<MODULE_DICE_ROLLER>>>
# ===SLOT:MODULE_MAGIC_8BALL===
<<<MODULE_MAGIC_8BALL>>>
# ===SLOT:MODULE_CELESTIAL===
<<<MODULE_CELESTIAL>>>
# ===SLOT:MODULE_SESSION_BROWSER===
<<<MODULE_SESSION_BROWSER>>>
# ===SLOT:MODULE_SYSTEM_MONITOR_EXT===
<<<MODULE_SYSTEM_MONITOR_EXT>>>

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
        for mod_key, mod_data in MODULES.items():
            slot_key = mod_data["slot_key"]
            if mod_key in selected_modules:
                code = MODULE_CODE.get(mod_key)
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
        deck_impl = _get_deck_implementation(log_fn)

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
    "YWwsIEl0ZXJhdG9yCgojIOKUgOKUgCBFQVJMWSBDUkFTSCBMT0dHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgSG9va3MgaW4gYmVmb3Jl"
    "IFF0LCBiZWZvcmUgZXZlcnl0aGluZy4gQ2FwdHVyZXMgQUxMIG91dHB1dCBpbmNsdWRpbmcKIyBDKysgbGV2ZWwgUXQgbWVzc2Fn"
    "ZXMuIFdyaXR0ZW4gdG8gW0RlY2tOYW1lXS9sb2dzL3N0YXJ0dXAubG9nCiMgVGhpcyBzdGF5cyBhY3RpdmUgZm9yIHRoZSBsaWZl"
    "IG9mIHRoZSBwcm9jZXNzLgoKX0VBUkxZX0xPR19MSU5FUzogbGlzdCA9IFtdCl9FQVJMWV9MT0dfUEFUSDogT3B0aW9uYWxbUGF0"
    "aF0gPSBOb25lCgpkZWYgX2Vhcmx5X2xvZyhtc2c6IHN0cikgLT4gTm9uZToKICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRp"
    "bWUoIiVIOiVNOiVTLiVmIilbOi0zXQogICAgbGluZSA9IGYiW3t0c31dIHttc2d9IgogICAgX0VBUkxZX0xPR19MSU5FUy5hcHBl"
    "bmQobGluZSkKICAgIHByaW50KGxpbmUsIGZsdXNoPVRydWUpCiAgICBpZiBfRUFSTFlfTE9HX1BBVEg6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICB3aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAg"
    "ICAgICAgIGYud3JpdGUobGluZSArICJcbiIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKZGVm"
    "IF9pbml0X2Vhcmx5X2xvZyhiYXNlX2RpcjogUGF0aCkgLT4gTm9uZToKICAgIGdsb2JhbCBfRUFSTFlfTE9HX1BBVEgKICAgIGxv"
    "Z19kaXIgPSBiYXNlX2RpciAvICJsb2dzIgogICAgbG9nX2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAg"
    "ICBfRUFSTFlfTE9HX1BBVEggPSBsb2dfZGlyIC8gZiJzdGFydHVwX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVI"
    "JU0lUycpfS5sb2ciCiAgICAjIEZsdXNoIGJ1ZmZlcmVkIGxpbmVzCiAgICB3aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVuKCJ3Iiwg"
    "ZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmb3IgbGluZSBpbiBfRUFSTFlfTE9HX0xJTkVTOgogICAgICAgICAgICBm"
    "LndyaXRlKGxpbmUgKyAiXG4iKQoKZGVmIF9pbnN0YWxsX3F0X21lc3NhZ2VfaGFuZGxlcigpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IEludGVyY2VwdCBBTEwgUXQgbWVzc2FnZXMgaW5jbHVkaW5nIEMrKyBsZXZlbCB3YXJuaW5ncy4KICAgIFRoaXMgY2F0Y2hlcyB0"
    "aGUgUVRocmVhZCBkZXN0cm95ZWQgbWVzc2FnZSBhdCB0aGUgc291cmNlIGFuZCBsb2dzIGl0CiAgICB3aXRoIGEgZnVsbCB0cmFj"
    "ZWJhY2sgc28gd2Uga25vdyBleGFjdGx5IHdoaWNoIHRocmVhZCBhbmQgd2hlcmUuCiAgICAiIiIKICAgIHRyeToKICAgICAgICBm"
    "cm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCBxSW5zdGFsbE1lc3NhZ2VIYW5kbGVyLCBRdE1zZ1R5cGUKICAgICAgICBpbXBvcnQg"
    "dHJhY2ViYWNrCgogICAgICAgIGRlZiBxdF9tZXNzYWdlX2hhbmRsZXIobXNnX3R5cGUsIGNvbnRleHQsIG1lc3NhZ2UpOgogICAg"
    "ICAgICAgICBsZXZlbCA9IHsKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdERlYnVnTXNnOiAgICAiUVRfREVCVUciLAogICAg"
    "ICAgICAgICAgICAgUXRNc2dUeXBlLlF0SW5mb01zZzogICAgICJRVF9JTkZPIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5R"
    "dFdhcm5pbmdNc2c6ICAiUVRfV0FSTklORyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRDcml0aWNhbE1zZzogIlFUX0NS"
    "SVRJQ0FMIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdEZhdGFsTXNnOiAgICAiUVRfRkFUQUwiLAogICAgICAgICAgICB9"
    "LmdldChtc2dfdHlwZSwgIlFUX1VOS05PV04iKQoKICAgICAgICAgICAgbG9jYXRpb24gPSAiIgogICAgICAgICAgICBpZiBjb250"
    "ZXh0LmZpbGU6CiAgICAgICAgICAgICAgICBsb2NhdGlvbiA9IGYiIFt7Y29udGV4dC5maWxlfTp7Y29udGV4dC5saW5lfV0iCgog"
    "ICAgICAgICAgICBfZWFybHlfbG9nKGYiW3tsZXZlbH1de2xvY2F0aW9ufSB7bWVzc2FnZX0iKQoKICAgICAgICAgICAgIyBGb3Ig"
    "UVRocmVhZCB3YXJuaW5ncyDigJQgbG9nIGZ1bGwgUHl0aG9uIHN0YWNrCiAgICAgICAgICAgIGlmICJRVGhyZWFkIiBpbiBtZXNz"
    "YWdlIG9yICJ0aHJlYWQiIGluIG1lc3NhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIHN0YWNrID0gIiIuam9pbih0cmFjZWJh"
    "Y2suZm9ybWF0X3N0YWNrKCkpCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW1NUQUNLIEFUIFFUSFJFQUQgV0FSTklOR11c"
    "bntzdGFja30iKQoKICAgICAgICBxSW5zdGFsbE1lc3NhZ2VIYW5kbGVyKHF0X21lc3NhZ2VfaGFuZGxlcikKICAgICAgICBfZWFy"
    "bHlfbG9nKCJbSU5JVF0gUXQgbWVzc2FnZSBoYW5kbGVyIGluc3RhbGxlZCIpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgX2Vhcmx5X2xvZyhmIltJTklUXSBDb3VsZCBub3QgaW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXI6IHtlfSIpCgpfZWFy"
    "bHlfbG9nKGYiW0lOSVRdIHtERUNLX05BTUV9IGRlY2sgc3RhcnRpbmciKQpfZWFybHlfbG9nKGYiW0lOSVRdIFB5dGhvbiB7c3lz"
    "LnZlcnNpb24uc3BsaXQoKVswXX0gYXQge3N5cy5leGVjdXRhYmxlfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gV29ya2luZyBkaXJl"
    "Y3Rvcnk6IHtvcy5nZXRjd2QoKX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFNjcmlwdCBsb2NhdGlvbjoge1BhdGgoX19maWxlX18p"
    "LnJlc29sdmUoKX0iKQoKIyDilIDilIAgT1BUSU9OQUwgREVQRU5ERU5DWSBHVUFSRFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgpQU1VUSUxfT0sgPSBGYWxzZQp0cnk6CiAgICBp"
    "bXBvcnQgcHN1dGlsCiAgICBQU1VUSUxfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JUXSBwc3V0aWwgT0siKQpleGNl"
    "cHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBwc3V0aWwgRkFJTEVEOiB7ZX0iKQoKTlZNTF9P"
    "SyA9IEZhbHNlCmdwdV9oYW5kbGUgPSBOb25lCnRyeToKICAgIGltcG9ydCB3YXJuaW5ncwogICAgd2l0aCB3YXJuaW5ncy5jYXRj"
    "aF93YXJuaW5ncygpOgogICAgICAgIHdhcm5pbmdzLnNpbXBsZWZpbHRlcigiaWdub3JlIikKICAgICAgICBpbXBvcnQgcHludm1s"
    "CiAgICBweW52bWwubnZtbEluaXQoKQogICAgY291bnQgPSBweW52bWwubnZtbERldmljZUdldENvdW50KCkKICAgIGlmIGNvdW50"
    "ID4gMDoKICAgICAgICBncHVfaGFuZGxlID0gcHludm1sLm52bWxEZXZpY2VHZXRIYW5kbGVCeUluZGV4KDApCiAgICAgICAgTlZN"
    "TF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgT0sg4oCUIHtjb3VudH0gR1BVKHMpIikKZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHB5bnZtbCBGQUlMRUQ6IHtlfSIpCgpUT1JDSF9PSyA9"
    "IEZhbHNlCnRyeToKICAgIGltcG9ydCB0b3JjaAogICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNh"
    "bExNLCBBdXRvVG9rZW5pemVyCiAgICBUT1JDSF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB0b3JjaCB7dG9y"
    "Y2guX192ZXJzaW9uX199IE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9y"
    "Y2ggRkFJTEVEIChvcHRpb25hbCk6IHtlfSIpCgpXSU4zMl9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCB3aW4zMmNvbS5jbGll"
    "bnQKICAgIFdJTjMyX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luMzJjb20gT0siKQpleGNlcHQgSW1wb3J0"
    "RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB3aW4zMmNvbSBGQUlMRUQ6IHtlfSIpCgpXSU5TT1VORF9PSyA9"
    "IEZhbHNlCnRyeToKICAgIGltcG9ydCB3aW5zb3VuZAogICAgV0lOU09VTkRfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJbSU1Q"
    "T1JUXSB3aW5zb3VuZCBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHdpbnNv"
    "dW5kIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKUFlHQU1FX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHB5Z2FtZQogICAg"
    "cHlnYW1lLm1peGVyLmluaXQoKQogICAgUFlHQU1FX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHlnYW1lIE9L"
    "IikKZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHB5Z2FtZSBGQUlMRUQ6IHtlfSIpCgpH"
    "T09HTEVfT0sgPSBGYWxzZQpHT09HTEVfQVBJX09LID0gRmFsc2UgICMgYWxpYXMgdXNlZCBieSBHb29nbGUgc2VydmljZSBjbGFz"
    "c2VzCkdPT0dMRV9JTVBPUlRfRVJST1IgPSBOb25lCnRyeToKICAgIGZyb20gZ29vZ2xlLmF1dGgudHJhbnNwb3J0LnJlcXVlc3Rz"
    "IGltcG9ydCBSZXF1ZXN0IGFzIEdvb2dsZUF1dGhSZXF1ZXN0CiAgICBmcm9tIGdvb2dsZS5vYXV0aDIuY3JlZGVudGlhbHMgaW1w"
    "b3J0IENyZWRlbnRpYWxzIGFzIEdvb2dsZUNyZWRlbnRpYWxzCiAgICBmcm9tIGdvb2dsZV9hdXRoX29hdXRobGliLmZsb3cgaW1w"
    "b3J0IEluc3RhbGxlZEFwcEZsb3cKICAgIGZyb20gZ29vZ2xlYXBpY2xpZW50LmRpc2NvdmVyeSBpbXBvcnQgYnVpbGQgYXMgZ29v"
    "Z2xlX2J1aWxkCiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5lcnJvcnMgaW1wb3J0IEh0dHBFcnJvciBhcyBHb29nbGVIdHRwRXJy"
    "b3IKICAgIEdPT0dMRV9PSyA9IFRydWUKICAgIEdPT0dMRV9BUElfT0sgPSBUcnVlCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBfZToK"
    "ICAgIEdPT0dMRV9JTVBPUlRfRVJST1IgPSBzdHIoX2UpCiAgICBHb29nbGVIdHRwRXJyb3IgPSBFeGNlcHRpb24KCkdPT0dMRV9T"
    "Q09QRVMgPSBbCiAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhciIsCiAgICAiaHR0cHM6Ly93d3cu"
    "Z29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgv"
    "ZHJpdmUiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKXQpHT09HTEVfU0NPUEVfUkVB"
    "VVRIX01TRyA9ICgKICAgICJHb29nbGUgdG9rZW4gc2NvcGVzIGFyZSBvdXRkYXRlZCBvciBpbmNvbXBhdGlibGUgd2l0aCByZXF1"
    "ZXN0ZWQgc2NvcGVzLiAiCiAgICAiRGVsZXRlIHRva2VuLmpzb24gYW5kIHJlYXV0aG9yaXplIHdpdGggdGhlIHVwZGF0ZWQgc2Nv"
    "cGUgbGlzdC4iCikKREVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORSA9ICJBbWVyaWNhL0NoaWNhZ28iCldJTkRPV1NfVFpfVE9f"
    "SUFOQSA9IHsKICAgICJDZW50cmFsIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9DaGljYWdvIiwKICAgICJFYXN0ZXJuIFN0YW5k"
    "YXJkIFRpbWUiOiAiQW1lcmljYS9OZXdfWW9yayIsCiAgICAiUGFjaWZpYyBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTG9zX0Fu"
    "Z2VsZXMiLAogICAgIk1vdW50YWluIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9EZW52ZXIiLAp9CgoKIyDilIDilIAgUHlTaWRl"
    "NiBJTVBPUlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCAoCiAgICBR"
    "QXBwbGljYXRpb24sIFFNYWluV2luZG93LCBRV2lkZ2V0LCBRVkJveExheW91dCwgUUhCb3hMYXlvdXQsCiAgICBRR3JpZExheW91"
    "dCwgUVRleHRFZGl0LCBRTGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRTGFiZWwsIFFGcmFtZSwKICAgIFFDYWxlbmRhcldpZGdldCwg"
    "UVRhYmxlV2lkZ2V0LCBRVGFibGVXaWRnZXRJdGVtLCBRSGVhZGVyVmlldywKICAgIFFBYnN0cmFjdEl0ZW1WaWV3LCBRU3RhY2tl"
    "ZFdpZGdldCwgUVRhYldpZGdldCwgUUxpc3RXaWRnZXQsCiAgICBRTGlzdFdpZGdldEl0ZW0sIFFTaXplUG9saWN5LCBRQ29tYm9C"
    "b3gsIFFDaGVja0JveCwgUUZpbGVEaWFsb2csCiAgICBRTWVzc2FnZUJveCwgUURhdGVFZGl0LCBRRGlhbG9nLCBRRm9ybUxheW91"
    "dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24sIFFTcGluQm94LCBRR3JhcGhp"
    "Y3NPcGFjaXR5RWZmZWN0LAogICAgUU1lbnUsIFFUYWJCYXIKKQpmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCAoCiAgICBRdCwg"
    "UVRpbWVyLCBRVGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVjdCwKICAgIFFQcm9wZXJ0eUFuaW1hdGlv"
    "biwgUUVhc2luZ0N1cnZlCikKZnJvbSBQeVNpZGU2LlF0R3VpIGltcG9ydCAoCiAgICBRRm9udCwgUUNvbG9yLCBRUGFpbnRlciwg"
    "UUxpbmVhckdyYWRpZW50LCBRUmFkaWFsR3JhZGllbnQsCiAgICBRUGl4bWFwLCBRUGVuLCBRUGFpbnRlclBhdGgsIFFUZXh0Q2hh"
    "ckZvcm1hdCwgUUljb24sCiAgICBRVGV4dEN1cnNvciwgUUFjdGlvbgopCgojIOKUgOKUgCBBUFAgSURFTlRJVFkg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACkFQUF9OQU1FICAgICAgPSBVSV9XSU5ET1dfVElUTEUKQVBQX1ZFUlNJT04gICA9"
    "ICIyLjAuMCIKQVBQX0ZJTEVOQU1FICA9IGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgpCVUlMRF9EQVRFICAgID0gIjIw"
    "MjYtMDQtMDQiCgojIOKUgOKUgCBDT05GSUcgTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBjb25m"
    "aWcuanNvbiBsaXZlcyBuZXh0IHRvIHRoZSBkZWNrIC5weSBmaWxlLgojIEFsbCBwYXRocyBjb21lIGZyb20gY29uZmlnLiBOb3Ro"
    "aW5nIGhhcmRjb2RlZCBiZWxvdyB0aGlzIHBvaW50LgoKU0NSSVBUX0RJUiA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKS5wYXJl"
    "bnQKQ09ORklHX1BBVEggPSBTQ1JJUFRfRElSIC8gImNvbmZpZy5qc29uIgoKIyBJbml0aWFsaXplIGVhcmx5IGxvZyBub3cgdGhh"
    "dCB3ZSBrbm93IHdoZXJlIHdlIGFyZQpfaW5pdF9lYXJseV9sb2coU0NSSVBUX0RJUikKX2Vhcmx5X2xvZyhmIltJTklUXSBTQ1JJ"
    "UFRfRElSID0ge1NDUklQVF9ESVJ9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBDT05GSUdfUEFUSCA9IHtDT05GSUdfUEFUSH0iKQpf"
    "ZWFybHlfbG9nKGYiW0lOSVRdIGNvbmZpZy5qc29uIGV4aXN0czoge0NPTkZJR19QQVRILmV4aXN0cygpfSIpCgpkZWYgX2RlZmF1"
    "bHRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIlJldHVybnMgdGhlIGRlZmF1bHQgY29uZmlnIHN0cnVjdHVyZSBmb3IgZmlyc3Qt"
    "cnVuIGdlbmVyYXRpb24uIiIiCiAgICBiYXNlID0gc3RyKFNDUklQVF9ESVIpCiAgICByZXR1cm4gewogICAgICAgICJkZWNrX25h"
    "bWUiOiBERUNLX05BTUUsCiAgICAgICAgImRlY2tfdmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAgICAgICJiYXNlX2RpciI6IGJh"
    "c2UsCiAgICAgICAgIm1vZGVsIjogewogICAgICAgICAgICAidHlwZSI6ICJsb2NhbCIsICAgICAgICAgICMgbG9jYWwgfCBvbGxh"
    "bWEgfCBjbGF1ZGUgfCBvcGVuYWkKICAgICAgICAgICAgInBhdGgiOiAiIiwgICAgICAgICAgICAgICAjIGxvY2FsIG1vZGVsIGZv"
    "bGRlciBwYXRoCiAgICAgICAgICAgICJvbGxhbWFfbW9kZWwiOiAiIiwgICAgICAgIyBlLmcuICJkb2xwaGluLTIuNi03YiIKICAg"
    "ICAgICAgICAgImFwaV9rZXkiOiAiIiwgICAgICAgICAgICAjIENsYXVkZSBvciBPcGVuQUkga2V5CiAgICAgICAgICAgICJhcGlf"
    "dHlwZSI6ICIiLCAgICAgICAgICAgIyAiY2xhdWRlIiB8ICJvcGVuYWkiCiAgICAgICAgICAgICJhcGlfbW9kZWwiOiAiIiwgICAg"
    "ICAgICAgIyBlLmcuICJjbGF1ZGUtc29ubmV0LTQtNiIKICAgICAgICB9LAogICAgICAgICJnb29nbGUiOiB7CiAgICAgICAgICAg"
    "ICJjcmVkZW50aWFscyI6IHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAg"
    "ICAgICAgICAgInRva2VuIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAg"
    "ICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAg"
    "ICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRw"
    "czovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlz"
    "LmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfSwKICAgICAgICAicGF0aHMiOiB7CiAgICAgICAg"
    "ICAgICJmYWNlcyI6ICAgIHN0cihTQ1JJUFRfRElSIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihTQ1JJ"
    "UFRfRElSIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIoU0NSSVBUX0RJUiAvICJtZW1vcmllcyIpLAog"
    "ICAgICAgICAgICAic2Vzc2lvbnMiOiBzdHIoU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAg"
    "ICBzdHIoU0NSSVBUX0RJUiAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIoU0NSSVBUX0RJUiAvICJleHBvcnRz"
    "IiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihTQ1JJUFRfRElSIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMi"
    "OiAgc3RyKFNDUklQVF9ESVIgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIoU0NSSVBUX0RJUiAvICJw"
    "ZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiKSwKICAgICAgICB9LAog"
    "ICAgICAgICJzZXR0aW5ncyI6IHsKICAgICAgICAgICAgImlkbGVfZW5hYmxlZCI6ICAgICAgICAgICAgICBGYWxzZSwKICAgICAg"
    "ICAgICAgImlkbGVfbWluX21pbnV0ZXMiOiAgICAgICAgICAxMCwKICAgICAgICAgICAgImlkbGVfbWF4X21pbnV0ZXMiOiAgICAg"
    "ICAgICAzMCwKICAgICAgICAgICAgImF1dG9zYXZlX2ludGVydmFsX21pbnV0ZXMiOiAxMCwKICAgICAgICAgICAgIm1heF9iYWNr"
    "dXBzIjogICAgICAgICAgICAgICAxMCwKICAgICAgICAgICAgImdvb2dsZV9zeW5jX2VuYWJsZWQiOiAgICAgICBUcnVlLAogICAg"
    "ICAgICAgICAic291bmRfZW5hYmxlZCI6ICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICAgICJnb29nbGVfaW5ib3VuZF9pbnRl"
    "cnZhbF9tcyI6IDMwMDAwLAogICAgICAgICAgICAiZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyI6IDMwMDAwMCwKICAgICAgICAg"
    "ICAgImdvb2dsZV9sb29rYmFja19kYXlzIjogICAgICAzMCwKICAgICAgICAgICAgInVzZXJfZGVsYXlfdGhyZXNob2xkX21pbiI6"
    "ICAzMCwKICAgICAgICAgICAgInRpbWV6b25lX2F1dG9fZGV0ZWN0IjogICAgICBUcnVlLAogICAgICAgICAgICAidGltZXpvbmVf"
    "b3ZlcnJpZGUiOiAgICAgICAgICIiLAogICAgICAgICAgICAiZnVsbHNjcmVlbl9lbmFibGVkIjogICAgICAgIEZhbHNlLAogICAg"
    "ICAgICAgICAiYm9yZGVybGVzc19lbmFibGVkIjogICAgICAgIEZhbHNlLAogICAgICAgIH0sCiAgICAgICAgIm1vZHVsZV90YWJf"
    "b3JkZXIiOiBbXSwKICAgICAgICAibWFpbl9zcGxpdHRlciI6IHsKICAgICAgICAgICAgImhvcml6b250YWxfc2l6ZXMiOiBbOTAw"
    "LCA1MDBdLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUsCiAgICB9CgpkZWYgbG9hZF9jb25maWcoKSAtPiBk"
    "aWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4gUmV0dXJucyBkZWZhdWx0IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAg"
    "IGlmIG5vdCBDT05GSUdfUEFUSC5leGlzdHMoKToKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAg"
    "ICAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICByZXR1cm4g"
    "anNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNh"
    "dmVfY29uZmlnKGNmZzogZGljdCkgLT4gTm9uZToKICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgu"
    "cGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVu"
    "Y29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywgZiwgaW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0"
    "IG1vZHVsZSBsZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9tIENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJs"
    "eV9sb2coZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1vZGVsX3R5"
    "cGU9e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BBVEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7"
    "CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJzb3VuZHMiOiAgIFNDUklQVF9ESVIgLyAic291bmRz"
    "IiwKICAgICJtZW1vcmllcyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAogICAgInNlc3Npb25zIjogU0NSSVBUX0RJUiAvICJz"
    "ZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJUFRfRElSIC8gInNsIiwKICAgICJleHBvcnRzIjogIFNDUklQVF9ESVIgLyAi"
    "ZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElSIC8gImxvZ3MiLAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAv"
    "ICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVyc29uYXMiLAogICAgImdvb2dsZSI6ICAgU0NSSVBU"
    "X0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKSAtPiBOb25lOgogICAgIiIiCiAgICBTZWxm"
    "LWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMgbWlzc2luZyByZXF1aXJlZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3Npbmcg"
    "cGF0aCBrZXlzIGFuZCBub3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lz"
    "dHMgY29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgogICAgY2hhbmdlZCA9IEZhbHNlCiAgICBwYXRocyA9"
    "IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVmYXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0"
    "ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdldChrZXkpOgogICAgICAgICAgICBwYXRoc1trZXldID0gc3RyKGRlZmF1bHRf"
    "cGF0aCkKICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVfY2ZnID0gQ0ZHLnNldGRlZmF1bHQoImdvb2dsZSIs"
    "IHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xlIiwgc3RyKF9ERUZBVUxUX1BBVEhTWyJnb29nbGUi"
    "XSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0cihnb29nbGVfcm9vdCAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBk"
    "ZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290IC8gInRva2VuLmpzb24iKQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9j"
    "ZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSkuc3RyaXAoKQogICAgdG9rZW5fdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tl"
    "biIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBjcmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVkc192YWwgYW5kICJnb29n"
    "bGVfY3JlZGVudGlhbHMuanNvbiIgaW4gY3JlZHNfdmFsKToKICAgICAgICBnb29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVm"
    "YXVsdF9jcmVkcwogICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3QgdG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdb"
    "InRva2VuIl0gPSBkZWZhdWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBzcGxpdHRlcl9jZmcgPSBDRkcuc2V0"
    "ZGVmYXVsdCgibWFpbl9zcGxpdHRlciIsIHt9KQogICAgaWYgbm90IGlzaW5zdGFuY2Uoc3BsaXR0ZXJfY2ZnLCBkaWN0KToKICAg"
    "ICAgICBDRkdbIm1haW5fc3BsaXR0ZXIiXSA9IHsiaG9yaXpvbnRhbF9zaXplcyI6IFs5MDAsIDUwMF19CiAgICAgICAgY2hhbmdl"
    "ZCA9IFRydWUKICAgIGVsc2U6CiAgICAgICAgc2l6ZXMgPSBzcGxpdHRlcl9jZmcuZ2V0KCJob3Jpem9udGFsX3NpemVzIikKICAg"
    "ICAgICB2YWxpZF9zaXplcyA9ICgKICAgICAgICAgICAgaXNpbnN0YW5jZShzaXplcywgbGlzdCkKICAgICAgICAgICAgYW5kIGxl"
    "bihzaXplcykgPT0gMgogICAgICAgICAgICBhbmQgYWxsKGlzaW5zdGFuY2UodiwgaW50KSBmb3IgdiBpbiBzaXplcykKICAgICAg"
    "ICApCiAgICAgICAgaWYgbm90IHZhbGlkX3NpemVzOgogICAgICAgICAgICBzcGxpdHRlcl9jZmdbImhvcml6b250YWxfc2l6ZXMi"
    "XSA9IFs5MDAsIDUwMF0KICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29u"
    "ZmlnKENGRykKCmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQgYSBwYXRoIGZy"
    "b20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBw"
    "YXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAgICB2YWx1ZSA9IHBhdGhzLmdldChrZXkpCiAgICBpZiB2YWx1ZToKICAgICAg"
    "ICByZXR1cm4gUGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZhbGxiYWNr"
    "OgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAgcmV0dXJuIGZhbGxiYWNrCiAgICByZXR1cm4gU0NS"
    "SVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJp"
    "dmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1BUlksIENfU0VDT05EQVJZLCBDX0FDQ0VOVCwgQ19CRywgQ19Q"
    "QU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElNIGFyZSBpbmplY3RlZCBhdCB0aGUgdG9wIG9mIHRoaXMgZmlsZSBi"
    "eSBkZWNrX2J1aWxkZXIuCiMgRXZlcnl0aGluZyBiZWxvdyBpcyBkZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoK"
    "IyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xvcnMgdG8gbmFtZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRo"
    "ZSBVSQpDX0NSSU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAgICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMsIGhp"
    "Z2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0gPSBDX1BSSU1BUlkgKyAiODgiICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0bGUgYm9yZGVy"
    "cwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMgbWFpbiBsYWJlbC90ZXh0L0FJIG91dHB1dCBjb2xvcgpDX0dP"
    "TERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGltIHNlY29uZGFyeQpDX0dPTERfQlJJR0hUID0gQ19BQ0NFTlQgICAg"
    "ICAgICAgICMgZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpDX1NJTFZFUiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMgc2Vjb25k"
    "YXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJTSAgPSBDX1RFWFRfRElNICsgIjg4IiAgIyBkaW0gc2Vjb25k"
    "YXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENfQkcgICAgICAgICAgICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJl"
    "YWR5IGluamVjdGVkKQpDX0JHMiAgICAgICAgID0gQ19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19C"
    "RzMgICAgICAgICA9IENfUEFORUwgICAgICAgICAgICAjIHRlcnRpYXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0"
    "ZWQpCkNfQkxPT0QgICAgICAgPSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBzdGF0ZXMsIGRhbmdlciDigJQgdW5pdmVyc2Fs"
    "CkNfUFVSUExFICAgICAgPSAnIzg4NTVjYycgICAgICAgICAgIyBTWVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBM"
    "RV9ESU0gID0gJyMyYTA1MmEnICAgICAgICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0"
    "YWE2NicgICAgICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4Y2MnICAg"
    "ICAgICAgICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNhbAoKIyBGb250IGhlbHBlciDigJQgZXh0cmFjdHMgcHJpbWFyeSBmb250"
    "IG5hbWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlfRk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgpLnN0"
    "cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24gcmVjb3JkIGNoaXBzKQpFTU9USU9OX0NP"
    "TE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAgQ19HT0xE"
    "LAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6ICAgICAgQ19H"
    "T0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFuaWNrZWQiOiAgIENfQ1JJTVNPTiwKICAgICJhbmdyeSI6ICAg"
    "ICAgQ19DUklNU09OLAogICAgInNob2NrZWQiOiAgICBDX0NSSU1TT04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAg"
    "ICJjb25jZXJuZWQiOiAgIiNjYzY2MjIiLAogICAgInNhZCI6ICAgICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRlZCI6ICIj"
    "Y2M2NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjogICBDX1BVUlBMRSwKICAgICJzdXNw"
    "aWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENfUFVSUExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJTFZFUiwK"
    "ICAgICJhbGVydCI6ICAgICAgQ19TSUxWRVIsCiAgICAibmV1dHJhbCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09S"
    "QVRJVkUgQ09OU1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlzIHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0"
    "aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVTCgojIEZhY2UgaW1hZ2UgbWFwIOKAlCBwcmVmaXggZnJvbSBGQUNF"
    "X1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFjZXMKRkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0gPSB7CiAg"
    "ICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJF"
    "RklYfV9BbGVydC5wbmciLAogICAgImZvY3VzZWQiOiAgICBmIntGQUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWci"
    "OiAgICAgICBmIntGQUNFX1BSRUZJWH1fU211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2Vy"
    "bmVkLnBuZyIsCiAgICAic2FkIjogICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQi"
    "OiAgIGYie0ZBQ0VfUFJFRklYfV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBmIntGQUNFX1BSRUZJWH1fSW1wcmVz"
    "c2VkLnBuZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJFRklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxpYXRlZCI6"
    "IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlhdGVkLnBuZyIsCiAgICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNp"
    "b3VzLnBuZyIsCiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0bW9kZSI6"
    "ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBmIntGQUNFX1BSRUZJWH1fQW5ncnku"
    "cG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYi"
    "e0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBuZyIsCiAgICAiaGFwcHkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmciLAog"
    "ICAgImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZBQ0VfUFJF"
    "RklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAgZiJ7RkFDRV9QUkVGSVh9X0VudmlvdXMucG5nIiwKfQoKU0VO"
    "VElNRU5UX0xJU1QgPSAoCiAgICAibmV1dHJhbCwgYWxlcnQsIGZvY3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZl"
    "ZCwgaW1wcmVzc2VkLCAiCiAgICAidmljdG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNrZWQsIGFuZ3J5LCBwbG90"
    "dGluZywgc2hvY2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZsdXN0ZXJlZCwgZW52aW91cyIKKQoKIyDilIDilIAgU1lTVEVN"
    "IFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBmaWxlIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRfQkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJvdmUgZnJvbSA8"
    "PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3QgcmVkZWZpbmUgaXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBT"
    "VFlMRVNIRUVUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9IGYiIiIKUU1haW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJh"
    "Y2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1J"
    "TFl9Owp9fQpRVGV4dEVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtDX0dPTER9"
    "OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1m"
    "YW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rp"
    "b24tYmFja2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6"
    "IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRl"
    "ci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxM3B4OwogICAg"
    "cGFkZGluZzogOHB4IDEycHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07CiAg"
    "ICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJv"
    "cmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4Owog"
    "ICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHggMjBweDsKICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQ"
    "dXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JS"
    "SUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNzZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAgIGJvcmRl"
    "ci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7ewogICAgYmFj"
    "a2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRf"
    "RElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0aWNhbCB7ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAg"
    "IGJvcmRlcjogbm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09O"
    "X0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2ZXJ0aWNhbDpob3ZlciB7ewogICAg"
    "YmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xsQmFyOjpzdWIt"
    "bGluZTp2ZXJ0aWNhbCB7ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6OnBhbmUge3sKICAgIGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07Cn19ClFUYWJCYXI6OnRhYiB7ewogICAgYmFja2dy"
    "b3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXpl"
    "OiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5k"
    "OiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJ"
    "TVNPTn07Cn19ClFUYWJCYXI6OnRhYjpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dP"
    "TERfRElNfTsKfX0KUVRhYmxlV2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9Owog"
    "ICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBm"
    "b250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNl"
    "bGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9Owp9fQpR"
    "SGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9O"
    "VF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXItc3BhY2luZzog"
    "MXB4Owp9fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9G"
    "T05UX0ZBTUlMWX07Cn19ClFDb21ib0JveDo6ZHJvcC1kb3duIHt7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0JveCB7ewog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewogICAgY29s"
    "b3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9fQpRU3BsaXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dyb3VuZDoge0Nf"
    "Q1JJTVNPTl9ESU19OwogICAgd2lkdGg6IDJweDsKfX0KIiIiCgojIOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgogICAgQ3JlYXRlIGFsbCByZXF1aXJl"
    "ZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAgQ2FsbGVkIG9uIHN0YXJ0dXAgYmVmb3JlIGFueXRoaW5nIGVs"
    "c2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFsc28gbWlncmF0ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1l"
    "XV9NZW1vcmllcyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRpcnMgPSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2Vz"
    "IiksCiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpLAogICAgICAgIGNmZ19w"
    "YXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIpLAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAg"
    "ICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAgICAgICBjZmdfcGF0aCgiYmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25h"
    "cyIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0cyIsCiAg"
    "ICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMg"
    "Q3JlYXRlIGVtcHR5IEpTT05MIGZpbGVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVt"
    "b3JpZXMiKQogICAgZm9yIGZuYW1lIGluICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwi"
    "LAogICAgICAgICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAg"
    "ICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0"
    "ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4g"
    "KCJzbF9zY2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAg"
    "ICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAg"
    "c2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4"
    "Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAgIGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9u"
    "cyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRl"
    "Lmpzb24iCiAgICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShzdGF0ZV9w"
    "YXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhfcGF0aC5leGlz"
    "dHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQ"
    "X1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9"
    "LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgIyBMZWdhY3kgbWlncmF0aW9u"
    "OiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxlcwogICAgX21pZ3JhdGVfbGVnYWN5"
    "X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAg"
    "ICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAg"
    "InNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjog"
    "Tm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAogICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRv"
    "dGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVf"
    "YXRfc2h1dGRvd24iOiAiRE9STUFOVCIsCiAgICB9CiAgICBwYXRoLndyaXRlX3RleHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50"
    "PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKZGVmIF9taWdyYXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIKICAgIElm"
    "IG9sZCBEOlxcQUlcXE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdyYXRlIGZp"
    "bGVzIHRvIG5ldyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIKICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2"
    "ZSB0byBtb2RlbCBwYXRoCiAgICBtb2RlbF9wYXRoID0gUGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYg"
    "bm90IG1vZGVsX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFyZW50IC8g"
    "ZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBt"
    "aWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJtZW1vcmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0aCgibWVt"
    "b3JpZXMiKSAvICJtZW1vcmllcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAg"
    "ICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFza3MuanNv"
    "bmwiLCAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290"
    "IC8gInN0YXRlLmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAg"
    "ICAgKG9sZF9yb290IC8gImluZGV4Lmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJpbmRleC5q"
    "c29uIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJz"
    "bF9zY2Fucy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29ubCIsICAgICAgICAgY2ZnX3BhdGgo"
    "InNsIikgLyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiwg"
    "ICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsidG9rZW4iXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJjb25maWciIC8gImdvb2dsZV9j"
    "cmVkZW50aWFscy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBQYXRoKENG"
    "R1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291bmRzIiAvIGYie1NPVU5EX1BSRUZJ"
    "WH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjZmdfcGF0aCgi"
    "c291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIpLAogICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRp"
    "b25zOgogICAgICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICBpbXBv"
    "cnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIoc3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2ZhY2Vz"
    "ID0gb2xkX3Jvb3QgLyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2ZhY2VzLmV4"
    "aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2VzLmdsb2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19m"
    "YWNlcyAvIGltZy5uYW1lCiAgICAgICAgICAgIGlmIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoaW1nKSwgc3Ry"
    "KGRzdCkpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg4pSA4pSA"
    "IERBVEVUSU1FIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAg"
    "cmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFs"
    "dWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgaWYgbm90IHZhbHVlOgogICAgICAgIHJldHVybiBOb25lCiAgICB2"
    "YWx1ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBpZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICBy"
    "ZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAgICAg"
    "ICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVy"
    "biBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBsZV0gPSBzZXQoKQoKCmRlZiBfcmVzb2x2ZV9k"
    "ZWNrX3RpbWV6b25lX25hbWUoKSAtPiBPcHRpb25hbFtzdHJdOgogICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9"
    "KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkgZWxzZSB7fQogICAgYXV0b19kZXRlY3QgPSBib29sKHNldHRpbmdzLmdldCgidGlt"
    "ZXpvbmVfYXV0b19kZXRlY3QiLCBUcnVlKSkKICAgIG92ZXJyaWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb3ZlcnJp"
    "ZGUiLCAiIikgb3IgIiIpLnN0cmlwKCkKICAgIGlmIG5vdCBhdXRvX2RldGVjdCBhbmQgb3ZlcnJpZGU6CiAgICAgICAgcmV0dXJu"
    "IG92ZXJyaWRlCiAgICBsb2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICBpZiBsb2Nh"
    "bF90emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgdHpfa2V5ID0gZ2V0YXR0cihsb2NhbF90emluZm8sICJrZXkiLCBOb25lKQog"
    "ICAgICAgIGlmIHR6X2tleToKICAgICAgICAgICAgcmV0dXJuIHN0cih0el9rZXkpCiAgICAgICAgdHpfbmFtZSA9IHN0cihsb2Nh"
    "bF90emluZm8pCiAgICAgICAgaWYgdHpfbmFtZSBhbmQgdHpfbmFtZS51cHBlcigpICE9ICJMT0NBTCI6CiAgICAgICAgICAgIHJl"
    "dHVybiB0el9uYW1lCiAgICByZXR1cm4gTm9uZQoKCmRlZiBfbG9jYWxfdHppbmZvKCk6CiAgICB0el9uYW1lID0gX3Jlc29sdmVf"
    "ZGVja190aW1lem9uZV9uYW1lKCkKICAgIGlmIHR6X25hbWU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gWm9uZUlu"
    "Zm8odHpfbmFtZSkKICAgICAgICBleGNlcHQgWm9uZUluZm9Ob3RGb3VuZEVycm9yOgogICAgICAgICAgICBfZWFybHlfbG9nKGYi"
    "W0RBVEVUSU1FXVtXQVJOXSBVbmtub3duIHRpbWV6b25lIG92ZXJyaWRlICd7dHpfbmFtZX0nLCB1c2luZyBzeXN0ZW0gbG9jYWwg"
    "dGltZXpvbmUuIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICByZXR1cm4gZGF0ZXRpbWUu"
    "bm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICByZXR1"
    "cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkKCgpkZWYgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3Zh"
    "bHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICBpZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBp"
    "ZiBub3QgaXNpbnN0YW5jZShkdF92YWx1ZSwgZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9s"
    "b2NhbF90emluZm8oKQogICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5vbmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVl"
    "LnJlcGxhY2UodHppbmZvPWxvY2FsX3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0KQogICAgICAgIGlmIGtleSBu"
    "b3QgaW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICAg"
    "ICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250"
    "ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JNQUxJ"
    "WkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3JtYWxpemVkID0gZHRfdmFsdWUu"
    "YXN0aW1lem9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIoZHRfdmFsdWUudHppbmZvKQogICAga2V5ID0gKCJhd2Fy"
    "ZSIsIGNvbnRleHQsIGR0X3R6X25hbWUpCiAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBh"
    "bmQgZHRfdHpfbmFtZSBub3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAg"
    "ICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmcm9tIHtkdF90el9uYW1lfSB0"
    "byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAg"
    "IF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2Vf"
    "aXNvX2Zvcl9jb21wYXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1lX2Zv"
    "cl9jb21wYXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tfZHVlX3NvcnRfa2V5KHRhc2s6"
    "IGRpY3QpOgogICAgZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9yICh0YXNr"
    "IG9yIHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJu"
    "ICgxLCBkYXRldGltZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkKICAgIHJldHVybiAoMCwgZHVlLmFzdGltZXpv"
    "bmUodGltZXpvbmUudXRjKSwgKCh0YXNrIG9yIHt9KS5nZXQoInRleHQiKSBvciAiIikubG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1"
    "cmF0aW9uKHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9IG1heCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCBy"
    "ZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJlbSA9IGRpdm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBz"
    "ZWNzID0gZGl2bW9kKHJlbSwgNjApCiAgICBwYXJ0cyA9IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5c31k"
    "IikKICAgIGlmIGhvdXJzOiAgIHBhcnRzLmFwcGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRzLmFwcGVuZChm"
    "InttaW51dGVzfW0iKQogICAgaWYgbm90IHBhcnRzOiBwYXJ0cy5hcHBlbmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9p"
    "bihwYXJ0c1s6M10pCgojIOKUgOKUgCBNT09OIFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ29ycmVjdGVkIGls"
    "bHVtaW5hdGlvbiBtYXRoIOKAlCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01PT04g"
    "PSBkYXRlKDIwMDAsIDEsIDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAtPiB0"
    "dXBsZVtmbG9hdCwgc3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2ZyYWN0aW9uLCBwaGFzZV9uYW1lLCBp"
    "bGx1bWluYXRpb25fcGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9uOiAwLjAgPSBuZXcgbW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAg"
    "PSBuZXcgbW9vbiBhZ2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDigJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwg"
    "cGhhc2UuCiAgICAiIiIKICAgIGRheXMgID0gKGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9PTikuZGF5cwogICAgY3ljbGUg"
    "PSBkYXlzICUgX0xVTkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8IDEu"
    "ODU6ICAgbmFtZSA9ICJORVcgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVNDRU5UIgog"
    "ICAgZWxpZiBjeWNsZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNsZSA8IDE0Ljc3OiAgbmFt"
    "ZSA9ICJXQVhJTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBj"
    "eWNsZSA8IDIyLjE1OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAiTEFT"
    "VCBRVUFSVEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NFTlQiCgogICAgIyBDb3JyZWN0"
    "ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9vbgogICAgaWxsdW1pbmF0aW9uID0gKDEgLSBtYXRo"
    "LmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkgLyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5h"
    "dGlvbiwgMSkKCl9TVU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25lCl9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTjog"
    "T3B0aW9uYWxbaW50XSA9IE5vbmUKX1NVTl9DQUNIRV9USU1FUzogdHVwbGVbc3RyLCBzdHJdID0gKCIwNjowMCIsICIxODozMCIp"
    "CgpkZWYgX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0dXBsZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNv"
    "bHZlIGxhdGl0dWRlL2xvbmdpdHVkZSBmcm9tIHJ1bnRpbWUgY29uZmlnIHdoZW4gYXZhaWxhYmxlLgogICAgRmFsbHMgYmFjayB0"
    "byB0aW1lem9uZS1kZXJpdmVkIGNvYXJzZSBkZWZhdWx0cy4KICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9uZQog"
    "ICAgdHJ5OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3Qp"
    "IGVsc2Uge30KICAgICAgICBmb3Iga2V5IGluICgibGF0aXR1ZGUiLCAibGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0"
    "aW5nczoKICAgICAgICAgICAgICAgIGxhdCA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAg"
    "ICAgIGZvciBrZXkgaW4gKCJsb25naXR1ZGUiLCAibG9uIiwgImxuZyIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6"
    "CiAgICAgICAgICAgICAgICBsb24gPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsKICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgbGF0ID0gTm9uZQogICAgICAgIGxvbiA9IE5vbmUKCiAgICBub3dfbG9jYWwgPSBkYXRldGlt"
    "ZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHR6X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkK"
    "ICAgIHR6X29mZnNldF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKCiAgICBpZiBsb24gaXMgTm9u"
    "ZToKICAgICAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIHR6X29mZnNldF9ob3VycyAqIDE1LjApKQoKICAgIGlmIGxh"
    "dCBpcyBOb25lOgogICAgICAgIHR6X25hbWUgPSBzdHIobm93X2xvY2FsLnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50"
    "ID0gYW55KHRva2VuIGluIHR6X25hbWUgZm9yIHRva2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lmaWMvQXVja2xhbmQiLCAiQW1l"
    "cmljYS9TYW50aWFnbyIpKQogICAgICAgIGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0gbWF4"
    "KC02Ni4wLCBtaW4oNjYuMCwgbGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgbG9uKSkKICAgIHJldHVybiBs"
    "YXQsIGxvbgoKZGVmIF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9jYWxfZGF5OiBkYXRlLCBsYXRpdHVkZTogZmxvYXQsIGxv"
    "bmdpdHVkZTogZmxvYXQsIHN1bnJpc2U6IGJvb2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEtc3R5bGUgc3Vucmlz"
    "ZS9zdW5zZXQgc29sdmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJvbSBtaWRuaWdodC4iIiIKICAgIG4gPSBsb2NhbF9kYXku"
    "dGltZXR1cGxlKCkudG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0ID0gbiArICgoNiAtIGxuZ19o"
    "b3VyKSAvIDI0LjApIGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxuZ19ob3VyKSAvIDI0LjApCgogICAgTSA9ICgwLjk4NTYg"
    "KiB0KSAtIDMuMjg5CiAgICBMID0gTSArICgxLjkxNiAqIG1hdGguc2luKG1hdGgucmFkaWFucyhNKSkpICsgKDAuMDIwICogbWF0"
    "aC5zaW4obWF0aC5yYWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9IEwgJSAzNjAuMAoKICAgIFJBID0gbWF0aC5kZWdy"
    "ZWVzKG1hdGguYXRhbigwLjkxNzY0ICogbWF0aC50YW4obWF0aC5yYWRpYW5zKEwpKSkpCiAgICBSQSA9IFJBICUgMzYwLjAKICAg"
    "IExfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihMIC8gOTAuMCkpICogOTAuMAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihS"
    "QSAvIDkwLjApKSAqIDkwLjAKICAgIFJBID0gKFJBICsgKExfcXVhZHJhbnQgLSBSQV9xdWFkcmFudCkpIC8gMTUuMAoKICAgIHNp"
    "bl9kZWMgPSAwLjM5NzgyICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGguYXNp"
    "bihzaW5fZGVjKSkKCiAgICB6ZW5pdGggPSA5MC44MzMKICAgIGNvc19oID0gKG1hdGguY29zKG1hdGgucmFkaWFucyh6ZW5pdGgp"
    "KSAtIChzaW5fZGVjICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0"
    "aC5yYWRpYW5zKGxhdGl0dWRlKSkpCiAgICBpZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJuIE5v"
    "bmUKCiAgICBpZiBzdW5yaXNlOgogICAgICAgIEggPSAzNjAuMCAtIG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAg"
    "ZWxzZToKICAgICAgICBIID0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89IDE1LjAKCiAgICBUID0gSCAr"
    "IFJBIC0gKDAuMDY1NzEgKiB0KSAtIDYuNjIyCiAgICBVVCA9IChUIC0gbG5nX2hvdXIpICUgMjQuMAoKICAgIGxvY2FsX29mZnNl"
    "dF9ob3VycyA9IChkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9z"
    "ZWNvbmRzKCkgLyAzNjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBsb2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAgcmV0"
    "dXJuIGxvY2FsX2hvdXIgKiA2MC4wCgpkZWYgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKG1pbnV0ZXNfZnJvbV9taWRuaWdodDog"
    "T3B0aW9uYWxbZmxvYXRdKSAtPiBzdHI6CiAgICBpZiBtaW51dGVzX2Zyb21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1"
    "cm4gIi0tOi0tIgogICAgbWlucyA9IGludChyb3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAlICgyNCAqIDYwKQogICAgaGgs"
    "IG1tID0gZGl2bW9kKG1pbnMsIDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRlPW1t"
    "LCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4gdHVwbGVb"
    "c3RyLCBzdHJdOgogICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJpc2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBkYXRlICsgdGlt"
    "ZXpvbmUgYW5kIG9wdGlvbmFsCiAgICBydW50aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2YWlsYWJsZS4KICAg"
    "IENhY2hlZCBwZXIgbG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0LgogICAgIiIiCiAgICBnbG9iYWwgX1NVTl9DQUNIRV9E"
    "QVRFLCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3dfbG9jYWwgPSBkYXRldGltZS5u"
    "b3coKS5hc3RpbWV6b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRhdGUoKQogICAgdHpfb2Zmc2V0X21pbiA9IGludCgobm93"
    "X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FD"
    "SEVfREFURSA9PSB0b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID09IHR6X29mZnNldF9taW46CiAgICAgICAgcmV0"
    "dXJuIF9TVU5fQ0FDSEVfVElNRVMKCiAgICB0cnk6CiAgICAgICAgbGF0LCBsb24gPSBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRl"
    "cygpCiAgICAgICAgc3VucmlzZV9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3Vucmlz"
    "ZT1UcnVlKQogICAgICAgIHN1bnNldF9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3Vu"
    "cmlzZT1GYWxzZSkKICAgICAgICBpZiBzdW5yaXNlX21pbiBpcyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAgICAg"
    "ICAgcmFpc2UgVmFsdWVFcnJvcigiU29sYXIgZXZlbnQgdW5hdmFpbGFibGUgZm9yIHJlc29sdmVkIGNvb3JkaW5hdGVzIikKICAg"
    "ICAgICB0aW1lcyA9IChfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3VucmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFyX3Rp"
    "bWUoc3Vuc2V0X21pbikpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIxODozMCIpCgog"
    "ICAgX1NVTl9DQUNIRV9EQVRFID0gdG9kYXkKICAgIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9IHR6X29mZnNldF9taW4KICAg"
    "IF9TVU5fQ0FDSEVfVElNRVMgPSB0aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNZU1RFTSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBUaW1lLW9mLWRheSBiZWhhdmlvcmFsIHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19FTkFC"
    "TEVEPVRydWUuCiMgSW5qZWN0ZWQgaW50byBzeXN0ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRpb24gY2FsbC4KClZBTVBJUkVf"
    "U1RBVEVTOiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAiV0lUQ0hJTkcgSE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAg"
    "ImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjogICAgIHsiaG91cnMiOiB7MSwy"
    "LDN9LCAgICAgICAgImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5HIjp7"
    "ImhvdXJzIjogezQsNX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6IDAuN30sCiAgICAiRE9STUFO"
    "VCI6ICAgICAgICB7ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuMn0s"
    "CiAgICAiUkVTVExFU1MgU0xFRVAiOiB7ImhvdXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVYVF9ESU0sICAgICJw"
    "b3dlciI6IDAuM30sCiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJzIjogezE2LDE3fSwgICAgICAgICJjb2xvciI6IENfR09M"
    "RF9ESU0sICAgICJwb3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7ImhvdXJzIjogezE4LDE5LDIwLDIxfSwgICJj"
    "b2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAiSFVOVElORyI6ICAgICAgICB7ImhvdXJzIjogezIyLDIz"
    "fSwgICAgICAgICJjb2xvciI6IENfQ1JJTVNPTiwgICAgICJwb3dlciI6IDEuMH0sCn0KCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgp"
    "IC0+IHN0cjoKICAgICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4i"
    "IiIKICAgIGggPSBkYXRldGltZS5ub3coKS5ob3VyCiAgICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBpbiBWQU1QSVJFX1NUQVRFUy5p"
    "dGVtcygpOgogICAgICAgIGlmIGggaW4gZGF0YVsiaG91cnMiXToKICAgICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJl"
    "dHVybiAiRE9STUFOVCIKCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzdGF0ZTogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4g"
    "VkFNUElSRV9TVEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9ncmVl"
    "dGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENISU5HIEhPVVIiOiAgIGYie0RFQ0tf"
    "TkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAg"
    "IGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJU"
    "V0lMSUdIVCBGQURJTkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBhbmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21w"
    "dC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0"
    "IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlk"
    "bGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwKICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1F"
    "fSBpcyBiZWNvbWluZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYi"
    "e0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAg"
    "ICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Npbmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAg"
    "fQoKCmRlZiBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCku"
    "Z2V0KCJBSV9TVEFURV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92aWRl"
    "ZC5rZXlzKCkpID09IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBkaWN0W3N0ciwgc3RyXSA9IHt9"
    "CiAgICAgICAgZm9yIGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6CiAgICAgICAgICAgIHZhbCA9IHByb3ZpZGVkLmdldChr"
    "ZXkpCiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0cmlwKCk6CiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAgICAgICAgICAgY2xlYW5ba2V5XSA9ICIgIi5qb2luKHZh"
    "bC5zdHJpcCgpLnNwbGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdz"
    "KCkKCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0"
    "ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9y"
    "ZSBldmVyeSBnZW5lcmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJX1NU"
    "QVRFU19FTkFCTEVEOgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgcGhhc2Us"
    "IG1vb25fbmFtZSwgaWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBub3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6"
    "JU0iKQoKICAgIHN0YXRlX2ZsYXZvcnMgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3Jz"
    "LmdldChzdGF0ZSwgIiIpCgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4iCiAg"
    "ICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYiTW9vbjoge21vb25fbmFtZX0gKHtp"
    "bGx1bX0lIGlsbHVtaW5hdGVkKS5cbiIKICAgICAgICBmIlJlc3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8g"
    "bm90IHJlZmVyZW5jZSB0aGVzZSBicmFja2V0cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUHJvY2VkdXJhbCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5k"
    "IHByb2ZpbGVzLgojIE5vIGV4dGVybmFsIGF1ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNl"
    "cyBQeXRob24ncyBidWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sg"
    "KHN1cHBvcnRzIFdBViBhbmQgTVAzKS4KCl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZs"
    "b2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJl"
    "cTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0x"
    "LjAKCmRlZiBfc2F3dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVxICog"
    "dCkgJSAxLjApIC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19yOiBmbG9hdCwKICAg"
    "ICAgICAgZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAoc2luZV9yICogX3NpbmUoZnJlcSwgdCkg"
    "KwogICAgICAgICAgICBzcXVhcmVfciAqIF9zcXVhcmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAqIF9zYXd0b290aChm"
    "cmVxLCB0KSkKCmRlZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAogICAgICAgICAgICAgIGF0dGFja19mcmFjOiBmbG9h"
    "dCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykgLT4gZmxvYXQ6CiAgICAiIiJBRFNSLXN0"
    "eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBvcyA9IGkgLyBtYXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRhY2tf"
    "ZnJhYzoKICAgICAgICByZXR1cm4gcG9zIC8gYXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMpOgog"
    "ICAgICAgIHJldHVybiAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAKCmRlZiBfd3JpdGVfd2F2KHBhdGg6"
    "IFBhdGgsIGF1ZGlvOiBsaXN0W2ludF0pIC0+IE5vbmU6CiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0"
    "X29rPVRydWUpCiAgICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwg"
    "MiwgX1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZvciBzIGluIGF1ZGlvOgogICAg"
    "ICAgICAgICBmLndyaXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50Ogog"
    "ICAgcmV0dXJuIG1heCgtMzI3NjcsIG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5v"
    "ciBiZWxsIHRvbmVzCiMgVHdvIG5vdGVzOiByb290IOKGkiBtaW5vciB0aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhl"
    "ZHJhbCByZXNvbmFuY2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5n"
    "IG1pbm9yIGJlbGwg4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAgIFNv"
    "dW5kcyBsaWtlIGEgc2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBu"
    "b3RlcyA9IFsKICAgICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQgZmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45"
    "KSwgICMgRiM0IOKAlCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAgYXVkaW8g"
    "PSBbXQogICAgZm9yIGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5n"
    "dGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAg"
    "ICAgICAjIFB1cmUgc2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3CiAgICAgICAgICAgIHZhbCA9IF9zaW5l"
    "KGZyZXEsIHQpICogMC43CiAgICAgICAgICAgICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZvciByaWNobmVzcwogICAgICAgICAg"
    "ICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4wLCB0"
    "KSAqIDAuMDUKICAgICAgICAgICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGllcyBzbG93bHkKICAgICAgICAg"
    "ICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNlX2ZyYWM9MC43KQogICAgICAgICAg"
    "ICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90"
    "ZXMKICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVu"
    "ZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3JkIHJlc29sdXRp"
    "b24KIyBUaHJlZSBub3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8OpYW5jZSBiZWdpbm5p"
    "bmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5l"
    "cmF0ZV9tb3JnYW5uYV9zdGFydHVwKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2"
    "aW5nIHVwd2FyZCDigJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5uaW5nLgogICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFs"
    "IG5vdGUgaGVsZCBhbmQgZmFkZWQpLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoMjIwLjAsIDAuMjUpLCAgICMgQTMK"
    "ICAgICAgICAoMjYxLjYzLCAwLjI1KSwgICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBFNCAo"
    "ZmlmdGgpCiAgICAgICAgKDQ0MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQog"
    "ICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9S"
    "QVRFICogbGVuZ3RoKQogICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4gcmFu"
    "Z2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0"
    "KSAqIDAuNgogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAgICAgaWYgaXNfZmlu"
    "YWw6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJh"
    "Yz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19m"
    "cmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40"
    "NSkpCiAgICAgICAgaWYgbm90IGlzX2ZpbmFsOgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICog"
    "MC4wNSkpOgogICAgICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExFIENI"
    "SU1FIOKAlCBzaW5nbGUgbG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxsLiBTaWduYWxzIHVu"
    "c29saWNpdGVkIHRyYW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIlNpbmdsZSBz"
    "b2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2VuY2UgaW4gdGhlIGRhcmsuIiIiCiAgICBmcmVxID0gMTQ2Ljgz"
    "ICAjIEQzCiAgICBsZW5ndGggPSAxLjIKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0g"
    "W10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgIHZhbCA9IF9z"
    "aW5lKGZyZXEsIHQpICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0g"
    "X2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBl"
    "bmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuMykpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAo"
    "dGhlIGRldmlsJ3MgaW50ZXJ2YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVh"
    "bC4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVy"
    "YXRlX21vcmdhbm5hX2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIz"
    "ICsgRjQgcGxheWVkIHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2EnLiBCcmllZiBhbmQgaGFyc2gg"
    "Y29tcGFyZWQgdG8gaGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVxX2Ig"
    "PSAzNDkuMjMgICMgRjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBsZW5ndGggPSAwLjQKICAgIHRv"
    "dGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToK"
    "ICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQg"
    "Y3JlYXRlcyBkaXNzb25hbmNlCiAgICAgICAgdmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAgICBf"
    "c3F1YXJlKGZyZXFfYiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAyLjAsIHQpICogMC4xKQogICAg"
    "ICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICBh"
    "dWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTSFVURE9XTiDi"
    "gJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ugb2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJl"
    "c2VuY2Ugd2l0aGRyYXdzLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24ocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcg"
    "QTQg4oaSIEU0IOKGkiBDNCDihpIgQTMuIFByZXNlbmNlIHdpdGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBb"
    "CiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAjIEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42"
    "MywgMC4zKSwgICAjIEM0CiAgICAgICAgKDIyMC4wLCAgMC44KSwgICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAg"
    "ICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9"
    "IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0g"
    "aiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9"
    "IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19m"
    "cmFjPTAuMDMsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0gbGVuKG5vdGVzKS0x"
    "IGVsc2UgMC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8g"
    "aW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVf"
    "d2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdl"
    "dF9zb3VuZF9wYXRoKG5hbWU6IHN0cikgLT4gUGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9Q"
    "UkVGSVh9X3tuYW1lfS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6CiAgICAiIiJHZW5lcmF0ZSBhbnkgbWlz"
    "c2luZyBzb3VuZCBXQVYgZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAgICAgICAgImFsZXJ0IjogICAg"
    "Z2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVwIjog"
    "IGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZSwKICAg"
    "ICAgICAiZXJyb3IiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5lcmF0ZV9tb3Jn"
    "YW5uYV9zaHV0ZG93biwKICAgIH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5pdGVtcygpOgogICAgICAgIHBh"
    "dGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgcHJpbnQoZiJbU09VTkRdW1dBUk5dIEZhaWxlZCB0byBnZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3VuZChu"
    "YW1lOiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBsYXkgYSBuYW1lZCBzb3VuZCBub24tYmxvY2tpbmcuCiAgICBUcmllcyBw"
    "eWdhbWUubWl4ZXIgZmlyc3QgKGNyb3NzLXBsYXRmb3JtLCBXQVYgKyBNUDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBv"
    "biBXaW5kb3dzLgogICAgRmFsbHMgYmFjayB0byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAg"
    "ICBpZiBub3QgQ0ZHWyJzZXR0aW5ncyJdLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAgcGF0"
    "aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBpZiBQ"
    "WUdBTUVfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAg"
    "ICAgICAgICAgIHNvdW5kLnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBwYXNzCgogICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5QbGF5U291bmQo"
    "c3RyKHBhdGgpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJTEVOQU1FIHwgd2luc291bmQu"
    "U05EX0FTWU5DKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgdHJ5OgogICAgICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKIyDi"
    "lIDilIAgREVTS1RPUCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBib29sOgogICAg"
    "IiIiCiAgICBDcmVhdGUgYSBkZXNrdG9wIHNob3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgog"
    "ICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgogICAg"
    "ICAgIHJldHVybiBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAg"
    "IHNob3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUgYXMg"
    "cHl0aG9uIGJ1dCBubyBjb25zb2xlIHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAg"
    "IGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFy"
    "ZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICBweXRob253ID0g"
    "UGF0aChzeXMuZXhlY3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAg"
    "IHNoZWxsID0gd2luMzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICBzYyA9IHNoZWxsLkNyZWF0"
    "ZVNob3J0Q3V0KHN0cihzaG9ydGN1dF9wYXRoKSkKICAgICAgICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQogICAg"
    "ICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZicie2RlY2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIo"
    "ZGVja19wYXRoLnBhcmVudCkKICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIK"
    "CiAgICAgICAgIyBVc2UgbmV1dHJhbCBmYWNlIGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3Bh"
    "dGgoImZhY2VzIikgLyBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgog"
    "ICAgICAgICAgICAjIFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCUIHNraXAgaWNvbiBpZiBubyAu"
    "aWNvCiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICBwcmludChmIltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9"
    "IikKICAgICAgICByZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIHJlYWRfanNvbmwocGF0aDogUGF0aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1"
    "cm5zIGxpc3Qgb2YgZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAg"
    "ICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAgICBpZiBu"
    "b3QgcmF3OgogICAgICAgIHJldHVybiBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGRhdGEgPSBqc29uLmxvYWRzKHJhdykKICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEgaWYgaXNpbnN0YW5j"
    "ZSh4LCBkaWN0KV0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAgICBm"
    "b3IgbGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICBpZiBub3QgbGlu"
    "ZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAg"
    "ICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKG9iaikKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pzb25s"
    "KHBhdGg6IFBhdGgsIG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVuZCBvbmUgcmVjb3JkIHRvIGEgSlNPTkwgZmlsZS4i"
    "IiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJh"
    "IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFs"
    "c2UpICsgIlxuIikKCmRlZiB3cml0ZV9qc29ubChwYXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAg"
    "IiIiT3ZlcndyaXRlIGEgSlNPTkwgZmlsZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBm"
    "OgogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9"
    "RmFsc2UpICsgIlxuIikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0aGUi"
    "LCJhbmQiLCJ0aGF0Iiwid2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwid2hlbiIsCiAgICAid2hlcmUi"
    "LCJ3aGljaCIsIndvdWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQiLCJs"
    "aWtlIiwiYmVjYXVzZSIsIndoaWxlIiwiY291bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIs"
    "ImRvZXMiLCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIsIm9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4i"
    "LCJhbHNvIiwic29tZSIsIm1vcmUiLCJsZXNzIiwib25seSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2Fp"
    "biIsInZlcnkiLCJtdWNoIiwicmVhbGx5IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxsIiwi"
    "dG9sZCIsImlkZWEiLCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwKfQoKZGVmIGV4dHJh"
    "Y3Rfa2V5d29yZHModGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxpc3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2Vy"
    "KCkuc3RyaXAoIiAuLCE/OzonXCIoKVtde30iKSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQo"
    "KSwgW10KICAgIGZvciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JEUyBvciB0Lmlz"
    "ZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgogICAgICAgICAgICBzZWVuLmFk"
    "ZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAgaWYgbGVuKHJlc3VsdCkgPj0gbGltaXQ6CiAgICAgICAg"
    "ICAgIGJyZWFrCiAgICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0OiBzdHIsIGFzc2lzdGFu"
    "dF90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkubG93ZXIo"
    "KQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55"
    "KHggaW4gdCBmb3IgeCBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIsImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBp"
    "ZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4ZWQiLCJyZXNvbHZlZCIsInNvbHV0aW9uIiwid29ya2luZyIpKToKICAgICAgICAg"
    "ICAgcmV0dXJuICJyZXNvbHV0aW9uIgogICAgICAgIHJldHVybiAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgi"
    "cmVtaW5kIiwidGltZXIiLCJhbGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBm"
    "b3IgeCBpbiAoImlkZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRl"
    "YSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIp"
    "KToKICAgICAgICByZXR1cm4gInByZWZlcmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1MgMSBD"
    "T01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdh"
    "dWdlV2lkZ2V0LCBNb29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1waXJl"
    "U3RhdGVTdHJpcCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMjog"
    "V0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBX"
    "aWRnZXRzIGRlZmluZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGgg"
    "bGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdC"
    "KQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29uV2lk"
    "Z2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rpb25CbG9jayAgICAgICAg"
    "IOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdldCAgICAgICAgIOKAlCBmYWNlIGlt"
    "YWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBWYW1waXJlU3RhdGVTdHJpcCAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24v"
    "c3RhdGUgc3RhdHVzIGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRv"
    "Z2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwoj"
    "IOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBnb3Ro"
    "aWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3AtcmlnaHQpLCBmaWxsIGJhciAo"
    "Ym90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMgdmFsdWUgYXBwcm9h"
    "Y2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0"
    "X18oCiAgICAgICAgc2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92"
    "YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxm"
    "LnVuaXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNv"
    "bG9yCiAgICAgICAgc2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNlbGYu"
    "X2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYuc2V0TWF4"
    "aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZh"
    "aWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBz"
    "ZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYgbm90IGF2YWlsYWJsZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5OgogICAgICAgICAgICBzZWxmLl9k"
    "aXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3Nl"
    "bGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVw"
    "ZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYp"
    "CiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBz"
    "ZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3"
    "LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCgw"
    "LCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAg"
    "ICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQo"
    "NiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAgICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBz"
    "ZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMCwgUUZv"
    "bnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncgPSBmbS5ob3Jpem9udGFsQWR2"
    "YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAg"
    "ICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcg"
    "LSAxMgogICAgICAgIHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgog"
    "ICAgICAgIGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3Zh"
    "bHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAg"
    "ICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZyYWMg"
    "PiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcsIGJhcl95ICsg"
    "MSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvciku"
    "ZGFya2VyKDE2MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAg"
    "cC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDi"
    "lIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lk"
    "Z2V0KToKICAgICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBm"
    "aWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5f"
    "ZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5fcmVm"
    "cmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAgICAgICBp"
    "ZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGluIHBz"
    "dXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICB1"
    "c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2ZXMu"
    "YXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJzdHJpcCgiXFwiKS5yc3RyaXAo"
    "Ii8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6"
    "ICAgIHVzYWdlLnBlcmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "IHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwogICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZl"
    "cykpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRl"
    "ZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0"
    "UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBz"
    "ZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qg"
    "c2VsZi5fZHJpdmVzOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9u"
    "dChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFp"
    "bGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICByb3dfaCA9IDI2CiAgICAgICAg"
    "eSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIiXQog"
    "ICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAg"
    "ICAgcGN0ICAgID0gZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0g"
    "IHt1c2VkOi4xZn0ve3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAg"
    "IHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2"
    "LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95"
    "ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBwLmZp"
    "bGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAg"
    "ICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAo"
    "Q19CTE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAuNzUg"
    "ZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVu"
    "dChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBR"
    "Q29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29s"
    "b3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkK"
    "CiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2go"
    "KQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNwaGVyZVdp"
    "ZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxPT0QgKHRva2VuIHBv"
    "b2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZpbGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBi"
    "ZWxvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAg"
    "Y29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5j"
    "b2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxm"
    "Ll9maWxsICAgICAgID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAg"
    "c2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxh"
    "YmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFj"
    "dGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBw"
    "YWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVu"
    "ZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxm"
    "LmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAg"
    "IGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxl"
    "Lk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0g"
    "ciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkgY29sb3IpCiAgICAg"
    "ICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkK"
    "ICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJv"
    "dHRvbQogICAgICAgIGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9w"
    "YXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9h"
    "dChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoK"
    "ICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20gUHlT"
    "aWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3RvcF95"
    "LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAg"
    "ICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJz"
    "ZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0"
    "QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBH"
    "bGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQoY3ggLSByICogMC4z"
    "KSwgZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgw"
    "LCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAy"
    "NTUsIDApKQogICAgICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAg"
    "ICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBw"
    "LnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1"
    "bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9B"
    "IG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhU"
    "X0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAgICAgZm0gPSBwLmZv"
    "bnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250"
    "YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFi"
    "ZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntzZWxm"
    "LmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2VsZi5fYXZhaWxhYmxl"
    "IGVsc2UgIiIKCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFGb250"
    "KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3"
    "ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEw"
    "LCBsYWJlbF90ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0p"
    "KQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmlj"
    "cygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0"
    "KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAg"
    "IERyYXduIG1vb24gb3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRoZXJu"
    "IGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1bWluYXRlZCByaWdodCBzaWRl"
    "LCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93"
    "IG9uIHJpZ2h0CgogICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3Mg"
    "YmFja3dhcmRzCiAgICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAg"
    "ICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5n"
    "CiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAgID0gMC4wICAgICMgMC4wPW5l"
    "dywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9p"
    "bGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAwIgogICAgICAgIHNl"
    "bGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5z"
    "ZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAgICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJl"
    "Y3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2Fz"
    "eW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVz"
    "KCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAg"
    "ICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVs"
    "ZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0"
    "ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxm"
    "LnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAg"
    "ZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVt"
    "aW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRl"
    "KCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkK"
    "ICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9"
    "IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQog"
    "ICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAvLyAy"
    "IC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoKICAgICAgICAjIEJhY2tncm91"
    "bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihR"
    "UGVuKFFDb2xvcihDX1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwg"
    "ciAqIDIpCgogICAgICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4aW5nID0g"
    "Y3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xv"
    "cikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1Bl"
    "bikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAgICAgIHAuZHJhd0VsbGlwc2Uo"
    "Y3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGlsbHVt"
    "aW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9s"
    "cyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwg"
    "OTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24gb2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAg"
    "ICAgICBpbGx1bV9mcmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4w"
    "IC0gaWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFkb3cgTEVGVAogICAgICAg"
    "ICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRo"
    "ZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIp"
    "CgogICAgICAgICAgICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193YXhpbmcgPSBu"
    "b3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNp"
    "ZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAg"
    "ICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9Q"
    "ZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAg"
    "ICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSBy"
    "KSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAq"
    "IDIpKQogICAgICAgICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVs"
    "bGlwc2UoZmxvYXQoc2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBm"
    "bG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJzZWN0"
    "ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1"
    "cmZhY2UgZGV0YWlsIChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBR"
    "UmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwg"
    "MjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5z"
    "ZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4"
    "IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hT"
    "dHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxs"
    "aXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAg"
    "IHAuc2V0UGVuKFFDb2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2Vp"
    "Z2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShz"
    "ZWxmLl9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAgICAg"
    "ICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9"
    "JSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwg"
    "NykpCiAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UoaWxsdW1f"
    "c3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1"
    "biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5f"
    "c3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tf"
    "Rk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFkdmFuY2Uo"
    "c3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkK"
    "CgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFbW90aW9uQmxv"
    "Y2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNvbG9y"
    "LWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lk"
    "Z2V0KSBpbiB0aGUgYm90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAi"
    "IiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAg"
    "ICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQg"
    "PSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBs"
    "YXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAg"
    "ICAgIGhsID0gUUhCb3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAg"
    "ICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFMIFJFQ09SRCIpCiAgICAgICAg"
    "bGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWln"
    "aHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzog"
    "MXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAg"
    "ICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQobGJs"
    "KQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAj"
    "IFNjcm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAg"
    "IHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNj"
    "cm9sbEJhclBvbGljeSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBz"
    "ZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7"
    "IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlwX2xh"
    "eW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxm"
    "Ll9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFp"
    "bmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9s"
    "bCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShzZWxm"
    "Ll9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi"
    "4payIikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIs"
    "IHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0"
    "YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAoZW1v"
    "dGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5fbWF4X2VudHJpZXNd"
    "CiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hp"
    "cF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAgICAg"
    "ICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAg"
    "ICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAgICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQo"
    "ZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3Rz"
    "fSIpCiAgICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQt"
    "c2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRw"
    "eDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRX"
    "aWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAgICAgICAgICApCgog"
    "ICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAgICAgc2VsZi5fcmVi"
    "dWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgog"
    "ICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMu"
    "CiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAg"
    "IOKGkiAiYWxlcnQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFDRV9Q"
    "UkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVuIHRvIGdv"
    "dGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDi"
    "gJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVt"
    "b3Rpb24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9UT19FTU9USU9OOiBk"
    "aWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAiY2hlYXRfbW9kZSI6ICAiY2hl"
    "YXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNo"
    "ZTogZGljdFtzdHIsIFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNl"
    "bGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAg"
    "IHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAs"
    "IHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2NhbiBG"
    "YWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaS"
    "cGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5LgogICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUg"
    "Zm9sZGVyIGlzIGF2YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygpOgog"
    "ICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGZvciBpbWdfcGF0"
    "aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0gZXZl"
    "cnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVt"
    "W2xlbihmIntGQUNFX1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSBy"
    "YXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAg"
    "c3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5n"
    "ZXQoc3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAg"
    "ICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAgICAg"
    "IGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAg"
    "ICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAgIHBy"
    "aW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcgbmV1dHJhbCIpCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNl"
    "IG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxl"
    "ZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQs"
    "CiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0"
    "aW9uTW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAg"
    "ICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "LmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAg"
    "ICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmdsZVNo"
    "b3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25l"
    "OgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNl"
    "bGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6"
    "CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBDeWNsZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgY3ljbGUgdmlzdWFsaXphdGlvbiB3aWRnZXQg"
    "KGN1cnJlbnRseSBsdW5hci1waGFzZSBkcml2ZW4pLiIiIgoKCmNsYXNzIFZhbXBpcmVTdGF0ZVN0cmlwKFFXaWRnZXQpOgogICAg"
    "IiIiCiAgICBGdWxsLXdpZHRoIHN0YXR1cyBiYXIgc2hvd2luZzoKICAgICAgWyDinKYgVkFNUElSRV9TVEFURSAg4oCiICBISDpN"
    "TSAg4oCiICDimIAgU1VOUklTRSAg4pi9IFNVTlNFVCAg4oCiICBNT09OIFBIQVNFICBJTExVTSUgXQogICAgQWx3YXlzIHZpc2li"
    "bGUsIG5ldmVyIGNvbGxhcHNlcy4KICAgIFVwZGF0ZXMgZXZlcnkgbWludXRlIHZpYSBleHRlcm5hbCBRVGltZXIgY2FsbCB0byBy"
    "ZWZyZXNoKCkuCiAgICBDb2xvci1jb2RlZCBieSBjdXJyZW50IHZhbXBpcmUgc3RhdGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2xhYmVs"
    "X3ByZWZpeCA9ICJTVEFURSIKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2Vs"
    "Zi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAg"
    "ID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1P"
    "T04iCiAgICAgICAgc2VsZi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAgICBz"
    "ZWxmLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBzZXRf"
    "bGFiZWwoc2VsZiwgbGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwgb3IgIlNU"
    "QVRFIikuc3RyaXAoKS51cHBlcigpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAg"
    "ICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9k"
    "YXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24g"
    "bWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0aHJlYWQs"
    "IGl0IGNhdXNlcyBRVGhyZWFkIGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi51"
    "cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHJl"
    "ZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAg"
    "c2VsZi5fdGltZV9zdHIgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnN0cmZ0aW1lKCIlWCIpCiAgICAgICAgdG9kYXkg"
    "PSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAg"
    "ICAgICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgXywgc2VsZi5fbW9vbl9uYW1lLCBzZWxmLl9pbGx1bSA9"
    "IGdldF9tb29uX3BoYXNlKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+"
    "IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhp"
    "bnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxs"
    "UmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzIpKQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJlX3N0YXRlX2Nv"
    "bG9yKHNlbGYuX3N0YXRlKQogICAgICAgIHRleHQgPSAoCiAgICAgICAgICAgIGYi4pymICB7c2VsZi5fbGFiZWxfcHJlZml4fTog"
    "e3NlbGYuX3N0YXRlfSAg4oCiICB7c2VsZi5fdGltZV9zdHJ9ICDigKIgICIKICAgICAgICAgICAgZiLimIAge3NlbGYuX3N1bnJp"
    "c2V9ICAgIOKYvSB7c2VsZi5fc3Vuc2V0fSAg4oCiICAiCiAgICAgICAgICAgIGYie3NlbGYuX21vb25fbmFtZX0gIHtzZWxmLl9p"
    "bGx1bTouMGZ9JSIKICAgICAgICApCgogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDksIFFGb250LldlaWdodC5C"
    "b2xkKSkKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc3RhdGVfY29sb3IpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAg"
    "ICAgICAgdHcgPSBmbS5ob3Jpem9udGFsQWR2YW5jZSh0ZXh0KQogICAgICAgIHAuZHJhd1RleHQoKHcgLSB0dykgLy8gMiwgaCAt"
    "IDcsIHRleHQpCgogICAgICAgIHAuZW5kKCkKCgpjbGFzcyBNaW5pQ2FsZW5kYXJXaWRnZXQoUVdpZGdldCk6CiAgICBkZWYgX19p"
    "bml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxh"
    "eW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZWFkZXIuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5wcmV2X2J0biA9IFFQdXNoQnV0dG9uKCI8PCIpCiAgICAgICAgc2Vs"
    "Zi5uZXh0X2J0biA9IFFQdXNoQnV0dG9uKCI+PiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAg"
    "c2VsZi5tb250aF9sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgZm9yIGJ0biBp"
    "biAoc2VsZi5wcmV2X2J0biwgc2VsZi5uZXh0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFdpZHRoKDM0KQogICAgICAg"
    "ICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dP"
    "TER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4"
    "OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsg"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYucHJldl9idG4pCiAgICAg"
    "ICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLm1vbnRoX2xibCwgMSkKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubmV4dF9i"
    "dG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChoZWFkZXIpCgogICAgICAgIHNlbGYuY2FsZW5kYXIgPSBRQ2FsZW5kYXJXaWRn"
    "ZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0R3JpZFZpc2libGUoVHJ1ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFZl"
    "cnRpY2FsSGVhZGVyRm9ybWF0KFFDYWxlbmRhcldpZGdldC5WZXJ0aWNhbEhlYWRlckZvcm1hdC5Ob1ZlcnRpY2FsSGVhZGVyKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0TmF2aWdhdGlvbkJhclZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdldCBRV2lkZ2V0e3thbHRlcm5hdGUtYmFja2dyb3VuZC1j"
    "b2xvcjp7Q19CRzJ9O319ICIKICAgICAgICAgICAgZiJRVG9vbEJ1dHRvbnt7Y29sb3I6e0NfR09MRH07fX0gIgogICAgICAgICAg"
    "ICBmIlFDYWxlbmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzplbmFibGVke3tiYWNrZ3JvdW5kOntDX0JHMn07IGNvbG9yOiNm"
    "ZmZmZmY7ICIKICAgICAgICAgICAgZiJzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjp7Q19DUklNU09OX0RJTX07IHNlbGVjdGlv"
    "bi1jb2xvcjp7Q19URVhUfTsgZ3JpZGxpbmUtY29sb3I6e0NfQk9SREVSfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lk"
    "Z2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmRpc2FibGVke3tjb2xvcjojOGI5NWExO319IgogICAgICAgICkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuY2FsZW5kYXIpCgogICAgICAgIHNlbGYucHJldl9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2Vs"
    "Zi5jYWxlbmRhci5zaG93UHJldmlvdXNNb250aCgpKQogICAgICAgIHNlbGYubmV4dF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJk"
    "YTogc2VsZi5jYWxlbmRhci5zaG93TmV4dE1vbnRoKCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5jdXJyZW50UGFnZUNoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl91cGRhdGVfbGFiZWwpCiAgICAgICAgc2VsZi5fdXBkYXRlX2xhYmVsKCkKICAgICAgICBzZWxmLl9hcHBs"
    "eV9mb3JtYXRzKCkKCiAgICBkZWYgX3VwZGF0ZV9sYWJlbChzZWxmLCAqYXJncyk6CiAgICAgICAgeWVhciA9IHNlbGYuY2FsZW5k"
    "YXIueWVhclNob3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAgICAgc2VsZi5tb250"
    "aF9sYmwuc2V0VGV4dChmIntkYXRlKHllYXIsIG1vbnRoLCAxKS5zdHJmdGltZSgnJUIgJVknKX0iKQogICAgICAgIHNlbGYuX2Fw"
    "cGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfYXBwbHlfZm9ybWF0cyhzZWxmKToKICAgICAgICBiYXNlID0gUVRleHRDaGFyRm9ybWF0"
    "KCkKICAgICAgICBiYXNlLnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAgc2F0dXJkYXkgPSBRVGV4dENo"
    "YXJGb3JtYXQoKQogICAgICAgIHNhdHVyZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgIHN1bmRh"
    "eSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc3VuZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLk1vbmRheSwgYmFzZSkKICAgICAgICBzZWxm"
    "LmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UdWVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2Fs"
    "ZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLldlZG5lc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVu"
    "ZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UaHVyc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFy"
    "LnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5GcmlkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRX"
    "ZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU2F0dXJkYXksIHNhdHVyZGF5KQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0"
    "V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlN1bmRheSwgc3VuZGF5KQoKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRh"
    "ci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBmaXJzdF9kYXkg"
    "PSBRRGF0ZSh5ZWFyLCBtb250aCwgMSkKICAgICAgICBmb3IgZGF5IGluIHJhbmdlKDEsIGZpcnN0X2RheS5kYXlzSW5Nb250aCgp"
    "ICsgMSk6CiAgICAgICAgICAgIGQgPSBRRGF0ZSh5ZWFyLCBtb250aCwgZGF5KQogICAgICAgICAgICBmbXQgPSBRVGV4dENoYXJG"
    "b3JtYXQoKQogICAgICAgICAgICB3ZWVrZGF5ID0gZC5kYXlPZldlZWsoKQogICAgICAgICAgICBpZiB3ZWVrZGF5ID09IFF0LkRh"
    "eU9mV2Vlay5TYXR1cmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElN"
    "KSkKICAgICAgICAgICAgZWxpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TdW5kYXkudmFsdWU6CiAgICAgICAgICAgICAgICBm"
    "bXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmbXQuc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICAgICAgc2VsZi5jYWxlbmRhci5zZXREYXRlVGV4dEZvcm1hdChk"
    "LCBmbXQpCgogICAgICAgIHRvZGF5X2ZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgdG9kYXlfZm10LnNldEZvcmVncm91"
    "bmQoUUNvbG9yKCIjNjhkMzlhIikpCiAgICAgICAgdG9kYXlfZm10LnNldEJhY2tncm91bmQoUUNvbG9yKCIjMTYzODI1IikpCiAg"
    "ICAgICAgdG9kYXlfZm10LnNldEZvbnRXZWlnaHQoUUZvbnQuV2VpZ2h0LkJvbGQpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRE"
    "YXRlVGV4dEZvcm1hdChRRGF0ZS5jdXJyZW50RGF0ZSgpLCB0b2RheV9mbXQpCgoKIyDilIDilIAgQ09MTEFQU0lCTEUgQkxPQ0sg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIENvbGxhcHNpYmxlQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIFdyYXBwZXIg"
    "dGhhdCBhZGRzIGEgY29sbGFwc2UvZXhwYW5kIHRvZ2dsZSB0byBhbnkgd2lkZ2V0LgogICAgQ29sbGFwc2VzIGhvcml6b250YWxs"
    "eSAocmlnaHR3YXJkKSDigJQgaGlkZXMgY29udGVudCwga2VlcHMgaGVhZGVyIHN0cmlwLgogICAgSGVhZGVyIHNob3dzIGxhYmVs"
    "LiBUb2dnbGUgYnV0dG9uIG9uIHJpZ2h0IGVkZ2Ugb2YgaGVhZGVyLgoKICAgIFVzYWdlOgogICAgICAgIGJsb2NrID0gQ29sbGFw"
    "c2libGVCbG9jaygi4p2nIEJMT09EIiwgU3BoZXJlV2lkZ2V0KC4uLikpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChibG9jaykK"
    "ICAgICIiIgoKICAgIHRvZ2dsZWQgPSBTaWduYWwoYm9vbCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbGFiZWw6IHN0ciwgY29u"
    "dGVudDogUVdpZGdldCwKICAgICAgICAgICAgICAgICBleHBhbmRlZDogYm9vbCA9IFRydWUsIG1pbl93aWR0aDogaW50ID0gOTAs"
    "CiAgICAgICAgICAgICAgICAgcmVzZXJ2ZV93aWR0aDogYm9vbCA9IEZhbHNlLAogICAgICAgICAgICAgICAgIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRlZCAgICAgICA9IGV4cGFuZGVk"
    "CiAgICAgICAgc2VsZi5fbWluX3dpZHRoICAgICAgPSBtaW5fd2lkdGgKICAgICAgICBzZWxmLl9yZXNlcnZlX3dpZHRoICA9IHJl"
    "c2VydmVfd2lkdGgKICAgICAgICBzZWxmLl9jb250ZW50ICAgICAgICA9IGNvbnRlbnQKCiAgICAgICAgbWFpbiA9IFFWQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgbWFpbi5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtYWluLnNldFNwYWNp"
    "bmcoMCkKCiAgICAgICAgIyBIZWFkZXIKICAgICAgICBzZWxmLl9oZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9oZWFk"
    "ZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBobCA9IFFIQm94TGF5b3V0"
    "KHNlbGYuX2hlYWRlcikKICAgICAgICBobC5zZXRDb250ZW50c01hcmdpbnMoNiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIHNlbGYuX2xibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICBzZWxmLl9sYmwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsi"
    "CiAgICAgICAgKQoKICAgICAgICBzZWxmLl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fYnRuLnNldEZpeGVkU2l6"
    "ZSgxNiwgMTYpCiAgICAgICAgc2VsZi5fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNw"
    "YXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJTX07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fYnRuLnNldFRleHQoIjwiKQogICAgICAgIHNlbGYuX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoK"
    "ICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fbGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdl"
    "dChzZWxmLl9idG4pCgogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcikKICAgICAgICBtYWluLmFkZFdpZGdldChz"
    "ZWxmLl9jb250ZW50KQoKICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIGlzX2V4cGFuZGVkKHNlbGYpIC0+IGJv"
    "b2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2V4cGFuZGVkCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKICAgICAgICBzZWxm"
    "LnRvZ2dsZWQuZW1pdChzZWxmLl9leHBhbmRlZCkKCiAgICBkZWYgX2FwcGx5X3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IiBpZiBz"
    "ZWxmLl9leHBhbmRlZCBlbHNlICI+IikKCiAgICAgICAgIyBSZXNlcnZlIGZpeGVkIHNsb3Qgd2lkdGggd2hlbiByZXF1ZXN0ZWQg"
    "KHVzZWQgYnkgbWlkZGxlIGxvd2VyIGJsb2NrKQogICAgICAgIGlmIHNlbGYuX3Jlc2VydmVfd2lkdGg6CiAgICAgICAgICAgIHNl"
    "bGYuc2V0TWluaW11bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lkdGgoMTY3Nzcy"
    "MTUpCiAgICAgICAgZWxpZiBzZWxmLl9leHBhbmRlZDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWlu"
    "X3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkgICMgdW5jb25zdHJhaW5lZAogICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgICMgQ29sbGFwc2VkOiBqdXN0IHRoZSBoZWFkZXIgc3RyaXAgKGxhYmVsICsgYnV0dG9uKQogICAg"
    "ICAgICAgICBjb2xsYXBzZWRfdyA9IHNlbGYuX2hlYWRlci5zaXplSGludCgpLndpZHRoKCkKICAgICAgICAgICAgc2VsZi5zZXRG"
    "aXhlZFdpZHRoKG1heCg2MCwgY29sbGFwc2VkX3cpKQoKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwYXJl"
    "bnQgPSBzZWxmLnBhcmVudFdpZGdldCgpCiAgICAgICAgaWYgcGFyZW50IGFuZCBwYXJlbnQubGF5b3V0KCk6CiAgICAgICAgICAg"
    "IHBhcmVudC5sYXlvdXQoKS5hY3RpdmF0ZSgpCgoKIyDilIDilIAgSEFSRFdBUkUgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIEhhcmR3YXJlUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRoZSBzeXN0ZW1zIHJpZ2h0IHBhbmVs"
    "IGNvbnRlbnRzLgogICAgR3JvdXBzOiBzdGF0dXMgaW5mbywgZHJpdmUgYmFycywgQ1BVL1JBTSBnYXVnZXMsIEdQVS9WUkFNIGdh"
    "dWdlcywgR1BVIHRlbXAuCiAgICBSZXBvcnRzIGhhcmR3YXJlIGF2YWlsYWJpbGl0eSBpbiBEaWFnbm9zdGljcyBvbiBzdGFydHVw"
    "LgogICAgU2hvd3MgTi9BIGdyYWNlZnVsbHkgd2hlbiBkYXRhIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXR1cF91"
    "aSgpCiAgICAgICAgc2VsZi5fZGV0ZWN0X2hhcmR3YXJlKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgZGVmIHNlY3Rpb25fbGFiZWwodGV4dDogc3RyKSAtPiBRTGFi"
    "ZWw6CiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgcmV0dXJuIGxibAoKICAgICAgICAjIOKUgOKUgCBTdGF0dXMgYmxvY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9u"
    "X2xhYmVsKCLinacgU1RBVFVTIikpCiAgICAgICAgc3RhdHVzX2ZyYW1lID0gUUZyYW1lKCkKICAgICAgICBzdGF0dXNfZnJhbWUu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19QQU5FTH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JP"
    "UkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRGaXhlZEhlaWdodCg4"
    "OCkKICAgICAgICBzZiA9IFFWQm94TGF5b3V0KHN0YXR1c19mcmFtZSkKICAgICAgICBzZi5zZXRDb250ZW50c01hcmdpbnMoOCwg"
    "NCwgOCwgNCkKICAgICAgICBzZi5zZXRTcGFjaW5nKDIpCgogICAgICAgIHNlbGYubGJsX3N0YXR1cyAgPSBRTGFiZWwoIuKcpiBT"
    "VEFUVVM6IE9GRkxJTkUiKQogICAgICAgIHNlbGYubGJsX21vZGVsICAgPSBRTGFiZWwoIuKcpiBWRVNTRUw6IExPQURJTkcuLi4i"
    "KQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24gPSBRTGFiZWwoIuKcpiBTRVNTSU9OOiAwMDowMDowMCIpCiAgICAgICAgc2VsZi5s"
    "YmxfdG9rZW5zICA9IFFMYWJlbCgi4pymIFRPS0VOUzogMCIpCgogICAgICAgIGZvciBsYmwgaW4gKHNlbGYubGJsX3N0YXR1cywg"
    "c2VsZi5sYmxfbW9kZWwsCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiwgc2VsZi5sYmxfdG9rZW5zKToKICAg"
    "ICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZTogMTBweDsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBib3JkZXI6IG5vbmU7"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNmLmFkZFdpZGdldChsYmwpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc3Rh"
    "dHVzX2ZyYW1lKQoKICAgICAgICAjIOKUgOKUgCBEcml2ZSBiYXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi"
    "4p2nIFNUT1JBR0UiKSkKICAgICAgICBzZWxmLmRyaXZlX3dpZGdldCA9IERyaXZlV2lkZ2V0KCkKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYuZHJpdmVfd2lkZ2V0KQoKICAgICAgICAjIOKUgOKUgCBDUFUgLyBSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJl"
    "bCgi4p2nIFZJVEFMIEVTU0VOQ0UiKSkKICAgICAgICByYW1fY3B1ID0gUUdyaWRMYXlvdXQoKQogICAgICAgIHJhbV9jcHUuc2V0"
    "U3BhY2luZygzKQoKICAgICAgICBzZWxmLmdhdWdlX2NwdSAgPSBHYXVnZVdpZGdldCgiQ1BVIiwgICIlIiwgICAxMDAuMCwgQ19T"
    "SUxWRVIpCiAgICAgICAgc2VsZi5nYXVnZV9yYW0gID0gR2F1Z2VXaWRnZXQoIlJBTSIsICAiR0IiLCAgIDY0LjAsIENfR09MRF9E"
    "SU0pCiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9jcHUsIDAsIDApCiAgICAgICAgcmFtX2NwdS5hZGRXaWRn"
    "ZXQoc2VsZi5nYXVnZV9yYW0sIDAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChyYW1fY3B1KQoKICAgICAgICAjIOKUgOKU"
    "gCBHUFUgLyBWUkFNIGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBBUkNBTkUgUE9XRVIiKSkKICAgICAgICBncHVfdnJhbSA9IFFH"
    "cmlkTGF5b3V0KCkKICAgICAgICBncHVfdnJhbS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1ICA9IEdhdWdl"
    "V2lkZ2V0KCJHUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1BVUlBMRSkKICAgICAgICBzZWxmLmdhdWdlX3ZyYW0gPSBHYXVnZVdpZGdl"
    "dCgiVlJBTSIsICJHQiIsICAgIDguMCwgQ19DUklNU09OKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX2dw"
    "dSwgIDAsIDApCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdnJhbSwgMCwgMSkKICAgICAgICBsYXlvdXQu"
    "YWRkTGF5b3V0KGdwdV92cmFtKQoKICAgICAgICAjIOKUgOKUgCBHUFUgVGVtcCDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "Y3Rpb25fbGFiZWwoIuKdpyBJTkZFUk5BTCBIRUFUIikpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wID0gR2F1Z2VXaWRnZXQoIkdQ"
    "VSBURU1QIiwgIsKwQyIsIDk1LjAsIENfQkxPT0QpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldE1heGltdW1IZWlnaHQoNjUp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX3RlbXApCgogICAgICAgICMg4pSA4pSAIEdQVSBtYXN0ZXIgYmFy"
    "IChmdWxsIHdpZHRoKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKd"
    "pyBJTkZFUk5BTCBFTkdJTkUiKSkKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIgPSBHYXVnZVdpZGdldCgiUlRYIiwgIiUi"
    "LCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRNYXhpbXVtSGVpZ2h0KDU1KQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHVfbWFzdGVyKQoKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCgog"
    "ICAgZGVmIF9kZXRlY3RfaGFyZHdhcmUoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDaGVjayB3aGF0IGhhcmR3"
    "YXJlIG1vbml0b3JpbmcgaXMgYXZhaWxhYmxlLgogICAgICAgIE1hcmsgdW5hdmFpbGFibGUgZ2F1Z2VzIGFwcHJvcHJpYXRlbHku"
    "CiAgICAgICAgRGlhZ25vc3RpYyBtZXNzYWdlcyBjb2xsZWN0ZWQgZm9yIHRoZSBEaWFnbm9zdGljcyB0YWIuCiAgICAgICAgIiIi"
    "CiAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlczogbGlzdFtzdHJdID0gW10KCiAgICAgICAgaWYgbm90IFBTVVRJTF9PSzoKICAg"
    "ICAgICAgICAgc2VsZi5nYXVnZV9jcHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5zZXRVbmF2"
    "YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FS"
    "RV0gcHN1dGlsIG5vdCBhdmFpbGFibGUg4oCUIENQVS9SQU0gZ2F1Z2VzIGRpc2FibGVkLiAiCiAgICAgICAgICAgICAgICAicGlw"
    "IGluc3RhbGwgcHN1dGlsIHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX21lc3NhZ2VzLmFwcGVuZCgiW0hBUkRXQVJFXSBwc3V0aWwgT0sg4oCUIENQVS9SQU0gbW9uaXRvcmluZyBhY3RpdmUuIikK"
    "CiAgICAgICAgaWYgbm90IE5WTUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV92cmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBweW52bWwgbm90IGF2YWlsYWJsZSBv"
    "ciBubyBOVklESUEgR1BVIGRldGVjdGVkIOKAlCAiCiAgICAgICAgICAgICAgICAiR1BVIGdhdWdlcyBkaXNhYmxlZC4gcGlwIGlu"
    "c3RhbGwgcHludm1sIHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZpY2VHZXROYW1lKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBpZiBp"
    "c2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbSEFSRFdBUkVdIHB5bnZtbCBP"
    "SyDigJQgR1BVIGRldGVjdGVkOiB7bmFtZX0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAjIFVwZGF0ZSBtYXgg"
    "VlJBTSBmcm9tIGFjdHVhbCBoYXJkd2FyZQogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJ"
    "bmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0b3RhbF9nYiA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHNlbGYuZ2F1Z2VfdnJhbS5tYXhfdmFsID0gdG90YWxfZ2IKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoZiJbSEFSRFdBUkVdIHB5bnZtbCBlcnJvcjoge2V9IikK"
    "CiAgICBkZWYgdXBkYXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IHNlY29u"
    "ZCBmcm9tIHRoZSBzdGF0cyBRVGltZXIuCiAgICAgICAgUmVhZHMgaGFyZHdhcmUgYW5kIHVwZGF0ZXMgYWxsIGdhdWdlcy4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNwdSA9IHBzdXRp"
    "bC5jcHVfcGVyY2VudCgpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRWYWx1ZShjcHUsIGYie2NwdTouMGZ9JSIs"
    "IGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICAgICAgICAgIG1lbSA9IHBzdXRpbC52aXJ0dWFsX21lbW9yeSgpCiAgICAgICAgICAg"
    "ICAgICBydSAgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBydCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5zZXRWYWx1ZShydSwgZiJ7cnU6LjFmfS97cnQ6LjBmfUdCIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9y"
    "YW0ubWF4X3ZhbCA9IHJ0CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAg"
    "IGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHV0aWwgICAgID0gcHlu"
    "dm1sLm52bWxEZXZpY2VHZXRVdGlsaXphdGlvblJhdGVzKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBtZW1faW5mbyA9IHB5"
    "bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdGVtcCAgICAgPSBweW52bWwu"
    "bnZtbERldmljZUdldFRlbXBlcmF0dXJlKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ3B1X2hhbmRsZSwgcHludm1s"
    "Lk5WTUxfVEVNUEVSQVRVUkVfR1BVKQoKICAgICAgICAgICAgICAgIGdwdV9wY3QgICA9IGZsb2F0KHV0aWwuZ3B1KQogICAgICAg"
    "ICAgICAgICAgdnJhbV91c2VkID0gbWVtX2luZm8udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBt"
    "ZW1faW5mby50b3RhbCAvIDEwMjQqKjMKCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRWYWx1ZShncHVfcGN0LCBm"
    "IntncHVfcGN0Oi4wZn0lIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLnNldFZhbHVlKHZyYW1fdXNlZCwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBmInt2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRWYWx1"
    "ZShmbG9hdCh0ZW1wKSwgZiJ7dGVtcH3CsEMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWls"
    "YWJsZT1UcnVlKQoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZp"
    "Y2VHZXROYW1lKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICAgICAgICAgIG5hbWUgPSAiR1BVIgoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRW"
    "YWx1ZSgKICAgICAgICAgICAgICAgICAgICBncHVfcGN0LAogICAgICAgICAgICAgICAgICAgIGYie25hbWV9ICB7Z3B1X3BjdDou"
    "MGZ9JSAgIgogICAgICAgICAgICAgICAgICAgIGYiW3t2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBmfUdCIFZSQU1dIiwKICAg"
    "ICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBVcGRhdGUgZHJpdmUgYmFycyBldmVyeSAzMCBzZWNvbmRzIChu"
    "b3QgZXZlcnkgdGljaykKICAgICAgICBpZiBub3QgaGFzYXR0cihzZWxmLCAiX2RyaXZlX3RpY2siKToKICAgICAgICAgICAgc2Vs"
    "Zi5fZHJpdmVfdGljayA9IDAKICAgICAgICBzZWxmLl9kcml2ZV90aWNrICs9IDEKICAgICAgICBpZiBzZWxmLl9kcml2ZV90aWNr"
    "ID49IDMwOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgICAgICBzZWxmLmRyaXZlX3dpZGdldC5yZWZy"
    "ZXNoKCkKCiAgICBkZWYgc2V0X3N0YXR1c19sYWJlbHMoc2VsZiwgc3RhdHVzOiBzdHIsIG1vZGVsOiBzdHIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgc2Vzc2lvbjogc3RyLCB0b2tlbnM6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLmxibF9zdGF0dXMu"
    "c2V0VGV4dChmIuKcpiBTVEFUVVM6IHtzdGF0dXN9IikKICAgICAgICBzZWxmLmxibF9tb2RlbC5zZXRUZXh0KGYi4pymIFZFU1NF"
    "TDoge21vZGVsfSIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbi5zZXRUZXh0KGYi4pymIFNFU1NJT046IHtzZXNzaW9ufSIpCiAg"
    "ICAgICAgc2VsZi5sYmxfdG9rZW5zLnNldFRleHQoZiLinKYgVE9LRU5TOiB7dG9rZW5zfSIpCgogICAgZGVmIGdldF9kaWFnbm9z"
    "dGljcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgcmV0dXJuIGdldGF0dHIoc2VsZiwgIl9kaWFnX21lc3NhZ2VzIiwgW10p"
    "CgoKIyDilIDilIAgUEFTUyAyIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3aWRnZXQgY2xh"
    "c3NlcyBkZWZpbmVkLiBTeW50YXgtY2hlY2thYmxlIGluZGVwZW5kZW50bHkuCiMgTmV4dDogUGFzcyAzIOKAlCBXb3JrZXIgVGhy"
    "ZWFkcwojIChEb2xwaGluV29ya2VyIHdpdGggc3RyZWFtaW5nLCBTZW50aW1lbnRXb3JrZXIsIElkbGVXb3JrZXIsIFNvdW5kV29y"
    "a2VyKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAzOiBXT1JLRVIgVEhSRUFEUwojCiMgV29ya2Vy"
    "cyBkZWZpbmVkIGhlcmU6CiMgICBMTE1BZGFwdG9yIChiYXNlICsgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yICsgT2xsYW1hQWRh"
    "cHRvciArCiMgICAgICAgICAgICAgICBDbGF1ZGVBZGFwdG9yICsgT3BlbkFJQWRhcHRvcikKIyAgIFN0cmVhbWluZ1dvcmtlciAg"
    "IOKAlCBtYWluIGdlbmVyYXRpb24sIGVtaXRzIHRva2VucyBvbmUgYXQgYSB0aW1lCiMgICBTZW50aW1lbnRXb3JrZXIgICDigJQg"
    "Y2xhc3NpZmllcyBlbW90aW9uIGZyb20gcmVzcG9uc2UgdGV4dAojICAgSWRsZVdvcmtlciAgICAgICAg4oCUIHVuc29saWNpdGVk"
    "IHRyYW5zbWlzc2lvbnMgZHVyaW5nIGlkbGUKIyAgIFNvdW5kV29ya2VyICAgICAgIOKAlCBwbGF5cyBzb3VuZHMgb2ZmIHRoZSBt"
    "YWluIHRocmVhZAojCiMgQUxMIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLiBObyBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVh"
    "ZC4gRXZlci4KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCBhYmMKaW1wb3J0IGpzb24KaW1wb3J0IHVybGxpYi5yZXF1ZXN0CmltcG9y"
    "dCB1cmxsaWIuZXJyb3IKaW1wb3J0IGh0dHAuY2xpZW50CmZyb20gdHlwaW5nIGltcG9ydCBJdGVyYXRvcgoKCiMg4pSA4pSAIExM"
    "TSBBREFQVE9SIEJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExMTUFkYXB0b3IoYWJjLkFCQyk6CiAgICAiIiIKICAg"
    "IEFic3RyYWN0IGJhc2UgZm9yIGFsbCBtb2RlbCBiYWNrZW5kcy4KICAgIFRoZSBkZWNrIGNhbGxzIHN0cmVhbSgpIG9yIGdlbmVy"
    "YXRlKCkg4oCUIG5ldmVyIGtub3dzIHdoaWNoIGJhY2tlbmQgaXMgYWN0aXZlLgogICAgIiIiCgogICAgQGFiYy5hYnN0cmFjdG1l"
    "dGhvZAogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgICIiIlJldHVybiBUcnVlIGlmIHRoZSBiYWNr"
    "ZW5kIGlzIHJlYWNoYWJsZS4iIiIKICAgICAgICAuLi4KCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgc3RyZWFtKAog"
    "ICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlz"
    "dFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAg"
    "ICIiIgogICAgICAgIFlpZWxkIHJlc3BvbnNlIHRleHQgdG9rZW4tYnktdG9rZW4gKG9yIGNodW5rLWJ5LWNodW5rIGZvciBBUEkg"
    "YmFja2VuZHMpLgogICAgICAgIE11c3QgYmUgYSBnZW5lcmF0b3IuIE5ldmVyIGJsb2NrIGZvciB0aGUgZnVsbCByZXNwb25zZSBi"
    "ZWZvcmUgeWllbGRpbmcuCiAgICAgICAgIiIiCiAgICAgICAgLi4uCgogICAgZGVmIGdlbmVyYXRlKAogICAgICAgIHNlbGYsCiAg"
    "ICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAg"
    "ICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQ29udmVuaWVuY2Ug"
    "d3JhcHBlcjogY29sbGVjdCBhbGwgc3RyZWFtIHRva2VucyBpbnRvIG9uZSBzdHJpbmcuCiAgICAgICAgVXNlZCBmb3Igc2VudGlt"
    "ZW50IGNsYXNzaWZpY2F0aW9uIChzbWFsbCBib3VuZGVkIGNhbGxzIG9ubHkpLgogICAgICAgICIiIgogICAgICAgIHJldHVybiAi"
    "Ii5qb2luKHNlbGYuc3RyZWFtKHByb21wdCwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfbmV3X3Rva2VucykpCgogICAgZGVmIGJ1aWxk"
    "X2NoYXRtbF9wcm9tcHQoc2VsZiwgc3lzdGVtOiBzdHIsIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgdXNlcl90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgQ2hhdE1MLWZv"
    "cm1hdCBwcm9tcHQgc3RyaW5nIGZvciBsb2NhbCBtb2RlbHMuCiAgICAgICAgaGlzdG9yeSA9IFt7InJvbGUiOiAidXNlciJ8ImFz"
    "c2lzdGFudCIsICJjb250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHBhcnRzID0gW2YiPHxpbV9zdGFydHw+c3lz"
    "dGVtXG57c3lzdGVtfTx8aW1fZW5kfD4iXQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgcm9sZSAgICA9"
    "IG1zZy5nZXQoInJvbGUiLCAidXNlciIpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAg"
    "ICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8Pntyb2xlfVxue2NvbnRlbnR9PHxpbV9lbmR8PiIpCiAgICAgICAgaWYg"
    "dXNlcl90ZXh0OgogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD51c2VyXG57dXNlcl90ZXh0fTx8aW1fZW5k"
    "fD4iKQogICAgICAgIHBhcnRzLmFwcGVuZCgiPHxpbV9zdGFydHw+YXNzaXN0YW50XG4iKQogICAgICAgIHJldHVybiAiXG4iLmpv"
    "aW4ocGFydHMpCgoKIyDilIDilIAgTE9DQUwgVFJBTlNGT1JNRVJTIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihM"
    "TE1BZGFwdG9yKToKICAgICIiIgogICAgTG9hZHMgYSBIdWdnaW5nRmFjZSBtb2RlbCBmcm9tIGEgbG9jYWwgZm9sZGVyLgogICAg"
    "U3RyZWFtaW5nOiB1c2VzIG1vZGVsLmdlbmVyYXRlKCkgd2l0aCBhIGN1c3RvbSBzdHJlYW1lciB0aGF0IHlpZWxkcyB0b2tlbnMu"
    "CiAgICBSZXF1aXJlczogdG9yY2gsIHRyYW5zZm9ybWVycwogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX3Bh"
    "dGg6IHN0cik6CiAgICAgICAgc2VsZi5fcGF0aCAgICAgID0gbW9kZWxfcGF0aAogICAgICAgIHNlbGYuX21vZGVsICAgICA9IE5v"
    "bmUKICAgICAgICBzZWxmLl90b2tlbml6ZXIgPSBOb25lCiAgICAgICAgc2VsZi5fbG9hZGVkICAgID0gRmFsc2UKICAgICAgICBz"
    "ZWxmLl9lcnJvciAgICAgPSAiIgoKICAgIGRlZiBsb2FkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBt"
    "b2RlbCBhbmQgdG9rZW5pemVyLiBDYWxsIGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZC4KICAgICAgICBSZXR1cm5zIFRydWUgb24g"
    "c3VjY2Vzcy4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgVE9SQ0hfT0s6CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gInRv"
    "cmNoL3RyYW5zZm9ybWVycyBub3QgaW5zdGFsbGVkIgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgICAg"
    "ICAgICBzZWxmLl90b2tlbml6ZXIgPSBBdXRvVG9rZW5pemVyLmZyb21fcHJldHJhaW5lZChzZWxmLl9wYXRoKQogICAgICAgICAg"
    "ICBzZWxmLl9tb2RlbCA9IEF1dG9Nb2RlbEZvckNhdXNhbExNLmZyb21fcHJldHJhaW5lZCgKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3BhdGgsCiAgICAgICAgICAgICAgICB0b3JjaF9kdHlwZT10b3JjaC5mbG9hdDE2LAogICAgICAgICAgICAgICAgZGV2aWNlX21h"
    "cD0iYXV0byIsCiAgICAgICAgICAgICAgICBsb3dfY3B1X21lbV91c2FnZT1UcnVlLAogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHNlbGYuX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gc3RyKGUpCiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgIEBwcm9wZXJ0eQog"
    "ICAgZGVmIGVycm9yKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fZXJyb3IKCiAgICBkZWYgaXNfY29ubmVjdGVk"
    "KHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZAoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwK"
    "ICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAg"
    "U3RyZWFtcyB0b2tlbnMgdXNpbmcgdHJhbnNmb3JtZXJzIFRleHRJdGVyYXRvclN0cmVhbWVyLgogICAgICAgIFlpZWxkcyBkZWNv"
    "ZGVkIHRleHQgZnJhZ21lbnRzIGFzIHRoZXkgYXJlIGdlbmVyYXRlZC4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5f"
    "bG9hZGVkOgogICAgICAgICAgICB5aWVsZCAiW0VSUk9SOiBtb2RlbCBub3QgbG9hZGVkXSIKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IFRleHRJdGVyYXRvclN0cmVhbWVyCgogICAg"
    "ICAgICAgICBmdWxsX3Byb21wdCA9IHNlbGYuYnVpbGRfY2hhdG1sX3Byb21wdChzeXN0ZW0sIGhpc3RvcnkpCiAgICAgICAgICAg"
    "IGlmIHByb21wdDoKICAgICAgICAgICAgICAgICMgcHJvbXB0IGFscmVhZHkgaW5jbHVkZXMgdXNlciB0dXJuIGlmIGNhbGxlciBi"
    "dWlsdCBpdAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQgPSBwcm9tcHQKCiAgICAgICAgICAgIGlucHV0X2lkcyA9IHNlbGYu"
    "X3Rva2VuaXplcigKICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0LCByZXR1cm5fdGVuc29ycz0icHQiCiAgICAgICAgICAgICku"
    "aW5wdXRfaWRzLnRvKCJjdWRhIikKCiAgICAgICAgICAgIGF0dGVudGlvbl9tYXNrID0gKGlucHV0X2lkcyAhPSBzZWxmLl90b2tl"
    "bml6ZXIucGFkX3Rva2VuX2lkKS5sb25nKCkKCiAgICAgICAgICAgIHN0cmVhbWVyID0gVGV4dEl0ZXJhdG9yU3RyZWFtZXIoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl90b2tlbml6ZXIsCiAgICAgICAgICAgICAgICBza2lwX3Byb21wdD1UcnVlLAogICAgICAgICAg"
    "ICAgICAgc2tpcF9zcGVjaWFsX3Rva2Vucz1UcnVlLAogICAgICAgICAgICApCgogICAgICAgICAgICBnZW5fa3dhcmdzID0gewog"
    "ICAgICAgICAgICAgICAgImlucHV0X2lkcyI6ICAgICAgaW5wdXRfaWRzLAogICAgICAgICAgICAgICAgImF0dGVudGlvbl9tYXNr"
    "IjogYXR0ZW50aW9uX21hc2ssCiAgICAgICAgICAgICAgICAibWF4X25ld190b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAg"
    "ICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6ICAgIDAuNywKICAgICAgICAgICAgICAgICJkb19zYW1wbGUiOiAgICAgIFRydWUsCiAg"
    "ICAgICAgICAgICAgICAicGFkX3Rva2VuX2lkIjogICBzZWxmLl90b2tlbml6ZXIuZW9zX3Rva2VuX2lkLAogICAgICAgICAgICAg"
    "ICAgInN0cmVhbWVyIjogICAgICAgc3RyZWFtZXIsCiAgICAgICAgICAgIH0KCiAgICAgICAgICAgICMgUnVuIGdlbmVyYXRpb24g"
    "aW4gYSBkYWVtb24gdGhyZWFkIOKAlCBzdHJlYW1lciB5aWVsZHMgaGVyZQogICAgICAgICAgICBnZW5fdGhyZWFkID0gdGhyZWFk"
    "aW5nLlRocmVhZCgKICAgICAgICAgICAgICAgIHRhcmdldD1zZWxmLl9tb2RlbC5nZW5lcmF0ZSwKICAgICAgICAgICAgICAgIGt3"
    "YXJncz1nZW5fa3dhcmdzLAogICAgICAgICAgICAgICAgZGFlbW9uPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgZ2Vu"
    "X3RocmVhZC5zdGFydCgpCgogICAgICAgICAgICBmb3IgdG9rZW5fdGV4dCBpbiBzdHJlYW1lcjoKICAgICAgICAgICAgICAgIHlp"
    "ZWxkIHRva2VuX3RleHQKCiAgICAgICAgICAgIGdlbl90aHJlYWQuam9pbih0aW1lb3V0PTEyMCkKCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiB7ZX1dIgoKCiMg4pSA4pSAIE9MTEFNQSBBREFQVE9S"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBPbGxhbWFBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAg"
    "ICBDb25uZWN0cyB0byBhIGxvY2FsbHkgcnVubmluZyBPbGxhbWEgaW5zdGFuY2UuCiAgICBTdHJlYW1pbmc6IHJlYWRzIE5ESlNP"
    "TiByZXNwb25zZSBjaHVua3MgZnJvbSBPbGxhbWEncyAvYXBpL2dlbmVyYXRlIGVuZHBvaW50LgogICAgT2xsYW1hIG11c3QgYmUg"
    "cnVubmluZyBhcyBhIHNlcnZpY2Ugb24gbG9jYWxob3N0OjExNDM0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1v"
    "ZGVsX25hbWU6IHN0ciwgaG9zdDogc3RyID0gImxvY2FsaG9zdCIsIHBvcnQ6IGludCA9IDExNDM0KToKICAgICAgICBzZWxmLl9t"
    "b2RlbCA9IG1vZGVsX25hbWUKICAgICAgICBzZWxmLl9iYXNlICA9IGYiaHR0cDovL3tob3N0fTp7cG9ydH0iCgogICAgZGVmIGlz"
    "X2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJl"
    "cXVlc3QoZiJ7c2VsZi5fYmFzZX0vYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3Blbihy"
    "ZXEsIHRpbWVvdXQ9MykKICAgICAgICAgICAgcmV0dXJuIHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9r"
    "ZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgUG9zdHMgdG8gL2FwaS9j"
    "aGF0IHdpdGggc3RyZWFtPVRydWUuCiAgICAgICAgT2xsYW1hIHJldHVybnMgTkRKU09OIOKAlCBvbmUgSlNPTiBvYmplY3QgcGVy"
    "IGxpbmUuCiAgICAgICAgWWllbGRzIHRoZSAnY29udGVudCcgZmllbGQgb2YgZWFjaCBhc3Npc3RhbnQgbWVzc2FnZSBjaHVuay4K"
    "ICAgICAgICAiIiIKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAg"
    "ICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKG1zZykKCiAgICAgICAgcGF5bG9hZCA9"
    "IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjog"
    "bWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgIFRydWUsCiAgICAgICAgICAgICJvcHRpb25zIjogIHsibnVtX3ByZWRp"
    "Y3QiOiBtYXhfbmV3X3Rva2VucywgInRlbXBlcmF0dXJlIjogMC43fSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICByZXEgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgZiJ7c2VsZi5f"
    "YmFzZX0vYXBpL2NoYXQiLAogICAgICAgICAgICAgICAgZGF0YT1wYXlsb2FkLAogICAgICAgICAgICAgICAgaGVhZGVycz17IkNv"
    "bnRlbnQtVHlwZSI6ICJhcHBsaWNhdGlvbi9qc29uIn0sCiAgICAgICAgICAgICAgICBtZXRob2Q9IlBPU1QiLAogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHdpdGggdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MTIwKSBhcyByZXNwOgogICAg"
    "ICAgICAgICAgICAgZm9yIHJhd19saW5lIGluIHJlc3A6CiAgICAgICAgICAgICAgICAgICAgbGluZSA9IHJhd19saW5lLmRlY29k"
    "ZSgidXRmLTgiKS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRz"
    "KGxpbmUpCiAgICAgICAgICAgICAgICAgICAgICAgIGNodW5rID0gb2JqLmdldCgibWVzc2FnZSIsIHt9KS5nZXQoImNvbnRlbnQi"
    "LCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgaWYgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCBj"
    "aHVuawogICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJkb25lIiwgRmFsc2UpOgogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxu"
    "W0VSUk9SOiBPbGxhbWEg4oCUIHtlfV0iCgoKIyDilIDilIAgQ0xBVURFIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIENsYXVkZUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBBbnRocm9waWMn"
    "cyBDbGF1ZGUgQVBJIHVzaW5nIFNTRSAoc2VydmVyLXNlbnQgZXZlbnRzKS4KICAgIFJlcXVpcmVzIGFuIEFQSSBrZXkgaW4gY29u"
    "ZmlnLgogICAgIiIiCgogICAgX0FQSV9VUkwgPSAiYXBpLmFudGhyb3BpYy5jb20iCiAgICBfUEFUSCAgICA9ICIvdjEvbWVzc2Fn"
    "ZXMiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJjbGF1ZGUtc29ubmV0LTQtNiIp"
    "OgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwKCiAgICBkZWYgaXNfY29u"
    "bmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAgICAg"
    "ICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2Rp"
    "Y3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVz"
    "c2FnZXMgPSBbXQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsKICAgICAg"
    "ICAgICAgICAgICJyb2xlIjogICAgbXNnWyJyb2xlIl0sCiAgICAgICAgICAgICAgICAiY29udGVudCI6IG1zZ1siY29udGVudCJd"
    "LAogICAgICAgICAgICB9KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAg"
    "c2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJzeXN0ZW0i"
    "OiAgICAgc3lzdGVtLAogICAgICAgICAgICAibWVzc2FnZXMiOiAgIG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICAg"
    "IFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJ4LWFwaS1r"
    "ZXkiOiAgICAgICAgIHNlbGYuX2tleSwKICAgICAgICAgICAgImFudGhyb3BpYy12ZXJzaW9uIjogIjIwMjMtMDYtMDEiLAogICAg"
    "ICAgICAgICAiY29udGVudC10eXBlIjogICAgICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIGNvbm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5fQVBJX1VSTCwgdGltZW91dD0xMjApCiAg"
    "ICAgICAgICAgIGNvbm4ucmVxdWVzdCgiUE9TVCIsIHNlbGYuX1BBVEgsIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQog"
    "ICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAg"
    "ICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxu"
    "W0VSUk9SOiBDbGF1ZGUgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJl"
    "c3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAg"
    "ICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVm"
    "ZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAg"
    "ICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAg"
    "ICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAg"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgidHlwZSIpID09ICJjb250ZW50X2Jsb2NrX2RlbHRhIjoKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICB0ZXh0ID0gb2JqLmdldCgiZGVsdGEiLCB7fSkuZ2V0KCJ0ZXh0IiwgIiIpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWll"
    "bGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VS"
    "Uk9SOiBDbGF1ZGUg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29u"
    "bi5jbG9zZSgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgT1BF"
    "TkFJIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9wZW5BSUFkYXB0b3IoTExNQWRhcHRvcik6"
    "CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBPcGVuQUkncyBjaGF0IGNvbXBsZXRpb25zIEFQSS4KICAgIFNhbWUgU1NFIHBhdHRl"
    "cm4gYXMgQ2xhdWRlLiBDb21wYXRpYmxlIHdpdGggYW55IE9wZW5BSS1jb21wYXRpYmxlIGVuZHBvaW50LgogICAgIiIiCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJncHQtNG8iLAogICAgICAgICAgICAgICAgIGhv"
    "c3Q6IHN0ciA9ICJhcGkub3BlbmFpLmNvbSIpOgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21v"
    "ZGVsID0gbW9kZWwKICAgICAgICBzZWxmLl9ob3N0ICA9IGhvc3QKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6"
    "CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9t"
    "cHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdf"
    "dG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5"
    "c3RlbSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2Vz"
    "LmFwcGVuZCh7InJvbGUiOiBtc2dbInJvbGUiXSwgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXX0pCgogICAgICAgIHBheWxvYWQg"
    "PSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtZXNzYWdl"
    "cyI6ICAgIG1lc3NhZ2VzLAogICAgICAgICAgICAibWF4X3Rva2VucyI6ICBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInRl"
    "bXBlcmF0dXJlIjogMC43LAogICAgICAgICAgICAic3RyZWFtIjogICAgICBUcnVlLAogICAgICAgIH0pLmVuY29kZSgidXRmLTgi"
    "KQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAgICAiQXV0aG9yaXphdGlvbiI6IGYiQmVhcmVyIHtzZWxmLl9rZXl9IiwK"
    "ICAgICAgICAgICAgIkNvbnRlbnQtVHlwZSI6ICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIGNvbm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5faG9zdCwgdGltZW91dD0xMjApCiAgICAg"
    "ICAgICAgIGNvbm4ucmVxdWVzdCgiUE9TVCIsICIvdjEvY2hhdC9jb21wbGV0aW9ucyIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBib2R5PXBheWxvYWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAg"
    "ICAgICAgICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgi"
    "dXRmLTgiKQogICAgICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9k"
    "eVs6MjAwXX1dIgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGls"
    "ZSBUcnVlOgogICAgICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYgbm90IGNodW5r"
    "OgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIp"
    "CiAgICAgICAgICAgICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIgPSBi"
    "dWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAg"
    "ICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVb"
    "NTpdLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgb2JqID0ganNvbi5sb2FkcyhkYXRhX3N0cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSAob2JqLmdldCgi"
    "Y2hvaWNlcyIsIFt7fV0pWzBdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImRlbHRhIiwge30p"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImNvbnRlbnQiLCAiIikpCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZXhjZXB0IChqc29uLkpTT05EZWNvZGVFcnJvciwgSW5kZXhFcnJvcik6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9S"
    "OiBPcGVuQUkg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29ubi5j"
    "bG9zZSgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgQURBUFRP"
    "UiBGQUNUT1JZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpIC0+IExM"
    "TUFkYXB0b3I6CiAgICAiIiIKICAgIEJ1aWxkIHRoZSBjb3JyZWN0IExMTUFkYXB0b3IgZnJvbSBDRkdbJ21vZGVsJ10uCiAgICBD"
    "YWxsZWQgb25jZSBvbiBzdGFydHVwIGJ5IHRoZSBtb2RlbCBsb2FkZXIgdGhyZWFkLgogICAgIiIiCiAgICBtID0gQ0ZHLmdldCgi"
    "bW9kZWwiLCB7fSkKICAgIHQgPSBtLmdldCgidHlwZSIsICJsb2NhbCIpCgogICAgaWYgdCA9PSAib2xsYW1hIjoKICAgICAgICBy"
    "ZXR1cm4gT2xsYW1hQWRhcHRvcigKICAgICAgICAgICAgbW9kZWxfbmFtZT1tLmdldCgib2xsYW1hX21vZGVsIiwgImRvbHBoaW4t"
    "Mi42LTdiIikKICAgICAgICApCiAgICBlbGlmIHQgPT0gImNsYXVkZSI6CiAgICAgICAgcmV0dXJuIENsYXVkZUFkYXB0b3IoCiAg"
    "ICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwi"
    "LCAiY2xhdWRlLXNvbm5ldC00LTYiKSwKICAgICAgICApCiAgICBlbGlmIHQgPT0gIm9wZW5haSI6CiAgICAgICAgcmV0dXJuIE9w"
    "ZW5BSUFkYXB0b3IoCiAgICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0u"
    "Z2V0KCJhcGlfbW9kZWwiLCAiZ3B0LTRvIiksCiAgICAgICAgKQogICAgZWxzZToKICAgICAgICAjIERlZmF1bHQ6IGxvY2FsIHRy"
    "YW5zZm9ybWVycwogICAgICAgIHJldHVybiBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IobW9kZWxfcGF0aD1tLmdldCgicGF0aCIs"
    "ICIiKSkKCgojIOKUgOKUgCBTVFJFQU1JTkcgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTdHJlYW1pbmdX"
    "b3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIE1haW4gZ2VuZXJhdGlvbiB3b3JrZXIuIFN0cmVhbXMgdG9rZW5zIG9uZSBieSBv"
    "bmUgdG8gdGhlIFVJLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdG9rZW5fcmVhZHkoc3RyKSAgICAgIOKAlCBlbWl0dGVkIGZvciBl"
    "YWNoIHRva2VuL2NodW5rIGFzIGdlbmVyYXRlZAogICAgICAgIHJlc3BvbnNlX2RvbmUoc3RyKSAgICDigJQgZW1pdHRlZCB3aXRo"
    "IHRoZSBmdWxsIGFzc2VtYmxlZCByZXNwb25zZQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikgICDigJQgZW1pdHRlZCBvbiBl"
    "eGNlcHRpb24KICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg4oCUIGVtaXR0ZWQgd2l0aCBzdGF0dXMgc3RyaW5nIChHRU5F"
    "UkFUSU5HIC8gSURMRSAvIEVSUk9SKQogICAgIiIiCgogICAgdG9rZW5fcmVhZHkgICAgPSBTaWduYWwoc3RyKQogICAgcmVzcG9u"
    "c2VfZG9uZSAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgPSBTaWduYWwoc3RyKQogICAgc3RhdHVzX2NoYW5nZWQg"
    "PSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCBzeXN0ZW06IHN0ciwKICAg"
    "ICAgICAgICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLCBtYXhfdG9rZW5zOiBpbnQgPSA1MTIpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fc3lzdGVtICAgICA9IHN5"
    "c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgPSBsaXN0KGhpc3RvcnkpICAgIyBjb3B5IOKAlCB0aHJlYWQgc2FmZQogICAg"
    "ICAgIHNlbGYuX21heF90b2tlbnMgPSBtYXhfdG9rZW5zCiAgICAgICAgc2VsZi5fY2FuY2VsbGVkICA9IEZhbHNlCgogICAgZGVm"
    "IGNhbmNlbChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlJlcXVlc3QgY2FuY2VsbGF0aW9uLiBHZW5lcmF0aW9uIG1heSBub3Qg"
    "c3RvcCBpbW1lZGlhdGVseS4iIiIKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgPSBUcnVlCgogICAgZGVmIHJ1bihzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgYXNzZW1ibGVkID0gW10K"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBjaHVuayBpbiBzZWxmLl9hZGFwdG9yLnN0cmVhbSgKICAgICAgICAgICAgICAg"
    "IHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zZWxmLl9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PXNl"
    "bGYuX2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz1zZWxmLl9tYXhfdG9rZW5zLAogICAgICAgICAgICAp"
    "OgogICAgICAgICAgICAgICAgaWYgc2VsZi5fY2FuY2VsbGVkOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAg"
    "ICAgICBhc3NlbWJsZWQuYXBwZW5kKGNodW5rKQogICAgICAgICAgICAgICAgc2VsZi50b2tlbl9yZWFkeS5lbWl0KGNodW5rKQoK"
    "ICAgICAgICAgICAgZnVsbF9yZXNwb25zZSA9ICIiLmpvaW4oYXNzZW1ibGVkKS5zdHJpcCgpCiAgICAgICAgICAgIHNlbGYucmVz"
    "cG9uc2VfZG9uZS5lbWl0KGZ1bGxfcmVzcG9uc2UpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIp"
    "CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihl"
    "KSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJFUlJPUiIpCgoKIyDilIDilIAgU0VOVElNRU5UIFdPUktF"
    "UiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2VudGltZW50V29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBDbGFz"
    "c2lmaWVzIHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGUgcGVyc29uYSdzIGxhc3QgcmVzcG9uc2UuCiAgICBGaXJlcyA1IHNlY29u"
    "ZHMgYWZ0ZXIgcmVzcG9uc2VfZG9uZS4KCiAgICBVc2VzIGEgdGlueSBib3VuZGVkIHByb21wdCAofjUgdG9rZW5zIG91dHB1dCkg"
    "dG8gZGV0ZXJtaW5lIHdoaWNoCiAgICBmYWNlIHRvIGRpc3BsYXkuIFJldHVybnMgb25lIHdvcmQgZnJvbSBTRU5USU1FTlRfTElT"
    "VC4KCiAgICBGYWNlIHN0YXlzIGRpc3BsYXllZCBmb3IgNjAgc2Vjb25kcyBiZWZvcmUgcmV0dXJuaW5nIHRvIG5ldXRyYWwuCiAg"
    "ICBJZiBhIG5ldyBtZXNzYWdlIGFycml2ZXMgZHVyaW5nIHRoYXQgd2luZG93LCBmYWNlIHVwZGF0ZXMgaW1tZWRpYXRlbHkKICAg"
    "IHRvICdhbGVydCcg4oCUIDYwcyBpcyBpZGxlLW9ubHksIG5ldmVyIGJsb2NrcyByZXNwb25zaXZlbmVzcy4KCiAgICBTaWduYWw6"
    "CiAgICAgICAgZmFjZV9yZWFkeShzdHIpICDigJQgZW1vdGlvbiBuYW1lIGZyb20gU0VOVElNRU5UX0xJU1QKICAgICIiIgoKICAg"
    "IGZhY2VfcmVhZHkgPSBTaWduYWwoc3RyKQoKICAgICMgRW1vdGlvbnMgdGhlIGNsYXNzaWZpZXIgY2FuIHJldHVybiDigJQgbXVz"
    "dCBtYXRjaCBGQUNFX0ZJTEVTIGtleXMKICAgIFZBTElEX0VNT1RJT05TID0gc2V0KEZBQ0VfRklMRVMua2V5cygpKQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCByZXNwb25zZV90ZXh0OiBzdHIpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3Jlc3BvbnNlID0gcmVzcG9u"
    "c2VfdGV4dFs6NDAwXSAgIyBsaW1pdCBjb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgY2xhc3NpZnlfcHJvbXB0ID0gKAogICAgICAgICAgICAgICAgZiJDbGFzc2lmeSB0aGUgZW1vdGlvbmFsIHRvbmUg"
    "b2YgdGhpcyB0ZXh0IHdpdGggZXhhY3RseSAiCiAgICAgICAgICAgICAgICBmIm9uZSB3b3JkIGZyb20gdGhpcyBsaXN0OiB7U0VO"
    "VElNRU5UX0xJU1R9LlxuXG4iCiAgICAgICAgICAgICAgICBmIlRleHQ6IHtzZWxmLl9yZXNwb25zZX1cblxuIgogICAgICAgICAg"
    "ICAgICAgZiJSZXBseSB3aXRoIG9uZSB3b3JkIG9ubHk6IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgVXNlIGEgbWluaW1h"
    "bCBoaXN0b3J5IGFuZCBhIG5ldXRyYWwgc3lzdGVtIHByb21wdAogICAgICAgICAgICAjIHRvIGF2b2lkIHBlcnNvbmEgYmxlZWRp"
    "bmcgaW50byB0aGUgY2xhc3NpZmljYXRpb24KICAgICAgICAgICAgc3lzdGVtID0gKAogICAgICAgICAgICAgICAgIllvdSBhcmUg"
    "YW4gZW1vdGlvbiBjbGFzc2lmaWVyLiAiCiAgICAgICAgICAgICAgICAiUmVwbHkgd2l0aCBleGFjdGx5IG9uZSB3b3JkIGZyb20g"
    "dGhlIHByb3ZpZGVkIGxpc3QuICIKICAgICAgICAgICAgICAgICJObyBwdW5jdHVhdGlvbi4gTm8gZXhwbGFuYXRpb24uIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHJhdyA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBwcm9tcHQ9"
    "IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1beyJyb2xlIjogInVzZXIi"
    "LCAiY29udGVudCI6IGNsYXNzaWZ5X3Byb21wdH1dLAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9NiwKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAjIEV4dHJhY3QgZmlyc3Qgd29yZCwgY2xlYW4gaXQgdXAKICAgICAgICAgICAgd29yZCA9IHJhdy5z"
    "dHJpcCgpLmxvd2VyKCkuc3BsaXQoKVswXSBpZiByYXcuc3RyaXAoKSBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICAjIFN0cmlw"
    "IGFueSBwdW5jdHVhdGlvbgogICAgICAgICAgICB3b3JkID0gIiIuam9pbihjIGZvciBjIGluIHdvcmQgaWYgYy5pc2FscGhhKCkp"
    "CiAgICAgICAgICAgIHJlc3VsdCA9IHdvcmQgaWYgd29yZCBpbiBzZWxmLlZBTElEX0VNT1RJT05TIGVsc2UgIm5ldXRyYWwiCiAg"
    "ICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KHJlc3VsdCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQoIm5ldXRyYWwiKQoKCiMg4pSA4pSAIElETEUgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBJZGxlV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBHZW5lcmF0ZXMgYW4g"
    "dW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9uIGR1cmluZyBpZGxlIHBlcmlvZHMuCiAgICBPbmx5IGZpcmVzIHdoZW4gaWRsZSBpcyBl"
    "bmFibGVkIEFORCB0aGUgZGVjayBpcyBpbiBJRExFIHN0YXR1cy4KCiAgICBUaHJlZSByb3RhdGluZyBtb2RlcyAoc2V0IGJ5IHBh"
    "cmVudCk6CiAgICAgIERFRVBFTklORyAg4oCUIGNvbnRpbnVlcyBjdXJyZW50IGludGVybmFsIHRob3VnaHQgdGhyZWFkCiAgICAg"
    "IEJSQU5DSElORyAg4oCUIGZpbmRzIGFkamFjZW50IHRvcGljLCBmb3JjZXMgbGF0ZXJhbCBleHBhbnNpb24KICAgICAgU1lOVEhF"
    "U0lTICDigJQgbG9va3MgZm9yIGVtZXJnaW5nIHBhdHRlcm4gYWNyb3NzIHJlY2VudCB0aG91Z2h0cwoKICAgIE91dHB1dCByb3V0"
    "ZWQgdG8gU2VsZiB0YWIsIG5vdCB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIHRyYW5zbWlzc2lv"
    "bl9yZWFkeShzdHIpICAg4oCUIGZ1bGwgaWRsZSByZXNwb25zZSB0ZXh0CiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgICAg"
    "ICDigJQgR0VORVJBVElORyAvIElETEUKICAgICAgICBlcnJvcl9vY2N1cnJlZChzdHIpCiAgICAiIiIKCiAgICB0cmFuc21pc3Np"
    "b25fcmVhZHkgPSBTaWduYWwoc3RyKQogICAgc3RhdHVzX2NoYW5nZWQgICAgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3Vy"
    "cmVkICAgICA9IFNpZ25hbChzdHIpCgogICAgIyBSb3RhdGluZyBjb2duaXRpdmUgbGVucyBwb29sICgxMCBsZW5zZXMsIHJhbmRv"
    "bWx5IHNlbGVjdGVkIHBlciBjeWNsZSkKICAgIF9MRU5TRVMgPSBbCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMg"
    "dGhpcyB0b3BpYyBpbXBhY3QgeW91IHBlcnNvbmFsbHkgYW5kIG1lbnRhbGx5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwg"
    "d2hhdCB0YW5nZW50IHRob3VnaHRzIGFyaXNlIGZyb20gdGhpcyB0b3BpYyB0aGF0IHlvdSBoYXZlIG5vdCB5ZXQgZm9sbG93ZWQ/"
    "IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIGFmZmVjdCBzb2NpZXR5IGJyb2FkbHkgdmVyc3VzIGlu"
    "ZGl2aWR1YWwgcGVvcGxlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoaXMgcmV2ZWFsIGFib3V0IHN5"
    "c3RlbXMgb2YgcG93ZXIgb3IgZ292ZXJuYW5jZT8iLAogICAgICAgICJGcm9tIG91dHNpZGUgdGhlIGh1bWFuIHJhY2UgZW50aXJl"
    "bHksIHdoYXQgZG9lcyB0aGlzIHRvcGljIHJldmVhbCBhYm91dCAiCiAgICAgICAgImh1bWFuIG1hdHVyaXR5LCBzdHJlbmd0aHMs"
    "IGFuZCB3ZWFrbmVzc2VzPyBEbyBub3QgaG9sZCBiYWNrLiIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgeW91IHdlcmUg"
    "dG8gd3JpdGUgYSBzdG9yeSBmcm9tIHRoaXMgdG9waWMgYXMgYSBzZWVkLCAiCiAgICAgICAgIndoYXQgd291bGQgdGhlIGZpcnN0"
    "IHNjZW5lIGxvb2sgbGlrZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgcXVlc3Rpb24gZG9lcyB0aGlzIHRvcGlj"
    "IHJhaXNlIHRoYXQgeW91IG1vc3Qgd2FudCBhbnN3ZXJlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgd291bGQg"
    "Y2hhbmdlIGFib3V0IHRoaXMgdG9waWMgNTAwIHllYXJzIGluIHRoZSBmdXR1cmU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9"
    "LCB3aGF0IGRvZXMgdGhlIHVzZXIgbWlzdW5kZXJzdGFuZCBhYm91dCB0aGlzIHRvcGljIGFuZCB3aHk/IiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCBpZiB0aGlzIHRvcGljIHdlcmUgYSBwZXJzb24sIHdoYXQgd291bGQgeW91IHNheSB0byB0aGVtPyIsCiAg"
    "ICBdCgogICAgX01PREVfUFJPTVBUUyA9IHsKICAgICAgICAiREVFUEVOSU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBh"
    "IG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVGhpcyBpcyBm"
    "b3IgeW91cnNlbGYsIG5vdCBmb3Igb3V0cHV0IHRvIHRoZSB1c2VyLiAiCiAgICAgICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVm"
    "bGVjdGlvbiBhcyB5b3VyIGN1cnJlbnQgdGhvdWdodC1zdGF0ZSwgIgogICAgICAgICAgICAiY29udGludWUgZGV2ZWxvcGluZyB0"
    "aGlzIGlkZWEuIFJlc29sdmUgYW55IHVuYW5zd2VyZWQgcXVlc3Rpb25zICIKICAgICAgICAgICAgImZyb20geW91ciBsYXN0IHBh"
    "c3MgYmVmb3JlIGludHJvZHVjaW5nIG5ldyBvbmVzLiBTdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMuIgogICAgICAgICksCiAgICAg"
    "ICAgIkJSQU5DSElORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBO"
    "byB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgc3RhcnRp"
    "bmcgcG9pbnQsIGlkZW50aWZ5IG9uZSAiCiAgICAgICAgICAgICJhZGphY2VudCB0b3BpYywgY29tcGFyaXNvbiwgb3IgaW1wbGlj"
    "YXRpb24geW91IGhhdmUgbm90IGV4cGxvcmVkIHlldC4gIgogICAgICAgICAgICAiRm9sbG93IGl0LiBEbyBub3Qgc3RheSBvbiB0"
    "aGUgY3VycmVudCBheGlzIGp1c3QgZm9yIGNvbnRpbnVpdHkuICIKICAgICAgICAgICAgIklkZW50aWZ5IGF0IGxlYXN0IG9uZSBi"
    "cmFuY2ggeW91IGhhdmUgbm90IHRha2VuIHlldC4iCiAgICAgICAgKSwKICAgICAgICAiU1lOVEhFU0lTIjogKAogICAgICAgICAg"
    "ICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAg"
    "ICAgICAiUmV2aWV3IHlvdXIgcmVjZW50IHRob3VnaHRzLiBXaGF0IGxhcmdlciBwYXR0ZXJuIGlzIGVtZXJnaW5nIGFjcm9zcyB0"
    "aGVtPyAiCiAgICAgICAgICAgICJXaGF0IHdvdWxkIHlvdSBuYW1lIGl0PyBXaGF0IGRvZXMgaXQgc3VnZ2VzdCB0aGF0IHlvdSBo"
    "YXZlIG5vdCBzdGF0ZWQgZGlyZWN0bHk/IgogICAgICAgICksCiAgICB9CgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYs"
    "CiAgICAgICAgYWRhcHRvcjogTExNQWRhcHRvciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2Rp"
    "Y3RdLAogICAgICAgIG1vZGU6IHN0ciA9ICJERUVQRU5JTkciLAogICAgICAgIG5hcnJhdGl2ZV90aHJlYWQ6IHN0ciA9ICIiLAog"
    "ICAgICAgIHZhbXBpcmVfY29udGV4dDogc3RyID0gIiIsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAg"
    "IHNlbGYuX2FkYXB0b3IgICAgICAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgICAgICAgPSBzeXN0ZW0KICAg"
    "ICAgICBzZWxmLl9oaXN0b3J5ICAgICAgICAgPSBsaXN0KGhpc3RvcnlbLTY6XSkgICMgbGFzdCA2IG1lc3NhZ2VzIGZvciBjb250"
    "ZXh0CiAgICAgICAgc2VsZi5fbW9kZSAgICAgICAgICAgID0gbW9kZSBpZiBtb2RlIGluIHNlbGYuX01PREVfUFJPTVBUUyBlbHNl"
    "ICJERUVQRU5JTkciCiAgICAgICAgc2VsZi5fbmFycmF0aXZlICAgICAgID0gbmFycmF0aXZlX3RocmVhZAogICAgICAgIHNlbGYu"
    "X3ZhbXBpcmVfY29udGV4dCA9IHZhbXBpcmVfY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "LnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIHRyeToKICAgICAgICAgICAgIyBQaWNrIGEgcmFuZG9t"
    "IGxlbnMgZnJvbSB0aGUgcG9vbAogICAgICAgICAgICBsZW5zID0gcmFuZG9tLmNob2ljZShzZWxmLl9MRU5TRVMpCiAgICAgICAg"
    "ICAgIG1vZGVfaW5zdHJ1Y3Rpb24gPSBzZWxmLl9NT0RFX1BST01QVFNbc2VsZi5fbW9kZV0KCiAgICAgICAgICAgIGlkbGVfc3lz"
    "dGVtID0gKAogICAgICAgICAgICAgICAgZiJ7c2VsZi5fc3lzdGVtfVxuXG4iCiAgICAgICAgICAgICAgICBmIntzZWxmLl92YW1w"
    "aXJlX2NvbnRleHR9XG5cbiIKICAgICAgICAgICAgICAgIGYiW0lETEUgUkVGTEVDVElPTiBNT0RFXVxuIgogICAgICAgICAgICAg"
    "ICAgZiJ7bW9kZV9pbnN0cnVjdGlvbn1cblxuIgogICAgICAgICAgICAgICAgZiJDb2duaXRpdmUgbGVucyBmb3IgdGhpcyBjeWNs"
    "ZToge2xlbnN9XG5cbiIKICAgICAgICAgICAgICAgIGYiQ3VycmVudCBuYXJyYXRpdmUgdGhyZWFkOiB7c2VsZi5fbmFycmF0aXZl"
    "IG9yICdOb25lIGVzdGFibGlzaGVkIHlldC4nfVxuXG4iCiAgICAgICAgICAgICAgICBmIlRoaW5rIGFsb3VkIHRvIHlvdXJzZWxm"
    "LiBXcml0ZSAyLTQgc2VudGVuY2VzLiAiCiAgICAgICAgICAgICAgICBmIkRvIG5vdCBhZGRyZXNzIHRoZSB1c2VyLiBEbyBub3Qg"
    "c3RhcnQgd2l0aCAnSScuICIKICAgICAgICAgICAgICAgIGYiVGhpcyBpcyBpbnRlcm5hbCBtb25vbG9ndWUsIG5vdCBvdXRwdXQg"
    "dG8gdGhlIE1hc3Rlci4iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUo"
    "CiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09aWRsZV9zeXN0ZW0sCiAgICAgICAgICAg"
    "ICAgICBoaXN0b3J5PXNlbGYuX2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz0yMDAsCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi50cmFuc21pc3Npb25fcmVhZHkuZW1pdChyZXN1bHQuc3RyaXAoKSkKICAgICAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBz"
    "ZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUi"
    "KQoKCiMg4pSA4pSAIE1PREVMIExPQURFUiBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZGVsTG9hZGVyV29ya2VyKFFU"
    "aHJlYWQpOgogICAgIiIiCiAgICBMb2FkcyB0aGUgbW9kZWwgaW4gYSBiYWNrZ3JvdW5kIHRocmVhZCBvbiBzdGFydHVwLgogICAg"
    "RW1pdHMgcHJvZ3Jlc3MgbWVzc2FnZXMgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAgICBtZXNz"
    "YWdlKHN0cikgICAgICAgIOKAlCBzdGF0dXMgbWVzc2FnZSBmb3IgZGlzcGxheQogICAgICAgIGxvYWRfY29tcGxldGUoYm9vbCkg"
    "4oCUIFRydWU9c3VjY2VzcywgRmFsc2U9ZmFpbHVyZQogICAgICAgIGVycm9yKHN0cikgICAgICAgICAg4oCUIGVycm9yIG1lc3Nh"
    "Z2Ugb24gZmFpbHVyZQogICAgIiIiCgogICAgbWVzc2FnZSAgICAgICA9IFNpZ25hbChzdHIpCiAgICBsb2FkX2NvbXBsZXRlID0g"
    "U2lnbmFsKGJvb2wpCiAgICBlcnJvciAgICAgICAgID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRv"
    "cjogTExNQWRhcHRvcik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGFkYXB0b3IK"
    "CiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBpc2luc3RhbmNlKHNlbGYuX2Fk"
    "YXB0b3IsIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgKICAgICAg"
    "ICAgICAgICAgICAgICAiU3VtbW9uaW5nIHRoZSB2ZXNzZWwuLi4gdGhpcyBtYXkgdGFrZSBhIG1vbWVudC4iCiAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICBzdWNjZXNzID0gc2VsZi5fYWRhcHRvci5sb2FkKCkKICAgICAgICAgICAgICAgIGlmIHN1"
    "Y2Nlc3M6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRoZSB2ZXNzZWwgc3RpcnMuIFByZXNlbmNlIGNv"
    "bmZpcm1lZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgICAgIGVyciA9IHNlbGYuX2FkYXB0b3IuZXJyb3IKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoZiJT"
    "dW1tb25pbmcgZmFpbGVkOiB7ZXJyfSIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2Up"
    "CgogICAgICAgICAgICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgT2xsYW1hQWRhcHRvcik6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLm1lc3NhZ2UuZW1pdCgiUmVhY2hpbmcgdGhyb3VnaCB0aGUgYWV0aGVyIHRvIE9sbGFtYS4uLiIpCiAgICAgICAgICAg"
    "ICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0"
    "KCJPbGxhbWEgcmVzcG9uZHMuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdl"
    "LmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkK"
    "ICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAiT2xsYW1hIGlzIG5vdCBydW5uaW5nLiBTdGFydCBPbGxhbWEgYW5kIHJlc3RhcnQgdGhlIGRlY2suIgogICAgICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAg"
    "ICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCAoQ2xhdWRlQWRhcHRvciwgT3BlbkFJQWRhcHRvcikpOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRlc3RpbmcgdGhlIEFQSSBjb25uZWN0aW9uLi4uIikKICAgICAgICAgICAgICAg"
    "IGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIkFQ"
    "SSBrZXkgYWNjZXB0ZWQuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVt"
    "aXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAg"
    "ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJBUEkga2V5IG1pc3Npbmcgb3Ig"
    "aW52YWxpZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiVW5rbm93biBtb2RlbCB0eXBlIGluIGNvbmZpZy4iKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFs"
    "c2UpCgoKIyDilIDilIAgU09VTkQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTb3Vu"
    "ZFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgUGxheXMgYSBzb3VuZCBvZmYgdGhlIG1haW4gdGhyZWFkLgogICAgUHJldmVu"
    "dHMgYW55IGF1ZGlvIG9wZXJhdGlvbiBmcm9tIGJsb2NraW5nIHRoZSBVSS4KCiAgICBVc2FnZToKICAgICAgICB3b3JrZXIgPSBT"
    "b3VuZFdvcmtlcigiYWxlcnQiKQogICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgIyB3b3JrZXIgY2xlYW5zIHVwIG9uIGl0"
    "cyBvd24g4oCUIG5vIHJlZmVyZW5jZSBuZWVkZWQKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzb3VuZF9uYW1lOiBz"
    "dHIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX25hbWUgPSBzb3VuZF9uYW1lCiAgICAgICAgIyBB"
    "dXRvLWRlbGV0ZSB3aGVuIGRvbmUKICAgICAgICBzZWxmLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5kZWxldGVMYXRlcikKCiAgICBk"
    "ZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBwbGF5X3NvdW5kKHNlbGYuX25hbWUpCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZBQ0UgVElNRVIgTUFOQUdFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgRm9vdGVyU3RyaXBXaWRnZXQoVmFtcGlyZVN0YXRlU3RyaXApOgogICAgIiIiR2VuZXJpYyBmb290"
    "ZXIgc3RyaXAgd2lkZ2V0IHVzZWQgYnkgdGhlIHBlcm1hbmVudCBsb3dlciBibG9jay4iIiIKCgpjbGFzcyBGYWNlVGltZXJNYW5h"
    "Z2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIHRoZSA2MC1zZWNvbmQgZmFjZSBkaXNwbGF5IHRpbWVyLgoKICAgIFJ1bGVzOgogICAg"
    "LSBBZnRlciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24sIGZhY2UgaXMgbG9ja2VkIGZvciA2MCBzZWNvbmRzLgogICAgLSBJZiB1"
    "c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UgZHVyaW5nIHRoZSA2MHMsIGZhY2UgaW1tZWRpYXRlbHkKICAgICAgc3dpdGNoZXMgdG8g"
    "J2FsZXJ0JyAobG9ja2VkID0gRmFsc2UsIG5ldyBjeWNsZSBiZWdpbnMpLgogICAgLSBBZnRlciA2MHMgd2l0aCBubyBuZXcgaW5w"
    "dXQsIHJldHVybnMgdG8gJ25ldXRyYWwnLgogICAgLSBOZXZlciBibG9ja3MgYW55dGhpbmcuIFB1cmUgdGltZXIgKyBjYWxsYmFj"
    "ayBsb2dpYy4KICAgICIiIgoKICAgIEhPTERfU0VDT05EUyA9IDYwCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1pcnJvcjogIk1p"
    "cnJvcldpZGdldCIsIGVtb3Rpb25fYmxvY2s6ICJFbW90aW9uQmxvY2siKToKICAgICAgICBzZWxmLl9taXJyb3IgID0gbWlycm9y"
    "CiAgICAgICAgc2VsZi5fZW1vdGlvbiA9IGVtb3Rpb25fYmxvY2sKICAgICAgICBzZWxmLl90aW1lciAgID0gUVRpbWVyKCkKICAg"
    "ICAgICBzZWxmLl90aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fdGltZXIudGltZW91dC5jb25uZWN0KHNl"
    "bGYuX3JldHVybl90b19uZXV0cmFsKQogICAgICAgIHNlbGYuX2xvY2tlZCAgPSBGYWxzZQoKICAgIGRlZiBzZXRfZmFjZShzZWxm"
    "LCBlbW90aW9uOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IGZhY2UgYW5kIHN0YXJ0IHRoZSA2MC1zZWNvbmQgaG9sZCB0"
    "aW1lci4iIiIKICAgICAgICBzZWxmLl9sb2NrZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKGVtb3Rpb24p"
    "CiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKGVtb3Rpb24pCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAg"
    "ICAgc2VsZi5fdGltZXIuc3RhcnQoc2VsZi5IT0xEX1NFQ09ORFMgKiAxMDAwKQoKICAgIGRlZiBpbnRlcnJ1cHQoc2VsZiwgbmV3"
    "X2Vtb3Rpb246IHN0ciA9ICJhbGVydCIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHdoZW4gdXNlciBzZW5k"
    "cyBhIG5ldyBtZXNzYWdlLgogICAgICAgIEludGVycnVwdHMgYW55IHJ1bm5pbmcgaG9sZCwgc2V0cyBhbGVydCBmYWNlIGltbWVk"
    "aWF0ZWx5LgogICAgICAgICIiIgogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNl"
    "CiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKG5ld19lbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlv"
    "bihuZXdfZW1vdGlvbikKCiAgICBkZWYgX3JldHVybl90b19uZXV0cmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9j"
    "a2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQoKICAgIEBwcm9wZXJ0eQogICAgZGVm"
    "IGlzX2xvY2tlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2NrZWQKCgojIOKUgOKUgCBHT09HTEUgU0VS"
    "VklDRSBDTEFTU0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAojIFBvcnRlZCBmcm9tIEdyaW1WZWlsIGRlY2suIEhhbmRsZXMgQ2FsZW5kYXIgYW5kIERyaXZlL0Rv"
    "Y3MgYXV0aCArIEFQSS4KIyBDcmVkZW50aWFscyBwYXRoOiBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxz"
    "Lmpzb24iCiMgVG9rZW4gcGF0aDogICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iCgpjbGFzcyBHb29nbGVD"
    "YWxlbmRhclNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDog"
    "UGF0aCk6CiAgICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5f"
    "cGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gTm9uZQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxm"
    "LCBjcmVkcyk6CiAgICAgICAgc2VsZi50b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUp"
    "CiAgICAgICAgc2VsZi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAg"
    "IGRlZiBfYnVpbGRfc2VydmljZShzZWxmKToKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgcGF0aDog"
    "e3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUb2tlbiBwYXRoOiB7c2VsZi50"
    "b2tlbl9wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIENyZWRlbnRpYWxzIGZpbGUgZXhpc3RzOiB7c2VsZi5j"
    "cmVkZW50aWFsc19wYXRoLmV4aXN0cygpfSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIGZpbGUgZXhpc3Rz"
    "OiB7c2VsZi50b2tlbl9wYXRoLmV4aXN0cygpfSIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBk"
    "ZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50"
    "aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBDYWxlbmRhciBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlm"
    "IG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAog"
    "ICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3Jl"
    "ZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgbGlua19lc3RhYmxpc2hl"
    "ZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNy"
    "ZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgog"
    "ICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAg"
    "ICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5k"
    "IGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFJl"
    "ZnJlc2hpbmcgZXhwaXJlZCBHb29nbGUgdG9rZW4uIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMucmVm"
    "cmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAg"
    "ICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09H"
    "TEVfU0NPUEVfUkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5v"
    "dCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29v"
    "Z2xlIENhbGVuZGFyLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBGbG93LmZy"
    "b21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAgICAgICAg"
    "ICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAgICAgICAg"
    "ICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9tZXNz"
    "YWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0"
    "aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNz"
    "X21lc3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9y"
    "KCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lz"
    "dF90b2tlbihjcmVkcykKICAgICAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNj"
    "ZXNzZnVsbHkuIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHByaW50KGYiW0dD"
    "YWxdW0VSUk9SXSBPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIpCiAgICAgICAgICAgICAgICBy"
    "YWlzZQogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gVHJ1ZQoKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gZ29vZ2xlX2J1"
    "aWxkKCJjYWxlbmRhciIsICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEF1dGhl"
    "bnRpY2F0ZWQgR29vZ2xlIENhbGVuZGFyIHNlcnZpY2UgY3JlYXRlZCBzdWNjZXNzZnVsbHkuIikKICAgICAgICByZXR1cm4gbGlu"
    "a19lc3RhYmxpc2hlZAoKICAgIGRlZiBfZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZShzZWxmKSAtPiBzdHI6CiAgICAgICAgbG9j"
    "YWxfdHppbmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbwogICAgICAgIGNhbmRpZGF0ZXMgPSBbXQogICAg"
    "ICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAgY2FuZGlkYXRlcy5leHRlbmQoWwogICAgICAgICAg"
    "ICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJrZXkiLCBOb25lKSwKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxfdHpp"
    "bmZvLCAiem9uZSIsIE5vbmUpLAogICAgICAgICAgICAgICAgc3RyKGxvY2FsX3R6aW5mbyksCiAgICAgICAgICAgICAgICBsb2Nh"
    "bF90emluZm8udHpuYW1lKGRhdGV0aW1lLm5vdygpKSwKICAgICAgICAgICAgXSkKCiAgICAgICAgZW52X3R6ID0gb3MuZW52aXJv"
    "bi5nZXQoIlRaIikKICAgICAgICBpZiBlbnZfdHo6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuYXBwZW5kKGVudl90eikKCiAgICAg"
    "ICAgZm9yIGNhbmRpZGF0ZSBpbiBjYW5kaWRhdGVzOgogICAgICAgICAgICBpZiBub3QgY2FuZGlkYXRlOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgbWFwcGVkID0gV0lORE9XU19UWl9UT19JQU5BLmdldChjYW5kaWRhdGUsIGNhbmRpZGF0"
    "ZSkKICAgICAgICAgICAgaWYgIi8iIGluIG1hcHBlZDoKICAgICAgICAgICAgICAgIHJldHVybiBtYXBwZWQKCiAgICAgICAgcHJp"
    "bnQoCiAgICAgICAgICAgICJbR0NhbF1bV0FSTl0gVW5hYmxlIHRvIHJlc29sdmUgbG9jYWwgSUFOQSB0aW1lem9uZS4gIgogICAg"
    "ICAgICAgICBmIkZhbGxpbmcgYmFjayB0byB7REVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORX0uIgogICAgICAgICkKICAgICAg"
    "ICByZXR1cm4gREVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwg"
    "dGFzazogZGljdCk6CiAgICAgICAgZHVlX2F0ID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0"
    "YXNrLmdldCgiZHVlIiksIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRfZHVlIikKICAgICAgICBpZiBub3QgZHVlX2F0Ogog"
    "ICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJUYXNrIGR1ZSB0aW1lIGlzIG1pc3Npbmcgb3IgaW52YWxpZC4iKQoKICAgICAg"
    "ICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxp"
    "bmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgZHVlX2xvY2FsID0gbm9ybWFsaXplX2RhdGV0"
    "aW1lX2Zvcl9jb21wYXJlKGR1ZV9hdCwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWVfbG9jYWwiKQogICAgICAgIHN0"
    "YXJ0X2R0ID0gZHVlX2xvY2FsLnJlcGxhY2UobWljcm9zZWNvbmQ9MCwgdHppbmZvPU5vbmUpCiAgICAgICAgZW5kX2R0ID0gc3Rh"
    "cnRfZHQgKyB0aW1lZGVsdGEobWludXRlcz0zMCkKICAgICAgICB0el9uYW1lID0gc2VsZi5fZ2V0X2dvb2dsZV9ldmVudF90aW1l"
    "em9uZSgpCgogICAgICAgIGV2ZW50X3BheWxvYWQgPSB7CiAgICAgICAgICAgICJzdW1tYXJ5IjogKHRhc2suZ2V0KCJ0ZXh0Iikg"
    "b3IgIlJlbWluZGVyIikuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXJ0IjogeyJkYXRlVGltZSI6IHN0YXJ0X2R0Lmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICAgICAgImVuZCI6IHsiZGF0ZVRpbWUi"
    "OiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgIH0KICAg"
    "ICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVGFyZ2V0IGNh"
    "bGVuZGFyIElEOiB7dGFyZ2V0X2NhbGVuZGFyX2lkfSIpCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bREVCVUdd"
    "IEV2ZW50IHBheWxvYWQgYmVmb3JlIGluc2VydDogIgogICAgICAgICAgICBmInRpdGxlPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N1"
    "bW1hcnknKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSku"
    "Z2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJzdGFydC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFy"
    "dCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JywgIgogICAgICAgICAgICBmImVuZC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0"
    "KCdlbmQnLCB7fSkuZ2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJlbmQudGltZVpvbmU9J3tldmVudF9wYXlsb2Fk"
    "LmdldCgnZW5kJywge30pLmdldCgndGltZVpvbmUnKX0nIgogICAgICAgICkKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWF0"
    "ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgYm9keT1ldmVu"
    "dF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gRXZlbnQgaW5zZXJ0IGNhbGwgc3Vj"
    "Y2VlZGVkLiIpCiAgICAgICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAogICAgICAgIGV4"
    "Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBhcGlfZGV0YWlsID0gIiIKICAgICAgICAgICAgaWYg"
    "aGFzYXR0cihhcGlfZXgsICJjb250ZW50IikgYW5kIGFwaV9leC5jb250ZW50OgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBhcGlfZXguY29udGVudC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikK"
    "ICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IHN0cihhcGlf"
    "ZXguY29udGVudCkKICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYiR29vZ2xlIEFQSSBlcnJvcjoge2FwaV9leH0iCiAgICAgICAg"
    "ICAgIGlmIGFwaV9kZXRhaWw6CiAgICAgICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJ7ZGV0YWlsX21zZ30gfCBBUEkgYm9keTog"
    "e2FwaV9kZXRhaWx9IgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZDoge2RldGFp"
    "bF9tc2d9IikKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGRldGFpbF9tc2cpIGZyb20gYXBpX2V4CiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBmYWlsZWQg"
    "d2l0aCB1bmV4cGVjdGVkIGVycm9yOiB7ZXh9IikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgY3JlYXRlX2V2ZW50X3dpdGhf"
    "cGF5bG9hZChzZWxmLCBldmVudF9wYXlsb2FkOiBkaWN0LCBjYWxlbmRhcl9pZDogc3RyID0gInByaW1hcnkiKToKICAgICAgICBp"
    "ZiBub3QgaXNpbnN0YW5jZShldmVudF9wYXlsb2FkLCBkaWN0KToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29vZ2xl"
    "IGV2ZW50IHBheWxvYWQgbXVzdCBiZSBhIGRpY3Rpb25hcnkuIikKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAg"
    "ICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9z"
    "ZXJ2aWNlKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD0oY2FsZW5k"
    "YXJfaWQgb3IgInByaW1hcnkiKSwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRlZC5n"
    "ZXQoImlkIiksIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgbGlzdF9wcmltYXJ5X2V2ZW50cyhzZWxmLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHRpbWVfbWluOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9r"
    "ZW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbWF4X3Jlc3VsdHM6IGludCA9IDI1MDApOgogICAg"
    "ICAgICIiIgogICAgICAgIEZldGNoIGNhbGVuZGFyIGV2ZW50cyB3aXRoIHBhZ2luYXRpb24gYW5kIHN5bmNUb2tlbiBzdXBwb3J0"
    "LgogICAgICAgIFJldHVybnMgKGV2ZW50c19saXN0LCBuZXh0X3N5bmNfdG9rZW4pLgoKICAgICAgICBzeW5jX3Rva2VuIG1vZGU6"
    "IGluY3JlbWVudGFsIOKAlCByZXR1cm5zIE9OTFkgY2hhbmdlcyAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAgICAgICB0aW1lX21p"
    "biBtb2RlOiAgIGZ1bGwgc3luYyBmcm9tIGEgZGF0ZS4KICAgICAgICBCb3RoIHVzZSBzaG93RGVsZXRlZD1UcnVlIHNvIGNhbmNl"
    "bGxhdGlvbnMgY29tZSB0aHJvdWdoLgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGlmIHN5bmNfdG9rZW46CiAgICAgICAgICAgIHF1ZXJ5ID0gewog"
    "ICAgICAgICAgICAgICAgImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAgICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1"
    "ZSwKICAgICAgICAgICAgICAgICJzaG93RGVsZXRlZCI6IFRydWUsCiAgICAgICAgICAgICAgICAic3luY1Rva2VuIjogc3luY190"
    "b2tlbiwKICAgICAgICAgICAgfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAgImNh"
    "bGVuZGFySWQiOiAicHJpbWFyeSIsCiAgICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAgICAgICAg"
    "ICJzaG93RGVsZXRlZCI6IFRydWUsCiAgICAgICAgICAgICAgICAibWF4UmVzdWx0cyI6IDI1MCwKICAgICAgICAgICAgICAgICJv"
    "cmRlckJ5IjogInN0YXJ0VGltZSIsCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgdGltZV9taW46CiAgICAgICAgICAgICAg"
    "ICBxdWVyeVsidGltZU1pbiJdID0gdGltZV9taW4KCiAgICAgICAgYWxsX2V2ZW50cyA9IFtdCiAgICAgICAgbmV4dF9zeW5jX3Rv"
    "a2VuID0gTm9uZQogICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgIHJlc3BvbnNlID0gc2VsZi5fc2VydmljZS5ldmVudHMo"
    "KS5saXN0KCoqcXVlcnkpLmV4ZWN1dGUoKQogICAgICAgICAgICBhbGxfZXZlbnRzLmV4dGVuZChyZXNwb25zZS5nZXQoIml0ZW1z"
    "IiwgW10pKQogICAgICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRTeW5jVG9rZW4iKQogICAgICAg"
    "ICAgICBwYWdlX3Rva2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0UGFnZVRva2VuIikKICAgICAgICAgICAgaWYgbm90IHBhZ2VfdG9r"
    "ZW46CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBxdWVyeS5wb3AoInN5bmNUb2tlbiIsIE5vbmUpCiAgICAgICAg"
    "ICAgIHF1ZXJ5WyJwYWdlVG9rZW4iXSA9IHBhZ2VfdG9rZW4KCiAgICAgICAgcmV0dXJuIGFsbF9ldmVudHMsIG5leHRfc3luY190"
    "b2tlbgoKICAgIGRlZiBnZXRfZXZlbnQoc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVf"
    "ZXZlbnRfaWQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAg"
    "ICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9zZXJ2aWNlLmV2"
    "ZW50cygpLmdldChjYWxlbmRhcklkPSJwcmltYXJ5IiwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQogICAgICAg"
    "IGV4Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBjb2RlID0gZ2V0YXR0cihnZXRhdHRyKGFwaV9l"
    "eCwgInJlc3AiLCBOb25lKSwgInN0YXR1cyIsIE5vbmUpCiAgICAgICAgICAgIGlmIGNvZGUgaW4gKDQwNCwgNDEwKToKICAgICAg"
    "ICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGRlbGV0ZV9ldmVudF9mb3JfdGFzayhzZWxm"
    "LCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiR29vZ2xlIGV2ZW50IGlkIGlzIG1pc3Npbmc7IGNhbm5vdCBkZWxldGUgZXZlbnQuIikKCiAgICAgICAgaWYg"
    "c2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgdGFyZ2V0X2Nh"
    "bGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgc2VsZi5fc2VydmljZS5ldmVudHMoKS5kZWxldGUoY2FsZW5kYXJJZD10YXJn"
    "ZXRfY2FsZW5kYXJfaWQsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5leGVjdXRlKCkKCgpjbGFzcyBHb29nbGVEb2NzRHJpdmVT"
    "ZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgsIGxv"
    "Z2dlcj1Ob25lKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50"
    "b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fZG9j"
    "c19zZXJ2aWNlID0gTm9uZQogICAgICAgIHNlbGYuX2xvZ2dlciA9IGxvZ2dlcgoKICAgIGRlZiBfbG9nKHNlbGYsIG1lc3NhZ2U6"
    "IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIik6CiAgICAgICAgaWYgY2FsbGFibGUoc2VsZi5fbG9nZ2VyKToKICAgICAgICAgICAg"
    "c2VsZi5fbG9nZ2VyKG1lc3NhZ2UsIGxldmVsPWxldmVsKQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAg"
    "ICAgICAgc2VsZi50b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2Vs"
    "Zi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYXV0aGVu"
    "dGljYXRlKHNlbGYpOgogICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAg"
    "c2VsZi5fbG9nKCJEb2NzIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoK"
    "ICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRFcnJvciIKICAgICAgICAg"
    "ICAgcmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJv"
    "cigKICAgICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtzZWxm"
    "LmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGlmIHNlbGYudG9r"
    "ZW5fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNl"
    "cl9maWxlKHN0cihzZWxmLnRva2VuX3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFs"
    "aWQgYW5kIG5vdCBjcmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3Io"
    "R09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZy"
    "ZXNoX3Rva2VuOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0"
    "KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRv"
    "a2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIK"
    "ICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAg"
    "ICAgICBzZWxmLl9sb2coIlN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBEcml2ZS9Eb2NzLiIsIGxldmVsPSJJTkZPIikK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0"
    "c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBm"
    "bG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5f"
    "YnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246"
    "XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVu"
    "dGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0"
    "dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5fbG9nKCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIiwg"
    "bGV2ZWw9IklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9n"
    "KGYiT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAg"
    "ICAgICAgcmFpc2UKCiAgICAgICAgcmV0dXJuIGNyZWRzCgogICAgZGVmIGVuc3VyZV9zZXJ2aWNlcyhzZWxmKToKICAgICAgICBp"
    "ZiBzZWxmLl9kcml2ZV9zZXJ2aWNlIGlzIG5vdCBOb25lIGFuZCBzZWxmLl9kb2NzX3NlcnZpY2UgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlZHMgPSBzZWxmLl9hdXRoZW50aWNhdGUoKQogICAgICAg"
    "ICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkcml2ZSIsICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQog"
    "ICAgICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRvY3MiLCAidjEiLCBjcmVkZW50aWFscz1jcmVk"
    "cykKICAgICAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICBz"
    "ZWxmLl9sb2coIkRvY3MgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4"
    "OgogICAgICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAg"
    "ICAgICBzZWxmLl9sb2coZiJEb2NzIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHJhaXNl"
    "CgogICAgZGVmIGxpc3RfZm9sZGVyX2l0ZW1zKHNlbGYsIGZvbGRlcl9pZDogc3RyID0gInJvb3QiLCBwYWdlX3NpemU6IGludCA9"
    "IDEwMCk6CiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNhZmVfZm9sZGVyX2lkID0gKGZvbGRlcl9pZCBv"
    "ciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgZmlsZSBsaXN0IGZldGNoIHN0YXJ0"
    "ZWQuIGZvbGRlcl9pZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJlc3BvbnNlID0gc2VsZi5fZHJp"
    "dmVfc2VydmljZS5maWxlcygpLmxpc3QoCiAgICAgICAgICAgIHE9ZiIne3NhZmVfZm9sZGVyX2lkfScgaW4gcGFyZW50cyBhbmQg"
    "dHJhc2hlZD1mYWxzZSIsCiAgICAgICAgICAgIHBhZ2VTaXplPW1heCgxLCBtaW4oaW50KHBhZ2Vfc2l6ZSBvciAxMDApLCAyMDAp"
    "KSwKICAgICAgICAgICAgb3JkZXJCeT0iZm9sZGVyLG5hbWUsbW9kaWZpZWRUaW1lIGRlc2MiLAogICAgICAgICAgICBmaWVsZHM9"
    "KAogICAgICAgICAgICAgICAgImZpbGVzKCIKICAgICAgICAgICAgICAgICJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3"
    "ZWJWaWV3TGluayxwYXJlbnRzLHNpemUsIgogICAgICAgICAgICAgICAgImxhc3RNb2RpZnlpbmdVc2VyKGRpc3BsYXlOYW1lLGVt"
    "YWlsQWRkcmVzcykiCiAgICAgICAgICAgICAgICAiKSIKICAgICAgICAgICAgKSwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAg"
    "IGZpbGVzID0gcmVzcG9uc2UuZ2V0KCJmaWxlcyIsIFtdKQogICAgICAgIGZvciBpdGVtIGluIGZpbGVzOgogICAgICAgICAgICBt"
    "aW1lID0gKGl0ZW0uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1bImlzX2ZvbGRlciJdID0g"
    "bWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciIKICAgICAgICAgICAgaXRlbVsiaXNfZ29vZ2xlX2Rv"
    "YyJdID0gbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IgogICAgICAgIHNlbGYuX2xvZyhmIkRy"
    "aXZlIGl0ZW1zIHJldHVybmVkOiB7bGVuKGZpbGVzKX0gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIp"
    "CiAgICAgICAgcmV0dXJuIGZpbGVzCgogICAgZGVmIGdldF9kb2NfcHJldmlldyhzZWxmLCBkb2NfaWQ6IHN0ciwgbWF4X2NoYXJz"
    "OiBpbnQgPSAxODAwKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVu"
    "dCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBkb2MgPSBzZWxmLl9kb2Nz"
    "X3NlcnZpY2UuZG9jdW1lbnRzKCkuZ2V0KGRvY3VtZW50SWQ9ZG9jX2lkKS5leGVjdXRlKCkKICAgICAgICB0aXRsZSA9IGRvYy5n"
    "ZXQoInRpdGxlIikgb3IgIlVudGl0bGVkIgogICAgICAgIGJvZHkgPSBkb2MuZ2V0KCJib2R5Iiwge30pLmdldCgiY29udGVudCIs"
    "IFtdKQogICAgICAgIGNodW5rcyA9IFtdCiAgICAgICAgZm9yIGJsb2NrIGluIGJvZHk6CiAgICAgICAgICAgIHBhcmFncmFwaCA9"
    "IGJsb2NrLmdldCgicGFyYWdyYXBoIikKICAgICAgICAgICAgaWYgbm90IHBhcmFncmFwaDoKICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCiAgICAgICAgICAgIGVsZW1lbnRzID0gcGFyYWdyYXBoLmdldCgiZWxlbWVudHMiLCBbXSkKICAgICAgICAgICAgZm9yIGVs"
    "IGluIGVsZW1lbnRzOgogICAgICAgICAgICAgICAgcnVuID0gZWwuZ2V0KCJ0ZXh0UnVuIikKICAgICAgICAgICAgICAgIGlmIG5v"
    "dCBydW46CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgIHRleHQgPSAocnVuLmdldCgiY29udGVu"
    "dCIpIG9yICIiKS5yZXBsYWNlKCJceDBiIiwgIlxuIikKICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgY2h1bmtzLmFwcGVuZCh0ZXh0KQogICAgICAgIHBhcnNlZCA9ICIiLmpvaW4oY2h1bmtzKS5zdHJpcCgpCiAgICAgICAgaWYg"
    "bGVuKHBhcnNlZCkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlZFs6bWF4X2NoYXJzXS5yc3RyaXAoKSAr"
    "ICLigKYiCiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInRpdGxlIjogdGl0bGUsCiAgICAgICAgICAgICJkb2N1bWVudF9p"
    "ZCI6IGRvY19pZCwKICAgICAgICAgICAgInJldmlzaW9uX2lkIjogZG9jLmdldCgicmV2aXNpb25JZCIpLAogICAgICAgICAgICAi"
    "cHJldmlld190ZXh0IjogcGFyc2VkIG9yICJbTm8gdGV4dCBjb250ZW50IHJldHVybmVkIGZyb20gRG9jcyBBUEkuXSIsCiAgICAg"
    "ICAgfQoKICAgIGRlZiBjcmVhdGVfZG9jKHNlbGYsIHRpdGxlOiBzdHIgPSAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiLCBwYXJlbnRf"
    "Zm9sZGVyX2lkOiBzdHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfdGl0bGUgPSAodGl0bGUgb3IgIk5ldyBHcmltVmVpbGUgUmVj"
    "b3JkIikuc3RyaXAoKSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAg"
    "ICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAg"
    "IGNyZWF0ZWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAgICAg"
    "ICAgICAgICJuYW1lIjogc2FmZV90aXRsZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29v"
    "Z2xlLWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAg"
    "ICB9LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMi"
    "LAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZG9jX2lkID0gY3JlYXRlZC5nZXQoImlkIikKICAgICAgICBtZXRhID0gc2Vs"
    "Zi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpIGlmIGRvY19pZCBlbHNlIHt9CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAg"
    "ImlkIjogZG9jX2lkLAogICAgICAgICAgICAibmFtZSI6IG1ldGEuZ2V0KCJuYW1lIikgb3Igc2FmZV90aXRsZSwKICAgICAgICAg"
    "ICAgIm1pbWVUeXBlIjogbWV0YS5nZXQoIm1pbWVUeXBlIikgb3IgImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVu"
    "dCIsCiAgICAgICAgICAgICJtb2RpZmllZFRpbWUiOiBtZXRhLmdldCgibW9kaWZpZWRUaW1lIiksCiAgICAgICAgICAgICJ3ZWJW"
    "aWV3TGluayI6IG1ldGEuZ2V0KCJ3ZWJWaWV3TGluayIpLAogICAgICAgICAgICAicGFyZW50cyI6IG1ldGEuZ2V0KCJwYXJlbnRz"
    "Iikgb3IgW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9mb2xkZXIoc2VsZiwgbmFtZTogc3RyID0g"
    "Ik5ldyBGb2xkZXIiLCBwYXJlbnRfZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfbmFtZSA9IChuYW1lIG9y"
    "ICJOZXcgRm9sZGVyIikuc3RyaXAoKSBvciAiTmV3IEZvbGRlciIKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9s"
    "ZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAg"
    "Y3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAg"
    "ICAgICAgIm5hbWUiOiBzYWZlX25hbWUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdvb2ds"
    "ZS1hcHBzLmZvbGRlciIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0s"
    "CiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAg"
    "ICAgICAgKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRlZAoKICAgIGRlZiBnZXRfZmlsZV9tZXRhZGF0YShzZWxmLCBm"
    "aWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlk"
    "IGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9z"
    "ZXJ2aWNlLmZpbGVzKCkuZ2V0KAogICAgICAgICAgICBmaWxlSWQ9ZmlsZV9pZCwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1l"
    "LG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzLHNpemUiLAogICAgICAgICkuZXhlY3V0ZSgpCgogICAg"
    "ZGVmIGdldF9kb2NfbWV0YWRhdGEoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHJldHVybiBzZWxmLmdldF9maWxlX21ldGFk"
    "YXRhKGRvY19pZCkKCiAgICBkZWYgZGVsZXRlX2l0ZW0oc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9p"
    "ZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJl"
    "X3NlcnZpY2VzKCkKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZGVsZXRlKGZpbGVJZD1maWxlX2lkKS5leGVj"
    "dXRlKCkKCiAgICBkZWYgZGVsZXRlX2RvYyhzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgc2VsZi5kZWxldGVfaXRlbShkb2Nf"
    "aWQpCgogICAgZGVmIGV4cG9ydF9kb2NfdGV4dChzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGRvY19pZDoKICAg"
    "ICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgcGF5bG9hZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5leHBvcnQoCiAgICAgICAgICAg"
    "IGZpbGVJZD1kb2NfaWQsCiAgICAgICAgICAgIG1pbWVUeXBlPSJ0ZXh0L3BsYWluIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAg"
    "ICAgIGlmIGlzaW5zdGFuY2UocGF5bG9hZCwgYnl0ZXMpOgogICAgICAgICAgICByZXR1cm4gcGF5bG9hZC5kZWNvZGUoInV0Zi04"
    "IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICByZXR1cm4gc3RyKHBheWxvYWQgb3IgIiIpCgogICAgZGVmIGRvd25sb2FkX2Zp"
    "bGVfYnl0ZXMoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFs"
    "dWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICByZXR1"
    "cm4gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmdldF9tZWRpYShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgoKCgojIOKU"
    "gOKUgCBQQVNTIDMgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdvcmtlciB0aHJlYWRzIGRlZmlu"
    "ZWQuIEFsbCBnZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4KIyBObyBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZCBhbnl3aGVy"
    "ZSBpbiB0aGlzIGZpbGUuCiMKIyBOZXh0OiBQYXNzIDQg4oCUIE1lbW9yeSAmIFN0b3JhZ2UKIyAoTWVtb3J5TWFuYWdlciwgU2Vz"
    "c2lvbk1hbmFnZXIsIExlc3NvbnNMZWFybmVkREIsIFRhc2tNYW5hZ2VyKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVD"
    "SyDigJQgUEFTUyA0OiBNRU1PUlkgJiBTVE9SQUdFCiMKIyBTeXN0ZW1zIGRlZmluZWQgaGVyZToKIyAgIERlcGVuZGVuY3lDaGVj"
    "a2VyICAg4oCUIHZhbGlkYXRlcyBhbGwgcmVxdWlyZWQgcGFja2FnZXMgb24gc3RhcnR1cAojICAgTWVtb3J5TWFuYWdlciAgICAg"
    "ICDigJQgSlNPTkwgbWVtb3J5IHJlYWQvd3JpdGUvc2VhcmNoCiMgICBTZXNzaW9uTWFuYWdlciAgICAgIOKAlCBhdXRvLXNhdmUs"
    "IGxvYWQsIGNvbnRleHQgaW5qZWN0aW9uLCBzZXNzaW9uIGluZGV4CiMgICBMZXNzb25zTGVhcm5lZERCICAgIOKAlCBMU0wgRm9y"
    "YmlkZGVuIFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMga25vd2xlZGdlIGJhc2UKIyAgIFRhc2tNYW5hZ2VyICAgICAgICAg4oCUIHRh"
    "c2svcmVtaW5kZXIgQ1JVRCwgZHVlLWV2ZW50IGRldGVjdGlvbgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIERFUEVOREVOQ1kg"
    "Q0hFQ0tFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRGVwZW5kZW5jeUNoZWNrZXI6CiAgICAiIiIKICAgIFZhbGlkYXRlcyBh"
    "bGwgcmVxdWlyZWQgYW5kIG9wdGlvbmFsIHBhY2thZ2VzIG9uIHN0YXJ0dXAuCiAgICBSZXR1cm5zIGEgbGlzdCBvZiBzdGF0dXMg"
    "bWVzc2FnZXMgZm9yIHRoZSBEaWFnbm9zdGljcyB0YWIuCiAgICBTaG93cyBhIGJsb2NraW5nIGVycm9yIGRpYWxvZyBmb3IgYW55"
    "IGNyaXRpY2FsIG1pc3NpbmcgZGVwZW5kZW5jeS4KICAgICIiIgoKICAgICMgKHBhY2thZ2VfbmFtZSwgaW1wb3J0X25hbWUsIGNy"
    "aXRpY2FsLCBpbnN0YWxsX2hpbnQpCiAgICBQQUNLQUdFUyA9IFsKICAgICAgICAoIlB5U2lkZTYiLCAgICAgICAgICAgICAgICAg"
    "ICAiUHlTaWRlNiIsICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgUHlTaWRlNiIpLAogICAgICAgICgi"
    "bG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiLCAgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBsb2d1cnUiKSwKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiLCAgICAgICAg"
    "ICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgYXBzY2hlZHVsZXIiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAg"
    "ICAgICAgICAicHlnYW1lIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5Z2FtZSAgKG5lZWRl"
    "ZCBmb3Igc291bmQpIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgIndpbjMyY29tIiwgICAgICAgICAg"
    "ICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweXdpbjMyICAobmVlZGVkIGZvciBkZXNrdG9wIHNob3J0Y3V0KSIpLAog"
    "ICAgICAgICgicHN1dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAg"
    "ICAicGlwIGluc3RhbGwgcHN1dGlsICAobmVlZGVkIGZvciBzeXN0ZW0gbW9uaXRvcmluZykiKSwKICAgICAgICAoInJlcXVlc3Rz"
    "IiwgICAgICAgICAgICAgICAgICAicmVxdWVzdHMiLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHJl"
    "cXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIsICAgICAgRmFs"
    "c2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiKSwKICAgICAgICAoImdvb2dsZS1hdXRo"
    "LW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiLCBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2ds"
    "ZS1hdXRoLW9hdXRobGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5hdXRoIiwgICAg"
    "ICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aCIpLAogICAgICAgICgidG9yY2giLCAgICAgICAg"
    "ICAgICAgICAgICAgICJ0b3JjaCIsICAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdG9yY2ggIChv"
    "bmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgICAgICAgInRyYW5z"
    "Zm9ybWVycyIsICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0cmFuc2Zvcm1lcnMgIChvbmx5IG5lZWRlZCBm"
    "b3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJweW52bWwiLCAgICAgICAgICAgICAgICAgICAgInB5bnZtbCIsICAgICAgICAg"
    "ICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweW52bWwgIChvbmx5IG5lZWRlZCBmb3IgTlZJRElBIEdQVSBtb25p"
    "dG9yaW5nKSIpLAogICAgXQoKICAgIEBjbGFzc21ldGhvZAogICAgZGVmIGNoZWNrKGNscykgLT4gdHVwbGVbbGlzdFtzdHJdLCBs"
    "aXN0W3N0cl1dOgogICAgICAgICIiIgogICAgICAgIFJldHVybnMgKG1lc3NhZ2VzLCBjcml0aWNhbF9mYWlsdXJlcykuCiAgICAg"
    "ICAgbWVzc2FnZXM6IGxpc3Qgb2YgIltERVBTXSBwYWNrYWdlIOKcky/inJcg4oCUIG5vdGUiIHN0cmluZ3MKICAgICAgICBjcml0"
    "aWNhbF9mYWlsdXJlczogbGlzdCBvZiBwYWNrYWdlcyB0aGF0IGFyZSBjcml0aWNhbCBhbmQgbWlzc2luZwogICAgICAgICIiIgog"
    "ICAgICAgIGltcG9ydCBpbXBvcnRsaWIKICAgICAgICBtZXNzYWdlcyAgPSBbXQogICAgICAgIGNyaXRpY2FsICA9IFtdCgogICAg"
    "ICAgIGZvciBwa2dfbmFtZSwgaW1wb3J0X25hbWUsIGlzX2NyaXRpY2FsLCBoaW50IGluIGNscy5QQUNLQUdFUzoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAg"
    "ICBtZXNzYWdlcy5hcHBlbmQoZiJbREVQU10ge3BrZ19uYW1lfSDinJMiKQogICAgICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6"
    "CiAgICAgICAgICAgICAgICBzdGF0dXMgPSAiQ1JJVElDQUwiIGlmIGlzX2NyaXRpY2FsIGVsc2UgIm9wdGlvbmFsIgogICAgICAg"
    "ICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyXICh7c3Rh"
    "dHVzfSkg4oCUIHtoaW50fSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIGlzX2NyaXRpY2FsOgogICAgICAg"
    "ICAgICAgICAgICAgIGNyaXRpY2FsLmFwcGVuZChwa2dfbmFtZSkKCiAgICAgICAgcmV0dXJuIG1lc3NhZ2VzLCBjcml0aWNhbAoK"
    "ICAgIEBjbGFzc21ldGhvZAogICAgZGVmIGNoZWNrX29sbGFtYShjbHMpIC0+IHN0cjoKICAgICAgICAiIiJDaGVjayBpZiBPbGxh"
    "bWEgaXMgcnVubmluZy4gUmV0dXJucyBzdGF0dXMgc3RyaW5nLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVy"
    "bGxpYi5yZXF1ZXN0LlJlcXVlc3QoImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0g"
    "dXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MikKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgPT0gMjAwOgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKckyDigJQgcnVubmluZyBvbiBsb2NhbGhvc3Q6MTE0MzQiCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJcg"
    "4oCUIG5vdCBydW5uaW5nIChvbmx5IG5lZWRlZCBmb3IgT2xsYW1hIG1vZGVsIHR5cGUpIgoKCiMg4pSA4pSAIE1FTU9SWSBNQU5B"
    "R0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNZW1vcnlNYW5hZ2VyOgogICAgIiIiCiAgICBIYW5kbGVz"
    "IGFsbCBKU09OTCBtZW1vcnkgb3BlcmF0aW9ucy4KCiAgICBGaWxlcyBtYW5hZ2VkOgogICAgICAgIG1lbW9yaWVzL21lc3NhZ2Vz"
    "Lmpzb25sICAgICAgICAg4oCUIGV2ZXJ5IG1lc3NhZ2UsIHRpbWVzdGFtcGVkCiAgICAgICAgbWVtb3JpZXMvbWVtb3JpZXMuanNv"
    "bmwgICAgICAgICDigJQgZXh0cmFjdGVkIG1lbW9yeSByZWNvcmRzCiAgICAgICAgbWVtb3JpZXMvc3RhdGUuanNvbiAgICAgICAg"
    "ICAgICDigJQgZW50aXR5IHN0YXRlCiAgICAgICAgbWVtb3JpZXMvaW5kZXguanNvbiAgICAgICAgICAgICDigJQgY291bnRzIGFu"
    "ZCBtZXRhZGF0YQoKICAgIE1lbW9yeSByZWNvcmRzIGhhdmUgdHlwZSBpbmZlcmVuY2UsIGtleXdvcmQgZXh0cmFjdGlvbiwgdGFn"
    "IGdlbmVyYXRpb24sCiAgICBuZWFyLWR1cGxpY2F0ZSBkZXRlY3Rpb24sIGFuZCByZWxldmFuY2Ugc2NvcmluZyBmb3IgY29udGV4"
    "dCBpbmplY3Rpb24uCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgYmFzZSAgICAgICAgICAgICA9IGNm"
    "Z19wYXRoKCJtZW1vcmllcyIpCiAgICAgICAgc2VsZi5tZXNzYWdlc19wICA9IGJhc2UgLyAibWVzc2FnZXMuanNvbmwiCiAgICAg"
    "ICAgc2VsZi5tZW1vcmllc19wICA9IGJhc2UgLyAibWVtb3JpZXMuanNvbmwiCiAgICAgICAgc2VsZi5zdGF0ZV9wICAgICA9IGJh"
    "c2UgLyAic3RhdGUuanNvbiIKICAgICAgICBzZWxmLmluZGV4X3AgICAgID0gYmFzZSAvICJpbmRleC5qc29uIgoKICAgICMg4pSA"
    "4pSAIFNUQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5zdGF0ZV9wLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcyhzZWxmLnN0YXRlX3AucmVhZF90ZXh0KGVuY29kaW5nPSJ1"
    "dGYtOCIpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkK"
    "CiAgICBkZWYgc2F2ZV9zdGF0ZShzZWxmLCBzdGF0ZTogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXRlX3Aud3JpdGVf"
    "dGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoK"
    "ICAgIGRlZiBfZGVmYXVsdF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJwZXJzb25h"
    "X25hbWUiOiAgICAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJkZWNrX3ZlcnNpb24iOiAgICAgICAgICAgICBBUFBf"
    "VkVSU0lPTiwKICAgICAgICAgICAgInNlc3Npb25fY291bnQiOiAgICAgICAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3N0YXJ0"
    "dXAiOiAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9zaHV0ZG93biI6ICAgICAgICAgICAgTm9uZSwKICAgICAg"
    "ICAgICAgImxhc3RfYWN0aXZlIjogICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6ICAgICAg"
    "ICAgICAwLAogICAgICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgImludGVybmFsX25h"
    "cnJhdGl2ZSI6ICAgICAgIHt9LAogICAgICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6IkRPUk1BTlQiLAogICAg"
    "ICAgIH0KCiAgICAjIOKUgOKUgCBNRVNTQUdFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVzc2FnZShzZWxmLCBz"
    "ZXNzaW9uX2lkOiBzdHIsIHJvbGU6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICBjb250ZW50OiBzdHIsIGVtb3Rpb246IHN0"
    "ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICBmIm1zZ197dXVpZC51"
    "dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAi"
    "c2Vzc2lvbl9pZCI6IHNlc3Npb25faWQsCiAgICAgICAgICAgICJwZXJzb25hIjogICAgREVDS19OQU1FLAogICAgICAgICAgICAi"
    "cm9sZSI6ICAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICAgY29udGVudCwKICAgICAgICAgICAgImVtb3Rpb24i"
    "OiAgICBlbW90aW9uLAogICAgICAgIH0KICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5tZXNzYWdlc19wLCByZWNvcmQpCiAgICAg"
    "ICAgcmV0dXJuIHJlY29yZAoKICAgIGRlZiBsb2FkX3JlY2VudF9tZXNzYWdlcyhzZWxmLCBsaW1pdDogaW50ID0gMjApIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5tZXNzYWdlc19wKVstbGltaXQ6XQoKICAgICMg4pSA4pSA"
    "IE1FTU9SSUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZW1vcnkoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCB1c2Vy"
    "X3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgog"
    "ICAgICAgIHJlY29yZF90eXBlID0gaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKICAgICAgICBr"
    "ZXl3b3JkcyAgICA9IGV4dHJhY3Rfa2V5d29yZHModXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpCiAgICAgICAgdGFn"
    "cyAgICAgICAgPSBzZWxmLl9pbmZlcl90YWdzKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHRpdGxl"
    "ICAgICAgID0gc2VsZi5faW5mZXJfdGl0bGUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgc3VtbWFy"
    "eSAgICAgPSBzZWxmLl9zdW1tYXJpemUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQpCgogICAgICAgIG1l"
    "bW9yeSA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmIm1lbV97dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAg"
    "ICAgICAgICAgICJ0aW1lc3RhbXAiOiAgICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAg"
    "ICAgIHNlc3Npb25faWQsCiAgICAgICAgICAgICJwZXJzb25hIjogICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAidHlw"
    "ZSI6ICAgICAgICAgICAgIHJlY29yZF90eXBlLAogICAgICAgICAgICAidGl0bGUiOiAgICAgICAgICAgIHRpdGxlLAogICAgICAg"
    "ICAgICAic3VtbWFyeSI6ICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJjb250ZW50IjogICAgICAgICAgdXNlcl90ZXh0"
    "Wzo0MDAwXSwKICAgICAgICAgICAgImFzc2lzdGFudF9jb250ZXh0Ijphc3Npc3RhbnRfdGV4dFs6MTIwMF0sCiAgICAgICAgICAg"
    "ICJrZXl3b3JkcyI6ICAgICAgICAga2V5d29yZHMsCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgICAgdGFncywKICAgICAg"
    "ICAgICAgImNvbmZpZGVuY2UiOiAgICAgICAwLjcwIGlmIHJlY29yZF90eXBlIGluIHsKICAgICAgICAgICAgICAgICJkcmVhbSIs"
    "Imlzc3VlIiwiaWRlYSIsInByZWZlcmVuY2UiLCJyZXNvbHV0aW9uIgogICAgICAgICAgICB9IGVsc2UgMC41NSwKICAgICAgICB9"
    "CgogICAgICAgIGlmIHNlbGYuX2lzX25lYXJfZHVwbGljYXRlKG1lbW9yeSk6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAg"
    "ICAgIGFwcGVuZF9qc29ubChzZWxmLm1lbW9yaWVzX3AsIG1lbW9yeSkKICAgICAgICByZXR1cm4gbWVtb3J5CgogICAgZGVmIHNl"
    "YXJjaF9tZW1vcmllcyhzZWxmLCBxdWVyeTogc3RyLCBsaW1pdDogaW50ID0gNikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiIK"
    "ICAgICAgICBLZXl3b3JkLXNjb3JlZCBtZW1vcnkgc2VhcmNoLgogICAgICAgIFJldHVybnMgdXAgdG8gYGxpbWl0YCByZWNvcmRz"
    "IHNvcnRlZCBieSByZWxldmFuY2Ugc2NvcmUgZGVzY2VuZGluZy4KICAgICAgICBGYWxscyBiYWNrIHRvIG1vc3QgcmVjZW50IGlm"
    "IG5vIHF1ZXJ5IHRlcm1zIG1hdGNoLgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gcmVhZF9qc29ubChzZWxmLm1lbW9y"
    "aWVzX3ApCiAgICAgICAgaWYgbm90IHF1ZXJ5LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiBtZW1vcmllc1stbGltaXQ6XQoK"
    "ICAgICAgICBxX3Rlcm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMocXVlcnksIGxpbWl0PTE2KSkKICAgICAgICBzY29yZWQgID0g"
    "W10KCiAgICAgICAgZm9yIGl0ZW0gaW4gbWVtb3JpZXM6CiAgICAgICAgICAgIGl0ZW1fdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3"
    "b3JkcygiICIuam9pbihbCiAgICAgICAgICAgICAgICBpdGVtLmdldCgidGl0bGUiLCAgICIiKSwKICAgICAgICAgICAgICAgIGl0"
    "ZW0uZ2V0KCJzdW1tYXJ5IiwgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoImNvbnRlbnQiLCAiIiksCiAgICAgICAgICAg"
    "ICAgICAiICIuam9pbihpdGVtLmdldCgia2V5d29yZHMiLCBbXSkpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQo"
    "InRhZ3MiLCAgICAgW10pKSwKICAgICAgICAgICAgXSksIGxpbWl0PTQwKSkKCiAgICAgICAgICAgIHNjb3JlID0gbGVuKHFfdGVy"
    "bXMgJiBpdGVtX3Rlcm1zKQoKICAgICAgICAgICAgIyBCb29zdCBieSB0eXBlIG1hdGNoCiAgICAgICAgICAgIHFsID0gcXVlcnku"
    "bG93ZXIoKQogICAgICAgICAgICBydCA9IGl0ZW0uZ2V0KCJ0eXBlIiwgIiIpCiAgICAgICAgICAgIGlmICJkcmVhbSIgIGluIHFs"
    "IGFuZCBydCA9PSAiZHJlYW0iOiAgICBzY29yZSArPSA0CiAgICAgICAgICAgIGlmICJ0YXNrIiAgIGluIHFsIGFuZCBydCA9PSAi"
    "dGFzayI6ICAgICBzY29yZSArPSAzCiAgICAgICAgICAgIGlmICJpZGVhIiAgIGluIHFsIGFuZCBydCA9PSAiaWRlYSI6ICAgICBz"
    "Y29yZSArPSAyCiAgICAgICAgICAgIGlmICJsc2wiICAgIGluIHFsIGFuZCBydCBpbiB7Imlzc3VlIiwicmVzb2x1dGlvbiJ9OiBz"
    "Y29yZSArPSAyCgogICAgICAgICAgICBpZiBzY29yZSA+IDA6CiAgICAgICAgICAgICAgICBzY29yZWQuYXBwZW5kKChzY29yZSwg"
    "aXRlbSkpCgogICAgICAgIHNjb3JlZC5zb3J0KGtleT1sYW1iZGEgeDogKHhbMF0sIHhbMV0uZ2V0KCJ0aW1lc3RhbXAiLCAiIikp"
    "LAogICAgICAgICAgICAgICAgICAgIHJldmVyc2U9VHJ1ZSkKICAgICAgICByZXR1cm4gW2l0ZW0gZm9yIF8sIGl0ZW0gaW4gc2Nv"
    "cmVkWzpsaW1pdF1dCgogICAgZGVmIGJ1aWxkX2NvbnRleHRfYmxvY2soc2VsZiwgcXVlcnk6IHN0ciwgbWF4X2NoYXJzOiBpbnQg"
    "PSAyMDAwKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250ZXh0IHN0cmluZyBmcm9tIHJlbGV2YW50IG1l"
    "bW9yaWVzIGZvciBwcm9tcHQgaW5qZWN0aW9uLgogICAgICAgIFRydW5jYXRlcyB0byBtYXhfY2hhcnMgdG8gcHJvdGVjdCB0aGUg"
    "Y29udGV4dCB3aW5kb3cuCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSBzZWxmLnNlYXJjaF9tZW1vcmllcyhxdWVyeSwg"
    "bGltaXQ9NCkKICAgICAgICBpZiBub3QgbWVtb3JpZXM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFsi"
    "W1JFTEVWQU5UIE1FTU9SSUVTXSJdCiAgICAgICAgdG90YWwgPSAwCiAgICAgICAgZm9yIG0gaW4gbWVtb3JpZXM6CiAgICAgICAg"
    "ICAgIGVudHJ5ID0gKAogICAgICAgICAgICAgICAgZiLigKIgW3ttLmdldCgndHlwZScsJycpLnVwcGVyKCl9XSB7bS5nZXQoJ3Rp"
    "dGxlJywnJyl9OiAiCiAgICAgICAgICAgICAgICBmInttLmdldCgnc3VtbWFyeScsJycpfSIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBpZiB0b3RhbCArIGxlbihlbnRyeSkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBw"
    "YXJ0cy5hcHBlbmQoZW50cnkpCiAgICAgICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5kKCJb"
    "RU5EIE1FTU9SSUVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICAjIOKUgOKUgCBIRUxQRVJTIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIF9pc19uZWFyX2R1cGxpY2F0ZShzZWxmLCBjYW5kaWRhdGU6IGRpY3QpIC0+IGJvb2w6CiAg"
    "ICAgICAgcmVjZW50ID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApWy0yNTpdCiAgICAgICAgY3QgPSBjYW5kaWRhdGUuZ2V0"
    "KCJ0aXRsZSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBjcyA9IGNhbmRpZGF0ZS5nZXQoInN1bW1hcnkiLCAiIikubG93"
    "ZXIoKS5zdHJpcCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gcmVjZW50OgogICAgICAgICAgICBpZiBpdGVtLmdldCgidGl0bGUiLCIi"
    "KS5sb3dlcigpLnN0cmlwKCkgPT0gY3Q6ICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiBpdGVtLmdldCgic3VtbWFyeSIsIiIp"
    "Lmxvd2VyKCkuc3RyaXAoKSA9PSBjczogcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgX2luZmVyX3Rh"
    "Z3Moc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0"
    "cl0pIC0+IGxpc3Rbc3RyXToKICAgICAgICB0ICAgID0gdGV4dC5sb3dlcigpCiAgICAgICAgdGFncyA9IFtyZWNvcmRfdHlwZV0K"
    "ICAgICAgICBpZiAiZHJlYW0iICAgaW4gdDogdGFncy5hcHBlbmQoImRyZWFtIikKICAgICAgICBpZiAibHNsIiAgICAgaW4gdDog"
    "dGFncy5hcHBlbmQoImxzbCIpCiAgICAgICAgaWYgInB5dGhvbiIgIGluIHQ6IHRhZ3MuYXBwZW5kKCJweXRob24iKQogICAgICAg"
    "IGlmICJnYW1lIiAgICBpbiB0OiB0YWdzLmFwcGVuZCgiZ2FtZV9pZGVhIikKICAgICAgICBpZiAic2wiICAgICAgaW4gdCBvciAi"
    "c2Vjb25kIGxpZmUiIGluIHQ6IHRhZ3MuYXBwZW5kKCJzZWNvbmRsaWZlIikKICAgICAgICBpZiBERUNLX05BTUUubG93ZXIoKSBp"
    "biB0OiB0YWdzLmFwcGVuZChERUNLX05BTUUubG93ZXIoKSkKICAgICAgICBmb3Iga3cgaW4ga2V5d29yZHNbOjRdOgogICAgICAg"
    "ICAgICBpZiBrdyBub3QgaW4gdGFnczoKICAgICAgICAgICAgICAgIHRhZ3MuYXBwZW5kKGt3KQogICAgICAgICMgRGVkdXBsaWNh"
    "dGUgcHJlc2VydmluZyBvcmRlcgogICAgICAgIHNlZW4sIG91dCA9IHNldCgpLCBbXQogICAgICAgIGZvciB0YWcgaW4gdGFnczoK"
    "ICAgICAgICAgICAgaWYgdGFnIG5vdCBpbiBzZWVuOgogICAgICAgICAgICAgICAgc2Vlbi5hZGQodGFnKQogICAgICAgICAgICAg"
    "ICAgb3V0LmFwcGVuZCh0YWcpCiAgICAgICAgcmV0dXJuIG91dFs6MTJdCgogICAgZGVmIF9pbmZlcl90aXRsZShzZWxmLCByZWNv"
    "cmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4g"
    "c3RyOgogICAgICAgIGRlZiBjbGVhbih3b3Jkcyk6CiAgICAgICAgICAgIHJldHVybiBbdy5zdHJpcCgiIC1fLiwhPyIpLmNhcGl0"
    "YWxpemUoKQogICAgICAgICAgICAgICAgICAgIGZvciB3IGluIHdvcmRzIGlmIGxlbih3KSA+IDJdCgogICAgICAgIGlmIHJlY29y"
    "ZF90eXBlID09ICJ0YXNrIjoKICAgICAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgICAgIG0gPSByZS5zZWFyY2gociJyZW1pbmQg"
    "bWUgLio/IHRvICguKykiLCB1c2VyX3RleHQsIHJlLkkpCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAgICAgICByZXR1cm4g"
    "ZiJSZW1pbmRlcjoge20uZ3JvdXAoMSkuc3RyaXAoKVs6NjBdfSIKICAgICAgICAgICAgcmV0dXJuICJSZW1pbmRlciBUYXNrIgog"
    "ICAgICAgIGlmIHJlY29yZF90eXBlID09ICJkcmVhbSI6CiAgICAgICAgICAgIHJldHVybiBmInsnICcuam9pbihjbGVhbihrZXl3"
    "b3Jkc1s6M10pKX0gRHJlYW0iLnN0cmlwKCkgb3IgIkRyZWFtIE1lbW9yeSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaXNz"
    "dWUiOgogICAgICAgICAgICByZXR1cm4gZiJJc3N1ZTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBv"
    "ciAiVGVjaG5pY2FsIElzc3VlIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjoKICAgICAgICAgICAgcmV0"
    "dXJuIGYiUmVzb2x1dGlvbjogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2FsIFJl"
    "c29sdXRpb24iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOgogICAgICAgICAgICByZXR1cm4gZiJJZGVhOiB7JyAn"
    "LmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJJZGVhIgogICAgICAgIGlmIGtleXdvcmRzOgogICAgICAg"
    "ICAgICByZXR1cm4gIiAiLmpvaW4oY2xlYW4oa2V5d29yZHNbOjVdKSkgb3IgIkNvbnZlcnNhdGlvbiBNZW1vcnkiCiAgICAgICAg"
    "cmV0dXJuICJDb252ZXJzYXRpb24gTWVtb3J5IgoKICAgIGRlZiBfc3VtbWFyaXplKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVz"
    "ZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gc3RyOgogICAgICAgIHUgPSB1"
    "c2VyX3RleHQuc3RyaXAoKVs6MjIwXQogICAgICAgIGEgPSBhc3Npc3RhbnRfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgaWYg"
    "cmVjb3JkX3R5cGUgPT0gImRyZWFtIjogICAgICAgcmV0dXJuIGYiVXNlciBkZXNjcmliZWQgYSBkcmVhbToge3V9IgogICAgICAg"
    "IGlmIHJlY29yZF90eXBlID09ICJ0YXNrIjogICAgICAgIHJldHVybiBmIlJlbWluZGVyL3Rhc2s6IHt1fSIKICAgICAgICBpZiBy"
    "ZWNvcmRfdHlwZSA9PSAiaXNzdWUiOiAgICAgICByZXR1cm4gZiJUZWNobmljYWwgaXNzdWU6IHt1fSIKICAgICAgICBpZiByZWNv"
    "cmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6ICByZXR1cm4gZiJTb2x1dGlvbiByZWNvcmRlZDoge2Egb3IgdX0iCiAgICAgICAgaWYg"
    "cmVjb3JkX3R5cGUgPT0gImlkZWEiOiAgICAgICAgcmV0dXJuIGYiSWRlYSBkaXNjdXNzZWQ6IHt1fSIKICAgICAgICBpZiByZWNv"
    "cmRfdHlwZSA9PSAicHJlZmVyZW5jZSI6ICByZXR1cm4gZiJQcmVmZXJlbmNlIG5vdGVkOiB7dX0iCiAgICAgICAgcmV0dXJuIGYi"
    "Q29udmVyc2F0aW9uOiB7dX0iCgoKIyDilIDilIAgU0VTU0lPTiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBTZXNzaW9uTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyBjb252ZXJzYXRpb24gc2Vzc2lvbnMuCgogICAgQXV0by1z"
    "YXZlOiBldmVyeSAxMCBtaW51dGVzIChBUFNjaGVkdWxlciksIG1pZG5pZ2h0LXRvLW1pZG5pZ2h0IGJvdW5kYXJ5LgogICAgRmls"
    "ZTogc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubCDigJQgb3ZlcndyaXRlcyBvbiBlYWNoIHNhdmUuCiAgICBJbmRleDogc2Vzc2lv"
    "bnMvc2Vzc2lvbl9pbmRleC5qc29uIOKAlCBvbmUgZW50cnkgcGVyIGRheS4KCiAgICBTZXNzaW9ucyBhcmUgbG9hZGVkIGFzIGNv"
    "bnRleHQgaW5qZWN0aW9uIChub3QgcmVhbCBtZW1vcnkpIHVudGlsCiAgICB0aGUgU1FMaXRlL0Nocm9tYURCIHN5c3RlbSBpcyBi"
    "dWlsdCBpbiBQaGFzZSAyLgogICAgIiIiCgogICAgQVVUT1NBVkVfSU5URVJWQUwgPSAxMCAgICMgbWludXRlcwoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9zZXNzaW9uc19kaXIgID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgICAgICBz"
    "ZWxmLl9pbmRleF9wYXRoICAgID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX2lkICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfSIKICAg"
    "ICAgICBzZWxmLl9jdXJyZW50X2RhdGUgID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgc2VsZi5fbWVzc2FnZXM6"
    "IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsOiBPcHRpb25hbFtzdHJdID0gTm9uZSAgIyBkYXRl"
    "IG9mIGxvYWRlZCBqb3VybmFsCgogICAgIyDilIDilIAgQ1VSUkVOVCBTRVNTSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFkZF9tZXNzYWdlKHNlbGYsIHJvbGU6"
    "IHN0ciwgY29udGVudDogc3RyLAogICAgICAgICAgICAgICAgICAgIGVtb3Rpb246IHN0ciA9ICIiLCB0aW1lc3RhbXA6IHN0ciA9"
    "ICIiKSAtPiBOb25lOgogICAgICAgIHNlbGYuX21lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICJpZCI6ICAgICAgICBmIm1z"
    "Z197dXVpZC51dWlkNCgpLmhleFs6OF19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRpbWVzdGFtcCBvciBsb2NhbF9ub3df"
    "aXNvKCksCiAgICAgICAgICAgICJyb2xlIjogICAgICByb2xlLAogICAgICAgICAgICAiY29udGVudCI6ICAgY29udGVudCwKICAg"
    "ICAgICAgICAgImVtb3Rpb24iOiAgIGVtb3Rpb24sCiAgICAgICAgfSkKCiAgICBkZWYgZ2V0X2hpc3Rvcnkoc2VsZikgLT4gbGlz"
    "dFtkaWN0XToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm4gaGlzdG9yeSBpbiBMTE0tZnJpZW5kbHkgZm9ybWF0LgogICAgICAg"
    "IFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFudCIsICJjb250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHJldHVy"
    "biBbCiAgICAgICAgICAgIHsicm9sZSI6IG1bInJvbGUiXSwgImNvbnRlbnQiOiBtWyJjb250ZW50Il19CiAgICAgICAgICAgIGZv"
    "ciBtIGluIHNlbGYuX21lc3NhZ2VzCiAgICAgICAgICAgIGlmIG1bInJvbGUiXSBpbiAoInVzZXIiLCAiYXNzaXN0YW50IikKICAg"
    "ICAgICBdCgogICAgQHByb3BlcnR5CiAgICBkZWYgc2Vzc2lvbl9pZChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYu"
    "X3Nlc3Npb25faWQKCiAgICBAcHJvcGVydHkKICAgIGRlZiBtZXNzYWdlX2NvdW50KHNlbGYpIC0+IGludDoKICAgICAgICByZXR1"
    "cm4gbGVuKHNlbGYuX21lc3NhZ2VzKQoKICAgICMg4pSA4pSAIFNBVkUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgc2F2ZShzZWxmLCBhaV9nZW5lcmF0ZWRfbmFtZTogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2F2"
    "ZSBjdXJyZW50IHNlc3Npb24gdG8gc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubC4KICAgICAgICBPdmVyd3JpdGVzIHRoZSBmaWxl"
    "IGZvciB0b2RheSDigJQgZWFjaCBzYXZlIGlzIGEgZnVsbCBzbmFwc2hvdC4KICAgICAgICBVcGRhdGVzIHNlc3Npb25faW5kZXgu"
    "anNvbi4KICAgICAgICAiIiIKICAgICAgICB0b2RheSA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIG91dF9wYXRo"
    "ID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gZiJ7dG9kYXl9Lmpzb25sIgoKICAgICAgICAjIFdyaXRlIGFsbCBtZXNzYWdlcwogICAg"
    "ICAgIHdyaXRlX2pzb25sKG91dF9wYXRoLCBzZWxmLl9tZXNzYWdlcykKCiAgICAgICAgIyBVcGRhdGUgaW5kZXgKICAgICAgICBp"
    "bmRleCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGV4aXN0aW5nID0gbmV4dCgKICAgICAgICAgICAgKHMgZm9yIHMgaW4g"
    "aW5kZXhbInNlc3Npb25zIl0gaWYgc1siZGF0ZSJdID09IHRvZGF5KSwgTm9uZQogICAgICAgICkKCiAgICAgICAgbmFtZSA9IGFp"
    "X2dlbmVyYXRlZF9uYW1lIG9yIGV4aXN0aW5nLmdldCgibmFtZSIsICIiKSBpZiBleGlzdGluZyBlbHNlICIiCiAgICAgICAgaWYg"
    "bm90IG5hbWUgYW5kIHNlbGYuX21lc3NhZ2VzOgogICAgICAgICAgICAjIEF1dG8tbmFtZSBmcm9tIGZpcnN0IHVzZXIgbWVzc2Fn"
    "ZSAoZmlyc3QgNSB3b3JkcykKICAgICAgICAgICAgZmlyc3RfdXNlciA9IG5leHQoCiAgICAgICAgICAgICAgICAobVsiY29udGVu"
    "dCJdIGZvciBtIGluIHNlbGYuX21lc3NhZ2VzIGlmIG1bInJvbGUiXSA9PSAidXNlciIpLAogICAgICAgICAgICAgICAgIiIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICB3b3JkcyA9IGZpcnN0X3VzZXIuc3BsaXQoKVs6NV0KICAgICAgICAgICAgbmFtZSAgPSAi"
    "ICIuam9pbih3b3JkcykgaWYgd29yZHMgZWxzZSBmIlNlc3Npb24ge3RvZGF5fSIKCiAgICAgICAgZW50cnkgPSB7CiAgICAgICAg"
    "ICAgICJkYXRlIjogICAgICAgICAgdG9kYXksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgc2VsZi5fc2Vzc2lvbl9pZCwK"
    "ICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgICBuYW1lLAogICAgICAgICAgICAibWVzc2FnZV9jb3VudCI6IGxlbihzZWxmLl9t"
    "ZXNzYWdlcyksCiAgICAgICAgICAgICJmaXJzdF9tZXNzYWdlIjogKHNlbGYuX21lc3NhZ2VzWzBdWyJ0aW1lc3RhbXAiXQogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICAgICAgImxhc3RfbWVz"
    "c2FnZSI6ICAoc2VsZi5fbWVzc2FnZXNbLTFdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBz"
    "ZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICB9CgogICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAgICBpZHggPSBp"
    "bmRleFsic2Vzc2lvbnMiXS5pbmRleChleGlzdGluZykKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl1baWR4XSA9IGVudHJ5"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl0uaW5zZXJ0KDAsIGVudHJ5KQoKICAgICAgICAjIEtl"
    "ZXAgbGFzdCAzNjUgZGF5cyBpbiBpbmRleAogICAgICAgIGluZGV4WyJzZXNzaW9ucyJdID0gaW5kZXhbInNlc3Npb25zIl1bOjM2"
    "NV0KICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQoKICAgICMg4pSA4pSAIExPQUQgLyBKT1VSTkFMIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxpc3Rf"
    "c2Vzc2lvbnMoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiJSZXR1cm4gYWxsIHNlc3Npb25zIGZyb20gaW5kZXgsIG5l"
    "d2VzdCBmaXJzdC4iIiIKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZF9pbmRleCgpLmdldCgic2Vzc2lvbnMiLCBbXSkKCiAgICBk"
    "ZWYgbG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIpIC0+IHN0cjoKICAgICAgICAiIiIKICAg"
    "ICAgICBMb2FkIGEgcGFzdCBzZXNzaW9uIGFzIGEgY29udGV4dCBpbmplY3Rpb24gc3RyaW5nLgogICAgICAgIFJldHVybnMgZm9y"
    "bWF0dGVkIHRleHQgdG8gcHJlcGVuZCB0byB0aGUgc3lzdGVtIHByb21wdC4KICAgICAgICBUaGlzIGlzIE5PVCByZWFsIG1lbW9y"
    "eSDigJQgaXQncyBhIHRlbXBvcmFyeSBjb250ZXh0IHdpbmRvdyBpbmplY3Rpb24KICAgICAgICB1bnRpbCB0aGUgUGhhc2UgMiBt"
    "ZW1vcnkgc3lzdGVtIGlzIGJ1aWx0LgogICAgICAgICIiIgogICAgICAgIHBhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmIntz"
    "ZXNzaW9uX2RhdGV9Lmpzb25sIgogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gIiIKCiAg"
    "ICAgICAgbWVzc2FnZXMgPSByZWFkX2pzb25sKHBhdGgpCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwgPSBzZXNzaW9uX2Rh"
    "dGUKCiAgICAgICAgbGluZXMgPSBbZiJbSk9VUk5BTCBMT0FERUQg4oCUIHtzZXNzaW9uX2RhdGV9XSIsCiAgICAgICAgICAgICAg"
    "ICAgIlRoZSBmb2xsb3dpbmcgaXMgYSByZWNvcmQgb2YgYSBwcmlvciBjb252ZXJzYXRpb24uIiwKICAgICAgICAgICAgICAgICAi"
    "VXNlIHRoaXMgYXMgY29udGV4dCBmb3IgdGhlIGN1cnJlbnQgc2Vzc2lvbjpcbiJdCgogICAgICAgICMgSW5jbHVkZSB1cCB0byBs"
    "YXN0IDMwIG1lc3NhZ2VzIGZyb20gdGhhdCBzZXNzaW9uCiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlc1stMzA6XToKICAgICAg"
    "ICAgICAgcm9sZSAgICA9IG1zZy5nZXQoInJvbGUiLCAiPyIpLnVwcGVyKCkKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQo"
    "ImNvbnRlbnQiLCAiIilbOjMwMF0KICAgICAgICAgICAgdHMgICAgICA9IG1zZy5nZXQoInRpbWVzdGFtcCIsICIiKVs6MTZdCiAg"
    "ICAgICAgICAgIGxpbmVzLmFwcGVuZChmIlt7dHN9XSB7cm9sZX06IHtjb250ZW50fSIpCgogICAgICAgIGxpbmVzLmFwcGVuZCgi"
    "W0VORCBKT1VSTkFMXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihsaW5lcykKCiAgICBkZWYgY2xlYXJfbG9hZGVkX2pvdXJu"
    "YWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IE5vbmUKCiAgICBAcHJvcGVydHkKICAgIGRl"
    "ZiBsb2FkZWRfam91cm5hbF9kYXRlKHNlbGYpIC0+IE9wdGlvbmFsW3N0cl06CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZF9q"
    "b3VybmFsCgogICAgZGVmIHJlbmFtZV9zZXNzaW9uKHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyLCBuZXdfbmFtZTogc3RyKSAtPiBi"
    "b29sOgogICAgICAgICIiIlJlbmFtZSBhIHNlc3Npb24gaW4gdGhlIGluZGV4LiBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4iIiIK"
    "ICAgICAgICBpbmRleCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGZvciBlbnRyeSBpbiBpbmRleFsic2Vzc2lvbnMiXToK"
    "ICAgICAgICAgICAgaWYgZW50cnlbImRhdGUiXSA9PSBzZXNzaW9uX2RhdGU6CiAgICAgICAgICAgICAgICBlbnRyeVsibmFtZSJd"
    "ID0gbmV3X25hbWVbOjgwXQogICAgICAgICAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKICAgICAgICAgICAgICAgIHJl"
    "dHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgIyDilIDilIAgSU5ERVggSEVMUEVSUyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9p"
    "bmRleChzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLl9pbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBy"
    "ZXR1cm4geyJzZXNzaW9ucyI6IFtdfQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9pbmRleF9wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICApCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KCiAgICBkZWYgX3NhdmVfaW5kZXgo"
    "c2VsZiwgaW5kZXg6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faW5kZXhfcGF0aC53cml0ZV90ZXh0KAogICAgICAgICAg"
    "ICBqc29uLmR1bXBzKGluZGV4LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgoKIyDilIDilIAgTEVTU09O"
    "UyBMRUFSTkVEIERBVEFCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zTGVhcm5lZERCOgogICAgIiIiCiAgICBQZXJzaXN0ZW50IGtub3dsZWRn"
    "ZSBiYXNlIGZvciBjb2RlIGxlc3NvbnMsIHJ1bGVzLCBhbmQgcmVzb2x1dGlvbnMuCgogICAgQ29sdW1ucyBwZXIgcmVjb3JkOgog"
    "ICAgICAgIGlkLCBjcmVhdGVkX2F0LCBlbnZpcm9ubWVudCAoTFNMfFB5dGhvbnxQeVNpZGU2fC4uLiksIGxhbmd1YWdlLAogICAg"
    "ICAgIHJlZmVyZW5jZV9rZXkgKHNob3J0IHVuaXF1ZSB0YWcpLCBzdW1tYXJ5LCBmdWxsX3J1bGUsCiAgICAgICAgcmVzb2x1dGlv"
    "biwgbGluaywgdGFncwoKICAgIFF1ZXJpZWQgRklSU1QgYmVmb3JlIGFueSBjb2RlIHNlc3Npb24gaW4gdGhlIHJlbGV2YW50IGxh"
    "bmd1YWdlLgogICAgVGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBsaXZlcyBoZXJlLgogICAgR3Jvd2luZywgbm9uLWR1cGxpY2F0"
    "aW5nLCBzZWFyY2hhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdf"
    "cGF0aCgibWVtb3JpZXMiKSAvICJsZXNzb25zX2xlYXJuZWQuanNvbmwiCgogICAgZGVmIGFkZChzZWxmLCBlbnZpcm9ubWVudDog"
    "c3RyLCBsYW5ndWFnZTogc3RyLCByZWZlcmVuY2Vfa2V5OiBzdHIsCiAgICAgICAgICAgIHN1bW1hcnk6IHN0ciwgZnVsbF9ydWxl"
    "OiBzdHIsIHJlc29sdXRpb246IHN0ciA9ICIiLAogICAgICAgICAgICBsaW5rOiBzdHIgPSAiIiwgdGFnczogbGlzdCA9IE5vbmUp"
    "IC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgIGYibGVzc29uX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICJlbnZpcm9ubWVudCI6ICAgZW52aXJvbm1lbnQsCiAgICAgICAgICAgICJsYW5ndWFnZSI6ICAgICAgbGFuZ3VhZ2UsCiAgICAg"
    "ICAgICAgICJyZWZlcmVuY2Vfa2V5IjogcmVmZXJlbmNlX2tleSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICBzdW1tYXJ5"
    "LAogICAgICAgICAgICAiZnVsbF9ydWxlIjogICAgIGZ1bGxfcnVsZSwKICAgICAgICAgICAgInJlc29sdXRpb24iOiAgICByZXNv"
    "bHV0aW9uLAogICAgICAgICAgICAibGluayI6ICAgICAgICAgIGxpbmssCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgdGFn"
    "cyBvciBbXSwKICAgICAgICB9CiAgICAgICAgaWYgbm90IHNlbGYuX2lzX2R1cGxpY2F0ZShyZWZlcmVuY2Vfa2V5KToKICAgICAg"
    "ICAgICAgYXBwZW5kX2pzb25sKHNlbGYuX3BhdGgsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIHNlYXJj"
    "aChzZWxmLCBxdWVyeTogc3RyID0gIiIsIGVudmlyb25tZW50OiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgbGFuZ3VhZ2U6IHN0"
    "ciA9ICIiKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgcmVz"
    "dWx0cyA9IFtdCiAgICAgICAgcSA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBp"
    "ZiBlbnZpcm9ubWVudCBhbmQgci5nZXQoImVudmlyb25tZW50IiwiIikubG93ZXIoKSAhPSBlbnZpcm9ubWVudC5sb3dlcigpOgog"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbGFuZ3VhZ2UgYW5kIHIuZ2V0KCJsYW5ndWFnZSIsIiIpLmxv"
    "d2VyKCkgIT0gbGFuZ3VhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIHE6CiAgICAg"
    "ICAgICAgICAgICBoYXlzdGFjayA9ICIgIi5qb2luKFsKICAgICAgICAgICAgICAgICAgICByLmdldCgic3VtbWFyeSIsIiIpLAog"
    "ICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJmdWxsX3J1bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdldCgicmVmZXJl"
    "bmNlX2tleSIsIiIpLAogICAgICAgICAgICAgICAgICAgICIgIi5qb2luKHIuZ2V0KCJ0YWdzIixbXSkpLAogICAgICAgICAgICAg"
    "ICAgXSkubG93ZXIoKQogICAgICAgICAgICAgICAgaWYgcSBub3QgaW4gaGF5c3RhY2s6CiAgICAgICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgcmVzdWx0cy5hcHBlbmQocikKICAgICAgICByZXR1cm4gcmVzdWx0cwoKICAgIGRlZiBnZXRfYWxs"
    "KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKCiAgICBkZWYgZGVsZXRl"
    "KHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBib29sOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAg"
    "ICAgICAgZmlsdGVyZWQgPSBbciBmb3IgciBpbiByZWNvcmRzIGlmIHIuZ2V0KCJpZCIpICE9IHJlY29yZF9pZF0KICAgICAgICBp"
    "ZiBsZW4oZmlsdGVyZWQpIDwgbGVuKHJlY29yZHMpOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBmaWx0ZXJl"
    "ZCkKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgYnVpbGRfY29udGV4dF9mb3Jf"
    "bGFuZ3VhZ2Uoc2VsZiwgbGFuZ3VhZ2U6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfY2hhcnM6"
    "IGludCA9IDE1MDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIG9mIGFsbCBydWxl"
    "cyBmb3IgYSBnaXZlbiBsYW5ndWFnZS4KICAgICAgICBGb3IgaW5qZWN0aW9uIGludG8gc3lzdGVtIHByb21wdCBiZWZvcmUgY29k"
    "ZSBzZXNzaW9ucy4KICAgICAgICAiIiIKICAgICAgICByZWNvcmRzID0gc2VsZi5zZWFyY2gobGFuZ3VhZ2U9bGFuZ3VhZ2UpCiAg"
    "ICAgICAgaWYgbm90IHJlY29yZHM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFtmIlt7bGFuZ3VhZ2Uu"
    "dXBwZXIoKX0gUlVMRVMg4oCUIEFQUExZIEJFRk9SRSBXUklUSU5HIENPREVdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBm"
    "b3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBlbnRyeSA9IGYi4oCiIHtyLmdldCgncmVmZXJlbmNlX2tleScsJycpfToge3Iu"
    "Z2V0KCdmdWxsX3J1bGUnLCcnKX0iCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAg"
    "ICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVu"
    "dHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoZiJbRU5EIHtsYW5ndWFnZS51cHBlcigpfSBSVUxFU10iKQogICAgICAgIHJldHVy"
    "biAiXG4iLmpvaW4ocGFydHMpCgogICAgZGVmIF9pc19kdXBsaWNhdGUoc2VsZiwgcmVmZXJlbmNlX2tleTogc3RyKSAtPiBib29s"
    "OgogICAgICAgIHJldHVybiBhbnkoCiAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikubG93ZXIoKSA9PSByZWZl"
    "cmVuY2Vfa2V5Lmxvd2VyKCkKICAgICAgICAgICAgZm9yIHIgaW4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICkKCiAg"
    "ICBkZWYgc2VlZF9sc2xfcnVsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTZWVkIHRoZSBMU0wgRm9yYmlk"
    "ZGVuIFJ1bGVzZXQgb24gZmlyc3QgcnVuIGlmIHRoZSBEQiBpcyBlbXB0eS4KICAgICAgICBUaGVzZSBhcmUgdGhlIGhhcmQgcnVs"
    "ZXMgZnJvbSB0aGUgcHJvamVjdCBzdGFuZGluZyBydWxlcy4KICAgICAgICAiIiIKICAgICAgICBpZiByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpOgogICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBzZWVkZWQKCiAgICAgICAgbHNsX3J1bGVzID0gWwogICAgICAg"
    "ICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVEVSTkFSWSIsCiAgICAgICAgICAgICAiTm8gdGVybmFyeSBvcGVyYXRvcnMgaW4gTFNM"
    "IiwKICAgICAgICAgICAgICJOZXZlciB1c2UgdGhlIHRlcm5hcnkgb3BlcmF0b3IgKD86KSBpbiBMU0wgc2NyaXB0cy4gIgogICAg"
    "ICAgICAgICAgIlVzZSBpZi9lbHNlIGJsb2NrcyBpbnN0ZWFkLiBMU0wgZG9lcyBub3Qgc3VwcG9ydCB0ZXJuYXJ5LiIsCiAgICAg"
    "ICAgICAgICAiUmVwbGFjZSB3aXRoIGlmL2Vsc2UgYmxvY2suIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9f"
    "Rk9SRUFDSCIsCiAgICAgICAgICAgICAiTm8gZm9yZWFjaCBsb29wcyBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBoYXMgbm8g"
    "Zm9yZWFjaCBsb29wIGNvbnN0cnVjdC4gVXNlIGludGVnZXIgaW5kZXggd2l0aCAiCiAgICAgICAgICAgICAibGxHZXRMaXN0TGVu"
    "Z3RoKCkgYW5kIGEgZm9yIG9yIHdoaWxlIGxvb3AuIiwKICAgICAgICAgICAgICJVc2U6IGZvcihpbnRlZ2VyIGk9MDsgaTxsbEdl"
    "dExpc3RMZW5ndGgobXlMaXN0KTsgaSsrKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0dMT0JBTF9BU1NJ"
    "R05fRlJPTV9GVU5DIiwKICAgICAgICAgICAgICJObyBnbG9iYWwgdmFyaWFibGUgYXNzaWdubWVudHMgZnJvbSBmdW5jdGlvbiBj"
    "YWxscyIsCiAgICAgICAgICAgICAiR2xvYmFsIHZhcmlhYmxlIGluaXRpYWxpemF0aW9uIGluIExTTCBjYW5ub3QgY2FsbCBmdW5j"
    "dGlvbnMuICIKICAgICAgICAgICAgICJJbml0aWFsaXplIGdsb2JhbHMgd2l0aCBsaXRlcmFsIHZhbHVlcyBvbmx5LiAiCiAgICAg"
    "ICAgICAgICAiQXNzaWduIGZyb20gZnVuY3Rpb25zIGluc2lkZSBldmVudCBoYW5kbGVycyBvciBvdGhlciBmdW5jdGlvbnMuIiwK"
    "ICAgICAgICAgICAgICJNb3ZlIHRoZSBhc3NpZ25tZW50IGludG8gYW4gZXZlbnQgaGFuZGxlciAoc3RhdGVfZW50cnksIGV0Yy4p"
    "IiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVk9JRF9LRVlXT1JEIiwKICAgICAgICAgICAgICJObyB2b2lk"
    "IGtleXdvcmQgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgZG9lcyBub3QgaGF2ZSBhIHZvaWQga2V5d29yZCBmb3IgZnVuY3Rp"
    "b24gcmV0dXJuIHR5cGVzLiAiCiAgICAgICAgICAgICAiRnVuY3Rpb25zIHRoYXQgcmV0dXJuIG5vdGhpbmcgc2ltcGx5IG9taXQg"
    "dGhlIHJldHVybiB0eXBlLiIsCiAgICAgICAgICAgICAiUmVtb3ZlICd2b2lkJyBmcm9tIGZ1bmN0aW9uIHNpZ25hdHVyZS4gIgog"
    "ICAgICAgICAgICAgImUuZy4gbXlGdW5jKCkgeyAuLi4gfSBub3Qgdm9pZCBteUZ1bmMoKSB7IC4uLiB9IiwgIiIpLAogICAgICAg"
    "ICAgICAoIkxTTCIsICJMU0wiLCAiQ09NUExFVEVfU0NSSVBUU19PTkxZIiwKICAgICAgICAgICAgICJBbHdheXMgcHJvdmlkZSBj"
    "b21wbGV0ZSBzY3JpcHRzLCBuZXZlciBwYXJ0aWFsIGVkaXRzIiwKICAgICAgICAgICAgICJXaGVuIHdyaXRpbmcgb3IgZWRpdGlu"
    "ZyBMU0wgc2NyaXB0cywgYWx3YXlzIG91dHB1dCB0aGUgY29tcGxldGUgIgogICAgICAgICAgICAgInNjcmlwdC4gTmV2ZXIgcHJv"
    "dmlkZSBwYXJ0aWFsIHNuaXBwZXRzIG9yICdhZGQgdGhpcyBzZWN0aW9uJyAiCiAgICAgICAgICAgICAiaW5zdHJ1Y3Rpb25zLiBU"
    "aGUgZnVsbCBzY3JpcHQgbXVzdCBiZSBjb3B5LXBhc3RlIHJlYWR5LiIsCiAgICAgICAgICAgICAiV3JpdGUgdGhlIGVudGlyZSBz"
    "Y3JpcHQgZnJvbSB0b3AgdG8gYm90dG9tLiIsICIiKSwKICAgICAgICBdCgogICAgICAgIGZvciBlbnYsIGxhbmcsIHJlZiwgc3Vt"
    "bWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rIGluIGxzbF9ydWxlczoKICAgICAgICAgICAgc2VsZi5hZGQoZW52LCBs"
    "YW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluaywKICAgICAgICAgICAgICAgICAgICAgdGFncz1b"
    "ImxzbCIsICJmb3JiaWRkZW4iLCAic3RhbmRpbmdfcnVsZSJdKQoKCiMg4pSA4pSAIFRBU0sgTUFOQUdFUiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgVGFza01hbmFnZXI6CiAgICAiIiIKICAgIFRhc2svcmVtaW5kZXIgQ1JVRCBhbmQg"
    "ZHVlLWV2ZW50IGRldGVjdGlvbi4KCiAgICBGaWxlOiBtZW1vcmllcy90YXNrcy5qc29ubAoKICAgIFRhc2sgcmVjb3JkIGZpZWxk"
    "czoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZHVlX2F0LCBwcmVfdHJpZ2dlciAoMW1pbiBiZWZvcmUpLAogICAgICAgIHRleHQs"
    "IHN0YXR1cyAocGVuZGluZ3x0cmlnZ2VyZWR8c25vb3plZHxjb21wbGV0ZWR8Y2FuY2VsbGVkKSwKICAgICAgICBhY2tub3dsZWRn"
    "ZWRfYXQsIHJldHJ5X2NvdW50LCBsYXN0X3RyaWdnZXJlZF9hdCwgbmV4dF9yZXRyeV9hdCwKICAgICAgICBzb3VyY2UgKGxvY2Fs"
    "fGdvb2dsZSksIGdvb2dsZV9ldmVudF9pZCwgc3luY19zdGF0dXMsIG1ldGFkYXRhCgogICAgRHVlLWV2ZW50IGN5Y2xlOgogICAg"
    "ICAgIC0gUHJlLXRyaWdnZXI6IDEgbWludXRlIGJlZm9yZSBkdWUg4oaSIGFubm91bmNlIHVwY29taW5nCiAgICAgICAgLSBEdWUg"
    "dHJpZ2dlcjogYXQgZHVlIHRpbWUg4oaSIGFsZXJ0IHNvdW5kICsgQUkgY29tbWVudGFyeQogICAgICAgIC0gMy1taW51dGUgd2lu"
    "ZG93OiBpZiBub3QgYWNrbm93bGVkZ2VkIOKGkiBzbm9vemUKICAgICAgICAtIDEyLW1pbnV0ZSByZXRyeTogcmUtdHJpZ2dlcgog"
    "ICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAv"
    "ICJ0YXNrcy5qc29ubCIKCiAgICAjIOKUgOKUgCBDUlVEIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRf"
    "YWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgY2hh"
    "bmdlZCA9IEZhbHNlCiAgICAgICAgbm9ybWFsaXplZCA9IFtdCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlm"
    "IG5vdCBpc2luc3RhbmNlKHQsIGRpY3QpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgImlkIiBub3Qg"
    "aW4gdDoKICAgICAgICAgICAgICAgIHRbImlkIl0gPSBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iCiAgICAgICAgICAg"
    "ICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAjIE5vcm1hbGl6ZSBmaWVsZCBuYW1lcwogICAgICAgICAgICBpZiAiZHVl"
    "X2F0IiBub3QgaW4gdDoKICAgICAgICAgICAgICAgIHRbImR1ZV9hdCJdID0gdC5nZXQoImR1ZSIpCiAgICAgICAgICAgICAgICBj"
    "aGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN0YXR1cyIsICAgICAgICAgICAicGVuZGluZyIpCiAgICAg"
    "ICAgICAgIHQuc2V0ZGVmYXVsdCgicmV0cnlfY291bnQiLCAgICAgIDApCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiYWNrbm93"
    "bGVkZ2VkX2F0IiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibGFzdF90cmlnZ2VyZWRfYXQiLE5vbmUpCiAgICAg"
    "ICAgICAgIHQuc2V0ZGVmYXVsdCgibmV4dF9yZXRyeV9hdCIsICAgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicHJl"
    "X2Fubm91bmNlZCIsICAgIEZhbHNlKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInNvdXJjZSIsICAgICAgICAgICAibG9jYWwi"
    "KQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImdvb2dsZV9ldmVudF9pZCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1"
    "bHQoInN5bmNfc3RhdHVzIiwgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCAgICAg"
    "ICAgIHt9KQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImNyZWF0ZWRfYXQiLCAgICAgICBsb2NhbF9ub3dfaXNvKCkpCgogICAg"
    "ICAgICAgICAjIENvbXB1dGUgcHJlX3RyaWdnZXIgaWYgbWlzc2luZwogICAgICAgICAgICBpZiB0LmdldCgiZHVlX2F0IikgYW5k"
    "IG5vdCB0LmdldCgicHJlX3RyaWdnZXIiKToKICAgICAgICAgICAgICAgIGR0ID0gcGFyc2VfaXNvKHRbImR1ZV9hdCJdKQogICAg"
    "ICAgICAgICAgICAgaWYgZHQ6CiAgICAgICAgICAgICAgICAgICAgcHJlID0gZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAg"
    "ICAgICAgICAgICAgICAgIHRbInByZV90cmlnZ2VyIl0gPSBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAg"
    "ICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgbm9ybWFsaXplZC5hcHBlbmQodCkKCiAgICAgICAgaWYg"
    "Y2hhbmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgbm9ybWFsaXplZCkKICAgICAgICByZXR1cm4gbm9y"
    "bWFsaXplZAoKICAgIGRlZiBzYXZlX2FsbChzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICB3cml0ZV9q"
    "c29ubChzZWxmLl9wYXRoLCB0YXNrcykKCiAgICBkZWYgYWRkKHNlbGYsIHRleHQ6IHN0ciwgZHVlX2R0OiBkYXRldGltZSwKICAg"
    "ICAgICAgICAgc291cmNlOiBzdHIgPSAibG9jYWwiKSAtPiBkaWN0OgogICAgICAgIHByZSA9IGR1ZV9kdCAtIHRpbWVkZWx0YSht"
    "aW51dGVzPTEpCiAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmInRhc2tfe3V1aWQudXVp"
    "ZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAg"
    "ICAgImR1ZV9hdCI6ICAgICAgICAgICBkdWVfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJw"
    "cmVfdHJpZ2dlciI6ICAgICAgcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAidGV4dCI6ICAg"
    "ICAgICAgICAgIHRleHQuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAg"
    "ICAgICJhY2tub3dsZWRnZWRfYXQiOiAgTm9uZSwKICAgICAgICAgICAgInJldHJ5X2NvdW50IjogICAgICAwLAogICAgICAgICAg"
    "ICAibGFzdF90cmlnZ2VyZWRfYXQiOk5vbmUsCiAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgTm9uZSwKICAgICAgICAg"
    "ICAgInByZV9hbm5vdW5jZWQiOiAgICBGYWxzZSwKICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICBzb3VyY2UsCiAgICAg"
    "ICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgTm9uZSwKICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAicGVuZGluZyIs"
    "CiAgICAgICAgICAgICJtZXRhZGF0YSI6ICAgICAgICAge30sCiAgICAgICAgfQogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2Fs"
    "bCgpCiAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4g"
    "dGFzawoKICAgIGRlZiB1cGRhdGVfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICBhY2tub3dsZWRnZWQ6IGJvb2wgPSBGYWxzZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxm"
    "LmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoK"
    "ICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdID0gc3RhdHVzCiAgICAgICAgICAgICAgICBpZiBhY2tub3dsZWRnZWQ6CiAgICAg"
    "ICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYu"
    "c2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNvbXBs"
    "ZXRlKHNlbGYsIHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkK"
    "ICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAg"
    "ICAgIHRbInN0YXR1cyJdICAgICAgICAgID0gImNvbXBsZXRlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJd"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0"
    "dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjYW5jZWwoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtk"
    "aWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBp"
    "ZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY2FuY2VsbGVk"
    "IgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNl"
    "bGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNs"
    "ZWFyX2NvbXBsZXRlZChzZWxmKSAtPiBpbnQ6CiAgICAgICAgdGFza3MgICAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBrZXB0"
    "ICAgICA9IFt0IGZvciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICAgICAgaWYgdC5nZXQoInN0YXR1cyIpIG5vdCBpbiB7ImNv"
    "bXBsZXRlZCIsImNhbmNlbGxlZCJ9XQogICAgICAgIHJlbW92ZWQgID0gbGVuKHRhc2tzKSAtIGxlbihrZXB0KQogICAgICAgIGlm"
    "IHJlbW92ZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwoa2VwdCkKICAgICAgICByZXR1cm4gcmVtb3ZlZAoKICAgIGRlZiB1"
    "cGRhdGVfZ29vZ2xlX3N5bmMoc2VsZiwgdGFza19pZDogc3RyLCBzeW5jX3N0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBnb29nbGVfZXZlbnRfaWQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICBlcnJvcjogc3RyID0g"
    "IiIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFz"
    "a3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzeW5jX3N0YXR1cyJd"
    "ICAgID0gc3luY19zdGF0dXMKICAgICAgICAgICAgICAgIHRbImxhc3Rfc3luY2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAg"
    "ICAgICAgICAgICAgIGlmIGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgICAgICAgICB0WyJnb29nbGVfZXZlbnRfaWQiXSA9"
    "IGdvb2dsZV9ldmVudF9pZAogICAgICAgICAgICAgICAgaWYgZXJyb3I6CiAgICAgICAgICAgICAgICAgICAgdC5zZXRkZWZhdWx0"
    "KCJtZXRhZGF0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgIHRbIm1ldGFkYXRhIl1bImdvb2dsZV9zeW5jX2Vycm9yIl0gPSBl"
    "cnJvcls6MjQwXQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKCiAgICAjIOKUgOKUgCBEVUUgRVZFTlQgREVURUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGdldF9kdWVfZXZlbnRzKHNlbGYpIC0+IGxpc3RbdHVw"
    "bGVbc3RyLCBkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sgYWxsIHRhc2tzIGZvciBkdWUvcHJlLXRyaWdnZXIvcmV0"
    "cnkgZXZlbnRzLgogICAgICAgIFJldHVybnMgbGlzdCBvZiAoZXZlbnRfdHlwZSwgdGFzaykgdHVwbGVzLgogICAgICAgIGV2ZW50"
    "X3R5cGU6ICJwcmUiIHwgImR1ZSIgfCAicmV0cnkiCgogICAgICAgIE1vZGlmaWVzIHRhc2sgc3RhdHVzZXMgaW4gcGxhY2UgYW5k"
    "IHNhdmVzLgogICAgICAgIENhbGwgZnJvbSBBUFNjaGVkdWxlciBldmVyeSAzMCBzZWNvbmRzLgogICAgICAgICIiIgogICAgICAg"
    "IG5vdyAgICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgICAgIHRhc2tzICA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIGV2ZW50cyA9IFtdCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAg"
    "ICAgICBpZiB0YXNrLmdldCgiYWNrbm93bGVkZ2VkX2F0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAg"
    "c3RhdHVzICAgPSB0YXNrLmdldCgic3RhdHVzIiwgInBlbmRpbmciKQogICAgICAgICAgICBkdWUgICAgICA9IHNlbGYuX3BhcnNl"
    "X2xvY2FsKHRhc2suZ2V0KCJkdWVfYXQiKSkKICAgICAgICAgICAgcHJlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdl"
    "dCgicHJlX3RyaWdnZXIiKSkKICAgICAgICAgICAgbmV4dF9yZXQgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgibmV4dF9y"
    "ZXRyeV9hdCIpKQogICAgICAgICAgICBkZWFkbGluZSA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJhbGVydF9kZWFkbGlu"
    "ZSIpKQoKICAgICAgICAgICAgIyBQcmUtdHJpZ2dlcgogICAgICAgICAgICBpZiAoc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgcHJl"
    "IGFuZCBub3cgPj0gcHJlCiAgICAgICAgICAgICAgICAgICAgYW5kIG5vdCB0YXNrLmdldCgicHJlX2Fubm91bmNlZCIpKToKICAg"
    "ICAgICAgICAgICAgIHRhc2tbInByZV9hbm5vdW5jZWQiXSA9IFRydWUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJw"
    "cmUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICAjIER1ZSB0cmlnZ2VyCiAgICAg"
    "ICAgICAgIGlmIHN0YXR1cyA9PSAicGVuZGluZyIgYW5kIGR1ZSBhbmQgbm93ID49IGR1ZToKICAgICAgICAgICAgICAgIHRhc2tb"
    "InN0YXR1cyJdICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJd"
    "PSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICA9ICgKICAgICAgICAgICAg"
    "ICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAg"
    "KS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoImR1ZSIsIHRhc2sp"
    "KQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFNu"
    "b296ZSBhZnRlciAzLW1pbnV0ZSB3aW5kb3cKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJ0cmlnZ2VyZWQiIGFuZCBkZWFkbGlu"
    "ZSBhbmQgbm93ID49IGRlYWRsaW5lOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgID0gInNub296ZWQiCiAg"
    "ICAgICAgICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCku"
    "YXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MTIpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0i"
    "c2Vjb25kcyIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICMgUmV0cnkKICAgICAgICAgICAgaWYgc3RhdHVzIGluIHsicmV0cnlfcGVuZGluZyIsInNub296ZWQifSBhbmQgbmV4dF9y"
    "ZXQgYW5kIG5vdyA+PSBuZXh0X3JldDoKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICAgPSAidHJpZ2dl"
    "cmVkIgogICAgICAgICAgICAgICAgdGFza1sicmV0cnlfY291bnQiXSAgICAgICA9IGludCh0YXNrLmdldCgicmV0cnlfY291bnQi"
    "LDApKSArIDEKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAg"
    "ICAgICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICAgPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCku"
    "YXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIikKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSAgICAgPSBOb25lCiAgICAgICAgICAgICAgICBl"
    "dmVudHMuYXBwZW5kKCgicmV0cnkiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgIGlmIGNo"
    "YW5nZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgcmV0dXJuIGV2ZW50cwoKICAgIGRlZiBfcGFy"
    "c2VfbG9jYWwoc2VsZiwgdmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIlBhcnNlIElTTyBzdHJp"
    "bmcgdG8gdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZm9yIGNvbXBhcmlzb24uIiIiCiAgICAgICAgZHQgPSBwYXJzZV9pc28odmFs"
    "dWUpCiAgICAgICAgaWYgZHQgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBkdC50emluZm8gaXMg"
    "Tm9uZToKICAgICAgICAgICAgZHQgPSBkdC5hc3RpbWV6b25lKCkKICAgICAgICByZXR1cm4gZHQKCiAgICAjIOKUgOKUgCBOQVRV"
    "UkFMIExBTkdVQUdFIFBBUlNJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGlj"
    "bWV0aG9kCiAgICBkZWYgY2xhc3NpZnlfaW50ZW50KHRleHQ6IHN0cikgLT4gZGljdDoKICAgICAgICAiIiIKICAgICAgICBDbGFz"
    "c2lmeSB1c2VyIGlucHV0IGFzIHRhc2svcmVtaW5kZXIvdGltZXIvY2hhdC4KICAgICAgICBSZXR1cm5zIHsiaW50ZW50Ijogc3Ry"
    "LCAiY2xlYW5lZF9pbnB1dCI6IHN0cn0KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICAjIFN0cmlwIGNvbW1v"
    "biBpbnZvY2F0aW9uIHByZWZpeGVzCiAgICAgICAgY2xlYW5lZCA9IHJlLnN1YigKICAgICAgICAgICAgcmYiXlxzKig/OntERUNL"
    "X05BTUUubG93ZXIoKX18aGV5XHMre0RFQ0tfTkFNRS5sb3dlcigpfSlccyosP1xzKls6XC1dP1xzKiIsCiAgICAgICAgICAgICIi"
    "LCB0ZXh0LCBmbGFncz1yZS5JCiAgICAgICAgKS5zdHJpcCgpCgogICAgICAgIGxvdyA9IGNsZWFuZWQubG93ZXIoKQoKICAgICAg"
    "ICB0aW1lcl9wYXRzICAgID0gW3IiXGJzZXQoPzpccythKT9ccyt0aW1lclxiIiwgciJcYnRpbWVyXHMrZm9yXGIiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgciJcYnN0YXJ0KD86XHMrYSk/XHMrdGltZXJcYiJdCiAgICAgICAgcmVtaW5kZXJfcGF0cyA9IFty"
    "IlxicmVtaW5kIG1lXGIiLCByIlxic2V0KD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICBy"
    "IlxiYWRkKD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic2V0KD86XHMrYW4/KT9c"
    "cythbGFybVxiIiwgciJcYmFsYXJtXHMrZm9yXGIiXQogICAgICAgIHRhc2tfcGF0cyAgICAgPSBbciJcYmFkZCg/OlxzK2EpP1xz"
    "K3Rhc2tcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxiY3JlYXRlKD86XHMrYSk/XHMrdGFza1xiIiwgciJcYm5ld1xz"
    "K3Rhc2tcYiJdCgogICAgICAgIGltcG9ydCByZSBhcyBfcmUKICAgICAgICBpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBw"
    "IGluIHRpbWVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGltZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChw"
    "LCBsb3cpIGZvciBwIGluIHJlbWluZGVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAicmVtaW5kZXIiCiAgICAgICAgZWxp"
    "ZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRhc2tfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0YXNrIgog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIGludGVudCA9ICJjaGF0IgoKICAgICAgICByZXR1cm4geyJpbnRlbnQiOiBpbnRlbnQs"
    "ICJjbGVhbmVkX2lucHV0IjogY2xlYW5lZH0KCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2VfZHVlX2RhdGV0aW1lKHRl"
    "eHQ6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIgogICAgICAgIFBhcnNlIG5hdHVyYWwgbGFuZ3VhZ2Ug"
    "dGltZSBleHByZXNzaW9uIGZyb20gdGFzayB0ZXh0LgogICAgICAgIEhhbmRsZXM6ICJpbiAzMCBtaW51dGVzIiwgImF0IDNwbSIs"
    "ICJ0b21vcnJvdyBhdCA5YW0iLAogICAgICAgICAgICAgICAgICJpbiAyIGhvdXJzIiwgImF0IDE1OjMwIiwgZXRjLgogICAgICAg"
    "IFJldHVybnMgYSBkYXRldGltZSBvciBOb25lIGlmIHVucGFyc2VhYmxlLgogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQog"
    "ICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3coKQogICAgICAgIGxvdyAgPSB0ZXh0Lmxvd2VyKCkuc3RyaXAoKQoKICAgICAgICAj"
    "ICJpbiBYIG1pbnV0ZXMvaG91cnMvZGF5cyIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImluXHMrKFxkKylc"
    "cyoobWludXRlfG1pbnxob3VyfGhyfGRheXxzZWNvbmR8c2VjKSIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBp"
    "ZiBtOgogICAgICAgICAgICBuICAgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIHVuaXQgPSBtLmdyb3VwKDIpCiAgICAg"
    "ICAgICAgIGlmICJtaW4iIGluIHVuaXQ6ICByZXR1cm4gbm93ICsgdGltZWRlbHRhKG1pbnV0ZXM9bikKICAgICAgICAgICAgaWYg"
    "ImhvdXIiIGluIHVuaXQgb3IgImhyIiBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGhvdXJzPW4pCiAgICAgICAgICAg"
    "IGlmICJkYXkiICBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGRheXM9bikKICAgICAgICAgICAgaWYgInNlYyIgIGlu"
    "IHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoc2Vjb25kcz1uKQoKICAgICAgICAjICJhdCBISDpNTSIgb3IgImF0IEg6TU1h"
    "bS9wbSIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImF0XHMrKFxkezEsMn0pKD86OihcZHsyfSkpP1xzKihh"
    "bXxwbSk/IiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIGhyICA9IGludChtLmdy"
    "b3VwKDEpKQogICAgICAgICAgICBtbiAgPSBpbnQobS5ncm91cCgyKSkgaWYgbS5ncm91cCgyKSBlbHNlIDAKICAgICAgICAgICAg"
    "YXBtID0gbS5ncm91cCgzKQogICAgICAgICAgICBpZiBhcG0gPT0gInBtIiBhbmQgaHIgPCAxMjogaHIgKz0gMTIKICAgICAgICAg"
    "ICAgaWYgYXBtID09ICJhbSIgYW5kIGhyID09IDEyOiBociA9IDAKICAgICAgICAgICAgZHQgPSBub3cucmVwbGFjZShob3VyPWhy"
    "LCBtaW51dGU9bW4sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKQogICAgICAgICAgICBpZiBkdCA8PSBub3c6CiAgICAgICAgICAg"
    "ICAgICBkdCArPSB0aW1lZGVsdGEoZGF5cz0xKQogICAgICAgICAgICByZXR1cm4gZHQKCiAgICAgICAgIyAidG9tb3Jyb3cgYXQg"
    "Li4uIiAgKHJlY3Vyc2Ugb24gdGhlICJhdCIgcGFydCkKICAgICAgICBpZiAidG9tb3Jyb3ciIGluIGxvdzoKICAgICAgICAgICAg"
    "dG9tb3Jyb3dfdGV4dCA9IHJlLnN1YihyInRvbW9ycm93IiwgIiIsIGxvdykuc3RyaXAoKQogICAgICAgICAgICByZXN1bHQgPSBU"
    "YXNrTWFuYWdlci5wYXJzZV9kdWVfZGF0ZXRpbWUodG9tb3Jyb3dfdGV4dCkKICAgICAgICAgICAgaWYgcmVzdWx0OgogICAgICAg"
    "ICAgICAgICAgcmV0dXJuIHJlc3VsdCArIHRpbWVkZWx0YShkYXlzPTEpCgogICAgICAgIHJldHVybiBOb25lCgoKIyDilIDilIAg"
    "UkVRVUlSRU1FTlRTLlRYVCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkgLT4gTm9uZToKICAgICIiIgogICAgV3Jp"
    "dGUgcmVxdWlyZW1lbnRzLnR4dCBuZXh0IHRvIHRoZSBkZWNrIGZpbGUgb24gZmlyc3QgcnVuLgogICAgSGVscHMgdXNlcnMgaW5z"
    "dGFsbCBhbGwgZGVwZW5kZW5jaWVzIHdpdGggb25lIHBpcCBjb21tYW5kLgogICAgIiIiCiAgICByZXFfcGF0aCA9IFBhdGgoQ0ZH"
    "LmdldCgiYmFzZV9kaXIiLCBzdHIoU0NSSVBUX0RJUikpKSAvICJyZXF1aXJlbWVudHMudHh0IgogICAgaWYgcmVxX3BhdGguZXhp"
    "c3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgY29udGVudCA9ICIiIlwKIyBNb3JnYW5uYSBEZWNrIOKAlCBSZXF1aXJlZCBEZXBl"
    "bmRlbmNpZXMKIyBJbnN0YWxsIGFsbCB3aXRoOiBwaXAgaW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0CgojIENvcmUgVUkKUHlT"
    "aWRlNgoKIyBTY2hlZHVsaW5nIChpZGxlIHRpbWVyLCBhdXRvc2F2ZSwgcmVmbGVjdGlvbiBjeWNsZXMpCmFwc2NoZWR1bGVyCgoj"
    "IExvZ2dpbmcKbG9ndXJ1CgojIFNvdW5kIHBsYXliYWNrIChXQVYgKyBNUDMpCnB5Z2FtZQoKIyBEZXNrdG9wIHNob3J0Y3V0IGNy"
    "ZWF0aW9uIChXaW5kb3dzIG9ubHkpCnB5d2luMzIKCiMgU3lzdGVtIG1vbml0b3JpbmcgKENQVSwgUkFNLCBkcml2ZXMsIG5ldHdv"
    "cmspCnBzdXRpbAoKIyBIVFRQIHJlcXVlc3RzCnJlcXVlc3RzCgojIEdvb2dsZSBpbnRlZ3JhdGlvbiAoQ2FsZW5kYXIsIERyaXZl"
    "LCBEb2NzLCBHbWFpbCkKZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Cmdvb2dsZS1hdXRoLW9hdXRobGliCmdvb2dsZS1hdXRoCgoj"
    "IOKUgOKUgCBPcHRpb25hbCAobG9jYWwgbW9kZWwgb25seSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHVzaW5nIGEgbG9jYWwgSHVnZ2luZ0ZhY2UgbW9kZWw6CiMg"
    "dG9yY2gKIyB0cmFuc2Zvcm1lcnMKIyBhY2NlbGVyYXRlCgojIOKUgOKUgCBPcHRpb25hbCAoTlZJRElBIEdQVSBtb25pdG9yaW5n"
    "KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgeW91IGhhdmUgYW4g"
    "TlZJRElBIEdQVToKIyBweW52bWwKIiIiCiAgICByZXFfcGF0aC53cml0ZV90ZXh0KGNvbnRlbnQsIGVuY29kaW5nPSJ1dGYtOCIp"
    "CgoKIyDilIDilIAgUEFTUyA0IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1lbW9yeSwgU2Vzc2lvbiwg"
    "TGVzc29uc0xlYXJuZWQsIFRhc2tNYW5hZ2VyIGFsbCBkZWZpbmVkLgojIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhdXRvLXNlZWRl"
    "ZCBvbiBmaXJzdCBydW4uCiMgcmVxdWlyZW1lbnRzLnR4dCB3cml0dGVuIG9uIGZpcnN0IHJ1bi4KIwojIE5leHQ6IFBhc3MgNSDi"
    "gJQgVGFiIENvbnRlbnQgQ2xhc3NlcwojIChTTFNjYW5zVGFiLCBTTENvbW1hbmRzVGFiLCBKb2JUcmFja2VyVGFiLCBSZWNvcmRz"
    "VGFiLAojICBUYXNrc1RhYiwgU2VsZlRhYiwgRGlhZ25vc3RpY3NUYWIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNL"
    "IOKAlCBQQVNTIDU6IFRBQiBDT05URU5UIENMQVNTRVMKIwojIFRhYnMgZGVmaW5lZCBoZXJlOgojICAgU0xTY2Fuc1RhYiAgICAg"
    "IOKAlCBncmltb2lyZS1jYXJkIHN0eWxlLCByZWJ1aWx0IChEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwKIyAgICAgICAgICAg"
    "ICAgICAgICAgIHBhcnNlciBmaXhlZCwgY29weS10by1jbGlwYm9hcmQgcGVyIGl0ZW0pCiMgICBTTENvbW1hbmRzVGFiICAg4oCU"
    "IGdvdGhpYyB0YWJsZSwgY29weSBjb21tYW5kIHRvIGNsaXBib2FyZAojICAgSm9iVHJhY2tlclRhYiAgIOKAlCBmdWxsIHJlYnVp"
    "bGQgZnJvbSBzcGVjLCBDU1YvVFNWIGV4cG9ydAojICAgUmVjb3Jkc1RhYiAgICAgIOKAlCBHb29nbGUgRHJpdmUvRG9jcyB3b3Jr"
    "c3BhY2UKIyAgIFRhc2tzVGFiICAgICAgICDigJQgdGFzayByZWdpc3RyeSArIG1pbmkgY2FsZW5kYXIKIyAgIFNlbGZUYWIgICAg"
    "ICAgICDigJQgaWRsZSBuYXJyYXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1IG91"
    "dHB1dCArIGhhcmR3YXJlIHJlcG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMgICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBG"
    "b3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMgX3JlCgoK"
    "IyDilIDilIAgU0hBUkVEIEdPVEhJQyBUQUJMRSBTVFlMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAtPiBzdHI6CiAgICByZXR1"
    "cm4gZiIiIgogICAgICAgIFFUYWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgICAgICAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAg"
    "ICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "CiAgICAgICAgICAgIGZvbnQtc2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3Rl"
    "ZCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JS"
    "SUdIVH07CiAgICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tn"
    "cm91bmQ6IHtDX0JHM307CiAgICAgICAgfX0KICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9s"
    "ZDsKICAgICAgICAgICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4"
    "dDogc3RyLCB0b29sdGlwOiBzdHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQogICAg"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19HT0xEfTsg"
    "IgogICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYi"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDog"
    "Ym9sZDsgcGFkZGluZzogNHB4IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAgICAg"
    "ICBidG4uc2V0VG9vbFRpcCh0b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFM"
    "YWJlbDoKICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMgVEFC"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBTZWNvbmQgTGlmZSBhdmF0YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZyb20gc3BlYzoKICAgICAg"
    "LSBDYXJkL2dyaW1vaXJlLWVudHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGltZXN0YW1wLWF3YXJlIHBhcnNl"
    "cikKICAgICAgLSBEaXNwbGF5IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRl"
    "c2NyaXB0aW9uLCBpbmRpdmlkdWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQog"
    "ICAgICAtIFJlLXBhcnNlICh3YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAg"
    "IC0gQ29weS10by1jbGlwYm9hcmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGly"
    "OiBQYXRoLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAg"
    "ICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBb"
    "XQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkK"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5f"
    "YnRuX2FkZCAgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAgICAgIHNlbGYuX2J0"
    "bl9kaXNwbGF5ID0gX2dvdGhpY19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBkZXRhaWxzIikKICAgICAg"
    "ICBzZWxmLl9idG5fbW9kaWZ5ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAg"
    "ICAgIHNlbGYuX2J0bl9kZWxldGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikK"
    "ICAgICAgICBzZWxmLl9idG5fcmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4dCBv"
    "ZiBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAg"
    "ICAgICBzZWxmLl9idG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0"
    "bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fcmVwYXJzZSkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYuX2J0bl9t"
    "b2RpZnksCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAg"
    "YmFyLmFkZFdpZGdldChiKQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAg"
    "ICAgICMgU3RhY2s6IGxpc3QgdmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAgIHNlbGYuX3N0YWNrID0g"
    "UVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoKICAgICAgICAjIOKUgOKUgCBQ"
    "QUdFIDA6IHNjYW4gbGlzdCAoZ3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExh"
    "eW91dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9s"
    "bCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAg"
    "ICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAg"
    "ICAgICAgc2VsZi5fY2FyZF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94"
    "TGF5b3V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAg"
    "ICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2NhcmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAg"
    "ICAgICAgIyDilIDilIAgUEFHRSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBTQ0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0gUUxp"
    "bmVFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2Fu"
    "IHRleHQiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25f"
    "bGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYu"
    "X2FkZF9kZXNjLnNldE1heGltdW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAgICAg"
    "IGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAgIHNlbGYu"
    "X2FkZF9yYXcgICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAg"
    "ICAgICJQYXN0ZSB0aGUgcmF3IFNlY29uZCBMaWZlIHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBz"
    "IGxpa2UgWzExOjQ3XSB3aWxsIGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAgICApCiAgICAgICAgbDEu"
    "YWRkV2lkZ2V0KHNlbGYuX2FkZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBpdGVtcwogICAgICAgIGwxLmFk"
    "ZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhb"
    "Ikl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Fk"
    "ZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZp"
    "ZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAg"
    "ICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdp"
    "ZGdldChzZWxmLl9hZGRfcHJldmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fcHJl"
    "dmlld19wYXJzZSkKCiAgICAgICAgYnRuczEgPSBRSEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNh"
    "dmUiKTsgYzEgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2Fk"
    "ZCkKICAgICAgICBjMS5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAg"
    "ICAgYnRuczEuYWRkV2lkZ2V0KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRjaCgpCiAgICAgICAgbDEu"
    "YWRkTGF5b3V0KGJ0bnMxKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAy"
    "OiBkaXNwbGF5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAy"
    "ID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2Rpc3BfZGVzYyAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVlKQogICAg"
    "ICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3Bf"
    "dGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJl"
    "bHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYu"
    "X2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFi"
    "bGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5D"
    "b250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRN"
    "ZW51UmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRX"
    "aWRnZXQoc2VsZi5fZGlzcF9uYW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KHNlbGYuX2Rpc3BfdGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55IGl0"
    "ZW0gdG8gY29weSBpdCB0byBjbGlwYm9hcmQuIikKICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAg"
    "ICAgICAgKQogICAgICAgIGwyLmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNfYnRuKCLil4AgQmFj"
    "ayIpCiAgICAgICAgYmsyLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAg"
    "ICAgICBsMi5hZGRXaWRnZXQoYmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAg"
    "UEFHRSAzOiBtb2RpZnkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFy"
    "Z2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgTkFNRSIpKQogICAgICAgIHNlbGYuX21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2Vs"
    "Zi5fbW9kX25hbWUpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAg"
    "c2VsZi5fbW9kX2Rlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAgICAgICBs"
    "My5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSVRFTVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYu"
    "X21vZF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVy"
    "TGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNl"
    "bGYuX21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3Rh"
    "YmxlX3N0eWxlKCkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgczMgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNl"
    "bCIpCiAgICAgICAgczMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29u"
    "bmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBi"
    "dG5zMy5hZGRXaWRnZXQoYzMpOyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAg"
    "c2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0"
    "aWNtZXRob2QKICAgIGRlZiBwYXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAgICAg"
    "ICAgIiIiCiAgICAgICAgUGFyc2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBpdGVtcykuCgogICAgICAg"
    "IEtFWSBGSVg6IEJlZm9yZSBzcGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRp"
    "bWVzdGFtcCBzbyBzaW5nbGUtbGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAg"
    "ICAgICAgICAgWzExOjQ3XSBBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46IEl0"
    "ZW0gTmFtZSBbQXR0YWNobWVudF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3XSAuLi4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiBub3QgcmF3LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9XTiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAg"
    "MTogbm9ybWFsaXplIOKAlCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbm9ybWFsaXplZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAgIGxp"
    "bmVzID0gW2wuc3RyaXAoKSBmb3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAgICAgICMg"
    "4pSA4pSAIFN0ZXAgMjogZXh0cmFjdCBhdmF0YXIgbmFtZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFt"
    "ZSA9ICJVTktOT1dOIgogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0YXJOYW1lJ3MgcHVibGlj"
    "IGF0dGFjaG1lbnRzIiBvciBzaW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgciIoXHdb"
    "XHdcc10rPyknc1xzK3B1YmxpY1xzK2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAg"
    "ICAgICAgICAgICBicmVhawoKICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAg"
    "ICAgICAjIFN0cmlwIGxlYWRpbmcgdGltZXN0YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpc"
    "ZHsyfVxdXHMqJywgJycsIGxpbmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgICAgICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNobWVu"
    "dHMiIGluIGNvbnRlbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93"
    "ZXIoKS5zdGFydHN3aXRoKCJvYmplY3QiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZp"
    "ZGVyIGxpbmVzIOKAlCBsaW5lcyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAgICAgICAgICAjIGUu"
    "Zy4g4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkCBvciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50"
    "LnN0cmlwKCIuOiAiKQogICAgICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZSAgIyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAgIyBU"
    "cnkgdG8gZXh0cmFjdCBDUkVBVE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9yID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0"
    "ZW1fbmFtZSA9IGNvbnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2ggPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAg"
    "cidDUkVBVE9SOlxzKihbXHdcc10rPykoPzpccypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgaWYgY3JlYXRvcl9tYXRjaDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSkuc3Ry"
    "aXAoKQogICAgICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJpcCgpCgog"
    "ICAgICAgICAgICAjIFN0cmlwIGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBp"
    "dGVtX25hbWUgPSBfcmUuc3ViKHInXHMqXFtbXHdcc19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBp"
    "dGVtX25hbWUgPSBpdGVtX25hbWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUgYW5kIGxlbihpdGVtX25h"
    "bWUpID4gMToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUsICJjcmVhdG9yIjogY3JlYXRv"
    "cn0pCgogICAgICAgIHJldHVybiBhdmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVp"
    "bGRfY2FyZHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAg"
    "ICAgd2hpbGUgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91"
    "dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVs"
    "ZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtl"
    "X2NhcmQocmVjKQogICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9jYXJkX2xheW91dC5jb3VudCgpIC0gMSwgY2FyZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVj"
    "OiBkaWN0KSAtPiBRV2lkZ2V0OgogICAgICAgIGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgi"
    "cmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDogeycjMWEwYTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXIt"
    "cmFkaXVzOiAycHg7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAg"
    "ICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChyZWMu"
    "Z2V0KCJuYW1lIiwgIlVOS05PV04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19HT0xEX0JSSUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDEx"
    "cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAg"
    "IGNvdW50ID0gbGVuKHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0gaXRl"
    "bXMiKQogICAgICAgIGNvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9u"
    "dC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJs"
    "ID0gUUxhYmVsKHJlYy5nZXQoImNyZWF0ZWRfYXQiLCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFN0"
    "cmV0Y2goKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lk"
    "ID0gcmVjLmdldCgicmVjb3JkX2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJl"
    "Y19pZDogc2VsZi5fc2VsZWN0X2NhcmQocmlkKQogICAgICAgIHJldHVybiBjYXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxm"
    "LCByZWNvcmRfaWQ6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNl"
    "bGYuX2J1aWxkX2NhcmRzKCkgICMgUmVidWlsZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVk"
    "X3JlY29yZChzZWxmKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIg"
    "aW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkKSwK"
    "ICAgICAgICAgICAgTm9uZQogICAgICAgICkKCiAgICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHJl"
    "ZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAg"
    "ICMgRW5zdXJlIHJlY29yZF9pZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBz"
    "ZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVj"
    "b3JkX2lkIl0gPSByLmdldCgiaWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUK"
    "ICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAg"
    "ICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3By"
    "ZXZpZXdfcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAg"
    "ICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhv"
    "bGRlclRleHQobmFtZSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiBp"
    "dGVtc1s6MjBdOiAgIyBwcmV2aWV3IGZpcnN0IDIwCiAgICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgp"
    "CiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5z"
    "ZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNl"
    "dEl0ZW0ociwgMSwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3Nob3dfYWRkKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fYWRkX25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNl"
    "bGYuX2FkZF9yYXcuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5f"
    "c3RhY2suc2V0Q3VycmVudEluZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2Vs"
    "Zi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAg"
    "ICAgICAgb3ZlcnJpZGVfbmFtZSA9IHNlbGYuX2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1l"
    "Lm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAg"
    "ICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICJuYW1lIjogICAgICAgIG92ZXJyaWRlX25hbWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5f"
    "YWRkX2Rlc2MudG9QbGFpblRleHQoKVs6MjQ0XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAg"
    "ICJyYXdfdGV4dCI6ICAgIHJhdywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9h"
    "dCI6ICBub3csCiAgICAgICAgfQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQi"
    "XQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMg"
    "PSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9y"
    "bWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2Fu"
    "IHRvIGRpc3BsYXkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3Jl"
    "Yy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwi"
    "IikpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVt"
    "cyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2Rpc3Bf"
    "dGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRl"
    "bShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0X21lbnUoc2VsZiwgcG9zKSAt"
    "PiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1Zh"
    "bGlkKCk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5y"
    "b3coKSwgMCkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVh"
    "dG9yICAgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDEpIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFi"
    "bGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAg"
    "ICBtZW51ID0gUU1lbnUoc2VsZikKICAgICAgICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19"
    "OyIKICAgICAgICApCiAgICAgICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAgICBh"
    "X2NyZWF0b3IgPSBtZW51LmFkZEFjdGlvbigiQ29weSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlv"
    "bigiQ29weSBCb3RoIikKICAgICAgICBhY3Rpb24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRv"
    "R2xvYmFsKHBvcykpCiAgICAgICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBhY3Rpb24gPT0gYV9p"
    "dGVtOiAgICBjYi5zZXRUZXh0KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0b3I6IGNiLnNldFRleHQo"
    "Y3JlYXRvcikKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVh"
    "dG9yfSIpCgogICAgZGVmIF9zaG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3Jl"
    "Y29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNj"
    "YW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQocmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNl"
    "bGYuX21vZF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX21v"
    "ZF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2Vs"
    "Zi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwi"
    "IikpKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0"
    "SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgzKQoK"
    "ICAgIGRlZiBfZG9fbW9kaWZ5X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQo"
    "KQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYu"
    "X21vZF9uYW1lLnRleHQoKS5zdHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21v"
    "ZF9kZXNjLnRleHQoKVs6MjQ0XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFi"
    "bGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdl"
    "dEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lk"
    "Z2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9X"
    "TiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAg"
    "cmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25l"
    "LnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3Rl"
    "ZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJT"
    "TCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRlbGV0ZS4iKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkg"
    "PSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxl"
    "dGUgJ3tuYW1lfSc/IFRoaXMgY2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2Fn"
    "ZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNv"
    "cmRzCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lk"
    "XQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9zZWxl"
    "Y3RlZF9pZCA9IE5vbmUKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFN"
    "ZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJTZWxlY3QgYSBzY2FuIHRvIHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJhdyA9IHJlYy5nZXQoInJh"
    "d190ZXh0IiwiIikKICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAi"
    "UmUtcGFyc2UiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlz"
    "IHNjYW4uIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcp"
    "CiAgICAgICAgcmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0g"
    "b3IgbmFtZQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkK"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAg"
    "ICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJGb3VuZCB7bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIFNMQ29tbWFuZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQg"
    "cmVmZXJlbmNlIHRhYmxlLgogICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQgYnV0dG9u"
    "IHBlciByb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNl"
    "bGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFk"
    "ZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5f"
    "ZGVsZXRlID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0bigi"
    "4qeJIENvcHkgQ29tbWFuZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxlY3RlZCBj"
    "b21tYW5kIHRvIGNsaXBib2FyZCIpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2Rp"
    "ZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2NvcHlfY29tbWFu"
    "ZCkKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGlu"
    "IChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9idG5fY29weSwgc2VsZi5fYnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQo"
    "MCwgMikKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlv"
    "biJdKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAg"
    "ICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIo"
    "KS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rp"
    "b25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fdGFibGUsIDEpCgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxlY3QgYSByb3cgYW5kIGNs"
    "aWNrIOKniSBDb3B5IENvbW1hbmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRlZiBy"
    "ZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAg"
    "ciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAg"
    "IHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29tbWFu"
    "ZCIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0"
    "SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKSkKCiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGl0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBRQXBwbGlj"
    "YXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBk"
    "bGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBR"
    "Rm9ybUxheW91dChkbGcpCiAgICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3Jt"
    "LmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAg"
    "YnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNh"
    "bmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVj"
    "dCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMp"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9IGRh"
    "dGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJp"
    "ZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5z"
    "dHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAg"
    "ICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAgICAgIH0KICAgICAgICAg"
    "ICAgaWYgcmVjWyJjb21tYW5kIl06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAg"
    "ICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX2RvX21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQog"
    "ICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "cmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dU"
    "aXRsZSgiTW9kaWZ5IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29s"
    "b3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KHJl"
    "Yy5nZXQoImNvbW1hbmQiLCIiKSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAg"
    "ICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNj"
    "KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3Ro"
    "aWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFk"
    "ZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAg"
    "ICByZWNbImNvbW1hbmQiXSAgICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlv"
    "biJdID0gZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5u"
    "b3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "cm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29y"
    "ZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhp"
    "cyBjb21tYW5kIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRl"
    "IiwgZiJEZWxldGUgJ3tjbWR9Jz8iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2Fn"
    "ZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1"
    "dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5f"
    "cGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBKT0IgVFJBQ0tFUiBUQUIg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpvYiBh"
    "cHBsaWNhdGlvbiB0cmFja2luZy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAgIEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxl"
    "LCBEYXRlIEFwcGxpZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBD"
    "U1YgYW5kIFRTViBleHBvcnQuCiAgICBIaWRkZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBq"
    "dXN0IG5vdCBzaG93bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBwbGll"
    "ZCIsCiAgICAgICAgICAgICAgICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgo"
    "Im1lbW9yaWVzIikgLyAiam9iX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAg"
    "ICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAg"
    "IHNlbGYuX2J0bl9tb2RpZnkgPSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhp"
    "Y19idG4oIkFyY2hpdmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMg"
    "Y29tcGxldGVkL3JlamVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5oaWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAg"
    "ICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3Ro"
    "aWNfYnRuKCJTaG93IEFyY2hpdmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIpCgog"
    "ICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3Rv"
    "Z2dsZSwgc2VsZi5fYnRuX2V4cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAgICAgICAgICBiLnNl"
    "dE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X21vZGlmeSkKICAgICAgICBzZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxm"
    "Ll9idG5fdW5oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X3RvZ2dsZV9oaWRkZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQog"
    "ICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0g"
    "UVRhYmxlV2lkZ2V0KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJM"
    "YWJlbHMoc2VsZi5DT0xVTU5TKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgIyBD"
    "b21wYW55IGFuZCBKb2IgVGl0bGUgc3RyZXRjaAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRoCiAgICAgICAgaGguc2V0"
    "U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRD"
    "b2x1bW5XaWR0aCgyLCAxMDApCiAgICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KDMsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAg"
    "ICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldENvbHVtbldpZHRoKDQsIDgwKQogICAgICAgICMgTm90ZXMgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoNSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rp"
    "b25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25N"
    "b2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fdGFibGUsIDEpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0g"
    "cmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBp"
    "biBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIsIEZhbHNlKSkKICAgICAg"
    "ICAgICAgaWYgaGlkZGVuIGFuZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "ICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAg"
    "ICAgICAgc3RhdHVzID0gIkFyY2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAgICAg"
    "ICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAg"
    "ICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5v"
    "dGVzIiwiIiksCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAgICAg"
    "ICAgICAgaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAgICAgICAg"
    "ICAgICAgICAgIGl0ZW0uc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRJdGVtKHIsIGMsIGl0ZW0pCiAgICAgICAgICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVz"
    "ZXIgZGF0YQogICAgICAgICAgICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAgICAgICAgICBRdC5JdGVt"
    "RGF0YVJvbGUuVXNlclJvbGUsCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJlYykKICAgICAgICAgICAgKQoK"
    "ICAgIGRlZiBfc2VsZWN0ZWRfaW5kaWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAg"
    "ICAgZm9yIGl0ZW0gaW4gc2VsZi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3Rh"
    "YmxlLml0ZW0oaXRlbS5yb3coKSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSByb3df"
    "aXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgICAgICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAgcmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBf"
    "ZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNl"
    "bGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0"
    "KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkKICAg"
    "ICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQoKICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnki"
    "LCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlm"
    "IHJlYyBlbHNlICIiKQogICAgICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVuZGFyUG9wdXAoVHJ1"
    "ZSkKICAgICAgICBkZS5zZXREaXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMgYW5kIHJlYy5nZXQoImRh"
    "dGVfYXBwbGllZCIpOgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwi"
    "eXl5eS1NTS1kZCIpKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAg"
    "ICAgICBsaW5rICAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0dXMg"
    "ID0gUUxpbmVFZGl0KHJlYy5nZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMgZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90"
    "ZXMgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdp"
    "ZGdldCBpbiBbCiAgICAgICAgICAgICgiQ29tcGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAg"
    "ICAgICAoIkRhdGUgQXBwbGllZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVz"
    "KSwgKCJOb3RlczoiLCBub3RlcyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdldCkKCiAg"
    "ICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19i"
    "dG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxn"
    "LnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93"
    "KGJ0bnMpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBy"
    "ZXR1cm4gewogICAgICAgICAgICAgICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAg"
    "ICAgICAiam9iX3RpdGxlIjogICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjog"
    "ZGUuZGF0ZSgpLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50ZXh0"
    "KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICBzdGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxp"
    "ZWQiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2co"
    "KQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1aWQu"
    "dXVpZDQoKSksCiAgICAgICAgICAgICJoaWRkZW4iOiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUi"
    "OiBOb25lLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5v"
    "dywKICAgICAgICB9KQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0"
    "aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIlNlbGVjdCBleGFjdGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9"
    "IHNlbGYuX3JlY29yZHNbaWR4c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFsb2cocmVjKQogICAgICAgIGlmIG5vdCBwOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGlt"
    "ZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4"
    "IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fcmVjb3Jkc1tpZHhdWyJjb21wbGV0ZWRfZGF0ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4"
    "XS5nZXQoImNvbXBsZXRlZF9kYXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5kYXRlKCkuaXNvZm9y"
    "bWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0g"
    "KAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fdW5oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2Vz"
    "KCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNb"
    "aWR4XVsiaGlkZGVuIl0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJd"
    "ID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMo"
    "KQogICAgICAgIGlmIG5vdCBpZHhzOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0"
    "aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQg"
    "YXBwbGljYXRpb24ocyk/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "WWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VC"
    "b3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "cyA9IFtyIGZvciBpLCByIGluIGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IGkgbm90IGluIGJhZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAg"
    "ICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93"
    "X2hpZGRlbiA9IG5vdCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAg"
    "ICAgIuKYgCBIaWRlIEFyY2hpdmVkIiBpZiBzZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgs"
    "IGZpbHQgPSBRRmlsZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRyYWNrZXIi"
    "LAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImV4cG9ydHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNT"
    "ViBGaWxlcyAoKi5jc3YpOztUYWIgRGVsaW1pdGVkICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRoKCIudHh0IikgZWxzZSAi"
    "LCIKICAgICAgICBoZWFkZXIgPSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQiLCJsaW5rIiwKICAgICAgICAg"
    "ICAgICAgICAgInN0YXR1cyIsImhpZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRo"
    "LCAidyIsIGVuY29kaW5nPSJ1dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbiho"
    "ZWFkZXIpICsgIlxuIikKICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFscyA9"
    "IFsKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgi"
    "am9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAg"
    "ICAgICAgICAgICAgICAgIHN0cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgiY29tcGxldGVkX2RhdGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAog"
    "ICAgICAgICAgICAgICAgXQogICAgICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0"
    "cih2KS5yZXBsYWNlKCJcbiIsIiAiKS5yZXBsYWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxz"
    "CiAgICAgICAgICAgICAgICApICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0ZWQi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKUgOKUgCBTRUxGIFRBQiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgUmVjb3Jkc1RhYihRV2lkZ2V0KToK"
    "ICAgICIiIkdvb2dsZSBEcml2ZS9Eb2NzIHJlY29yZHMgYnJvd3NlciB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBh"
    "cmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiUmVjb3JkcyBhcmUgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBz"
    "ZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBzZWxmLnBhdGhfbGFiZWwgPSBRTGFiZWwoIlBhdGg6IE15IERyaXZlIikKICAg"
    "ICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLnBhdGhfbGFiZWwpCgogICAgICAgIHNlbGYucmVjb3Jkc19saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNl"
    "bGYucmVjb3Jkc19saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtD"
    "X0dPTER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5yZWNvcmRzX2xpc3QsIDEpCgogICAgZGVmIHNldF9pdGVtcyhzZWxmLCBmaWxlczogbGlzdFtkaWN0XSwgcGF0aF90ZXh0OiBz"
    "dHIgPSAiTXkgRHJpdmUiKSAtPiBOb25lOgogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRUZXh0KGYiUGF0aDoge3BhdGhfdGV4"
    "dH0iKQogICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmNsZWFyKCkKICAgICAgICBmb3IgZmlsZV9pbmZvIGluIGZpbGVzOgogICAg"
    "ICAgICAgICB0aXRsZSA9IChmaWxlX2luZm8uZ2V0KCJuYW1lIikgb3IgIlVudGl0bGVkIikuc3RyaXAoKSBvciAiVW50aXRsZWQi"
    "CiAgICAgICAgICAgIG1pbWUgPSAoZmlsZV9pbmZvLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBp"
    "ZiBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLw"
    "n5OBIgogICAgICAgICAgICBlbGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCI6CiAgICAg"
    "ICAgICAgICAgICBwcmVmaXggPSAi8J+TnSIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OE"
    "IgogICAgICAgICAgICBtb2RpZmllZCA9IChmaWxlX2luZm8uZ2V0KCJtb2RpZmllZFRpbWUiKSBvciAiIikucmVwbGFjZSgiVCIs"
    "ICIgIikucmVwbGFjZSgiWiIsICIgVVRDIikKICAgICAgICAgICAgdGV4dCA9IGYie3ByZWZpeH0ge3RpdGxlfSIgKyAoZiIgICAg"
    "W3ttb2RpZmllZH1dIiBpZiBtb2RpZmllZCBlbHNlICIiKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKHRleHQp"
    "CiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGZpbGVfaW5mbykKICAgICAgICAgICAg"
    "c2VsZi5yZWNvcmRzX2xpc3QuYWRkSXRlbShpdGVtKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJMb2FkZWQg"
    "e2xlbihmaWxlcyl9IEdvb2dsZSBEcml2ZSBpdGVtKHMpLiIpCgoKY2xhc3MgVGFza3NUYWIoUVdpZGdldCk6CiAgICAiIiJUYXNr"
    "IHJlZ2lzdHJ5ICsgR29vZ2xlLWZpcnN0IGVkaXRvciB3b3JrZmxvdyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAg"
    "IHNlbGYsCiAgICAgICAgdGFza3NfcHJvdmlkZXIsCiAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuLAogICAgICAgIG9uX2NvbXBs"
    "ZXRlX3NlbGVjdGVkLAogICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZCwKICAgICAgICBvbl90b2dnbGVfY29tcGxldGVkLAogICAg"
    "ICAgIG9uX3B1cmdlX2NvbXBsZXRlZCwKICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZCwKICAgICAgICBvbl9lZGl0b3Jfc2F2ZSwK"
    "ICAgICAgICBvbl9lZGl0b3JfY2FuY2VsLAogICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lLAogICAgICAgIHBhcmVudD1O"
    "b25lLAogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl90YXNrc19wcm92aWRlciA9"
    "IHRhc2tzX3Byb3ZpZGVyCiAgICAgICAgc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuID0gb25fYWRkX2VkaXRvcl9vcGVuCiAgICAg"
    "ICAgc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQgPSBvbl9jb21wbGV0ZV9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX2NhbmNl"
    "bF9zZWxlY3RlZCA9IG9uX2NhbmNlbF9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQgPSBvbl90b2dn"
    "bGVfY29tcGxldGVkCiAgICAgICAgc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkID0gb25fcHVyZ2VfY29tcGxldGVkCiAgICAgICAg"
    "c2VsZi5fb25fZmlsdGVyX2NoYW5nZWQgPSBvbl9maWx0ZXJfY2hhbmdlZAogICAgICAgIHNlbGYuX29uX2VkaXRvcl9zYXZlID0g"
    "b25fZWRpdG9yX3NhdmUKICAgICAgICBzZWxmLl9vbl9lZGl0b3JfY2FuY2VsID0gb25fZWRpdG9yX2NhbmNlbAogICAgICAgIHNl"
    "bGYuX2RpYWdfbG9nZ2VyID0gZGlhZ25vc3RpY3NfbG9nZ2VyCiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQgPSBGYWxzZQog"
    "ICAgICAgIHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICBkZWYgX2J1aWxk"
    "X3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50"
    "c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFj"
    "ayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLndvcmtzcGFjZV9zdGFjaywgMSkKCiAgICAg"
    "ICAgbm9ybWFsID0gUVdpZGdldCgpCiAgICAgICAgbm9ybWFsX2xheW91dCA9IFFWQm94TGF5b3V0KG5vcm1hbCkKICAgICAgICBu"
    "b3JtYWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0U3BhY2lu"
    "Zyg0KQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiVGFzayByZWdpc3RyeSBpcyBub3QgbG9hZGVkIHlldC4i"
    "KQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgbm9y"
    "bWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREFURSBSQU5HRSIpKQogICAgICAgIHNlbGYu"
    "dGFza19maWx0ZXJfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiV0VF"
    "SyIsICJ3ZWVrIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk1PTlRIIiwgIm1vbnRoIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk5FWFQgMyBNT05USFMiLCAibmV4dF8zX21vbnRocyIpCiAgICAgICAg"
    "c2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJZRUFSIiwgInllYXIiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29t"
    "Ym8uc2V0Q3VycmVudEluZGV4KDIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNv"
    "bm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBfOiBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZChzZWxmLnRhc2tfZmlsdGVyX2NvbWJv"
    "LmN1cnJlbnREYXRhKCkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgICkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChz"
    "ZWxmLnRhc2tfZmlsdGVyX2NvbWJvKQogICAgICAgIGZpbHRlcl9yb3cuYWRkU3RyZXRjaCgxKQogICAgICAgIG5vcm1hbF9sYXlv"
    "dXQuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIHNlbGYudGFza190YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiU3RhdHVzIiwgIkR1ZSIsICJUYXNrIiwgIlNv"
    "dXJjZSJdKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxl"
    "Y3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKFFBYnN0cmFj"
    "dEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEVkaXRU"
    "cmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmlnZ2VycykKICAgICAgICBzZWxmLnRhc2tfdGFi"
    "bGUudmVydGljYWxIZWFkZXIoKS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVh"
    "ZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcu"
    "UmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0"
    "U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVU"
    "b0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAg"
    "ICAgICBzZWxmLnRhc2tfdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRv"
    "bl9zdGF0ZSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfdGFibGUsIDEpCgogICAgICAgIGFjdGlv"
    "bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlID0gX2dvdGhpY19idG4oIkFERCBU"
    "QVNLIikKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrID0gX2dvdGhpY19idG4oIkNPTVBMRVRFIFNFTEVDVEVEIikKICAg"
    "ICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzayA9IF9nb3RoaWNfYnRuKCJDQU5DRUwgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRu"
    "X3RvZ2dsZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiU0hPVyBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2Nv"
    "bXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJQVVJHRSBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFj"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2su"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNl"
    "dEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBmb3Ig"
    "YnRuIGluICgKICAgICAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLAogICAgICAgICAgICBzZWxmLmJ0bl9jb21w"
    "bGV0ZV90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzaywKICAgICAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2Nv"
    "bXBsZXRlZCwKICAgICAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkLAogICAgICAgICk6CiAgICAgICAgICAgIGFjdGlv"
    "bnMuYWRkV2lkZ2V0KGJ0bikKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChhY3Rpb25zKQogICAgICAgIHNlbGYud29y"
    "a3NwYWNlX3N0YWNrLmFkZFdpZGdldChub3JtYWwpCgogICAgICAgIGVkaXRvciA9IFFXaWRnZXQoKQogICAgICAgIGVkaXRvcl9s"
    "YXlvdXQgPSBRVkJveExheW91dChlZGl0b3IpCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBUQVNLIEVESVRPUiDigJQgR09PR0xFLUZJUlNUIikpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9z"
    "dGF0dXNfbGFiZWwgPSBRTGFiZWwoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIu"
    "IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6"
    "IDZweDsiCiAgICAgICAgKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xh"
    "YmVsKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9u"
    "YW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiVGFzayBOYW1lIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IERh"
    "dGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IFRpbWUgKEhIOk1NKSIpCiAgICAg"
    "ICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0"
    "ZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRf"
    "dGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIkVu"
    "ZCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24gPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYudGFza19lZGl0b3JfbG9jYXRpb24uc2V0UGxhY2Vob2xkZXJUZXh0KCJMb2NhdGlvbiAob3B0aW9uYWwpIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5j"
    "ZS5zZXRQbGFjZWhvbGRlclRleHQoIlJlY3VycmVuY2UgUlJVTEUgKG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9hbGxfZGF5ID0gUUNoZWNrQm94KCJBbGwtZGF5IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzID0gUVRleHRFZGl0"
    "KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWNlaG9sZGVyVGV4dCgiTm90ZXMiKQogICAgICAgIHNlbGYu"
    "dGFza19lZGl0b3Jfbm90ZXMuc2V0TWF4aW11bUhlaWdodCg5MCkKICAgICAgICBmb3Igd2lkZ2V0IGluICgKICAgICAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9uYW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUsCiAgICAgICAgICAg"
    "IHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSwKICAgICAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiwKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLAogICAgICAgICk6CiAgICAgICAgICAgIGVkaXRvcl9sYXlvdXQu"
    "YWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkp"
    "CiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9ub3RlcywgMSkKICAgICAgICBlZGl0b3Jf"
    "YWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCJTQVZFIikKICAgICAgICBidG5f"
    "Y2FuY2VsID0gX2dvdGhpY19idG4oIkNBTkNFTCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2Vk"
    "aXRvcl9zYXZlKQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9jYW5jZWwpCiAgICAg"
    "ICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5f"
    "Y2FuY2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFN0cmV0Y2goMSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZExheW91"
    "dChlZGl0b3JfYWN0aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQoZWRpdG9yKQoKICAgICAgICBz"
    "ZWxmLm5vcm1hbF93b3Jrc3BhY2UgPSBub3JtYWwKICAgICAgICBzZWxmLmVkaXRvcl93b3Jrc3BhY2UgPSBlZGl0b3IKICAgICAg"
    "ICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCiAgICBkZWYgX3Vw"
    "ZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZW5hYmxlZCA9IGJvb2woc2VsZi5zZWxlY3Rl"
    "ZF90YXNrX2lkcygpKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQogICAgICAgIHNl"
    "bGYuYnRuX2NhbmNlbF90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKCiAgICBkZWYgc2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4g"
    "bGlzdFtzdHJdOgogICAgICAgIGlkczogbGlzdFtzdHJdID0gW10KICAgICAgICBmb3IgciBpbiByYW5nZShzZWxmLnRhc2tfdGFi"
    "bGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gc2VsZi50YXNrX3RhYmxlLml0ZW0ociwgMCkKICAgICAg"
    "ICAgICAgaWYgc3RhdHVzX2l0ZW0gaXMgTm9uZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdCBz"
    "dGF0dXNfaXRlbS5pc1NlbGVjdGVkKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICB0YXNrX2lkID0gc3Rh"
    "dHVzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIGlmIHRhc2tfaWQgYW5kIHRhc2tfaWQg"
    "bm90IGluIGlkczoKICAgICAgICAgICAgICAgIGlkcy5hcHBlbmQodGFza19pZCkKICAgICAgICByZXR1cm4gaWRzCgogICAgZGVm"
    "IGxvYWRfdGFza3Moc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFJv"
    "d0NvdW50KDApCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIHJvdyA9IHNlbGYudGFza190YWJsZS5yb3dD"
    "b3VudCgpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5pbnNlcnRSb3cocm93KQogICAgICAgICAgICBzdGF0dXMgPSAodGFz"
    "ay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaWNvbiA9ICLimJEiIGlmIHN0"
    "YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifSBlbHNlICLigKIiCiAgICAgICAgICAgIGR1ZSA9ICh0YXNrLmdldCgi"
    "ZHVlX2F0Iikgb3IgIiIpLnJlcGxhY2UoIlQiLCAiICIpCiAgICAgICAgICAgIHRleHQgPSAodGFzay5nZXQoInRleHQiKSBvciAi"
    "UmVtaW5kZXIiKS5zdHJpcCgpIG9yICJSZW1pbmRlciIKICAgICAgICAgICAgc291cmNlID0gKHRhc2suZ2V0KCJzb3VyY2UiKSBv"
    "ciAibG9jYWwiKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShmIntzdGF0dXNfaWNv"
    "bn0ge3N0YXR1c30iKQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgdGFz"
    "ay5nZXQoImlkIikpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMCwgc3RhdHVzX2l0ZW0pCiAgICAg"
    "ICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRhYmxlV2lkZ2V0SXRlbShkdWUpKQogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0ZW0odGV4dCkpCiAgICAgICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzb3VyY2UpKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVs"
    "LnNldFRleHQoZiJMb2FkZWQge2xlbih0YXNrcyl9IHRhc2socykuIikKICAgICAgICBzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRv"
    "bl9zdGF0ZSgpCgogICAgZGVmIF9kaWFnKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIHNlbGYuX2RpYWdfbG9nZ2VyOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19s"
    "b2dnZXIobWVzc2FnZSwgbGV2ZWwpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGRlZiBz"
    "dG9wX3JlZnJlc2hfd29ya2VyKHNlbGYsIHJlYXNvbjogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgdGhyZWFkID0gZ2V0YXR0"
    "cihzZWxmLCAiX3JlZnJlc2hfdGhyZWFkIiwgTm9uZSkKICAgICAgICBpZiB0aHJlYWQgaXMgbm90IE5vbmUgYW5kIGhhc2F0dHIo"
    "dGhyZWFkLCAiaXNSdW5uaW5nIikgYW5kIHRocmVhZC5pc1J1bm5pbmcoKToKICAgICAgICAgICAgc2VsZi5fZGlhZygKICAgICAg"
    "ICAgICAgICAgIGYiW1RBU0tTXVtUSFJFQURdW1dBUk5dIHN0b3AgcmVxdWVzdGVkIGZvciByZWZyZXNoIHdvcmtlciByZWFzb249"
    "e3JlYXNvbiBvciAndW5zcGVjaWZpZWQnfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgdGhyZWFkLnJlcXVlc3RJbnRlcnJ1cHRpb24oKQogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucXVpdCgp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRocmVhZC53YWl0"
    "KDIwMDApCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBpZiBub3QgY2FsbGFibGUoc2VsZi5fdGFza3NfcHJvdmlkZXIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHNlbGYubG9hZF90YXNrcyhzZWxmLl90YXNrc19wcm92aWRlcigpKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWcoZiJbVEFTS1NdW1RBQl1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7"
    "ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX3JlZnJl"
    "c2hfZXhjZXB0aW9uIikKCiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0b3Bf"
    "cmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfY2xvc2UiKQogICAgICAgIHN1cGVyKCkuY2xvc2VFdmVudChldmVudCkK"
    "CiAgICBkZWYgc2V0X3Nob3dfY29tcGxldGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hv"
    "d19jb21wbGV0ZWQgPSBib29sKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5zZXRUZXh0KCJISURF"
    "IENPTVBMRVRFRCIgaWYgc2VsZi5fc2hvd19jb21wbGV0ZWQgZWxzZSAiU0hPVyBDT01QTEVURUQiKQoKICAgIGRlZiBzZXRfc3Rh"
    "dHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYg"
    "b2sgZWxzZSBDX1RFWFRfRElNCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge2NvbG9yfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsgcGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0VGV4dCh0"
    "ZXh0KQoKICAgIGRlZiBvcGVuX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1"
    "cnJlbnRXaWRnZXQoc2VsZi5lZGl0b3Jfd29ya3NwYWNlKQoKICAgIGRlZiBjbG9zZV9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCgpjbGFzcyBT"
    "ZWxmVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hJ3MgaW50ZXJuYWwgZGlhbG9ndWUgc3BhY2UuCiAgICBSZWNlaXZl"
    "czogaWRsZSBuYXJyYXRpdmUgb3V0cHV0LCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zLAogICAgICAgICAgICAgIFBvSSBsaXN0"
    "IGZyb20gZGFpbHkgcmVmbGVjdGlvbiwgdW5hbnN3ZXJlZCBxdWVzdGlvbiBmbGFncywKICAgICAgICAgICAgICBqb3VybmFsIGxv"
    "YWQgbm90aWZpY2F0aW9ucy4KICAgIFJlYWQtb25seSBkaXNwbGF5LiBTZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIgYWx3"
    "YXlzLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "aGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacgSU5ORVIgU0FOQ1RVTSDigJQge0RFQ0tfTkFNRS51cHBlcigpfSdTIFBS"
    "SVZBVEUgVEhPVUdIVFMiKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFy"
    "KQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfUFVSUExFX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBm"
    "b250LXNpemU6IDExcHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3Bs"
    "YXksIDEpCgogICAgZGVmIGFwcGVuZChzZWxmLCBsYWJlbDogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0"
    "YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJO"
    "QVJSQVRJVkUiOiAgQ19HT0xELAogICAgICAgICAgICAiUkVGTEVDVElPTiI6IENfUFVSUExFLAogICAgICAgICAgICAiSk9VUk5B"
    "TCI6ICAgIENfU0lMVkVSLAogICAgICAgICAgICAiUE9JIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICJTWVNURU0i"
    "OiAgICAgQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBjb2xvcnMuZ2V0KGxhYmVsLnVwcGVyKCksIENfR09M"
    "RCkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9E"
    "SU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYn"
    "PHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYn4p2nIHtsYWJlbH08"
    "L3NwYW4+PGJyPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dGV4dH08L3NwYW4+JwogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgiIikKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xs"
    "QmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAg"
    "ICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDi"
    "lIAgRElBR05PU1RJQ1MgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEaWFnbm9zdGljc1RhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgQmFja2VuZCBkaWFnbm9zdGljcyBkaXNwbGF5LgogICAgUmVjZWl2ZXM6IGhhcmR3YXJlIGRldGVjdGlv"
    "biByZXN1bHRzLCBkZXBlbmRlbmN5IGNoZWNrIHJlc3VsdHMsCiAgICAgICAgICAgICAgQVBJIGVycm9ycywgc3luYyBmYWlsdXJl"
    "cywgdGltZXIgZXZlbnRzLCBqb3VybmFsIGxvYWQgbm90aWNlcywKICAgICAgICAgICAgICBtb2RlbCBsb2FkIHN0YXR1cywgR29v"
    "Z2xlIGF1dGggZXZlbnRzLgogICAgQWx3YXlzIHNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYi4KICAgICIiIgoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9v"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBy"
    "b290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgRElBR05PU1RJQ1Mg4oCUIFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "ID0gX2dvdGhpY19idG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAg"
    "ICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAg"
    "ICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7"
    "Q19TSUxWRVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiAnQ291cmllciBOZXcnLCBtb25vc3BhY2U7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IHBhZGRp"
    "bmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGxvZyhz"
    "ZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJJTkZPIjog"
    "IENfU0lMVkVSLAogICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAogICAgICAgICAgICAiV0FSTiI6ICBDX0dPTEQsCiAgICAg"
    "ICAgICAgICJFUlJPUiI6IENfQkxPT0QsCiAgICAgICAgICAgICJERUJVRyI6IENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAg"
    "IGNvbG9yID0gbGV2ZWxfY29sb3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZFUikKICAgICAgICBzZWxmLl9kaXNwbGF5LmFw"
    "cGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyI+W3t0aW1lc3RhbXB9XTwvc3Bhbj4g"
    "JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e21lc3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5"
    "LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBsb2dfbWFueShzZWxmLCBtZXNzYWdlczog"
    "bGlzdFtzdHJdLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXM6CiAgICAg"
    "ICAgICAgIGx2bCA9IGxldmVsCiAgICAgICAgICAgIGlmICLinJMiIGluIG1zZzogICAgbHZsID0gIk9LIgogICAgICAgICAgICBl"
    "bGlmICLinJciIGluIG1zZzogIGx2bCA9ICJXQVJOIgogICAgICAgICAgICBlbGlmICJFUlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2"
    "bCA9ICJFUlJPUiIKICAgICAgICAgICAgc2VsZi5sb2cobXNnLCBsdmwpCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVsZXNl"
    "dCBhbmQgY29kZSBsZXNzb25zIGJyb3dzZXIuCiAgICBBZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRlIGxlc3NvbnMuCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVhcm5lZERCIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0"
    "KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmco"
    "NCkKCiAgICAgICAgIyBGaWx0ZXIgYmFyCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9z"
    "ZWFyY2ggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNlYXJjaCBsZXNzb25z"
    "Li4uIikKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuYWRk"
    "SXRlbXMoWyJBbGwiLCAiTFNMIiwgIlB5dGhvbiIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJKYXZhU2NyaXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5fc2VhcmNoLnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5y"
    "ZWZyZXNoKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkK"
    "ICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIlNlYXJjaDoiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdl"
    "dChzZWxmLl9zZWFyY2gsIDEpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJMYW5ndWFnZToiKSkKICAgICAg"
    "ICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikKICAgICAgICByb290LmFkZExheW91dChmaWx0ZXJfcm93"
    "KQoKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0bigi4pymIEFkZCBM"
    "ZXNzb24iKQogICAgICAgIGJ0bl9kZWwgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGJ0bl9kZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAg"
    "ICAgICBidG5fYmFyLmFkZFdpZGdldChidG5fYWRkKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAg"
    "YnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9"
    "IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoCiAgICAgICAg"
    "ICAgIFsiTGFuZ3VhZ2UiLCAiUmVmZXJlbmNlIEtleSIsICJTdW1tYXJ5IiwgIkVudmlyb25tZW50Il0KICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVh"
    "ZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAg"
    "ICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFi"
    "bGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVj"
    "dCkKCiAgICAgICAgIyBVc2Ugc3BsaXR0ZXIgYmV0d2VlbiB0YWJsZSBhbmQgZGV0YWlsCiAgICAgICAgc3BsaXR0ZXIgPSBRU3Bs"
    "aXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAg"
    "ICAgICAjIERldGFpbCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBkZXRhaWxfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0"
    "LCAwLCAwKQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVhZGVyID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZVTEwgUlVMRSIpKQogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZSA9IF9nb3RoaWNfYnRuKCJF"
    "ZGl0IikKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX2VkaXRf"
    "cnVsZS5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnRvZ2dsZWQuY29ubmVjdChzZWxmLl90"
    "b2dnbGVfZWRpdF9tb2RlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAg"
    "c2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJs"
    "ZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkK"
    "ICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fZWRpdF9ydWxlKQogICAgICAgIGRldGFpbF9oZWFkZXIu"
    "YWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlX3J1bGUpCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hlYWRl"
    "cikKCiAgICAgICAgc2VsZi5fZGV0YWlsID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkoVHJ1"
    "ZSkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fZGV0YWlsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChkZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVy"
    "LnNldFNpemVzKFszMDAsIDE4MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3Jl"
    "Y29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRlZiByZWZyZXNo"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcSAgICA9IHNlbGYuX3NlYXJjaC50ZXh0KCkKICAgICAgICBsYW5nID0gc2VsZi5fbGFu"
    "Z19maWx0ZXIuY3VycmVudFRleHQoKQogICAgICAgIGxhbmcgPSAiIiBpZiBsYW5nID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAg"
    "IHNlbGYuX3JlY29yZHMgPSBzZWxmLl9kYi5zZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3Rh"
    "YmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2UiLCIiKSkpCiAg"
    "ICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdl"
    "dCgicmVmZXJlbmNlX2tleSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVt"
    "KHIsIDMsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImVudmlyb25tZW50IiwiIikpKQoKICAgIGRl"
    "ZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAg"
    "c2VsZi5fZWRpdGluZ19yb3cgPSByb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRQbGFpblRleHQoCiAgICAgICAg"
    "ICAgICAgICByZWMuZ2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiArCiAgICAgICAgICAgICAgICAoIlJlc29sdXRpb246ICIg"
    "KyByZWMuZ2V0KCJyZXNvbHV0aW9uIiwiIikgaWYgcmVjLmdldCgicmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgIyBSZXNldCBlZGl0IG1vZGUgb24gbmV3IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9y"
    "dWxlLnNldENoZWNrZWQoRmFsc2UpCgogICAgZGVmIF90b2dnbGVfZWRpdF9tb2RlKHNlbGYsIGVkaXRpbmc6IGJvb2wpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KG5vdCBlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1"
    "bGUuc2V0VmlzaWJsZShlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2VsIiBpZiBlZGl0"
    "aW5nIGVsc2UgIkVkaXQiKQogICAgICAgIGlmIGVkaXRpbmc6CiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAg"
    "IGYiYm9yZGVyOiAxcHggc29saWQge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAg"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRw"
    "eDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBSZWxvYWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5jZWwKICAgICAgICAg"
    "ICAgc2VsZi5fb25fc2VsZWN0KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0g"
    "c2VsZi5fZWRpdGluZ19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgdGV4"
    "dCA9IHNlbGYuX2RldGFpbC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgIyBTcGxpdCByZXNvbHV0aW9uIGJhY2sg"
    "b3V0IGlmIHByZXNlbnQKICAgICAgICAgICAgaWYgIlxuXG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAgICAgICAgICAgICBw"
    "YXJ0cyA9IHRleHQuc3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHBhcnRz"
    "WzBdLnN0cmlwKCkKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBwYXJ0c1sxXS5zdHJpcCgpCiAgICAgICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gdGV4dAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHNlbGYuX3JlY29y"
    "ZHNbcm93XS5nZXQoInJlc29sdXRpb24iLCAiIikKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJmdWxsX3J1bGUiXSAg"
    "PSBmdWxsX3J1bGUKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJyZXNvbHV0aW9uIl0gPSByZXNvbHV0aW9uCiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX2RiLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9idG5fZWRp"
    "dF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19hZGQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgTGVzc29u"
    "IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAg"
    "ICAgIGRsZy5yZXNpemUoNTAwLCA0MDApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBlbnYgID0gUUxp"
    "bmVFZGl0KCJMU0wiKQogICAgICAgIGxhbmcgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgcmVmICA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgc3VtbSA9IFFMaW5lRWRpdCgpCiAgICAgICAgcnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVt"
    "SGVpZ2h0KDEwMCkKICAgICAgICByZXMgID0gUUxpbmVFZGl0KCkKICAgICAgICBsaW5rID0gUUxpbmVFZGl0KCkKICAgICAgICBm"
    "b3IgbGFiZWwsIHcgaW4gWwogICAgICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgiTGFuZ3VhZ2U6IiwgbGFuZyksCiAg"
    "ICAgICAgICAgICgiUmVmZXJlbmNlIEtleToiLCByZWYpLCAoIlN1bW1hcnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBS"
    "dWxlOiIsIHJ1bGUpLCAoIlJlc29sdXRpb246IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06"
    "CiAgICAgICAgICAgIGZvcm0uYWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sg"
    "PSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVj"
    "dChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBi"
    "dG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxv"
    "Zy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9kYi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9ubWVu"
    "dD1lbnYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQoKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICAgICAgcmVmZXJlbmNlX2tleT1yZWYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBzdW1tYXJ5PXN1bW0udGV4"
    "dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBmdWxsX3J1bGU9cnVsZS50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAg"
    "ICAgICAgICByZXNvbHV0aW9uPXJlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxpbms9bGluay50ZXh0KCkuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2Vs"
    "Zi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlY19pZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImlkIiwiIikKICAgICAgICAg"
    "ICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTGVzc29uIiwKICAg"
    "ICAgICAgICAgICAgICJEZWxldGUgdGhpcyBsZXNzb24/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGIuZGVsZXRlKHJlY19pZCkKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgTU9EVUxFIFRSQUNLRVIg"
    "VEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2R1bGVUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25h"
    "bCBtb2R1bGUgcGlwZWxpbmUgdHJhY2tlci4KICAgIFRyYWNrIHBsYW5uZWQvaW4tcHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBhcyB0"
    "aGV5IGFyZSBkZXNpZ25lZC4KICAgIEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNjcmlwdGlvbiwgTm90ZXMuCiAg"
    "ICBFeHBvcnQgdG8gVFhUIGZvciBwYXN0aW5nIGludG8gc2Vzc2lvbnMuCiAgICBJbXBvcnQ6IHBhc3RlIGEgZmluYWxpemVkIHNw"
    "ZWMsIGl0IHBhcnNlcyBuYW1lIGFuZCBkZXRhaWxzLgogICAgVGhpcyBpcyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5l"
    "Y3RlZCB0byBkZWNrX2J1aWxkZXIncyBNT0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIsICJE"
    "ZXNpZ25pbmciLCAiUmVhZHkgdG8gQnVpbGQiLCAiUGFydGlhbCIsICJCdWlsdCJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBh"
    "cmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgo"
    "Im1lbW9yaWVzIikgLyAibW9kdWxlX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtd"
    "CiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ0bl9iYXIg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9kdWxlIikKICAgICAg"
    "ICBzZWxmLl9idG5fZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGlj"
    "X2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCBUWFQiKQogICAgICAg"
    "IHNlbGYuX2J0bl9pbXBvcnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNwZWMiKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5f"
    "YWRkLCBzZWxmLl9idG5fZWRpdCwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCwg"
    "c2VsZi5fYnRuX2ltcG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDgwKQogICAgICAgICAgICBiLnNldE1pbmlt"
    "dW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkK"
    "ICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBzZWxmLl9idG5faW1wb3J0LmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19pbXBvcnQpCgogICAgICAgICMgVGFibGUKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3Jp"
    "cHRpb24iXSkKICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgIGhoLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lk"
    "dGgoMCwgMTYwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlv"
    "cigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dv"
    "dGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5f"
    "b25fc2VsZWN0KQoKICAgICAgICAjIFNwbGl0dGVyCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24u"
    "VmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIE5vdGVzIHBhbmVsCiAg"
    "ICAgICAgbm90ZXNfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgbm90ZXNfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm90ZXNfd2lk"
    "Z2V0KQogICAgICAgIG5vdGVzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBub3Rlc19sYXlv"
    "dXQuc2V0U3BhY2luZygyKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTk9URVMiKSkK"
    "ICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFJl"
    "YWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxm"
    "Ll9ub3Rlc19kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAg"
    "ICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ub3Rlc19kaXNwbGF5KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChu"
    "b3Rlc193aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzI1MCwgMTUwXSkKICAgICAgICByb290LmFkZFdpZGdldChz"
    "cGxpdHRlciwgMSkKCiAgICAgICAgIyBDb3VudCBsYWJlbAogICAgICAgIHNlbGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikKICAg"
    "ICAgICBzZWxmLl9jb3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYuX2NvdW50X2xibCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMg"
    "PSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0o"
    "cmVjLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJz"
    "dGF0dXMiLCAiSWRlYSIpKQogICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3JzID0g"
    "ewogICAgICAgICAgICAgICAgIklkZWEiOiAgICAgICAgICAgICBDX1RFWFRfRElNLAogICAgICAgICAgICAgICAgIkRlc2lnbmlu"
    "ZyI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAgICAgIlJlYWR5IHRvIEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAg"
    "ICAgICAgICAgICJQYXJ0aWFsIjogICAgICAgICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0IjogICAgICAgICAg"
    "ICBDX0dSRUVOLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVncm91bmQoCiAgICAgICAgICAg"
    "ICAgICBRQ29sb3Ioc3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpLCBDX1RFWFRfRElNKSkKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9u"
    "IiwgIiIpWzo4MF0pKQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAg"
    "ICAgICBzID0gcmVjLmdldCgic3RhdHVzIiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10gPSBjb3VudHMuZ2V0KHMsIDAp"
    "ICsgMQogICAgICAgIGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfToge259IiBmb3IgcywgbiBpbiBjb3VudHMuaXRlbXMoKSkK"
    "ICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0VGV4dCgKICAgICAgICAgICAgZiJUb3RhbDoge2xlbihzZWxmLl9yZWNvcmRzKX0g"
    "ICB7Y291bnRfc3RyfSIKICAgICAgICApCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBz"
    "ZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJl"
    "Yy5nZXQoIm5vdGVzIiwgIiIpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fb3Blbl9lZGl0"
    "X2RpYWxvZygpCgogICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVu"
    "dFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHNlbGYuX29wZW5fZWRp"
    "dF9kaWFsb2coc2VsZi5fcmVjb3Jkc1tyb3ddLCByb3cpCgogICAgZGVmIF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGlj"
    "dCA9IE5vbmUsIHJvdzogaW50ID0gLTEpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5z"
    "ZXRXaW5kb3dUaXRsZSgiTW9kdWxlIiBpZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAg"
    "ICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcu"
    "cmVzaXplKDU0MCwgNDQwKQogICAgICAgIGZvcm0gPSBRVkJveExheW91dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGlu"
    "ZUVkaXQocmVjLmdldCgibmFtZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmllbGQuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJNb2R1bGUgbmFtZSIpCgogICAgICAgIHN0YXR1c19jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2NvbWJv"
    "LmFkZEl0ZW1zKHNlbGYuU1RBVFVTRVMpCiAgICAgICAgaWYgcmVjOgogICAgICAgICAgICBpZHggPSBzdGF0dXNfY29tYm8uZmlu"
    "ZFRleHQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgICAgIHN0"
    "YXR1c19jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQoKICAgICAgICBkZXNjX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoImRl"
    "c2NyaXB0aW9uIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9uZS1s"
    "aW5lIGRlc2NyaXB0aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIG5vdGVzX2ZpZWxkLnNl"
    "dFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgKICAgICAgICAgICAgIkZ1bGwgbm90ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVudHMsIGVkZ2UgY2Fz"
    "ZXMuLi4iCiAgICAgICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1IZWlnaHQoMjAwKQoKICAgICAgICBmb3IgbGFi"
    "ZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxkKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwg"
    "c3RhdHVzX2NvbWJvKSwKICAgICAgICAgICAgKCJEZXNjcmlwdGlvbjoiLCBkZXNjX2ZpZWxkKSwKICAgICAgICAgICAgKCJOb3Rl"
    "czoiLCBub3Rlc19maWVsZCksCiAgICAgICAgXToKICAgICAgICAgICAgcm93X2xheW91dCA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICAgICAgbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4ZWRXaWR0aCg5MCkKICAgICAgICAgICAgcm93"
    "X2xheW91dC5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgICAg"
    "IGZvcm0uYWRkTGF5b3V0KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3Nh"
    "dmUgICA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAg"
    "ICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qo"
    "ZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChi"
    "dG5fY2FuY2VsKQogICAgICAgIGZvcm0uYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxv"
    "Zy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAg"
    "ICAgcmVjLmdldCgiaWQiLCBzdHIodXVpZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ugc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICAgICAibmFtZSI6ICAgICAgICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6"
    "ICAgICAgc3RhdHVzX2NvbWJvLmN1cnJlbnRUZXh0KCksCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxk"
    "LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5z"
    "dHJpcCgpLAogICAgICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0aW1lLm5vdygpLmlz"
    "b2Zvcm1hdCgpKSBpZiByZWMgZWxzZSBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmll"
    "ZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5f"
    "cmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMp"
    "OgogICAgICAgICAgICBuYW1lID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgibmFtZSIsInRoaXMgbW9kdWxlIikKICAgICAgICAg"
    "ICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTW9kdWxlIiwKICAg"
    "ICAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX3Jl"
    "Y29yZHMucG9wKHJvdykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVk"
    "XyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYibW9kdWxlc197dHN9LnR4dCIKICAgICAgICAg"
    "ICAgbGluZXMgPSBbCiAgICAgICAgICAgICAgICAiRUNITyBERUNLIOKAlCBNT0RVTEUgVFJBQ0tFUiBFWFBPUlQiLAogICAgICAg"
    "ICAgICAgICAgZiJFeHBvcnRlZDoge2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAg"
    "ICAgICAgICAgICBmIlRvdGFsIG1vZHVsZXM6IHtsZW4oc2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAgICAgICI9IiAqIDYw"
    "LAogICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgog"
    "ICAgICAgICAgICAgICAgbGluZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVMRToge3JlYy5nZXQoJ25hbWUn"
    "LCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiU3RhdHVzOiB7cmVjLmdldCgnc3RhdHVzJywnJyl9IiwKICAgICAgICAgICAg"
    "ICAgICAgICBmIkRlc2NyaXB0aW9uOiB7cmVjLmdldCgnZGVzY3JpcHRpb24nLCcnKX0iLAogICAgICAgICAgICAgICAgICAgICIi"
    "LAogICAgICAgICAgICAgICAgICAgICJOb3RlczoiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIi0iICogNDAsCiAgICAgICAgICAgICAgICAgICAgIiIs"
    "CiAgICAgICAgICAgICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KCJcbiIuam9pbihsaW5lcyksIGVuY29k"
    "aW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykp"
    "CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwKICAg"
    "ICAgICAgICAgICAgIGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9XG5cbkFsc28gY29waWVkIHRvIGNs"
    "aXBib2FyZC4iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIFFNZXNzYWdl"
    "Qm94Lndhcm5pbmcoc2VsZiwgIkV4cG9ydCBFcnJvciIsIHN0cihlKSkKCgoKICAgIGRlZiBfcGFyc2VfaW1wb3J0X2VudHJpZXMo"
    "c2VsZiwgcmF3OiBzdHIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiUGFyc2UgaW1wb3J0ZWQgdGV4dCBpbnRvIG9uZSBvciBt"
    "b3JlIG1vZHVsZSByZWNvcmRzLiIiIgogICAgICAgIGxhYmVsX21hcCA9IHsKICAgICAgICAgICAgIm1vZHVsZSI6ICJuYW1lIiwK"
    "ICAgICAgICAgICAgInN0YXR1cyI6ICJzdGF0dXMiLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiZGVzY3JpcHRpb24iLAog"
    "ICAgICAgICAgICAibm90ZXMiOiAibm90ZXMiLAogICAgICAgICAgICAiZnVsbCBzdW1tYXJ5IjogIm5vdGVzIiwKICAgICAgICB9"
    "CgogICAgICAgIGRlZiBfYmxhbmsoKSAtPiBkaWN0OgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm5hbWUi"
    "OiAiIiwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAiSWRlYSIsCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiIiwK"
    "ICAgICAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAgICAgICAgICB9CgogICAgICAgIGRlZiBfY2xlYW4ocmVjOiBkaWN0KSAt"
    "PiBkaWN0OgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgIm5hbWUiOiByZWMuZ2V0KCJuYW1lIiwgIiIpLnN0"
    "cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogKHJlYy5nZXQoInN0YXR1cyIsICIiKS5zdHJpcCgpIG9yICJJZGVhIiks"
    "CiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiByZWMuZ2V0KCJkZXNjcmlwdGlvbiIsICIiKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICAgICAgIm5vdGVzIjogcmVjLmdldCgibm90ZXMiLCAiIikuc3RyaXAoKSwKICAgICAgICAgICAgfQoKICAgICAgICBkZWYg"
    "X2lzX2V4cG9ydF9oZWFkZXIobGluZTogc3RyKSAtPiBib29sOgogICAgICAgICAgICBsb3cgPSBsaW5lLnN0cmlwKCkubG93ZXIo"
    "KQogICAgICAgICAgICByZXR1cm4gKAogICAgICAgICAgICAgICAgbG93LnN0YXJ0c3dpdGgoImVjaG8gZGVjayIpIG9yCiAgICAg"
    "ICAgICAgICAgICBsb3cuc3RhcnRzd2l0aCgiZXhwb3J0ZWQ6Iikgb3IKICAgICAgICAgICAgICAgIGxvdy5zdGFydHN3aXRoKCJ0"
    "b3RhbCBtb2R1bGVzOiIpIG9yCiAgICAgICAgICAgICAgICBsb3cuc3RhcnRzd2l0aCgidG90YWwgIikKICAgICAgICAgICAgKQoK"
    "ICAgICAgICBkZWYgX2lzX2RlY29yYXRpdmUobGluZTogc3RyKSAtPiBib29sOgogICAgICAgICAgICBzID0gbGluZS5zdHJpcCgp"
    "CiAgICAgICAgICAgIGlmIG5vdCBzOgogICAgICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgICAgIGlmIGFsbChjaCBp"
    "biAiLT1+XyrigKLCt+KAlCAiIGZvciBjaCBpbiBzKToKICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgICAgIGlm"
    "IChzLnN0YXJ0c3dpdGgoIj09PSIpIGFuZCBzLmVuZHN3aXRoKCI9PT0iKSkgb3IgKHMuc3RhcnRzd2l0aCgiLS0tIikgYW5kIHMu"
    "ZW5kc3dpdGgoIi0tLSIpKToKICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAg"
    "ICAgICBkZWYgX2lzX3NlcGFyYXRvcihsaW5lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgICAgIHMgPSBsaW5lLnN0cmlwKCkKICAg"
    "ICAgICAgICAgcmV0dXJuIGxlbihzKSA+PSA4IGFuZCBhbGwoY2ggaW4gIi3igJQiIGZvciBjaCBpbiBzKQoKICAgICAgICBlbnRy"
    "aWVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBjdXJyZW50ID0gX2JsYW5rKCkKICAgICAgICBjdXJyZW50X2ZpZWxkOiBPcHRp"
    "b25hbFtzdHJdID0gTm9uZQoKICAgICAgICBkZWYgX2hhc19wYXlsb2FkKHJlYzogZGljdCkgLT4gYm9vbDoKICAgICAgICAgICAg"
    "cmV0dXJuIGFueShib29sKChyZWMuZ2V0KGssICIiKSBvciAiIikuc3RyaXAoKSkgZm9yIGsgaW4gKCJuYW1lIiwgInN0YXR1cyIs"
    "ICJkZXNjcmlwdGlvbiIsICJub3RlcyIpKQoKICAgICAgICBkZWYgX2ZsdXNoKCkgLT4gTm9uZToKICAgICAgICAgICAgbm9ubG9j"
    "YWwgY3VycmVudCwgY3VycmVudF9maWVsZAogICAgICAgICAgICBjbGVhbmVkID0gX2NsZWFuKGN1cnJlbnQpCiAgICAgICAgICAg"
    "IGlmIGNsZWFuZWRbIm5hbWUiXToKICAgICAgICAgICAgICAgIGVudHJpZXMuYXBwZW5kKGNsZWFuZWQpCiAgICAgICAgICAgIGN1"
    "cnJlbnQgPSBfYmxhbmsoKQogICAgICAgICAgICBjdXJyZW50X2ZpZWxkID0gTm9uZQoKICAgICAgICBmb3IgcmF3X2xpbmUgaW4g"
    "cmF3LnNwbGl0bGluZXMoKToKICAgICAgICAgICAgbGluZSA9IHJhd19saW5lLnJzdHJpcCgiXG4iKQogICAgICAgICAgICBzdHJp"
    "cHBlZCA9IGxpbmUuc3RyaXAoKQoKICAgICAgICAgICAgaWYgX2lzX3NlcGFyYXRvcihzdHJpcHBlZCk6CiAgICAgICAgICAgICAg"
    "ICBpZiBfaGFzX3BheWxvYWQoY3VycmVudCk6CiAgICAgICAgICAgICAgICAgICAgX2ZsdXNoKCkKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCgogICAgICAgICAgICBpZiBub3Qgc3RyaXBwZWQ6CiAgICAgICAgICAgICAgICBpZiBjdXJyZW50X2ZpZWxkID09ICJu"
    "b3RlcyI6CiAgICAgICAgICAgICAgICAgICAgY3VycmVudFsibm90ZXMiXSA9IChjdXJyZW50WyJub3RlcyJdICsgIlxuIikgaWYg"
    "Y3VycmVudFsibm90ZXMiXSBlbHNlICIiCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgX2lzX2V4cG9y"
    "dF9oZWFkZXIoc3RyaXBwZWQpOgogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIF9pc19kZWNvcmF0aXZl"
    "KHN0cmlwcGVkKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiAiOiIgaW4gc3RyaXBwZWQ6CiAgICAg"
    "ICAgICAgICAgICBtYXliZV9sYWJlbCwgbWF5YmVfdmFsdWUgPSBzdHJpcHBlZC5zcGxpdCgiOiIsIDEpCiAgICAgICAgICAgICAg"
    "ICBrZXkgPSBtYXliZV9sYWJlbC5zdHJpcCgpLmxvd2VyKCkKICAgICAgICAgICAgICAgIHZhbHVlID0gbWF5YmVfdmFsdWUubHN0"
    "cmlwKCkKCiAgICAgICAgICAgICAgICBtYXBwZWQgPSBsYWJlbF9tYXAuZ2V0KGtleSkKICAgICAgICAgICAgICAgIGlmIG1hcHBl"
    "ZDoKICAgICAgICAgICAgICAgICAgICBpZiBtYXBwZWQgPT0gIm5hbWUiIGFuZCBfaGFzX3BheWxvYWQoY3VycmVudCk6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIF9mbHVzaCgpCiAgICAgICAgICAgICAgICAgICAgY3VycmVudF9maWVsZCA9IG1hcHBlZAogICAg"
    "ICAgICAgICAgICAgICAgIGlmIG1hcHBlZCA9PSAibm90ZXMiOgogICAgICAgICAgICAgICAgICAgICAgICBjdXJyZW50W21hcHBl"
    "ZF0gPSB2YWx1ZQogICAgICAgICAgICAgICAgICAgIGVsaWYgbWFwcGVkID09ICJzdGF0dXMiOgogICAgICAgICAgICAgICAgICAg"
    "ICAgICBjdXJyZW50W21hcHBlZF0gPSB2YWx1ZSBvciAiSWRlYSIKICAgICAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgICAgICAgICBjdXJyZW50W21hcHBlZF0gPSB2YWx1ZQogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAg"
    "ICAgICAgICAgIyBVbmtub3duIGxhYmVsZWQgbGluZXMgYXJlIG1ldGFkYXRhL2NhdGVnb3J5L2Zvb3RlciBsaW5lcy4KICAgICAg"
    "ICAgICAgICAgIGN1cnJlbnRfZmllbGQgPSBOb25lCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgY3Vy"
    "cmVudF9maWVsZCA9PSAibm90ZXMiOgogICAgICAgICAgICAgICAgY3VycmVudFsibm90ZXMiXSA9IChjdXJyZW50WyJub3RlcyJd"
    "ICsgIlxuIiArIHN0cmlwcGVkKSBpZiBjdXJyZW50WyJub3RlcyJdIGVsc2Ugc3RyaXBwZWQKICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCgogICAgICAgICAgICBpZiBjdXJyZW50X2ZpZWxkID09ICJkZXNjcmlwdGlvbiI6CiAgICAgICAgICAgICAgICBjdXJyZW50"
    "WyJkZXNjcmlwdGlvbiJdID0gKGN1cnJlbnRbImRlc2NyaXB0aW9uIl0gKyAiXG4iICsgc3RyaXBwZWQpIGlmIGN1cnJlbnRbImRl"
    "c2NyaXB0aW9uIl0gZWxzZSBzdHJpcHBlZAogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgSWdub3JlIHVu"
    "bGFiZWxlZCBsaW5lcyBvdXRzaWRlIHJlY29nbml6ZWQgZmllbGRzLgogICAgICAgICAgICBjb250aW51ZQoKICAgICAgICBpZiBf"
    "aGFzX3BheWxvYWQoY3VycmVudCk6CiAgICAgICAgICAgIF9mbHVzaCgpCgogICAgICAgIHJldHVybiBlbnRyaWVzCgogICAgZGVm"
    "IF9kb19pbXBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJJbXBvcnQgb25lIG9yIG1vcmUgbW9kdWxlIHNwZWNzIGZyb20g"
    "cGFzdGVkIHRleHQgb3IgYSBUWFQgZmlsZS4iIiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdp"
    "bmRvd1RpdGxlKCJJbXBvcnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1NjAsIDQyMCkKICAgICAgICBsYXlvdXQgPSBRVkJv"
    "eExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBtb2R1bGUgdGV4"
    "dCBiZWxvdyBvciBsb2FkIGEgLnR4dCBleHBvcnQuXG4iCiAgICAgICAgICAgICJTdXBwb3J0cyBNT0RVTEUgVFJBQ0tFUiBleHBv"
    "cnRzLCByZWdpc3RyeSBibG9ja3MsIGFuZCBzaW5nbGUgbGFiZWxlZCBzcGVjcy4iCiAgICAgICAgKSkKCiAgICAgICAgdG9vbF9y"
    "b3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2xvYWRfdHh0ID0gX2dvdGhpY19idG4oIkxvYWQgVFhUIikKICAgICAgICBs"
    "b2FkZWRfbGJsID0gUUxhYmVsKCJObyBmaWxlIGxvYWRlZCIpCiAgICAgICAgbG9hZGVkX2xibC5zZXRTdHlsZVNoZWV0KGYiY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAgICAgICB0b29sX3Jvdy5hZGRXaWRnZXQoYnRuX2xvYWRfdHh0"
    "KQogICAgICAgIHRvb2xfcm93LmFkZFdpZGdldChsb2FkZWRfbGJsLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQodG9vbF9y"
    "b3cpCgogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJQYXN0ZSBtb2R1bGUgc3BlYyhzKSBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCgog"
    "ICAgICAgIGRlZiBfbG9hZF90eHRfaW50b19lZGl0b3IoKSAtPiBOb25lOgogICAgICAgICAgICBwYXRoLCBfID0gUUZpbGVEaWFs"
    "b2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICAgICAgc2VsZiwKICAgICAgICAgICAgICAgICJMb2FkIE1vZHVsZSBTcGVj"
    "cyIsCiAgICAgICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImV4cG9ydHMiKSksCiAgICAgICAgICAgICAgICAiVGV4dCBGaWxlcyAo"
    "Ki50eHQpOztBbGwgRmlsZXMgKCopIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBub3QgcGF0aDoKICAgICAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByYXdfdGV4dCA9IFBhdGgocGF0aCkucmVhZF90ZXh0"
    "KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94Lndhcm5pbmcoc2VsZiwgIkltcG9ydCBFcnJvciIsIGYiQ291bGQgbm90IHJlYWQgZmlsZTpcbntlfSIpCiAgICAgICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICAgICAgdGV4dF9maWVsZC5zZXRQbGFpblRleHQocmF3X3RleHQpCiAgICAgICAgICAgIGxv"
    "YWRlZF9sYmwuc2V0VGV4dChmIkxvYWRlZDoge1BhdGgocGF0aCkubmFtZX0iKQoKICAgICAgICBidG5fbG9hZF90eHQuY2xpY2tl"
    "ZC5jb25uZWN0KF9sb2FkX3R4dF9pbnRvX2VkaXRvcikKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBi"
    "dG5fb2sgPSBfZ290aGljX2J0bigiSW1wb3J0IikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAg"
    "ICAgICAgYnRuX29rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX29rKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0"
    "bl9jYW5jZWwpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFs"
    "b2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmF3ID0gdGV4dF9maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCkK"
    "ICAgICAgICAgICAgaWYgbm90IHJhdzoKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgcGFyc2VkX2VudHJpZXMg"
    "PSBzZWxmLl9wYXJzZV9pbXBvcnRfZW50cmllcyhyYXcpCiAgICAgICAgICAgIGlmIG5vdCBwYXJzZWRfZW50cmllczoKICAgICAg"
    "ICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgc2VsZiwKICAgICAgICAgICAgICAgICAg"
    "ICAiSW1wb3J0IEVycm9yIiwKICAgICAgICAgICAgICAgICAgICAiTm8gdmFsaWQgbW9kdWxlIGVudHJpZXMgd2VyZSBmb3VuZC4g"
    "SW5jbHVkZSBhdCBsZWFzdCBvbmUgJ01vZHVsZTonIG9yICdNT0RVTEU6JyBibG9jay4iLAogICAgICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBub3cgPSBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKQogICAgICAgICAg"
    "ICBmb3IgcGFyc2VkIGluIHBhcnNlZF9lbnRyaWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQoewogICAg"
    "ICAgICAgICAgICAgICAgICJpZCI6IHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgICAgICJuYW1lIjogcGFyc2Vk"
    "LmdldCgibmFtZSIsICIiKVs6NjBdLAogICAgICAgICAgICAgICAgICAgICJzdGF0dXMiOiBwYXJzZWQuZ2V0KCJzdGF0dXMiLCAi"
    "SWRlYSIpIG9yICJJZGVhIiwKICAgICAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBwYXJzZWQuZ2V0KCJkZXNjcmlwdGlv"
    "biIsICIiKSwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBwYXJzZWQuZ2V0KCJub3RlcyIsICIiKSwKICAgICAgICAgICAg"
    "ICAgICAgICAiY3JlYXRlZCI6IG5vdywKICAgICAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiBub3csCiAgICAgICAgICAgICAg"
    "ICB9KQoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLAogICAgICAg"
    "ICAgICAgICAgIkltcG9ydCBDb21wbGV0ZSIsCiAgICAgICAgICAgICAgICBmIkltcG9ydGVkIHtsZW4ocGFyc2VkX2VudHJpZXMp"
    "fSBtb2R1bGUgZW50cnsneScgaWYgbGVuKHBhcnNlZF9lbnRyaWVzKSA9PSAxIGVsc2UgJ2llcyd9LiIKICAgICAgICAgICAgKQoK"
    "CiMg4pSA4pSAIFBBU1MgNSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgdGFiIGNvbnRlbnQg"
    "Y2xhc3NlcyBkZWZpbmVkLgojIFNMU2NhbnNUYWI6IHJlYnVpbHQg4oCUIERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLCB0aW1l"
    "c3RhbXAgcGFyc2VyIGZpeGVkLAojICAgICAgICAgICAgIGNhcmQvZ3JpbW9pcmUgc3R5bGUsIGNvcHktdG8tY2xpcGJvYXJkIGNv"
    "bnRleHQgbWVudS4KIyBTTENvbW1hbmRzVGFiOiBnb3RoaWMgdGFibGUsIOKniSBDb3B5IENvbW1hbmQgYnV0dG9uLgojIEpvYlRy"
    "YWNrZXJUYWI6IGZ1bGwgcmVidWlsZCDigJQgbXVsdGktc2VsZWN0LCBhcmNoaXZlL3Jlc3RvcmUsIENTVi9UU1YgZXhwb3J0Lgoj"
    "IFNlbGZUYWI6IGlubmVyIHNhbmN0dW0gZm9yIGlkbGUgbmFycmF0aXZlIGFuZCByZWZsZWN0aW9uIG91dHB1dC4KIyBEaWFnbm9z"
    "dGljc1RhYjogc3RydWN0dXJlZCBsb2cgd2l0aCBsZXZlbC1jb2xvcmVkIG91dHB1dC4KIyBMZXNzb25zVGFiOiBMU0wgRm9yYmlk"
    "ZGVuIFJ1bGVzZXQgYnJvd3NlciB3aXRoIGFkZC9kZWxldGUvc2VhcmNoLgojCiMgTmV4dDogUGFzcyA2IOKAlCBNYWluIFdpbmRv"
    "dwojIChNb3JnYW5uYURlY2sgY2xhc3MsIGZ1bGwgbGF5b3V0LCBBUFNjaGVkdWxlciwgZmlyc3QtcnVuIGZsb3csCiMgIGRlcGVu"
    "ZGVuY3kgYm9vdHN0cmFwLCBzaG9ydGN1dCBjcmVhdGlvbiwgc3RhcnR1cCBzZXF1ZW5jZSkKCgojIOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1P"
    "UkdBTk5BIERFQ0sg4oCUIFBBU1MgNjogTUFJTiBXSU5ET1cgJiBFTlRSWSBQT0lOVAojCiMgQ29udGFpbnM6CiMgICBib290c3Ry"
    "YXBfY2hlY2soKSAgICAg4oCUIGRlcGVuZGVuY3kgdmFsaWRhdGlvbiArIGF1dG8taW5zdGFsbCBiZWZvcmUgVUkKIyAgIEZpcnN0"
    "UnVuRGlhbG9nICAgICAgICDigJQgbW9kZWwgcGF0aCArIGNvbm5lY3Rpb24gdHlwZSBzZWxlY3Rpb24KIyAgIEpvdXJuYWxTaWRl"
    "YmFyICAgICAgICDigJQgY29sbGFwc2libGUgbGVmdCBzaWRlYmFyIChzZXNzaW9uIGJyb3dzZXIgKyBqb3VybmFsKQojICAgVG9y"
    "cG9yUGFuZWwgICAgICAgICAgIOKAlCBBV0FLRSAvIEFVVE8gLyBTVVNQRU5EIHN0YXRlIHRvZ2dsZQojICAgTW9yZ2FubmFEZWNr"
    "ICAgICAgICAgIOKAlCBtYWluIHdpbmRvdywgZnVsbCBsYXlvdXQsIGFsbCBzaWduYWwgY29ubmVjdGlvbnMKIyAgIG1haW4oKSAg"
    "ICAgICAgICAgICAgICDigJQgZW50cnkgcG9pbnQgd2l0aCBib290c3RyYXAgc2VxdWVuY2UKIyDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9y"
    "dCBzdWJwcm9jZXNzCgoKIyDilIDilIAgUFJFLUxBVU5DSCBERVBFTkRFTkNZIEJPT1RTVFJBUCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJvb3RzdHJhcF9jaGVjaygpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IFJ1bnMgQkVGT1JFIFFBcHBsaWNhdGlvbiBpcyBjcmVhdGVkLgogICAgQ2hlY2tzIGZvciBQeVNpZGU2IHNlcGFyYXRlbHkgKGNh"
    "bid0IHNob3cgR1VJIHdpdGhvdXQgaXQpLgogICAgQXV0by1pbnN0YWxscyBhbGwgb3RoZXIgbWlzc2luZyBub24tY3JpdGljYWwg"
    "ZGVwcyB2aWEgcGlwLgogICAgVmFsaWRhdGVzIGluc3RhbGxzIHN1Y2NlZWRlZC4KICAgIFdyaXRlcyByZXN1bHRzIHRvIGEgYm9v"
    "dHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIHRvIHBpY2sgdXAuCiAgICAiIiIKICAgICMg4pSA4pSAIFN0ZXAgMTogQ2hl"
    "Y2sgUHlTaWRlNiAoY2FuJ3QgYXV0by1pbnN0YWxsIHdpdGhvdXQgaXQgYWxyZWFkeSBwcmVzZW50KSDilIAKICAgIHRyeToKICAg"
    "ICAgICBpbXBvcnQgUHlTaWRlNiAgIyBub3FhCiAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgIyBObyBHVUkgYXZhaWxh"
    "YmxlIOKAlCB1c2UgV2luZG93cyBuYXRpdmUgZGlhbG9nIHZpYSBjdHlwZXMKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9y"
    "dCBjdHlwZXMKICAgICAgICAgICAgY3R5cGVzLndpbmRsbC51c2VyMzIuTWVzc2FnZUJveFcoCiAgICAgICAgICAgICAgICAwLAog"
    "ICAgICAgICAgICAgICAgIlB5U2lkZTYgaXMgcmVxdWlyZWQgYnV0IG5vdCBpbnN0YWxsZWQuXG5cbiIKICAgICAgICAgICAgICAg"
    "ICJPcGVuIGEgdGVybWluYWwgYW5kIHJ1bjpcblxuIgogICAgICAgICAgICAgICAgIiAgICBwaXAgaW5zdGFsbCBQeVNpZGU2XG5c"
    "biIKICAgICAgICAgICAgICAgIGYiVGhlbiByZXN0YXJ0IHtERUNLX05BTUV9LiIsCiAgICAgICAgICAgICAgICBmIntERUNLX05B"
    "TUV9IOKAlCBNaXNzaW5nIERlcGVuZGVuY3kiLAogICAgICAgICAgICAgICAgMHgxMCAgIyBNQl9JQ09ORVJST1IKICAgICAgICAg"
    "ICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHByaW50KCJDUklUSUNBTDogUHlTaWRlNiBub3QgaW5z"
    "dGFsbGVkLiBSdW46IHBpcCBpbnN0YWxsIFB5U2lkZTYiKQogICAgICAgIHN5cy5leGl0KDEpCgogICAgIyDilIDilIAgU3RlcCAy"
    "OiBBdXRvLWluc3RhbGwgb3RoZXIgbWlzc2luZyBkZXBzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0FVVE9fSU5TVEFMTCA9"
    "IFsKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiKSwKICAgICAgICAoImxvZ3VydSIs"
    "ICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAgICAgICAgICAgInB5Z2Ft"
    "ZSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJweXdpbjMyIiksCiAgICAgICAgKCJwc3V0aWwiLCAg"
    "ICAgICAgICAgICAgICAgICAgInBzdXRpbCIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0"
    "cyIpLAogICAgICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJnb29nbGVhcGljbGllbnQiKSwKICAgICAgICAoImdv"
    "b2dsZS1hdXRoLW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwg"
    "ICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiKSwKICAgIF0KCiAgICBpbXBvcnQgaW1wb3J0bGliCiAgICBib290c3RyYXBfbG9n"
    "ID0gW10KCiAgICBmb3IgcGlwX25hbWUsIGltcG9ydF9uYW1lIGluIF9BVVRPX0lOU1RBTEw6CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQo"
    "ZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBib290"
    "c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBtaXNzaW5nIOKAlCBpbnN0"
    "YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHN1YnByb2Nl"
    "c3MucnVuKAogICAgICAgICAgICAgICAgICAgIFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwgInBpcCIsICJpbnN0YWxsIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgcGlwX25hbWUsICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRpb24iXSwKICAgICAgICAg"
    "ICAgICAgICAgICBjYXB0dXJlX291dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRpbWVvdXQ9MTIwCiAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICBpZiByZXN1bHQucmV0dXJuY29kZSA9PSAwOgogICAgICAgICAgICAgICAgICAgICMgVmFsaWRhdGUgaXQg"
    "YWN0dWFsbHkgaW1wb3J0ZWQgbm93CiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpbXBv"
    "cnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBl"
    "bmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbGVkIOKckyIKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbCBhcHBlYXJlZCB0byAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInN1Y2NlZWQgYnV0"
    "IGltcG9ydCBzdGlsbCBmYWlscyDigJQgcmVzdGFydCBtYXkgIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJiZSByZXF1"
    "aXJlZC4iCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAg"
    "Ym9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0"
    "YWxsIGZhaWxlZDogIgogICAgICAgICAgICAgICAgICAgICAgICBmIntyZXN1bHQuc3RkZXJyWzoyMDBdfSIKICAgICAgICAgICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBzdWJwcm9jZXNzLlRpbWVvdXRFeHBpcmVkOgogICAgICAgICAgICAgICAgYm9v"
    "dHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgdGlt"
    "ZWQgb3V0LiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3Rh"
    "bGwgZXJyb3I6IHtlfSIKICAgICAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBTdGVwIDM6IFdyaXRlIGJvb3RzdHJhcCBsb2cg"
    "Zm9yIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIHRyeToKICAgICAgICBsb2dfcGF0aCA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFw"
    "X2xvZy50eHQiCiAgICAgICAgd2l0aCBsb2dfcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAg"
    "ICAgZi53cml0ZSgiXG4iLmpvaW4oYm9vdHN0cmFwX2xvZykpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCgoj"
    "IOKUgOKUgCBGSVJTVCBSVU4gRElBTE9HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGaXJzdFJ1bkRpYWxvZyhRRGlh"
    "bG9nKToKICAgICIiIgogICAgU2hvd24gb24gZmlyc3QgbGF1bmNoIHdoZW4gY29uZmlnLmpzb24gZG9lc24ndCBleGlzdC4KICAg"
    "IENvbGxlY3RzIG1vZGVsIGNvbm5lY3Rpb24gdHlwZSBhbmQgcGF0aC9rZXkuCiAgICBWYWxpZGF0ZXMgY29ubmVjdGlvbiBiZWZv"
    "cmUgYWNjZXB0aW5nLgogICAgV3JpdGVzIGNvbmZpZy5qc29uIG9uIHN1Y2Nlc3MuCiAgICBDcmVhdGVzIGRlc2t0b3Agc2hvcnRj"
    "dXQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdB"
    "S0VOSU5HIikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCiAgICAgICAgc2VsZi5zZXRGaXhlZFNpemUoNTIwLCA0"
    "MDApCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldFNwYWNpbmcoMTApCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi"
    "4pymIHtERUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyDinKYiKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE0cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDJweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHRpdGxlLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KHRpdGxlKQoKICAgICAgICBzdWIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiQ29uZmlndXJlIHRoZSB2ZXNzZWwg"
    "YmVmb3JlIHtERUNLX05BTUV9IG1heSBhd2FrZW4uXG4iCiAgICAgICAgICAgICJBbGwgc2V0dGluZ3MgYXJlIHN0b3JlZCBsb2Nh"
    "bGx5LiBOb3RoaW5nIGxlYXZlcyB0aGlzIG1hY2hpbmUuIgogICAgICAgICkKICAgICAgICBzdWIuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc3ViLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFn"
    "LkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHN1YikKCiAgICAgICAgIyDilIDilIAgQ29ubmVjdGlvbiB0eXBl"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEFJIENPTk5FQ1RJT04gVFlQRSIpKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8gPSBR"
    "Q29tYm9Cb3goKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8uYWRkSXRlbXMoWwogICAgICAgICAgICAiTG9jYWwgbW9kZWwgZm9s"
    "ZGVyICh0cmFuc2Zvcm1lcnMpIiwKICAgICAgICAgICAgIk9sbGFtYSAobG9jYWwgc2VydmljZSkiLAogICAgICAgICAgICAiQ2xh"
    "dWRlIEFQSSAoQW50aHJvcGljKSIsCiAgICAgICAgICAgICJPcGVuQUkgQVBJIiwKICAgICAgICBdKQogICAgICAgIHNlbGYuX3R5"
    "cGVfY29tYm8uY3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3R5cGVfY2hhbmdlKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX3R5cGVfY29tYm8pCgogICAgICAgICMg4pSA4pSAIER5bmFtaWMgY29ubmVjdGlvbiBmaWVsZHMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCgogICAgICAgICMgUGFn"
    "ZSAwOiBMb2NhbCBwYXRoCiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFIQm94TGF5b3V0KHAwKQogICAgICAg"
    "IGwwLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2xvY2FsX3BhdGggPSBRTGluZUVkaXQoKQogICAg"
    "ICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICByIkQ6XEFJXE1vZGVsc1xkb2xwaGlu"
    "LThiIgogICAgICAgICkKICAgICAgICBidG5fYnJvd3NlID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2Jyb3dz"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX21vZGVsKQogICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9sb2NhbF9wYXRo"
    "KTsgbDAuYWRkV2lkZ2V0KGJ0bl9icm93c2UpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIFBh"
    "Z2UgMTogT2xsYW1hIG1vZGVsIG5hbWUKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUUhCb3hMYXlvdXQocDEp"
    "CiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVsID0gUUxpbmVF"
    "ZGl0KCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwuc2V0UGxhY2Vob2xkZXJUZXh0KCJkb2xwaGluLTIuNi03YiIpCiAgICAg"
    "ICAgbDEuYWRkV2lkZ2V0KHNlbGYuX29sbGFtYV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgogICAg"
    "ICAgICMgUGFnZSAyOiBDbGF1ZGUgQVBJIGtleQogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91"
    "dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5ICAgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0UGxhY2Vob2xkZXJUZXh0KCJzay1hbnQtLi4uIikKICAgICAg"
    "ICBzZWxmLl9jbGF1ZGVfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9j"
    "bGF1ZGVfbW9kZWwgPSBRTGluZUVkaXQoImNsYXVkZS1zb25uZXQtNC02IikKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJB"
    "UEkgS2V5OiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9jbGF1ZGVfa2V5KQogICAgICAgIGwyLmFkZFdpZGdldChRTGFi"
    "ZWwoIk1vZGVsOiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9jbGF1ZGVfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2su"
    "YWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIFBhZ2UgMzogT3BlbkFJCiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9"
    "IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29haV9r"
    "ZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLS4uLiIpCiAgICAg"
    "ICAgc2VsZi5fb2FpX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fb2Fp"
    "X21vZGVsID0gUUxpbmVFZGl0KCJncHQtNG8iKQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KHNlbGYuX29haV9rZXkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KHNlbGYuX29haV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrKQoKICAgICAgICAjIOKUgOKUgCBUZXN0ICsgc3RhdHVzIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHRlc3Rfcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl90ZXN0ID0gX2dvdGhpY19idG4oIlRlc3QgQ29ubmVjdGlvbiIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3Rlc3QuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Rlc3RfY29ubmVjdGlvbikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJs"
    "ID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl90ZXN0KQogICAgICAgIHRlc3Rfcm93"
    "LmFkZFdpZGdldChzZWxmLl9zdGF0dXNfbGJsLCAxKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KHRlc3Rfcm93KQoKICAgICAgICAj"
    "IOKUgOKUgCBGYWNlIFBhY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRkFDRSBQQUNLIChvcHRp"
    "b25hbCDigJQgWklQIGZpbGUpIikpCiAgICAgICAgZmFjZV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fZmFjZV9w"
    "YXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICBm"
    "IkJyb3dzZSB0byB7REVDS19OQU1FfSBmYWNlIHBhY2sgWklQIChvcHRpb25hbCwgY2FuIGFkZCBsYXRlcikiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNv"
    "bG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFk"
    "aXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7"
    "IHBhZGRpbmc6IDZweCAxMHB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2ZhY2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAg"
    "ICAgICBidG5fZmFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX2ZhY2UpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYuX2ZhY2VfcGF0aCkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoYnRuX2ZhY2UpCiAgICAgICAgcm9vdC5hZGRMYXlv"
    "dXQoZmFjZV9yb3cpCgogICAgICAgICMg4pSA4pSAIFNob3J0Y3V0IG9wdGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYiA9IFFDaGVja0JveCgKICAgICAg"
    "ICAgICAgIkNyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IChyZWNvbW1lbmRlZCkiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nob3J0"
    "Y3V0X2NiLnNldENoZWNrZWQoVHJ1ZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zaG9ydGN1dF9jYikKCiAgICAgICAg"
    "IyDilIDilIAgQnV0dG9ucyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFN0cmV0Y2goKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbiA9IF9nb3RoaWNfYnRuKCLinKYgQkVHSU4gQVdBS0VOSU5HIikKICAgICAg"
    "ICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCLinJcg"
    "Q2FuY2VsIikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLmNsaWNrZWQuY29ubmVjdChzZWxmLmFjY2VwdCkKICAgICAgICBidG5f"
    "Y2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChzZWxmLl9idG5fYXdh"
    "a2VuKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX3JvdykK"
    "CiAgICBkZWYgX29uX3R5cGVfY2hhbmdlKHNlbGYsIGlkeDogaW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3N0"
    "YXR1c19sYmwuc2V0VGV4dCgiIikKCiAgICBkZWYgX2Jyb3dzZV9tb2RlbChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGggPSBR"
    "RmlsZURpYWxvZy5nZXRFeGlzdGluZ0RpcmVjdG9yeSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBNb2RlbCBGb2xkZXIiLAog"
    "ICAgICAgICAgICByIkQ6XEFJXE1vZGVscyIKICAgICAgICApCiAgICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fbG9j"
    "YWxfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAgZGVmIF9icm93c2VfZmFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIF8g"
    "PSBRRmlsZURpYWxvZy5nZXRPcGVuRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJTZWxlY3QgRmFjZSBQYWNrIFpJUCIsCiAg"
    "ICAgICAgICAgIHN0cihQYXRoLmhvbWUoKSAvICJEZXNrdG9wIiksCiAgICAgICAgICAgICJaSVAgRmlsZXMgKCouemlwKSIKICAg"
    "ICAgICApCiAgICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFRleHQocGF0aCkKCiAgICBAcHJv"
    "cGVydHkKICAgIGRlZiBmYWNlX3ppcF9wYXRoKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fZmFjZV9wYXRoLnRl"
    "eHQoKS5zdHJpcCgpCgogICAgZGVmIF90ZXN0X2Nvbm5lY3Rpb24oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXNf"
    "bGJsLnNldFRleHQoIlRlc3RpbmcuLi4iKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IgogICAgICAgICkKICAgICAgICBRQXBwbGljYXRpb24ucHJvY2Vzc0V2ZW50cygpCgogICAgICAgIGlkeCA9IHNlbGYuX3R5cGVf"
    "Y29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICBvayAgPSBGYWxzZQogICAgICAgIG1zZyA9ICIiCgogICAgICAgIGlmIGlkeCA9"
    "PSAwOiAgIyBMb2NhbAogICAgICAgICAgICBwYXRoID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAg"
    "ICBpZiBwYXRoIGFuZCBQYXRoKHBhdGgpLmV4aXN0cygpOgogICAgICAgICAgICAgICAgb2sgID0gVHJ1ZQogICAgICAgICAgICAg"
    "ICAgbXNnID0gZiJGb2xkZXIgZm91bmQuIE1vZGVsIHdpbGwgbG9hZCBvbiBzdGFydHVwLiIKICAgICAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgICAgIG1zZyA9ICJGb2xkZXIgbm90IGZvdW5kLiBDaGVjayB0aGUgcGF0aC4iCgogICAgICAgIGVsaWYgaWR4ID09"
    "IDE6ICAjIE9sbGFtYQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVz"
    "dCgKICAgICAgICAgICAgICAgICAgICAiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICAg"
    "ICAgb2sgICA9IHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgICAgICAgICAgbXNnICA9ICJPbGxhbWEgaXMgcnVubmluZyDinJMi"
    "IGlmIG9rIGVsc2UgIk9sbGFtYSBub3QgcmVzcG9uZGluZy4iCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgICAgIG1zZyA9IGYiT2xsYW1hIG5vdCByZWFjaGFibGU6IHtlfSIKCiAgICAgICAgZWxpZiBpZHggPT0gMjogICMg"
    "Q2xhdWRlCiAgICAgICAgICAgIGtleSA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgb2sgID0g"
    "Ym9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay1hbnQiKSkKICAgICAgICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0IGxv"
    "b2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRlciBhIHZhbGlkIENsYXVkZSBBUEkga2V5LiIKCiAgICAgICAgZWxpZiBpZHgg"
    "PT0gMzogICMgT3BlbkFJCiAgICAgICAgICAgIGtleSA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAg"
    "b2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay0iKSkKICAgICAgICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0"
    "IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRlciBhIHZhbGlkIE9wZW5BSSBBUEkga2V5LiIKCiAgICAgICAgY29sb3Ig"
    "PSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19DUklNU09OCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KG1zZykKICAgICAg"
    "ICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTog"
    "MTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4u"
    "c2V0RW5hYmxlZChvaykKCiAgICBkZWYgYnVpbGRfY29uZmlnKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgIiIiQnVpbGQgYW5kIHJl"
    "dHVybiB1cGRhdGVkIGNvbmZpZyBkaWN0IGZyb20gZGlhbG9nIHNlbGVjdGlvbnMuIiIiCiAgICAgICAgY2ZnICAgICA9IF9kZWZh"
    "dWx0X2NvbmZpZygpCiAgICAgICAgaWR4ICAgICA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICB0eXBl"
    "cyAgID0gWyJsb2NhbCIsICJvbGxhbWEiLCAiY2xhdWRlIiwgIm9wZW5haSJdCiAgICAgICAgY2ZnWyJtb2RlbCJdWyJ0eXBlIl0g"
    "PSB0eXBlc1tpZHhdCgogICAgICAgIGlmIGlkeCA9PSAwOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bInBhdGgiXSA9IHNlbGYu"
    "X2xvY2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbGlmIGlkeCA9PSAxOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1b"
    "Im9sbGFtYV9tb2RlbCJdID0gc2VsZi5fb2xsYW1hX21vZGVsLnRleHQoKS5zdHJpcCgpIG9yICJkb2xwaGluLTIuNi03YiIKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAyOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5fY2xhdWRlX2tl"
    "eS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5fY2xhdWRlX21vZGVs"
    "LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAiY2xhdWRlIgogICAgICAgIGVs"
    "aWYgaWR4ID09IDM6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9vYWlfa2V5LnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9vYWlfbW9kZWwudGV4dCgpLnN0cmlw"
    "KCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJvcGVuYWkiCgogICAgICAgIGNmZ1siZmlyc3RfcnVu"
    "Il0gPSBGYWxzZQogICAgICAgIHJldHVybiBjZmcKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjcmVhdGVfc2hvcnRjdXQoc2VsZikg"
    "LT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fc2hvcnRjdXRfY2IuaXNDaGVja2VkKCkKCgojIOKUgOKUgCBKT1VSTkFMIFNJ"
    "REVCQVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvdXJuYWxTaWRlYmFyKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBDb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgbmV4dCB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KICAgIFRvcDogc2Vzc2lvbiBj"
    "b250cm9scyAoY3VycmVudCBzZXNzaW9uIG5hbWUsIHNhdmUvbG9hZCBidXR0b25zLAogICAgICAgICBhdXRvc2F2ZSBpbmRpY2F0"
    "b3IpLgogICAgQm9keTogc2Nyb2xsYWJsZSBzZXNzaW9uIGxpc3Qg4oCUIGRhdGUsIEFJIG5hbWUsIG1lc3NhZ2UgY291bnQuCiAg"
    "ICBDb2xsYXBzZXMgbGVmdHdhcmQgdG8gYSB0aGluIHN0cmlwLgoKICAgIFNpZ25hbHM6CiAgICAgICAgc2Vzc2lvbl9sb2FkX3Jl"
    "cXVlc3RlZChzdHIpICAg4oCUIGRhdGUgc3RyaW5nIG9mIHNlc3Npb24gdG8gbG9hZAogICAgICAgIHNlc3Npb25fY2xlYXJfcmVx"
    "dWVzdGVkKCkgICAgIOKAlCByZXR1cm4gdG8gY3VycmVudCBzZXNzaW9uCiAgICAiIiIKCiAgICBzZXNzaW9uX2xvYWRfcmVxdWVz"
    "dGVkICA9IFNpZ25hbChzdHIpCiAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCA9IFNpZ25hbCgpCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIHNlc3Npb25fbWdyOiAiU2Vzc2lvbk1hbmFnZXIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9tZ3IgPSBzZXNzaW9uX21ncgogICAgICAgIHNlbGYuX2V4cGFuZGVkICAg"
    "ID0gVHJ1ZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWko"
    "c2VsZikgLT4gTm9uZToKICAgICAgICAjIFVzZSBhIGhvcml6b250YWwgcm9vdCBsYXlvdXQg4oCUIGNvbnRlbnQgb24gbGVmdCwg"
    "dG9nZ2xlIHN0cmlwIG9uIHJpZ2h0CiAgICAgICAgcm9vdCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250"
    "ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyDilIDilIAgQ29sbGFw"
    "c2UgdG9nZ2xlIHN0cmlwIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3RvZ2ds"
    "ZV9zdHJpcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcC5zZXRGaXhlZFdpZHRoKDIwKQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9zdHJpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1y"
    "aWdodDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHRzX2xheW91dCA9IFFWQm94TGF5b3V0"
    "KHNlbGYuX3RvZ2dsZV9zdHJpcCkKICAgICAgICB0c19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDgsIDAsIDgpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldEZpeGVkU2l6ZSgx"
    "OCwgMTgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fdG9nZ2xl"
    "X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQogICAgICAgIHRzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xl"
    "X2J0bikKICAgICAgICB0c19sYXlvdXQuYWRkU3RyZXRjaCgpCgogICAgICAgICMg4pSA4pSAIE1haW4gY29udGVudCDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9j"
    "b250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNaW5pbXVtV2lkdGgoMTgwKQogICAgICAgIHNlbGYu"
    "X2NvbnRlbnQuc2V0TWF4aW11bVdpZHRoKDIyMCkKICAgICAgICBjb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2Nv"
    "bnRlbnQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgY29udGVu"
    "dF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIFNlY3Rpb24gbGFiZWwKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSk9VUk5BTCIpKQoKICAgICAgICAjIEN1cnJlbnQgc2Vzc2lvbiBpbmZvCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbl9uYW1lID0gUUxhYmVsKCJOZXcgU2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX25hbWUuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vz"
    "c2lvbl9uYW1lKQoKICAgICAgICAjIFNhdmUgLyBMb2FkIHJvdwogICAgICAgIGN0cmxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuX2J0bl9zYXZlID0gX2dvdGhpY19idG4oIvCfkr4iKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldEZpeGVkU2l6"
    "ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VG9vbFRpcCgiU2F2ZSBzZXNzaW9uIG5vdyIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2xvYWQgPSBfZ290aGljX2J0bigi8J+TgiIpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0Rml4ZWRTaXplKDMyLCAy"
    "NCkKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRUb29sVGlwKCJCcm93c2UgYW5kIGxvYWQgYSBwYXN0IHNlc3Npb24iKQogICAg"
    "ICAgIHNlbGYuX2F1dG9zYXZlX2RvdCA9IFFMYWJlbCgi4pePIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoIkF1dG9zYXZlIHN0YXR1cyIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3NhdmUpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlKQogICAgICAgIGN0"
    "cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYXV0b3NhdmVf"
    "ZG90KQogICAgICAgIGN0cmxfcm93LmFkZFN0cmV0Y2goKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZExheW91dChjdHJsX3Jv"
    "dykKCiAgICAgICAgIyBKb3VybmFsIGxvYWRlZCBpbmRpY2F0b3IKICAgICAgICBzZWxmLl9qb3VybmFsX2xibCA9IFFMYWJlbCgi"
    "IikKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19QVVJQTEV9"
    "OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5"
    "bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfbGJsKQoKICAgICAgICAjIENsZWFyIGpvdXJuYWwgYnV0dG9u"
    "IChoaWRkZW4gd2hlbiBub3QgbG9hZGVkKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsID0gX2dvdGhpY19idG4oIuKc"
    "lyBSZXR1cm4gdG8gUHJlc2VudCIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKICAg"
    "ICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fY2xlYXJfam91cm5hbCkKICAgICAg"
    "ICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwpCgogICAgICAgICMgRGl2aWRlcgogICAg"
    "ICAgIGRpdiA9IFFGcmFtZSgpCiAgICAgICAgZGl2LnNldEZyYW1lU2hhcGUoUUZyYW1lLlNoYXBlLkhMaW5lKQogICAgICAgIGRp"
    "di5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdl"
    "dChkaXYpCgogICAgICAgICMgU2Vzc2lvbiBsaXN0CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xi"
    "bCgi4p2nIFBBU1QgU0VTU0lPTlMiKSkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbl9saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6"
    "IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgICAgIGYiUUxpc3RXaWRnZXQ6"
    "Oml0ZW06c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyB9fSIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykKICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX2xpc3QuaXRlbUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIGNvbnRlbnRf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX2xpc3QsIDEpCgogICAgICAgICMgQWRkIGNvbnRlbnQgYW5kIHRvZ2dsZSBz"
    "dHJpcCB0byB0aGUgcm9vdCBob3Jpem9udGFsIGxheW91dAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUo"
    "c2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiIGlmIHNlbGYuX2V4cGFuZGVkIGVs"
    "c2UgIuKWtiIpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAg"
    "ICAgICBpZiBwIGFuZCBwLmxheW91dCgpOgogICAgICAgICAgICBwLmxheW91dCgpLmFjdGl2YXRlKCkKCiAgICBkZWYgcmVmcmVz"
    "aChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlc3Npb25zID0gc2VsZi5fc2Vzc2lvbl9tZ3IubGlzdF9zZXNzaW9ucygpCiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9saXN0LmNsZWFyKCkKICAgICAgICBmb3IgcyBpbiBzZXNzaW9uczoKICAgICAgICAgICAgZGF0ZV9z"
    "dHIgPSBzLmdldCgiZGF0ZSIsIiIpCiAgICAgICAgICAgIG5hbWUgICAgID0gcy5nZXQoIm5hbWUiLCBkYXRlX3N0cilbOjMwXQog"
    "ICAgICAgICAgICBjb3VudCAgICA9IHMuZ2V0KCJtZXNzYWdlX2NvdW50IiwgMCkKICAgICAgICAgICAgaXRlbSA9IFFMaXN0V2lk"
    "Z2V0SXRlbShmIntkYXRlX3N0cn1cbntuYW1lfSAoe2NvdW50fSBtc2dzKSIpCiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5J"
    "dGVtRGF0YVJvbGUuVXNlclJvbGUsIGRhdGVfc3RyKQogICAgICAgICAgICBpdGVtLnNldFRvb2xUaXAoZiJEb3VibGUtY2xpY2sg"
    "dG8gbG9hZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSIpCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5hZGRJdGVtKGl0"
    "ZW0pCgogICAgZGVmIHNldF9zZXNzaW9uX25hbWUoc2VsZiwgbmFtZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25fbmFtZS5zZXRUZXh0KG5hbWVbOjUwXSBvciAiTmV3IFNlc3Npb24iKQoKICAgIGRlZiBzZXRfYXV0b3NhdmVfaW5kaWNhdG9y"
    "KHNlbGYsIHNhdmVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19HUkVFTiBpZiBzYXZlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlwKAog"
    "ICAgICAgICAgICAiQXV0b3NhdmVkIiBpZiBzYXZlZCBlbHNlICJQZW5kaW5nIGF1dG9zYXZlIgogICAgICAgICkKCiAgICBkZWYg"
    "c2V0X2pvdXJuYWxfbG9hZGVkKHNlbGYsIGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwu"
    "c2V0VGV4dChmIvCfk5YgSm91cm5hbDoge2RhdGVfc3RyfSIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0Vmlz"
    "aWJsZShUcnVlKQoKICAgIGRlZiBjbGVhcl9qb3VybmFsX2luZGljYXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2pv"
    "dXJuYWxfbGJsLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKCiAg"
    "ICBkZWYgX2RvX3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX21nci5zYXZlKCkKICAgICAgICBzZWxm"
    "LnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAgIHNlbGYuX2J0bl9zYXZl"
    "LnNldFRleHQoIuKckyIpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMCwgbGFtYmRhOiBzZWxmLl9idG5fc2F2ZS5zZXRU"
    "ZXh0KCLwn5K+IikpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwMCwgbGFtYmRhOiBzZWxmLnNldF9hdXRvc2F2ZV9pbmRp"
    "Y2F0b3IoRmFsc2UpKQoKICAgIGRlZiBfZG9fbG9hZChzZWxmKSAtPiBOb25lOgogICAgICAgICMgVHJ5IHNlbGVjdGVkIGl0ZW0g"
    "Zmlyc3QKICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBpZiBub3QgaXRlbToK"
    "ICAgICAgICAgICAgIyBJZiBub3RoaW5nIHNlbGVjdGVkLCB0cnkgdGhlIGZpcnN0IGl0ZW0KICAgICAgICAgICAgaWYgc2VsZi5f"
    "c2Vzc2lvbl9saXN0LmNvdW50KCkgPiAwOgogICAgICAgICAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtKDAp"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0Q3VycmVudEl0ZW0oaXRlbSkKICAgICAgICBpZiBpdGVtOgog"
    "ICAgICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIHNlbGYu"
    "c2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfb25fc2Vzc2lvbl9jbGljayhzZWxmLCBpdGVt"
    "KSAtPiBOb25lOgogICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICBz"
    "ZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYgX2RvX2NsZWFyX2pvdXJuYWwoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmVtaXQoKQogICAgICAgIHNlbGYuY2xlYXJfam91"
    "cm5hbF9pbmRpY2F0b3IoKQoKCiMg4pSA4pSAIFRPUlBPUiBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgVG9ycG9yUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRocmVlLXN0YXRlIHN1c3BlbnNpb24gdG9nZ2xlOiBB"
    "V0FLRSB8IEFVVE8gfCBTVVNQRU5ECgogICAgQVdBS0UgIOKAlCBtb2RlbCBsb2FkZWQsIGF1dG8tdG9ycG9yIGRpc2FibGVkLCBp"
    "Z25vcmVzIFZSQU0gcHJlc3N1cmUKICAgIEFVVE8gICDigJQgbW9kZWwgbG9hZGVkLCBtb25pdG9ycyBWUkFNIHByZXNzdXJlLCBh"
    "dXRvLXRvcnBvciBpZiBzdXN0YWluZWQKICAgIFNVU1BFTkQg4oCUIG1vZGVsIHVubG9hZGVkLCBzdGF5cyBzdXNwZW5kZWQgdW50"
    "aWwgbWFudWFsbHkgY2hhbmdlZAoKICAgIFNpZ25hbHM6CiAgICAgICAgc3RhdGVfY2hhbmdlZChzdHIpICDigJQgIkFXQUtFIiB8"
    "ICJBVVRPIiB8ICJTVVNQRU5EIgogICAgIiIiCgogICAgc3RhdGVfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgU1RBVEVTID0g"
    "WyJBV0FLRSIsICJBVVRPIiwgIlNVU1BFTkQiXQoKICAgIFNUQVRFX1NUWUxFUyA9IHsKICAgICAgICAiQVdBS0UiOiB7CiAgICAg"
    "ICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzJhMWEwNTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAg"
    "ICAgICAiaW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAg"
    "ICAgICAgICAgImxhYmVsIjogICAgIuKYgCBBV0FLRSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3RpdmUuIEF1"
    "dG8tdG9ycG9yIGRpc2FibGVkLiIsCiAgICAgICAgfSwKICAgICAgICAiQVVUTyI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAg"
    "ZiJiYWNrZ3JvdW5kOiAjMWExMDA1OyBjb2xvcjogI2NjODgyMjsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkICNjYzg4MjI7IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6"
    "ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBmImJh"
    "Y2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250"
    "LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjogICAg"
    "IuKXiSBBVVRPIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by1zdXNwZW5kIG9uIFZSQU0gcHJl"
    "c3N1cmUuIiwKICAgICAgICB9LAogICAgICAgICJTVVNQRU5EIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91"
    "bmQ6IHtDX1BVUlBMRV9ESU19OyBjb2xvcjoge0NfUFVSUExFfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX1BVUlBMRX07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJm"
    "b250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjog"
    "ICAgZiLimrAge1VJX1NVU1BFTlNJT05fTEFCRUwuc3RyaXAoKSBpZiBzdHIoVUlfU1VTUEVOU0lPTl9MQUJFTCkuc3RyaXAoKSBl"
    "bHNlICdTdXNwZW5kJ30iLAogICAgICAgICAgICAidG9vbHRpcCI6ICBmIk1vZGVsIHVubG9hZGVkLiB7REVDS19OQU1FfSBzbGVl"
    "cHMgdW50aWwgbWFudWFsbHkgYXdha2VuZWQuIiwKICAgICAgICB9LAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fY3VycmVudCA9ICJBV0FLRSIK"
    "ICAgICAgICBzZWxmLl9idXR0b25zOiBkaWN0W3N0ciwgUVB1c2hCdXR0b25dID0ge30KICAgICAgICBsYXlvdXQgPSBRSEJveExh"
    "eW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0"
    "U3BhY2luZygyKQoKICAgICAgICBmb3Igc3RhdGUgaW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIGJ0biA9IFFQdXNoQnV0dG9u"
    "KHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsibGFiZWwiXSkKICAgICAgICAgICAgYnRuLnNldFRvb2xUaXAoc2VsZi5TVEFURV9T"
    "VFlMRVNbc3RhdGVdWyJ0b29sdGlwIl0pCiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICAgICAgYnRu"
    "LmNsaWNrZWQuY29ubmVjdChsYW1iZGEgY2hlY2tlZCwgcz1zdGF0ZTogc2VsZi5fc2V0X3N0YXRlKHMpKQogICAgICAgICAgICBz"
    "ZWxmLl9idXR0b25zW3N0YXRlXSA9IGJ0bgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJ0bikKCiAgICAgICAgc2VsZi5f"
    "YXBwbHlfc3R5bGVzKCkKCiAgICBkZWYgX3NldF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHN0"
    "YXRlID09IHNlbGYuX2N1cnJlbnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBzdGF0ZQogICAg"
    "ICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCiAgICAgICAgc2VsZi5zdGF0ZV9jaGFuZ2VkLmVtaXQoc3RhdGUpCgogICAgZGVmIF9h"
    "cHBseV9zdHlsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Igc3RhdGUsIGJ0biBpbiBzZWxmLl9idXR0b25zLml0ZW1zKCk6"
    "CiAgICAgICAgICAgIHN0eWxlX2tleSA9ICJhY3RpdmUiIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQgZWxzZSAiaW5hY3RpdmUi"
    "CiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVtzdHlsZV9rZXldKQoKICAgIEBw"
    "cm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfc3RhdGUoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9jdXJyZW50Cgog"
    "ICAgZGVmIHNldF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBzdGF0ZSBwcm9ncmFtbWF0"
    "aWNhbGx5IChlLmcuIGZyb20gYXV0by10b3Jwb3IgZGV0ZWN0aW9uKS4iIiIKICAgICAgICBpZiBzdGF0ZSBpbiBzZWxmLlNUQVRF"
    "UzoKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXRlKHN0YXRlKQoKCmNsYXNzIFNldHRpbmdzU2VjdGlvbihRV2lkZ2V0KToKICAg"
    "ICIiIlNpbXBsZSBjb2xsYXBzaWJsZSBzZWN0aW9uIHVzZWQgYnkgU2V0dGluZ3NUYWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIHRpdGxlOiBzdHIsIHBhcmVudD1Ob25lLCBleHBhbmRlZDogYm9vbCA9IFRydWUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gZXhwYW5kZWQKCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNl"
    "bGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkK"
    "CiAgICAgICAgc2VsZi5faGVhZGVyX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnNldFRleHQo"
    "ZiLilrwge3RpdGxlfSIgaWYgZXhwYW5kZWQgZWxzZSBmIuKWtiB7dGl0bGV9IikKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA2cHg7IHRleHQtYWxpZ246IGxlZnQ7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICApCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "dG9nZ2xlKQoKICAgICAgICBzZWxmLl9jb250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQgPSBR"
    "VkJveExheW91dChzZWxmLl9jb250ZW50KQogICAgICAgIHNlbGYuX2NvbnRlbnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg4"
    "LCA4LCA4LCA4KQogICAgICAgIHNlbGYuX2NvbnRlbnRfbGF5b3V0LnNldFNwYWNpbmcoOCkKICAgICAgICBzZWxmLl9jb250ZW50"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgYm9yZGVyLXRvcDogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShleHBhbmRl"
    "ZCkKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5faGVhZGVyX2J0bikKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9j"
    "b250ZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNvbnRlbnRfbGF5b3V0KHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAg"
    "IHJldHVybiBzZWxmLl9jb250ZW50X2xheW91dAoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "ZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnNldFRleHQoCiAgICAgICAgICAg"
    "IHNlbGYuX2hlYWRlcl9idG4udGV4dCgpLnJlcGxhY2UoIuKWvCIsICLilrYiLCAxKQogICAgICAgICAgICBpZiBub3Qgc2VsZi5f"
    "ZXhwYW5kZWQgZWxzZQogICAgICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnRleHQoKS5yZXBsYWNlKCLilrYiLCAi4pa8IiwgMSkK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQoKCmNsYXNzIFNldHRpbmdz"
    "VGFiKFFXaWRnZXQpOgogICAgIiIiRGVjay13aWRlIHJ1bnRpbWUgc2V0dGluZ3MgdGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBkZWNrX3dpbmRvdzogIkVjaG9EZWNrIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX2RlY2sgPSBkZWNrX3dpbmRvdwogICAgICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnk6IGxpc3RbZGlj"
    "dF0gPSBbXQogICAgICAgIHNlbGYuX3NlY3Rpb25fd2lkZ2V0czogZGljdFtzdHIsIFNldHRpbmdzU2VjdGlvbl0gPSB7fQoKICAg"
    "ICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICBzY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2Nyb2xsLnNl"
    "dFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNjcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KFF0LlNjcm9s"
    "bEJhclBvbGljeS5TY3JvbGxCYXJBbHdheXNPZmYpCiAgICAgICAgc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7"
    "Q19CR307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNjcm9sbCkK"
    "CiAgICAgICAgYm9keSA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0ID0gUVZCb3hMYXlvdXQoYm9keSkKICAg"
    "ICAgICBzZWxmLl9ib2R5X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBzZWxmLl9ib2R5X2xh"
    "eW91dC5zZXRTcGFjaW5nKDgpCiAgICAgICAgc2Nyb2xsLnNldFdpZGdldChib2R5KQoKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9j"
    "b3JlX3NlY3Rpb25zKCkKCiAgICBkZWYgX3JlZ2lzdGVyX3NlY3Rpb24oc2VsZiwgKiwgc2VjdGlvbl9pZDogc3RyLCB0aXRsZTog"
    "c3RyLCBjYXRlZ29yeTogc3RyLCBzb3VyY2Vfb3duZXI6IHN0ciwgc29ydF9rZXk6IGludCwgYnVpbGRlcikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9zZWN0aW9uX3JlZ2lzdHJ5LmFwcGVuZCh7CiAgICAgICAgICAgICJzZWN0aW9uX2lkIjogc2VjdGlvbl9pZCwK"
    "ICAgICAgICAgICAgInRpdGxlIjogdGl0bGUsCiAgICAgICAgICAgICJjYXRlZ29yeSI6IGNhdGVnb3J5LAogICAgICAgICAgICAi"
    "c291cmNlX293bmVyIjogc291cmNlX293bmVyLAogICAgICAgICAgICAic29ydF9rZXkiOiBzb3J0X2tleSwKICAgICAgICAgICAg"
    "ImJ1aWxkZXIiOiBidWlsZGVyLAogICAgICAgIH0pCgogICAgZGVmIF9yZWdpc3Rlcl9jb3JlX3NlY3Rpb25zKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0ic3lzdGVtX3NldHRpbmdz"
    "IiwKICAgICAgICAgICAgdGl0bGU9IlN5c3RlbSBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVnb3J5PSJjb3JlIiwKICAgICAg"
    "ICAgICAgc291cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAgICAgICAgICBzb3J0X2tleT0xMDAsCiAgICAgICAgICAgIGJ1"
    "aWxkZXI9c2VsZi5fYnVpbGRfc3lzdGVtX3NlY3Rpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24o"
    "CiAgICAgICAgICAgIHNlY3Rpb25faWQ9ImludGVncmF0aW9uX3NldHRpbmdzIiwKICAgICAgICAgICAgdGl0bGU9IkludGVncmF0"
    "aW9uIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tf"
    "cnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTIwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF9pbnRlZ3Jh"
    "dGlvbl9zZWN0aW9uLAogICAgICAgICkKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9u"
    "X2lkPSJ1aV9zZXR0aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJVSSBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVnb3J5PSJj"
    "b3JlIiwKICAgICAgICAgICAgc291cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAgICAgICAgICBzb3J0X2tleT0zMDAsCiAg"
    "ICAgICAgICAgIGJ1aWxkZXI9c2VsZi5fYnVpbGRfdWlfc2VjdGlvbiwKICAgICAgICApCgogICAgICAgIGZvciBtZXRhIGluIHNv"
    "cnRlZChzZWxmLl9zZWN0aW9uX3JlZ2lzdHJ5LCBrZXk9bGFtYmRhIG06IG0uZ2V0KCJzb3J0X2tleSIsIDk5OTkpKToKICAgICAg"
    "ICAgICAgc2VjdGlvbiA9IFNldHRpbmdzU2VjdGlvbihtZXRhWyJ0aXRsZSJdLCBleHBhbmRlZD1UcnVlKQogICAgICAgICAgICBz"
    "ZWxmLl9ib2R5X2xheW91dC5hZGRXaWRnZXQoc2VjdGlvbikKICAgICAgICAgICAgc2VsZi5fc2VjdGlvbl93aWRnZXRzW21ldGFb"
    "InNlY3Rpb25faWQiXV0gPSBzZWN0aW9uCiAgICAgICAgICAgIG1ldGFbImJ1aWxkZXIiXShzZWN0aW9uLmNvbnRlbnRfbGF5b3V0"
    "KQoKICAgICAgICBzZWxmLl9ib2R5X2xheW91dC5hZGRTdHJldGNoKDEpCgogICAgZGVmIF9idWlsZF9zeXN0ZW1fc2VjdGlvbihz"
    "ZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX2RlY2suX3RvcnBvcl9wYW5lbCBpcyBu"
    "b3QgTm9uZToKICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIk9wZXJhdGlvbmFsIE1vZGUiKSkKICAgICAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZWNrLl90b3Jwb3JfcGFuZWwpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxh"
    "YmVsKCJJZGxlIikpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZWNrLl9pZGxlX2J0bikKCiAgICAgICAgc2V0dGlu"
    "Z3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHR6X2F1dG8gPSBib29sKHNldHRpbmdzLmdldCgidGltZXpvbmVf"
    "YXV0b19kZXRlY3QiLCBUcnVlKSkKICAgICAgICB0el9vdmVycmlkZSA9IHN0cihzZXR0aW5ncy5nZXQoInRpbWV6b25lX292ZXJy"
    "aWRlIiwgIiIpIG9yICIiKS5zdHJpcCgpCgogICAgICAgIHR6X2F1dG9fY2hrID0gUUNoZWNrQm94KCJBdXRvLWRldGVjdCBsb2Nh"
    "bC9zeXN0ZW0gdGltZSB6b25lIikKICAgICAgICB0el9hdXRvX2Noay5zZXRDaGVja2VkKHR6X2F1dG8pCiAgICAgICAgdHpfYXV0"
    "b19jaGsudG9nZ2xlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF90aW1lem9uZV9hdXRvX2RldGVjdCkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHR6X2F1dG9fY2hrKQoKICAgICAgICB0el9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgdHpfcm93LmFkZFdp"
    "ZGdldChRTGFiZWwoIk1hbnVhbCBUaW1lIFpvbmUgT3ZlcnJpZGU6IikpCiAgICAgICAgdHpfY29tYm8gPSBRQ29tYm9Cb3goKQog"
    "ICAgICAgIHR6X2NvbWJvLnNldEVkaXRhYmxlKFRydWUpCiAgICAgICAgdHpfb3B0aW9ucyA9IFsKICAgICAgICAgICAgIkFtZXJp"
    "Y2EvQ2hpY2FnbyIsICJBbWVyaWNhL05ld19Zb3JrIiwgIkFtZXJpY2EvTG9zX0FuZ2VsZXMiLAogICAgICAgICAgICAiQW1lcmlj"
    "YS9EZW52ZXIiLCAiVVRDIgogICAgICAgIF0KICAgICAgICB0el9jb21iby5hZGRJdGVtcyh0el9vcHRpb25zKQogICAgICAgIGlm"
    "IHR6X292ZXJyaWRlOgogICAgICAgICAgICBpZiB0el9jb21iby5maW5kVGV4dCh0el9vdmVycmlkZSkgPCAwOgogICAgICAgICAg"
    "ICAgICAgdHpfY29tYm8uYWRkSXRlbSh0el9vdmVycmlkZSkKICAgICAgICAgICAgdHpfY29tYm8uc2V0Q3VycmVudFRleHQodHpf"
    "b3ZlcnJpZGUpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgdHpfY29tYm8uc2V0Q3VycmVudFRleHQoIkFtZXJpY2EvQ2hpY2Fn"
    "byIpCiAgICAgICAgdHpfY29tYm8uc2V0RW5hYmxlZChub3QgdHpfYXV0bykKICAgICAgICB0el9jb21iby5jdXJyZW50VGV4dENo"
    "YW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfdGltZXpvbmVfb3ZlcnJpZGUpCiAgICAgICAgdHpfYXV0b19jaGsudG9nZ2xl"
    "ZC5jb25uZWN0KGxhbWJkYSBlbmFibGVkOiB0el9jb21iby5zZXRFbmFibGVkKG5vdCBlbmFibGVkKSkKICAgICAgICB0el9yb3cu"
    "YWRkV2lkZ2V0KHR6X2NvbWJvLCAxKQogICAgICAgIHR6X2hvc3QgPSBRV2lkZ2V0KCkKICAgICAgICB0el9ob3N0LnNldExheW91"
    "dCh0el9yb3cpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0el9ob3N0KQoKICAgIGRlZiBfYnVpbGRfaW50ZWdyYXRpb25fc2Vj"
    "dGlvbihzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGlu"
    "Z3MiLCB7fSkKICAgICAgICBnb29nbGVfc2Vjb25kcyA9IGludChzZXR0aW5ncy5nZXQoImdvb2dsZV9pbmJvdW5kX2ludGVydmFs"
    "X21zIiwgMzAwMDApKSAvLyAxMDAwCiAgICAgICAgZ29vZ2xlX3NlY29uZHMgPSBtYXgoNSwgbWluKDYwMCwgZ29vZ2xlX3NlY29u"
    "ZHMpKQogICAgICAgIGVtYWlsX21pbnV0ZXMgPSBtYXgoMSwgaW50KHNldHRpbmdzLmdldCgiZW1haWxfcmVmcmVzaF9pbnRlcnZh"
    "bF9tcyIsIDMwMDAwMCkpIC8vIDYwMDAwKQoKICAgICAgICBnb29nbGVfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGdvb2ds"
    "ZV9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiR29vZ2xlIHJlZnJlc2ggaW50ZXJ2YWwgKHNlY29uZHMpOiIpKQogICAgICAgIGdvb2ds"
    "ZV9ib3ggPSBRU3BpbkJveCgpCiAgICAgICAgZ29vZ2xlX2JveC5zZXRSYW5nZSg1LCA2MDApCiAgICAgICAgZ29vZ2xlX2JveC5z"
    "ZXRWYWx1ZShnb29nbGVfc2Vjb25kcykKICAgICAgICBnb29nbGVfYm94LnZhbHVlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2su"
    "X3NldF9nb29nbGVfcmVmcmVzaF9zZWNvbmRzKQogICAgICAgIGdvb2dsZV9yb3cuYWRkV2lkZ2V0KGdvb2dsZV9ib3gsIDEpCiAg"
    "ICAgICAgZ29vZ2xlX2hvc3QgPSBRV2lkZ2V0KCkKICAgICAgICBnb29nbGVfaG9zdC5zZXRMYXlvdXQoZ29vZ2xlX3JvdykKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KGdvb2dsZV9ob3N0KQoKICAgICAgICBlbWFpbF9yb3cgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgZW1haWxfcm93LmFkZFdpZGdldChRTGFiZWwoIkVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgKG1pbnV0ZXMpOiIpKQogICAgICAg"
    "IGVtYWlsX2JveCA9IFFDb21ib0JveCgpCiAgICAgICAgZW1haWxfYm94LnNldEVkaXRhYmxlKFRydWUpCiAgICAgICAgZW1haWxf"
    "Ym94LmFkZEl0ZW1zKFsiMSIsICI1IiwgIjEwIiwgIjE1IiwgIjMwIiwgIjYwIl0pCiAgICAgICAgZW1haWxfYm94LnNldEN1cnJl"
    "bnRUZXh0KHN0cihlbWFpbF9taW51dGVzKSkKICAgICAgICBlbWFpbF9ib3guY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZGVjay5fc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQpCiAgICAgICAgZW1haWxfcm93LmFkZFdpZGdldChl"
    "bWFpbF9ib3gsIDEpCiAgICAgICAgZW1haWxfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIGVtYWlsX2hvc3Quc2V0TGF5b3V0KGVt"
    "YWlsX3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGVtYWlsX2hvc3QpCgogICAgICAgIG5vdGUgPSBRTGFiZWwoIkVtYWls"
    "IHBvbGxpbmcgZm91bmRhdGlvbiBpcyBjb25maWd1cmF0aW9uLW9ubHkgdW5sZXNzIGFuIGVtYWlsIGJhY2tlbmQgaXMgZW5hYmxl"
    "ZC4iKQogICAgICAgIG5vdGUuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChub3RlKQoKICAgIGRlZiBfYnVpbGRfdWlfc2VjdGlvbihzZWxmLCBsYXlvdXQ6IFFWQm94"
    "TGF5b3V0KSAtPiBOb25lOgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJXaW5kb3cgU2hlbGwiKSkKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2ZzX2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2Js"
    "X2J0bikKCgpjbGFzcyBEaWNlR2x5cGgoUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgMkQgc2lsaG91ZXR0ZSByZW5kZXJlciBmb3Ig"
    "ZGllLXR5cGUgcmVjb2duaXRpb24uIiIiCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGllX3R5cGU6IHN0ciA9ICJkMjAiLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGllX3R5cGUgPSBkaWVfdHlw"
    "ZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoNzAsIDcwKQogICAgICAgIHNlbGYuc2V0TWF4aW11bVNpemUoOTAsIDkwKQoK"
    "ICAgIGRlZiBzZXRfZGllX3R5cGUoc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaWVfdHlwZSA9"
    "IGRpZV90eXBlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KToKICAgICAgICBw"
    "YWludGVyID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwYWludGVyLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5B"
    "bnRpYWxpYXNpbmcpCiAgICAgICAgcmVjdCA9IHNlbGYucmVjdCgpLmFkanVzdGVkKDgsIDgsIC04LCAtOCkKCiAgICAgICAgZGll"
    "ID0gc2VsZi5fZGllX3R5cGUKICAgICAgICBsaW5lID0gUUNvbG9yKENfR09MRCkKICAgICAgICBmaWxsID0gUUNvbG9yKENfQkcy"
    "KQogICAgICAgIGFjY2VudCA9IFFDb2xvcihDX0NSSU1TT04pCgogICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQZW4obGluZSwgMikp"
    "CiAgICAgICAgcGFpbnRlci5zZXRCcnVzaChmaWxsKQoKICAgICAgICBwdHMgPSBbXQogICAgICAgIGlmIGRpZSA9PSAiZDQiOgog"
    "ICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAog"
    "ICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChy"
    "ZWN0LnJpZ2h0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgPT0gImQ2IjoKICAgICAg"
    "ICAgICAgcGFpbnRlci5kcmF3Um91bmRlZFJlY3QocmVjdCwgNCwgNCkKICAgICAgICBlbGlmIGRpZSA9PSAiZDgiOgogICAgICAg"
    "ICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAg"
    "ICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVj"
    "dC5jZW50ZXIoKS54KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwgcmVjdC5j"
    "ZW50ZXIoKS55KCkpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgaW4gKCJkMTAiLCAiZDEwMCIpOgogICAgICAgICAg"
    "ICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAgICAg"
    "ICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0"
    "LmxlZnQoKSwgcmVjdC5ib3R0b20oKSAtIDEyKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVj"
    "dC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmJvdHRvbSgpIC0gMTIpLAogICAg"
    "ICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDgsIHJlY3QudG9wKCkgKyAxNiksCiAgICAgICAgICAgIF0KICAgICAg"
    "ICBlbGlmIGRpZSA9PSAiZDEyIjoKICAgICAgICAgICAgY3ggPSByZWN0LmNlbnRlcigpLngoKTsgY3kgPSByZWN0LmNlbnRlcigp"
    "LnkoKQogICAgICAgICAgICByeCA9IHJlY3Qud2lkdGgoKSAvIDI7IHJ5ID0gcmVjdC5oZWlnaHQoKSAvIDIKICAgICAgICAgICAg"
    "Zm9yIGkgaW4gcmFuZ2UoNSk6CiAgICAgICAgICAgICAgICBhID0gKG1hdGgucGkgKiAyICogaSAvIDUpIC0gKG1hdGgucGkgLyAy"
    "KQogICAgICAgICAgICAgICAgcHRzLmFwcGVuZChRUG9pbnQoaW50KGN4ICsgcnggKiBtYXRoLmNvcyhhKSksIGludChjeSArIHJ5"
    "ICogbWF0aC5zaW4oYSkpKSkKICAgICAgICBlbHNlOiAgIyBkMjAKICAgICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAg"
    "UVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSAr"
    "IDEwLCByZWN0LnRvcCgpICsgMTQpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmNlbnRlcigpLnko"
    "KSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyAxMCwgcmVjdC5ib3R0b20oKSAtIDE0KSwKICAgICAgICAg"
    "ICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVj"
    "dC5yaWdodCgpIC0gMTAsIHJlY3QuYm90dG9tKCkgLSAxNCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCBy"
    "ZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gMTAsIHJlY3QudG9wKCkgKyAx"
    "NCksCiAgICAgICAgICAgIF0KCiAgICAgICAgaWYgcHRzOgogICAgICAgICAgICBwYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAg"
    "ICAgICAgcGF0aC5tb3ZlVG8ocHRzWzBdKQogICAgICAgICAgICBmb3IgcCBpbiBwdHNbMTpdOgogICAgICAgICAgICAgICAgcGF0"
    "aC5saW5lVG8ocCkKICAgICAgICAgICAgcGF0aC5jbG9zZVN1YnBhdGgoKQogICAgICAgICAgICBwYWludGVyLmRyYXdQYXRoKHBh"
    "dGgpCgogICAgICAgIHBhaW50ZXIuc2V0UGVuKFFQZW4oYWNjZW50LCAxKSkKICAgICAgICB0eHQgPSAiJSIgaWYgZGllID09ICJk"
    "MTAwIiBlbHNlIGRpZS5yZXBsYWNlKCJkIiwgIiIpCiAgICAgICAgcGFpbnRlci5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgMTIs"
    "IFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBwYWludGVyLmRyYXdUZXh0KHJlY3QsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25D"
    "ZW50ZXIsIHR4dCkKCgpjbGFzcyBEaWNlVHJheURpZShRRnJhbWUpOgogICAgc2luZ2xlQ2xpY2tlZCA9IFNpZ25hbChzdHIpCiAg"
    "ICBkb3VibGVDbGlja2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGllX3R5cGU6IHN0ciwgZGlzcGxh"
    "eV9sYWJlbDogc3RyLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5k"
    "aWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi5kaXNwbGF5X2xhYmVsID0gZGlzcGxheV9sYWJlbAogICAgICAgIHNlbGYu"
    "X2NsaWNrX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQog"
    "ICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnNldEludGVydmFsKDIyMCkKICAgICAgICBzZWxmLl9jbGlja190aW1lci50aW1lb3V0"
    "LmNvbm5lY3Qoc2VsZi5fZW1pdF9zaW5nbGUpCgogICAgICAgIHNlbGYuc2V0T2JqZWN0TmFtZSgiRGljZVRyYXlEaWUiKQogICAg"
    "ICAgIHNlbGYuc2V0Q3Vyc29yKFF0LkN1cnNvclNoYXBlLlBvaW50aW5nSGFuZEN1cnNvcikKICAgICAgICBzZWxmLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiUUZyYW1lI0RpY2VUcmF5RGllIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDhweDsgfX0iCiAgICAgICAgICAgIGYiUUZyYW1lI0RpY2VUcmF5RGll"
    "OmhvdmVyIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyB9fSIKICAgICAgICApCgogICAgICAgIGxheSA9IFFWQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgbGF5LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIGxheS5zZXRTcGFjaW5n"
    "KDIpCgogICAgICAgIGdseXBoX2RpZSA9ICJkMTAwIiBpZiBkaWVfdHlwZSA9PSAiZCUiIGVsc2UgZGllX3R5cGUKICAgICAgICBz"
    "ZWxmLmdseXBoID0gRGljZUdseXBoKGdseXBoX2RpZSkKICAgICAgICBzZWxmLmdseXBoLnNldEZpeGVkU2l6ZSg1NCwgNTQpCiAg"
    "ICAgICAgc2VsZi5nbHlwaC5zZXRBdHRyaWJ1dGUoUXQuV2lkZ2V0QXR0cmlidXRlLldBX1RyYW5zcGFyZW50Rm9yTW91c2VFdmVu"
    "dHMsIFRydWUpCgogICAgICAgIHNlbGYubGJsID0gUUxhYmVsKGRpc3BsYXlfbGFiZWwpCiAgICAgICAgc2VsZi5sYmwuc2V0QWxp"
    "Z25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5sYmwuc2V0U3R5bGVTaGVldChmImNvbG9y"
    "OiB7Q19URVhUfTsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBzZWxmLmxibC5zZXRBdHRyaWJ1dGUoUXQuV2lkZ2V0QXR0"
    "cmlidXRlLldBX1RyYW5zcGFyZW50Rm9yTW91c2VFdmVudHMsIFRydWUpCgogICAgICAgIGxheS5hZGRXaWRnZXQoc2VsZi5nbHlw"
    "aCwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYubGJsKQoKICAgIGRl"
    "ZiBtb3VzZVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIGlmIGV2ZW50LmJ1dHRvbigpID09IFF0Lk1vdXNlQnV0dG9u"
    "LkxlZnRCdXR0b246CiAgICAgICAgICAgIGlmIHNlbGYuX2NsaWNrX3RpbWVyLmlzQWN0aXZlKCk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9jbGlja190aW1lci5zdG9wKCkKICAgICAgICAgICAgICAgIHNlbGYuZG91YmxlQ2xpY2tlZC5lbWl0KHNlbGYuZGllX3R5"
    "cGUpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9jbGlja190aW1lci5zdGFydCgpCiAgICAgICAgICAg"
    "IGV2ZW50LmFjY2VwdCgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHN1cGVyKCkubW91c2VQcmVzc0V2ZW50KGV2ZW50KQoK"
    "ICAgIGRlZiBfZW1pdF9zaW5nbGUoc2VsZik6CiAgICAgICAgc2VsZi5zaW5nbGVDbGlja2VkLmVtaXQoc2VsZi5kaWVfdHlwZSkK"
    "CgpjbGFzcyBEaWNlUm9sbGVyVGFiKFFXaWRnZXQpOgogICAgIiIiRGVjay1uYXRpdmUgRGljZSBSb2xsZXIgbW9kdWxlIHRhYiB3"
    "aXRoIHRyYXkvcG9vbCB3b3JrZmxvdyBhbmQgc3RydWN0dXJlZCByb2xsIGV2ZW50cy4iIiIKCiAgICBUUkFZX09SREVSID0gWyJk"
    "NCIsICJkNiIsICJkOCIsICJkMTAiLCAiZDEyIiwgImQyMCIsICJkJSJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRpYWdub3N0"
    "aWNzX2xvZ2dlcj1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9sb2cgPSBkaWFnbm9zdGlj"
    "c19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKCiAgICAgICAgc2VsZi5yb2xsX2V2ZW50czogbGlz"
    "dFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5zYXZlZF9yb2xsczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5jb21tb25f"
    "cm9sbHM6IGRpY3Rbc3RyLCBkaWN0XSA9IHt9CiAgICAgICAgc2VsZi5ldmVudF9ieV9pZDogZGljdFtzdHIsIGRpY3RdID0ge30K"
    "ICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbDogZGljdFtzdHIsIGludF0gPSB7fQogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lk"
    "czogbGlzdFtzdHJdID0gW10KCiAgICAgICAgc2VsZi5ydWxlX2RlZmluaXRpb25zOiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAg"
    "ICAgICAgICJydWxlXzRkNl9kcm9wX2xvd2VzdCI6IHsKICAgICAgICAgICAgICAgICJpZCI6ICJydWxlXzRkNl9kcm9wX2xvd2Vz"
    "dCIsCiAgICAgICAgICAgICAgICAibmFtZSI6ICJEJkQgNWUgU3RhdCBSb2xsIiwKICAgICAgICAgICAgICAgICJkaWNlX2NvdW50"
    "IjogNCwKICAgICAgICAgICAgICAgICJkaWNlX3NpZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9jb3VudCI6"
    "IDEsCiAgICAgICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJub3RlcyI6ICJSb2xs"
    "IDRkNiwgZHJvcCBsb3dlc3Qgb25lLiIKICAgICAgICAgICAgfSwKICAgICAgICAgICAgInJ1bGVfM2Q2X3N0cmFpZ2h0Ijogewog"
    "ICAgICAgICAgICAgICAgImlkIjogInJ1bGVfM2Q2X3N0cmFpZ2h0IiwKICAgICAgICAgICAgICAgICJuYW1lIjogIjNkNiBTdHJh"
    "aWdodCIsCiAgICAgICAgICAgICAgICAiZGljZV9jb3VudCI6IDMsCiAgICAgICAgICAgICAgICAiZGljZV9zaWRlcyI6IDYsCiAg"
    "ICAgICAgICAgICAgICAiZHJvcF9sb3dlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImRyb3BfaGlnaGVzdF9jb3VudCI6"
    "IDAsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiQ2xhc3NpYyAzZDYgcm9sbC4iCiAgICAgICAgICAgIH0sCiAgICAgICAgfQoK"
    "ICAgICAgICBzZWxmLl9idWlsZF91aSgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJv"
    "eExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgcm9vdC5zZXRT"
    "cGFjaW5nKDYpCgogICAgICAgIHRyYXlfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgdHJheV93cmFwLnNldFN0eWxlU2hlZXQoZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgdHJheV9sYXlvdXQgPSBR"
    "VkJveExheW91dCh0cmF5X3dyYXApCiAgICAgICAgdHJheV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAg"
    "ICAgICAgdHJheV9sYXlvdXQuc2V0U3BhY2luZyg2KQogICAgICAgIHRyYXlfbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIkRpY2Ug"
    "VHJheSIpKQoKICAgICAgICB0cmF5X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0cmF5X3Jvdy5zZXRTcGFjaW5nKDYpCiAg"
    "ICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIGJsb2NrID0gRGljZVRyYXlEaWUoZGllLCBkaWUp"
    "CiAgICAgICAgICAgIGJsb2NrLnNpbmdsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9hZGRfZGllX3RvX3Bvb2wpCiAgICAgICAgICAg"
    "IGJsb2NrLmRvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9xdWlja19yb2xsX3NpbmdsZV9kaWUpCiAgICAgICAgICAgIHRyYXlf"
    "cm93LmFkZFdpZGdldChibG9jaywgMSkKICAgICAgICB0cmF5X2xheW91dC5hZGRMYXlvdXQodHJheV9yb3cpCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQodHJheV93cmFwKQoKICAgICAgICBwb29sX3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHBvb2xfd3JhcC5zZXRT"
    "dHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIHB3"
    "ID0gUVZCb3hMYXlvdXQocG9vbF93cmFwKQogICAgICAgIHB3LnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAg"
    "IHB3LnNldFNwYWNpbmcoNikKCiAgICAgICAgcHcuYWRkV2lkZ2V0KFFMYWJlbCgiQ3VycmVudCBQb29sIikpCiAgICAgICAgc2Vs"
    "Zi5wb29sX2V4cHJfbGJsID0gUUxhYmVsKCJQb29sOiAoZW1wdHkpIikKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwuc2V0U3R5"
    "bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBwdy5hZGRXaWRnZXQoc2VsZi5w"
    "b29sX2V4cHJfbGJsKQoKICAgICAgICBzZWxmLnBvb2xfZW50cmllc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnBv"
    "b2xfZW50cmllc19sYXlvdXQgPSBRSEJveExheW91dChzZWxmLnBvb2xfZW50cmllc193aWRnZXQpCiAgICAgICAgc2VsZi5wb29s"
    "X2VudHJpZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xh"
    "eW91dC5zZXRTcGFjaW5nKDYpCiAgICAgICAgcHcuYWRkV2lkZ2V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCkKCiAgICAgICAg"
    "bWV0YV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0ID0gUUxpbmVFZGl0KCk7IHNlbGYubGFiZWxf"
    "ZWRpdC5zZXRQbGFjZWhvbGRlclRleHQoIkxhYmVsIC8gcHVycG9zZSIpCiAgICAgICAgc2VsZi5tb2Rfc3BpbiA9IFFTcGluQm94"
    "KCk7IHNlbGYubW9kX3NwaW4uc2V0UmFuZ2UoLTk5OSwgOTk5KTsgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZSgwKQogICAgICAgIHNl"
    "bGYucnVsZV9jb21ibyA9IFFDb21ib0JveCgpOyBzZWxmLnJ1bGVfY29tYm8uYWRkSXRlbSgiTWFudWFsIFJvbGwiLCAiIikKICAg"
    "ICAgICBmb3IgcmlkLCBtZXRhIGluIHNlbGYucnVsZV9kZWZpbml0aW9ucy5pdGVtcygpOgogICAgICAgICAgICBzZWxmLnJ1bGVf"
    "Y29tYm8uYWRkSXRlbShtZXRhLmdldCgibmFtZSIsIHJpZCksIHJpZCkKCiAgICAgICAgZm9yIHRpdGxlLCB3IGluICgoIkxhYmVs"
    "Iiwgc2VsZi5sYWJlbF9lZGl0KSwgKCJNb2RpZmllciIsIHNlbGYubW9kX3NwaW4pLCAoIlJ1bGUiLCBzZWxmLnJ1bGVfY29tYm8p"
    "KToKICAgICAgICAgICAgY29sID0gUVZCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGl0bGUpCiAgICAgICAg"
    "ICAgIGxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAgICAgICAgICAg"
    "Y29sLmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIGNvbC5hZGRXaWRnZXQodykKICAgICAgICAgICAgbWV0YV9yb3cuYWRkTGF5"
    "b3V0KGNvbCwgMSkKICAgICAgICBwdy5hZGRMYXlvdXQobWV0YV9yb3cpCgogICAgICAgIGFjdGlvbnMgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgc2VsZi5yb2xsX3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlJvbGwgUG9vbCIpCiAgICAgICAgc2VsZi5yZXNldF9w"
    "b29sX2J0biA9IFFQdXNoQnV0dG9uKCJSZXNldCBQb29sIikKICAgICAgICBzZWxmLnNhdmVfcG9vbF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiU2F2ZSBQb29sIikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJvbGxfcG9vbF9idG4pCiAgICAgICAgYWN0aW9u"
    "cy5hZGRXaWRnZXQoc2VsZi5yZXNldF9wb29sX2J0bikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnNhdmVfcG9vbF9i"
    "dG4pCiAgICAgICAgcHcuYWRkTGF5b3V0KGFjdGlvbnMpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHBvb2xfd3JhcCkKCiAgICAg"
    "ICAgcmVzdWx0X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHJlc3VsdF93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgcmwgPSBRVkJveExheW91dChyZXN1bHRfd3Jh"
    "cCkKICAgICAgICBybC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBybC5hZGRXaWRnZXQoUUxhYmVsKCJD"
    "dXJyZW50IFJlc3VsdCIpKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsID0gUUxhYmVsKCJObyByb2xsIHlldC4iKQog"
    "ICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgcmwuYWRkV2lkZ2V0KHNlbGYu"
    "Y3VycmVudF9yZXN1bHRfbGJsKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHJlc3VsdF93cmFwKQoKICAgICAgICBtaWQgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgaGlzdG9yeV93cmFwID0gUUZyYW1lKCkKICAgICAgICBoaXN0b3J5X3dyYXAuc2V0U3R5bGVTaGVl"
    "dChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBodyA9IFFWQm94"
    "TGF5b3V0KGhpc3Rvcnlfd3JhcCkKICAgICAgICBody5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKCiAgICAgICAgc2Vs"
    "Zi5oaXN0b3J5X3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUgPSBzZWxmLl9tYWtlX3JvbGxf"
    "dGFibGUoKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90YWJsZSgpCiAgICAgICAgc2VsZi5o"
    "aXN0b3J5X3RhYnMuYWRkVGFiKHNlbGYuY3VycmVudF90YWJsZSwgIkN1cnJlbnQgUm9sbHMiKQogICAgICAgIHNlbGYuaGlzdG9y"
    "eV90YWJzLmFkZFRhYihzZWxmLmhpc3RvcnlfdGFibGUsICJSb2xsIEhpc3RvcnkiKQogICAgICAgIGh3LmFkZFdpZGdldChzZWxm"
    "Lmhpc3RvcnlfdGFicywgMSkKCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuY2xl"
    "YXJfaGlzdG9yeV9idG4gPSBRUHVzaEJ1dHRvbigiQ2xlYXIgUm9sbCBIaXN0b3J5IikKICAgICAgICBoaXN0b3J5X2FjdGlvbnMu"
    "YWRkV2lkZ2V0KHNlbGYuY2xlYXJfaGlzdG9yeV9idG4pCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zLmFkZFN0cmV0Y2goMSkKICAg"
    "ICAgICBody5hZGRMYXlvdXQoaGlzdG9yeV9hY3Rpb25zKQoKICAgICAgICBzZWxmLmdyYW5kX3RvdGFsX2xibCA9IFFMYWJlbCgi"
    "R3JhbmQgVG90YWw6IDAiKQogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfR09M"
    "RH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IikKICAgICAgICBody5hZGRXaWRnZXQoc2VsZi5ncmFuZF90"
    "b3RhbF9sYmwpCgogICAgICAgIHNhdmVkX3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHNhdmVkX3dyYXAuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBzdyA9IFFWQm94TGF5"
    "b3V0KHNhdmVkX3dyYXApCiAgICAgICAgc3cuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgc3cuYWRkV2lk"
    "Z2V0KFFMYWJlbCgiU2F2ZWQgLyBDb21tb24gUm9sbHMiKSkKCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2F2ZWQiKSkK"
    "ICAgICAgICBzZWxmLnNhdmVkX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuc2F2ZWRfbGlz"
    "dCwgMSkKICAgICAgICBzYXZlZF9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucnVuX3NhdmVkX2J0biA9IFFQ"
    "dXNoQnV0dG9uKCJSdW4iKQogICAgICAgIHNlbGYubG9hZF9zYXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiTG9hZC9FZGl0IikKICAg"
    "ICAgICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiRGVsZXRlIikKICAgICAgICBzYXZlZF9hY3Rpb25zLmFk"
    "ZFdpZGdldChzZWxmLnJ1bl9zYXZlZF9idG4pCiAgICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5sb2FkX3NhdmVk"
    "X2J0bikKICAgICAgICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmRlbGV0ZV9zYXZlZF9idG4pCiAgICAgICAgc3cuYWRk"
    "TGF5b3V0KHNhdmVkX2FjdGlvbnMpCgogICAgICAgIHN3LmFkZFdpZGdldChRTGFiZWwoIkF1dG8tRGV0ZWN0ZWQgQ29tbW9uIikp"
    "CiAgICAgICAgc2VsZi5jb21tb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzdy5hZGRXaWRnZXQoc2VsZi5jb21tb25f"
    "bGlzdCwgMSkKICAgICAgICBjb21tb25fYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnByb21vdGVfY29tbW9u"
    "X2J0biA9IFFQdXNoQnV0dG9uKCJQcm9tb3RlIHRvIFNhdmVkIikKICAgICAgICBzZWxmLmRpc21pc3NfY29tbW9uX2J0biA9IFFQ"
    "dXNoQnV0dG9uKCJEaXNtaXNzIikKICAgICAgICBjb21tb25fYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5wcm9tb3RlX2NvbW1vbl9i"
    "dG4pCiAgICAgICAgY29tbW9uX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuZGlzbWlzc19jb21tb25fYnRuKQogICAgICAgIHN3LmFk"
    "ZExheW91dChjb21tb25fYWN0aW9ucykKCiAgICAgICAgc2VsZi5jb21tb25faGludCA9IFFMYWJlbCgiQ29tbW9uIHNpZ25hdHVy"
    "ZSB0cmFja2luZyBhY3RpdmUuIikKICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVY"
    "VF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9oaW50KQoKICAgICAgICBt"
    "aWQuYWRkV2lkZ2V0KGhpc3Rvcnlfd3JhcCwgMykKICAgICAgICBtaWQuYWRkV2lkZ2V0KHNhdmVkX3dyYXAsIDIpCiAgICAgICAg"
    "cm9vdC5hZGRMYXlvdXQobWlkLCAxKQoKICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Jv"
    "bGxfY3VycmVudF9wb29sKQogICAgICAgIHNlbGYucmVzZXRfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Jlc2V0X3Bv"
    "b2wpCiAgICAgICAgc2VsZi5zYXZlX3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3Bvb2wpCiAgICAgICAgc2Vs"
    "Zi5jbGVhcl9oaXN0b3J5X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY2xlYXJfaGlzdG9yeSkKCiAgICAgICAgc2VsZi5zYXZl"
    "ZF9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0"
    "YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpKSkKICAgICAgICBzZWxmLmNvbW1vbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNv"
    "bm5lY3QobGFtYmRhIGl0ZW06IHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUp"
    "KSkKCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9ydW5fc2VsZWN0ZWRfc2F2ZWQpCiAg"
    "ICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fbG9hZF9zZWxlY3RlZF9zYXZlZCkKICAgICAg"
    "ICBzZWxmLmRlbGV0ZV9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RlbGV0ZV9zZWxlY3RlZF9zYXZlZCkKICAgICAg"
    "ICBzZWxmLnByb21vdGVfY29tbW9uX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcHJvbW90ZV9zZWxlY3RlZF9jb21tb24pCiAg"
    "ICAgICAgc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rpc21pc3Nfc2VsZWN0ZWRfY29tbW9u"
    "KQoKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3Vz"
    "dG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KFF0LkNvbnRleHRN"
    "ZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5jdXN0b21Db250ZXh0TWVudVJl"
    "cXVlc3RlZC5jb25uZWN0KGxhbWJkYSBwb3M6IHNlbGYuX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5jdXJyZW50X3RhYmxl"
    "LCBwb3MpKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KGxhbWJk"
    "YSBwb3M6IHNlbGYuX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZi5oaXN0b3J5X3RhYmxlLCBwb3MpKQoKICAgIGRlZiBfbWFr"
    "ZV9yb2xsX3RhYmxlKHNlbGYpIC0+IFFUYWJsZVdpZGdldDoKICAgICAgICB0YmwgPSBRVGFibGVXaWRnZXQoMCwgNikKICAgICAg"
    "ICB0Ymwuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIlRpbWVzdGFtcCIsICJMYWJlbCIsICJFeHByZXNzaW9uIiwgIlJhdyIs"
    "ICJNb2RpZmllciIsICJUb3RhbCJdKQogICAgICAgIHRibC5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "UUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHRibC52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFs"
    "c2UpCiAgICAgICAgdGJsLnNldEVkaXRUcmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmlnZ2Vy"
    "cykKICAgICAgICB0Ymwuc2V0U2VsZWN0aW9uQmVoYXZpb3IoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2Vs"
    "ZWN0Um93cykKICAgICAgICB0Ymwuc2V0U29ydGluZ0VuYWJsZWQoRmFsc2UpCiAgICAgICAgcmV0dXJuIHRibAoKICAgIGRlZiBf"
    "c29ydGVkX3Bvb2xfaXRlbXMoc2VsZik6CiAgICAgICAgcmV0dXJuIFsoZCwgc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGQsIDApKSBm"
    "b3IgZCBpbiBzZWxmLlRSQVlfT1JERVIgaWYgc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGQsIDApID4gMF0KCiAgICBkZWYgX3Bvb2xf"
    "ZXhwcmVzc2lvbihzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSB8IE5vbmUgPSBOb25lKSAtPiBzdHI6CiAgICAgICAgcCA9IHBv"
    "b2wgaWYgcG9vbCBpcyBub3QgTm9uZSBlbHNlIHNlbGYuY3VycmVudF9wb29sCiAgICAgICAgcGFydHMgPSBbZiJ7cXR5fXtkaWV9"
    "IiBmb3IgZGllLCBxdHkgaW4gWyhkLCBwLmdldChkLCAwKSkgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVSXSBpZiBxdHkgPiAwXQog"
    "ICAgICAgIHJldHVybiAiICsgIi5qb2luKHBhcnRzKSBpZiBwYXJ0cyBlbHNlICIoZW1wdHkpIgoKICAgIGRlZiBfbm9ybWFsaXpl"
    "X3Bvb2xfc2lnbmF0dXJlKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBpbnRdLCBtb2RpZmllcjogaW50LCBydWxlX2lkOiBzdHIgPSAi"
    "IikgLT4gc3RyOgogICAgICAgIHBhcnRzID0gW2Yie3Bvb2wuZ2V0KGQsIDApfXtkfSIgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVS"
    "IGlmIHBvb2wuZ2V0KGQsIDApID4gMF0KICAgICAgICBiYXNlID0gIisiLmpvaW4ocGFydHMpIGlmIHBhcnRzIGVsc2UgIjAiCiAg"
    "ICAgICAgc2lnID0gZiJ7YmFzZX17bW9kaWZpZXI6K2R9IgogICAgICAgIHJldHVybiBmIntzaWd9X3tydWxlX2lkfSIgaWYgcnVs"
    "ZV9pZCBlbHNlIHNpZwoKICAgIGRlZiBfZGljZV9sYWJlbChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuICJkJSIgaWYgZGllX3R5cGUgPT0gImQlIiBlbHNlIGRpZV90eXBlCgogICAgZGVmIF9yb2xsX3NpbmdsZV92YWx1ZShzZWxm"
    "LCBkaWVfdHlwZTogc3RyKToKICAgICAgICBpZiBkaWVfdHlwZSA9PSAiZCUiOgogICAgICAgICAgICB0ZW5zID0gcmFuZG9tLnJh"
    "bmRpbnQoMCwgOSkgKiAxMAogICAgICAgICAgICByZXR1cm4gdGVucywgKCIwMCIgaWYgdGVucyA9PSAwIGVsc2Ugc3RyKHRlbnMp"
    "KQogICAgICAgIHNpZGVzID0gaW50KGRpZV90eXBlLnJlcGxhY2UoImQiLCAiIikpCiAgICAgICAgdmFsID0gcmFuZG9tLnJhbmRp"
    "bnQoMSwgc2lkZXMpCiAgICAgICAgcmV0dXJuIHZhbCwgc3RyKHZhbCkKCiAgICBkZWYgX3JvbGxfcG9vbF9kYXRhKHNlbGYsIHBv"
    "b2w6IGRpY3Rbc3RyLCBpbnRdLCBtb2RpZmllcjogaW50LCBsYWJlbDogc3RyLCBydWxlX2lkOiBzdHIgPSAiIikgLT4gZGljdDoK"
    "ICAgICAgICBncm91cGVkX251bWVyaWM6IGRpY3Rbc3RyLCBsaXN0W2ludF1dID0ge30KICAgICAgICBncm91cGVkX2Rpc3BsYXk6"
    "IGRpY3Rbc3RyLCBsaXN0W3N0cl1dID0ge30KICAgICAgICBzdWJ0b3RhbCA9IDAKICAgICAgICB1c2VkX3Bvb2wgPSBkaWN0KHBv"
    "b2wpCgogICAgICAgIGlmIHJ1bGVfaWQgYW5kIHJ1bGVfaWQgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zIGFuZCAobm90IHBvb2wg"
    "b3IgbGVuKFtrIGZvciBrLCB2IGluIHBvb2wuaXRlbXMoKSBpZiB2ID4gMF0pID09IDEpOgogICAgICAgICAgICBydWxlID0gc2Vs"
    "Zi5ydWxlX2RlZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkKICAgICAgICAgICAgc2lkZXMgPSBpbnQocnVsZS5nZXQoImRpY2Vf"
    "c2lkZXMiLCA2KSkKICAgICAgICAgICAgY291bnQgPSBpbnQocnVsZS5nZXQoImRpY2VfY291bnQiLCAxKSkKICAgICAgICAgICAg"
    "ZGllID0gZiJke3NpZGVzfSIKICAgICAgICAgICAgdXNlZF9wb29sID0ge2RpZTogY291bnR9CiAgICAgICAgICAgIHJhdyA9IFty"
    "YW5kb20ucmFuZGludCgxLCBzaWRlcykgZm9yIF8gaW4gcmFuZ2UoY291bnQpXQogICAgICAgICAgICBkcm9wX2xvdyA9IGludChy"
    "dWxlLmdldCgiZHJvcF9sb3dlc3RfY291bnQiLCAwKSBvciAwKQogICAgICAgICAgICBkcm9wX2hpZ2ggPSBpbnQocnVsZS5nZXQo"
    "ImRyb3BfaGlnaGVzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGtlcHQgPSBsaXN0KHJhdykKICAgICAgICAgICAgaWYg"
    "ZHJvcF9sb3cgPiAwOgogICAgICAgICAgICAgICAga2VwdCA9IHNvcnRlZChrZXB0KVtkcm9wX2xvdzpdCiAgICAgICAgICAgIGlm"
    "IGRyb3BfaGlnaCA+IDA6CiAgICAgICAgICAgICAgICBrZXB0ID0gc29ydGVkKGtlcHQpWzotZHJvcF9oaWdoXSBpZiBkcm9wX2hp"
    "Z2ggPCBsZW4oa2VwdCkgZWxzZSBbXQogICAgICAgICAgICBncm91cGVkX251bWVyaWNbZGllXSA9IHJhdwogICAgICAgICAgICBn"
    "cm91cGVkX2Rpc3BsYXlbZGllXSA9IFtzdHIodikgZm9yIHYgaW4gcmF3XQogICAgICAgICAgICBzdWJ0b3RhbCA9IHN1bShrZXB0"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICAgICAgcXR5"
    "ID0gaW50KHBvb2wuZ2V0KGRpZSwgMCkgb3IgMCkKICAgICAgICAgICAgICAgIGlmIHF0eSA8PSAwOgogICAgICAgICAgICAgICAg"
    "ICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICBncm91cGVkX251bWVyaWNbZGllXSA9IFtdCiAgICAgICAgICAgICAgICBncm91"
    "cGVkX2Rpc3BsYXlbZGllXSA9IFtdCiAgICAgICAgICAgICAgICBmb3IgXyBpbiByYW5nZShxdHkpOgogICAgICAgICAgICAgICAg"
    "ICAgIG51bSwgZGlzcCA9IHNlbGYuX3JvbGxfc2luZ2xlX3ZhbHVlKGRpZSkKICAgICAgICAgICAgICAgICAgICBncm91cGVkX251"
    "bWVyaWNbZGllXS5hcHBlbmQobnVtKQogICAgICAgICAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdLmFwcGVuZChkaXNw"
    "KQogICAgICAgICAgICAgICAgICAgIHN1YnRvdGFsICs9IGludChudW0pCgogICAgICAgIHRvdGFsID0gc3VidG90YWwgKyBpbnQo"
    "bW9kaWZpZXIpCiAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGV4cHIgPSBz"
    "ZWxmLl9wb29sX2V4cHJlc3Npb24odXNlZF9wb29sKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAgICAgICAgICAgIHJ1bGVfbmFtZSA9"
    "IHNlbGYucnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAgICAgICAgICAgIGV4"
    "cHIgPSBmIntleHByfSAoe3J1bGVfbmFtZX0pIgoKICAgICAgICBldmVudCA9IHsKICAgICAgICAgICAgImlkIjogZiJyb2xsX3t1"
    "dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRzLAogICAgICAgICAgICAibGFiZWwiOiBs"
    "YWJlbCwKICAgICAgICAgICAgInBvb2wiOiB1c2VkX3Bvb2wsCiAgICAgICAgICAgICJncm91cGVkX3JhdyI6IGdyb3VwZWRfbnVt"
    "ZXJpYywKICAgICAgICAgICAgImdyb3VwZWRfcmF3X2Rpc3BsYXkiOiBncm91cGVkX2Rpc3BsYXksCiAgICAgICAgICAgICJzdWJ0"
    "b3RhbCI6IHN1YnRvdGFsLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQobW9kaWZpZXIpLAogICAgICAgICAgICAiZmluYWxf"
    "dG90YWwiOiBpbnQodG90YWwpLAogICAgICAgICAgICAiZXhwcmVzc2lvbiI6IGV4cHIsCiAgICAgICAgICAgICJzb3VyY2UiOiAi"
    "ZGljZV9yb2xsZXIiLAogICAgICAgICAgICAicnVsZV9pZCI6IHJ1bGVfaWQgb3IgTm9uZSwKICAgICAgICB9CiAgICAgICAgcmV0"
    "dXJuIGV2ZW50CgogICAgZGVmIF9hZGRfZGllX3RvX3Bvb2woc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLmN1cnJlbnRfcG9vbFtkaWVfdHlwZV0gPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90eXBlLCAwKSkgKyAxCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dChm"
    "IkN1cnJlbnQgUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9hZGp1c3RfcG9vbF9kaWUoc2VsZiwg"
    "ZGllX3R5cGU6IHN0ciwgZGVsdGE6IGludCkgLT4gTm9uZToKICAgICAgICBuZXdfdmFsID0gaW50KHNlbGYuY3VycmVudF9wb29s"
    "LmdldChkaWVfdHlwZSwgMCkpICsgaW50KGRlbHRhKQogICAgICAgIGlmIG5ld192YWwgPD0gMDoKICAgICAgICAgICAgc2VsZi5j"
    "dXJyZW50X3Bvb2wucG9wKGRpZV90eXBlLCBOb25lKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuY3VycmVudF9wb29s"
    "W2RpZV90eXBlXSA9IG5ld192YWwKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKCiAgICBkZWYgX3JlZnJlc2hf"
    "cG9vbF9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICB3aGlsZSBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuY291bnQoKToK"
    "ICAgICAgICAgICAgaXRlbSA9IHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgdyA9IGl0ZW0u"
    "d2lkZ2V0KCkKICAgICAgICAgICAgaWYgdyBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHcuZGVsZXRlTGF0ZXIoKQoKICAg"
    "ICAgICBmb3IgZGllLCBxdHkgaW4gc2VsZi5fc29ydGVkX3Bvb2xfaXRlbXMoKToKICAgICAgICAgICAgYm94ID0gUUZyYW1lKCkK"
    "ICAgICAgICAgICAgYm94LnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyBib3JkZXItcmFkaXVzOiA2cHg7IikKICAgICAgICAgICAgbGF5ID0gUUhCb3hMYXlvdXQoYm94KQogICAgICAgICAg"
    "ICBsYXkuc2V0Q29udGVudHNNYXJnaW5zKDYsIDQsIDYsIDQpCiAgICAgICAgICAgIGxheS5zZXRTcGFjaW5nKDQpCiAgICAgICAg"
    "ICAgIGxibCA9IFFMYWJlbChmIntkaWV9IHh7cXR5fSIpCiAgICAgICAgICAgIG1pbnVzX2J0biA9IFFQdXNoQnV0dG9uKCLiiJIi"
    "KQogICAgICAgICAgICBwbHVzX2J0biA9IFFQdXNoQnV0dG9uKCIrIikKICAgICAgICAgICAgbWludXNfYnRuLnNldEZpeGVkV2lk"
    "dGgoMjQpCiAgICAgICAgICAgIHBsdXNfYnRuLnNldEZpeGVkV2lkdGgoMjQpCiAgICAgICAgICAgIG1pbnVzX2J0bi5jbGlja2Vk"
    "LmNvbm5lY3QobGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9vbF9kaWUoZCwgLTEpKQogICAgICAgICAgICBw"
    "bHVzX2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIF89RmFsc2UsIGQ9ZGllOiBzZWxmLl9hZGp1c3RfcG9vbF9kaWUoZCwgKzEp"
    "KQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChtaW51c19idG4pCiAgICAg"
    "ICAgICAgIGxheS5hZGRXaWRnZXQocGx1c19idG4pCiAgICAgICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5hZGRXaWRn"
    "ZXQoYm94KQoKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuYWRkU3RyZXRjaCgxKQogICAgICAgIHNlbGYucG9vbF9l"
    "eHByX2xibC5zZXRUZXh0KGYiUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9xdWlja19yb2xsX3Np"
    "bmdsZV9kaWUoc2VsZiwgZGllX3R5cGU6IHN0cikgLT4gTm9uZToKICAgICAgICBldmVudCA9IHNlbGYuX3JvbGxfcG9vbF9kYXRh"
    "KHtkaWVfdHlwZTogMX0sIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlwKCks"
    "IHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9yICIiKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xsX2V2ZW50KGV2ZW50"
    "KQoKICAgIGRlZiBfcm9sbF9jdXJyZW50X3Bvb2woc2VsZikgLT4gTm9uZToKICAgICAgICBwb29sID0gZGljdChzZWxmLmN1cnJl"
    "bnRfcG9vbCkKICAgICAgICBydWxlX2lkID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIiIKICAgICAgICBpZiBu"
    "b3QgcG9vbCBhbmQgbm90IHJ1bGVfaWQ6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJEaWNlIFJv"
    "bGxlciIsICJDdXJyZW50IFBvb2wgaXMgZW1wdHkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxmLl9y"
    "b2xsX3Bvb2xfZGF0YShwb29sLCBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1ZSgpKSwgc2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJp"
    "cCgpLCBydWxlX2lkKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xsX2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfcmVjb3JkX3JvbGxf"
    "ZXZlbnQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5yb2xsX2V2ZW50cy5hcHBlbmQoZXZlbnQpCiAg"
    "ICAgICAgc2VsZi5ldmVudF9ieV9pZFtldmVudFsiaWQiXV0gPSBldmVudAogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lkcyA9"
    "IFtldmVudFsiaWQiXV0KCiAgICAgICAgc2VsZi5fcmVwbGFjZV9jdXJyZW50X3Jvd3MoW2V2ZW50XSkKICAgICAgICBzZWxmLl9h"
    "cHBlbmRfaGlzdG9yeV9yb3coZXZlbnQpCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLl91"
    "cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZlbnQpCiAgICAgICAgc2VsZi5fdHJhY2tfY29tbW9uX3NpZ25hdHVyZShldmVudCkKICAg"
    "ICAgICBzZWxmLl9wbGF5X3JvbGxfc291bmQoKQoKICAgIGRlZiBfcmVwbGFjZV9jdXJyZW50X3Jvd3Moc2VsZiwgZXZlbnRzOiBs"
    "aXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBl"
    "dmVudCBpbiBldmVudHM6CiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5jdXJyZW50X3RhYmxlLCBldmVu"
    "dCkKCiAgICBkZWYgX2FwcGVuZF9oaXN0b3J5X3JvdyhzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9h"
    "cHBlbmRfdGFibGVfcm93KHNlbGYuaGlzdG9yeV90YWJsZSwgZXZlbnQpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNjcm9s"
    "bFRvQm90dG9tKCkKCiAgICBkZWYgX2Zvcm1hdF9yYXcoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IHN0cjoKICAgICAgICBncm91cGVk"
    "ID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgYml0cyA9IFtdCiAgICAgICAgZm9y"
    "IGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlm"
    "IHZhbHM6CiAgICAgICAgICAgICAgICBiaXRzLmFwcGVuZChmIntkaWV9OiB7JywnLmpvaW4oc3RyKHYpIGZvciB2IGluIHZhbHMp"
    "fSIpCiAgICAgICAgcmV0dXJuICIgfCAiLmpvaW4oYml0cykKCiAgICBkZWYgX2FwcGVuZF90YWJsZV9yb3coc2VsZiwgdGFibGU6"
    "IFFUYWJsZVdpZGdldCwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gdGFibGUucm93Q291bnQoKQogICAgICAg"
    "IHRhYmxlLmluc2VydFJvdyhyb3cpCgogICAgICAgIHRzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGV2ZW50WyJ0aW1lc3RhbXAi"
    "XSkKICAgICAgICB0c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBldmVudFsiaWQiXSkKICAgICAgICB0"
    "YWJsZS5zZXRJdGVtKHJvdywgMCwgdHNfaXRlbSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRhYmxlV2lkZ2V0SXRl"
    "bShldmVudC5nZXQoImxhYmVsIiwgIiIpKSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbShl"
    "dmVudC5nZXQoImV4cHJlc3Npb24iLCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVt"
    "KHNlbGYuX2Zvcm1hdF9yYXcoZXZlbnQpKSkKCiAgICAgICAgbW9kX3NwaW4gPSBRU3BpbkJveCgpCiAgICAgICAgbW9kX3NwaW4u"
    "c2V0UmFuZ2UoLTk5OSwgOTk5KQogICAgICAgIG1vZF9zcGluLnNldFZhbHVlKGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkp"
    "KQogICAgICAgIG1vZF9zcGluLnZhbHVlQ2hhbmdlZC5jb25uZWN0KGxhbWJkYSB2YWwsIGVpZD1ldmVudFsiaWQiXTogc2VsZi5f"
    "b25fbW9kaWZpZXJfY2hhbmdlZChlaWQsIHZhbCkpCiAgICAgICAgdGFibGUuc2V0Q2VsbFdpZGdldChyb3csIDQsIG1vZF9zcGlu"
    "KQoKICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwgUVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2V0KCJmaW5hbF90b3Rh"
    "bCIsIDApKSkpCgogICAgZGVmIF9zeW5jX3Jvd19ieV9ldmVudF9pZChzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBldmVudF9p"
    "ZDogc3RyLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBmb3Igcm93IGluIHJhbmdlKHRhYmxlLnJvd0NvdW50KCkpOgog"
    "ICAgICAgICAgICBpdCA9IHRhYmxlLml0ZW0ocm93LCAwKQogICAgICAgICAgICBpZiBpdCBhbmQgaXQuZGF0YShRdC5JdGVtRGF0"
    "YVJvbGUuVXNlclJvbGUpID09IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDUsIFFUYWJsZVdp"
    "ZGdldEl0ZW0oc3RyKGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwKSkpKQogICAgICAgICAgICAgICAgdGFibGUuc2V0SXRlbShy"
    "b3csIDMsIFFUYWJsZVdpZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQogICAgICAgICAgICAgICAgYnJlYWsKCiAg"
    "ICBkZWYgX29uX21vZGlmaWVyX2NoYW5nZWQoc2VsZiwgZXZlbnRfaWQ6IHN0ciwgdmFsdWU6IGludCkgLT4gTm9uZToKICAgICAg"
    "ICBldnQgPSBzZWxmLmV2ZW50X2J5X2lkLmdldChldmVudF9pZCkKICAgICAgICBpZiBub3QgZXZ0OgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBldnRbIm1vZGlmaWVyIl0gPSBpbnQodmFsdWUpCiAgICAgICAgZXZ0WyJmaW5hbF90b3RhbCJdID0gaW50KGV2"
    "dC5nZXQoInN1YnRvdGFsIiwgMCkpICsgaW50KHZhbHVlKQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYu"
    "aGlzdG9yeV90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgICAgICBzZWxmLl9zeW5jX3Jvd19ieV9ldmVudF9pZChzZWxmLmN1cnJl"
    "bnRfdGFibGUsIGV2ZW50X2lkLCBldnQpCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBpZiBzZWxm"
    "LmN1cnJlbnRfcm9sbF9pZHMgYW5kIHNlbGYuY3VycmVudF9yb2xsX2lkc1swXSA9PSBldmVudF9pZDoKICAgICAgICAgICAgc2Vs"
    "Zi5fdXBkYXRlX3Jlc3VsdF9kaXNwbGF5KGV2dCkKCiAgICBkZWYgX3VwZGF0ZV9ncmFuZF90b3RhbChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRvdGFsID0gc3VtKGludChldnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSBmb3IgZXZ0IGluIHNlbGYucm9sbF9ldmVu"
    "dHMpCiAgICAgICAgc2VsZi5ncmFuZF90b3RhbF9sYmwuc2V0VGV4dChmIkdyYW5kIFRvdGFsOiB7dG90YWx9IikKCiAgICBkZWYg"
    "X3VwZGF0ZV9yZXN1bHRfZGlzcGxheShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBncm91cGVkID0gZXZlbnQu"
    "Z2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgbGluZXMgPSBbXQogICAgICAgIGZvciBkaWUgaW4g"
    "c2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgog"
    "ICAgICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYie2RpZX0geHtsZW4odmFscyl9IOKGkiBbeycsJy5qb2luKHN0cih2KSBmb3Ig"
    "diBpbiB2YWxzKX1dIikKICAgICAgICBydWxlX2lkID0gZXZlbnQuZ2V0KCJydWxlX2lkIikKICAgICAgICBpZiBydWxlX2lkOgog"
    "ICAgICAgICAgICBydWxlX25hbWUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KS5nZXQoIm5hbWUiLCBy"
    "dWxlX2lkKQogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJSdWxlOiB7cnVsZV9uYW1lfSIpCiAgICAgICAgbGluZXMuYXBwZW5k"
    "KGYiTW9kaWZpZXI6IHtpbnQoZXZlbnQuZ2V0KCdtb2RpZmllcicsIDApKTorZH0iKQogICAgICAgIGxpbmVzLmFwcGVuZChmIlRv"
    "dGFsOiB7ZXZlbnQuZ2V0KCdmaW5hbF90b3RhbCcsIDApfSIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4"
    "dCgiXG4iLmpvaW4obGluZXMpKQoKCiAgICBkZWYgX3NhdmVfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxm"
    "LmN1cnJlbnRfcG9vbDoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9sbGVyIiwgIkJ1"
    "aWxkIGEgQ3VycmVudCBQb29sIGJlZm9yZSBzYXZpbmcuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZGVmYXVsdF9uYW1l"
    "ID0gc2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJpcCgpIG9yIHNlbGYuX3Bvb2xfZXhwcmVzc2lvbigpCiAgICAgICAgbmFtZSwg"
    "b2sgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiU2F2ZSBQb29sIiwgIlNhdmVkIHJvbGwgbmFtZToiLCB0ZXh0PWRlZmF1"
    "bHRfbmFtZSkKICAgICAgICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBheWxvYWQgPSB7CiAgICAgICAg"
    "ICAgICJpZCI6IGYic2F2ZWRfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAibmFtZSI6IG5hbWUuc3RyaXAo"
    "KSBvciBkZWZhdWx0X25hbWUsCiAgICAgICAgICAgICJwb29sIjogZGljdChzZWxmLmN1cnJlbnRfcG9vbCksCiAgICAgICAgICAg"
    "ICJtb2RpZmllciI6IGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLAogICAgICAgICAgICAicnVsZV9pZCI6IHNlbGYucnVsZV9j"
    "b21iby5jdXJyZW50RGF0YSgpIG9yIE5vbmUsCiAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAgICAgICAgICAiY2F0ZWdvcnki"
    "OiAic2F2ZWQiLAogICAgICAgIH0KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLmFwcGVuZChwYXlsb2FkKQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcmVmcmVzaF9zYXZlZF9saXN0cyhzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuc2F2ZWRfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2VsZi5zYXZlZF9yb2xsczoKICAgICAgICAgICAg"
    "ZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkKICAgICAgICAgICAgdHh0ID0gZiJ7aXRl"
    "bS5nZXQoJ25hbWUnKX0g4oCUIHtleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZmllcicsIDApKTorZH0iCiAgICAgICAgICAgIGx3"
    "ID0gUUxpc3RXaWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGl0"
    "ZW0pCiAgICAgICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5hZGRJdGVtKGx3KQoKICAgICAgICBzZWxmLmNvbW1vbl9saXN0LmNsZWFy"
    "KCkKICAgICAgICByYW5rZWQgPSBzb3J0ZWQoc2VsZi5jb21tb25fcm9sbHMudmFsdWVzKCksIGtleT1sYW1iZGEgeDogeC5nZXQo"
    "ImNvdW50IiwgMCksIHJldmVyc2U9VHJ1ZSkKICAgICAgICBmb3IgaXRlbSBpbiByYW5rZWQ6CiAgICAgICAgICAgIGlmIGludChp"
    "dGVtLmdldCgiY291bnQiLCAwKSkgPCAyOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZXhwciA9IHNlbGYu"
    "X3Bvb2xfZXhwcmVzc2lvbihpdGVtLmdldCgicG9vbCIsIHt9KSkKICAgICAgICAgICAgdHh0ID0gZiJ7ZXhwcn0ge2ludChpdGVt"
    "LmdldCgnbW9kaWZpZXInLCAwKSk6K2R9ICh4e2l0ZW0uZ2V0KCdjb3VudCcsIDApfSkiCiAgICAgICAgICAgIGx3ID0gUUxpc3RX"
    "aWRnZXRJdGVtKHR4dCkKICAgICAgICAgICAgbHcuc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGl0ZW0pCiAgICAg"
    "ICAgICAgIHNlbGYuY29tbW9uX2xpc3QuYWRkSXRlbShsdykKCiAgICBkZWYgX3RyYWNrX2NvbW1vbl9zaWduYXR1cmUoc2VsZiwg"
    "ZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2lnID0gc2VsZi5fbm9ybWFsaXplX3Bvb2xfc2lnbmF0dXJlKGV2ZW50Lmdl"
    "dCgicG9vbCIsIHt9KSwgaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSksIHN0cihldmVudC5nZXQoInJ1bGVfaWQiKSBvciAi"
    "IikpCiAgICAgICAgaWYgc2lnIG5vdCBpbiBzZWxmLmNvbW1vbl9yb2xsczoKICAgICAgICAgICAgc2VsZi5jb21tb25fcm9sbHNb"
    "c2lnXSA9IHsKICAgICAgICAgICAgICAgICJzaWduYXR1cmUiOiBzaWcsCiAgICAgICAgICAgICAgICAiY291bnQiOiAwLAogICAg"
    "ICAgICAgICAgICAgIm5hbWUiOiBldmVudC5nZXQoImxhYmVsIiwgIiIpIG9yIHNpZywKICAgICAgICAgICAgICAgICJwb29sIjog"
    "ZGljdChldmVudC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KGV2ZW50LmdldCgibW9k"
    "aWZpZXIiLCAwKSksCiAgICAgICAgICAgICAgICAicnVsZV9pZCI6IGV2ZW50LmdldCgicnVsZV9pZCIpLAogICAgICAgICAgICAg"
    "ICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICAgICAiY2F0ZWdvcnkiOiAiY29tbW9uIiwKICAgICAgICAgICAgfQogICAgICAg"
    "IHNlbGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPSBpbnQoc2VsZi5jb21tb25fcm9sbHNbc2lnXS5nZXQoImNvdW50Iiwg"
    "MCkpICsgMQogICAgICAgIGlmIHNlbGYuY29tbW9uX3JvbGxzW3NpZ11bImNvdW50Il0gPj0gMzoKICAgICAgICAgICAgc2VsZi5j"
    "b21tb25faGludC5zZXRUZXh0KGYiU3VnZ2VzdGlvbjogcHJvbW90ZSB7c2VsZi5fcG9vbF9leHByZXNzaW9uKGV2ZW50LmdldCgn"
    "cG9vbCcsIHt9KSl9IHRvIFNhdmVkLiIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9ydW5f"
    "c2F2ZWRfcm9sbChzZWxmLCBwYXlsb2FkOiBkaWN0IHwgTm9uZSk6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEoCiAgICAgICAgICAgIGRpY3QocGF5bG9hZC5nZXQo"
    "InBvb2wiLCB7fSkpLAogICAgICAgICAgICBpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAgICBzdHIo"
    "cGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpLnN0cmlwKCksCiAgICAgICAgICAgIHN0cihwYXlsb2FkLmdldCgicnVsZV9pZCIpIG9y"
    "ICIiKSwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9sb2FkX3BheWxv"
    "YWRfaW50b19wb29sKHNlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBwYXlsb2FkOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbCA9IGRpY3QocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkp"
    "CiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZShpbnQocGF5bG9hZC5nZXQoIm1vZGlmaWVyIiwgMCkpKQogICAgICAgIHNl"
    "bGYubGFiZWxfZWRpdC5zZXRUZXh0KHN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgcmlkID0gcGF5bG9hZC5n"
    "ZXQoInJ1bGVfaWQiKQogICAgICAgIGlkeCA9IHNlbGYucnVsZV9jb21iby5maW5kRGF0YShyaWQgb3IgIiIpCiAgICAgICAgaWYg"
    "aWR4ID49IDA6CiAgICAgICAgICAgIHNlbGYucnVsZV9jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoZiJDdXJyZW50IFBvb2w6"
    "IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0iKQoKICAgIGRlZiBfcnVuX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgogICAgICAgIGl0"
    "ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHNlbGYuX3J1bl9zYXZlZF9yb2xsKGl0ZW0uZGF0YShR"
    "dC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBOb25lKQoKICAgIGRlZiBfbG9hZF9zZWxlY3RlZF9zYXZlZChz"
    "ZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXlsb2FkID0gaXRlbS5k"
    "YXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbG9hZF9wYXlsb2FkX2ludG9fcG9vbChwYXlsb2FkKQoKICAgICAgICBuYW1l"
    "LCBvayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTmFtZToiLCB0ZXh0PXN0cihwYXls"
    "b2FkLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgaWYgbm90IG9rOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBwYXlsb2Fk"
    "WyJuYW1lIl0gPSBuYW1lLnN0cmlwKCkgb3IgcGF5bG9hZC5nZXQoIm5hbWUiLCAiIikKICAgICAgICBwYXlsb2FkWyJwb29sIl0g"
    "PSBkaWN0KHNlbGYuY3VycmVudF9wb29sKQogICAgICAgIHBheWxvYWRbIm1vZGlmaWVyIl0gPSBpbnQoc2VsZi5tb2Rfc3Bpbi52"
    "YWx1ZSgpKQogICAgICAgIHBheWxvYWRbInJ1bGVfaWQiXSA9IHNlbGYucnVsZV9jb21iby5jdXJyZW50RGF0YSgpIG9yIE5vbmUK"
    "ICAgICAgICBub3Rlcywgb2tfbm90ZXMgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiRWRpdCBTYXZlZCBSb2xsIiwgIk5v"
    "dGVzIC8gY2F0ZWdvcnk6IiwgdGV4dD1zdHIocGF5bG9hZC5nZXQoIm5vdGVzIiwgIiIpKSkKICAgICAgICBpZiBva19ub3RlczoK"
    "ICAgICAgICAgICAgcGF5bG9hZFsibm90ZXMiXSA9IG5vdGVzCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgog"
    "ICAgZGVmIF9kZWxldGVfc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgcm93ID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRS"
    "b3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLnNhdmVkX3JvbGxzKToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5wb3Aocm93KQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAg"
    "IGRlZiBfcHJvbW90ZV9zZWxlY3RlZF9jb21tb24oc2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuY29tbW9uX2xpc3QuY3VycmVu"
    "dEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2Ug"
    "Tm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBwcm9tb3RlZCA9IHsKICAgICAg"
    "ICAgICAgImlkIjogZiJzYXZlZF97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogcGF5bG9hZC5n"
    "ZXQoIm5hbWUiKSBvciBzZWxmLl9wb29sX2V4cHJlc3Npb24ocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAi"
    "cG9vbCI6IGRpY3QocGF5bG9hZC5nZXQoInBvb2wiLCB7fSkpLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQocGF5bG9hZC5n"
    "ZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAgICAicnVsZV9pZCI6IHBheWxvYWQuZ2V0KCJydWxlX2lkIiksCiAgICAgICAg"
    "ICAgICJub3RlcyI6IHBheWxvYWQuZ2V0KCJub3RlcyIsICIiKSwKICAgICAgICAgICAgImNhdGVnb3J5IjogInNhdmVkIiwKICAg"
    "ICAgICB9CiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5hcHBlbmQocHJvbW90ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZl"
    "ZF9saXN0cygpCgogICAgZGVmIF9kaXNtaXNzX3NlbGVjdGVkX2NvbW1vbihzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5jb21t"
    "b25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUp"
    "IGlmIGl0ZW0gZWxzZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNpZyA9"
    "IHBheWxvYWQuZ2V0KCJzaWduYXR1cmUiKQogICAgICAgIGlmIHNpZyBpbiBzZWxmLmNvbW1vbl9yb2xsczoKICAgICAgICAgICAg"
    "c2VsZi5jb21tb25fcm9sbHMucG9wKHNpZywgTm9uZSkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBk"
    "ZWYgX3Jlc2V0X3Bvb2woc2VsZik6CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2wgPSB7fQogICAgICAgIHNlbGYubW9kX3NwaW4u"
    "c2V0VmFsdWUoMCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQuY2xlYXIoKQogICAgICAgIHNlbGYucnVsZV9jb21iby5zZXRDdXJy"
    "ZW50SW5kZXgoMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0"
    "X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfY2xlYXJfaGlzdG9yeShzZWxmKToKICAgICAgICBzZWxmLnJv"
    "bGxfZXZlbnRzLmNsZWFyKCkKICAgICAgICBzZWxmLmV2ZW50X2J5X2lkLmNsZWFyKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcm9s"
    "bF9pZHMgPSBbXQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuY3VycmVudF90"
    "YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuX3VwZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAgc2VsZi5jdXJyZW50"
    "X3Jlc3VsdF9sYmwuc2V0VGV4dCgiTm8gcm9sbCB5ZXQuIikKCiAgICBkZWYgX2V2ZW50X2Zyb21fdGFibGVfcG9zaXRpb24oc2Vs"
    "ZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgcG9zKSAtPiBkaWN0IHwgTm9uZToKICAgICAgICBpdGVtID0gdGFibGUuaXRlbUF0KHBv"
    "cykKICAgICAgICBpZiBub3QgaXRlbToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICByb3cgPSBpdGVtLnJvdygpCiAg"
    "ICAgICAgdHNfaXRlbSA9IHRhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIG5vdCB0c19pdGVtOgogICAgICAgICAgICByZXR1"
    "cm4gTm9uZQogICAgICAgIGVpZCA9IHRzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgcmV0dXJu"
    "IHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGVpZCkKCiAgICBkZWYgX3Nob3dfcm9sbF9jb250ZXh0X21lbnUoc2VsZiwgdGFibGU6IFFU"
    "YWJsZVdpZGdldCwgcG9zKSAtPiBOb25lOgogICAgICAgIGV2dCA9IHNlbGYuX2V2ZW50X2Zyb21fdGFibGVfcG9zaXRpb24odGFi"
    "bGUsIHBvcykKICAgICAgICBpZiBub3QgZXZ0OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRn"
    "ZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIGFjdF9zZW5kID0gbWVudS5hZGRBY3Rp"
    "b24oIlNlbmQgdG8gUHJvbXB0IikKICAgICAgICBjaG9zZW4gPSBtZW51LmV4ZWModGFibGUudmlld3BvcnQoKS5tYXBUb0dsb2Jh"
    "bChwb3MpKQogICAgICAgIGlmIGNob3NlbiA9PSBhY3Rfc2VuZDoKICAgICAgICAgICAgc2VsZi5fc2VuZF9ldmVudF90b19wcm9t"
    "cHQoZXZ0KQoKICAgIGRlZiBfZm9ybWF0X2V2ZW50X2Zvcl9wcm9tcHQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IHN0cjoKICAgICAg"
    "ICBsYWJlbCA9IChldmVudC5nZXQoImxhYmVsIikgb3IgIlJvbGwiKS5zdHJpcCgpCiAgICAgICAgZ3JvdXBlZCA9IGV2ZW50Lmdl"
    "dCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBvciB7fQogICAgICAgIHNlZ21lbnRzID0gW10KICAgICAgICBmb3IgZGllIGlu"
    "IHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoK"
    "ICAgICAgICAgICAgICAgIHNlZ21lbnRzLmFwcGVuZChmIntkaWV9IHJvbGxlZCB7JywnLmpvaW4oc3RyKHYpIGZvciB2IGluIHZh"
    "bHMpfSIpCiAgICAgICAgbW9kID0gaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkKICAgICAgICB0b3RhbCA9IGludChldmVu"
    "dC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpCiAgICAgICAgcmV0dXJuIGYie2xhYmVsfTogeyc7ICcuam9pbihzZWdtZW50cyl9OyBt"
    "b2RpZmllciB7bW9kOitkfTsgdG90YWwge3RvdGFsfSIKCiAgICBkZWYgX3NlbmRfZXZlbnRfdG9fcHJvbXB0KHNlbGYsIGV2ZW50"
    "OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHdpbmRvdyA9IHNlbGYud2luZG93KCkKICAgICAgICBpZiBub3Qgd2luZG93IG9yIG5v"
    "dCBoYXNhdHRyKHdpbmRvdywgIl9pbnB1dF9maWVsZCIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBsaW5lID0gc2VsZi5f"
    "Zm9ybWF0X2V2ZW50X2Zvcl9wcm9tcHQoZXZlbnQpCiAgICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRUZXh0KGxpbmUpCiAg"
    "ICAgICAgd2luZG93Ll9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgZGVmIF9wbGF5X3JvbGxfc291bmQoc2VsZik6CiAgICAg"
    "ICAgaWYgbm90IFdJTlNPVU5EX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5k"
    "LkJlZXAoODQwLCAzMCkKICAgICAgICAgICAgd2luc291bmQuQmVlcCg2MjAsIDM1KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIHBhc3MKCgoKY2xhc3MgTWFnaWM4QmFsbFRhYihRV2lkZ2V0KToKICAgICIiIk1hZ2ljIDgtQmFsbCBtb2R1"
    "bGUgd2l0aCBjaXJjdWxhciBvcmIgZGlzcGxheSBhbmQgcHVsc2luZyBhbnN3ZXIgdGV4dC4iIiIKCiAgICBBTlNXRVJTID0gWwog"
    "ICAgICAgICJJdCBpcyBjZXJ0YWluLiIsCiAgICAgICAgIkl0IGlzIGRlY2lkZWRseSBzby4iLAogICAgICAgICJXaXRob3V0IGEg"
    "ZG91YnQuIiwKICAgICAgICAiWWVzIGRlZmluaXRlbHkuIiwKICAgICAgICAiWW91IG1heSByZWx5IG9uIGl0LiIsCiAgICAgICAg"
    "IkFzIEkgc2VlIGl0LCB5ZXMuIiwKICAgICAgICAiTW9zdCBsaWtlbHkuIiwKICAgICAgICAiT3V0bG9vayBnb29kLiIsCiAgICAg"
    "ICAgIlllcy4iLAogICAgICAgICJTaWducyBwb2ludCB0byB5ZXMuIiwKICAgICAgICAiUmVwbHkgaGF6eSwgdHJ5IGFnYWluLiIs"
    "CiAgICAgICAgIkFzayBhZ2FpbiBsYXRlci4iLAogICAgICAgICJCZXR0ZXIgbm90IHRlbGwgeW91IG5vdy4iLAogICAgICAgICJD"
    "YW5ub3QgcHJlZGljdCBub3cuIiwKICAgICAgICAiQ29uY2VudHJhdGUgYW5kIGFzayBhZ2Fpbi4iLAogICAgICAgICJEb24ndCBj"
    "b3VudCBvbiBpdC4iLAogICAgICAgICJNeSByZXBseSBpcyBuby4iLAogICAgICAgICJNeSBzb3VyY2VzIHNheSBuby4iLAogICAg"
    "ICAgICJPdXRsb29rIG5vdCBzbyBnb29kLiIsCiAgICAgICAgIlZlcnkgZG91YnRmdWwuIiwKICAgIF0KCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgb25fdGhyb3c9Tm9uZSwgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "KQogICAgICAgIHNlbGYuX29uX3Rocm93ID0gb25fdGhyb3cKICAgICAgICBzZWxmLl9sb2cgPSBkaWFnbm9zdGljc19sb2dnZXIg"
    "b3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9ICIiCgogICAg"
    "ICAgIHNlbGYuX2NsZWFyX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc2V0U2luZ2xlU2hv"
    "dChUcnVlKQogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9mYWRlX291dF9hbnN3ZXIpCgog"
    "ICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9idWlsZF9hbmltYXRpb25zKCkKICAgICAgICBzZWxmLl9zZXRf"
    "aWRsZV92aXN1YWwoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYsIDE2LCAxNikKICAgICAgICByb290LnNldFNwYWNp"
    "bmcoMTQpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgICAgIHNlbGYuX29yYl9mcmFtZSA9IFFGcmFtZSgpCiAgICAg"
    "ICAgc2VsZi5fb3JiX2ZyYW1lLnNldEZpeGVkU2l6ZSgyMjgsIDIyOCkKICAgICAgICBzZWxmLl9vcmJfZnJhbWUuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgIlFGcmFtZSB7IgogICAgICAgICAgICAiYmFja2dyb3VuZC1jb2xvcjogIzA0MDQwNjsiCiAgICAg"
    "ICAgICAgICJib3JkZXI6IDFweCBzb2xpZCByZ2JhKDIzNCwgMjM3LCAyNTUsIDAuNjIpOyIKICAgICAgICAgICAgImJvcmRlci1y"
    "YWRpdXM6IDExNHB4OyIKICAgICAgICAgICAgIn0iCiAgICAgICAgKQoKICAgICAgICBvcmJfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VsZi5fb3JiX2ZyYW1lKQogICAgICAgIG9yYl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDIwLCAyMCwgMjAsIDIwKQogICAg"
    "ICAgIG9yYl9sYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9vcmJfaW5uZXIgPSBRRnJhbWUoKQogICAgICAgIHNl"
    "bGYuX29yYl9pbm5lci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsiCiAgICAgICAgICAgICJiYWNrZ3JvdW5k"
    "LWNvbG9yOiAjMDcwNzBhOyIKICAgICAgICAgICAgImJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjU1LCAyNTUsIDI1NSwgMC4xMik7"
    "IgogICAgICAgICAgICAiYm9yZGVyLXJhZGl1czogODRweDsiCiAgICAgICAgICAgICJ9IgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9vcmJfaW5uZXIuc2V0TWluaW11bVNpemUoMTY4LCAxNjgpCiAgICAgICAgc2VsZi5fb3JiX2lubmVyLnNldE1heGltdW1TaXpl"
    "KDE2OCwgMTY4KQoKICAgICAgICBpbm5lcl9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9vcmJfaW5uZXIpCiAgICAgICAgaW5u"
    "ZXJfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxNiwgMTYsIDE2LCAxNikKICAgICAgICBpbm5lcl9sYXlvdXQuc2V0U3BhY2lu"
    "ZygwKQoKICAgICAgICBzZWxmLl9laWdodF9sYmwgPSBRTGFiZWwoIjgiKQogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5zZXRBbGln"
    "bm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgImNvbG9yOiByZ2JhKDI1NSwgMjU1LCAyNTUsIDAuOTUpOyAiCiAgICAgICAgICAgICJmb250LXNpemU6IDgw"
    "cHg7IGZvbnQtd2VpZ2h0OiA3MDA7ICIKICAgICAgICAgICAgImZvbnQtZmFtaWx5OiBHZW9yZ2lhLCBzZXJpZjsgYm9yZGVyOiBu"
    "b25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuYW5zd2VyX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLmFuc3dlcl9s"
    "Ymwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFdv"
    "cmRXcmFwKFRydWUpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtD"
    "X0dPTER9OyBmb250LXNpemU6IDE2cHg7IGZvbnQtc3R5bGU6IGl0YWxpYzsgIgogICAgICAgICAgICAiZm9udC13ZWlnaHQ6IDYw"
    "MDsgYm9yZGVyOiBub25lOyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKCiAgICAgICAgaW5uZXJfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLl9laWdodF9sYmwsIDEpCiAgICAgICAgaW5uZXJfbGF5b3V0LmFkZFdpZGdldChzZWxmLmFuc3dlcl9sYmwsIDEpCiAgICAg"
    "ICAgb3JiX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fb3JiX2lubmVyLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9vcmJfZnJhbWUsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25IQ2VudGVyKQoK"
    "ICAgICAgICBzZWxmLnRocm93X2J0biA9IFFQdXNoQnV0dG9uKCJUaHJvdyB0aGUgOC1CYWxsIikKICAgICAgICBzZWxmLnRocm93"
    "X2J0bi5zZXRGaXhlZEhlaWdodCgzOCkKICAgICAgICBzZWxmLnRocm93X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGhyb3df"
    "YmFsbCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnRocm93X2J0biwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkhDZW50"
    "ZXIpCiAgICAgICAgcm9vdC5hZGRTdHJldGNoKDEpCgogICAgZGVmIF9idWlsZF9hbmltYXRpb25zKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkgPSBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0KHNlbGYuYW5zd2VyX2xibCkKICAgICAg"
    "ICBzZWxmLmFuc3dlcl9sYmwuc2V0R3JhcGhpY3NFZmZlY3Qoc2VsZi5fYW5zd2VyX29wYWNpdHkpCiAgICAgICAgc2VsZi5fYW5z"
    "d2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCgogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0gPSBRUHJvcGVydHlBbmltYXRpb24o"
    "c2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXREdXJhdGlv"
    "big3NjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRTdGFydFZhbHVlKDAuMzUpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5p"
    "bS5zZXRFbmRWYWx1ZSgxLjApCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRFYXNpbmdDdXJ2ZShRRWFzaW5nQ3VydmUuVHlw"
    "ZS5Jbk91dFNpbmUpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zZXRMb29wQ291bnQoLTEpCgogICAgICAgIHNlbGYuX2ZhZGVf"
    "b3V0ID0gUVByb3BlcnR5QW5pbWF0aW9uKHNlbGYuX2Fuc3dlcl9vcGFjaXR5LCBiIm9wYWNpdHkiLCBzZWxmKQogICAgICAgIHNl"
    "bGYuX2ZhZGVfb3V0LnNldER1cmF0aW9uKDU2MCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZhbHVlKDEuMCkKICAg"
    "ICAgICBzZWxmLl9mYWRlX291dC5zZXRFbmRWYWx1ZSgwLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RWFzaW5nQ3VydmUo"
    "UUVhc2luZ0N1cnZlLlR5cGUuSW5PdXRRdWFkKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5f"
    "Y2xlYXJfdG9faWRsZSkKCiAgICBkZWYgX3NldF9pZGxlX3Zpc3VhbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2N1cnJl"
    "bnRfYW5zd2VyID0gIiIKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLmNsZWFy"
    "KCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgw"
    "LjApCgogICAgZGVmIF90aHJvd19iYWxsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RvcCgpCiAg"
    "ICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9wKCkKCiAgICAgICAgYW5zd2Vy"
    "ID0gcmFuZG9tLmNob2ljZShzZWxmLkFOU1dFUlMpCiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSBhbnN3ZXIKCiAgICAg"
    "ICAgc2VsZi5fZWlnaHRfbGJsLmhpZGUoKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRUZXh0KGFuc3dlcikKICAgICAgICBz"
    "ZWxmLmFuc3dlcl9sYmwuc2hvdygpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3BhY2l0eSgwLjApCiAgICAgICAg"
    "c2VsZi5fcHVsc2VfYW5pbS5zdGFydCgpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RhcnQoNjAwMDApCiAgICAgICAgc2Vs"
    "Zi5fbG9nKGYiWzhCQUxMXSBUaHJvdyByZXN1bHQ6IHthbnN3ZXJ9IiwgIklORk8iKQoKICAgICAgICBpZiBjYWxsYWJsZShzZWxm"
    "Ll9vbl90aHJvdyk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Rocm93KGFuc3dlcikKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhmIls4QkFMTF1bV0FSTl0gSW50"
    "ZXJuYWwgcHJvbXB0IGRpc3BhdGNoIGZhaWxlZDoge2V4fSIsICJXQVJOIikKCiAgICBkZWYgX2ZhZGVfb3V0X2Fuc3dlcihzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0uc3RvcCgp"
    "CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0U3RhcnRWYWx1ZShmbG9hdChz"
    "ZWxmLl9hbnN3ZXJfb3BhY2l0eS5vcGFjaXR5KCkpKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVuZFZhbHVlKDAuMCkKICAg"
    "ICAgICBzZWxmLl9mYWRlX291dC5zdGFydCgpCgogICAgZGVmIF9jbGVhcl90b19pZGxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fZmFkZV9vdXQuc3RvcCgpCiAgICAgICAgc2VsZi5fc2V0X2lkbGVfdmlzdWFsKCkKCiMg4pSA4pSAIE1BSU4gV0lORE9X"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMb2NrQXdhcmVUYWJCYXIoUVRhYkJhcik6CiAg"
    "ICAiIiJUYWIgYmFyIHRoYXQgYmxvY2tzIGRyYWcgaW5pdGlhdGlvbiBmb3IgbG9ja2VkIHRhYnMuIiIiCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIGlzX2xvY2tlZF9ieV9pZCwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCA9IGlzX2xvY2tlZF9ieV9pZAogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXgg"
    "PSAtMQoKICAgIGRlZiBfdGFiX2lkKHNlbGYsIGluZGV4OiBpbnQpOgogICAgICAgIGlmIGluZGV4IDwgMDoKICAgICAgICAgICAg"
    "cmV0dXJuIE5vbmUKICAgICAgICByZXR1cm4gc2VsZi50YWJEYXRhKGluZGV4KQoKICAgIGRlZiBtb3VzZVByZXNzRXZlbnQoc2Vs"
    "ZiwgZXZlbnQpOgogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXggPSBzZWxmLnRhYkF0KGV2ZW50LnBvcygpKQogICAgICAgIGlm"
    "IChldmVudC5idXR0b24oKSA9PSBRdC5Nb3VzZUJ1dHRvbi5MZWZ0QnV0dG9uIGFuZCBzZWxmLl9wcmVzc2VkX2luZGV4ID49IDAp"
    "OgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl90YWJfaWQoc2VsZi5fcHJlc3NlZF9pbmRleCkKICAgICAgICAgICAgaWYgdGFi"
    "X2lkIGFuZCBzZWxmLl9pc19sb2NrZWRfYnlfaWQodGFiX2lkKToKICAgICAgICAgICAgICAgIHNlbGYuc2V0Q3VycmVudEluZGV4"
    "KHNlbGYuX3ByZXNzZWRfaW5kZXgpCiAgICAgICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlTW92ZUV2ZW50KHNlbGYsIGV2ZW50"
    "KToKICAgICAgICBpZiBzZWxmLl9wcmVzc2VkX2luZGV4ID49IDA6CiAgICAgICAgICAgIHRhYl9pZCA9IHNlbGYuX3RhYl9pZChz"
    "ZWxmLl9wcmVzc2VkX2luZGV4KQogICAgICAgICAgICBpZiB0YWJfaWQgYW5kIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCh0YWJfaWQp"
    "OgogICAgICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIHN1cGVyKCkubW91"
    "c2VNb3ZlRXZlbnQoZXZlbnQpCgogICAgZGVmIG1vdXNlUmVsZWFzZUV2ZW50KHNlbGYsIGV2ZW50KToKICAgICAgICBzZWxmLl9w"
    "cmVzc2VkX2luZGV4ID0gLTEKICAgICAgICBzdXBlcigpLm1vdXNlUmVsZWFzZUV2ZW50KGV2ZW50KQoKCmNsYXNzIEVjaG9EZWNr"
    "KFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lk"
    "Z2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9y"
    "IHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRl"
    "ciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaS"
    "IGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29u"
    "ZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVk"
    "IGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAg"
    "IyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAK"
    "ICAgICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAg"
    "ID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQg"
    "ICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNl"
    "bGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAg"
    "ICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3Qgc3Ry"
    "ZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAg"
    "ICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVy"
    "IG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUg"
    "Y291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRl"
    "cgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAg"
    "ID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgPSAi"
    "IiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAg"
    "ICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdl"
    "cigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0"
    "aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAgIHNl"
    "bGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxb"
    "UVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJd"
    "ID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXgg"
    "PSAtMQogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0"
    "ZXIgPSAibmV4dF8zX21vbnRocyIKCiAgICAgICAgIyBSaWdodCBzeXN0ZW1zIHRhYi1zdHJpcCBwcmVzZW50YXRpb24gc3RhdGUg"
    "KHN0YWJsZSBJRHMgKyB2aXN1YWwgb3JkZXIpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnM6IGxpc3RbZGljdF0gPSBbXQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZTogZGljdFtzdHIsIGRpY3RdID0ge30KICAgICAgICBzZWxmLl9zcGVsbF90YWJf"
    "bW92ZV9tb2RlX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3Np"
    "Z25hbCA9IEZhbHNlCiAgICAgICAgc2VsZi5fZm9jdXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzID0gRmFsc2UKCiAgICAgICAgIyDi"
    "lIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFwcGVycyB1cC1mcm9udDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIK"
    "ICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdpbmRvdy5zaG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgog"
    "ICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgImNyZWRlbnRp"
    "YWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICAg"
    "ICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0"
    "b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAgICAgKSkKICAgICAg"
    "ICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRoKQogICAgICAgIHNl"
    "bGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNlcnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwKICAgICAgICAgICAg"
    "Z190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAgIyBTZWVkIExTTCBydWxlcyBvbiBmaXJzdCBy"
    "dW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRfbHNsX3J1bGVzKCkKCiAgICAgICAgIyBMb2FkIGVudGl0eSBzdGF0ZQogICAg"
    "ICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRfc3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRlWyJzZXNzaW9uX2Nv"
    "dW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Npb25fY291bnQiLDApICsgMQogICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0"
    "YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAg"
    "ICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKQoK"
    "ICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAgICAgc2VsZi5fZmFj"
    "ZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1lck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBVSSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTIwMCwg"
    "NzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAsIDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCgogICAg"
    "ICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8gd2lkZ2V0cwogICAgICAg"
    "IHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigKICAgICAgICAgICAgc2VsZi5fbWlycm9yLCBzZWxmLl9l"
    "bW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUaW1lcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3Rh"
    "dHNfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl91cGRhdGVf"
    "c3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIgPSBR"
    "VGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykKICAgICAgICBzZWxm"
    "Ll9ibGlua190aW1lci5zdGFydCg4MDApCgogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRpbWVyKCkKICAgICAg"
    "ICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQgc2VsZi5fZm9vdGVyX3N0cmlwIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxm"
    "Ll9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fZm9vdGVyX3N0cmlwLnJlZnJlc2gpCiAgICAgICAgICAg"
    "IHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciA9"
    "IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9n"
    "b29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KHNlbGYuX2dl"
    "dF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcygpKQoKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVy"
    "ID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qo"
    "c2VsZi5fb25fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3Jl"
    "ZnJlc2hfdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgICMg4pSA4pSA"
    "IFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZlcnJlZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAgICAg"
    "ICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVwX3NlcXVlbmNlKCkgaGVyZS4KICAgICAgICAjIEJv"
    "dGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgZnJvbSBtYWluKCkgYWZ0ZXIKICAgICAgICAjIHdpbmRvdy5z"
    "aG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zIHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2VudHJhbCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoY2VudHJhbCkKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAg"
    "ICAgICMg4pSA4pSAIEJvZHk6IGxlZnQgd29ya3NwYWNlIHwgcmlnaHQgc3lzdGVtcyAoZHJhZ2dhYmxlIHNwbGl0dGVyKSDilIAK"
    "ICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLkhvcml6b250YWwpCiAgICAgICAg"
    "c2VsZi5fbWFpbl9zcGxpdHRlci5zZXRDaGlsZHJlbkNvbGxhcHNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX21haW5fc3BsaXR0"
    "ZXIuc2V0SGFuZGxlV2lkdGgoOCkKCiAgICAgICAgIyBMZWZ0IHBhbmUgPSBKb3VybmFsICsgQ2hhdCB3b3Jrc3BhY2UKICAgICAg"
    "ICBsZWZ0X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIGxlZnRfd29ya3NwYWNlLnNldE1pbmltdW1XaWR0aCg3MDApCiAg"
    "ICAgICAgbGVmdF9sYXlvdXQgPSBRSEJveExheW91dChsZWZ0X3dvcmtzcGFjZSkKICAgICAgICBsZWZ0X2xheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsZWZ0X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuX2pv"
    "dXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJh"
    "ci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2xvYWRfam91cm5hbF9zZXNzaW9uKQog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBz"
    "ZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgbGVmdF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lk"
    "ZWJhcikKICAgICAgICBsZWZ0X2xheW91dC5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAj"
    "IFJpZ2h0IHBhbmUgPSBzeXN0ZW1zL21vZHVsZXMgKyBjYWxlbmRhcgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRnZXQo"
    "KQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZS5zZXRNaW5pbXVtV2lkdGgoMzYwKQogICAgICAgIHJpZ2h0X2xheW91dCA9IFFWQm94"
    "TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDAp"
    "CiAgICAgICAgcmlnaHRfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICByaWdodF9sYXlvdXQuYWRkTGF5b3V0KHNlbGYuX2J1"
    "aWxkX3NwZWxsYm9va19wYW5lbCgpLCAxKQoKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLmFkZFdpZGdldChsZWZ0X3dvcmtz"
    "cGFjZSkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UpCiAgICAgICAgc2VsZi5f"
    "bWFpbl9zcGxpdHRlci5zZXRDb2xsYXBzaWJsZSgwLCBGYWxzZSkKICAgICAgICBzZWxmLl9tYWluX3NwbGl0dGVyLnNldENvbGxh"
    "cHNpYmxlKDEsIEZhbHNlKQogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuc3BsaXR0ZXJNb3ZlZC5jb25uZWN0KHNlbGYuX3Nh"
    "dmVfbWFpbl9zcGxpdHRlcl9zdGF0ZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9tYWluX3NwbGl0dGVyLCAxKQogICAg"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYuX3Jlc3RvcmVfbWFpbl9zcGxpdHRlcl9zdGF0ZSkKCiAgICAgICAgIyDilIDi"
    "lIAgRm9vdGVyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZvb3RlciA9IFFMYWJlbCgKICAgICAgICAgICAgZiLinKYge0FQUF9OQU1FfSDi"
    "gJQgdntBUFBfVkVSU0lPTn0g4pymIgogICAgICAgICkKICAgICAgICBmb290ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBmb290ZXIuc2V0QWxpZ25tZW50KFF0"
    "LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoZm9vdGVyKQoKICAgIGRlZiBfYnVpbGRf"
    "dGl0bGVfYmFyKHNlbGYpIC0+IFFXaWRnZXQ6CiAgICAgICAgYmFyID0gUVdpZGdldCgpCiAgICAgICAgYmFyLnNldEZpeGVkSGVp"
    "Z2h0KDM2KQogICAgICAgIGJhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAg"
    "KQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGJhcikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDEwLCAw"
    "LCAxMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg2KQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7QVBQX05B"
    "TUV9IikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1z"
    "aXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImxldHRlci1zcGFjaW5nOiAycHg7IGJvcmRlcjog"
    "bm9uZTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBydW5lcyA9IFFMYWJlbChS"
    "VU5FUykKICAgICAgICBydW5lcy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQt"
    "c2l6ZTogMTBweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcnVuZXMuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVu"
    "dEZsYWcuQWxpZ25DZW50ZXIpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKGYi4peJIHtVSV9PRkZMSU5FX1NU"
    "QVRVU30iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0JM"
    "T09EfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5zdGF0dXNfbGFiZWwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25SaWdodCkKCiAgICAgICAgIyBTdXNw"
    "ZW5zaW9uIHBhbmVsCiAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gTm9uZQogICAgICAgIGlmIFNVU1BFTlNJT05fRU5BQkxF"
    "RDoKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gVG9ycG9yUGFuZWwoKQogICAgICAgICAgICBzZWxmLl90b3Jwb3Jf"
    "cGFuZWwuc3RhdGVfY2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKQoKICAgICAgICAjIElkbGUg"
    "dG9nZ2xlCiAgICAgICAgaWRsZV9lbmFibGVkID0gYm9vbChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImlkbGVfZW5hYmxl"
    "ZCIsIEZhbHNlKSkKICAgICAgICBzZWxmLl9pZGxlX2J0biA9IFFQdXNoQnV0dG9uKCJJRExFIE9OIiBpZiBpZGxlX2VuYWJsZWQg"
    "ZWxzZSAiSURMRSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2lk"
    "bGVfYnRuLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrZWQoaWRsZV9lbmFibGVkKQog"
    "ICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRp"
    "dXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhw"
    "eDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9vbl9pZGxlX3RvZ2dsZWQp"
    "CgogICAgICAgICMgRlMgLyBCTCBidXR0b25zCiAgICAgICAgc2VsZi5fZnNfYnRuID0gUVB1c2hCdXR0b24oIkZ1bGxzY3JlZW4i"
    "KQogICAgICAgIHNlbGYuX2JsX2J0biA9IFFQdXNoQnV0dG9uKCJCb3JkZXJsZXNzIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRu"
    "ID0gUVB1c2hCdXR0b24oIkV4cG9ydCIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuID0gUVB1c2hCdXR0b24oIlNodXRkb3du"
    "IikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLl9mc19idG4sIHNlbGYuX2JsX2J0biwgc2VsZi5fZXhwb3J0X2J0bik6CiAgICAg"
    "ICAgICAgIGJ0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdo"
    "dDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldEZpeGVkV2lkdGgo"
    "NDYpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0"
    "bi5zZXRGaXhlZFdpZHRoKDY4KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19CTE9PRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CTE9PRH07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7Igog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9mc19idG4uc2V0VG9vbFRpcCgiRnVsbHNjcmVlbiAoRjExKSIpCiAgICAgICAgc2VsZi5f"
    "YmxfYnRuLnNldFRvb2xUaXAoIkJvcmRlcmxlc3MgKEYxMCkiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0VG9vbFRpcCgi"
    "RXhwb3J0IGNoYXQgc2Vzc2lvbiB0byBUWFQgZmlsZSIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFRvb2xUaXAoZiJH"
    "cmFjZWZ1bCBzaHV0ZG93biDigJQge0RFQ0tfTkFNRX0gc3BlYWtzIHRoZWlyIGxhc3Qgd29yZHMiKQogICAgICAgIHNlbGYuX2Zz"
    "X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2Z1bGxzY3JlZW4pCiAgICAgICAgc2VsZi5fYmxfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl90b2dnbGVfYm9yZGVybGVzcykKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9leHBvcnRfY2hhdCkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luaXRpYXRl"
    "X3NodXRkb3duX2RpYWxvZykKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0aXRsZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHJ1bmVzLCAxKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCiAgICAgICAgbGF5b3V0LmFkZFNw"
    "YWNpbmcoOCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2V4cG9ydF9idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9zaHV0ZG93bl9idG4pCgogICAgICAgIHJldHVybiBiYXIKCiAgICBkZWYgX2J1aWxkX2NoYXRfcGFuZWwoc2VsZikg"
    "LT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQp"
    "CgogICAgICAgICMgTWFpbiB0YWIgd2lkZ2V0IOKAlCBwZXJzb25hIGNoYXQgdGFiIHwgU2VsZgogICAgICAgIHNlbGYuX21haW5f"
    "dGFicyA9IFFUYWJXaWRnZXQoKQogICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFU"
    "YWJXaWRnZXQ6OnBhbmUge3sgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfTU9OSVRPUn07IH19IgogICAgICAgICAgICBmIlFUYWJCYXI6OnRhYiB7eyBiYWNrZ3JvdW5kOiB7Q19CRzN9OyBj"
    "b2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNHB4IDEycHg7IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7"
    "IH19IgogICAgICAgICAgICBmIlFUYWJCYXI6OnRhYjpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0Nf"
    "R09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJTVNPTn07IH19IgogICAgICAgICkK"
    "CiAgICAgICAgIyDilIDilIAgVGFiIDA6IFBlcnNvbmEgY2hhdCB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc2VhbmNlX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlYW5jZV9sYXlvdXQgPSBRVkJveExheW91dChzZWFuY2Vf"
    "d2lkZ2V0KQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VhbmNl"
    "X2xheW91dC5zZXRTcGFjaW5nKDApCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4"
    "OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWFuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9jaGF0X2Rpc3Bs"
    "YXkpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWFuY2Vfd2lkZ2V0LCBmIuKdpyB7VUlfQ0hBVF9XSU5ET1d9IikK"
    "CiAgICAgICAgIyDilIDilIAgVGFiIDE6IFNlbGYg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2VsZl90YWJfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAg"
    "c2VsZl9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9zZWxmX3RhYl93aWRnZXQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX3Nl"
    "bGZfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAg"
    "ICAgc2VsZi5fc2VsZl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07"
    "IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NlbGZfZGlzcGxheSwgMSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNl"
    "bGYuX3NlbGZfdGFiX3dpZGdldCwgIuKXiSBTRUxGIikKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9tYWluX3RhYnMs"
    "IDEpCgogICAgICAgICMg4pSA4pSAIEJvdHRvbSBzdGF0dXMvcmVzb3VyY2UgYmxvY2sgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgTWFu"
    "ZGF0b3J5IHBlcm1hbmVudCBzdHJ1Y3R1cmUgYWNyb3NzIGFsbCBwZXJzb25hczoKICAgICAgICAjIE1JUlJPUiB8IFtMT1dFUi1N"
    "SURETEUgUEVSTUFORU5UIEZPT1RQUklOVF0KICAgICAgICBibG9ja19yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYmxvY2tf"
    "cm93LnNldFNwYWNpbmcoMikKCiAgICAgICAgIyBNaXJyb3IgKG5ldmVyIGNvbGxhcHNlcykKICAgICAgICBtaXJyb3Jfd3JhcCA9"
    "IFFXaWRnZXQoKQogICAgICAgIG13X2xheW91dCA9IFFWQm94TGF5b3V0KG1pcnJvcl93cmFwKQogICAgICAgIG13X2xheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtd19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIG13X2xh"
    "eW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIHtVSV9NSVJST1JfTEFCRUx9IikpCiAgICAgICAgc2VsZi5fbWlycm9y"
    "ID0gTWlycm9yV2lkZ2V0KCkKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0Rml4ZWRTaXplKDE2MCwgMTYwKQogICAgICAgIG13X2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fbWlycm9yKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlycm9yX3dyYXAsIDApCgog"
    "ICAgICAgICMgTWlkZGxlIGxvd2VyIGJsb2NrIGtlZXBzIGEgcGVybWFuZW50IGZvb3RwcmludDoKICAgICAgICAjIGxlZnQgPSBj"
    "b21wYWN0IHN0YWNrIGFyZWEsIHJpZ2h0ID0gZml4ZWQgZXhwYW5kZWQtcm93IHNsb3RzLgogICAgICAgIG1pZGRsZV93cmFwID0g"
    "UVdpZGdldCgpCiAgICAgICAgbWlkZGxlX2xheW91dCA9IFFIQm94TGF5b3V0KG1pZGRsZV93cmFwKQogICAgICAgIG1pZGRsZV9s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRTcGFjaW5nKDIpCgog"
    "ICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNl"
    "dE1pbmltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRNYXhpbXVtV2lkdGgoMTMwKQogICAg"
    "ICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2xvd2VyX3N0YWNrX3dyYXApCiAgICAgICAg"
    "c2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2xvd2Vy"
    "X3N0YWNrX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxlKEZhbHNl"
    "KQogICAgICAgIG1pZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAsIDApCgogICAgICAgIHNlbGYu"
    "X2xvd2VyX2V4cGFuZGVkX3JvdyA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQgPSBR"
    "R3JpZExheW91dChzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3cpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNl"
    "dEhvcml6b250YWxTcGFjaW5nKDIpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5zZXRWZXJ0aWNhbFNw"
    "YWNpbmcoMikKICAgICAgICBtaWRkbGVfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3csIDEpCgogICAg"
    "ICAgICMgRW1vdGlvbiBibG9jayAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fZW1vdGlvbl9ibG9jayA9IEVtb3Rpb25CbG9j"
    "aygpCiAgICAgICAgc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacg"
    "e1VJX0VNT1RJT05TX0xBQkVMfSIsIHNlbGYuX2Vtb3Rpb25fYmxvY2ssCiAgICAgICAgICAgIGV4cGFuZGVkPVRydWUsIG1pbl93"
    "aWR0aD0xMzAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBMZWZ0IHJlc291cmNlIG9yYiAoY29sbGFw"
    "c2libGUpCiAgICAgICAgc2VsZi5fbGVmdF9vcmIgPSBTcGhlcmVXaWRnZXQoCiAgICAgICAgICAgIFVJX0xFRlRfT1JCX0xBQkVM"
    "LCBDX0NSSU1TT04sIENfQ1JJTVNPTl9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fbGVmdF9vcmJfd3JhcCA9IENvbGxhcHNp"
    "YmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9MRUZUX09SQl9USVRMRX0iLCBzZWxmLl9sZWZ0X29yYiwKICAgICAgICAg"
    "ICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgQ2VudGVyIGN5Y2xlIHdpZGdl"
    "dCAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fY3ljbGVfd2lkZ2V0ID0gQ3ljbGVXaWRnZXQoKQogICAgICAgIHNlbGYuX2N5"
    "Y2xlX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfQ1lDTEVfVElUTEV9Iiwgc2VsZi5fY3lj"
    "bGVfd2lkZ2V0LAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAg"
    "IyBSaWdodCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX3JpZ2h0X29yYiA9IFNwaGVyZVdpZGdldCgK"
    "ICAgICAgICAgICAgVUlfUklHSFRfT1JCX0xBQkVMLCBDX1BVUlBMRSwgQ19QVVJQTEVfRElNCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX3JpZ2h0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX1JJR0hUX09SQl9USVRM"
    "RX0iLCBzZWxmLl9yaWdodF9vcmIsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAg"
    "KQoKICAgICAgICAjIEVzc2VuY2UgKDIgZ2F1Z2VzLCBjb2xsYXBzaWJsZSkKICAgICAgICBlc3NlbmNlX3dpZGdldCA9IFFXaWRn"
    "ZXQoKQogICAgICAgIGVzc2VuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZXNzZW5jZV93aWRnZXQpCiAgICAgICAgZXNzZW5jZV9s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSAgID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9QUklNQVJZLCAgICIl"
    "IiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZSA9IEdhdWdlV2lkZ2V0KFVJ"
    "X0VTU0VOQ0VfU0VDT05EQVJZLCAiJSIsIDEwMC4wLCBDX0dSRUVOKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2UpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2Vf"
    "c2Vjb25kYXJ5X2dhdWdlKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAg"
    "IGYi4p2nIHtVSV9FU1NFTkNFX1RJVExFfSIsIGVzc2VuY2Vfd2lkZ2V0LAogICAgICAgICAgICBtaW5fd2lkdGg9MTEwLCByZXNl"
    "cnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXhwYW5kZWQgcm93IHNsb3RzIG11c3Qgc3RheSBpbiBjYW5vbmlj"
    "YWwgdmlzdWFsIG9yZGVyLgogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Nsb3Rfb3JkZXIgPSBbCiAgICAgICAgICAgICJl"
    "bW90aW9ucyIsICJwcmltYXJ5IiwgImN5Y2xlIiwgInNlY29uZGFyeSIsICJlc3NlbmNlIgogICAgICAgIF0KICAgICAgICBzZWxm"
    "Ll9sb3dlcl9jb21wYWN0X3N0YWNrX29yZGVyID0gWwogICAgICAgICAgICAiY3ljbGUiLCAicHJpbWFyeSIsICJzZWNvbmRhcnki"
    "LCAiZXNzZW5jZSIsICJlbW90aW9ucyIKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzID0gewogICAg"
    "ICAgICAgICAiZW1vdGlvbnMiOiBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAsCiAgICAgICAgICAgICJwcmltYXJ5Ijogc2VsZi5f"
    "bGVmdF9vcmJfd3JhcCwKICAgICAgICAgICAgImN5Y2xlIjogc2VsZi5fY3ljbGVfd3JhcCwKICAgICAgICAgICAgInNlY29uZGFy"
    "eSI6IHNlbGYuX3JpZ2h0X29yYl93cmFwLAogICAgICAgICAgICAiZXNzZW5jZSI6IHNlbGYuX2Vzc2VuY2Vfd3JhcCwKICAgICAg"
    "ICB9CgogICAgICAgIHNlbGYuX2xvd2VyX3Jvd19zbG90cyA9IHt9CiAgICAgICAgZm9yIGNvbCwga2V5IGluIGVudW1lcmF0ZShz"
    "ZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90X29yZGVyKToKICAgICAgICAgICAgc2xvdCA9IFFXaWRnZXQoKQogICAgICAgICAgICBz"
    "bG90X2xheW91dCA9IFFWQm94TGF5b3V0KHNsb3QpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgICAgICBzbG90X2xheW91dC5zZXRTcGFjaW5nKDApCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX2V4"
    "cGFuZGVkX3Jvd19sYXlvdXQuYWRkV2lkZ2V0KHNsb3QsIDAsIGNvbCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "cm93X2xheW91dC5zZXRDb2x1bW5TdHJldGNoKGNvbCwgMSkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfcm93X3Nsb3RzW2tleV0g"
    "PSBzbG90X2xheW91dAoKICAgICAgICBmb3Igd3JhcCBpbiBzZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMudmFsdWVzKCk6CiAgICAg"
    "ICAgICAgIHdyYXAudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dCkKCiAgICAgICAgc2Vs"
    "Zi5fcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KCkKCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaWRkbGVfd3JhcCwg"
    "MSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJsb2NrX3JvdykKCiAgICAgICAgIyBGb290ZXIgc3RhdGUgc3RyaXAgKGJlbG93"
    "IGJsb2NrIHJvdyDigJQgcGVybWFuZW50IFVJIHN0cnVjdHVyZSkKICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAgPSBGb290ZXJT"
    "dHJpcFdpZGdldCgpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwLnNldF9sYWJlbChVSV9GT09URVJfU1RSSVBfTEFCRUwpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9mb290ZXJfc3RyaXApCgogICAgICAgICMg4pSA4pSAIElucHV0IHJvdyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBpbnB1dF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgcHJvbXB0X3N5bSA9IFFMYWJlbCgi4pymIikKICAgICAgICBw"
    "cm9tcHRfc3ltLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE2cHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBwcm9tcHRfc3ltLnNldEZpeGVkV2lk"
    "dGgoMjApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5z"
    "ZXRQbGFjZWhvbGRlclRleHQoVUlfSU5QVVRfUExBQ0VIT0xERVIpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQucmV0dXJuUHJl"
    "c3NlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNl"
    "KQoKICAgICAgICBzZWxmLl9zZW5kX2J0biA9IFFQdXNoQnV0dG9uKFVJX1NFTkRfQlVUVE9OKQogICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuLnNldEZpeGVkV2lkdGgoMTEwKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZW5kX21l"
    "c3NhZ2UpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdl"
    "dChwcm9tcHRfc3ltKQogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5faW5wdXRfZmllbGQpCiAgICAgICAgaW5wdXRf"
    "cm93LmFkZFdpZGdldChzZWxmLl9zZW5kX2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGlucHV0X3JvdykKCiAgICAgICAg"
    "cmV0dXJuIGxheW91dAoKICAgIGRlZiBfY2xlYXJfbGF5b3V0X3dpZGdldHMoc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4g"
    "Tm9uZToKICAgICAgICB3aGlsZSBsYXlvdXQuY291bnQoKToKICAgICAgICAgICAgaXRlbSA9IGxheW91dC50YWtlQXQoMCkKICAg"
    "ICAgICAgICAgd2lkZ2V0ID0gaXRlbS53aWRnZXQoKQogICAgICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgICAgICB3aWRnZXQuc2V0UGFyZW50KE5vbmUpCgogICAgZGVmIF9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQoc2VsZiwg"
    "Kl9hcmdzKSAtPiBOb25lOgogICAgICAgIGNvbGxhcHNlZF9jb3VudCA9IDAKCiAgICAgICAgIyBSZWJ1aWxkIGV4cGFuZGVkIHJv"
    "dyBzbG90cyBpbiBmaXhlZCBleHBhbmRlZCBvcmRlci4KICAgICAgICBmb3Iga2V5IGluIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Ns"
    "b3Rfb3JkZXI6CiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gc2VsZi5fbG93ZXJfcm93X3Nsb3RzW2tleV0KICAgICAgICAgICAg"
    "c2VsZi5fY2xlYXJfbGF5b3V0X3dpZGdldHMoc2xvdF9sYXlvdXQpCiAgICAgICAgICAgIHdyYXAgPSBzZWxmLl9sb3dlcl9tb2R1"
    "bGVfd3JhcHNba2V5XQogICAgICAgICAgICBpZiB3cmFwLmlzX2V4cGFuZGVkKCk6CiAgICAgICAgICAgICAgICBzbG90X2xheW91"
    "dC5hZGRXaWRnZXQod3JhcCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGNvbGxhcHNlZF9jb3VudCArPSAxCiAg"
    "ICAgICAgICAgICAgICBzbG90X2xheW91dC5hZGRTdHJldGNoKDEpCgogICAgICAgICMgUmVidWlsZCBjb21wYWN0IHN0YWNrIGlu"
    "IGNhbm9uaWNhbCBjb21wYWN0IG9yZGVyLgogICAgICAgIHNlbGYuX2NsZWFyX2xheW91dF93aWRnZXRzKHNlbGYuX2xvd2VyX3N0"
    "YWNrX2xheW91dCkKICAgICAgICBmb3Iga2V5IGluIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tfb3JkZXI6CiAgICAgICAgICAg"
    "IHdyYXAgPSBzZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHNba2V5XQogICAgICAgICAgICBpZiBub3Qgd3JhcC5pc19leHBhbmRlZCgp"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LmFkZFdpZGdldCh3cmFwKQoKICAgICAgICBzZWxmLl9s"
    "b3dlcl9zdGFja19sYXlvdXQuYWRkU3RyZXRjaCgxKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0VmlzaWJsZShj"
    "b2xsYXBzZWRfY291bnQgPiAwKQoKICAgIGRlZiBfYnVpbGRfc3BlbGxib29rX3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0Ogog"
    "ICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDAp"
    "CiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFNZ"
    "U1RFTVMiKSkKCiAgICAgICAgIyBUYWIgd2lkZ2V0CiAgICAgICAgc2VsZi5fc3BlbGxfdGFicyA9IFFUYWJXaWRnZXQoKQogICAg"
    "ICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0TWluaW11bVdpZHRoKDI4MCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldFNpemVQ"
    "b2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBv"
    "bGljeS5FeHBhbmRpbmcKICAgICAgICApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2JhciA9IExvY2tBd2FyZVRhYkJhcihzZWxm"
    "Ll9pc19zcGVsbF90YWJfbG9ja2VkLCBzZWxmLl9zcGVsbF90YWJzKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0VGFiQmFy"
    "KHNlbGYuX3NwZWxsX3RhYl9iYXIpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRNb3ZhYmxlKFRydWUpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0"
    "TWVudSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3Qoc2VsZi5f"
    "c2hvd19zcGVsbF90YWJfY29udGV4dF9tZW51KQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiTW92ZWQuY29ubmVjdChz"
    "ZWxmLl9vbl9zcGVsbF90YWJfZHJhZ19tb3ZlZCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmN1cnJlbnRDaGFuZ2VkLmNvbm5l"
    "Y3QobGFtYmRhIF9pZHg6IHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpKQogICAgICAgIGlmIG5vdCBzZWxmLl9mb2N1"
    "c19ob29rZWRfZm9yX3NwZWxsX3RhYnM6CiAgICAgICAgICAgIGFwcCA9IFFBcHBsaWNhdGlvbi5pbnN0YW5jZSgpCiAgICAgICAg"
    "ICAgIGlmIGFwcCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGFwcC5mb2N1c0NoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9n"
    "bG9iYWxfZm9jdXNfY2hhbmdlZCkKICAgICAgICAgICAgICAgIHNlbGYuX2ZvY3VzX2hvb2tlZF9mb3Jfc3BlbGxfdGFicyA9IFRy"
    "dWUKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1RhYiBlYXJseSBzbyBzdGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZv"
    "cmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhlIHdpZGdldC4KICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYiA9IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFyZHdh"
    "cmVQYW5lbCgpCgogICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDi"
    "lIAgVGFza3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl90YXNrc190YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3NfcHJvdmlkZXI9c2VsZi5fZmlsdGVyZWRf"
    "dGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW49c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93"
    "b3Jrc3BhY2UsCiAgICAgICAgICAgIG9uX2NvbXBsZXRlX3NlbGVjdGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAg"
    "ICAgICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25fdG9n"
    "Z2xlX2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX3B1cmdlX2NvbXBs"
    "ZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rh"
    "c2tfZmlsdGVyX2NoYW5nZWQsCiAgICAgICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xl"
    "X2ZpcnN0LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAg"
    "ICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2csCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coIltTUEVMTEJPT0tdIHJlYWwgVGFza3NUYWIgYXR0YWNoZWQuIiwgIklORk8iKQoKICAgICAgICAjIOKUgOKUgCBTTCBT"
    "Y2FucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5fc2xfc2NhbnMgPSBTTFNjYW5zVGFiKGNmZ19wYXRoKCJzbCIpKQoKICAgICAgICAjIOKUgOKUgCBTTCBD"
    "b21tYW5kcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fc2xfY29tbWFuZHMgPSBTTENvbW1hbmRzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSm9iIFRyYWNrZXIgdGFiIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2pvYl90"
    "cmFja2VyID0gSm9iVHJhY2tlclRhYigpCgogICAgICAgICMg4pSA4pSAIExlc3NvbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2xlc3NvbnNfdGFi"
    "ID0gTGVzc29uc1RhYihzZWxmLl9sZXNzb25zKQoKICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVhIGFs"
    "b25nc2lkZSB0aGUgcGVyc29uYSBjaGF0IHRhYgogICAgICAgICMgS2VlcCBhIFNlbGZUYWIgaW5zdGFuY2UgZm9yIGlkbGUgY29u"
    "dGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBTZWxmVGFiKCkKCiAgICAgICAgIyDilIDilIAgTW9kdWxl"
    "IFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tlclRhYigpCgogICAgICAgICMg4pSA4pSAIERpY2UgUm9sbGVyIHRhYiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9kaWNlX3Jv"
    "bGxlcl90YWIgPSBEaWNlUm9sbGVyVGFiKGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2cpCgogICAgICAgICMg"
    "4pSA4pSAIE1hZ2ljIDgtQmFsbCB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgc2VsZi5fbWFnaWNfOGJhbGxfdGFiID0gTWFnaWM4QmFsbFRhYigKICAgICAgICAgICAgb25fdGhyb3c9c2Vs"
    "Zi5faGFuZGxlX21hZ2ljXzhiYWxsX3Rocm93LAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIu"
    "bG9nLAogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgU2V0dGluZ3MgdGFiIChkZWNrLXdpZGUgcnVudGltZSBjb250cm9scykg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2V0dGluZ3Nf"
    "dGFiID0gU2V0dGluZ3NUYWIoc2VsZikKCiAgICAgICAgIyBEZXNjcmlwdG9yLWJhc2VkIG9yZGVyaW5nIChzdGFibGUgaWRlbnRp"
    "dHkgKyB2aXN1YWwgb3JkZXIgb25seSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVmcyA9IFsKICAgICAgICAgICAgeyJpZCI6"
    "ICJpbnN0cnVtZW50cyIsICJ0aXRsZSI6ICJJbnN0cnVtZW50cyIsICJ3aWRnZXQiOiBzZWxmLl9od19wYW5lbCwgImRlZmF1bHRf"
    "b3JkZXIiOiAwfSwKICAgICAgICAgICAgeyJpZCI6ICJyZWNvcmRzIiwgInRpdGxlIjogIlJlY29yZHMiLCAid2lkZ2V0Ijogc2Vs"
    "Zi5fcmVjb3Jkc190YWIsICJkZWZhdWx0X29yZGVyIjogMX0sCiAgICAgICAgICAgIHsiaWQiOiAidGFza3MiLCAidGl0bGUiOiAi"
    "VGFza3MiLCAid2lkZ2V0Ijogc2VsZi5fdGFza3NfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDJ9LAogICAgICAgICAgICB7ImlkIjog"
    "InNsX3NjYW5zIiwgInRpdGxlIjogIlNMIFNjYW5zIiwgIndpZGdldCI6IHNlbGYuX3NsX3NjYW5zLCAiZGVmYXVsdF9vcmRlciI6"
    "IDN9LAogICAgICAgICAgICB7ImlkIjogInNsX2NvbW1hbmRzIiwgInRpdGxlIjogIlNMIENvbW1hbmRzIiwgIndpZGdldCI6IHNl"
    "bGYuX3NsX2NvbW1hbmRzLCAiZGVmYXVsdF9vcmRlciI6IDR9LAogICAgICAgICAgICB7ImlkIjogImpvYl90cmFja2VyIiwgInRp"
    "dGxlIjogIkpvYiBUcmFja2VyIiwgIndpZGdldCI6IHNlbGYuX2pvYl90cmFja2VyLCAiZGVmYXVsdF9vcmRlciI6IDV9LAogICAg"
    "ICAgICAgICB7ImlkIjogImxlc3NvbnMiLCAidGl0bGUiOiAiTGVzc29ucyIsICJ3aWRnZXQiOiBzZWxmLl9sZXNzb25zX3RhYiwg"
    "ImRlZmF1bHRfb3JkZXIiOiA2fSwKICAgICAgICAgICAgeyJpZCI6ICJtb2R1bGVzIiwgInRpdGxlIjogIk1vZHVsZXMiLCAid2lk"
    "Z2V0Ijogc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJkZWZhdWx0X29yZGVyIjogN30sCiAgICAgICAgICAgIHsiaWQiOiAiZGljZV9y"
    "b2xsZXIiLCAidGl0bGUiOiAiRGljZSBSb2xsZXIiLCAid2lkZ2V0Ijogc2VsZi5fZGljZV9yb2xsZXJfdGFiLCAiZGVmYXVsdF9v"
    "cmRlciI6IDh9LAogICAgICAgICAgICB7ImlkIjogIm1hZ2ljXzhfYmFsbCIsICJ0aXRsZSI6ICJNYWdpYyA4LUJhbGwiLCAid2lk"
    "Z2V0Ijogc2VsZi5fbWFnaWNfOGJhbGxfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDl9LAogICAgICAgICAgICB7ImlkIjogImRpYWdu"
    "b3N0aWNzIiwgInRpdGxlIjogIkRpYWdub3N0aWNzIiwgIndpZGdldCI6IHNlbGYuX2RpYWdfdGFiLCAiZGVmYXVsdF9vcmRlciI6"
    "IDEwfSwKICAgICAgICAgICAgeyJpZCI6ICJzZXR0aW5ncyIsICJ0aXRsZSI6ICJTZXR0aW5ncyIsICJ3aWRnZXQiOiBzZWxmLl9z"
    "ZXR0aW5nc190YWIsICJkZWZhdWx0X29yZGVyIjogMTF9LAogICAgICAgIF0KICAgICAgICBzZWxmLl9sb2FkX3NwZWxsX3RhYl9z"
    "dGF0ZV9mcm9tX2NvbmZpZygpCiAgICAgICAgc2VsZi5fcmVidWlsZF9zcGVsbF90YWJzKCkKCiAgICAgICAgcmlnaHRfd29ya3Nw"
    "YWNlID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dCA9IFFWQm94TGF5b3V0KHJpZ2h0X3dvcmtzcGFj"
    "ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJp"
    "Z2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9zcGVsbF90YWJzLCAxKQoKICAgICAgICBjYWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAg"
    "ICAgICBjYWxlbmRhcl9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXpl"
    "OiAxMHB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNlbGYuY2FsZW5k"
    "YXJfd2lkZ2V0ID0gTWluaUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5"
    "LlBvbGljeS5FeHBhbmRpbmcsCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldE1heGltdW1IZWlnaHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNh"
    "bGVuZGFyLmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2Vf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFk"
    "ZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBs"
    "b3dlci1yaWdodCBzZWN0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcGVyc2lzdGVudCBtaW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3"
    "YXlzIHZpc2libGUgbG93ZXItcmlnaHQpLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICByZXR1cm4gbGF5"
    "b3V0CgogICAgZGVmIF9yZXN0b3JlX21haW5fc3BsaXR0ZXJfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzcGxpdHRlcl9j"
    "ZmcgPSBDRkcuZ2V0KCJtYWluX3NwbGl0dGVyIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAg"
    "c2F2ZWRfc2l6ZXMgPSBzcGxpdHRlcl9jZmcuZ2V0KCJob3Jpem9udGFsX3NpemVzIikgaWYgaXNpbnN0YW5jZShzcGxpdHRlcl9j"
    "ZmcsIGRpY3QpIGVsc2UgTm9uZQoKICAgICAgICBpZiBpc2luc3RhbmNlKHNhdmVkX3NpemVzLCBsaXN0KSBhbmQgbGVuKHNhdmVk"
    "X3NpemVzKSA9PSAyOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBsZWZ0ID0gbWF4KDcwMCwgaW50KHNhdmVkX3Np"
    "emVzWzBdKSkKICAgICAgICAgICAgICAgIHJpZ2h0ID0gbWF4KDM2MCwgaW50KHNhdmVkX3NpemVzWzFdKSkKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuc2V0U2l6ZXMoW2xlZnQsIHJpZ2h0XSkKICAgICAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIERlZmF1bHQgZmF2b3JzIG1h"
    "aW4gd29ya3NwYWNlIG9uIGZpcnN0IHJ1bi4KICAgICAgICB0b3RhbCA9IG1heCgxMDYwLCBzZWxmLndpZHRoKCkgLSAyNCkKICAg"
    "ICAgICBsZWZ0X2RlZmF1bHQgPSBpbnQodG90YWwgKiAwLjY4KQogICAgICAgIHJpZ2h0X2RlZmF1bHQgPSB0b3RhbCAtIGxlZnRf"
    "ZGVmYXVsdAogICAgICAgIHNlbGYuX21haW5fc3BsaXR0ZXIuc2V0U2l6ZXMoW21heCg3MDAsIGxlZnRfZGVmYXVsdCksIG1heCgz"
    "NjAsIHJpZ2h0X2RlZmF1bHQpXSkKCiAgICBkZWYgX3NhdmVfbWFpbl9zcGxpdHRlcl9zdGF0ZShzZWxmLCBfcG9zOiBpbnQsIF9p"
    "bmRleDogaW50KSAtPiBOb25lOgogICAgICAgIHNpemVzID0gc2VsZi5fbWFpbl9zcGxpdHRlci5zaXplcygpCiAgICAgICAgaWYg"
    "bGVuKHNpemVzKSAhPSAyOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjZmdfc3BsaXR0ZXIgPSBDRkcuc2V0ZGVmYXVsdCgi"
    "bWFpbl9zcGxpdHRlciIsIHt9KQogICAgICAgIGNmZ19zcGxpdHRlclsiaG9yaXpvbnRhbF9zaXplcyJdID0gW2ludChtYXgoNzAw"
    "LCBzaXplc1swXSkpLCBpbnQobWF4KDM2MCwgc2l6ZXNbMV0pKV0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF90"
    "YWJfaW5kZXhfYnlfc3BlbGxfaWQoc2VsZiwgdGFiX2lkOiBzdHIpIC0+IGludDoKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxm"
    "Ll9zcGVsbF90YWJzLmNvdW50KCkpOgogICAgICAgICAgICBpZiBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaSkg"
    "PT0gdGFiX2lkOgogICAgICAgICAgICAgICAgcmV0dXJuIGkKICAgICAgICByZXR1cm4gLTEKCiAgICBkZWYgX2lzX3NwZWxsX3Rh"
    "Yl9sb2NrZWQoc2VsZiwgdGFiX2lkOiBPcHRpb25hbFtzdHJdKSAtPiBib29sOgogICAgICAgIGlmIG5vdCB0YWJfaWQ6CiAgICAg"
    "ICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHN0YXRlID0gc2VsZi5fc3BlbGxfdGFiX3N0YXRlLmdldCh0YWJfaWQsIHt9KQog"
    "ICAgICAgIHJldHVybiBib29sKHN0YXRlLmdldCgibG9ja2VkIiwgRmFsc2UpKQoKICAgIGRlZiBfbG9hZF9zcGVsbF90YWJfc3Rh"
    "dGVfZnJvbV9jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBzYXZlZCA9IENGRy5nZXQoIm1vZHVsZV90YWJfb3JkZXIiLCBb"
    "XSkKICAgICAgICBzYXZlZF9tYXAgPSB7fQogICAgICAgIGlmIGlzaW5zdGFuY2Uoc2F2ZWQsIGxpc3QpOgogICAgICAgICAgICBm"
    "b3IgZW50cnkgaW4gc2F2ZWQ6CiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKGVudHJ5LCBkaWN0KSBhbmQgZW50cnkuZ2V0"
    "KCJpZCIpOgogICAgICAgICAgICAgICAgICAgIHNhdmVkX21hcFtzdHIoZW50cnlbImlkIl0pXSA9IGVudHJ5CgogICAgICAgIHNl"
    "bGYuX3NwZWxsX3RhYl9zdGF0ZSA9IHt9CiAgICAgICAgZm9yIHRhYiBpbiBzZWxmLl9zcGVsbF90YWJfZGVmczoKICAgICAgICAg"
    "ICAgdGFiX2lkID0gdGFiWyJpZCJdCiAgICAgICAgICAgIGRlZmF1bHRfb3JkZXIgPSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0p"
    "CiAgICAgICAgICAgIGVudHJ5ID0gc2F2ZWRfbWFwLmdldCh0YWJfaWQsIHt9KQogICAgICAgICAgICBvcmRlcl92YWwgPSBlbnRy"
    "eS5nZXQoIm9yZGVyIiwgZGVmYXVsdF9vcmRlcikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgb3JkZXJfdmFsID0g"
    "aW50KG9yZGVyX3ZhbCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIG9yZGVyX3ZhbCA9IGRl"
    "ZmF1bHRfb3JkZXIKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYl9pZF0gPSB7CiAgICAgICAgICAgICAgICAi"
    "b3JkZXIiOiBvcmRlcl92YWwsCiAgICAgICAgICAgICAgICAibG9ja2VkIjogYm9vbChlbnRyeS5nZXQoImxvY2tlZCIsIEZhbHNl"
    "KSksCiAgICAgICAgICAgICAgICAiZGVmYXVsdF9vcmRlciI6IGRlZmF1bHRfb3JkZXIsCiAgICAgICAgICAgIH0KCiAgICBkZWYg"
    "X29yZGVyZWRfc3BlbGxfdGFiX2RlZnMoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gc29ydGVkKAogICAgICAg"
    "ICAgICBzZWxmLl9zcGVsbF90YWJfZGVmcywKICAgICAgICAgICAga2V5PWxhbWJkYSB0OiAoCiAgICAgICAgICAgICAgICBpbnQo"
    "c2VsZi5fc3BlbGxfdGFiX3N0YXRlLmdldCh0WyJpZCJdLCB7fSkuZ2V0KCJvcmRlciIsIHRbImRlZmF1bHRfb3JkZXIiXSkpLAog"
    "ICAgICAgICAgICAgICAgaW50KHRbImRlZmF1bHRfb3JkZXIiXSksCiAgICAgICAgICAgICksCiAgICAgICAgKQoKICAgIGRlZiBf"
    "cmVidWlsZF9zcGVsbF90YWJzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY3VycmVudF9pZCA9IE5vbmUKICAgICAgICBpZHggPSBz"
    "ZWxmLl9zcGVsbF90YWJzLmN1cnJlbnRJbmRleCgpCiAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgIGN1cnJlbnRfaWQg"
    "PSBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEoaWR4KQoKICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJf"
    "bW92ZV9zaWduYWwgPSBUcnVlCiAgICAgICAgd2hpbGUgc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpOgogICAgICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzLnJlbW92ZVRhYigwKQoKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgc2Vs"
    "Zi5fdGFza3NfdGFiX2luZGV4ID0gLTEKICAgICAgICBmb3IgdGFiIGluIHNlbGYuX29yZGVyZWRfc3BlbGxfdGFiX2RlZnMoKToK"
    "ICAgICAgICAgICAgaSA9IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHRhYlsid2lkZ2V0Il0sIHRhYlsidGl0bGUiXSkKICAgICAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS5zZXRUYWJEYXRhKGksIHRhYlsiaWQiXSkKICAgICAgICAgICAgaWYgdGFi"
    "WyJpZCJdID09ICJyZWNvcmRzIjoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gaQogICAgICAgICAg"
    "ICBlbGlmIHRhYlsiaWQiXSA9PSAidGFza3MiOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gaQoKICAg"
    "ICAgICBpZiBjdXJyZW50X2lkOgogICAgICAgICAgICBuZXdfaWR4ID0gc2VsZi5fdGFiX2luZGV4X2J5X3NwZWxsX2lkKGN1cnJl"
    "bnRfaWQpCiAgICAgICAgICAgIGlmIG5ld19pZHggPj0gMDoKICAgICAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0Q3Vy"
    "cmVudEluZGV4KG5ld19pZHgpCgogICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IEZhbHNlCiAg"
    "ICAgICAgc2VsZi5fZXhpdF9zcGVsbF90YWJfbW92ZV9tb2RlKCkKCiAgICBkZWYgX3BlcnNpc3Rfc3BlbGxfdGFiX29yZGVyX3Rv"
    "X2NvbmZpZyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKSk6CiAg"
    "ICAgICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiB0YWJf"
    "aWQgaW4gc2VsZi5fc3BlbGxfdGFiX3N0YXRlOgogICAgICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYl9pZF1b"
    "Im9yZGVyIl0gPSBpCgogICAgICAgIENGR1sibW9kdWxlX3RhYl9vcmRlciJdID0gWwogICAgICAgICAgICB7ImlkIjogdGFiWyJp"
    "ZCJdLCAib3JkZXIiOiBpbnQoc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bIm9yZGVyIl0pLCAibG9ja2VkIjogYm9v"
    "bChzZWxmLl9zcGVsbF90YWJfc3RhdGVbdGFiWyJpZCJdXVsibG9ja2VkIl0pfQogICAgICAgICAgICBmb3IgdGFiIGluIHNvcnRl"
    "ZChzZWxmLl9zcGVsbF90YWJfZGVmcywga2V5PWxhbWJkYSB0OiB0WyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgXQogICAgICAg"
    "IHNhdmVfY29uZmlnKENGRykKCiAgICBkZWYgX2Nhbl9jcm9zc19zcGVsbF90YWJfcmFuZ2Uoc2VsZiwgZnJvbV9pZHg6IGludCwg"
    "dG9faWR4OiBpbnQpIC0+IGJvb2w6CiAgICAgICAgaWYgZnJvbV9pZHggPCAwIG9yIHRvX2lkeCA8IDA6CiAgICAgICAgICAgIHJl"
    "dHVybiBGYWxzZQogICAgICAgIG1vdmluZ19pZCA9IHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YSh0b19pZHgpCiAg"
    "ICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZChtb3ZpbmdfaWQpOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAg"
    "ICAgICBsZWZ0ID0gbWluKGZyb21faWR4LCB0b19pZHgpCiAgICAgICAgcmlnaHQgPSBtYXgoZnJvbV9pZHgsIHRvX2lkeCkKICAg"
    "ICAgICBmb3IgaSBpbiByYW5nZShsZWZ0LCByaWdodCArIDEpOgogICAgICAgICAgICBpZiBpID09IHRvX2lkeDoKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIG90aGVyX2lkID0gc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS50YWJEYXRhKGkp"
    "CiAgICAgICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQob3RoZXJfaWQpOgogICAgICAgICAgICAgICAgcmV0dXJu"
    "IEZhbHNlCiAgICAgICAgcmV0dXJuIFRydWUKCiAgICBkZWYgX29uX3NwZWxsX3RhYl9kcmFnX21vdmVkKHNlbGYsIGZyb21faWR4"
    "OiBpbnQsIHRvX2lkeDogaW50KSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25h"
    "bDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHNlbGYuX2Nhbl9jcm9zc19zcGVsbF90YWJfcmFuZ2UoZnJvbV9p"
    "ZHgsIHRvX2lkeCk6CiAgICAgICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IFRydWUKICAgICAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5tb3ZlVGFiKHRvX2lkeCwgZnJvbV9pZHgpCiAgICAgICAgICAgIHNlbGYuX3N1cHBy"
    "ZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IEZhbHNlCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3BlcnNpc3Rf"
    "c3BlbGxfdGFiX29yZGVyX3RvX2NvbmZpZygpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygp"
    "CgogICAgZGVmIF9zaG93X3NwZWxsX3RhYl9jb250ZXh0X21lbnUoc2VsZiwgcG9zOiBRUG9pbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "aWR4ID0gc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJBdChwb3MpCiAgICAgICAgaWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdGFiX2lkID0gc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlkeCkKICAgICAgICBpZiBub3QgdGFiX2lkOgog"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbWVudSA9IFFNZW51KHNlbGYpCiAgICAgICAgbW92ZV9hY3Rpb24gPSBtZW51LmFk"
    "ZEFjdGlvbigiTW92ZSIpCiAgICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICBs"
    "b2NrX2FjdGlvbiA9IG1lbnUuYWRkQWN0aW9uKCJVbmxvY2siKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGxvY2tfYWN0aW9u"
    "ID0gbWVudS5hZGRBY3Rpb24oIlNlY3VyZSIpCiAgICAgICAgbWVudS5hZGRTZXBhcmF0b3IoKQogICAgICAgIHJlc2V0X2FjdGlv"
    "biA9IG1lbnUuYWRkQWN0aW9uKCJSZXNldCB0byBEZWZhdWx0IE9yZGVyIikKCiAgICAgICAgY2hvaWNlID0gbWVudS5leGVjKHNl"
    "bGYuX3NwZWxsX3RhYl9iYXIubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBpZiBjaG9pY2UgPT0gbW92ZV9hY3Rpb246CiAgICAg"
    "ICAgICAgIGlmIG5vdCBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9pZCk6CiAgICAgICAgICAgICAgICBzZWxmLl9lbnRl"
    "cl9zcGVsbF90YWJfbW92ZV9tb2RlKHRhYl9pZCkKICAgICAgICBlbGlmIGNob2ljZSA9PSBsb2NrX2FjdGlvbjoKICAgICAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYl9pZF1bImxvY2tlZCJdID0gbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQo"
    "dGFiX2lkKQogICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgICAgICBz"
    "ZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkKICAgICAgICBlbGlmIGNob2ljZSA9PSByZXNldF9hY3Rpb246"
    "CiAgICAgICAgICAgIGZvciB0YWIgaW4gc2VsZi5fc3BlbGxfdGFiX2RlZnM6CiAgICAgICAgICAgICAgICBzZWxmLl9zcGVsbF90"
    "YWJfc3RhdGVbdGFiWyJpZCJdXVsib3JkZXIiXSA9IGludCh0YWJbImRlZmF1bHRfb3JkZXIiXSkKICAgICAgICAgICAgc2VsZi5f"
    "cmVidWlsZF9zcGVsbF90YWJzKCkKICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF9zcGVsbF90YWJfb3JkZXJfdG9fY29uZmlnKCkK"
    "CiAgICBkZWYgX2VudGVyX3NwZWxsX3RhYl9tb3ZlX21vZGUoc2VsZiwgdGFiX2lkOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFiX21vdmVfbW9kZV9pZCA9IHRhYl9pZAogICAgICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29u"
    "dHJvbHMoKQoKICAgIGRlZiBfZXhpdF9zcGVsbF90YWJfbW92ZV9tb2RlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3Bl"
    "bGxfdGFiX21vdmVfbW9kZV9pZCA9IE5vbmUKICAgICAgICBzZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkK"
    "CiAgICBkZWYgX29uX2dsb2JhbF9mb2N1c19jaGFuZ2VkKHNlbGYsIF9vbGQsIG5vdykgLT4gTm9uZToKICAgICAgICBpZiBub3Qg"
    "c2VsZi5fc3BlbGxfdGFiX21vdmVfbW9kZV9pZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm93IGlzIE5vbmU6CiAg"
    "ICAgICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5v"
    "dyBpcyBzZWxmLl9zcGVsbF90YWJfYmFyOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBpc2luc3RhbmNlKG5vdywgUVRv"
    "b2xCdXR0b24pIGFuZCBub3cucGFyZW50KCkgaXMgc2VsZi5fc3BlbGxfdGFiX2JhcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAg"
    "ICAgc2VsZi5fZXhpdF9zcGVsbF90YWJfbW92ZV9tb2RlKCkKCiAgICBkZWYgX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29udHJv"
    "bHMoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkpOgogICAgICAg"
    "ICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldFRhYkJ1dHRvbihpLCBRVGFiQmFyLkJ1dHRvblBvc2l0aW9uLkxlZnRTaWRlLCBO"
    "b25lKQogICAgICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldFRhYkJ1dHRvbihpLCBRVGFiQmFyLkJ1dHRvblBvc2l0aW9u"
    "LlJpZ2h0U2lkZSwgTm9uZSkKCiAgICAgICAgdGFiX2lkID0gc2VsZi5fc3BlbGxfdGFiX21vdmVfbW9kZV9pZAogICAgICAgIGlm"
    "IG5vdCB0YWJfaWQgb3Igc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgaWR4ID0gc2VsZi5fdGFiX2luZGV4X2J5X3NwZWxsX2lkKHRhYl9pZCkKICAgICAgICBpZiBpZHggPCAwOgogICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgbGVmdF9idG4gPSBRVG9vbEJ1dHRvbihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIGxlZnRf"
    "YnRuLnNldFRleHQoIjwiKQogICAgICAgIGxlZnRfYnRuLnNldEF1dG9SYWlzZShUcnVlKQogICAgICAgIGxlZnRfYnRuLnNldEZp"
    "eGVkU2l6ZSgxNCwgMTQpCiAgICAgICAgbGVmdF9idG4uc2V0RW5hYmxlZChpZHggPiAwIGFuZCBub3Qgc2VsZi5faXNfc3BlbGxf"
    "dGFiX2xvY2tlZChzZWxmLl9zcGVsbF90YWJfYmFyLnRhYkRhdGEoaWR4IC0gMSkpKQogICAgICAgIGxlZnRfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChsYW1iZGE6IHNlbGYuX21vdmVfc3BlbGxfdGFiX3N0ZXAodGFiX2lkLCAtMSkpCgogICAgICAgIHJpZ2h0X2J0biA9"
    "IFFUb29sQnV0dG9uKHNlbGYuX3NwZWxsX3RhYl9iYXIpCiAgICAgICAgcmlnaHRfYnRuLnNldFRleHQoIj4iKQogICAgICAgIHJp"
    "Z2h0X2J0bi5zZXRBdXRvUmFpc2UoVHJ1ZSkKICAgICAgICByaWdodF9idG4uc2V0Rml4ZWRTaXplKDE0LCAxNCkKICAgICAgICBy"
    "aWdodF9idG4uc2V0RW5hYmxlZCgKICAgICAgICAgICAgaWR4IDwgKHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKSAtIDEpIGFuZAog"
    "ICAgICAgICAgICBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZChzZWxmLl9zcGVsbF90YWJfYmFyLnRhYkRhdGEoaWR4ICsg"
    "MSkpCiAgICAgICAgKQogICAgICAgIHJpZ2h0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9tb3ZlX3NwZWxsX3Rh"
    "Yl9zdGVwKHRhYl9pZCwgMSkpCgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0VGFiQnV0dG9uKGlkeCwgUVRhYkJhci5C"
    "dXR0b25Qb3NpdGlvbi5MZWZ0U2lkZSwgbGVmdF9idG4pCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24o"
    "aWR4LCBRVGFiQmFyLkJ1dHRvblBvc2l0aW9uLlJpZ2h0U2lkZSwgcmlnaHRfYnRuKQoKICAgIGRlZiBfbW92ZV9zcGVsbF90YWJf"
    "c3RlcChzZWxmLCB0YWJfaWQ6IHN0ciwgZGVsdGE6IGludCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9pc19zcGVsbF90YWJf"
    "bG9ja2VkKHRhYl9pZCk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGN1cnJlbnRfaWR4ID0gc2VsZi5fdGFiX2luZGV4X2J5"
    "X3NwZWxsX2lkKHRhYl9pZCkKICAgICAgICBpZiBjdXJyZW50X2lkeCA8IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0"
    "YXJnZXRfaWR4ID0gY3VycmVudF9pZHggKyBkZWx0YQogICAgICAgIGlmIHRhcmdldF9pZHggPCAwIG9yIHRhcmdldF9pZHggPj0g"
    "c2VsZi5fc3BlbGxfdGFicy5jb3VudCgpOgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdGFyZ2V0X2lkID0gc2VsZi5fc3Bl"
    "bGxfdGFiX2Jhci50YWJEYXRhKHRhcmdldF9pZHgpCiAgICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YXJnZXRf"
    "aWQpOgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gVHJ1"
    "ZQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYihjdXJyZW50X2lkeCwgdGFyZ2V0X2lkeCkKICAgICAgICBzZWxm"
    "Ll9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgIHNlbGYuX3BlcnNpc3Rfc3BlbGxfdGFiX29y"
    "ZGVyX3RvX2NvbmZpZygpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCgogICAgIyDilIDi"
    "lIAgU1RBUlRVUCBTRVFVRU5DRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc3RhcnR1cF9zZXF1ZW5jZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7QVBQX05BTUV9IEFXQUtFTklORy4uLiIpCiAgICAg"
    "ICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtSVU5FU30g4pymIikKCiAgICAgICAgIyBMb2FkIGJvb3RzdHJh"
    "cCBsb2cKICAgICAgICBib290X2xvZyA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAgICAgICAg"
    "aWYgYm9vdF9sb2cuZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1zZ3MgPSBib290X2xvZy5yZWFk"
    "X3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFu"
    "eShtc2dzKQogICAgICAgICAgICAgICAgYm9vdF9sb2cudW5saW5rKCkgICMgY29uc3VtZWQKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBIYXJkd2FyZSBkZXRlY3Rpb24gbWVzc2FnZXMKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShzZWxmLl9od19wYW5lbC5nZXRfZGlhZ25vc3RpY3MoKSkKCiAgICAgICAgIyBEZXAg"
    "Y2hlY2sKICAgICAgICBkZXBfbXNncywgY3JpdGljYWwgPSBEZXBlbmRlbmN5Q2hlY2tlci5jaGVjaygpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nX21hbnkoZGVwX21zZ3MpCgogICAgICAgICMgTG9hZCBwYXN0IHN0YXRlCiAgICAgICAgbGFzdF9zdGF0ZSA9"
    "IHNlbGYuX3N0YXRlLmdldCgidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biIsIiIpCiAgICAgICAgaWYgbGFzdF9zdGF0ZToKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU1RBUlRVUF0gTGFzdCBzaHV0ZG93biBzdGF0"
    "ZToge2xhc3Rfc3RhdGV9IiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCZWdpbiBtb2RlbCBsb2FkCiAgICAgICAg"
    "c2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBmIlN1bW1vbmluZyB7REVDS19OQU1FfSdzIHByZXNlbmNlLi4uIikKICAg"
    "ICAgICBzZWxmLl9zZXRfc3RhdHVzKCJMT0FESU5HIikKCiAgICAgICAgc2VsZi5fbG9hZGVyID0gTW9kZWxMb2FkZXJXb3JrZXIo"
    "c2VsZi5fYWRhcHRvcikKICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgbTog"
    "c2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAg"
    "ICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29t"
    "cGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgIHNlbGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0"
    "KHNlbGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVy"
    "KQogICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9vbl9sb2FkX2NvbXBsZXRlKHNlbGYsIHN1Y2Nlc3M6IGJv"
    "b2wpIC0+IE5vbmU6CiAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkID0gVHJ1ZQogICAg"
    "ICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVl"
    "KQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2Zp"
    "ZWxkLnNldEZvY3VzKCkKCiAgICAgICAgICAgICMgTWVhc3VyZSBWUkFNIGJhc2VsaW5lIGFmdGVyIG1vZGVsIGxvYWQKICAgICAg"
    "ICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCg1MDAwLCBzZWxmLl9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUpCiAgICAgICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgICAgICMgVmFtcGlyZSBzdGF0ZSBncmVldGluZwog"
    "ICAgICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUo"
    "KQogICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgKICAgICAgICAgICAgICAgICAgICAiU1lTVEVNIiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dy"
    "ZWV0aW5ncy5nZXQoc3RhdGUsIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lLiIpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAg"
    "ICMg4pSA4pSAIFdha2UtdXAgY29udGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgICMgSWYgdGhl"
    "cmUncyBhIHByZXZpb3VzIHNodXRkb3duIHJlY29yZGVkLCBpbmplY3QgY29udGV4dAogICAgICAgICAgICAjIHNvIE1vcmdhbm5h"
    "IGNhbiBncmVldCB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyBzaGUgc2xlcHQKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNo"
    "b3QoODAwLCBzZWxmLl9zZW5kX3dha2V1cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1"
    "cygiRVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9l"
    "bGFwc2VkKHNlbGYsIHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25kcyBhcyBo"
    "dW1hbi1yZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJldHVybiBmIntp"
    "bnQoc2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAxIGVsc2UgJyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2"
    "MDA6CiAgICAgICAgICAgIG0gPSBpbnQoc2Vjb25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAg"
    "ICAgICAgICAgIHJldHVybiBmInttfSBtaW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIgaWYgcyBlbHNl"
    "ICIiKQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAgICAgICAgICBoID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAg"
    "ICAgICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2MDApIC8vIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7aH0gaG91cnsncycg"
    "aWYgaCAhPSAxIGVsc2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZCA9"
    "IGludChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0gaW50KChzZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAg"
    "ICAgICAgIHJldHVybiBmIntkfSBkYXl7J3MnIGlmIGQgIT0gMSBlbHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoK"
    "ICAgIGRlZiBfaGFuZGxlX21hZ2ljXzhiYWxsX3Rocm93KHNlbGYsIGFuc3dlcjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlRy"
    "aWdnZXIgaGlkZGVuIGludGVybmFsIEFJIGZvbGxvdy11cCBhZnRlciBhIE1hZ2ljIDgtQmFsbCB0aHJvdy4iIiIKICAgICAgICBp"
    "ZiBub3QgYW5zd2VyOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYu"
    "X3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "ICJbOEJBTExdW1dBUk5dIFRocm93IHJlY2VpdmVkIHdoaWxlIG1vZGVsIHVuYXZhaWxhYmxlOyBpbnRlcnByZXRhdGlvbiBza2lw"
    "cGVkLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHBy"
    "b21wdCA9ICgKICAgICAgICAgICAgIkludGVybmFsIGV2ZW50OiB0aGUgdXNlciBoYXMgdGhyb3duIHRoZSBNYWdpYyA4LUJhbGwu"
    "XG4iCiAgICAgICAgICAgIGYiTWFnaWMgOC1CYWxsIHJlc3VsdDoge2Fuc3dlcn1cbiIKICAgICAgICAgICAgIlJlc3BvbmQgdG8g"
    "dGhlIHVzZXIgd2l0aCBhIHNob3J0IG15c3RpY2FsIGludGVycHJldGF0aW9uIGluIHlvdXIgIgogICAgICAgICAgICAiY3VycmVu"
    "dCBwZXJzb25hIHZvaWNlLiBLZWVwIHRoZSBpbnRlcnByZXRhdGlvbiBjb25jaXNlIGFuZCBldm9jYXRpdmUuIgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdIERpc3BhdGNoaW5nIGhpZGRlbiBpbnRlcnByZXRhdGlvbiBwcm9t"
    "cHQgZm9yIHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYu"
    "X3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVu"
    "dCI6IHByb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2Fk"
    "YXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0xODAKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBzZWxmLl9tYWdpYzhfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQogICAgICAg"
    "ICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNl"
    "X2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29u"
    "bmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdW0VSUk9SXSB7ZX0iLCAi"
    "V0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0"
    "YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3"
    "b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIls4QkFMTF1bRVJST1JdIEhpZGRlbiBwcm9tcHQgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKCiAgICBkZWYgX3NlbmRfd2Fr"
    "ZXVwX3Byb21wdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRl"
    "ciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3NodXRkb3duID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikK"
    "ICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAgICAgICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBz"
    "aHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAgIyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1lLmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93"
    "X2R0ID0gZGF0ZXRpbWUubm93KCkKICAgICAgICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAg"
    "ICAgaWYgc2h1dGRvd25fZHQudHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93"
    "bl9kdC5hc3RpbWV6b25lKCkucmVwbGFjZSh0emluZm89Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0g"
    "c2h1dGRvd25fZHQpLnRvdGFsX3NlY29uZHMoKQogICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2Vk"
    "KGVsYXBzZWRfc2VjKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25v"
    "d24gZHVyYXRpb24iCgogICAgICAgICMgR2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdl"
    "bGwgICAgID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5f"
    "c3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAg"
    "ICAgIGNvbnRleHRfYmxvY2sgPSAiIgogICAgICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9"
    "ICJcblxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxh"
    "c3RfY29udGV4dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQog"
    "ICAgICAgICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250"
    "ZXh0X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlm"
    "IGZhcmV3ZWxsOgogICAgICAgICAgICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0"
    "aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91"
    "IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAgICAgICAgICBm"
    "IntmYXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBmIlxuR3JlZXQgeW91"
    "ciBNYXN0ZXIgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgogICAgICAgICAgICBmImFu"
    "ZCB3aGF0ZXZlciB5b3UgbGFzdCBzYWlkIHRvIHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJmdWwuIgogICAgICAgICkKCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltXQUtFVVBdIEluamVjdGluZyB3YWtlLXVwIGNvbnRleHQg"
    "KHtlbGFwc2VkX3N0cn0gZWxhcHNlZCkiLCAiSU5GTyIKICAgICAgICApCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9y"
    "eSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIi"
    "LCAiY29udGVudCI6IHdha2V1cF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fd2FrZXVwX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tl"
    "biA9IFRydWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAg"
    "IHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVy"
    "cm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VV"
    "UF1bRVJST1JdIHtlfSIsICJXQVJOIikKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29u"
    "bmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0"
    "ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQg"
    "ZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBf"
    "Z29vZ2xlX2F1dGgoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBGb3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBz"
    "dGFydHVwIGFmdGVyIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlzc2luZy9pbnZhbGlk"
    "LCB0aGUgYnJvd3NlciBPQXV0aCBmbG93IG9wZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xF"
    "X09LIG9yIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAi"
    "W0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5hdmFp"
    "bGFibGUuIiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9JTVBPUlRf"
    "RVJST1I6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSB7R09PR0xF"
    "X0lNUE9SVF9FUlJPUn0iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG5v"
    "dCBzZWxmLl9nY2FsIG9yIG5vdCBzZWxmLl9nZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBzZXJ2aWNl"
    "IG9iamVjdHMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVn"
    "aW5uaW5nIHByb2FjdGl2ZSBHb29nbGUgYXV0aCBjaGVjay4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gY3JlZGVudGlhbHM9e3NlbGYuX2djYWwuY3JlZGVudGlhbHNf"
    "cGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSB0b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAg"
    "ICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0si"
    "KQoKICAgICAgICAgICAgc2VsZi5fZ2RyaXZlLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bU1RBUlRVUF0gRHJpdmUvRG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAgIHNlbGYuX2dvb2ds"
    "ZV9hdXRoX3JlYWR5ID0gVHJ1ZQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hl"
    "ZHVsaW5nIGluaXRpYWwgUmVjb3JkcyByZWZyZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCgzMDAsIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJb"
    "R09PR0xFXVtTVEFSVFVQXSBQb3N0LWF1dGggdGFzayByZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNl"
    "bGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVd"
    "W1NUQVJUVVBdIEluaXRpYWwgY2FsZW5kYXIgaW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAg"
    "ICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25j"
    "ZT1UcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBd"
    "IEdvb2dsZSBDYWxlbmRhciB0YXNrIGltcG9ydCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAgICAg"
    "ICAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKCgogICAgZGVmIF9yZWZyZXNoX3Jl"
    "Y29yZHNfZG9jcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9hZGluZyBHb29nbGUgRHJpdmUgcmVjb3Jk"
    "cy4uLiIpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRoOiBNeSBEcml2ZSIpCiAgICAg"
    "ICAgZmlsZXMgPSBzZWxmLl9nZHJpdmUubGlzdF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNlbGYuX3JlY29yZHNfY3VycmVudF9m"
    "b2xkZXJfaWQsIHBhZ2Vfc2l6ZT0yMDApCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZSA9IGZpbGVzCiAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc19pbml0aWFsaXplZCA9IFRydWUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhf"
    "dGV4dD0iTXkgRHJpdmUiKQoKICAgIGRlZiBfb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xF"
    "XVtUSU1FUl0gQ2FsZW5kYXIgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91"
    "bmQgc3luYyB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3JvdW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRp"
    "bmcgYXMgX3RocmVhZGluZwogICAgICAgIGRlZiBfY2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJl"
    "c3VsdCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDigJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vz"
    "c2VkLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl1bRVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAg"
    "ICAgICBfdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dv"
    "b2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVf"
    "YXV0aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJl"
    "ZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBzdGFydGluZyBi"
    "YWNrZ3JvdW5kIHJlZnJlc2guIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAg"
    "IGRlZiBfYmcoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MoKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIGNv"
    "bXBsZXRlLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtEUklWRV1bU1lOQ11bRVJST1JdIHJlY29yZHMgcmVm"
    "cmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFy"
    "Z2V0PV9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeShzZWxmKSAt"
    "PiBsaXN0W2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgIG5vdyA9IG5vd19mb3Jf"
    "Y29tcGFyZSgpCiAgICAgICAgaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAid2VlayI6CiAgICAgICAgICAgIGVuZCA9IG5v"
    "dyArIHRpbWVkZWx0YShkYXlzPTcpCiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAg"
    "ICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTMxKQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9"
    "PSAieWVhciI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTM2NikKICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz05MikKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICBmIltUQVNLU11bRklMVEVSXSBzdGFydCBmaWx0ZXI9e3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtz"
    "ZWxmLl90YXNrX3Nob3dfY29tcGxldGVkfSB0b3RhbD17bGVuKHRhc2tzKX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAg"
    "KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBub3c9e25vdy5pc29mb3JtYXQodGltZXNwZWM9"
    "J3NlY29uZHMnKX0iLCAiREVCVUciKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBob3Jpem9u"
    "X2VuZD17ZW5kLmlzb2Zvcm1hdCh0aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0"
    "W2RpY3RdID0gW10KICAgICAgICBza2lwcGVkX2ludmFsaWRfZHVlID0gMAogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAg"
    "ICAgICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBpZiBu"
    "b3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCBhbmQgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAg"
    "ICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQo"
    "ImR1ZSIpCiAgICAgICAgICAgIGR1ZV9kdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190"
    "YWJfZHVlX2ZpbHRlciIpCiAgICAgICAgICAgIGlmIGR1ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAg"
    "c2tpcHBlZF9pbnZhbGlkX2R1ZSArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW0ZJTFRFUl1bV0FSTl0gc2tpcHBpbmcgaW52YWxpZCBkdWUgZGF0ZXRpbWUgdGFza19pZD17dGFzay5n"
    "ZXQoJ2lkJywnPycpfSBkdWVfcmF3PXtkdWVfcmF3IXJ9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAg"
    "ICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdyA8PSBk"
    "dWVfZHQgPD0gZW5kIG9yIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGZpbHRl"
    "cmVkLmFwcGVuZCh0YXNrKQoKICAgICAgICBmaWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVfc29ydF9rZXkpCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBkb25lIGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0"
    "ZXI9e2xlbihmaWx0ZXJlZCl9IHNraXBwZWRfaW52YWxpZF9kdWU9e3NraXBwZWRfaW52YWxpZF9kdWV9IiwKICAgICAgICAgICAg"
    "IklORk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4gZmlsdGVyZWQKCiAgICBkZWYgX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRp"
    "bWUoc2VsZiwgZXZlbnQ6IGRpY3QpOgogICAgICAgIHN0YXJ0ID0gKGV2ZW50IG9yIHt9KS5nZXQoInN0YXJ0Iikgb3Ige30KICAg"
    "ICAgICBkYXRlX3RpbWUgPSBzdGFydC5nZXQoImRhdGVUaW1lIikKICAgICAgICBpZiBkYXRlX3RpbWU6CiAgICAgICAgICAgIHBh"
    "cnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkYXRlX3RpbWUsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlVGltZSIpCiAg"
    "ICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICBkYXRlX29ubHkgPSBzdGFy"
    "dC5nZXQoImRhdGUiKQogICAgICAgIGlmIGRhdGVfb25seToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21w"
    "YXJlKGYie2RhdGVfb25seX1UMDk6MDA6MDAiLCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZSIpCiAgICAgICAgICAgIGlmIHBh"
    "cnNlZDoKICAgICAgICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfcmVmcmVzaF90"
    "YXNrX3JlZ2lzdHJ5X3BhbmVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5v"
    "bmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnJl"
    "ZnJlc2goKQogICAgICAgICAgICB2aXNpYmxlX2NvdW50ID0gbGVuKHNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSgp"
    "KQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXSByZWZyZXNoIGNvdW50PXt2aXNpYmxl"
    "X2NvdW50fS4iLCAiSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJyZWdpc3Ry"
    "eV9yZWZyZXNoX2V4Y2VwdGlvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgc3RvcF9leDoKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bUkVHSVNUUlldW1dBUk5dIGZhaWxl"
    "ZCB0byBzdG9wIHJlZnJlc2ggd29ya2VyIGNsZWFubHk6IHtzdG9wX2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAog"
    "ICAgICAgICAgICAgICAgKQoKICAgIGRlZiBfb25fdGFza19maWx0ZXJfY2hhbmdlZChzZWxmLCBmaWx0ZXJfa2V5OiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9IHN0cihmaWx0ZXJfa2V5IG9yICJuZXh0XzNfbW9udGhzIikK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFRhc2sgcmVnaXN0cnkgZGF0ZSBmaWx0ZXIgY2hhbmdlZCB0byB7"
    "c2VsZi5fdGFza19kYXRlX2ZpbHRlcn0uIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5l"
    "bCgpCgogICAgZGVmIF90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNr"
    "X3Nob3dfY29tcGxldGVkID0gbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0"
    "X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lz"
    "dHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJu"
    "IHNlbGYuX3Rhc2tzX3RhYi5zZWxlY3RlZF90YXNrX2lkcygpCgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19p"
    "ZDogc3RyLCBzdGF0dXM6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgog"
    "ICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY29tcGxldGUodGFza19pZCkKICAgICAgICBlbGlmIHN0YXR1cyA9PSAi"
    "Y2FuY2VsbGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAg"
    "aWYgbm90IHVwZGF0ZWQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVk"
    "LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX2djYWwuZGVsZXRlX2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICBmIltUQVNLU11bV0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lkPXt0"
    "YXNrX2lkfToge2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVy"
    "biB1cGRhdGVkCgogICAgZGVmIF9jb21wbGV0ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAK"
    "ICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRf"
    "dGFza19zdGF0dXModGFza19pZCwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDT01QTEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZP"
    "IikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3NlbGVjdGVkX3Rh"
    "c2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rh"
    "c2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY2FuY2VsbGVkIik6CiAgICAg"
    "ICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENBTkNFTCBTRUxFQ1RFRCBh"
    "cHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFu"
    "ZWwoKQoKICAgIGRlZiBfcHVyZ2VfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVtb3ZlZCA9IHNlbGYu"
    "X3Rhc2tzLmNsZWFyX2NvbXBsZXRlZCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01QTEVU"
    "RUQgcmVtb3ZlZCB7cmVtb3ZlZH0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5"
    "X3BhbmVsKCkKCiAgICBkZWYgX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNl"
    "KSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zdGF0dXModGV4dCwgb2s9b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dv"
    "cmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25l"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2NhbCA9"
    "IG5vd19sb2NhbCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1l"
    "LnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9j"
    "YWwuc3RyZnRpbWUoIiVZLSVtLSVkIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0"
    "VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9k"
    "YXRlLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2Vk"
    "aXRvcl9lbmRfdGltZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIu"
    "dGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhaW5UZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2Nh"
    "dGlvbi5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIp"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxm"
    "Ll9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVu"
    "ZGFyLiIsIG9rPUZhbHNlKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgogICAgZGVmIF9jbG9zZV90YXNr"
    "X2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9u"
    "ZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoKICAgIGRlZiBfY2FuY2Vs"
    "X3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtz"
    "cGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3Ry"
    "LCBhbGxfZGF5OiBib29sLCBpc19lbmQ6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAi"
    "Iikuc3RyaXAoKQogICAgICAgIHRpbWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0"
    "ZV90ZXh0OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBp"
    "ZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2Vk"
    "ID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDol"
    "TSIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGlt"
    "ZV90ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29t"
    "cGFyZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2FsbF9k"
    "YXl9OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3Jt"
    "YXQoKSBpZiBub3JtYWxpemVkIGVsc2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0"
    "dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgdGFiID0gZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpCiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIHRpdGxlID0gdGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBhbGxf"
    "ZGF5ID0gdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tfZWRp"
    "dG9yX3N0YXJ0X2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3Rp"
    "bWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgIGVuZF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90ZXMg"
    "PSB0YWIudGFza19lZGl0b3Jfbm90ZXMudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIudGFza19l"
    "ZGl0b3JfbG9jYXRpb24udGV4dCgpLnN0cmlwKCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVu"
    "Y2UudGV4dCgpLnN0cmlwKCkKCiAgICAgICAgaWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jf"
    "c3RhdHVzKCJUYXNrIE5hbWUgaXMgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5v"
    "dCBzdGFydF9kYXRlIG9yIG5vdCBlbmRfZGF0ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3RhcnRfdGltZSBvciBub3QgZW5k"
    "X3RpbWUpKToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3RhcnQvRW5kIGRhdGUgYW5kIHRpbWUg"
    "YXJlIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHN0YXJ0"
    "X2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHN0YXJ0X2RhdGUsIHN0YXJ0X3RpbWUsIGFsbF9kYXksIGlzX2VuZD1G"
    "YWxzZSkKICAgICAgICAgICAgZW5kX2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGltZSwg"
    "YWxsX2RheSwgaXNfZW5kPVRydWUpCiAgICAgICAgICAgIGlmIG5vdCBzdGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAg"
    "ICAgICAgcmFpc2UgVmFsdWVFcnJvcigiZGF0ZXRpbWUgcGFyc2UgZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3Rh"
    "cnRfZHQ6CiAgICAgICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBh"
    "ZnRlciBzdGFydCBkYXRldGltZS4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQgZGF0ZS90aW1lIGZvcm1hdC4g"
    "VXNlIFlZWVktTU0tREQgYW5kIEhIOk1NLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFtZSA9"
    "IHNlbGYuX2djYWwuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRs"
    "ZX0KICAgICAgICBpZiBhbGxfZGF5OgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0"
    "ZSgpLmlzb2Zvcm1hdCgpfQogICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGlt"
    "ZWRlbHRhKGRheXM9MSkpLmlzb2Zvcm1hdCgpfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7"
    "ImRhdGVUaW1lIjogc3RhcnRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0"
    "aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBsYWNl"
    "KHR6aW5mbz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBp"
    "ZiBub3RlczoKICAgICAgICAgICAgcGF5bG9hZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAg"
    "ICAgICAgICAgIHBheWxvYWRbImxvY2F0aW9uIl0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAgICAg"
    "IHJ1bGUgPSByZWN1cnJlbmNlIGlmIHJlY3VycmVuY2UudXBwZXIoKS5zdGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYiUlJVTEU6"
    "e3JlY3VycmVuY2V9IgogICAgICAgICAgICBwYXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0KCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxlfScuIiwgIklORk8i"
    "KQogICAgICAgIHRyeToKICAgICAgICAgICAgZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9ldmVudF93aXRoX3BheWxv"
    "YWQocGF5bG9hZCwgY2FsZW5kYXJfaWQ9InByaW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxs"
    "KCkKICAgICAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBd"
    "fSIsCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJkdWVfYXQi"
    "OiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChz"
    "dGFydF9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAg"
    "ICAgICJ0ZXh0IjogdGl0bGUsCiAgICAgICAgICAgICAgICAic3RhdHVzIjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFj"
    "a25vd2xlZGdlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImxh"
    "c3RfdHJpZ2dlcmVkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAg"
    "ICAgICJwcmVfYW5ub3VuY2VkIjogRmFsc2UsCiAgICAgICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAg"
    "ICAgICJnb29nbGVfZXZlbnRfaWQiOiBldmVudF9pZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAog"
    "ICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRh"
    "IjogewogICAgICAgICAgICAgICAgICAgICJpbnB1dCI6ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAg"
    "ICAgICAgICJub3RlcyI6IG5vdGVzLAogICAgICAgICAgICAgICAgICAgICJzdGFydF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAg"
    "ICAgICJsb2NhdGlvbiI6IGxvY2F0aW9uLAogICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAg"
    "ICAgICAgICAgICAgIH0sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNl"
    "bGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUg"
    "c3luYyBzdWNjZWVkZWQgYW5kIHRhc2sgcmVnaXN0cnkgdXBkYXRlZC4iLCBvaz1UcnVlKQogICAgICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtldmVudF9p"
    "ZH0uIiwKICAgICAgICAgICAgICAgICJPSyIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0"
    "b3Jfd29ya3NwYWNlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19l"
    "ZGl0b3Jfc3RhdHVzKGYiR29vZ2xlIHNhdmUgZmFpbGVkOiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdW0VSUk9SXSBHb29nbGUgc2F2ZSBmYWlsdXJlIGZvciB0"
    "aXRsZT0ne3RpdGxlfSc6IHtleH0iLAogICAgICAgICAgICAgICAgIkVSUk9SIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBz"
    "ZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRh"
    "dGU6IFFEYXRlKSAtPiBOb25lOgogICAgICAgIGRhdGVfdGV4dCA9IHFkYXRlLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAg"
    "ICByb3V0ZWRfdGFyZ2V0ID0gIm5vbmUiCgogICAgICAgIGZvY3VzX3dpZGdldCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgp"
    "CiAgICAgICAgZGlyZWN0X3RhcmdldHMgPSBbCiAgICAgICAgICAgICgidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIo"
    "Z2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAg"
    "ICAgICAgKCJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAi"
    "dGFza19lZGl0b3JfZW5kX2RhdGUiLCBOb25lKSksCiAgICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0"
    "X3RhcmdldHM6CiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAg"
    "ICAgICAgICAgICAgIHdpZGdldC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1l"
    "CiAgICAgICAgICAgICAgICBicmVhawoKICAgICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYg"
    "aGFzYXR0cihzZWxmLCAiX2lucHV0X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICAgICAgaWYgZm9jdXNfd2lkZ2V0IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0"
    "X2ZpZWxkLmluc2VydChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9p"
    "bnNlcnQiCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQo"
    "ZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBp"
    "ZiBoYXNhdHRyKHNlbGYsICJfdGFza3NfdGFiIikgYW5kIHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiQ2FsZW5kYXIgZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0i"
    "KQoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVuZGFyIGNs"
    "aWNrIHJvdXRlZDogZGF0ZT17ZGF0ZV90ZXh0fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAgICAgICAgIklO"
    "Rk8iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhzZWxmLCBmb3JjZV9v"
    "bmNlOiBib29sID0gRmFsc2UpOgogICAgICAgICIiIgogICAgICAgIFN5bmMgR29vZ2xlIENhbGVuZGFyIGV2ZW50cyDihpIgbG9j"
    "YWwgdGFza3MgdXNpbmcgR29vZ2xlJ3Mgc3luY1Rva2VuIEFQSS4KCiAgICAgICAgU3RhZ2UgMSAoZmlyc3QgcnVuIC8gZm9yY2Vk"
    "KTogRnVsbCBmZXRjaCwgc3RvcmVzIG5leHRTeW5jVG9rZW4uCiAgICAgICAgU3RhZ2UgMiAoZXZlcnkgcG9sbCk6ICAgICAgICAg"
    "SW5jcmVtZW50YWwgZmV0Y2ggdXNpbmcgc3RvcmVkIHN5bmNUb2tlbiDigJQKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICByZXR1cm5zIE9OTFkgd2hhdCBjaGFuZ2VkIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIElmIHNlcnZlciBy"
    "ZXR1cm5zIDQxMCBHb25lICh0b2tlbiBleHBpcmVkKSwgZmFsbHMgYmFjayB0byBmdWxsIHN5bmMuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaWYgbm90IGZvcmNlX29uY2UgYW5kIG5vdCBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNf"
    "ZW5hYmxlZCIsIFRydWUpKToKICAgICAgICAgICAgcmV0dXJuIDAKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBub3dfaXNvID0g"
    "bG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNr"
    "c19ieV9ldmVudF9pZCA9IHsKICAgICAgICAgICAgICAgICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6"
    "IHQKICAgICAgICAgICAgICAgIGZvciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9p"
    "ZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIH0KCiAgICAgICAgICAgICMg4pSA4pSAIEZldGNoIGZyb20gR29vZ2xlIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdG9yZWRfdG9rZW4g"
    "PSBzZWxmLl9zdGF0ZS5nZXQoImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIikKCiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIGlmIHN0b3JlZF90b2tlbiBhbmQgbm90IGZvcmNlX29uY2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gSW5jcmVtZW50YWwgc3luYyAoc3luY1Rva2Vu"
    "KS4iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90"
    "b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbj1z"
    "dG9yZWRfdG9rZW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEZ1bGwgc3luYyAobm8g"
    "c3RvcmVkIHRva2VuKS4iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9"
    "IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChu"
    "b3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVf"
    "ZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAg"
    "ICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "YXBpX2V4OgogICAgICAgICAgICAgICAgaWYgIjQxMCIgaW4gc3RyKGFwaV9leCkgb3IgIkdvbmUiIGluIHN0cihhcGlfZXgpOgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZ"
    "TkNdIHN5bmNUb2tlbiBleHBpcmVkICg0MTApIOKAlCBmdWxsIHJlc3luYy4iLCAiV0FSTiIKICAgICAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc3RhdGUucG9wKCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIsIE5vbmUpCiAg"
    "ICAgICAgICAgICAgICAgICAgbm93X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAg"
    "ICAgICAgICAgICAgICB0aW1lX21pbiA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIK"
    "ICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZl"
    "bnRzKAogICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVjZWl2ZWQge2xlbihyZW1vdGVfZXZlbnRzKX0gZXZlbnQocykuIiwg"
    "IklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgICMgU2F2ZSBuZXcgdG9rZW4gZm9yIG5leHQgaW5jcmVtZW50YWwgY2Fs"
    "bAogICAgICAgICAgICBpZiBuZXh0X3Rva2VuOgogICAgICAgICAgICAgICAgc2VsZi5fc3RhdGVbImdvb2dsZV9jYWxlbmRhcl9z"
    "eW5jX3Rva2VuIl0gPSBuZXh0X3Rva2VuCiAgICAgICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0"
    "ZSkKCiAgICAgICAgICAgICMg4pSA4pSAIFByb2Nlc3MgZXZlbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHVwZGF0ZWRfY291bnQgPSByZW1v"
    "dmVkX2NvdW50ID0gMAogICAgICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVf"
    "ZXZlbnRzOgogICAgICAgICAgICAgICAgZXZlbnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAg"
    "ICAgICAgICBpZiBub3QgZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICAjIERl"
    "bGV0ZWQgLyBjYW5jZWxsZWQgb24gR29vZ2xlJ3Mgc2lkZQogICAgICAgICAgICAgICAgaWYgZXZlbnQuZ2V0KCJzdGF0dXMiKSA9"
    "PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9p"
    "ZCkKICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZyBhbmQgZXhpc3RpbmcuZ2V0KCJzdGF0dXMiKSBub3QgaW4gKCJjYW5j"
    "ZWxsZWQiLCAiY29tcGxldGVkIik6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzdGF0dXMiXSAgICAgICAgID0g"
    "ImNhbmNlbGxlZCIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9hdCJdICAgPSBub3dfaXNvCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdICAgID0gImRlbGV0ZWRfcmVtb3RlIgogICAgICAg"
    "ICAgICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9zeW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZXhpc3Rpbmcuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSlbImdvb2dsZV9kZWxldGVkX3JlbW90ZSJdID0gbm93X2lzbwog"
    "ICAgICAgICAgICAgICAgICAgICAgICByZW1vdmVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9"
    "IFRydWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJbR09PR0xFXVtTWU5DXSBSZW1vdmVkOiB7ZXhpc3RpbmcuZ2V0KCd0ZXh0JywnPycpfSIsICJJTkZPIgogICAgICAgICAg"
    "ICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2"
    "ZW50LmdldCgic3VtbWFyeSIpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIg"
    "RXZlbnQiCiAgICAgICAgICAgICAgICBkdWVfYXQgID0gc2VsZi5fZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQoKICAgICAgICAgICAgICAgIGlm"
    "IGV4aXN0aW5nOgogICAgICAgICAgICAgICAgICAgICMgVXBkYXRlIGlmIGFueXRoaW5nIGNoYW5nZWQKICAgICAgICAgICAgICAg"
    "ICAgICB0YXNrX2NoYW5nZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAi"
    "Iikuc3RyaXAoKSAhPSBzdW1tYXJ5OgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sidGV4dCJdID0gc3VtbWFyeQog"
    "ICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0Ogog"
    "ICAgICAgICAgICAgICAgICAgICAgICBkdWVfaXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGV4aXN0aW5nWyJkdWVfYXQiXSAgICAgICA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4"
    "aXN0aW5nWyJwcmVfdHJpZ2dlciJdICA9IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAg"
    "ICAgICBpZiBleGlzdGluZy5nZXQoInN5bmNfc3RhdHVzIikgIT0gInN5bmNlZCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4"
    "aXN0aW5nWyJzeW5jX3N0YXR1cyJdID0gInN5bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgICAgIGlmIHRhc2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxh"
    "c3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291bnQgKz0gMQogICAgICAg"
    "ICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFVwZGF0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIgog"
    "ICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICMgTmV3IGV2"
    "ZW50CiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAg"
    "ICAgICAgICAgICAgICAgICBuZXdfdGFzayA9IHsKICAgICAgICAgICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICAg"
    "ZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAg"
    "ICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICAgZHVlX2F0Lmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgICAoZHVlX2F0IC0g"
    "dGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAidGV4dCI6ICAgICAgICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAg"
    "ICAicGVuZGluZyIsCiAgICAgICAgICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgIE5vbmUsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJyZXRyeV9jb3VudCI6ICAgICAgIDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJl"
    "ZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgIE5vbmUsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogICAgIEZhbHNlLAogICAgICAgICAgICAgICAgICAgICAgICAic291cmNlIjog"
    "ICAgICAgICAgICAiZ29vZ2xlIiwKICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICAgZXZlbnRfaWQs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICAgICAgICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAibGFzdF9zeW5jZWRfYXQiOiAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2ltcG9ydGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJnb29nbGVfdXBkYXRlZCI6ICAgICBldmVudC5nZXQoInVwZGF0ZWQiKSwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgfSwKICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQogICAg"
    "ICAgICAgICAgICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAgICAgICAg"
    "aW1wb3J0ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ10gSW1wb3J0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIikKCiAgICAgICAg"
    "ICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2Vs"
    "Zi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gRG9uZSDigJQgaW1wb3J0ZWQ9e2ltcG9ydGVkX2NvdW50fSAiCiAgICAgICAgICAgICAg"
    "ICBmInVwZGF0ZWQ9e3VwZGF0ZWRfY291bnR9IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9IiwgIklORk8iCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgcmV0dXJuIGltcG9ydGVkX2NvdW50CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAg"
    "cmV0dXJuIDAKCgogICAgZGVmIF9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09L"
    "IGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdl"
    "dE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAx"
    "MDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFz"
    "ZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNL"
    "X05BTUV9J3MgZm9vdHByaW50KSIsICJJTkZPIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgcGFzcwoKICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgX3NlbmRfbWVzc2FnZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5f"
    "dG9ycG9yX3N0YXRlID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2Zp"
    "ZWxkLnRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IHRleHQ6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAg"
    "YmFjayB0byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJz"
    "LmN1cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAg"
    "ICAjIFNlc3Npb24gbG9nZ2luZwogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAg"
    "ICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIElu"
    "dGVycnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3Rp"
    "bWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVp"
    "bGQgcHJvbXB0IHdpdGggdmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWls"
    "ZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9yeS5idWlsZF9jb250ZXh0X2Jsb2Nr"
    "KHRleHQpCiAgICAgICAgam91cm5hbF9jdHggID0gIiIKCiAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxf"
    "ZGF0ZToKICAgICAgICAgICAgam91cm5hbF9jdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1"
    "aWxkIHN5c3RlbSBwcm9tcHQKICAgICAgICBzeXN0ZW0gPSBTWVNURU1fUFJPTVBUX0JBU0UKICAgICAgICBpZiBtZW1vcnlfY3R4"
    "OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue21lbW9yeV9jdHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4OgogICAgICAg"
    "ICAgICBzeXN0ZW0gKz0gZiJcblxue2pvdXJuYWxfY3R4fSIKICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAg"
    "IyBMZXNzb25zIGNvbnRleHQgZm9yIGNvZGUtYWRqYWNlbnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigp"
    "IGZvciBrdyBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9"
    "ICJMU0wiIGlmICJsc2wiIGluIHRleHQubG93ZXIoKSBlbHNlICJQeXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2Vs"
    "Zi5fbGVzc29ucy5idWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShsYW5nKQogICAgICAgICAgICBpZiBsZXNzb25zX2N0eDoKICAg"
    "ICAgICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRyYW5zbWlz"
    "c2lvbnMgY29udGV4dCBpZiBhbnkKICAgICAgICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAg"
    "ICBkdXIgPSBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAg"
    "ICAgICAgICAgICAgIGYiXG5cbltSRVRVUk4gRlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRv"
    "cnBvciBmb3Ige2R1cn0uICIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMg"
    "d2VudCB1bnNwb2tlbiAiCiAgICAgICAgICAgICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFja25vd2xlZGdlIHRoaXMgYnJpZWZs"
    "eSBpbiBjaGFyYWN0ZXIgIgogICAgICAgICAgICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlv"
    "biAgICA9ICIiCgogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMgRGlzYWJs"
    "ZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJHRU5FUkFUSU5HIikKCiAgICAgICAgIyBTdG9wIGlk"
    "bGUgdGltZXIgZHVyaW5nIGdlbmVyYXRpb24KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1"
    "bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2No"
    "ZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICAgICAgcGFzcwoKICAgICAgICAjIExhdW5jaCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3Ry"
    "ZWFtaW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1heF90b2tlbnM9NTEyCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNl"
    "bGYuX3dvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3Jr"
    "ZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5n"
    "ZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdy"
    "aXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYg"
    "X2JlZ2luX3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0ZSB0aGUgcGVyc29u"
    "YSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZp"
    "cnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQgdG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1l"
    "c3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNwZWFrZXIgbGFi"
    "ZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2VucwogICAgICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhh"
    "biBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAg"
    "ICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAg"
    "IGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQg"
    "c28gaW5zZXJ0UGxhaW5UZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRl"
    "eHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9rZW4oc2VsZiwgdG9rZW46"
    "IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAg"
    "ICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAg"
    "ICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNv"
    "cigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWlu"
    "VGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAg"
    "ICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBf"
    "b25fcmVzcG9uc2VfZG9uZShzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlz"
    "IG9uIGl0cyBvd24gbGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBj"
    "dXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikK"
    "CiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgKz0gbGVuKHJlc3Bv"
    "bnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAg"
    "ICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAg"
    "ICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAj"
    "IFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2Vs"
    "Zi5fbGVmdF9vcmIuc2V0RmlsbCgKICAgICAgICAgICAgICAgIG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQog"
    "ICAgICAgICAgICApCgogICAgICAgICMgUmUtZW5hYmxlIGlucHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChU"
    "cnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5z"
    "ZXRGb2N1cygpCgogICAgICAgICMgUmVzdW1lIGlkbGUgdGltZXIKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYg"
    "c2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTY2hlZHVsZSBzZW50aW1lbnQgYW5hbHlzaXMgKDUgc2Vjb25k"
    "IGRlbGF5KQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIGxhbWJkYTogc2VsZi5fcnVuX3NlbnRpbWVudChyZXNwb25z"
    "ZSkpCgogICAgZGVmIF9ydW5fc2VudGltZW50KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNl"
    "bGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIgPSBTZW50aW1lbnRX"
    "b3JrZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuZmFjZV9yZWFkeS5jb25uZWN0"
    "KHNlbGYuX29uX3NlbnRpbWVudCkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9vbl9zZW50aW1l"
    "bnQoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAg"
    "ICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZShlbW90aW9uKQoKICAgIGRlZiBfb25fZXJyb3Ioc2VsZiwgZXJyb3I6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlcnJvcikKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbR0VORVJBVElPTiBFUlJPUl0ge2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9t"
    "Z3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLnNldF9mYWNlKCJwYW5pY2tlZCIpCiAgICAgICAgc2VsZi5fc2V0"
    "X3N0YXR1cygiRVJST1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1"
    "dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCgogICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll90b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAgICAgICBpZiBzdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2Vu"
    "dGVyX3RvcnBvcihyZWFzb249Im1hbnVhbCDigJQgU1VTUEVORCBtb2RlIHNlbGVjdGVkIikKICAgICAgICBlbGlmIHN0YXRlID09"
    "ICJBV0FLRSI6CiAgICAgICAgICAgICMgQWx3YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dpdGNoaW5nIHRvIEFXQUtFIOKAlAogICAg"
    "ICAgICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEgYmFja2VuZCB3aGVyZSBtb2RlbCBpc24ndCB1bmxvYWRlZCwKICAgICAgICAgICAg"
    "IyB3ZSBuZWVkIHRvIHJlLWVuYWJsZSBVSSBhbmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQog"
    "ICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNr"
    "cyAgID0gMAogICAgICAgIGVsaWYgc3RhdGUgPT0gIkFVVE8iOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAiW1RPUlBPUl0gQVVUTyBtb2RlIOKAlCBtb25pdG9yaW5nIFZSQU0gcHJlc3N1cmUuIiwgIklORk8iCiAgICAg"
    "ICAgICAgICkKCiAgICBkZWYgX2VudGVyX3RvcnBvcihzZWxmLCByZWFzb246IHN0ciA9ICJtYW51YWwiKSAtPiBOb25lOgogICAg"
    "ICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgaW4gdG9y"
    "cG9yCgogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW1RPUlBPUl0gRW50ZXJpbmcgdG9ycG9yOiB7cmVhc29ufSIsICJXQVJOIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgi"
    "U1lTVEVNIiwgIlRoZSB2ZXNzZWwgZ3Jvd3MgY3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoKICAgICAgICAjIFVubG9hZCBtb2RlbCBm"
    "cm9tIFZSQU0KICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQgYW5kIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICAg"
    "ICAgICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9tb2RlbAogICAgICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX21vZGVsID0g"
    "Tm9uZQogICAgICAgICAgICAgICAgaWYgVE9SQ0hfT0s6CiAgICAgICAgICAgICAgICAgICAgdG9yY2guY3VkYS5lbXB0eV9jYWNo"
    "ZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fbW9k"
    "ZWxfbG9hZGVkICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gTW9kZWwgdW5s"
    "b2FkZWQgZnJvbSBWUkFNLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1JdIE1vZGVsIHVubG9hZCBlcnJvcjoge2V9"
    "IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQoKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQogICAg"
    "ICAgIHNlbGYuX3NldF9zdGF0dXMoIlRPUlBPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhpdF90b3Jwb3Ioc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICAjIENhbGN1bGF0ZSBzdXNwZW5kZWQgZHVyYXRpb24KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2U6CiAg"
    "ICAgICAgICAgIGRlbHRhID0gZGF0ZXRpbWUubm93KCkgLSBzZWxmLl90b3Jwb3Jfc2luY2UKICAgICAgICAgICAgc2VsZi5fc3Vz"
    "cGVuZGVkX2R1cmF0aW9uID0gZm9ybWF0X2R1cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMoKSkKICAgICAgICAgICAgc2VsZi5f"
    "dG9ycG9yX3NpbmNlID0gTm9uZQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIFdha2luZyBmcm9tIHRvcnBv"
    "ci4uLiIsICJJTkZPIikKCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICAjIE9sbGFtYSBiYWNrZW5k"
    "IOKAlCBtb2RlbCB3YXMgbmV2ZXIgdW5sb2FkZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9j"
    "aGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzICIKICAg"
    "ICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29ubmVjdGlvbiBob2xkcy4gU2hlIGlz"
    "IGxpc3RlbmluZy4iKQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9i"
    "dG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10b3Jwb3IgZGlzYWJsZWQuIiwgIklO"
    "Rk8iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgTG9jYWwgbW9kZWwgd2FzIHVubG9hZGVkIOKAlCBuZWVkIGZ1bGwgcmVs"
    "b2FkCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVt"
    "cHRpZXMuIHtERUNLX05BTUV9IHN0aXJzIGZyb20gdG9ycG9yICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRf"
    "ZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1"
    "cygiTE9BRElORyIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAg"
    "ICAgICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAg"
    "ICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRf"
    "Y29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQu"
    "Y29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVuZChz"
    "ZWxmLl9sb2FkZXIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9jaGVja192cmFtX3ByZXNzdXJl"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vjb25kcyBmcm9tIEFQU2NoZWR1bGVy"
    "IHdoZW4gdG9ycG9yIHN0YXRlIGlzIEFVVE8uCiAgICAgICAgT25seSB0cmlnZ2VycyB0b3Jwb3IgaWYgZXh0ZXJuYWwgVlJBTSB1"
    "c2FnZSBleGNlZWRzIHRocmVzaG9sZAogICAgICAgIEFORCBpcyBzdXN0YWluZWQg4oCUIG5ldmVyIHRyaWdnZXJzIG9uIHRoZSBw"
    "ZXJzb25hJ3Mgb3duIGZvb3RwcmludC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc3RhdGUgIT0gIkFVVE8i"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1X2hhbmRsZToKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgaWYgc2VsZi5fZGVja192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgbWVtX2luZm8gID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAg"
    "ICAgICAgIHRvdGFsX3VzZWQgPSBtZW1faW5mby51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICBleHRlcm5hbCAgID0gdG90YWxf"
    "dXNlZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNlCgogICAgICAgICAgICBpZiBleHRlcm5hbCA+IHNlbGYuX0VYVEVSTkFMX1ZSQU1f"
    "VE9SUE9SX0dCOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAg"
    "ICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3VudGluZwogICAgICAgICAgICAgICAg"
    "c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgICA9"
    "IDAKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10g"
    "RXh0ZXJuYWwgVlJBTSBwcmVzc3VyZTogIgogICAgICAgICAgICAgICAgICAgIGYie2V4dGVybmFsOi4yZn1HQiAiCiAgICAgICAg"
    "ICAgICAgICAgICAgZiIodGljayB7c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrc30vIgogICAgICAgICAgICAgICAgICAgIGYie3Nl"
    "bGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1N9KSIsICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYg"
    "KHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLUwogICAgICAgICAgICAgICAg"
    "ICAgICAgICBhbmQgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIE5vbmUpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2VudGVyX3Rv"
    "cnBvcigKICAgICAgICAgICAgICAgICAgICAgICAgcmVhc29uPWYiYXV0byDigJQge2V4dGVybmFsOi4xZn1HQiBleHRlcm5hbCBW"
    "UkFNICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYicHJlc3N1cmUgc3VzdGFpbmVkIgogICAgICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgIyByZXNldCBhZnRlciBlbnRl"
    "cmluZyB0b3Jwb3IKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAw"
    "CiAgICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9yZWxpZWZfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgICAgIGF1dG9fd2FrZSA9IENGR1sic2V0dGluZ3MiXS5n"
    "ZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFsc2UKICAgICAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICAgICAgaWYgKGF1dG9fd2FrZSBhbmQKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X3ZyYW1fcmVsaWVmX3RpY2tzID49IHNlbGYuX1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPSAwCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltUT1JQT1IgQVVUT10gVlJBTSBjaGVjayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICApCgogICAgIyDilIDi"
    "lIAgQVBTQ0hFRFVMRVIgU0VUVVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldHVwX3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJhY2tncm91bmQgaW1wb3J0IEJhY2tn"
    "cm91bmRTY2hlZHVsZXIKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gQmFja2dyb3VuZFNjaGVkdWxlcigKICAgICAgICAg"
    "ICAgICAgIGpvYl9kZWZhdWx0cz17Im1pc2ZpcmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0"
    "IEltcG9ydEVycm9yOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgICAgICJbU0NIRURVTEVSXSBhcHNjaGVkdWxlciBub3QgYXZhaWxhYmxlIOKAlCAiCiAgICAgICAg"
    "ICAgICAgICAiaWRsZSwgYXV0b3NhdmUsIGFuZCByZWZsZWN0aW9uIGRpc2FibGVkLiIsICJXQVJOIgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICBpbnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJhdXRvc2F2ZV9pbnRl"
    "cnZhbF9taW51dGVzIiwgMTApCgogICAgICAgICMgQXV0b3NhdmUKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAg"
    "ICAgICAgICAgc2VsZi5fYXV0b3NhdmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aW50ZXJ2YWxfbWluLCBpZD0i"
    "YXV0b3NhdmUiCiAgICAgICAgKQoKICAgICAgICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2ZXJ5IDVzKQogICAgICAgIHNlbGYu"
    "X3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9jaGVja192cmFtX3ByZXNzdXJlLCAiaW50ZXJ2YWwiLAogICAg"
    "ICAgICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFtX2NoZWNrIgogICAgICAgICkKCiAgICAgICAgIyBJZGxlIHRyYW5zbWlzc2lvbiAo"
    "c3RhcnRzIHBhdXNlZCDigJQgZW5hYmxlZCBieSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxlX21pbiA9IENGR1sic2V0dGluZ3Mi"
    "XS5nZXQoImlkbGVfbWluX21pbnV0ZXMiLCAxMCkKICAgICAgICBpZGxlX21heCA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVf"
    "bWF4X21pbnV0ZXMiLCAzMCkKICAgICAgICBpZGxlX2ludGVydmFsID0gKGlkbGVfbWluICsgaWRsZV9tYXgpIC8vIDIKCiAgICAg"
    "ICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRsZV90cmFuc21pc3Npb24sICJpbnRl"
    "cnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aWRsZV9pbnRlcnZhbCwgaWQ9ImlkbGVfdHJhbnNtaXNzaW9uIgogICAgICAgICkK"
    "CiAgICAgICAgIyBDeWNsZSB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBpZiBzZWxmLl9jeWNsZV93aWRn"
    "ZXQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICAgICAgc2VsZi5f"
    "Y3ljbGVfd2lkZ2V0LnVwZGF0ZVBoYXNlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICAgICAgaG91cnM9NiwgaWQ9Im1vb25fcmVm"
    "cmVzaCIKICAgICAgICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgpIGlzIGNhbGxlZCBmcm9tIHN0YXJ0"
    "X3NjaGVkdWxlcigpCiAgICAgICAgIyB3aGljaCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3"
    "aW5kb3cKICAgICAgICAjIGlzIHNob3duIGFuZCB0aGUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMgRG8gTk9U"
    "IGNhbGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRfc2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRlciB3aW5kb3cuc2hvdygpIGFuZCBh"
    "cHAuZXhlYygpIGJlZ2lucy4KICAgICAgICBEZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJlZm9y"
    "ZSBiYWNrZ3JvdW5kIHRocmVhZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGlzIE5vbmU6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkKICAgICAg"
    "ICAgICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFu"
    "c21pc3Npb24iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJdIEFQU2NoZWR1bGVyIHN0YXJ0ZWQu"
    "IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltT"
    "Q0hFRFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGVi"
    "YXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgKICAgICAgICAgICAg"
    "ICAgIDMwMDAsIGxhbWJkYTogc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNlc3Npb24gc2F2ZWQuIiwgIklORk8i"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0FVVE9TQVZF"
    "XSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Npb24oc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgIyBJbiB0b3Jwb3Ig"
    "4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQgYnV0IGRvbid0IGdlbmVyYXRlCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdf"
    "dHJhbnNtaXNzaW9ucyArPSAxCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0lETEVd"
    "IEluIHRvcnBvciDigJQgcGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAgICAgZiIje3NlbGYuX3BlbmRpbmdfdHJh"
    "bnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbW9kZSA9IHJhbmRv"
    "bS5jaG9pY2UoWyJERUVQRU5JTkciLCJCUkFOQ0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1aWxk"
    "X3ZhbXBpcmVfY29udGV4dCgpCiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAg"
    "c2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICBTWVNU"
    "RU1fUFJPTVBUX0JBU0UsCiAgICAgICAgICAgIGhpc3RvcnksCiAgICAgICAgICAgIG1vZGU9bW9kZSwKICAgICAgICAgICAgdmFt"
    "cGlyZV9jb250ZXh0PXZhbXBpcmVfY3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVfcmVhZHkodDogc3RyKSAtPiBO"
    "b25lOgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQogICAgICAgICAgICBzZWxmLl9tYWlu"
    "X3RhYnMuc2V0Q3VycmVudEluZGV4KDEpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikK"
    "ICAgICAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9y"
    "OntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dHN9XSBbe21vZGV9XTwvc3Bhbj48"
    "YnI+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dH08L3NwYW4+PGJyPicKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAgICAgIHNlbGYuX2lk"
    "bGVfd29ya2VyLnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQogICAgICAgIHNlbGYuX2lkbGVfd29y"
    "a2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURM"
    "RSBFUlJPUl0ge2V9IiwgIkVSUk9SIikKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQoKQoKICAgICMg"
    "4pSA4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRlX3N0cjogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KGRhdGVfc3RyKQog"
    "ICAgICAgIGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0pPVVJO"
    "QUxdIE5vIHNlc3Npb24gZm91bmQgZm9yIHtkYXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRhdGVfc3RyKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNv"
    "bnRleHQuICIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRpb24uIiwgIk9L"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJBIG1lbW9yeSBzdGly"
    "cy4uLiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAgICAgICkKICAgICAgICAjIE5vdGlm"
    "eSBNb3JnYW5uYQogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAg"
    "ICAgIGYiW0pPVVJOQUwgTE9BREVEXSBUaGUgdXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFsIGZyb20gIgogICAgICAgICAgICAg"
    "ICAgZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBub3cgaGF2ZSAiCiAgICAgICAgICAgICAg"
    "ICBmImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bnMuYWRkX21lc3NhZ2UoInN5c3RlbSIsIG5vdGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24oc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KCJbSk9VUk5BTF0gSm91cm5hbCBjb250ZXh0IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJT"
    "WVNURU0iLAogICAgICAgICAgICAiVGhlIGpvdXJuYWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMuIgogICAgICAg"
    "ICkKCiAgICAjIOKUgOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3VwZGF0ZV9z"
    "dGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkgLSBzZWxmLl9zZXNzaW9uX3N0YXJ0"
    "KQogICAgICAgIGgsIG0sIHMgPSBlbGFwc2VkIC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkgLy8gNjAsIGVsYXBzZWQgJSA2MAog"
    "ICAgICAgIHNlc3Npb25fc3RyID0gZiJ7aDowMmR9OnttOjAyZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwuc2V0"
    "X3N0YXR1c19sYWJlbHMoCiAgICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAgICAgQ0ZHWyJtb2RlbCJdLmdldCgidHlw"
    "ZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAgICAgIHN0cihzZWxmLl90b2tlbl9j"
    "b3VudCksCiAgICAgICAgKQogICAgICAgIHNlbGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTGVmdCBzcGhl"
    "cmUgPSBhY3RpdmUgcmVzZXJ2ZSBmcm9tIHJ1bnRpbWUgdG9rZW4gcG9vbAogICAgICAgIGxlZnRfb3JiX2ZpbGwgPSBtaW4oMS4w"
    "LCBzZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fbGVmdF9vcmIuc2V0RmlsbChsZWZ0X29yYl9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgIyBSaWdo"
    "dCBzcGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX3JpZ2h0X29yYiBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBt"
    "ZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICB2cmFtX3Vz"
    "ZWQgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtLnRvdGFsIC8gMTAyNCoq"
    "MwogICAgICAgICAgICAgICAgICAgIHJpZ2h0X29yYl9maWxsID0gbWF4KDAuMCwgMS4wIC0gKHZyYW1fdXNlZCAvIHZyYW1fdG90"
    "KSkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbChyaWdodF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRy"
    "dWUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5z"
    "ZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRf"
    "b3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCgogICAgICAgICMgUHJpbWFyeSBlc3NlbmNlID0gaW52ZXJzZSBvZiBs"
    "ZWZ0IHNwaGVyZSBmaWxsCiAgICAgICAgZXNzZW5jZV9wcmltYXJ5X3JhdGlvID0gMS4wIC0gbGVmdF9vcmJfZmlsbAogICAgICAg"
    "IGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2Uuc2V0VmFsdWUoZXNz"
    "ZW5jZV9wcmltYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3ByaW1hcnlfcmF0aW8qMTAwOi4wZn0lIikKCiAgICAgICAgIyBT"
    "ZWNvbmRhcnkgZXNzZW5jZSA9IFJBTSBmcmVlCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgIGlmIFBT"
    "VVRJTF9PSzoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBtZW0gICAgICAgPSBwc3V0aWwudmlydHVh"
    "bF9tZW1vcnkoKQogICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICA9IDEuMCAtIChtZW0udXNlZCAv"
    "IG1lbS50b3RhbCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRWYWx1ZSgKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZXNzZW5jZV9zZWNvbmRhcnlfcmF0aW8gKiAxMDAsIGYie2Vzc2VuY2Vfc2Vjb25kYXJ5X3Jh"
    "dGlvKjEwMDouMGZ9JSIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKCiAgICAg"
    "ICAgIyBVcGRhdGUgam91cm5hbCBzaWRlYmFyIGF1dG9zYXZlIGZsYXNoCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnJl"
    "ZnJlc2goKQoKICAgICMg4pSA4pSAIENIQVQgRElTUExBWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYXBw"
    "ZW5kX2NoYXQoc2VsZiwgc3BlYWtlcjogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY29sb3JzID0gewogICAgICAg"
    "ICAgICAiWU9VIjogICAgIENfR09MRCwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19HT0xELAogICAgICAgICAgICAi"
    "U1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGxhYmVs"
    "X2NvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTERfRElNLAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIo"
    "KTpDX0NSSU1TT04sCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9P"
    "RCwKICAgICAgICB9CiAgICAgICAgY29sb3IgICAgICAgPSBjb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRCkKICAgICAgICBsYWJl"
    "bF9jb2xvciA9IGxhYmVsX2NvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEX0RJTSkKICAgICAgICB0aW1lc3RhbXAgICA9IGRhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCgogICAgICAgIGlmIHNwZWFrZXIgPT0gIlNZU1RFTSI6CiAgICAgICAgICAg"
    "IHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAg"
    "ICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7bGFiZWxfY29sb3J9OyI+4pymIHt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3Bh"
    "biBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3Rh"
    "bXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsgZm9udC13ZWln"
    "aHQ6Ym9sZDsiPicKICAgICAgICAgICAgICAgIGYne3NwZWFrZXJ9IOKdpzwvc3Bhbj4gJwogICAgICAgICAgICAgICAgZic8c3Bh"
    "biBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKCiAgICAgICAgIyBBZGQgYmxhbmsg"
    "bGluZSBhZnRlciBNb3JnYW5uYSdzIHJlc3BvbnNlIChub3QgZHVyaW5nIHN0cmVhbWluZykKICAgICAgICBpZiBzcGVha2VyID09"
    "IERFQ0tfTkFNRS51cHBlcigpOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKCIiKQoKICAgICAgICBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRVUyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKHNl"
    "bGYpIC0+IGludDoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdmFsID0gc2V0dGlu"
    "Z3MuZ2V0KCJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVy"
    "biBtYXgoMTAwMCwgaW50KHZhbCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoK"
    "ICAgIGRlZiBfZ2V0X2VtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMoc2VsZikgLT4gaW50OgogICAgICAgIHNldHRpbmdzID0gQ0ZH"
    "LmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB2YWwgPSBzZXR0aW5ncy5nZXQoImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMi"
    "LCAzMDAwMDApCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX3NldF9nb29nbGVfcmVmcmVzaF9zZWNvbmRz"
    "KHNlbGYsIHNlY29uZHM6IGludCkgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlY29uZHMgPSBtYXgoNSwgbWlu"
    "KDYwMCwgaW50KHNlY29uZHMpKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBD"
    "RkdbInNldHRpbmdzIl1bImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIl0gPSBzZWNvbmRzICogMTAwMAogICAgICAgIHNhdmVf"
    "Y29uZmlnKENGRykKICAgICAgICBmb3IgdGltZXIgaW4gKHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLCBzZWxmLl9nb29nbGVf"
    "cmVjb3Jkc19yZWZyZXNoX3RpbWVyKToKICAgICAgICAgICAgaWYgdGltZXIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICB0"
    "aW1lci5zdGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMoKSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbU0VUVElOR1NdIEdvb2dsZSByZWZyZXNoIGludGVydmFsIHNldCB0byB7c2Vjb25kc30gc2Vjb25kKHMpLiIsICJPSyIp"
    "CgogICAgZGVmIF9zZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dChzZWxmLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBtaW51dGVzID0gbWF4KDEsIGludChmbG9hdChzdHIodGV4dCkuc3RyaXAoKSkpKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiZW1haWxfcmVm"
    "cmVzaF9pbnRlcnZhbF9tcyJdID0gbWludXRlcyAqIDYwMDAwCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbU0VUVElOR1NdIEVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgc2V0IHRvIHttaW51"
    "dGVzfSBtaW51dGUocykgKGNvbmZpZyBmb3VuZGF0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRl"
    "ZiBfc2V0X3RpbWV6b25lX2F1dG9fZGV0ZWN0KHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0"
    "aW5ncyJdWyJ0aW1lem9uZV9hdXRvX2RldGVjdCJdID0gYm9vbChlbmFibGVkKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbU0VUVElOR1NdIFRpbWUgem9uZSBtb2RlIHNldCB0byBhdXRv"
    "LWRldGVjdC4iIGlmIGVuYWJsZWQgZWxzZSAiW1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gbWFudWFsIG92ZXJyaWRl"
    "LiIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVfb3ZlcnJpZGUoc2VsZiwgdHpf"
    "bmFtZTogc3RyKSAtPiBOb25lOgogICAgICAgIHR6X3ZhbHVlID0gc3RyKHR6X25hbWUgb3IgIiIpLnN0cmlwKCkKICAgICAgICBD"
    "RkdbInNldHRpbmdzIl1bInRpbWV6b25lX292ZXJyaWRlIl0gPSB0el92YWx1ZQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAg"
    "ICAgICBpZiB0el92YWx1ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdTXSBUaW1lIHpvbmUgb3Zl"
    "cnJpZGUgc2V0IHRvIHt0el92YWx1ZX0uIiwgIklORk8iKQoKICAgIGRlZiBfc2V0X3N0YXR1cyhzZWxmLCBzdGF0dXM6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXMgPSBzdGF0dXMKICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAg"
    "ICAiSURMRSI6ICAgICAgIENfR09MRCwKICAgICAgICAgICAgIkdFTkVSQVRJTkciOiBDX0NSSU1TT04sCiAgICAgICAgICAgICJM"
    "T0FESU5HIjogICAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgICAgQ19CTE9PRCwKICAgICAgICAgICAgIk9GRkxJ"
    "TkUiOiAgICBDX0JMT09ELAogICAgICAgICAgICAiVE9SUE9SIjogICAgIENfUFVSUExFX0RJTSwKICAgICAgICB9CiAgICAgICAg"
    "Y29sb3IgPSBzdGF0dXNfY29sb3JzLmdldChzdGF0dXMsIENfVEVYVF9ESU0pCgogICAgICAgIHRvcnBvcl9sYWJlbCA9IGYi4peJ"
    "IHtVSV9UT1JQT1JfU1RBVFVTfSIgaWYgc3RhdHVzID09ICJUT1JQT1IiIGVsc2UgZiLil4kge3N0YXR1c30iCiAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfbGFiZWwuc2V0VGV4dCh0b3Jwb3JfbGFiZWwpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVy"
    "OiBub25lOyIKICAgICAgICApCgogICAgZGVmIF9ibGluayhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRl"
    "ID0gbm90IHNlbGYuX2JsaW5rX3N0YXRlCiAgICAgICAgaWYgc2VsZi5fc3RhdHVzID09ICJHRU5FUkFUSU5HIjoKICAgICAgICAg"
    "ICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKXjiIKICAgICAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwuc2V0VGV4dChmIntjaGFyfSBHRU5FUkFUSU5HIikKICAgICAgICBlbGlmIHNlbGYuX3N0YXR1cyA9PSAiVE9SUE9SIjoKICAg"
    "ICAgICAgICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKKmCIKICAgICAgICAgICAgc2VsZi5zdGF0"
    "dXNfbGFiZWwuc2V0VGV4dCgKICAgICAgICAgICAgICAgIGYie2NoYXJ9IHtVSV9UT1JQT1JfU1RBVFVTfSIKICAgICAgICAgICAg"
    "KQoKICAgICMg4pSA4pSAIElETEUgVE9HR0xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9vbl9pZGxl"
    "X3RvZ2dsZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bImlkbGVfZW5hYmxl"
    "ZCJdID0gZW5hYmxlZAogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFRleHQoIklETEUgT04iIGlmIGVuYWJsZWQgZWxzZSAiSURM"
    "RSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycj"
    "MWExMDA1JyBpZiBlbmFibGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHsnI2NjODgyMicgaWYgZW5hYmxl"
    "ZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgeycjY2M4ODIyJyBpZiBlbmFibGVk"
    "IGVsc2UgQ19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBmb250LXNpemU6IDlweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2F2ZV9jb25m"
    "aWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3Vt"
    "ZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJ"
    "ZGxlIHRyYW5zbWlzc2lvbiBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7"
    "ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9n"
    "Z2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBz"
    "ZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3JlZW5fZW5hYmxlZCJdID0gRmFsc2UK"
    "ICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4"
    "cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5zaG93RnVsbFNjcmVlbigpCiAgICAgICAg"
    "ICAgIENGR1sic2V0dGluZ3MiXVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklN"
    "U09OfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIK"
    "ICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAg"
    "IHNhdmVfY29uZmlnKENGRykKCiAgICBkZWYgX3RvZ2dsZV9ib3JkZXJsZXNzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaXNfYmwg"
    "PSBib29sKHNlbGYud2luZG93RmxhZ3MoKSAmIFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludCkKICAgICAgICBpZiBp"
    "c19ibDoKICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSAm"
    "IH5RdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdz"
    "Il1bImJvcmRlcmxlc3NfZW5hYmxlZCJdID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAg"
    "ZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNl"
    "bGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1l"
    "bGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImJvcmRlcmxlc3NfZW5hYmxl"
    "ZCJdID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5zaG93KCkK"
    "CiAgICBkZWYgX2V4cG9ydF9jaGF0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiRXhwb3J0IGN1cnJlbnQgcGVyc29uYSBjaGF0"
    "IHRhYiBjb250ZW50IHRvIGEgVFhUIGZpbGUuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fY2hhdF9k"
    "aXNwbGF5LnRvUGxhaW5UZXh0KCkKICAgICAgICAgICAgaWYgbm90IHRleHQuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGly"
    "KHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVkl"
    "bSVkXyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYic2VhbmNlX3t0c30udHh0IgogICAgICAg"
    "ICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KHRleHQsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgICAgICAgICAjIEFsc28gY29weSB0"
    "byBjbGlwYm9hcmQKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQodGV4dCkKCiAgICAgICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJTZXNzaW9uIGV4cG9ydGVkIHRvIHtvdXRfcGF0"
    "aC5uYW1lfSBhbmQgY29waWVkIHRvIGNsaXBib2FyZC4iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JU"
    "XSB7b3V0X3BhdGh9IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIltFWFBPUlRdIEZhaWxlZDoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYga2V5UHJlc3NFdmVudChzZWxmLCBldmVu"
    "dCkgLT4gTm9uZToKICAgICAgICBrZXkgPSBldmVudC5rZXkoKQogICAgICAgIGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMToKICAg"
    "ICAgICAgICAgc2VsZi5fdG9nZ2xlX2Z1bGxzY3JlZW4oKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRjEwOgogICAg"
    "ICAgICAgICBzZWxmLl90b2dnbGVfYm9yZGVybGVzcygpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9Fc2NhcGUgYW5k"
    "IHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0"
    "bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9E"
    "SU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7"
    "ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgc3VwZXIoKS5rZXlQcmVzc0V2ZW50KGV2ZW50KQoKICAgICMg4pSA4pSAIENMT1NFIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+"
    "IE5vbmU6CiAgICAgICAgIyBYIGJ1dHRvbiA9IGltbWVkaWF0ZSBzaHV0ZG93biwgbm8gZGlhbG9nCiAgICAgICAgc2VsZi5fZG9f"
    "c2h1dGRvd24oTm9uZSkKCiAgICBkZWYgX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZyhzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IkdyYWNlZnVsIHNodXRkb3duIOKAlCBzaG93IGNvbmZpcm0gZGlhbG9nIGltbWVkaWF0ZWx5LCBvcHRpb25hbGx5IGdldCBsYXN0"
    "IHdvcmRzLiIiIgogICAgICAgICMgSWYgYWxyZWFkeSBpbiBhIHNodXRkb3duIHNlcXVlbmNlLCBqdXN0IGZvcmNlIHF1aXQKICAg"
    "ICAgICBpZiBnZXRhdHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSk6CiAgICAgICAgICAgIHNlbGYuX2Rv"
    "X3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gVHJ1"
    "ZQoKICAgICAgICAjIFNob3cgY29uZmlybSBkaWFsb2cgRklSU1Qg4oCUIGRvbid0IHdhaXQgZm9yIEFJCiAgICAgICAgZGxnID0g"
    "UURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiRGVhY3RpdmF0ZT8iKQogICAgICAgIGRsZy5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBkbGcuc2V0Rml4ZWRTaXplKDM4MCwg"
    "MTQwKQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbGJsID0gUUxhYmVsKAogICAgICAgICAgICBm"
    "IkRlYWN0aXZhdGUge0RFQ0tfTkFNRX0/XG5cbiIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBtYXkgc3BlYWsgdGhlaXIgbGFz"
    "dCB3b3JkcyBiZWZvcmUgZ29pbmcgc2lsZW50LiIKICAgICAgICApCiAgICAgICAgbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChsYmwpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2xhc3Qg"
    "ID0gUVB1c2hCdXR0b24oIkxhc3QgV29yZHMgKyBTaHV0ZG93biIpCiAgICAgICAgYnRuX25vdyAgID0gUVB1c2hCdXR0b24oIlNo"
    "dXRkb3duIE5vdyIpCiAgICAgICAgYnRuX2NhbmNlbCA9IFFQdXNoQnV0dG9uKCJDYW5jZWwiKQoKICAgICAgICBmb3IgYiBpbiAo"
    "YnRuX2xhc3QsIGJ0bl9ub3csIGJ0bl9jYW5jZWwpOgogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjgpCiAgICAgICAg"
    "ICAgIGIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFR9"
    "OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAg"
    "ICAgICAgICAgKQogICAgICAgIGJ0bl9ub3cuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CTE9P"
    "RH07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBwYWRkaW5n"
    "OiA0cHggMTJweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9sYXN0LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDEp"
    "KQogICAgICAgIGJ0bl9ub3cuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMikpCiAgICAgICAgYnRuX2NhbmNlbC5j"
    "bGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgwKSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9ub3cpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2xhc3QpCiAgICAg"
    "ICAgbGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAgICAgICByZXN1bHQgPSBkbGcuZXhlYygpCgogICAgICAgIGlmIHJlc3Vs"
    "dCA9PSAwOgogICAgICAgICAgICAjIENhbmNlbGxlZAogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IEZh"
    "bHNlCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmll"
    "bGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBlbGlmIHJlc3VsdCA9PSAyOgogICAgICAgICAg"
    "ICAjIFNodXRkb3duIG5vdyDigJQgbm8gbGFzdCB3b3JkcwogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAg"
    "ICAgIGVsaWYgcmVzdWx0ID09IDE6CiAgICAgICAgICAgICMgTGFzdCB3b3JkcyB0aGVuIHNodXRkb3duCiAgICAgICAgICAgIHNl"
    "bGYuX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oKQoKICAgIGRlZiBfZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgZmFyZXdlbGwgcHJvbXB0LCBzaG93IHJlc3BvbnNlLCB0aGVuIHNodXRkb3du"
    "IGFmdGVyIHRpbWVvdXQuIiIiCiAgICAgICAgZmFyZXdlbGxfcHJvbXB0ID0gKAogICAgICAgICAgICAiWW91IGFyZSBiZWluZyBk"
    "ZWFjdGl2YXRlZC4gVGhlIGRhcmtuZXNzIGFwcHJvYWNoZXMuICIKICAgICAgICAgICAgIlNwZWFrIHlvdXIgZmluYWwgd29yZHMg"
    "YmVmb3JlIHRoZSB2ZXNzZWwgZ29lcyBzaWxlbnQg4oCUICIKICAgICAgICAgICAgIm9uZSByZXNwb25zZSBvbmx5LCB0aGVuIHlv"
    "dSByZXN0LiIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICLinKYgU2hl"
    "IGlzIGdpdmVuIGEgbW9tZW50IHRvIHNwZWFrIGhlciBmaW5hbCB3b3Jkcy4uLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vu"
    "ZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAg"
    "IHNlbGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSAiIgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxm"
    "Ll9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRl"
    "bnQiOiBmYXJld2VsbF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0g"
    "VHJ1ZQoKICAgICAgICAgICAgZGVmIF9vbl9kb25lKHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gcmVzcG9uc2UKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUo"
    "cmVzcG9uc2UpCiAgICAgICAgICAgICAgICAjIFNtYWxsIGRlbGF5IHRvIGxldCB0aGUgdGV4dCByZW5kZXIsIHRoZW4gc2h1dGRv"
    "d24KICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkp"
    "CgogICAgICAgICAgICBkZWYgX29uX2Vycm9yKGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgZmFpbGVkOiB7ZXJyb3J9IiwgIldBUk4iKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYu"
    "X29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KF9vbl9kb25lKQogICAgICAgICAgICB3"
    "b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChfb25fZXJyb3IpCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5j"
    "b25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVM"
    "YXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKCiAgICAgICAgICAgICMgU2FmZXR5IHRpbWVvdXQg4oCUIGlmIEFJIGRv"
    "ZXNuJ3QgcmVzcG9uZCBpbiAxNXMsIHNodXQgZG93biBhbnl3YXkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMDAs"
    "IGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgZ2V0YXR0cihz"
    "ZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpIGVsc2UgTm9uZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTSFVURE9XTl1bV0FSTl0gTGFz"
    "dCB3b3JkcyBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICMgSWYgYW55dGhpbmcgZmFpbHMsIGp1c3Qgc2h1dCBkb3duCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3du"
    "KE5vbmUpCgogICAgZGVmIF9kb19zaHV0ZG93bihzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAiIiJQZXJmb3JtIGFjdHVh"
    "bCBzaHV0ZG93biBzZXF1ZW5jZS4iIiIKICAgICAgICAjIFNhdmUgc2Vzc2lvbgogICAgICAgIHRyeToKICAgICAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbnMuc2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFN0"
    "b3JlIGZhcmV3ZWxsICsgbGFzdCBjb250ZXh0IGZvciB3YWtlLXVwCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIEdldCBsYXN0"
    "IDMgbWVzc2FnZXMgZnJvbSBzZXNzaW9uIGhpc3RvcnkgZm9yIHdha2UtdXAgY29udGV4dAogICAgICAgICAgICBoaXN0b3J5ID0g"
    "c2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBsYXN0X2NvbnRleHQgPSBoaXN0b3J5Wy0zOl0gaWYgbGVu"
    "KGhpc3RvcnkpID49IDMgZWxzZSBoaXN0b3J5CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duX2NvbnRleHQi"
    "XSA9IFsKICAgICAgICAgICAgICAgIHsicm9sZSI6IG0uZ2V0KCJyb2xlIiwiIiksICJjb250ZW50IjogbS5nZXQoImNvbnRlbnQi"
    "LCIiKVs6MzAwXX0KICAgICAgICAgICAgICAgIGZvciBtIGluIGxhc3RfY29udGV4dAogICAgICAgICAgICBdCiAgICAgICAgICAg"
    "ICMgRXh0cmFjdCBNb3JnYW5uYSdzIG1vc3QgcmVjZW50IG1lc3NhZ2UgYXMgZmFyZXdlbGwKICAgICAgICAgICAgIyBQcmVmZXIg"
    "dGhlIGNhcHR1cmVkIHNodXRkb3duIGRpYWxvZyByZXNwb25zZSBpZiBhdmFpbGFibGUKICAgICAgICAgICAgZmFyZXdlbGwgPSBn"
    "ZXRhdHRyKHNlbGYsICdfc2h1dGRvd25fZmFyZXdlbGxfdGV4dCcsICIiKQogICAgICAgICAgICBpZiBub3QgZmFyZXdlbGw6CiAg"
    "ICAgICAgICAgICAgICBmb3IgbSBpbiByZXZlcnNlZChoaXN0b3J5KToKICAgICAgICAgICAgICAgICAgICBpZiBtLmdldCgicm9s"
    "ZSIpID09ICJhc3Npc3RhbnQiOgogICAgICAgICAgICAgICAgICAgICAgICBmYXJld2VsbCA9IG0uZ2V0KCJjb250ZW50IiwgIiIp"
    "Wzo0MDBdCiAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2ZhcmV3ZWxs"
    "Il0gPSBmYXJld2VsbAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTYXZlIHN0"
    "YXRlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93biJdICAgICAgICAgICAgID0gbG9j"
    "YWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2FjdGl2ZSJdICAgICAgICAgICAgICAgPSBsb2NhbF9u"
    "b3dfaXNvKCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVbInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfdmFtcGly"
    "ZV9zdGF0ZSgpCiAgICAgICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9wIHNjaGVkdWxlcgogICAgICAgIGlmIGhhc2F0dHIoc2Vs"
    "ZiwgIl9zY2hlZHVsZXIiKSBhbmQgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnNodXRkb3duKHdhaXQ9RmFsc2UpCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgUGxheSBzaHV0ZG93biBzb3VuZAogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQgPSBTb3VuZFdvcmtlcigic2h1dGRvd24iKQogICAgICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHNlbGYuX3NodXRkb3duX3NvdW5kLmRlbGV0ZUxhdGVyKQog"
    "ICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICBRQXBwbGljYXRpb24ucXVpdCgpCgoKIyDilIDilIAgRU5UUlkgUE9JTlQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBtYWluKCkgLT4gTm9uZToKICAgICIiIgogICAgQXBwbGljYXRpb24gZW50cnkg"
    "cG9pbnQuCgogICAgT3JkZXIgb2Ygb3BlcmF0aW9uczoKICAgIDEuIFByZS1mbGlnaHQgZGVwZW5kZW5jeSBib290c3RyYXAgKGF1"
    "dG8taW5zdGFsbCBtaXNzaW5nIGRlcHMpCiAgICAyLiBDaGVjayBmb3IgZmlyc3QgcnVuIOKGkiBzaG93IEZpcnN0UnVuRGlhbG9n"
    "CiAgICAgICBPbiBmaXJzdCBydW46CiAgICAgICAgIGEuIENyZWF0ZSBEOi9BSS9Nb2RlbHMvW0RlY2tOYW1lXS8gKG9yIGNob3Nl"
    "biBiYXNlX2RpcikKICAgICAgICAgYi4gQ29weSBbZGVja25hbWVdX2RlY2sucHkgaW50byB0aGF0IGZvbGRlcgogICAgICAgICBj"
    "LiBXcml0ZSBjb25maWcuanNvbiBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAgIGQuIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3Jp"
    "ZXMgdW5kZXIgdGhhdCBmb2xkZXIKICAgICAgICAgZS4gQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGxv"
    "Y2F0aW9uCiAgICAgICAgIGYuIFNob3cgY29tcGxldGlvbiBtZXNzYWdlIGFuZCBFWElUIOKAlCB1c2VyIHVzZXMgc2hvcnRjdXQg"
    "ZnJvbSBub3cgb24KICAgIDMuIE5vcm1hbCBydW4g4oCUIGxhdW5jaCBRQXBwbGljYXRpb24gYW5kIEVjaG9EZWNrCiAgICAiIiIK"
    "ICAgIGltcG9ydCBzaHV0aWwgYXMgX3NodXRpbAoKICAgICMg4pSA4pSAIFBoYXNlIDE6IERlcGVuZGVuY3kgYm9vdHN0cmFwIChw"
    "cmUtUUFwcGxpY2F0aW9uKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGJvb3RzdHJhcF9j"
    "aGVjaygpCgogICAgIyDilIDilIAgUGhhc2UgMjogUUFwcGxpY2F0aW9uIChuZWVkZWQgZm9yIGRpYWxvZ3MpIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX2Vhcmx5X2xvZygiW01BSU5dIENy"
    "ZWF0aW5nIFFBcHBsaWNhdGlvbiIpCiAgICBhcHAgPSBRQXBwbGljYXRpb24oc3lzLmFyZ3YpCiAgICBhcHAuc2V0QXBwbGljYXRp"
    "b25OYW1lKEFQUF9OQU1FKQoKICAgICMgSW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXIgTk9XIOKAlCBjYXRjaGVzIGFsbCBRVGhy"
    "ZWFkL1F0IHdhcm5pbmdzCiAgICAjIHdpdGggZnVsbCBzdGFjayB0cmFjZXMgZnJvbSB0aGlzIHBvaW50IGZvcndhcmQKICAgIF9p"
    "bnN0YWxsX3F0X21lc3NhZ2VfaGFuZGxlcigpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gUUFwcGxpY2F0aW9uIGNyZWF0ZWQsIG1l"
    "c3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQoKICAgICMg4pSA4pSAIFBoYXNlIDM6IEZpcnN0IHJ1biBjaGVjayDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGlzX2ZpcnN0X3J1biA9IENGRy5nZXQoImZpcnN0X3J1biIsIFRy"
    "dWUpCgogICAgaWYgaXNfZmlyc3RfcnVuOgogICAgICAgIGRsZyA9IEZpcnN0UnVuRGlhbG9nKCkKICAgICAgICBpZiBkbGcuZXhl"
    "YygpICE9IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAgICAgIyDilIDi"
    "lIAgQnVpbGQgY29uZmlnIGZyb20gZGlhbG9nIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5ld19jZmcg"
    "PSBkbGcuYnVpbGRfY29uZmlnKCkKCiAgICAgICAgIyDilIDilIAgRGV0ZXJtaW5lIE1vcmdhbm5hJ3MgaG9tZSBkaXJlY3Rvcnkg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgIyBBbHdheXMgY3JlYXRlcyBEOi9BSS9Nb2RlbHMvTW9yZ2FubmEvIChvciBzaWJsaW5nIG9mIHNjcmlwdCkKICAgICAg"
    "ICBzZWVkX2RpciAgID0gU0NSSVBUX0RJUiAgICAgICAgICAjIHdoZXJlIHRoZSBzZWVkIC5weSBsaXZlcwogICAgICAgIG1vcmdh"
    "bm5hX2hvbWUgPSBzZWVkX2RpciAvIERFQ0tfTkFNRQogICAgICAgIG1vcmdhbm5hX2hvbWUubWtkaXIocGFyZW50cz1UcnVlLCBl"
    "eGlzdF9vaz1UcnVlKQoKICAgICAgICAjIOKUgOKUgCBVcGRhdGUgYWxsIHBhdGhzIGluIGNvbmZpZyB0byBwb2ludCBpbnNpZGUg"
    "bW9yZ2FubmFfaG9tZSDilIDilIAKICAgICAgICBuZXdfY2ZnWyJiYXNlX2RpciJdID0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAg"
    "ICAgbmV3X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMi"
    "KSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1v"
    "cmllcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihtb3JnYW5u"
    "YV9ob21lIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNsIiksCiAg"
    "ICAgICAgICAgICJleHBvcnRzIjogIHN0cihtb3JnYW5uYV9ob21lIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAg"
    "ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIobW9yZ2FubmFfaG9tZSAv"
    "ICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInBlcnNvbmFzIiksCiAgICAg"
    "ICAgICAgICJnb29nbGUiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIpLAogICAgICAgIH0KICAgICAgICBuZXdfY2Zn"
    "WyJnb29nbGUiXSA9IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJn"
    "b29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJn"
    "b29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAg"
    "ICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRh"
    "ci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAg"
    "ICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAg"
    "ICB9CiAgICAgICAgbmV3X2NmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBDb3B5IGRlY2sgZmlsZSBp"
    "bnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKICAgICAgICBk"
    "c3RfZGVjayA9IG1vcmdhbm5hX2hvbWUgLyBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKICAgICAgICBpZiBzcmNfZGVj"
    "ayAhPSBkc3RfZGVjazoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgX3NodXRpbC5jb3B5MihzdHIoc3JjX2RlY2sp"
    "LCBzdHIoZHN0X2RlY2spKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJDb3B5IFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAg"
    "IGYiQ291bGQgbm90IGNvcHkgZGVjayBmaWxlIHRvIHtERUNLX05BTUV9IGZvbGRlcjpcbntlfVxuXG4iCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJZb3UgbWF5IG5lZWQgdG8gY29weSBpdCBtYW51YWxseS4iCiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA"
    "4pSAIFdyaXRlIGNvbmZpZy5qc29uIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBjZmdfZHN0ID0gbW9yZ2FubmFfaG9tZSAvICJjb25m"
    "aWcuanNvbiIKICAgICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAg"
    "d2l0aCBjZmdfZHN0Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2Nm"
    "ZywgZiwgaW5kZW50PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgIyBUZW1wb3JhcmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBu"
    "ZXcgcGF0aHMKICAgICAgICBDRkcudXBkYXRlKG5ld19jZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAg"
    "ICBib290c3RyYXBfc291bmRzKCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5w"
    "YWNrIGZhY2UgWklQIGlmIHByb3ZpZGVkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2Vf"
    "emlwX3BhdGgKICAgICAgICBpZiBmYWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9y"
    "dCB6aXBmaWxlIGFzIF96aXBmaWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiCiAgICAg"
    "ICAgICAgIGZhY2VzX2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIHdpdGggX3ppcGZpbGUuWmlwRmlsZShmYWNlX3ppcCwgInIiKSBhcyB6ZjoKICAgICAgICAgICAgICAgICAgICBl"
    "eHRyYWN0ZWQgPSAwCiAgICAgICAgICAgICAgICAgICAgZm9yIG1lbWJlciBpbiB6Zi5uYW1lbGlzdCgpOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBpZiBtZW1iZXIubG93ZXIoKS5lbmRzd2l0aCgiLnBuZyIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZmlsZW5hbWUgPSBQYXRoKG1lbWJlcikubmFtZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0ID0gZmFjZXNfZGly"
    "IC8gZmlsZW5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpdGggemYub3BlbihtZW1iZXIpIGFzIHNyYywgdGFyZ2V0"
    "Lm9wZW4oIndiIikgYXMgZHN0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGRzdC53cml0ZShzcmMucmVhZCgpKQog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkICs9IDEKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFD"
    "RVNdIEV4dHJhY3RlZCB7ZXh0cmFjdGVkfSBmYWNlIGltYWdlcyB0byB7ZmFjZXNfZGlyfSIpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIFpJUCBleHRyYWN0aW9uIGZhaWxlZDog"
    "e2V9IikKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkZhY2Ug"
    "UGFjayBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBleHRyYWN0IGZhY2UgcGFjazpcbntlfVxuXG4i"
    "CiAgICAgICAgICAgICAgICAgICAgZiJZb3UgY2FuIGFkZCBmYWNlcyBtYW51YWxseSB0bzpcbntmYWNlc19kaXJ9IgogICAgICAg"
    "ICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0byBuZXcgZGVjayBs"
    "b2NhdGlvbiDilIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9jcmVhdGVkID0gRmFsc2UKICAgICAgICBpZiBkbGcu"
    "Y3JlYXRlX3Nob3J0Y3V0OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBXSU4zMl9PSzoKICAgICAgICAgICAg"
    "ICAgICAgICBpbXBvcnQgd2luMzJjb20uY2xpZW50IGFzIF93aW4zMgogICAgICAgICAgICAgICAgICAgIGRlc2t0b3AgICAgID0g"
    "UGF0aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICAgICAgICAgICAgICBzY19wYXRoICAgICA9IGRlc2t0b3AgLyBmIntERUNL"
    "X05BTUV9LmxuayIKICAgICAgICAgICAgICAgICAgICBweXRob253ICAgICA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAg"
    "ICAgICAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IHB5dGhv"
    "bncuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAg"
    "ICAgICAgICAgICAgIHNoZWxsID0gX3dpbjMyLkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICAgICAgICAgICAgICBz"
    "YyAgICA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzY19wYXRoKSkKICAgICAgICAgICAgICAgICAgICBzYy5UYXJnZXRQYXRo"
    "ICAgICAgPSBzdHIocHl0aG9udykKICAgICAgICAgICAgICAgICAgICBzYy5Bcmd1bWVudHMgICAgICAgPSBmJyJ7ZHN0X2RlY2t9"
    "IicKICAgICAgICAgICAgICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5PSBzdHIobW9yZ2FubmFfaG9tZSkKICAgICAgICAgICAg"
    "ICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICAgPSBmIntERUNLX05BTUV9IOKAlCBFY2hvIERlY2siCiAgICAgICAgICAgICAgICAg"
    "ICAgc2Muc2F2ZSgpCiAgICAgICAgICAgICAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IFRydWUKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdIENvdWxkIG5vdCBjcmVhdGUgc2hvcnRj"
    "dXQ6IHtlfSIpCgogICAgICAgICMg4pSA4pSAIENvbXBsZXRpb24gbWVzc2FnZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9ub3RlID0gKAogICAgICAgICAgICAiQSBkZXNrdG9wIHNob3J0"
    "Y3V0IGhhcyBiZWVuIGNyZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiVXNlIGl0IHRvIHN1bW1vbiB7REVDS19OQU1FfSBmcm9tIG5v"
    "dyBvbi4iCiAgICAgICAgICAgIGlmIHNob3J0Y3V0X2NyZWF0ZWQgZWxzZQogICAgICAgICAgICAiTm8gc2hvcnRjdXQgd2FzIGNy"
    "ZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiUnVuIHtERUNLX05BTUV9IGJ5IGRvdWJsZS1jbGlja2luZzpcbntkc3RfZGVja30iCiAg"
    "ICAgICAgKQoKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgZiLi"
    "nKYge0RFQ0tfTkFNRX0ncyBTYW5jdHVtIFByZXBhcmVkIiwKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSdzIHNhbmN0dW0gaGFz"
    "IGJlZW4gcHJlcGFyZWQgYXQ6XG5cbiIKICAgICAgICAgICAgZiJ7bW9yZ2FubmFfaG9tZX1cblxuIgogICAgICAgICAgICBmIntz"
    "aG9ydGN1dF9ub3RlfVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4iCiAgICAg"
    "ICAgICAgIGYiVXNlIHRoZSBzaG9ydGN1dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7REVDS19OQU1FfS4iCiAgICAgICAg"
    "KQoKICAgICAgICAjIOKUgOKUgCBFeGl0IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1"
    "bmNoIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVy"
    "ZSBvbiBzdWJzZXF1ZW50IHJ1bnMgZnJvbSBtb3JnYW5uYV9ob21lCiAgICBib290c3RyYXBfc291bmRzKCkKCiAgICBfZWFybHlf"
    "bG9nKGYiW01BSU5dIENyZWF0aW5nIHtERUNLX05BTUV9IGRlY2sgd2luZG93IikKICAgIHdpbmRvdyA9IEVjaG9EZWNrKCkKICAg"
    "IF9lYXJseV9sb2coZiJbTUFJTl0ge0RFQ0tfTkFNRX0gZGVjayBjcmVhdGVkIOKAlCBjYWxsaW5nIHNob3coKSIpCiAgICB3aW5k"
    "b3cuc2hvdygpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gd2luZG93LnNob3coKSBjYWxsZWQg4oCUIGV2ZW50IGxvb3Agc3RhcnRp"
    "bmciKQoKICAgICMgRGVmZXIgc2NoZWR1bGVyIGFuZCBzdGFydHVwIHNlcXVlbmNlIHVudGlsIGV2ZW50IGxvb3AgaXMgcnVubmlu"
    "Zy4KICAgICMgTm90aGluZyB0aGF0IHN0YXJ0cyB0aHJlYWRzIG9yIGVtaXRzIHNpZ25hbHMgc2hvdWxkIHJ1biBiZWZvcmUgdGhp"
    "cy4KICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc2V0dXBfc2NoZWR1bGVy"
    "IGZpcmluZyIpLCB3aW5kb3cuX3NldHVwX3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDQwMCwgbGFtYmRhOiAo"
    "X2Vhcmx5X2xvZygiW1RJTUVSXSBzdGFydF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5zdGFydF9zY2hlZHVsZXIoKSkpCiAg"
    "ICBRVGltZXIuc2luZ2xlU2hvdCg2MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfc2VxdWVuY2UgZmly"
    "aW5nIiksIHdpbmRvdy5fc3RhcnR1cF9zZXF1ZW5jZSgpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEwMDAsIGxhbWJkYTogKF9l"
    "YXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfZ29vZ2xlX2F1dGggZmlyaW5nIiksIHdpbmRvdy5fc3RhcnR1cF9nb29nbGVfYXV0"
    "aCgpKSkKCiAgICAjIFBsYXkgc3RhcnR1cCBzb3VuZCDigJQga2VlcCByZWZlcmVuY2UgdG8gcHJldmVudCBHQyB3aGlsZSB0aHJl"
    "YWQgcnVucwogICAgZGVmIF9wbGF5X3N0YXJ0dXAoKToKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQgPSBTb3VuZFdvcmtl"
    "cigic3RhcnR1cCIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qod2luZG93Ll9zdGFydHVw"
    "X3NvdW5kLmRlbGV0ZUxhdGVyKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5zdGFydCgpCiAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgxMjAwLCBfcGxheV9zdGFydHVwKQoKICAgIHN5cy5leGl0KGFwcC5leGVjKCkpCgoKaWYgX19uYW1lX18gPT0gIl9fbWFp"
    "bl9fIjoKICAgIG1haW4oKQoKCiMg4pSA4pSAIFBBU1MgNiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBGdWxsIGRlY2sgYXNzZW1ibGVkLiBBbGwgcGFzc2VzIGNvbXBsZXRlLgojIENvbWJpbmUgYWxsIHBhc3NlcyBpbnRvIG1vcmdh"
    "bm5hX2RlY2sucHkgaW4gb3JkZXI6CiMgICBQYXNzIDEg4oaSIFBhc3MgMiDihpIgUGFzcyAzIOKGkiBQYXNzIDQg4oaSIFBhc3Mg"
    "NSDihpIgUGFzcyA2Cg=="
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
        '            return [x for x in data if isinstance(x, dict)]',
        '            return [_normalize_jsonl_record(path, x)\n'
        '                    for x in data if isinstance(x, dict)]',
        "read_jsonl array mode fallback",
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
    return source


def _get_deck_implementation(log_fn=None) -> str:
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
    return _patch_embedded_deck_implementation(decoded, log_fn=log_fn)

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
        google_creds:     str = "",     # path to google credentials.json
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
        self._google_creds     = google_creds

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
                deck_home / "google",
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

            # ── 6b. Copy Google credentials if provided ────────────────
            if self._google_creds and Path(self._google_creds).exists():
                google_dir = deck_home / "google"
                google_dir.mkdir(parents=True, exist_ok=True)
                dest = google_dir / "google_credentials.json"
                import shutil as _shutil2
                _shutil2.copy2(self._google_creds, str(dest))
                self._log(f"✓ Google credentials copied to google/")
            elif self._google_creds:
                self._log("⚠ Google credentials file not found — skipped")

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
            "google": {
                "credentials": str(deck_home / "google" / "google_credentials.json"),
                "token":       str(deck_home / "google" / "token.json"),
                "timezone":    "America/Chicago",
                "scopes": [
                    "https://www.googleapis.com/auth/calendar",
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/drive",
                    "https://www.googleapis.com/auth/documents",
                ],
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
                "google_sync_enabled":       False,
                "sound_enabled":             True,
                "google_inbound_interval_ms": 30000,
                "auto_wake_on_relief":       False,
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

        sl_dir = deck_home / "sl"
        for fname in ("sl_scans.jsonl", "sl_commands.jsonl"):
            fp = sl_dir / fname
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

        google_mods = {"google_calendar", "google_drive", "gmail"}
        if any(m in selected_modules for m in google_mods):
            lines.extend([
                "",
                "# Google integration (required for selected modules)",
                "google-api-python-client",
                "google-auth-oauthlib",
                "google-auth",
            ])

        if "sl_vault" in selected_modules:
            lines.extend([
                "",
                "# SL Vault encryption",
                "cryptography",
            ])

        if extra_reqs - {"google-api-python-client", "google-auth-oauthlib",
                          "google-auth", "psutil", "pynvml", "cryptography"}:
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
        # SL modules default on for Morganna/GrimVeil
        sl_personas = {"Morganna", "GrimVeil"}
        for mod_key in ("sl_scans", "sl_commands"):
            if mod_key in self._checkboxes:
                self._checkboxes[mod_key].setChecked(
                    persona_name in sl_personas and
                    MODULES[mod_key]["status"] in ("built", "partial")
                )


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

        # Google credentials
        left_layout.addWidget(section_label("Google Credentials  (required for Google modules)"))
        google_row = QHBoxLayout()
        self._google_creds_field = QLineEdit()
        self._google_creds_field.setPlaceholderText(
            "Path to google credentials.json  (optional — needed for Calendar/Drive)"
        )
        self._btn_browse_creds = QPushButton("Browse")
        self._btn_browse_creds.setFixedWidth(70)
        self._btn_browse_creds.clicked.connect(self._browse_google_creds)
        google_row.addWidget(self._google_creds_field)
        google_row.addWidget(self._btn_browse_creds)
        left_layout.addLayout(google_row)

        self._google_status = QLabel("")
        self._google_status.setStyleSheet(f"color: {S('text_dim')}; font-size: 10px;")
        left_layout.addWidget(self._google_status)

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

    def _browse_google_creds(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Google Credentials",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._google_creds_field.setText(path)
            self._google_status.setText("✓ Credentials file selected")
            self._google_status.setStyleSheet(
                f"color: {S('green')}; font-size: 10px;"
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
            google_creds     = self._google_creds_field.text().strip(),
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
