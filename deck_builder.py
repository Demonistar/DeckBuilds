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
    "b3JkZXIiOiBbXSwKICAgICAgICAiZmlyc3RfcnVuIjogVHJ1ZSwKICAgIH0KCmRlZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAg"
    "ICAiIiJMb2FkIGNvbmZpZy5qc29uLiBSZXR1cm5zIGRlZmF1bHQgaWYgbWlzc2luZyBvciBjb3JydXB0LiIiIgogICAgaWYgbm90"
    "IENPTkZJR19QQVRILmV4aXN0cygpOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQogICAgdHJ5OgogICAgICAgIHdp"
    "dGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxv"
    "YWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygpCgpkZWYgc2F2ZV9jb25m"
    "aWcoY2ZnOiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29uZmlnLmpzb24uIiIiCiAgICBDT05GSUdfUEFUSC5wYXJlbnQu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBDT05GSUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9"
    "InV0Zi04IikgYXMgZjoKICAgICAgICBqc29uLmR1bXAoY2ZnLCBmLCBpbmRlbnQ9MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxl"
    "IGxldmVsIOKAlCBldmVyeXRoaW5nIGJlbG93IHJlYWRzIGZyb20gQ0ZHCkNGRyA9IGxvYWRfY29uZmlnKCkKX2Vhcmx5X2xvZyhm"
    "IltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NGRy5nZXQoJ2ZpcnN0X3J1bicpfSwgbW9kZWxfdHlwZT17Q0ZH"
    "LmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0iKQoKX0RFRkFVTFRfUEFUSFM6IGRpY3Rbc3RyLCBQYXRoXSA9IHsKICAgICJm"
    "YWNlcyI6ICAgIFNDUklQVF9ESVIgLyAiRmFjZXMiLAogICAgInNvdW5kcyI6ICAgU0NSSVBUX0RJUiAvICJzb3VuZHMiLAogICAg"
    "Im1lbW9yaWVzIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAgICAic2Vzc2lvbnMiOiBTQ1JJUFRfRElSIC8gInNlc3Npb25z"
    "IiwKICAgICJzbCI6ICAgICAgIFNDUklQVF9ESVIgLyAic2wiLAogICAgImV4cG9ydHMiOiAgU0NSSVBUX0RJUiAvICJleHBvcnRz"
    "IiwKICAgICJsb2dzIjogICAgIFNDUklQVF9ESVIgLyAibG9ncyIsCiAgICAiYmFja3VwcyI6ICBTQ1JJUFRfRElSIC8gImJhY2t1"
    "cHMiLAogICAgInBlcnNvbmFzIjogU0NSSVBUX0RJUiAvICJwZXJzb25hcyIsCiAgICAiZ29vZ2xlIjogICBTQ1JJUFRfRElSIC8g"
    "Imdvb2dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpIC0+IE5vbmU6CiAgICAiIiIKICAgIFNlbGYtaGVhbCBv"
    "bGRlciBjb25maWcuanNvbiBmaWxlcyBtaXNzaW5nIHJlcXVpcmVkIHBhdGgga2V5cy4KICAgIEFkZHMgbWlzc2luZyBwYXRoIGtl"
    "eXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnRpYWwvdG9rZW4gbG9jYXRpb25zLAogICAgdGhlbiBwZXJzaXN0cyBjb25m"
    "aWcuanNvbiBpZiBhbnl0aGluZyBjaGFuZ2VkLgogICAgIiIiCiAgICBjaGFuZ2VkID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNl"
    "dGRlZmF1bHQoInBhdGhzIiwge30pCiAgICBmb3Iga2V5LCBkZWZhdWx0X3BhdGggaW4gX0RFRkFVTFRfUEFUSFMuaXRlbXMoKToK"
    "ICAgICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZGVmYXVsdF9wYXRoKQog"
    "ICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGdvb2dsZV9jZmcgPSBDRkcuc2V0ZGVmYXVsdCgiZ29vZ2xlIiwge30pCiAg"
    "ICBnb29nbGVfcm9vdCA9IFBhdGgocGF0aHMuZ2V0KCJnb29nbGUiLCBzdHIoX0RFRkFVTFRfUEFUSFNbImdvb2dsZSJdKSkpCiAg"
    "ICBkZWZhdWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIikKICAgIGRlZmF1bHRf"
    "dG9rZW4gPSBzdHIoZ29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIpCiAgICBjcmVkc192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQo"
    "ImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpcCgpCiAgICB0b2tlbl92YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIp"
    "KS5zdHJpcCgpCiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJjb25maWciIGluIGNyZWRzX3ZhbCBhbmQgImdvb2dsZV9jcmVk"
    "ZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdvb2dsZV9jZmdbImNyZWRlbnRpYWxzIl0gPSBkZWZhdWx0X2Ny"
    "ZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgIGlmIG5vdCB0b2tlbl92YWw6CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9rZW4i"
    "XSA9IGRlZmF1bHRfdG9rZW4KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25m"
    "aWcoQ0ZHKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJv"
    "bSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2JqZWN0IHdpdGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBh"
    "dGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZhbHVlID0gcGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAg"
    "IHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQoa2V5KQogICAgaWYgZmFsbGJhY2s6"
    "CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAgICAgICByZXR1cm4gZmFsbGJhY2sKICAgIHJldHVybiBTQ1JJ"
    "UFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKUgOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2"
    "ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFSWSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BB"
    "TkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJlIGluamVjdGVkIGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5"
    "IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml2ZWQgZnJvbSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgoj"
    "IFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9ycyB0byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhl"
    "IFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAgIyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGln"
    "aGxpZ2h0cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJz"
    "CkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAgIyBtYWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09M"
    "RF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4OCIgIyBkaW0gc2Vjb25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAg"
    "ICAgICAgIyBlbXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElNICAgICAgICAgIyBzZWNvbmRh"
    "cnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElNICA9IENfVEVYVF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRh"
    "cnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAgICAgICAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVh"
    "ZHkgaW5qZWN0ZWQpCkNfQkcyICAgICAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JH"
    "MyAgICAgICAgID0gQ19QQU5FTCAgICAgICAgICAgICMgdGVydGlhcnkvaW5wdXQgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3Rl"
    "ZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAgICAgICAjIGVycm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwK"
    "Q19QVVJQTEUgICAgICA9ICcjODg1NWNjJyAgICAgICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExF"
    "X0RJTSAgPSAnIzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjNDRh"
    "YTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5pdmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAg"
    "ICAgICAgIyBpbmZvIHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZvbnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQg"
    "bmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNLX0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3Ry"
    "aXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChmb3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09M"
    "T1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAgInNtdWciOiAgICAgICBDX0dPTEQs"
    "CiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZlZCI6ICAgQ19HT0xELAogICAgImhhcHB5IjogICAgICBDX0dP"
    "TEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5pY2tlZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAg"
    "ICBDX0NSSU1TT04sCiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAg"
    "ImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAgICAgICIjY2M2NjIyIiwKICAgICJodW1pbGlhdGVkIjogIiNj"
    "YzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAgICAicGxvdHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3Bp"
    "Y2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZpb3VzIjogICAgQ19QVVJQTEUsCiAgICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAog"
    "ICAgImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAgQ19URVhUX0RJTSwKfQoKIyDilIDilIAgREVDT1JB"
    "VElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUlVORVMgaXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRo"
    "ZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMgRmFjZSBpbWFnZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0Vf"
    "UFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRocy5mYWNlcwpGQUNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAg"
    "ICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVG"
    "SVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6"
    "ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TbXVnLnBuZyIsCiAgICAiY29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJu"
    "ZWQucG5nIiwKICAgICJzYWQiOiAgICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGlldmVkLnBuZyIsCiAgICAiaW1wcmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNz"
    "ZWQucG5nIiwKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pbGlhdGVkIjog"
    "ZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lv"
    "dXMucG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjog"
    "IGYie0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAiYW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5w"
    "bmciLAogICAgInBsb3R0aW5nIjogICBmIntGQUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7"
    "RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAg"
    "ICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHkucG5nIiwKICAgICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVG"
    "SVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVudmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5U"
    "SU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmVkLCBzYWQsIHJlbGlldmVk"
    "LCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNpb3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0"
    "aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksIGZsaXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0g"
    "UFJPTVBUIOKAlCBpbmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFscmVhZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8"
    "PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCByZWRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNU"
    "WUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxFID0gZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFj"
    "a2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlM"
    "WX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07"
    "CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZh"
    "bWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlv"
    "bi1iYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjog"
    "e0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVy"
    "LXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBw"
    "YWRkaW5nOiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAg"
    "IGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hCdXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NS"
    "SU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9y"
    "ZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAg"
    "ICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAyMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1"
    "c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJ"
    "R0hUfTsKfX0KUVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9OwogICAgYm9yZGVy"
    "LWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0dG9uOmRpc2FibGVkIHt7CiAgICBiYWNr"
    "Z3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9E"
    "SU19Owp9fQpRU2Nyb2xsQmFyOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4OwogICAg"
    "Ym9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05f"
    "RElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBi"
    "YWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1s"
    "aW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdldDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0NfQkcyfTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElN"
    "fTsKICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6"
    "IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6"
    "IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklN"
    "U09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09M"
    "RF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAg"
    "ICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZv"
    "bnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2Vs"
    "ZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFI"
    "ZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05U"
    "X0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAx"
    "cHg7Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZP"
    "TlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRlcjogbm9uZTsKfX0KUUNoZWNrQm94IHt7CiAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xv"
    "cjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVk"
    "IGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxsZWQgb24gc3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxz"
    "ZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxzbyBtaWdyYXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVd"
    "X01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgogICAgZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMi"
    "KSwKICAgICAgICBjZmdfcGF0aCgic291bmRzIiksCiAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3Bh"
    "dGgoInNlc3Npb25zIiksCiAgICAgICAgY2ZnX3BhdGgoInNsIiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAg"
    "ICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJiYWNrdXBzIiksCiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFz"
    "IiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJleHBvcnRzIiwKICAg"
    "IF0KICAgIGZvciBkIGluIGRpcnM6CiAgICAgICAgZC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgIyBD"
    "cmVhdGUgZW1wdHkgSlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBleGlzdAogICAgbWVtb3J5X2RpciA9IGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpCiAgICBmb3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29ubCIsICJtZW1vcmllcy5qc29ubCIsICJ0YXNrcy5qc29ubCIs"
    "CiAgICAgICAgICAgICAgICAgICJsZXNzb25zX2xlYXJuZWQuanNvbmwiLCAicGVyc29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAg"
    "ICAgZnAgPSBtZW1vcnlfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRl"
    "X3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGlyID0gY2ZnX3BhdGgoInNsIikKICAgIGZvciBmbmFtZSBpbiAo"
    "InNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25sIik6CiAgICAgICAgZnAgPSBzbF9kaXIgLyBmbmFtZQogICAgICAg"
    "IGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAgICAgICAgZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBz"
    "ZXNzaW9uc19kaXIgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgaWR4ID0gc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXgu"
    "anNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3RzKCk6CiAgICAgICAgaWR4LndyaXRlX3RleHQoanNvbi5kdW1wcyh7InNlc3Npb25z"
    "IjogW119LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc3RhdGVfcGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUu"
    "anNvbiIKICAgIGlmIG5vdCBzdGF0ZV9wYXRoLmV4aXN0cygpOgogICAgICAgIF93cml0ZV9kZWZhdWx0X3N0YXRlKHN0YXRlX3Bh"
    "dGgpCgogICAgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5kZXguanNvbiIKICAgIGlmIG5vdCBpbmRleF9wYXRoLmV4aXN0"
    "cygpOgogICAgICAgIGluZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyh7InZlcnNpb24iOiBBUFBf"
    "VkVSU0lPTiwgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMH0s"
    "IGluZGVudD0yKSwKICAgICAgICAgICAgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246"
    "IGlmIG9sZCBNb3JnYW5uYV9NZW1vcmllcyBmb2xkZXIgZXhpc3RzLCBtaWdyYXRlIGZpbGVzCiAgICBfbWlncmF0ZV9sZWdhY3lf"
    "ZmlsZXMoKQoKZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICBzdGF0ZSA9IHsKICAgICAg"
    "ICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAi"
    "c2Vzc2lvbl9jb3VudCI6IDAsCiAgICAgICAgImxhc3Rfc3RhcnR1cCI6IE5vbmUsCiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBO"
    "b25lLAogICAgICAgICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAidG90"
    "YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiB7fSwKICAgICAgICAidmFtcGlyZV9zdGF0ZV9h"
    "dF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgIH0KICAgIHBhdGgud3JpdGVfdGV4dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9"
    "MiksIGVuY29kaW5nPSJ1dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkgLT4gTm9uZToKICAgICIiIgogICAgSWYg"
    "b2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpcyBkZXRlY3RlZCwKICAgIG1pZ3JhdGUgZmls"
    "ZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIiIgogICAgIyBUcnkgdG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZl"
    "IHRvIG1vZGVsIHBhdGgKICAgIG1vZGVsX3BhdGggPSBQYXRoKENGR1sibW9kZWwiXS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBu"
    "b3QgbW9kZWxfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KICAgIG9sZF9yb290ID0gbW9kZWxfcGF0aC5wYXJlbnQgLyBm"
    "IntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9yb290LmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIG1p"
    "Z3JhdGlvbnMgPSBbCiAgICAgICAgKG9sZF9yb290IC8gIm1lbW9yaWVzLmpzb25sIiwgICAgICAgICAgIGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpIC8gIm1lbW9yaWVzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gIm1lc3NhZ2VzLmpzb25sIiwgICAgICAgICAg"
    "ICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJ0YXNrcy5qc29u"
    "bCIsICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3Qg"
    "LyAic3RhdGUuanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInN0YXRlLmpzb24iKSwKICAgICAg"
    "ICAob2xkX3Jvb3QgLyAiaW5kZXguanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpz"
    "b24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfc2NhbnMuanNvbmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNs"
    "X3NjYW5zLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX2NvbW1hbmRzLmpzb25sIiwgICAgICAgICBjZmdfcGF0aCgi"
    "c2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAg"
    "ICAgUGF0aChDRkdbImdvb2dsZSJdWyJ0b2tlbiJdKSksCiAgICAgICAgKG9sZF9yb290IC8gImNvbmZpZyIgLyAiZ29vZ2xlX2Ny"
    "ZWRlbnRpYWxzLmpzb24iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIFBhdGgoQ0ZH"
    "WyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJzb3VuZHMiIC8gZiJ7U09VTkRfUFJFRklY"
    "fV9hbGVydC53YXYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJz"
    "b3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiksCiAgICBdCgogICAgZm9yIHNyYywgZHN0IGluIG1pZ3JhdGlv"
    "bnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0LmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICBkc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9y"
    "dCBzaHV0aWwKICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoc3JjKSwgc3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyBNaWdyYXRlIGZhY2UgaW1hZ2VzCiAgICBvbGRfZmFjZXMg"
    "PSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNmZ19wYXRoKCJmYWNlcyIpCiAgICBpZiBvbGRfZmFjZXMuZXhp"
    "c3RzKCk6CiAgICAgICAgZm9yIGltZyBpbiBvbGRfZmFjZXMuZ2xvYigiKi5wbmciKToKICAgICAgICAgICAgZHN0ID0gbmV3X2Zh"
    "Y2VzIC8gaW1nLm5hbWUKICAgICAgICAgICAgaWYgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihpbWcpLCBzdHIo"
    "ZHN0KSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKIyDilIDilIAg"
    "REFURVRJTUUgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGxvY2FsX25vd19pc28oKSAtPiBzdHI6CiAgICBy"
    "ZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKS5pc29mb3JtYXQoKQoKZGVmIHBhcnNlX2lzbyh2YWx1"
    "ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICBpZiBub3QgdmFsdWU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZh"
    "bHVlID0gdmFsdWUuc3RyaXAoKQogICAgdHJ5OgogICAgICAgIGlmIHZhbHVlLmVuZHN3aXRoKCJaIik6CiAgICAgICAgICAgIHJl"
    "dHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0pLnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0YykKICAgICAg"
    "ICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCl9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDogc2V0W3R1cGxlXSA9IHNldCgpCgoKZGVmIF9yZXNvbHZlX2Rl"
    "Y2tfdGltZXpvbmVfbmFtZSgpIC0+IE9wdGlvbmFsW3N0cl06CiAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30p"
    "IGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICBhdXRvX2RldGVjdCA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1l"
    "em9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgb3ZlcnJpZGUgPSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlk"
    "ZSIsICIiKSBvciAiIikuc3RyaXAoKQogICAgaWYgbm90IGF1dG9fZGV0ZWN0IGFuZCBvdmVycmlkZToKICAgICAgICByZXR1cm4g"
    "b3ZlcnJpZGUKICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8KICAgIGlmIGxvY2Fs"
    "X3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICB0el9rZXkgPSBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpCiAg"
    "ICAgICAgaWYgdHpfa2V5OgogICAgICAgICAgICByZXR1cm4gc3RyKHR6X2tleSkKICAgICAgICB0el9uYW1lID0gc3RyKGxvY2Fs"
    "X3R6aW5mbykKICAgICAgICBpZiB0el9uYW1lIGFuZCB0el9uYW1lLnVwcGVyKCkgIT0gIkxPQ0FMIjoKICAgICAgICAgICAgcmV0"
    "dXJuIHR6X25hbWUKICAgIHJldHVybiBOb25lCgoKZGVmIF9sb2NhbF90emluZm8oKToKICAgIHR6X25hbWUgPSBfcmVzb2x2ZV9k"
    "ZWNrX3RpbWV6b25lX25hbWUoKQogICAgaWYgdHpfbmFtZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBab25lSW5m"
    "byh0el9uYW1lKQogICAgICAgIGV4Y2VwdCBab25lSW5mb05vdEZvdW5kRXJyb3I6CiAgICAgICAgICAgIF9lYXJseV9sb2coZiJb"
    "REFURVRJTUVdW1dBUk5dIFVua25vd24gdGltZXpvbmUgb3ZlcnJpZGUgJ3t0el9uYW1lfScsIHVzaW5nIHN5c3RlbSBsb2NhbCB0"
    "aW1lem9uZS4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIHJldHVybiBkYXRldGltZS5u"
    "b3coKS5hc3RpbWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV0YwoKCmRlZiBub3dfZm9yX2NvbXBhcmUoKToKICAgIHJldHVy"
    "biBkYXRldGltZS5ub3coX2xvY2FsX3R6aW5mbygpKQoKCmRlZiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFs"
    "dWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIGlmIGR0X3ZhbHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGlm"
    "IG5vdCBpc2luc3RhbmNlKGR0X3ZhbHVlLCBkYXRldGltZSk6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGxvY2FsX3R6ID0gX2xv"
    "Y2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50emluZm8gaXMgTm9uZToKICAgICAgICBub3JtYWxpemVkID0gZHRfdmFsdWUu"
    "cmVwbGFjZSh0emluZm89bG9jYWxfdHopCiAgICAgICAga2V5ID0gKCJuYWl2ZSIsIGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5v"
    "dCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6CiAgICAgICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBkYXRldGltZSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRl"
    "eHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgX0RBVEVUSU1FX05PUk1BTEla"
    "QVRJT05fTE9HR0VELmFkZChrZXkpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5h"
    "c3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpfbmFtZSA9IHN0cihkdF92YWx1ZS50emluZm8pCiAgICBrZXkgPSAoImF3YXJl"
    "IiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3QgaW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFu"
    "ZCBkdF90el9uYW1lIG5vdCBpbiB7IlVUQyIsIHN0cihsb2NhbF90eil9OgogICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAg"
    "IGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZyb20ge2R0X3R6X25hbWV9IHRv"
    "IGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBhcmlzb25zLiIKICAgICAgICApCiAgICAgICAg"
    "X0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkpCiAgICByZXR1cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9p"
    "c29fZm9yX2NvbXBhcmUodmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIHJldHVybiBub3JtYWxpemVfZGF0ZXRpbWVfZm9y"
    "X2NvbXBhcmUocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250ZXh0KQoKCmRlZiBfdGFza19kdWVfc29ydF9rZXkodGFzazog"
    "ZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoKHRhc2sgb3Ige30pLmdldCgiZHVlX2F0Iikgb3IgKHRhc2sg"
    "b3Ige30pLmdldCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29ydCIpCiAgICBpZiBkdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4g"
    "KDEsIGRhdGV0aW1lLm1heC5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpKQogICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9u"
    "ZSh0aW1lem9uZS51dGMpLCAoKHRhc2sgb3Ige30pLmdldCgidGV4dCIpIG9yICIiKS5sb3dlcigpKQoKCmRlZiBmb3JtYXRfZHVy"
    "YXRpb24oc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgIHRvdGFsID0gbWF4KDAsIGludChzZWNvbmRzKSkKICAgIGRheXMsIHJl"
    "bSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3VycywgcmVtID0gZGl2bW9kKHJlbSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNl"
    "Y3MgPSBkaXZtb2QocmVtLCA2MCkKICAgIHBhcnRzID0gW10KICAgIGlmIGRheXM6ICAgIHBhcnRzLmFwcGVuZChmIntkYXlzfWQi"
    "KQogICAgaWYgaG91cnM6ICAgcGFydHMuYXBwZW5kKGYie2hvdXJzfWgiKQogICAgaWYgbWludXRlczogcGFydHMuYXBwZW5kKGYi"
    "e21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFwcGVuZChmIntzZWNzfXMiKQogICAgcmV0dXJuICIgIi5qb2lu"
    "KHBhcnRzWzozXSkKCiMg4pSA4pSAIE1PT04gUEhBU0UgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDb3JyZWN0ZWQgaWxs"
    "dW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNoZXMgbGFiZWxlZCBwaGFzZS4KCl9LTk9XTl9ORVdfTU9PTiA9"
    "IGRhdGUoMjAwMCwgMSwgNikKX0xVTkFSX0NZQ0xFICAgID0gMjkuNTMwNTg4NjcKCmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1"
    "cGxlW2Zsb2F0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0dXJucyAocGhhc2VfZnJhY3Rpb24sIHBoYXNlX25hbWUsIGls"
    "bHVtaW5hdGlvbl9wY3QpLgogICAgcGhhc2VfZnJhY3Rpb246IDAuMCA9IG5ldyBtb29uLCAwLjUgPSBmdWxsIG1vb24sIDEuMCA9"
    "IG5ldyBtb29uIGFnYWluLgogICAgaWxsdW1pbmF0aW9uX3BjdDogMOKAkzEwMCwgY29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBw"
    "aGFzZS4KICAgICIiIgogICAgZGF5cyAgPSAoZGF0ZS50b2RheSgpIC0gX0tOT1dOX05FV19NT09OKS5kYXlzCiAgICBjeWNsZSA9"
    "IGRheXMgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUgLyBfTFVOQVJfQ1lDTEUKCiAgICBpZiAgIGN5Y2xlIDwgMS44"
    "NTogICBuYW1lID0gIk5FVyBNT09OIgogICAgZWxpZiBjeWNsZSA8IDcuMzg6ICAgbmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAg"
    "ICBlbGlmIGN5Y2xlIDwgOS4yMjogICBuYW1lID0gIkZJUlNUIFFVQVJURVIiCiAgICBlbGlmIGN5Y2xlIDwgMTQuNzc6ICBuYW1l"
    "ID0gIldBWElORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDE2LjYxOiAgbmFtZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5"
    "Y2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDIzLjk5OiAgbmFtZSA9ICJMQVNU"
    "IFFVQVJURVIiCiAgICBlbHNlOiAgICAgICAgICAgICAgICBuYW1lID0gIldBTklORyBDUkVTQ0VOVCIKCiAgICAjIENvcnJlY3Rl"
    "ZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcGVha3MgYXQgZnVsbCBtb29uCiAgICBpbGx1bWluYXRpb24gPSAoMSAtIG1hdGgu"
    "Y29zKDIgKiBtYXRoLnBpICogcGhhc2UpKSAvIDIgKiAxMDAKICAgIHJldHVybiBwaGFzZSwgbmFtZSwgcm91bmQoaWxsdW1pbmF0"
    "aW9uLCAxKQoKX1NVTl9DQUNIRV9EQVRFOiBPcHRpb25hbFtkYXRlXSA9IE5vbmUKX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOOiBP"
    "cHRpb25hbFtpbnRdID0gTm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0dXBsZVtzdHIsIHN0cl0gPSAoIjA2OjAwIiwgIjE4OjMwIikK"
    "CmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpIC0+IHR1cGxlW2Zsb2F0LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29s"
    "dmUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGZyb20gcnVudGltZSBjb25maWcgd2hlbiBhdmFpbGFibGUuCiAgICBGYWxscyBiYWNrIHRv"
    "IHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAgIiIiCiAgICBsYXQgPSBOb25lCiAgICBsb24gPSBOb25lCiAg"
    "ICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkg"
    "ZWxzZSB7fQogICAgICAgIGZvciBrZXkgaW4gKCJsYXRpdHVkZSIsICJsYXQiKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRp"
    "bmdzOgogICAgICAgICAgICAgICAgbGF0ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAg"
    "ICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJsb24iLCAibG5nIik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoK"
    "ICAgICAgICAgICAgICAgIGxvbiA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICBsYXQgPSBOb25lCiAgICAgICAgbG9uID0gTm9uZQoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1l"
    "Lm5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKQog"
    "ICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zmc2V0LnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25l"
    "OgogICAgICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgdHpfb2Zmc2V0X2hvdXJzICogMTUuMCkpCgogICAgaWYgbGF0"
    "IGlzIE5vbmU6CiAgICAgICAgdHpfbmFtZSA9IHN0cihub3dfbG9jYWwudHppbmZvIG9yICIiKQogICAgICAgIHNvdXRoX2hpbnQg"
    "PSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9rZW4gaW4gKCJBdXN0cmFsaWEiLCAiUGFjaWZpYy9BdWNrbGFuZCIsICJBbWVy"
    "aWNhL1NhbnRpYWdvIikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYgc291dGhfaGludCBlbHNlIDM1LjAKCiAgICBsYXQgPSBtYXgo"
    "LTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCBsb24pKQogICAgcmV0dXJuIGxh"
    "dCwgbG9uCgpkZWYgX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyhsb2NhbF9kYXk6IGRhdGUsIGxhdGl0dWRlOiBmbG9hdCwgbG9u"
    "Z2l0dWRlOiBmbG9hdCwgc3VucmlzZTogYm9vbCkgLT4gT3B0aW9uYWxbZmxvYXRdOgogICAgIiIiTk9BQS1zdHlsZSBzdW5yaXNl"
    "L3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwgbWludXRlcyBmcm9tIG1pZG5pZ2h0LiIiIgogICAgbiA9IGxvY2FsX2RheS50"
    "aW1ldHVwbGUoKS50bV95ZGF5CiAgICBsbmdfaG91ciA9IGxvbmdpdHVkZSAvIDE1LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hv"
    "dXIpIC8gMjQuMCkgaWYgc3VucmlzZSBlbHNlIG4gKyAoKDE4IC0gbG5nX2hvdXIpIC8gMjQuMCkKCiAgICBNID0gKDAuOTg1NiAq"
    "IHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKE0pKSkgKyAoMC4wMjAgKiBtYXRo"
    "LnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuNjM0CiAgICBMID0gTCAlIDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3Jl"
    "ZXMobWF0aC5hdGFuKDAuOTE3NjQgKiBtYXRoLnRhbihtYXRoLnJhZGlhbnMoTCkpKSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAg"
    "TF9xdWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5MC4wKSkgKiA5MC4wCiAgICBSQV9xdWFkcmFudCA9IChtYXRoLmZsb29yKFJB"
    "IC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFkcmFudCAtIFJBX3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2lu"
    "X2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoTCkpCiAgICBjb3NfZGVjID0gbWF0aC5jb3MobWF0aC5hc2lu"
    "KHNpbl9kZWMpKQoKICAgIHplbml0aCA9IDkwLjgzMwogICAgY29zX2ggPSAobWF0aC5jb3MobWF0aC5yYWRpYW5zKHplbml0aCkp"
    "IC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkpIC8gKGNvc19kZWMgKiBtYXRoLmNvcyhtYXRo"
    "LnJhZGlhbnMobGF0aXR1ZGUpKSkKICAgIGlmIGNvc19oIDwgLTEuMCBvciBjb3NfaCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9u"
    "ZQoKICAgIGlmIHN1bnJpc2U6CiAgICAgICAgSCA9IDM2MC4wIC0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBl"
    "bHNlOgogICAgICAgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkKICAgIEggLz0gMTUuMAoKICAgIFQgPSBIICsg"
    "UkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAgIFVUID0gKFQgLSBsbmdfaG91cikgJSAyNC4wCgogICAgbG9jYWxfb2Zmc2V0"
    "X2hvdXJzID0gKGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3Nl"
    "Y29uZHMoKSAvIDM2MDAuMAogICAgbG9jYWxfaG91ciA9IChVVCArIGxvY2FsX29mZnNldF9ob3VycykgJSAyNC4wCiAgICByZXR1"
    "cm4gbG9jYWxfaG91ciAqIDYwLjAKCmRlZiBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUobWludXRlc19mcm9tX21pZG5pZ2h0OiBP"
    "cHRpb25hbFtmbG9hdF0pIC0+IHN0cjoKICAgIGlmIG1pbnV0ZXNfZnJvbV9taWRuaWdodCBpcyBOb25lOgogICAgICAgIHJldHVy"
    "biAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbnV0ZXNfZnJvbV9taWRuaWdodCkpICUgKDI0ICogNjApCiAgICBoaCwg"
    "bW0gPSBkaXZtb2QobWlucywgNjApCiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShob3VyPWhoLCBtaW51dGU9bW0s"
    "IHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKS5zdHJmdGltZSgiJUg6JU0iKQoKZGVmIGdldF9zdW5fdGltZXMoKSAtPiB0dXBsZVtz"
    "dHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3VucmlzZS9zdW5zZXQgdXNpbmcgc3lzdGVtIGRhdGUgKyB0aW1l"
    "em9uZSBhbmQgb3B0aW9uYWwKICAgIHJ1bnRpbWUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAg"
    "Q2FjaGVkIHBlciBsb2NhbCBkYXRlIGFuZCB0aW1lem9uZSBvZmZzZXQuCiAgICAiIiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0RB"
    "VEUsIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNIRV9USU1FUwoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5v"
    "dygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwuZGF0ZSgpCiAgICB0el9vZmZzZXRfbWluID0gaW50KChub3df"
    "bG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNI"
    "RV9EQVRFID09IHRvZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPT0gdHpfb2Zmc2V0X21pbjoKICAgICAgICByZXR1"
    "cm4gX1NVTl9DQUNIRV9USU1FUwoKICAgIHRyeToKICAgICAgICBsYXQsIGxvbiA9IF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVz"
    "KCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNl"
    "PVRydWUpCiAgICAgICAgc3Vuc2V0X21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5y"
    "aXNlPUZhbHNlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5vbmUgb3Igc3Vuc2V0X21pbiBpcyBOb25lOgogICAgICAgICAg"
    "ICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVudCB1bmF2YWlsYWJsZSBmb3IgcmVzb2x2ZWQgY29vcmRpbmF0ZXMiKQogICAg"
    "ICAgIHRpbWVzID0gKF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5yaXNlX21pbiksIF9mb3JtYXRfbG9jYWxfc29sYXJfdGlt"
    "ZShzdW5zZXRfbWluKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdGltZXMgPSAoIjA2OjAwIiwgIjE4OjMwIikKCiAg"
    "ICBfU1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID0gdHpfb2Zmc2V0X21pbgogICAg"
    "X1NVTl9DQUNIRV9USU1FUyA9IHRpbWVzCiAgICByZXR1cm4gdGltZXMKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJM"
    "RUQ9VHJ1ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZXZlcnkgZ2VuZXJhdGlvbiBjYWxsLgoKVkFNUElSRV9T"
    "VEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElORyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAi"
    "Y29sb3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIs"
    "M30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lMSUdIVCBGQURJTkciOnsi"
    "aG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5U"
    "IjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwK"
    "ICAgICJSRVNUTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBv"
    "d2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7MTYsMTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xE"
    "X0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5FRCI6ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNv"
    "bG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsiaG91cnMiOiB7MjIsMjN9"
    "LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwKfQoKZGVmIGdldF92YW1waXJlX3N0YXRlKCkg"
    "LT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZhbXBpcmUgc3RhdGUgbmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIi"
    "IgogICAgaCA9IGRhdGV0aW1lLm5vdygpLmhvdXIKICAgIGZvciBzdGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0"
    "ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJob3VycyJdOgogICAgICAgICAgICByZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0"
    "dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHN0YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBW"
    "QU1QSVJFX1NUQVRFUy5nZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xEKQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dyZWV0"
    "aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsKICAgICAgICAiV0lUQ0hJTkcgSE9VUiI6ICAgZiJ7REVDS19O"
    "QU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdodCBub3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAg"
    "ZiJ7REVDS19OQU1FfSByZW1haW5zIGZvY3VzZWQgYW5kIGF2YWlsYWJsZSBmb3IgeW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRX"
    "SUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50aXZlIGFuZCB3YWl0aW5nIGZvciB5b3VyIG5leHQgcHJvbXB0"
    "LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQg"
    "c3RpbGwgcmVzcG9uc2l2ZS4iLAogICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBmIntERUNLX05BTUV9IGlzIGxpZ2h0bHkgaWRs"
    "ZSBhbmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElSUklORyI6ICAgICAgICBmIntERUNLX05BTUV9"
    "IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGludWUuIiwKICAgICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7"
    "REVDS19OQU1FfSBpcyBmdWxseSBhY3RpdmUgYW5kIHByZXBhcmVkIHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAg"
    "ICAgZiJ7REVDS19OQU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vzc2luZyB3aW5kb3cgYW5kIHN0YW5kaW5nIGJ5LiIsCiAgICB9"
    "CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0cl06CiAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5n"
    "ZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBpc2luc3RhbmNlKHByb3ZpZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVk"
    "LmtleXMoKSkgPT0gc2V0KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBzdHJdID0ge30K"
    "ICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtl"
    "eSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAg"
    "ICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFs"
    "LnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3Mo"
    "KQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6CiAgICAiIiIKICAgIEJ1aWxkIHRoZSB2YW1waXJlIHN0YXRl"
    "ICsgbW9vbiBwaGFzZSBjb250ZXh0IHN0cmluZyBmb3Igc3lzdGVtIHByb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3Jl"
    "IGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3YXlzIGZyZXNoLgogICAgIiIiCiAgICBpZiBub3QgQUlfU1RB"
    "VEVTX0VOQUJMRUQ6CiAgICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwg"
    "bW9vbl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgIG5vdyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDol"
    "TSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkKICAgIGZsYXZvciA9IHN0YXRlX2ZsYXZvcnMu"
    "Z2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYiXG5cbltDVVJSRU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAg"
    "ICAgICBmIlZhbXBpcmUgc3RhdGU6IHtzdGF0ZX0uIHtmbGF2b3J9XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2ls"
    "bHVtfSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVDS19OQU1FfSBpbiB0aGlzIHN0YXRlLiBEbyBu"
    "b3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIKICAgICkKCiMg4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5lcmF0aW9uLiBHb3RoaWMvdmFtcGlyaWMgc291bmQg"
    "cHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8gZmlsZXMgcmVxdWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2Vz"
    "IFB5dGhvbidzIGJ1aWx0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFjayAo"
    "c3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRlZiBfc2luZShmcmVxOiBmbG9hdCwgdDogZmxv"
    "YXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGguc2luKDIgKiBtYXRoLnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVx"
    "OiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDEuMCBpZiBfc2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEu"
    "MAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDIgKiAoKGZyZXEgKiB0"
    "KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQsIHNxdWFyZV9yOiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAg"
    "ICAgICBmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSAr"
    "CiAgICAgICAgICAgIHNxdWFyZV9yICogX3NxdWFyZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNhd19yICogX3Nhd3Rvb3RoKGZy"
    "ZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFsOiBpbnQsCiAgICAgICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0"
    "ID0gMC4wNSwKICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM6IGZsb2F0ID0gMC4zKSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5"
    "bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAvIG1heCgxLCB0b3RhbCkKICAgIGlmIHBvcyA8IGF0dGFja19m"
    "cmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwogICAgZWxpZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAg"
    "ICAgICAgcmV0dXJuICgxIC0gcG9zKSAvIHJlbGVhc2VfZnJhYwogICAgcmV0dXJuIDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDog"
    "UGF0aCwgYXVkaW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rf"
    "b2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0cihwYXRoKSwgInciKSBhcyBmOgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAy"
    "LCBfU0FNUExFX1JBVEUsIDAsICJOT05FIiwgIm5vdCBjb21wcmVzc2VkIikpCiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAg"
    "ICAgICAgIGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYgX2NsYW1wKHY6IGZsb2F0KSAtPiBpbnQ6CiAg"
    "ICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyNzY3KSkpCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5kaW5nIG1pbm9y"
    "IGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9yIHRoaXJkIGJlbG93LiBTbG93LCBoYXVudGluZywgY2F0aGVk"
    "cmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIERlc2NlbmRpbmcg"
    "bWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwgcHVyZSBzaW5lIHdpdGggbG9uZyBzdXN0YWluLgogICAgU291"
    "bmRzIGxpa2UgYSBzaW5nbGUgcmVzb25hbnQgYmVsbCBkeWluZyBpbiBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5v"
    "dGVzID0gWwogICAgICAgICg0NDAuMCwgMC42KSwgICAjIEE0IOKAlCBmaXJzdCBzdHJpa2UKICAgICAgICAoMzY5Ljk5LCAwLjkp"
    "LCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxvdyksIGxvbmdlciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9"
    "IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3RoIGluIG5vdGVzOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0"
    "aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAg"
    "ICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5vIHNxdWFyZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUo"
    "ZnJlcSwgdCkgKiAwLjcKICAgICAgICAgICAgIyBBZGQgYSBzdWJ0bGUgaGFybW9uaWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAg"
    "IHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAzLjAsIHQp"
    "ICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZlbG9wZSDigJQgYmVsbCBkaWVzIHNsb3dseQogICAgICAgICAg"
    "ICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDEsIHJlbGVhc2VfZnJhYz0wLjcpCiAgICAgICAgICAg"
    "IGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAjIEJyaWVmIHNpbGVuY2UgYmV0d2VlbiBub3Rl"
    "cwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjEpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5k"
    "KDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBhc2NlbmRpbmcgbWlub3IgY2hvcmQgcmVzb2x1dGlv"
    "bgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hvcmQpLCBmaW5hbCBub3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmlu"
    "Zy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVy"
    "YXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZp"
    "bmcgdXB3YXJkIOKAlCBsaWtlIGEgc8OpYW5jZSBiZWdpbm5pbmcuCiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwg"
    "bm90ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICgyMjAuMCwgMC4yNSksICAgIyBBMwog"
    "ICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhpcmQpCiAgICAgICAgKDMyOS42MywgMC4yNSksICAjIEU0IChm"
    "aWZ0aCkKICAgICAgICAoNDQwLjAsIDAuOCksICAgICMgQTQg4oCUIGZpbmFsLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAg"
    "ICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JB"
    "VEUgKiBsZW5ndGgpCiAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBsZW4obm90ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5n"
    "ZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQp"
    "ICogMC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMgogICAgICAgICAgICBpZiBpc19maW5h"
    "bDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFj"
    "PTAuNikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2Zy"
    "YWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQ1"
    "KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAw"
    "LjA1KSk6CiAgICAgICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIElETEUgQ0hJ"
    "TUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29mdC4gTGlrZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5z"
    "b2xpY2l0ZWQgdHJhbnNtaXNzaW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNv"
    "ZnQgbG93IGJlbGwg4oCUIEQzLiBWZXJ5IHF1aWV0LiBQcmVzZW5jZSBpbiB0aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMg"
    "ICMgRDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBb"
    "XQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3Np"
    "bmUoZnJlcSwgdCkgKiAwLjUKICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBf"
    "ZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjc1KQogICAgICAgIGF1ZGlvLmFwcGVu"
    "ZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEVSUk9SIOKAlCB0cml0b25lICh0"
    "aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVmLiBTb21ldGhpbmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFs"
    "LgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJh"
    "dGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgogICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMg"
    "KyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHkuCiAgICBUaGUgJ2RpYWJvbHVzIGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBj"
    "b21wYXJlZCB0byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2EgPSAyNDYuOTQgICMgQjMKICAgIGZyZXFfYiA9"
    "IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvdmUgQikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90"
    "YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgog"
    "ICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlCBj"
    "cmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUoZnJlcV9hLCB0KSAqIDAuNSArCiAgICAgICAgICAgICAgIF9z"
    "cXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAgIF9zaW5lKGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAg"
    "ICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgIGF1"
    "ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKA"
    "lCBkZXNjZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9uCiMgUmV2ZXJzZSBvZiBzdGFydHVwLiBUaGUgc8OpYW5jZSBlbmRzLiBQcmVz"
    "ZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiRGVzY2VuZGluZyBB"
    "NCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdpbmcgaW50byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsK"
    "ICAgICAgICAoNDQwLjAsICAwLjMpLCAgICMgQTQKICAgICAgICAoMzI5LjYzLCAwLjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYz"
    "LCAwLjMpLCAgICMgQzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAgICMgQTMg4oCUIGZpbmFsLCBsb25nIGZhZGUKICAgIF0KICAg"
    "IGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0g"
    "aW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBq"
    "IC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41NQogICAgICAgICAgICB2YWwgKz0g"
    "X3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2Zy"
    "YWM9MC4wMywKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJlbGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEg"
    "ZWxzZSAwLjMpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40KSkKICAgICAgICBmb3IgXyBp"
    "biByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93"
    "YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBBVEhTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2V0"
    "X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAgcmV0dXJuIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BS"
    "RUZJWH1fe25hbWV9LndhdiIKCmRlZiBib290c3RyYXBfc291bmRzKCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNz"
    "aW5nIHNvdW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJhdG9ycyA9IHsKICAgICAgICAiYWxlcnQiOiAgICBn"
    "ZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZuIG5hbWUgdW5jaGFuZ2VkCiAgICAgICAgInN0YXJ0dXAiOiAg"
    "Z2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwKICAgICAgICAiaWRsZSI6ICAgICBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAg"
    "ICAgICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yLAogICAgICAgICJzaHV0ZG93biI6IGdlbmVyYXRlX21vcmdh"
    "bm5hX3NodXRkb3duLAogICAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBpbiBnZW5lcmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0"
    "aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVyYXRlIHtuYW1lfToge2V9IikKCmRlZiBwbGF5X3NvdW5kKG5h"
    "bWU6IHN0cikgLT4gTm9uZToKICAgICIiIgogICAgUGxheSBhIG5hbWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5"
    "Z2FtZS5taXhlciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAgICBGYWxscyBiYWNrIHRvIHdpbnNvdW5kIG9u"
    "IFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvbi5iZWVwKCkgYXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAg"
    "IGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJzb3VuZF9lbmFibGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRo"
    "ID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGlmIFBZ"
    "R0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1lLm1peGVyLlNvdW5kKHN0cihwYXRoKSkKICAg"
    "ICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgIHBhc3MKCiAgICBpZiBXSU5TT1VORF9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChz"
    "dHIocGF0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3VuZC5TTkRfRklMRU5BTUUgfCB3aW5zb3VuZC5T"
    "TkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAg"
    "ICB0cnk6CiAgICAgICAgUUFwcGxpY2F0aW9uLmJlZXAoKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKU"
    "gOKUgCBERVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBjcmVhdGVfZGVza3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAi"
    "IiIKICAgIENyZWF0ZSBhIGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhlIGRlY2sgLnB5IGZpbGUgdXNpbmcgcHl0aG9udy5leGUuCiAg"
    "ICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5LgogICAgIiIiCiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAg"
    "ICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAgICAgZGVza3RvcCA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAg"
    "c2hvcnRjdXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKCiAgICAgICAgIyBweXRob253ID0gc2FtZSBhcyBw"
    "eXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAg"
    "aWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJl"
    "bnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6CiAgICAgICAgICAgIHB5dGhvbncgPSBQ"
    "YXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3BhdGggPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAg"
    "c2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRl"
    "U2hvcnRDdXQoc3RyKHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBhdGggICAgID0gc3RyKHB5dGhvbncpCiAgICAg"
    "ICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeSA9IHN0cihk"
    "ZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2NyaXB0aW9uICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoK"
    "ICAgICAgICAjIFVzZSBuZXV0cmFsIGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0"
    "aCgiZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIKICAgICAgICBpZiBpY29uX3BhdGguZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNlIFBORyBkaXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5p"
    "Y28KICAgICAgICAgICAgcGFzcwoKICAgICAgICBzYy5zYXZlKCkKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0i"
    "KQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwgVVRJTElUSUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3RdOgogICAgIiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVy"
    "bnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09OIGFycmF5cyB0b28uIiIiCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICByZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlwKCkKICAgIGlmIG5v"
    "dCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3RhcnRzd2l0aCgiWyIpOgogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgZGF0YSA9IGpzb24ubG9hZHMocmF3KQogICAgICAgICAgICByZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNl"
    "KHgsIGRpY3QpXQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIGl0ZW1zID0gW10KICAgIGZv"
    "ciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5l"
    "OgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToKICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAg"
    "ICAgICAgICBpZiBpc2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQob2JqKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZXR1cm4gaXRlbXMKCmRlZiBhcHBlbmRfanNvbmwo"
    "cGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25lOgogICAgIiIiQXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIi"
    "IgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oImEi"
    "LCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhvYmosIGVuc3VyZV9hc2NpaT1GYWxz"
    "ZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgsIHJlY29yZHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAi"
    "IiJPdmVyd3JpdGUgYSBKU09OTCBmaWxlIHdpdGggYSBsaXN0IG9mIHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6"
    "CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZi53cml0ZShqc29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1G"
    "YWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZV09SRCAvIE1FTU9SWSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApfU1RPUFdPUkRTID0gewogICAgInRoZSIs"
    "ImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRoaXMiLCJmcm9tIiwieW91ciIsIndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIs"
    "IndoaWNoIiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwidGhlbiIsImludG8iLCJqdXN0IiwKICAgICJhYm91dCIsImxp"
    "a2UiLCJiZWNhdXNlIiwid2hpbGUiLCJjb3VsZCIsInNob3VsZCIsInRoZWlyIiwid2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwi"
    "ZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNhbnQiLCJ3b250Iiwib250byIsIm92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIs"
    "ImFsc28iLCJzb21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndhbnQiLCJ3aWxsIiwic2hhbGwiLAogICAgImFnYWlu"
    "IiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIsInVzZWQiLCJ1c2luZyIsInNhaWQiLAogICAgInRlbGwiLCJ0"
    "b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhpbmciLCJzdHVmZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFj"
    "dF9rZXl3b3Jkcyh0ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtzdHJdOgogICAgdG9rZW5zID0gW3QubG93ZXIo"
    "KS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc3BsaXQoKV0KICAgIHNlZW4sIHJlc3VsdCA9IHNldCgp"
    "LCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAgICAgIGlmIGxlbih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNk"
    "aWdpdCgpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIHQgbm90IGluIHNlZW46CiAgICAgICAgICAgIHNlZW4uYWRk"
    "KHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4ocmVzdWx0KSA+PSBsaW1pdDoKICAgICAgICAg"
    "ICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50"
    "X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICB0ID0gKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigp"
    "CiAgICBpZiAiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiAiZHJlYW0iCiAgICBpZiBhbnko"
    "eCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29kZSIsImVycm9yIiwiYnVnIikpOgogICAgICAgIGlm"
    "IGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhlZCIsInJlc29sdmVkIiwic29sdXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAg"
    "ICByZXR1cm4gInJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJy"
    "ZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICByZXR1cm4gInRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZv"
    "ciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0IGlmIiwiZ2FtZSIsInByb2plY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVh"
    "IgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoInByZWZlciIsImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtlIiwiaSB3YW50Iikp"
    "OgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIKICAgIHJldHVybiAiY29udmVyc2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENP"
    "TVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5leHQ6IFBhc3MgMiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1"
    "Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdpZGdldCwgRW1vdGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVT"
    "dGF0ZVN0cmlwLCBDb2xsYXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAyOiBX"
    "SURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRvIGZvcm0gdGhlIGZ1bGwgZGVjay4KIwojIFdp"
    "ZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQgICAgICAgICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBs"
    "YWJlbCBhbmQgdmFsdWUKIyAgIERyaXZlV2lkZ2V0ICAgICAgICAgIOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0Ip"
    "CiMgICBTcGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNpcmNsZSBmb3IgQkxPT0QgYW5kIE1BTkEKIyAgIE1vb25XaWRn"
    "ZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlIHNoYWRvdwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg"
    "4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBjaGlwcwojICAgTWlycm9yV2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1h"
    "Z2UgZGlzcGxheSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAgIOKAlCBmdWxsLXdpZHRoIHRpbWUvbW9vbi9z"
    "dGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDigJQgd3JhcHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9n"
    "Z2xlIHRvIGFueSB3aWRnZXQKIyAgIEhhcmR3YXJlUGFuZWwgICAgICAgIOKAlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBHYXVnZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgSG9yaXpvbnRhbCBmaWxsLWJhciBnYXVnZSB3aXRoIGdvdGhp"
    "YyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCksIHZhbHVlIHRleHQgKHRvcC1yaWdodCksIGZpbGwgYmFyIChi"
    "b3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg4oaSIENfQ1JJTVNPTiDihpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2Fj"
    "aGVzIG1heC4KICAgIFNob3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5pdDogc3RyID0gIiIsCiAgICAgICAgbWF4X3Zh"
    "bDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjogc3RyID0gQ19HT0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYu"
    "dW5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92YWwKICAgICAgICBzZWxmLmNvbG9yICAgID0gY29s"
    "b3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5f"
    "YXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhp"
    "bXVtSGVpZ2h0KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxvYXQsIGRpc3BsYXk6IHN0ciA9ICIiLCBhdmFp"
    "bGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3ZhbHVlICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNl"
    "bGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBlbGlmIGRpc3BsYXk6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "c3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9IGYie3ZhbHVlOi4wZn17c2Vs"
    "Zi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHNldFVuYXZhaWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLl9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAgIHNlbGYudXBk"
    "YXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikK"
    "ICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNl"
    "bGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91bmQKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcs"
    "IGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDAs"
    "IDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJlbAogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAg"
    "ICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5kcmF3VGV4dCg2"
    "LCAxNCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yIGlmIHNl"
    "bGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9u"
    "dC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZh"
    "bmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2LCAxNCwgc2VsZi5fZGlzcGxheSkKCiAgICAg"
    "ICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAgICAgICAgYmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAt"
    "IDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQ"
    "ZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAg"
    "ICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92YWwgPiAwOgogICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFs"
    "dWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAg"
    "ICAgICAgICAjIENvbG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYgZnJhYyA+"
    "IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIGZyYWMgPiAwLjY1IGVsc2UKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAgICAgICAgIGdyYWQgPSBRTGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAx"
    "LCA3ICsgZmlsbF93LCBiYXJfeSArIDEpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5k"
    "YXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBw"
    "LmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAtIDIsIGdyYWQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKU"
    "gCBEUklWRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0IsIGZp"
    "bGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRyaXZlcyB2aWEgcHN1dGlsLgogICAgIiIiCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9k"
    "cml2ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodCgzMCkKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kcml2ZXMgPSBbXQogICAgICAgIGlm"
    "IG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1"
    "dGlsLmRpc2tfcGFydGl0aW9ucyhhbGw9RmFsc2UpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVz"
    "YWdlID0gcHN1dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50KQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RyaXZlcy5h"
    "cHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjogcGFydC5kZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgi"
    "LyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidXNlZCI6ICAgdXNhZ2UudXNlZCAgLyAxMDI0KiozLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAidG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAicGN0Ijog"
    "ICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAgIH0pCiAgICAgICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "cGFzcwogICAgICAgICMgUmVzaXplIHRvIGZpdCBhbGwgZHJpdmVzCiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2VsZi5fZHJpdmVz"
    "KSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVm"
    "IHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRS"
    "ZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNl"
    "bGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250"
    "KFFGb250KERFQ0tfRk9OVCwgOSkpCiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwgMTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2YWls"
    "YWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHJvd19oID0gMjYKICAgICAgICB5"
    "ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAg"
    "ICAgICAgICAgIHVzZWQgICA9IGRydlsidXNlZCJdCiAgICAgICAgICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogICAgICAgICAg"
    "ICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAgICAgICAgIGxhYmVsID0gZiJ7bGV0dGVyfSAg"
    "e3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAg"
    "cC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYs"
    "IHkgKyAxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAgICBiYXJfeCA9IDYKICAgICAgICAgICAgYmFyX3kg"
    "PSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICAgICAgYmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmls"
    "bFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xvcihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9y"
    "KENfQk9SREVSKSkKICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAg"
    "ICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBjdCkpCiAgICAgICAgICAgIGJhcl9jb2xvciA9IChD"
    "X0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBl"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0dPTERfRElNKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50"
    "KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFD"
    "b2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xv"
    "cikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoK"
    "ICAgICAgICAgICAgeSArPSByb3dfaAoKICAgICAgICBwLmVuZCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1cGRhdGUgZHJpdmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgp"
    "CgoKIyDilIDilIAgU1BIRVJFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lk"
    "Z2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9v"
    "bCkgYW5kIE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEdsYXNzeSBzaGluZSBlZmZlY3QuIExhYmVsIGJl"
    "bG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBj"
    "b2xvcl9mdWxsOiBzdHIsCiAgICAgICAgY29sb3JfZW1wdHk6IHN0ciwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgICAgID0gbGFiZWwKICAgICAgICBzZWxmLmNv"
    "bG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3JfZW1wdHkgPSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYu"
    "X2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpIgMS4wCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBz"
    "ZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2VsZiwgZnJhY3Rpb246IGZsb2F0LCBhdmFpbGFi"
    "bGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZpbGwgICAgICA9IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0"
    "aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGUKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBh"
    "aW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5k"
    "ZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYu"
    "aGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIwKSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAg"
    "Y3kgPSAoaCAtIDIwKSAvLyAyICsgNAoKICAgICAgICAjIERyb3Agc2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMCwgMCwgMCwgODApKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSBy"
    "ICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIEJhc2UgY2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAg"
    "ICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQog"
    "ICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBGaWxsIGZyb20gYm90"
    "dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5kIHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3Bh"
    "dGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBjaXJjbGVfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0"
    "KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCgog"
    "ICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYuX2ZpbGwgKiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNp"
    "ZGU2LlF0Q29yZSBpbXBvcnQgUVJlY3RGCiAgICAgICAgICAgIGZpbGxfcmVjdCA9IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3ks"
    "IHIgKiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAg"
    "ICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAgICAgIGNsaXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNl"
    "Y3RlZChmaWxsX3BhdGgpCgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRC"
    "cnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkKQoKICAgICAgICAjIEds"
    "YXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAogICAgICAgICAgICBmbG9hdChjeCAtIHIgKiAwLjMp"
    "LCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICogMC42KQogICAgICAgICkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAs"
    "IFFDb2xvcigyNTUsIDI1NSwgMjU1LCA1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUsIDI1"
    "NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAg"
    "ICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAu"
    "c2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVs"
    "bCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBOL0Eg"
    "b3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRf"
    "RElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KCJDb3VyaWVyIE5ldyIsIDgpKQogICAgICAgICAgICBmbSA9IHAuZm9u"
    "dE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gZm0uaG9yaXpvbnRh"
    "bEFkdmFuY2UodHh0KSAvLyAyLCBjeSArIDQsIHR4dCkKCiAgICAgICAgIyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJl"
    "bF90ZXh0ID0gKHNlbGYubGFiZWwgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UKICAgICAgICAgICAgICAgICAgICAgIGYie3NlbGYu"
    "bGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9maWxsICogMTAwKX0lIiBpZiBzZWxmLl9hdmFpbGFibGUg"
    "ZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQo"
    "REVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBsdyAvLyAyLCBoIC0gMTAs"
    "IGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkp"
    "CiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNz"
    "KCkKICAgICAgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0X3RleHQpCiAgICAgICAgICAgIHAuZHJhd1RleHQo"
    "Y3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBNT09OIFdJREdFVCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAg"
    "RHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1cmF0ZSBzaGFkb3cuCgogICAgUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4g"
    "aGVtaXNwaGVyZSwgc3RhbmRhcmQpOgogICAgICAtIFdheGluZyAobmV34oaSZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUs"
    "IHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxsdW1pbmF0ZWQgbGVmdCBzaWRlLCBzaGFkb3cg"
    "b24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4gYmUgZmxpcHBlZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBi"
    "YWNrd2FyZHMKICAgIG9uIHRoaXMgbWFjaGluZS4gU2V0IE1PT05fU0hBRE9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAg"
    "ICIiIgoKICAgICMg4oaQIEZMSVAgVEhJUyB0byBUcnVlIGlmIG1vb24gYXBwZWFycyBiYWNrd2FyZHMgZHVyaW5nIHRlc3RpbmcK"
    "ICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAg"
    "ICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGhhc2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3"
    "LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgICAgICAgID0gIk5FVyBNT09OIgogICAgICAgIHNlbGYuX2ls"
    "bHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxmLl9zdW5yaXNlICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2Vs"
    "Zi5fc3Vuc2V0ICAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICAgICA9IE5vbmUKICAgICAgICBzZWxmLnNl"
    "dE1pbmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFzZSgpICAgICAgICAgICMgcG9wdWxhdGUgY29ycmVj"
    "dCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5"
    "bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2ZldGNoKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMo"
    "KQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAg"
    "IHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxl"
    "IHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1lciDigJQgbmV2ZXIgY2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRl"
    "KCkgZGlyZWN0bHkgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYu"
    "dXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mZXRjaCwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBk"
    "ZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9waGFzZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1p"
    "bmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUo"
    "KQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQog"
    "ICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0g"
    "UVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAg"
    "ICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIg"
    "LSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMzYpIC8vIDIgKyA0CgogICAgICAgICMgQmFja2dyb3Vu"
    "ZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIwLCAxMiwgMjgpKQogICAgICAgIHAuc2V0UGVuKFFQ"
    "ZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCBy"
    "ICogMikKCiAgICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2UgKiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193YXhpbmcgPSBj"
    "eWNsZV9kYXkgPCAoX0xVTkFSX0NZQ0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1vb24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9y"
    "KQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA+IDE6CiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVu"
    "KQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIxMCwgMTg1KSkKICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShj"
    "eCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFNoYWRvdyBjYWxjdWxhdGlvbgogICAgICAgICMgaWxsdW1p"
    "bmF0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2FuaW5nCiAgICAgICAgIyBzaGFkb3dfb2Zmc2V0IGNvbnRyb2xz"
    "IGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5"
    "OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBvZiBkaWFtZXRlciB0aGUgc2hhZG93IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAg"
    "ICAgIGlsbHVtX2ZyYWMgID0gc2VsZi5faWxsdW1pbmF0aW9uIC8gMTAwLjAKICAgICAgICAgICAgc2hhZG93X2ZyYWMgPSAxLjAg"
    "LSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0ZWQgcmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAg"
    "ICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cgUklHSFQKICAgICAgICAgICAgIyBvZmZzZXQgbW92ZXMgdGhl"
    "IHNoYWRvdyBlbGxpcHNlIGhvcml6b250YWxseQogICAgICAgICAgICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikK"
    "CiAgICAgICAgICAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAgICAgICAgICAgICAgIGlzX3dheGluZyA9IG5v"
    "dCBpc193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dheGluZzoKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIGxlZnQgc2lk"
    "ZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBjeCAtIHIgLSBvZmZzZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "ICAgICMgU2hhZG93IG9uIHJpZ2h0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByICsgb2Zmc2V0CgogICAg"
    "ICAgICAgICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1Bl"
    "bikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xpcHBlZCB0byBtb29uIGNpcmNsZQogICAgICAgICAg"
    "ICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBtb29uX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIp"
    "LCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICog"
    "MikpCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxs"
    "aXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZs"
    "b2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBjbGlwcGVkX3NoYWRvdyA9IG1vb25fcGF0aC5pbnRlcnNlY3Rl"
    "ZChzaGFkb3dfcGF0aCkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkX3NoYWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3Vy"
    "ZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQgdGV4dHVyZSBncmFkaWVudCkKICAgICAgICBzaGluZSA9IFFS"
    "YWRpYWxHcmFkaWVudChmbG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChjeSAtIHIgKiAwLjIpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAy"
    "NDAsIDMwKSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigyMDAsIDE4MCwgMTQwLCA1KSkKICAgICAgICBwLnNl"
    "dEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3gg"
    "LSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0"
    "eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxp"
    "cHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgUGhhc2UgbmFtZSBiZWxvdyBtb29uCiAgICAgICAg"
    "cC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3LCBRRm9udC5XZWln"
    "aHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNl"
    "bGYuX25hbWUpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIG53IC8vIDIsIGN5ICsgciArIDE0LCBzZWxmLl9uYW1lKQoKICAgICAg"
    "ICAjIElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxsdW1fc3RyID0gZiJ7c2VsZi5faWxsdW1pbmF0aW9uOi4wZn0l"
    "IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3"
    "KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBpdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9z"
    "dHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3Vu"
    "IHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9IGYi4piAIHtzZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9z"
    "dW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19G"
    "T05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShz"
    "dW5fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwgc3VuX3N0cikKCiAgICAgICAgcC5lbmQoKQoK"
    "CiMg4pSA4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9j"
    "ayhRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IHBhbmVsLgogICAgU2hvd3MgY29sb3It"
    "Y29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5leHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRn"
    "ZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29sbGFwc2VzIHRvIGp1c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBsZVtzdHIsIHN0cl1dID0gW10gICMgKGVtb3Rpb24sIHRpbWVzdGFtcCkKICAg"
    "ICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxmLl9tYXhfZW50cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxh"
    "eW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyIHJvdwogICAgICAgIGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAg"
    "IGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAg"
    "ICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAg"
    "ICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFiZWwoIuKdpyBFTU9USU9OQUwgUkVDT1JEIikKICAgICAgICBs"
    "Ymwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdo"
    "dDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAx"
    "cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7"
    "IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChsYmwp"
    "CiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCgogICAgICAgICMg"
    "U2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAg"
    "c2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Ny"
    "b2xsQmFyUG9saWN5KAogICAgICAgICAgICBRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNl"
    "bGYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsi"
    "CiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NoaXBfbGF5"
    "b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYu"
    "X2NoaXBfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2hpcF9jb250YWlu"
    "ZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoaGVhZGVyKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xs"
    "KQoKICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aCgxMzApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRWaXNpYmxlKHNlbGYu"
    "X2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLi"
    "lrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKICAgIGRlZiBhZGRFbW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwg"
    "dGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBpZiBub3QgdGltZXN0YW1wOgogICAgICAgICAgICB0aW1lc3Rh"
    "bXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgIHNlbGYuX2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90"
    "aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3RvcnkgPSBzZWxmLl9oaXN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10K"
    "ICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYgX3JlYnVpbGRfY2hpcHMoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChrZWVwIHRoZSBzdHJldGNoIGF0IGVuZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlw"
    "X2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NoaXBfbGF5b3V0LnRha2VBdCgwKQogICAgICAg"
    "ICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAg"
    "IGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0b3J5OgogICAgICAgICAgICBjb2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChl"
    "bW90aW9uLCBDX1RFWFRfRElNKQogICAgICAgICAgICBjaGlwID0gUUxhYmVsKGYi4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7dHN9"
    "IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1z"
    "aXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4"
    "OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0Lmluc2VydFdp"
    "ZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmNvdW50KCkgLSAxLCBjaGlwCiAgICAgICAgICAgICkKCiAg"
    "ICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9oaXN0b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1"
    "aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJST1IgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBNaXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIiIgogICAgRmFjZSBpbWFnZSBkaXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAg"
    "ICBEeW5hbWljYWxseSBsb2FkcyBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4K"
    "ICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToKICAgICAgICB7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg"
    "4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIOKGkiAic2FkIgogICAgICAgIHtGQUNFX1BS"
    "RUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAgICBGYWxscyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290"
    "aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdlcyBmb3VuZC4KICAgIE1pc3NpbmcgZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIOKA"
    "lCBubyBjcmFzaCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQuCiAgICAiIiIKCiAgICAjIFNwZWNpYWwgc3RlbSDihpIgZW1v"
    "dGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBzdGVtIGFmdGVyIE1vcmdhbm5hXykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRp"
    "Y3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRfY3J5aW5nIjogICJzYWQiLAogICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVh"
    "dG1vZGUiLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgICAgIHNlbGYuX2NhY2hl"
    "OiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGYuX2N1cnJlbnQgICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2Vs"
    "Zi5fd2FybmVkOiBzZXRbc3RyXSA9IHNldCgpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAgICAg"
    "c2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwg"
    "c2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3ByZWxvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTY2FuIEZh"
    "Y2VzLyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVzLgogICAgICAgIEJ1aWxkIGVtb3Rpb27ihpJw"
    "aXhtYXAgY2FjaGUgZHluYW1pY2FsbHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIGxpc3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBm"
    "b2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXRo"
    "IGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIpOgogICAgICAgICAgICAjIHN0ZW0gPSBldmVy"
    "eXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwogICAgICAgICAgICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1b"
    "bGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAgICMgZS5nLiAiU2FkX0NyeWluZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJh"
    "d19zdGVtLmxvd2VyKCkgICAgICAgICAgICAgICAgICAgICAgICAgICMgInNhZF9jcnlpbmciCgogICAgICAgICAgICAjIE1hcCBz"
    "cGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAgICAgICBlbW90aW9uID0gc2VsZi5fU1RFTV9UT19FTU9USU9OLmdl"
    "dChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAgcHggPSBRUGl4bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAg"
    "ICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAgICAgICAgICAgIHNlbGYuX2NhY2hlW2Vtb3Rpb25dID0gcHgKCiAgICAgICAg"
    "aWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgIGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAg"
    "ICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl93YXJuZWQgYW5kIGZhY2UgIT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAgcHJp"
    "bnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZToge2ZhY2V9IOKAlCB1c2luZyBuZXV0cmFsIikKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAgICAgZmFjZSA9ICJuZXV0cmFsIgogICAgICAgIGlmIGZhY2Ug"
    "bm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZhY2UKICAgICAgICBweCA9IHNlbGYuX2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVk"
    "ID0gcHguc2NhbGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkgLSA0LAogICAgICAgICAgICBzZWxmLmhlaWdodCgpIC0gNCwK"
    "ICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2RlLktlZXBBc3BlY3RSYXRpbywKICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRp"
    "b25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAogICAgICAgICkKICAgICAgICBzZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAg"
    "ICAgc2VsZi5zZXRUZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhvbGRlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "Y2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadcbuKcpiIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogMjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAg"
    "ICAgICApCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBkZWYgcmVzaXplRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6"
    "CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkKICAgICAgICBpZiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2Vs"
    "Zi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoK"
    "ICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIEN5Y2xlV2lkZ2V0KE1vb25XaWRnZXQpOgogICAgIiIiR2VuZXJpYyBjeWNsZSB2aXN1YWxpemF0aW9uIHdpZGdldCAo"
    "Y3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xhc3MgVmFtcGlyZVN0YXRlU3RyaXAoUVdpZGdldCk6CiAgICAi"
    "IiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1N"
    "ICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJs"
    "ZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFsIFFUaW1lciBjYWxsIHRvIHJl"
    "ZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFtcGlyZSBzdGF0ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxf"
    "cHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxm"
    "Ll90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAg"
    "PSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgID0gTm9uZQogICAgICAgIHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9P"
    "TiIKICAgICAgICBzZWxmLl9pbGx1bSAgICAgPSAwLjAKICAgICAgICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNl"
    "bGYuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07IikKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIHNldF9s"
    "YWJlbChzZWxmLCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9IChsYWJlbCBvciAiU1RB"
    "VEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBkZWYgX2YoKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAg"
    "IHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0gc3MKICAgICAgICAgICAgc2VsZi5fc3VuX2Rh"
    "dGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBt"
    "YWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUoKSBmcm9tCiAgICAgICAgICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwg"
    "aXQgY2F1c2VzIFFUaHJlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVw"
    "ZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZiwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBz"
    "ZWxmLl90aW1lX3N0ciAgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuc3RyZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9"
    "IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAg"
    "ICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBfLCBzZWxmLl9tb29uX25hbWUsIHNlbGYuX2lsbHVtID0g"
    "Z2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4g"
    "Tm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGlu"
    "dC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICBwLmZpbGxS"
    "ZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMikpCgogICAgICAgIHN0YXRlX2NvbG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29s"
    "b3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7"
    "c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3Vucmlz"
    "ZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2ls"
    "bHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJv"
    "bGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0g"
    "NywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5"
    "b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250ZW50"
    "c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxm"
    "Lm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBz"
    "ZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGlu"
    "IChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAg"
    "ICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09M"
    "RH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBm"
    "b250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAg"
    "ICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0"
    "bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVy"
    "dGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAg"
    "ICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNv"
    "bG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAg"
    "IGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2Zm"
    "ZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9u"
    "LWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRn"
    "ZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAgKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxm"
    "LmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRh"
    "OiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5j"
    "b25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVfbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5"
    "X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRh"
    "ci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRo"
    "X2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBw"
    "bHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQo"
    "KQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hh"
    "ckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYu"
    "Y2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIu"
    "c2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdl"
    "ZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRX"
    "ZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFy"
    "LnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9"
    "IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkg"
    "KyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZv"
    "cm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5"
    "T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0p"
    "KQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZt"
    "dC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRG"
    "b3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQs"
    "IGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3Vu"
    "ZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAg"
    "ICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERh"
    "dGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0"
    "aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5"
    "IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwu"
    "IFRvZ2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBz"
    "aWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQog"
    "ICAgIiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250"
    "ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwK"
    "ICAgICAgICAgICAgICAgICByZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQK"
    "ICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAogICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVz"
    "ZXJ2ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0U3BhY2lu"
    "ZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRl"
    "ci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQo"
    "c2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNp"
    "bmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIK"
    "ICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXpl"
    "KDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3Bh"
    "cmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgog"
    "ICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0"
    "KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNl"
    "bGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9v"
    "bDoKICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYu"
    "dG9nZ2xlZC5lbWl0KHNlbGYuX2V4cGFuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNl"
    "bGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAo"
    "dXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2Vs"
    "Zi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIx"
    "NSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5f"
    "d2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAg"
    "ICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZp"
    "eGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVu"
    "dCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAg"
    "cGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwg"
    "Y29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1"
    "Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAu"
    "CiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3Vp"
    "KCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkK"
    "ICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJl"
    "bDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25f"
    "bGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4"
    "KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0"
    "LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNU"
    "QVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIp"
    "CiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxi"
    "bF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBz"
    "ZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAg"
    "ICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXpl"
    "OiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsi"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0"
    "dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLi"
    "nacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVs"
    "KCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRT"
    "cGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJ"
    "TFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJ"
    "TSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdl"
    "dChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSA"
    "IEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdy"
    "aWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VX"
    "aWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0"
    "KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1"
    "LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5h"
    "ZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vj"
    "dGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BV"
    "IFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIg"
    "KGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2n"
    "IElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIs"
    "IDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAg"
    "ICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdh"
    "cmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4K"
    "ICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIK"
    "ICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAg"
    "ICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJF"
    "XSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAg"
    "aW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoK"
    "ICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAg"
    "ICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFp"
    "bGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9y"
    "IG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5z"
    "dGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlz"
    "aW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9L"
    "IOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1heCBW"
    "UkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUlu"
    "Zm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAg"
    "ICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoK"
    "ICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25k"
    "IGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAg"
    "ICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGls"
    "LmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwg"
    "YXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAg"
    "ICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAg"
    "ICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3Jh"
    "bS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAg"
    "aWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52"
    "bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0gcHlu"
    "dm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5u"
    "dm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwu"
    "TlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAgICAg"
    "ICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1l"
    "bV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYi"
    "e2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVl"
    "KGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxh"
    "YmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmlj"
    "ZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZh"
    "bHVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4w"
    "Zn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAg"
    "ICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5v"
    "dCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxm"
    "Ll9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sg"
    "Pj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJl"
    "c2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5z"
    "ZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VM"
    "OiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAg"
    "ICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0"
    "aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkK"
    "CgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFz"
    "c2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJl"
    "YWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3Jr"
    "ZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJz"
    "IGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFw"
    "dG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg"
    "4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBj"
    "bGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQg"
    "dHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1h"
    "aW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFk"
    "LiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0"
    "IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExN"
    "IEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAg"
    "QWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJh"
    "dGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0"
    "aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tl"
    "bmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAg"
    "ICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0"
    "W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAg"
    "IiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBi"
    "YWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJl"
    "Zm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAg"
    "ICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAg"
    "IG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3"
    "cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1l"
    "bnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIi"
    "LmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRf"
    "Y2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9y"
    "bWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNz"
    "aXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0"
    "ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0g"
    "bXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAg"
    "ICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1"
    "c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8"
    "PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9p"
    "bihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExM"
    "TUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBT"
    "dHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4K"
    "ICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0"
    "aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9u"
    "ZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNl"
    "bGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1v"
    "ZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBz"
    "dWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9y"
    "Y2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAg"
    "ICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAg"
    "IHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5f"
    "cGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFw"
    "PSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAg"
    "ICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQo"
    "c2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAog"
    "ICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAg"
    "ICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBT"
    "dHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29k"
    "ZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9s"
    "b2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAg"
    "ICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAgICAg"
    "aWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1"
    "aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5f"
    "dG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5p"
    "bnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2Vu"
    "aXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAg"
    "ICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAg"
    "ICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2si"
    "OiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAg"
    "ICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAg"
    "ICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAg"
    "ICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBp"
    "biBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRp"
    "bmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dh"
    "cmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBnZW5f"
    "dGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAgeWll"
    "bGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAg"
    "IENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09O"
    "IHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBy"
    "dW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9k"
    "ZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21v"
    "ZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNf"
    "Y29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVx"
    "dWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJl"
    "cSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDog"
    "c3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tl"
    "bnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2No"
    "YXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIg"
    "bGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgog"
    "ICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAg"
    "ICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0g"
    "anNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBt"
    "ZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGlj"
    "dCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9i"
    "YXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29u"
    "dGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAg"
    "ICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2Rl"
    "KCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMo"
    "bGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIs"
    "ICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNo"
    "dW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5b"
    "RVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydz"
    "IENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25m"
    "aWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdl"
    "cyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6"
    "CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25u"
    "ZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAg"
    "ICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGlj"
    "dF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNz"
    "YWdlcyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAg"
    "ICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50Il0s"
    "CiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBz"
    "ZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6"
    "ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAg"
    "VHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtl"
    "eSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAg"
    "ICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAg"
    "ICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAg"
    "ICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAg"
    "ICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5b"
    "RVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoK"
    "ICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0gcmVz"
    "cC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAg"
    "ICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZm"
    "ZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAg"
    "ICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVs"
    "ZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25u"
    "LmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVO"
    "QUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToK"
    "ICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVy"
    "biBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9z"
    "dDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9k"
    "ZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoK"
    "ICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21w"
    "dDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190"
    "b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lz"
    "dGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMu"
    "YXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9"
    "IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2Vz"
    "IjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVt"
    "cGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIp"
    "CgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAog"
    "ICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAg"
    "ICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAg"
    "ICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1"
    "dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5"
    "WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxl"
    "IFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6"
    "CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikK"
    "ICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1"
    "ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAg"
    "ICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1"
    "Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJj"
    "aG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAg"
    "ICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6"
    "IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNs"
    "b3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9S"
    "IEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExN"
    "QWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENh"
    "bGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJt"
    "b2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJl"
    "dHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0y"
    "LjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAg"
    "ICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIs"
    "ICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4gT3Bl"
    "bkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5n"
    "ZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJh"
    "bnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwg"
    "IiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dv"
    "cmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9u"
    "ZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVh"
    "Y2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGgg"
    "dGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4"
    "Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVS"
    "QVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25z"
    "ZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9"
    "IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAg"
    "ICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lz"
    "dGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAg"
    "ICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYg"
    "Y2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBz"
    "dG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAg"
    "cHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2Vs"
    "Zi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6"
    "CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAg"
    "ICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgog"
    "ICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNw"
    "b25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikK"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUp"
    "KQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VS"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNz"
    "aWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25k"
    "cyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0"
    "byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNU"
    "LgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAg"
    "IElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAg"
    "dG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoK"
    "ICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAg"
    "ZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0"
    "IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25z"
    "ZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBv"
    "ZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5U"
    "SU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAg"
    "ICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFs"
    "IGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGlu"
    "ZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFyZSBh"
    "biBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0"
    "aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0i"
    "IiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIs"
    "ICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0"
    "cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAg"
    "YW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkK"
    "ICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAg"
    "ICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1"
    "bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVu"
    "YWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFy"
    "ZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAg"
    "QlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVT"
    "SVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRl"
    "ZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9u"
    "X3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAg"
    "IOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lv"
    "bl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJy"
    "ZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9t"
    "bHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0"
    "aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3"
    "aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8i"
    "LAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5k"
    "aXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lz"
    "dGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVs"
    "eSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3Rocywg"
    "YW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0"
    "byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qg"
    "c2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMg"
    "cmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBj"
    "aGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0s"
    "IHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMg"
    "e0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAg"
    "IF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEg"
    "bW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZv"
    "ciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZs"
    "ZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRo"
    "aXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFz"
    "cyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAg"
    "ICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5v"
    "IHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGlu"
    "ZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNh"
    "dGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRo"
    "ZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJy"
    "YW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAg"
    "ICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAg"
    "ICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRo"
    "ZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhh"
    "dmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwK"
    "ICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGlj"
    "dF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAg"
    "ICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAg"
    "c2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAg"
    "ICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRl"
    "eHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2Ug"
    "IkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5f"
    "dmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "c3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20g"
    "bGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAg"
    "ICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0"
    "ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBp"
    "cmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAg"
    "ICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xl"
    "OiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUg"
    "b3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYu"
    "IFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBz"
    "dGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0"
    "byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgK"
    "ICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAg"
    "ICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxm"
    "LnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNl"
    "bGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIp"
    "CgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRo"
    "cmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBF"
    "bWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3Nh"
    "Z2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDi"
    "gJQgVHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVzc2Fn"
    "ZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBT"
    "aWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9y"
    "OiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoK"
    "ICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRh"
    "cHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAg"
    "ICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYgc3Vj"
    "Y2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29u"
    "ZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAg"
    "ICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1"
    "bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkK"
    "CiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAgICAg"
    "IHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAg"
    "ICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQo"
    "Ik9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2Uu"
    "ZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQog"
    "ICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAg"
    "ICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAgICAg"
    "aWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJ"
    "IGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1p"
    "dChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBp"
    "bnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxz"
    "ZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5k"
    "V29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50"
    "cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNv"
    "dW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRz"
    "IG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0"
    "cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1"
    "dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRl"
    "ZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdldChWYW1waXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmljIGZvb3Rl"
    "ciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2VyIGJsb2NrLiIiIgoKCmNsYXNzIEZhY2VUaW1lck1hbmFn"
    "ZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVsZXM6CiAgICAt"
    "IEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElmIHVz"
    "ZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAn"
    "YWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1"
    "dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNr"
    "IGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWly"
    "cm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IK"
    "ICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQogICAg"
    "ICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2Vs"
    "Zi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYs"
    "IGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRp"
    "bWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlvbikK"
    "ICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAg"
    "ICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBuZXdf"
    "ZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRz"
    "IGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRp"
    "YXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UK"
    "ICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9u"
    "KG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2Nr"
    "ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "aXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJW"
    "SUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9j"
    "cyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMu"
    "anNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2dsZUNh"
    "bGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQ"
    "YXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9w"
    "YXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYs"
    "IGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkK"
    "ICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAg"
    "ZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7"
    "c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRv"
    "a2VuX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6IHtzZWxmLmNy"
    "ZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6"
    "IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRl"
    "dGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRp"
    "bWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYg"
    "bm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAg"
    "ICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVk"
    "ZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVk"
    "ID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3Jl"
    "ZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAg"
    "ICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAg"
    "ICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQg"
    "Y3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gUmVm"
    "cmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZy"
    "ZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAg"
    "ICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dM"
    "RV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90"
    "IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29n"
    "bGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJv"
    "bV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAg"
    "ICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAg"
    "ICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3Nh"
    "Z2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRo"
    "aXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3Nf"
    "bWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3Io"
    "Ik9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0"
    "X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nl"
    "c3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0Nh"
    "bF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJh"
    "aXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVp"
    "bGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVu"
    "dGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5r"
    "X2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBsb2Nh"
    "bF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAg"
    "ICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAg"
    "ICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90emlu"
    "Zm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZvKSwKICAgICAgICAgICAgICAgIGxvY2Fs"
    "X3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoKICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9u"
    "LmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAg"
    "ICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRl"
    "KQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgogICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmlu"
    "dCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAg"
    "ICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FfS4iCiAgICAgICAgKQogICAgICAg"
    "IHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0"
    "YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRh"
    "c2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAgICAg"
    "IGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlu"
    "a19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRp"
    "bWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3Rh"
    "cnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFy"
    "dF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6"
    "b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBv"
    "ciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICAgICAiZW5kIjogeyJkYXRlVGltZSI6"
    "IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQogICAg"
    "ICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2Fs"
    "ZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtERUJVR10g"
    "RXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0bGU9J3tldmVudF9wYXlsb2FkLmdldCgnc3Vt"
    "bWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5n"
    "ZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0"
    "Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQo"
    "J2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQu"
    "Z2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRl"
    "ZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50"
    "X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNj"
    "ZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhj"
    "ZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAgICBpZiBo"
    "YXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQog"
    "ICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9l"
    "eC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29nbGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAg"
    "ICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBib2R5OiB7"
    "YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWls"
    "X21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3"
    "aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0aF9w"
    "YXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlm"
    "IG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUg"
    "ZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAg"
    "ICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3Nl"
    "cnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRh"
    "cl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkLmdl"
    "dCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3ByaW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tl"
    "bjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAg"
    "ICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQu"
    "CiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTog"
    "aW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWlu"
    "IG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2FuY2Vs"
    "bGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAg"
    "ICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkgPSB7CiAg"
    "ICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVl"
    "LAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rv"
    "a2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2Fs"
    "ZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAg"
    "InNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZXN1bHRzIjogMjUwLAogICAgICAgICAgICAgICAgIm9y"
    "ZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAg"
    "IHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNfdG9r"
    "ZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygp"
    "Lmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMi"
    "LCBbXSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAg"
    "ICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAgICBpZiBub3QgcGFnZV90b2tl"
    "bjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAgICAg"
    "ICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rv"
    "a2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9l"
    "dmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAg"
    "ICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZl"
    "bnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAg"
    "ZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4"
    "LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAgICAg"
    "ICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYs"
    "IGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBpZiBz"
    "ZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICB0YXJnZXRfY2Fs"
    "ZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRhcmdl"
    "dF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNl"
    "cnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwgbG9n"
    "Z2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRv"
    "a2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2Nz"
    "X3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTog"
    "c3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAgICBz"
    "ZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAg"
    "ICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxm"
    "LnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50"
    "aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBz"
    "ZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgog"
    "ICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAg"
    "ICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAg"
    "IGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9y"
    "KAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYu"
    "Y3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tl"
    "bl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2Vy"
    "X2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxp"
    "ZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihH"
    "T09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJl"
    "c2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3Qo"
    "KSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9r"
    "ZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9Igog"
    "ICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAg"
    "ICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRz"
    "X2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZs"
    "b3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9i"
    "cm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpc"
    "bnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50"
    "aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1"
    "cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iLCBs"
    "ZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2co"
    "ZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAg"
    "ICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3JlZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlm"
    "IHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAg"
    "ICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRz"
    "KQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHNl"
    "bGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6"
    "CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAg"
    "ICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgcmFpc2UK"
    "CiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0g"
    "MTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9y"
    "ICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRl"
    "ZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2"
    "ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0"
    "cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEwMCksIDIwMCkp"
    "LAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0o"
    "CiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdl"
    "YlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUsZW1h"
    "aWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAgICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAg"
    "ZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1p"
    "bWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbVsiaXNfZm9sZGVyIl0gPSBt"
    "aW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9j"
    "Il0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJp"
    "dmUgaXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikK"
    "ICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6"
    "IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50"
    "IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nf"
    "c2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9jLmdl"
    "dCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50Iiwg"
    "W10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBoID0g"
    "YmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVtZW50cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwg"
    "aW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRSdW4iKQogICAgICAgICAgICAgICAgaWYgbm90"
    "IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250ZW50"
    "Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAg"
    "ICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBs"
    "ZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsg"
    "IuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lk"
    "IjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAgICJw"
    "cmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAgICAg"
    "ICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9m"
    "b2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNv"
    "cmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAg"
    "ICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAg"
    "Y3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAg"
    "ICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29n"
    "bGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAg"
    "IH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIs"
    "CiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxm"
    "LmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAgICAgICByZXR1cm4gewogICAgICAgICAgICAi"
    "aWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAgICAg"
    "ICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50"
    "IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAgICAgIndlYlZp"
    "ZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMi"
    "KSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIgPSAi"
    "TmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3Ig"
    "Ik5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgogICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xk"
    "ZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBj"
    "cmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAg"
    "ICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xl"
    "LWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwK"
    "ICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAg"
    "ICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIGdldF9maWxlX21ldGFkYXRhKHNlbGYsIGZp"
    "bGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQg"
    "aXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3Nl"
    "cnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUs"
    "bWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBk"
    "ZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRh"
    "dGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lk"
    "OgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVf"
    "c2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1"
    "dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19p"
    "ZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAg"
    "ICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3Nl"
    "cnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAgICAgICAg"
    "ZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAg"
    "ICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgi"
    "LCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAiIikKCiAgICBkZWYgZG93bmxvYWRfZmls"
    "ZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1"
    "ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVy"
    "biBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg4pSA"
    "4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5l"
    "ZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJl"
    "IGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNz"
    "aW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNL"
    "IOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNr"
    "ZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAg"
    "IOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2ZSwg"
    "bG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBGb3Ji"
    "aWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFz"
    "ay9yZW1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBD"
    "SEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFs"
    "bCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBt"
    "ZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkg"
    "Y3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3Jp"
    "dGljYWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAg"
    "ICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJs"
    "b2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0"
    "YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAg"
    "IFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAg"
    "ICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVk"
    "IGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAgICAg"
    "ICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAg"
    "ICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAg"
    "ICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMi"
    "LCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVx"
    "dWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxz"
    "ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgt"
    "b2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xl"
    "LWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAg"
    "ICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3JjaCAgKG9u"
    "bHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycyIsICAgICAgICAgICAgICAidHJhbnNm"
    "b3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZv"
    "ciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkgbmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0"
    "b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxp"
    "c3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAg"
    "ICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAgICAgIGNyaXRp"
    "Y2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAg"
    "ICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAg"
    "ICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAg"
    "IG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoK"
    "ICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxzZSAib3B0aW9uYWwiCiAgICAgICAg"
    "ICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0"
    "dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAg"
    "ICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgog"
    "ICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNscykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFt"
    "YSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJs"
    "bGliLnJlcXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1"
    "cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAg"
    "ICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDi"
    "gJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilIAgTUVNT1JZIE1BTkFH"
    "RVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRsZXMg"
    "YWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMu"
    "anNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29u"
    "bCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAg"
    "ICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5k"
    "IG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcg"
    "Z2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250ZXh0"
    "IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0gY2Zn"
    "X3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAg"
    "ICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0YXRlX3AgICAgID0gYmFz"
    "ZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAgPSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDilIDi"
    "lIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAg"
    "IGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0"
    "Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoK"
    "ICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90"
    "ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgog"
    "ICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBlcnNvbmFf"
    "bmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tfdmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9W"
    "RVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAgICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1"
    "cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3duIjogICAgICAgICAgICBOb25lLAogICAgICAg"
    "ICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogICAgICAg"
    "ICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAg"
    "ICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNl"
    "c3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3Ry"
    "ID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJz"
    "ZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJy"
    "b2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6"
    "ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAg"
    "ICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlz"
    "dFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAg"
    "TUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJf"
    "dGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAg"
    "ICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtl"
    "eXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdz"
    "ICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUg"
    "ICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5"
    "ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVt"
    "b3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAg"
    "ICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAg"
    "ICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBl"
    "IjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAg"
    "ICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRb"
    "OjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAg"
    "ImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAg"
    "ICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFtIiwi"
    "aXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0K"
    "CiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAg"
    "ICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2Vh"
    "cmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgog"
    "ICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMg"
    "c29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYg"
    "bm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3Jp"
    "ZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgog"
    "ICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBb"
    "XQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdv"
    "cmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRl"
    "bS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAgICAg"
    "ICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdldCgi"
    "dGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJt"
    "cyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5s"
    "b3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwg"
    "YW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0"
    "YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNj"
    "b3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNj"
    "b3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBp"
    "dGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSks"
    "CiAgICAgICAgICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29y"
    "ZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9"
    "IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVt"
    "b3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBj"
    "b250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LCBs"
    "aW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJb"
    "UkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAg"
    "ICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgndGl0"
    "bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBh"
    "cnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltF"
    "TkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAg"
    "ICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQo"
    "InRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dl"
    "cigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIp"
    "Lmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIiku"
    "bG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFn"
    "cyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3Ry"
    "XSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQog"
    "ICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0"
    "YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAg"
    "aWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJz"
    "ZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGlu"
    "IHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAg"
    "ICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0"
    "ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgog"
    "ICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAg"
    "ICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29y"
    "ZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBz"
    "dHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRh"
    "bGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3Jk"
    "X3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBt"
    "ZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVybiBm"
    "IlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAgICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAg"
    "ICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdv"
    "cmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1"
    "ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9y"
    "ICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1"
    "cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVz"
    "b2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsnICcu"
    "am9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAg"
    "ICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICBy"
    "ZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNl"
    "cl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVz"
    "ZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiBy"
    "ZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAg"
    "aWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJlY29y"
    "ZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiBy"
    "ZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29y"
    "ZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJD"
    "b252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNh"
    "dmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxl"
    "OiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9u"
    "cy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29u"
    "dGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1"
    "aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNl"
    "bGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAg"
    "ICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczog"
    "bGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUg"
    "b2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTog"
    "c3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0g"
    "IiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNn"
    "X3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19p"
    "c28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICBjb250ZW50LAogICAg"
    "ICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0"
    "W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAg"
    "W3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJu"
    "IFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9y"
    "IG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAg"
    "ICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5f"
    "c2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJldHVy"
    "biBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZl"
    "IGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUg"
    "Zm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5q"
    "c29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGgg"
    "PSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAg"
    "ICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGlu"
    "ZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBp"
    "bmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0gYWlf"
    "Z2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBu"
    "b3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdl"
    "IChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250ZW50"
    "Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAgICAgICAgICAgICAgICAiIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIg"
    "Ii5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICAg"
    "ICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAog"
    "ICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21l"
    "c3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9tZXNz"
    "YWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNl"
    "bGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGlu"
    "ZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50cnkpCgogICAgICAgICMgS2Vl"
    "cCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1"
    "XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9z"
    "ZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3"
    "ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRl"
    "ZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAg"
    "ICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3Jt"
    "YXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5"
    "IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1l"
    "bW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nl"
    "c3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAg"
    "ICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0"
    "ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAg"
    "ICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAgICJV"
    "c2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxh"
    "c3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAg"
    "ICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgi"
    "Y29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAg"
    "ICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJb"
    "RU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5h"
    "bChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVm"
    "IGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pv"
    "dXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJv"
    "b2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgog"
    "ICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgog"
    "ICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0g"
    "PSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAgcmV0"
    "dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2lu"
    "ZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJl"
    "dHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChz"
    "ZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAg"
    "IGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05T"
    "IExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdl"
    "IGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAg"
    "ICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAg"
    "ICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9u"
    "LCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFu"
    "Z3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVwbGljYXRp"
    "bmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19w"
    "YXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmlyb25tZW50OiBz"
    "dHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6"
    "IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkg"
    "LT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVp"
    "ZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAg"
    "ImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAg"
    "ICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnks"
    "CiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29s"
    "dXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdz"
    "IG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAg"
    "ICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNo"
    "KHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3Ry"
    "ID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1"
    "bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGlm"
    "IGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAg"
    "ICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93"
    "ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAg"
    "ICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVu"
    "Y2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAgICAg"
    "ICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBjb250"
    "aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdldF9hbGwo"
    "c2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUo"
    "c2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAg"
    "ICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlm"
    "IGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVk"
    "KQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9s"
    "YW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczog"
    "aW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVz"
    "IGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2Rl"
    "IHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAg"
    "ICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51"
    "cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZv"
    "ciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5n"
    "ZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAg"
    "ICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50"
    "cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJu"
    "ICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6"
    "CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVy"
    "ZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAg"
    "IGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRk"
    "ZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxl"
    "cyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5f"
    "cGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAg"
    "ICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBMU0wi"
    "LAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAg"
    "ICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAg"
    "ICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19G"
    "T1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBubyBm"
    "b3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRleCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5n"
    "dGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0"
    "TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lH"
    "Tl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNh"
    "bGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0"
    "aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAg"
    "ICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAog"
    "ICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLiki"
    "LCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAgIk5vIHZvaWQg"
    "a2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlv"
    "biByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0"
    "aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAg"
    "ICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAg"
    "ICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNv"
    "bXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5n"
    "IExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92"
    "aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRo"
    "ZSBmdWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNj"
    "cmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1t"
    "YXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxh"
    "bmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAgICB0YWdzPVsi"
    "bHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBk"
    "dWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25sCgogICAgVGFzayByZWNvcmQgZmllbGRz"
    "OgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwg"
    "c3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdl"
    "ZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8"
    "Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAg"
    "ICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0"
    "cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5k"
    "b3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAg"
    "ICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8g"
    "InRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9h"
    "bGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFu"
    "Z2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYg"
    "bm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBp"
    "biB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAg"
    "ICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVf"
    "YXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAgIGNo"
    "YW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAgICJwZW5kaW5nIikKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3ds"
    "ZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVf"
    "YW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2NhbCIp"
    "CiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVs"
    "dCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAg"
    "ICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAg"
    "ICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQg"
    "bm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAg"
    "ICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAg"
    "ICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAg"
    "ICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBj"
    "aGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBub3Jt"
    "YWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAg"
    "ICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1p"
    "bnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlk"
    "NCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAg"
    "ICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgInBy"
    "ZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAg"
    "ICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAg"
    "ICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAgICAg"
    "ICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAgICAg"
    "ICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwKICAgICAg"
    "ICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwK"
    "ICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxs"
    "KCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0"
    "YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYu"
    "bG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgog"
    "ICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAg"
    "ICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5z"
    "YXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxl"
    "dGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQog"
    "ICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAg"
    "ICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0g"
    "PSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1"
    "cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2Rp"
    "Y3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlm"
    "IHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQi"
    "CiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xl"
    "YXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQg"
    "ICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsiY29t"
    "cGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYg"
    "cmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVmIHVw"
    "ZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAi"
    "IikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNr"
    "czoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0g"
    "ICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAg"
    "ICAgICAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0g"
    "Z29vZ2xlX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1bHQo"
    "Im1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiXVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVy"
    "cm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAg"
    "ICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
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
    "aykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGludGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUs"
    "IERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg"
    "4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0"
    "b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3Jpbmcp"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBO"
    "VklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikK"
    "CgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBM"
    "ZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVk"
    "IG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKA"
    "lCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNU"
    "YWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg"
    "4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVkIGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg"
    "4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAg"
    "ICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgICDigJQg"
    "Z290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFja2VyVGFiICAg4oCUIGZ1bGwgcmVidWls"
    "ZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtz"
    "cGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAg"
    "ICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1cnUgb3V0"
    "cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZv"
    "cmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3dzZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgoj"
    "IOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dvdGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVy"
    "biBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAg"
    "IGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAg"
    "ICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsK"
    "ICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVk"
    "IHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJ"
    "R0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dy"
    "b3VuZDoge0NfQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAgIGJhY2tn"
    "cm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xk"
    "OwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIKCmRlZiBfZ290aGljX2J0bih0ZXh0"
    "OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBi"
    "dG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAi"
    "CiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgZiJm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAg"
    "IGJ0bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxh"
    "YmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xE"
    "fTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBUQUIg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAg"
    "IFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4KICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAt"
    "IENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAgICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2Vy"
    "KQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwgZGVz"
    "Y3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHByZXNlbnQpCiAg"
    "ICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAg"
    "LSBDb3B5LXRvLWNsaXBib2FyZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6"
    "IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAg"
    "ID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtd"
    "CiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJv"
    "eExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRT"
    "cGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9i"
    "dG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAgICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQogICAgICAg"
    "IHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQog"
    "ICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9m"
    "IHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAg"
    "ICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRu"
    "X21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9k"
    "b19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5fYnRuX21v"
    "ZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRuX3JlcGFyc2UpOgogICAgICAgICAgICBi"
    "YXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAg"
    "ICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBR"
    "U3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ssIDEpCgogICAgICAgICMg4pSA4pSAIFBB"
    "R0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5"
    "b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xs"
    "ID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAg"
    "IHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAg"
    "ICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAgID0gUVZCb3hM"
    "YXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0"
    "LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAg"
    "ICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAg"
    "ICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAgICAgICBsMS5zZXRD"
    "b250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9z"
    "ZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4g"
    "dGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5f"
    "YWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX2Rlc2MpCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5f"
    "YWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAg"
    "ICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFtcHMg"
    "bGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVtcyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBsMS5h"
    "ZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAjIFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRk"
    "V2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcg"
    "PSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsi"
    "SXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRk"
    "X3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0TWF4aW11bUhlaWdodCgxMjApCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDEuYWRkV2lk"
    "Z2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2"
    "aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2"
    "ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRk"
    "KQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAg"
    "ICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQoYzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5h"
    "ZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDI6"
    "IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0"
    "LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAg"
    "ICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1z"
    "aXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90"
    "YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5f"
    "ZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJs"
    "ZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNv"
    "bnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4dE1l"
    "bnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0X21lbnUpCgogICAgICAgIGwyLmFkZFdp"
    "ZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRX"
    "aWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRl"
    "bSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlfaGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNr"
    "IikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAg"
    "ICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQ"
    "QUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJn"
    "aW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxm"
    "Ll9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBz"
    "ZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwz"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5f"
    "bW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJM"
    "YWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2Vs"
    "Zi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFi"
    "bGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2Vs"
    "IikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25u"
    "ZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0"
    "bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91dChidG5zMykKICAgICAgICBz"
    "ZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRp"
    "Y21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAg"
    "ICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQgaW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAg"
    "S0VZIEZJWDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGlt"
    "ZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0OgogICAg"
    "ICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRl"
    "bSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAgIGlm"
    "IG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwgW10KCiAgICAgICAgIyDilIDilIAgU3RlcCAx"
    "OiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0YW1wcyDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGlu"
    "ZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDi"
    "lIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1l"
    "ID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMg"
    "YXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihcd1tc"
    "d1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAg"
    "ICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVudCA9IF9yZS5zdWIocideXFtcZHsxLDJ9Olxk"
    "ezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50"
    "cyIgaW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgY29udGVudC5sb3dl"
    "cigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlk"
    "ZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5n"
    "LiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9IGNvbnRlbnQu"
    "c3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5lCgogICAgICAgICAgICAjIFRy"
    "eSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRl"
    "bV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICBy"
    "J0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJp"
    "cCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAg"
    "ICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAgIGl0"
    "ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0"
    "ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAgICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFt"
    "ZSkgPiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVhdG9y"
    "fSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA4pSAIENBUkQgUkVOREVSSU5HIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWls"
    "ZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAg"
    "ICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0"
    "LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxl"
    "dGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9IHNlbGYuX21ha2Vf"
    "Y2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6"
    "IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJy"
    "ZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1y"
    "YWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAg"
    "ICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5n"
    "ZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19HT0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAg"
    "Y291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsKGYie2NvdW50fSBpdGVt"
    "cyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250"
    "LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwg"
    "PSBRTGFiZWwocmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBzZWxlY3QKICAgICAgICByZWNfaWQg"
    "PSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVj"
    "X2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYs"
    "IHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2Vs"
    "Zi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRf"
    "cmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3IgciBp"
    "biBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAog"
    "ICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAg"
    "IyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGluIHNl"
    "bGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgICAgICAgICAgICByWyJyZWNv"
    "cmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQog"
    "ICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJl"
    "dmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAg"
    "IG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9s"
    "ZGVyVGV4dChuYW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0"
    "ZW1zWzoyMF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkK"
    "ICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNl"
    "dEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRlZiBfc2hvd19hZGQoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9z"
    "dGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxm"
    "Ll9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAg"
    "ICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRpbWUu"
    "bm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "IHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAg"
    "ICAgIm5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9h"
    "ZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAgICAg"
    "InJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0"
    "IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQogICAgICAgIHdyaXRlX2pzb25s"
    "KHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRbInJlY29yZF9pZCJd"
    "CiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9"
    "IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3Jt"
    "YXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4g"
    "dG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVj"
    "LmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIi"
    "KSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1z"
    "IixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90"
    "YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAg"
    "ICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVt"
    "KHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAg"
    "ICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2NvbnRleHRfbWVudShzZWxmLCBwb3MpIC0+"
    "IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBvcykKICAgICAgICBpZiBub3QgaWR4LmlzVmFs"
    "aWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJv"
    "dygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0"
    "b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJs"
    "ZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAg"
    "IG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBJdGVtIE5hbWUiKQogICAgICAgIGFf"
    "Y3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9u"
    "KCJDb3B5IEJvdGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9H"
    "bG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKQogICAgICAgIGlmIGFjdGlvbiA9PSBhX2l0"
    "ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChj"
    "cmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0"
    "b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVj"
    "b3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2Nh"
    "bnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2Vs"
    "Zi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRS"
    "b3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fbW9k"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxm"
    "Ll9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIi"
    "KSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJ"
    "dGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgog"
    "ICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgp"
    "CiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5f"
    "bW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9k"
    "X2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJs"
    "ZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0"
    "SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRn"
    "ZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktOT1dO"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICBy"
    "ZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVk"
    "X3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNM"
    "IFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAgICByZXBseSA9"
    "IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0"
    "ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9u"
    "LlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29y"
    "ZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRd"
    "CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3NlbGVj"
    "dGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3"
    "X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJS"
    "ZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJObyByYXcgdGV4dCBzdG9yZWQgZm9yIHRoaXMg"
    "c2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykK"
    "ICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBv"
    "ciBuYW1lCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQog"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAg"
    "ICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFuZCBy"
    "ZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24g"
    "cGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgog"
    "ICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxm"
    "LnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRk"
    "IikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9k"
    "ZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3RoaWNfYnRuKCLi"
    "p4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJDb3B5IHNlbGVjdGVkIGNv"
    "bW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikK"
    "ICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlm"
    "eS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5k"
    "KQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4g"
    "KHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRk"
    "U3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgw"
    "LCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9u"
    "Il0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAg"
    "ICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigp"
    "LnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlv"
    "bkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdl"
    "dChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAgICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xp"
    "Y2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJl"
    "ZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAg"
    "IHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBy"
    "ID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5k"
    "IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJ"
    "dGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNh"
    "dGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICAgICAgIGRs"
    "Zy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFG"
    "b3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0u"
    "YWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBi"
    "dG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2Fu"
    "Y2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0"
    "KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykK"
    "ICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0"
    "ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgICAgICAgICAgICAgImlk"
    "IjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0"
    "cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAg"
    "ICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAgICAg"
    "ICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAgICAgICAgICAg"
    "ICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAg"
    "ICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBy"
    "ZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1Rp"
    "dGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xv"
    "cjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQocmVj"
    "LmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAg"
    "ICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2Mp"
    "CiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhp"
    "Y19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3Qo"
    "ZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRk"
    "Um93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAg"
    "IHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9u"
    "Il0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5v"
    "dyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBy"
    "b3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jk"
    "cyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQiLCJ0aGlz"
    "IGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUi"
    "LCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9iIGFw"
    "cGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUs"
    "IERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENT"
    "ViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVjdGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp1"
    "c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVk"
    "IiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50"
    "PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgi"
    "bWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAg"
    "ICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAg"
    "ICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAg"
    "IGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAgPSBfZ290aGlj"
    "X2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBj"
    "b21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZlZCBhcHBsaWNhdGlvbnMiKQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhp"
    "Y19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAg"
    "ICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdG9n"
    "Z2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0"
    "TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "bW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYu"
    "X2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "dG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAg"
    "ICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBR"
    "VGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxh"
    "YmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENv"
    "bXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcu"
    "UmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1v"
    "ZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDigJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENv"
    "bHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAg"
    "IGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlv"
    "bkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1v"
    "ZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdl"
    "dChzZWxmLl90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSBy"
    "ZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGlu"
    "IHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAg"
    "ICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAg"
    "ICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAg"
    "ICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAg"
    "ICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0"
    "KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAgICAgICAgICAg"
    "ICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3RhdHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgibm90"
    "ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAgICAg"
    "ICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAgICAgICAg"
    "ICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldEl0ZW0ociwgYywgaXRlbSkKICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNl"
    "ciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0ZW1E"
    "YXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5kZXgocmVjKQogICAgICAgICAgICApCgog"
    "ICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAg"
    "ICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFi"
    "bGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAgICAgICAgIGlkeCA9IHJvd19p"
    "dGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAgICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9k"
    "aWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2Vs"
    "ZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQo"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAg"
    "ICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFueSIs"
    "IiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYg"
    "cmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVl"
    "KQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAgIGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0"
    "ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5"
    "eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQogICAg"
    "ICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHN0YXR1cyAg"
    "PSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBub3Rl"
    "cyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lk"
    "Z2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSksCiAgICAgICAg"
    "ICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXMp"
    "LCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAg"
    "ICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0"
    "bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcu"
    "cmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "YnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJl"
    "dHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAg"
    "ICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBk"
    "ZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRleHQo"
    "KS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGll"
    "ZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAg"
    "ICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2RpYWxvZygp"
    "CiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51"
    "dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51"
    "dWlkNCgpKSwKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6"
    "IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgICAgbm93"
    "LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMpICE9IDE6CiAgICAgICAg"
    "ICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0g"
    "c2VsZi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1l"
    "Lm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3Jk"
    "cykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHgg"
    "aW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhd"
    "LmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3Jt"
    "YXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAo"
    "CiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMo"
    "KToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tp"
    "ZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0g"
    "PSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygp"
    "CiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rp"
    "b24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBh"
    "cHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5Z"
    "ZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJv"
    "eC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IHNldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRz"
    "ID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYg"
    "aSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAg"
    "ICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRlbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3df"
    "aGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAg"
    "ICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwg"
    "ZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIs"
    "CiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NW"
    "IEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNlICIs"
    "IgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBwbGllZCIsImxpbmsiLAogICAgICAgICAg"
    "ICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBvcGVuKHBhdGgs"
    "ICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhl"
    "YWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxzID0g"
    "WwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJq"
    "b2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAg"
    "ICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiksCiAgICAg"
    "ICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICAgICAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAg"
    "ICAgICAgICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAgc3Ry"
    "KHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAgIGZvciB2IGluIHZhbHMK"
    "ICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgog"
    "ICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxm"
    "KQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNl"
    "bGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0aDogTXkgRHJpdmUiKQogICAg"
    "ICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0Nf"
    "R09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxm"
    "LnJlY29yZHNfbGlzdCwgMSkKCiAgICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0"
    "ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0"
    "fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAg"
    "ICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIK"
    "ICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGlm"
    "IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCf"
    "k4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAg"
    "ICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4Qi"
    "CiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVkVGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwg"
    "IiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAgICBb"
    "e21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkK"
    "ICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBz"
    "ZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7"
    "bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRhc2sg"
    "cmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAg"
    "c2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxl"
    "dGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAg"
    "ICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAog"
    "ICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5v"
    "bmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0g"
    "dGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4gPSBvbl9hZGRfZWRpdG9yX29wZW4KICAgICAg"
    "ICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2Vs"
    "X3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2ds"
    "ZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBz"
    "ZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBv"
    "bl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZiBfYnVpbGRf"
    "dWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRz"
    "TWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNr"
    "ID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAg"
    "ICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5v"
    "cm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRTcGFjaW5n"
    "KDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIp"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBub3Jt"
    "YWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50"
    "YXNrX2ZpbHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJXRUVL"
    "IiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEgiLCAibW9udGgiKQogICAgICAg"
    "IHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21i"
    "by5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29u"
    "bmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9jaGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8u"
    "Y3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNl"
    "bGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9ybWFsX2xheW91"
    "dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291"
    "cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVj"
    "dGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0"
    "SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRy"
    "aWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRv"
    "Q29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9u"
    "X3N0YXRlKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9u"
    "cyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRB"
    "U0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0bigiQ09NUExFVEUgU0VMRUNURUQiKQogICAg"
    "ICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5f"
    "dG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29t"
    "cGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0"
    "RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBi"
    "dG4gaW4gKAogICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBs"
    "ZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29t"
    "cGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgKToKICAgICAgICAgICAgYWN0aW9u"
    "cy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jr"
    "c3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAgZWRpdG9yX2xh"
    "eW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAw"
    "LCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9z"
    "ZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09HTEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0"
    "YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4i"
    "KQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzog"
    "NnB4OyIKICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFi"
    "ZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25h"
    "bWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgRGF0"
    "ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRl"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90"
    "aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5k"
    "IFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNl"
    "bGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNl"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9y"
    "X2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQo"
    "KQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50"
    "YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSwKICAgICAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAg"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW91dC5h"
    "ZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkK"
    "ICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9h"
    "Y3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAgIGJ0bl9j"
    "YW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRp"
    "dG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAg"
    "ICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9j"
    "YW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0"
    "KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChlZGl0b3IpCgogICAgICAgIHNl"
    "bGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dvcmtzcGFjZSA9IGVkaXRvcgogICAgICAg"
    "IHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBk"
    "YXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVk"
    "X3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2Vs"
    "Zi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGRlZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBs"
    "aXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQogICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJs"
    "ZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAgICAg"
    "ICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90IHN0"
    "YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0"
    "dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBu"
    "b3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMKCiAgICBkZWYg"
    "bG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0Um93"
    "Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0Nv"
    "dW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNr"
    "LmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3Rh"
    "dHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJk"
    "dWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAgICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJS"
    "ZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9y"
    "ICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29u"
    "fSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNr"
    "LmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNl"
    "bGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAgICAgICAgICAgc2VsZi50YXNr"
    "X3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwu"
    "c2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9u"
    "X3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xv"
    "Z2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0"
    "b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRy"
    "KHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQgaGFzYXR0cih0"
    "aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAgICAgICAgICBzZWxmLl9kaWFnKAogICAgICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17"
    "cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdGhyZWFkLndhaXQo"
    "MjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtl"
    "eH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVz"
    "aF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RvcF9y"
    "ZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoK"
    "ICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93"
    "X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRleHQoIkhJREUg"
    "Q09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVBMRVRFRCIpCgogICAgZGVmIHNldF9zdGF0"
    "dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBv"
    "ayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9"
    "OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRl"
    "eHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3Vy"
    "cmVudFdpZGdldChzZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNl"
    "bGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVz"
    "OiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxpc3Qg"
    "ZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYWwgbG9h"
    "ZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdh"
    "eXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBo"
    "ZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJ"
    "VkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAg"
    "IHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIp"
    "CiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxh"
    "eSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1lc3Rh"
    "bXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5B"
    "UlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFM"
    "IjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6"
    "ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xE"
    "KQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8"
    "c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwv"
    "c3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxC"
    "YXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAg"
    "ICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKU"
    "gCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQp"
    "OgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9u"
    "IHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVz"
    "LCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29n"
    "bGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJv"
    "b3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIg"
    "PSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAg"
    "ICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2Vs"
    "Zi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtD"
    "X1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGlu"
    "ZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNl"
    "bGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGlt"
    "ZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklORk8iOiAg"
    "Q19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAgICAgICJXQVJOIjogIENfR09MRCwKICAgICAg"
    "ICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAg"
    "Y29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBw"
    "ZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAn"
    "CiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXku"
    "dmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1lc3NhZ2VzOiBs"
    "aXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAg"
    "ICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVs"
    "aWYgIuKclyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZs"
    "ID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0"
    "IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoK"
    "ICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0"
    "KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3Nl"
    "YXJjaCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3NvbnMu"
    "Li4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJ"
    "dGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJl"
    "ZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQog"
    "ICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAg"
    "IGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3cp"
    "CgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIExl"
    "c3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAg"
    "ICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBi"
    "dG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0g"
    "UVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAgICAg"
    "ICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJvbm1lbnQiXQogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDIsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAg"
    "ICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5z"
    "ZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJs"
    "ZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0"
    "KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwKICAgICAgICBzcGxpdHRlciA9IFFTcGxp"
    "dHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAg"
    "ICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQg"
    "PSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQs"
    "IDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAg"
    "ICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlID0gX2dvdGhpY19idG4oIkVk"
    "aXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9y"
    "dWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3Rv"
    "Z2dsZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBz"
    "ZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxl"
    "KEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQog"
    "ICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5h"
    "ZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVy"
    "KQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVl"
    "KQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIu"
    "c2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVj"
    "b3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2go"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxmLl9sYW5n"
    "X2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIiIGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAg"
    "c2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFi"
    "bGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0"
    "KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAg"
    "ICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0o"
    "ciwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVm"
    "IF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBz"
    "ZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAg"
    "ICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAg"
    "ICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjogIiAr"
    "IHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1"
    "bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVs"
    "ZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVkaXRp"
    "bmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307"
    "IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAg"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4"
    "OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250ZW50IG9uIGNhbmNlbAogICAgICAgICAg"
    "ICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBz"
    "ZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0"
    "ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFjayBv"
    "dXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAgIHBh"
    "cnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNb"
    "MF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFdLnN0cmlwKCkKICAgICAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jk"
    "c1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9"
    "IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAgICAg"
    "ICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0"
    "X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBMZXNzb24i"
    "KQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAg"
    "ICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGlu"
    "ZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYgID0gUUxpbmVFZGl0KCkKICAg"
    "ICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0KCkKICAgICAgICBydWxlLnNldE1heGltdW1I"
    "ZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQoKQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZv"
    "ciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICAg"
    "ICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBzdW1tKSwKICAgICAgICAgICAgKCJGdWxsIFJ1"
    "bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAgICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToK"
    "ICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9"
    "IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0"
    "bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9n"
    "LkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAgIGVudmlyb25tZW50"
    "PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAg"
    "ICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0"
    "KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxm"
    "Ll9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAg"
    "ICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAg"
    "ICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3Nh"
    "Z2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9k"
    "Yi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUgVFJBQ0tFUiBU"
    "QUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFs"
    "IG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRo"
    "ZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1lLCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAg"
    "IEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3Bl"
    "YywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29ubmVj"
    "dGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRl"
    "c2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgi"
    "bWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10K"
    "ICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAg"
    "IHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNf"
    "YnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9h"
    "ZGQsIHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBz"
    "ZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWluaW11"
    "bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZWRpdCkKICAgICAgICBzZWxm"
    "Ll9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlw"
    "dGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0"
    "aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9y"
    "KAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290"
    "aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9v"
    "bl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5W"
    "ZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAg"
    "ICAgICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193aWRn"
    "ZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91"
    "dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQog"
    "ICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVh"
    "ZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYu"
    "X25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0Nf"
    "R09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAg"
    "ICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5v"
    "dGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNw"
    "bGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVsKCIiKQogICAg"
    "ICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMg"
    "aW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5f"
    "dGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShy"
    "ZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0"
    "YXR1cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7"
    "CiAgICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICAgICAiRGVzaWduaW5n"
    "IjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG8gQnVpbGQiOiAgIENfUFVSUExFLAogICAgICAg"
    "ICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIsCiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAgICAg"
    "IENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICAg"
    "ICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24i"
    "LCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAg"
    "ICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkg"
    "KyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQog"
    "ICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAg"
    "IHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNl"
    "bGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAg"
    "ICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRleHQocmVj"
    "LmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9vcGVuX2VkaXRf"
    "ZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50"
    "Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0"
    "X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBkZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0"
    "ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNl"
    "dFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAg"
    "ICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5y"
    "ZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5l"
    "RWRpdChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRlclRl"
    "eHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzdGF0dXNfY29tYm8u"
    "YWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6CiAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5k"
    "VGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAgc3Rh"
    "dHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmllbGQgPSBRTGluZUVkaXQocmVjLmdldCgiZGVz"
    "Y3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxp"
    "bmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0"
    "UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNl"
    "cy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBsYWJl"
    "bCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1czoiLCBz"
    "dGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5vdGVz"
    "OiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "ICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkwKQogICAgICAgICAgICByb3df"
    "bGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAg"
    "Zm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2"
    "ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAg"
    "ICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChk"
    "bGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0"
    "bl9jYW5jZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9n"
    "LkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAg"
    "ICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZiByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAg"
    "ICAgICAgICJuYW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjog"
    "ICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2NfZmllbGQu"
    "dGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0"
    "cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNv"
    "Zm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVk"
    "IjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcm93ID49IDA6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9y"
    "ZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6"
    "CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAgICAg"
    "ICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAg"
    "ICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAg"
    "ICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFy"
    "ZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRf"
    "JUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAgICAg"
    "ICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAg"
    "ICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAg"
    "ICAgICAgICAgIGYiVG90YWwgbW9kdWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAs"
    "CiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAg"
    "ICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAgIGYiTU9EVUxFOiB7cmVjLmdldCgnbmFtZScs"
    "JycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAgICAg"
    "ICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgIiIs"
    "CiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAg"
    "ICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAiIiwK"
    "ICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rp"
    "bmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkK"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAg"
    "ICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xp"
    "cGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3gud2FybmluZyhzZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUpKQoKCgogICAgZGVmIF9wYXJzZV9pbXBvcnRfZW50cmllcyhz"
    "ZWxmLCByYXc6IHN0cikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiJQYXJzZSBpbXBvcnRlZCB0ZXh0IGludG8gb25lIG9yIG1v"
    "cmUgbW9kdWxlIHJlY29yZHMuIiIiCiAgICAgICAgbGFiZWxfbWFwID0gewogICAgICAgICAgICAibW9kdWxlIjogIm5hbWUiLAog"
    "ICAgICAgICAgICAic3RhdHVzIjogInN0YXR1cyIsCiAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6ICJkZXNjcmlwdGlvbiIsCiAg"
    "ICAgICAgICAgICJub3RlcyI6ICJub3RlcyIsCiAgICAgICAgICAgICJmdWxsIHN1bW1hcnkiOiAibm90ZXMiLAogICAgICAgIH0K"
    "CiAgICAgICAgZGVmIF9ibGFuaygpIC0+IGRpY3Q6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAibmFtZSI6"
    "ICIiLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICJJZGVhIiwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6ICIiLAog"
    "ICAgICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgIH0KCiAgICAgICAgZGVmIF9jbGVhbihyZWM6IGRpY3QpIC0+"
    "IGRpY3Q6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAibmFtZSI6IHJlYy5nZXQoIm5hbWUiLCAiIikuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAocmVjLmdldCgic3RhdHVzIiwgIiIpLnN0cmlwKCkgb3IgIklkZWEiKSwK"
    "ICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IHJlYy5nZXQoImRlc2NyaXB0aW9uIiwgIiIpLnN0cmlwKCksCiAgICAgICAg"
    "ICAgICAgICAibm90ZXMiOiByZWMuZ2V0KCJub3RlcyIsICIiKS5zdHJpcCgpLAogICAgICAgICAgICB9CgogICAgICAgIGRlZiBf"
    "aXNfZXhwb3J0X2hlYWRlcihsaW5lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgICAgIGxvdyA9IGxpbmUuc3RyaXAoKS5sb3dlcigp"
    "CiAgICAgICAgICAgIHJldHVybiAoCiAgICAgICAgICAgICAgICBsb3cuc3RhcnRzd2l0aCgiZWNobyBkZWNrIikgb3IKICAgICAg"
    "ICAgICAgICAgIGxvdy5zdGFydHN3aXRoKCJleHBvcnRlZDoiKSBvcgogICAgICAgICAgICAgICAgbG93LnN0YXJ0c3dpdGgoInRv"
    "dGFsIG1vZHVsZXM6Iikgb3IKICAgICAgICAgICAgICAgIGxvdy5zdGFydHN3aXRoKCJ0b3RhbCAiKQogICAgICAgICAgICApCgog"
    "ICAgICAgIGRlZiBfaXNfZGVjb3JhdGl2ZShsaW5lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgICAgIHMgPSBsaW5lLnN0cmlwKCkK"
    "ICAgICAgICAgICAgaWYgbm90IHM6CiAgICAgICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICAgICAgaWYgYWxsKGNoIGlu"
    "ICItPX5fKuKAosK34oCUICIgZm9yIGNoIGluIHMpOgogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICAgICAgaWYg"
    "KHMuc3RhcnRzd2l0aCgiPT09IikgYW5kIHMuZW5kc3dpdGgoIj09PSIpKSBvciAocy5zdGFydHN3aXRoKCItLS0iKSBhbmQgcy5l"
    "bmRzd2l0aCgiLS0tIikpOgogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAg"
    "ICAgIGRlZiBfaXNfc2VwYXJhdG9yKGxpbmU6IHN0cikgLT4gYm9vbDoKICAgICAgICAgICAgcyA9IGxpbmUuc3RyaXAoKQogICAg"
    "ICAgICAgICByZXR1cm4gbGVuKHMpID49IDggYW5kIGFsbChjaCBpbiAiLeKAlCIgZm9yIGNoIGluIHMpCgogICAgICAgIGVudHJp"
    "ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIGN1cnJlbnQgPSBfYmxhbmsoKQogICAgICAgIGN1cnJlbnRfZmllbGQ6IE9wdGlv"
    "bmFsW3N0cl0gPSBOb25lCgogICAgICAgIGRlZiBfaGFzX3BheWxvYWQocmVjOiBkaWN0KSAtPiBib29sOgogICAgICAgICAgICBy"
    "ZXR1cm4gYW55KGJvb2woKHJlYy5nZXQoaywgIiIpIG9yICIiKS5zdHJpcCgpKSBmb3IgayBpbiAoIm5hbWUiLCAic3RhdHVzIiwg"
    "ImRlc2NyaXB0aW9uIiwgIm5vdGVzIikpCgogICAgICAgIGRlZiBfZmx1c2goKSAtPiBOb25lOgogICAgICAgICAgICBub25sb2Nh"
    "bCBjdXJyZW50LCBjdXJyZW50X2ZpZWxkCiAgICAgICAgICAgIGNsZWFuZWQgPSBfY2xlYW4oY3VycmVudCkKICAgICAgICAgICAg"
    "aWYgY2xlYW5lZFsibmFtZSJdOgogICAgICAgICAgICAgICAgZW50cmllcy5hcHBlbmQoY2xlYW5lZCkKICAgICAgICAgICAgY3Vy"
    "cmVudCA9IF9ibGFuaygpCiAgICAgICAgICAgIGN1cnJlbnRfZmllbGQgPSBOb25lCgogICAgICAgIGZvciByYXdfbGluZSBpbiBy"
    "YXcuc3BsaXRsaW5lcygpOgogICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUucnN0cmlwKCJcbiIpCiAgICAgICAgICAgIHN0cmlw"
    "cGVkID0gbGluZS5zdHJpcCgpCgogICAgICAgICAgICBpZiBfaXNfc2VwYXJhdG9yKHN0cmlwcGVkKToKICAgICAgICAgICAgICAg"
    "IGlmIF9oYXNfcGF5bG9hZChjdXJyZW50KToKICAgICAgICAgICAgICAgICAgICBfZmx1c2goKQogICAgICAgICAgICAgICAgY29u"
    "dGludWUKCiAgICAgICAgICAgIGlmIG5vdCBzdHJpcHBlZDoKICAgICAgICAgICAgICAgIGlmIGN1cnJlbnRfZmllbGQgPT0gIm5v"
    "dGVzIjoKICAgICAgICAgICAgICAgICAgICBjdXJyZW50WyJub3RlcyJdID0gKGN1cnJlbnRbIm5vdGVzIl0gKyAiXG4iKSBpZiBj"
    "dXJyZW50WyJub3RlcyJdIGVsc2UgIiIKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiBfaXNfZXhwb3J0"
    "X2hlYWRlcihzdHJpcHBlZCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgX2lzX2RlY29yYXRpdmUo"
    "c3RyaXBwZWQpOgogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmICI6IiBpbiBzdHJpcHBlZDoKICAgICAg"
    "ICAgICAgICAgIG1heWJlX2xhYmVsLCBtYXliZV92YWx1ZSA9IHN0cmlwcGVkLnNwbGl0KCI6IiwgMSkKICAgICAgICAgICAgICAg"
    "IGtleSA9IG1heWJlX2xhYmVsLnN0cmlwKCkubG93ZXIoKQogICAgICAgICAgICAgICAgdmFsdWUgPSBtYXliZV92YWx1ZS5sc3Ry"
    "aXAoKQoKICAgICAgICAgICAgICAgIG1hcHBlZCA9IGxhYmVsX21hcC5nZXQoa2V5KQogICAgICAgICAgICAgICAgaWYgbWFwcGVk"
    "OgogICAgICAgICAgICAgICAgICAgIGlmIG1hcHBlZCA9PSAibmFtZSIgYW5kIF9oYXNfcGF5bG9hZChjdXJyZW50KToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgX2ZsdXNoKCkKICAgICAgICAgICAgICAgICAgICBjdXJyZW50X2ZpZWxkID0gbWFwcGVkCiAgICAg"
    "ICAgICAgICAgICAgICAgaWYgbWFwcGVkID09ICJub3RlcyI6CiAgICAgICAgICAgICAgICAgICAgICAgIGN1cnJlbnRbbWFwcGVk"
    "XSA9IHZhbHVlCiAgICAgICAgICAgICAgICAgICAgZWxpZiBtYXBwZWQgPT0gInN0YXR1cyI6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGN1cnJlbnRbbWFwcGVkXSA9IHZhbHVlIG9yICJJZGVhIgogICAgICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGN1cnJlbnRbbWFwcGVkXSA9IHZhbHVlCiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICAgICAjIFVua25vd24gbGFiZWxlZCBsaW5lcyBhcmUgbWV0YWRhdGEvY2F0ZWdvcnkvZm9vdGVyIGxpbmVzLgogICAgICAg"
    "ICAgICAgICAgY3VycmVudF9maWVsZCA9IE5vbmUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiBjdXJy"
    "ZW50X2ZpZWxkID09ICJub3RlcyI6CiAgICAgICAgICAgICAgICBjdXJyZW50WyJub3RlcyJdID0gKGN1cnJlbnRbIm5vdGVzIl0g"
    "KyAiXG4iICsgc3RyaXBwZWQpIGlmIGN1cnJlbnRbIm5vdGVzIl0gZWxzZSBzdHJpcHBlZAogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKCiAgICAgICAgICAgIGlmIGN1cnJlbnRfZmllbGQgPT0gImRlc2NyaXB0aW9uIjoKICAgICAgICAgICAgICAgIGN1cnJlbnRb"
    "ImRlc2NyaXB0aW9uIl0gPSAoY3VycmVudFsiZGVzY3JpcHRpb24iXSArICJcbiIgKyBzdHJpcHBlZCkgaWYgY3VycmVudFsiZGVz"
    "Y3JpcHRpb24iXSBlbHNlIHN0cmlwcGVkCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBJZ25vcmUgdW5s"
    "YWJlbGVkIGxpbmVzIG91dHNpZGUgcmVjb2duaXplZCBmaWVsZHMuCiAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgIGlmIF9o"
    "YXNfcGF5bG9hZChjdXJyZW50KToKICAgICAgICAgICAgX2ZsdXNoKCkKCiAgICAgICAgcmV0dXJuIGVudHJpZXMKCiAgICBkZWYg"
    "X2RvX2ltcG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkltcG9ydCBvbmUgb3IgbW9yZSBtb2R1bGUgc3BlY3MgZnJvbSBw"
    "YXN0ZWQgdGV4dCBvciBhIFRYVCBmaWxlLiIiIgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2lu"
    "ZG93VGl0bGUoIkltcG9ydCBNb2R1bGUgU3BlYyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDU2MCwgNDIwKQogICAgICAgIGxheW91dCA9IFFWQm94"
    "TGF5b3V0KGRsZykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgKICAgICAgICAgICAgIlBhc3RlIG1vZHVsZSB0ZXh0"
    "IGJlbG93IG9yIGxvYWQgYSAudHh0IGV4cG9ydC5cbiIKICAgICAgICAgICAgIlN1cHBvcnRzIE1PRFVMRSBUUkFDS0VSIGV4cG9y"
    "dHMsIHJlZ2lzdHJ5IGJsb2NrcywgYW5kIHNpbmdsZSBsYWJlbGVkIHNwZWNzLiIKICAgICAgICApKQoKICAgICAgICB0b29sX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fbG9hZF90eHQgPSBfZ290aGljX2J0bigiTG9hZCBUWFQiKQogICAgICAgIGxv"
    "YWRlZF9sYmwgPSBRTGFiZWwoIk5vIGZpbGUgbG9hZGVkIikKICAgICAgICBsb2FkZWRfbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xv"
    "cjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgIHRvb2xfcm93LmFkZFdpZGdldChidG5fbG9hZF90eHQp"
    "CiAgICAgICAgdG9vbF9yb3cuYWRkV2lkZ2V0KGxvYWRlZF9sYmwsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dCh0b29sX3Jv"
    "dykKCiAgICAgICAgdGV4dF9maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgdGV4dF9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQo"
    "IlBhc3RlIG1vZHVsZSBzcGVjKHMpIGhlcmUuLi4iKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGV4dF9maWVsZCwgMSkKCiAg"
    "ICAgICAgZGVmIF9sb2FkX3R4dF9pbnRvX2VkaXRvcigpIC0+IE5vbmU6CiAgICAgICAgICAgIHBhdGgsIF8gPSBRRmlsZURpYWxv"
    "Zy5nZXRPcGVuRmlsZU5hbWUoCiAgICAgICAgICAgICAgICBzZWxmLAogICAgICAgICAgICAgICAgIkxvYWQgTW9kdWxlIFNwZWNz"
    "IiwKICAgICAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpKSwKICAgICAgICAgICAgICAgICJUZXh0IEZpbGVzICgq"
    "LnR4dCk7O0FsbCBGaWxlcyAoKikiLAogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJhd190ZXh0ID0gUGF0aChwYXRoKS5yZWFkX3RleHQo"
    "ZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3Nh"
    "Z2VCb3gud2FybmluZyhzZWxmLCAiSW1wb3J0IEVycm9yIiwgZiJDb3VsZCBub3QgcmVhZCBmaWxlOlxue2V9IikKICAgICAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWluVGV4dChyYXdfdGV4dCkKICAgICAgICAgICAgbG9h"
    "ZGVkX2xibC5zZXRUZXh0KGYiTG9hZGVkOiB7UGF0aChwYXRoKS5uYW1lfSIpCgogICAgICAgIGJ0bl9sb2FkX3R4dC5jbGlja2Vk"
    "LmNvbm5lY3QoX2xvYWRfdHh0X2ludG9fZWRpdG9yKQoKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0"
    "bl9vayA9IF9nb3RoaWNfYnRuKCJJbXBvcnQiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAg"
    "ICAgICBidG5fb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qo"
    "ZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fb2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRu"
    "X2NhbmNlbCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxv"
    "Zy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByYXcgPSB0ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBwYXJzZWRfZW50cmllcyA9"
    "IHNlbGYuX3BhcnNlX2ltcG9ydF9lbnRyaWVzKHJhdykKICAgICAgICAgICAgaWYgbm90IHBhcnNlZF9lbnRyaWVzOgogICAgICAg"
    "ICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAgICBzZWxmLAogICAgICAgICAgICAgICAgICAg"
    "ICJJbXBvcnQgRXJyb3IiLAogICAgICAgICAgICAgICAgICAgICJObyB2YWxpZCBtb2R1bGUgZW50cmllcyB3ZXJlIGZvdW5kLiBJ"
    "bmNsdWRlIGF0IGxlYXN0IG9uZSAnTW9kdWxlOicgb3IgJ01PRFVMRTonIGJsb2NrLiIsCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAg"
    "IGZvciBwYXJzZWQgaW4gcGFyc2VkX2VudHJpZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZCh7CiAgICAg"
    "ICAgICAgICAgICAgICAgImlkIjogc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAgICAgIm5hbWUiOiBwYXJzZWQu"
    "Z2V0KCJuYW1lIiwgIiIpWzo2MF0sCiAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6IHBhcnNlZC5nZXQoInN0YXR1cyIsICJJ"
    "ZGVhIikgb3IgIklkZWEiLAogICAgICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IHBhcnNlZC5nZXQoImRlc2NyaXB0aW9u"
    "IiwgIiIpLAogICAgICAgICAgICAgICAgICAgICJub3RlcyI6IHBhcnNlZC5nZXQoIm5vdGVzIiwgIiIpLAogICAgICAgICAgICAg"
    "ICAgICAgICJjcmVhdGVkIjogbm93LAogICAgICAgICAgICAgICAgICAgICJtb2RpZmllZCI6IG5vdywKICAgICAgICAgICAgICAg"
    "IH0pCgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsCiAgICAgICAg"
    "ICAgICAgICAiSW1wb3J0IENvbXBsZXRlIiwKICAgICAgICAgICAgICAgIGYiSW1wb3J0ZWQge2xlbihwYXJzZWRfZW50cmllcyl9"
    "IG1vZHVsZSBlbnRyeyd5JyBpZiBsZW4ocGFyc2VkX2VudHJpZXMpID09IDEgZWxzZSAnaWVzJ30uIgogICAgICAgICAgICApCgoK"
    "IyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0YWIgY29udGVudCBj"
    "bGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVz"
    "dGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29u"
    "dGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJh"
    "Y2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMg"
    "U2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3IgaWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0"
    "aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRk"
    "ZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2luZG93"
    "CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVwZW5k"
    "ZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9S"
    "R0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMKIyBDb250YWluczoKIyAgIGJvb3RzdHJh"
    "cF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RS"
    "dW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGVi"
    "YXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jw"
    "b3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sg"
    "ICAgICAgICAg4oCUIG1haW4gd2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAg"
    "ICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0"
    "IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAg"
    "UnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2Fu"
    "J3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBk"
    "ZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290"
    "c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVj"
    "ayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAg"
    "ICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBhdmFpbGFi"
    "bGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0"
    "IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAg"
    "ICAgICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAgICAg"
    "Ik9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAiICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxu"
    "IgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RFQ0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAg"
    "ICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5vdCBpbnN0"
    "YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6"
    "IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0g"
    "WwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1Iiwg"
    "ICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1l"
    "IiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRpbCIsICAg"
    "ICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3Rz"
    "IiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29v"
    "Z2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAg"
    "ICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAgIGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cg"
    "PSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChm"
    "IltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3Rz"
    "dHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3Rh"
    "bGxpbmcuLi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vz"
    "cy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAgICAg"
    "ICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAg"
    "ICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAgICAgIyBWYWxpZGF0ZSBpdCBh"
    "Y3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9y"
    "dGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVu"
    "ZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0g"
    "e3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQg"
    "aW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVp"
    "cmVkLiIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBi"
    "b290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3Rh"
    "bGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19IgogICAgICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290"
    "c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1l"
    "ZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFs"
    "bCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBm"
    "b3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBf"
    "bG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAg"
    "ICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKCiMg"
    "4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0UnVuRGlhbG9nKFFEaWFs"
    "b2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAg"
    "Q29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9y"
    "ZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1"
    "dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FL"
    "RU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQw"
    "MCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3Qg"
    "PSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLi"
    "nKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIK"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAg"
    "ICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5h"
    "ZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZlc3NlbCBi"
    "ZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2Fs"
    "bHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcu"
    "QWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFD"
    "b21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb2xk"
    "ZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1"
    "ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlw"
    "ZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdl"
    "IDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAg"
    "bDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4t"
    "OGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3Nl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgp"
    "OyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFn"
    "ZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRSEJveExheW91dChwMSkK"
    "ICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAg"
    "ICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAg"
    "ICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0"
    "KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAg"
    "IHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2Ns"
    "YXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQ"
    "SSBLZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJl"
    "bCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5h"
    "ZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0g"
    "UVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tl"
    "eSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stLi4uIikKICAgICAg"
    "ICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlf"
    "bW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAg"
    "ICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAg"
    "ICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxm"
    "Ll9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwg"
    "PSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAgICAgdGVzdF9yb3cu"
    "YWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg"
    "4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlv"
    "bmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3Bh"
    "dGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYi"
    "QnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRp"
    "dXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsg"
    "cGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAgICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAg"
    "ICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQo"
    "c2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExheW91"
    "dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAg"
    "ICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRj"
    "dXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAj"
    "IOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5"
    "b3V0KCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAg"
    "IHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBD"
    "YW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9j"
    "YW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2Fr"
    "ZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93KQoK"
    "ICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3Vy"
    "cmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3Rh"
    "dHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFG"
    "aWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIsCiAg"
    "ICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9sb2Nh"
    "bF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9"
    "IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAg"
    "ICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAg"
    "ICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9w"
    "ZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4"
    "dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19s"
    "Ymwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsi"
    "CiAgICAgICAgKQogICAgICAgIFFBcHBsaWNhdGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9j"
    "b21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09"
    "IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAg"
    "ICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxpZiBpZHggPT0g"
    "MTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0"
    "KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAg"
    "ICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIg"
    "aWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBD"
    "bGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBi"
    "b29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9v"
    "a3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAgICAgICBlbGlmIGlkeCA9"
    "PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBv"
    "ayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQg"
    "bG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9"
    "IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAg"
    "IHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAx"
    "MHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5z"
    "ZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0"
    "dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1"
    "bHRfY29uZmlnKCkKICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVz"
    "ICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9"
    "IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5f"
    "bG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsi"
    "b2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdiIgogICAg"
    "ICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5"
    "LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwu"
    "dGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxp"
    "ZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4i"
    "XSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAt"
    "PiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lE"
    "RUJBUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAg"
    "IENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZXNzaW9uIGNv"
    "bnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRv"
    "cikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlzdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAg"
    "IENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRoaW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVx"
    "dWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1"
    "ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNlc3Npb24KICAgICIiIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0"
    "ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAg"
    "PSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0LCB0"
    "b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBDb2xsYXBz"
    "ZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xl"
    "X3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJp"
    "Z2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAgIHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4"
    "LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b2dnbGVf"
    "YnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICAgIyDilIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2Nv"
    "bnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5f"
    "Y29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAgICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29u"
    "dGVudCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250ZW50"
    "X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBz"
    "ZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNz"
    "aW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXpl"
    "KDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxm"
    "Ll9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0"
    "KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRvb2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAg"
    "ICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxm"
    "Ll9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAgICAgY3Ry"
    "bF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9k"
    "b3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93"
    "KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVsKCIi"
    "KQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07"
    "IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHls"
    "ZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBj"
    "b250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24g"
    "KGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyX"
    "IFJldHVybiB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAg"
    "ICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAgICAgICAgZGl2"
    "LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0"
    "KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6"
    "aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xlIHN0"
    "cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKICAg"
    "ICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxz"
    "ZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAg"
    "ICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNo"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAg"
    "ICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0"
    "ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAg"
    "ICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRn"
    "ZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1jbGljayB0"
    "byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRl"
    "bSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCBuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJOZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Io"
    "c2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LXNp"
    "emU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAg"
    "ICAgICAgICAgICJBdXRvc2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBz"
    "ZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5z"
    "ZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNp"
    "YmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91"
    "cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQoKICAg"
    "IGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYu"
    "c2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUu"
    "c2V0VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRl"
    "eHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGlj"
    "YXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBm"
    "aXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgog"
    "ICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9z"
    "ZXNzaW9uX2xpc3QuY291bnQoKSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAg"
    "ICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5z"
    "ZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0ZW0p"
    "IC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgIHNl"
    "bGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3Vy"
    "bmFsX2luZGljYXRvcigpCgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFX"
    "QUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGln"
    "bm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1"
    "dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRp"
    "bCBtYW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0UiIHwg"
    "IkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBb"
    "IkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6IHsKICAgICAg"
    "ICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAg"
    "ICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAg"
    "ICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAg"
    "ICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0"
    "by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBm"
    "ImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9yOiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXpl"
    "OiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi"
    "4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVz"
    "c3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFTkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3Vu"
    "ZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYi"
    "YmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZv"
    "bnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAg"
    "ICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQRU5TSU9OX0xBQkVMKS5zdHJpcCgpIGVs"
    "c2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVw"
    "cyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgog"
    "ICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRT"
    "cGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24o"
    "c2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NU"
    "WUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4u"
    "Y2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNl"
    "bGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBzZWxmLl9h"
    "cHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3Rh"
    "dGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAg"
    "ICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0ZSkKCiAgICBkZWYgX2Fw"
    "cGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToK"
    "ICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIK"
    "ICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHBy"
    "b3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAg"
    "ICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRp"
    "Y2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVT"
    "OgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKY2xhc3MgU2V0dGluZ3NTZWN0aW9uKFFXaWRnZXQpOgogICAg"
    "IiIiU2ltcGxlIGNvbGxhcHNpYmxlIHNlY3Rpb24gdXNlZCBieSBTZXR0aW5nc1RhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgdGl0bGU6IHN0ciwgcGFyZW50PU5vbmUsIGV4cGFuZGVkOiBib29sID0gVHJ1ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBleHBhbmRlZAoKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoK"
    "ICAgICAgICBzZWxmLl9oZWFkZXJfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dChm"
    "IuKWvCB7dGl0bGV9IiBpZiBleHBhbmRlZCBlbHNlIGYi4pa2IHt0aXRsZX0iKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDZweDsgdGV4dC1hbGlnbjogbGVmdDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90"
    "b2dnbGUpCgogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgs"
    "IDgsIDgsIDgpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNlbGYuX2NvbnRlbnQu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyBib3JkZXItdG9wOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKGV4cGFuZGVk"
    "KQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9oZWFkZXJfYnRuKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Nv"
    "bnRlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY29udGVudF9sYXlvdXQoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAg"
    "cmV0dXJuIHNlbGYuX2NvbnRlbnRfbGF5b3V0CgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9l"
    "eHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dCgKICAgICAgICAgICAg"
    "c2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVwbGFjZSgi4pa8IiwgIuKWtiIsIDEpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9l"
    "eHBhbmRlZCBlbHNlCiAgICAgICAgICAgIHNlbGYuX2hlYWRlcl9idG4udGV4dCgpLnJlcGxhY2UoIuKWtiIsICLilrwiLCAxKQog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCgoKY2xhc3MgU2V0dGluZ3NU"
    "YWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLXdpZGUgcnVudGltZSBzZXR0aW5ncyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGRlY2tfd2luZG93OiAiRWNob0RlY2siLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQp"
    "CiAgICAgICAgc2VsZi5fZGVjayA9IGRlY2tfd2luZG93CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeTogbGlzdFtkaWN0"
    "XSA9IFtdCiAgICAgICAgc2VsZi5fc2VjdGlvbl93aWRnZXRzOiBkaWN0W3N0ciwgU2V0dGluZ3NTZWN0aW9uXSA9IHt9CgogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNjcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzY3JvbGwuc2V0"
    "V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxCYXJQb2xpY3koUXQuU2Nyb2xs"
    "QmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtD"
    "X0JHfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Nyb2xsKQoK"
    "ICAgICAgICBib2R5ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQgPSBRVkJveExheW91dChib2R5KQogICAg"
    "ICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHNlbGYuX2JvZHlfbGF5"
    "b3V0LnNldFNwYWNpbmcoOCkKICAgICAgICBzY3JvbGwuc2V0V2lkZ2V0KGJvZHkpCgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX2Nv"
    "cmVfc2VjdGlvbnMoKQoKICAgIGRlZiBfcmVnaXN0ZXJfc2VjdGlvbihzZWxmLCAqLCBzZWN0aW9uX2lkOiBzdHIsIHRpdGxlOiBz"
    "dHIsIGNhdGVnb3J5OiBzdHIsIHNvdXJjZV9vd25lcjogc3RyLCBzb3J0X2tleTogaW50LCBidWlsZGVyKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnkuYXBwZW5kKHsKICAgICAgICAgICAgInNlY3Rpb25faWQiOiBzZWN0aW9uX2lkLAog"
    "ICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImNhdGVnb3J5IjogY2F0ZWdvcnksCiAgICAgICAgICAgICJz"
    "b3VyY2Vfb3duZXIiOiBzb3VyY2Vfb3duZXIsCiAgICAgICAgICAgICJzb3J0X2tleSI6IHNvcnRfa2V5LAogICAgICAgICAgICAi"
    "YnVpbGRlciI6IGJ1aWxkZXIsCiAgICAgICAgfSkKCiAgICBkZWYgX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJzeXN0ZW1fc2V0dGluZ3Mi"
    "LAogICAgICAgICAgICB0aXRsZT0iU3lzdGVtIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAg"
    "ICAgICBzb3VyY2Vfb3duZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTEwMCwKICAgICAgICAgICAgYnVp"
    "bGRlcj1zZWxmLl9idWlsZF9zeXN0ZW1fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlvbigK"
    "ICAgICAgICAgICAgc2VjdGlvbl9pZD0iaW50ZWdyYXRpb25fc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iSW50ZWdyYXRp"
    "b24gU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19y"
    "dW50aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MjAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX2ludGVncmF0"
    "aW9uX3NlY3Rpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25f"
    "aWQ9InVpX3NldHRpbmdzIiwKICAgICAgICAgICAgdGl0bGU9IlVJIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNv"
    "cmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTMwMCwKICAg"
    "ICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF91aV9zZWN0aW9uLAogICAgICAgICkKCiAgICAgICAgZm9yIG1ldGEgaW4gc29y"
    "dGVkKHNlbGYuX3NlY3Rpb25fcmVnaXN0cnksIGtleT1sYW1iZGEgbTogbS5nZXQoInNvcnRfa2V5IiwgOTk5OSkpOgogICAgICAg"
    "ICAgICBzZWN0aW9uID0gU2V0dGluZ3NTZWN0aW9uKG1ldGFbInRpdGxlIl0sIGV4cGFuZGVkPVRydWUpCiAgICAgICAgICAgIHNl"
    "bGYuX2JvZHlfbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uKQogICAgICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHNbbWV0YVsi"
    "c2VjdGlvbl9pZCJdXSA9IHNlY3Rpb24KICAgICAgICAgICAgbWV0YVsiYnVpbGRlciJdKHNlY3Rpb24uY29udGVudF9sYXlvdXQp"
    "CgogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxkX3N5c3RlbV9zZWN0aW9uKHNl"
    "bGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiT3BlcmF0aW9uYWwgTW9kZSIpKQogICAgICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX3RvcnBvcl9wYW5lbCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFi"
    "ZWwoIklkbGUiKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2lkbGVfYnRuKQoKICAgICAgICBzZXR0aW5n"
    "cyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdHpfYXV0byA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9h"
    "dXRvX2RldGVjdCIsIFRydWUpKQogICAgICAgIHR6X292ZXJyaWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb3ZlcnJp"
    "ZGUiLCAiIikgb3IgIiIpLnN0cmlwKCkKCiAgICAgICAgdHpfYXV0b19jaGsgPSBRQ2hlY2tCb3goIkF1dG8tZGV0ZWN0IGxvY2Fs"
    "L3N5c3RlbSB0aW1lIHpvbmUiKQogICAgICAgIHR6X2F1dG9fY2hrLnNldENoZWNrZWQodHpfYXV0bykKICAgICAgICB0el9hdXRv"
    "X2Noay50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X3RpbWV6b25lX2F1dG9fZGV0ZWN0KQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQodHpfYXV0b19jaGspCgogICAgICAgIHR6X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0el9yb3cuYWRkV2lk"
    "Z2V0KFFMYWJlbCgiTWFudWFsIFRpbWUgWm9uZSBPdmVycmlkZToiKSkKICAgICAgICB0el9jb21ibyA9IFFDb21ib0JveCgpCiAg"
    "ICAgICAgdHpfY29tYm8uc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAgICB0el9vcHRpb25zID0gWwogICAgICAgICAgICAiQW1lcmlj"
    "YS9DaGljYWdvIiwgIkFtZXJpY2EvTmV3X1lvcmsiLCAiQW1lcmljYS9Mb3NfQW5nZWxlcyIsCiAgICAgICAgICAgICJBbWVyaWNh"
    "L0RlbnZlciIsICJVVEMiCiAgICAgICAgXQogICAgICAgIHR6X2NvbWJvLmFkZEl0ZW1zKHR6X29wdGlvbnMpCiAgICAgICAgaWYg"
    "dHpfb3ZlcnJpZGU6CiAgICAgICAgICAgIGlmIHR6X2NvbWJvLmZpbmRUZXh0KHR6X292ZXJyaWRlKSA8IDA6CiAgICAgICAgICAg"
    "ICAgICB0el9jb21iby5hZGRJdGVtKHR6X292ZXJyaWRlKQogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCh0el9v"
    "dmVycmlkZSkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCgiQW1lcmljYS9DaGljYWdv"
    "IikKICAgICAgICB0el9jb21iby5zZXRFbmFibGVkKG5vdCB0el9hdXRvKQogICAgICAgIHR6X2NvbWJvLmN1cnJlbnRUZXh0Q2hh"
    "bmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF90aW1lem9uZV9vdmVycmlkZSkKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVk"
    "LmNvbm5lY3QobGFtYmRhIGVuYWJsZWQ6IHR6X2NvbWJvLnNldEVuYWJsZWQobm90IGVuYWJsZWQpKQogICAgICAgIHR6X3Jvdy5h"
    "ZGRXaWRnZXQodHpfY29tYm8sIDEpCiAgICAgICAgdHpfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIHR6X2hvc3Quc2V0TGF5b3V0"
    "KHR6X3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHR6X2hvc3QpCgogICAgZGVmIF9idWlsZF9pbnRlZ3JhdGlvbl9zZWN0"
    "aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5n"
    "cyIsIHt9KQogICAgICAgIGdvb2dsZV9zZWNvbmRzID0gaW50KHNldHRpbmdzLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxf"
    "bXMiLCAzMDAwMCkpIC8vIDEwMDAKICAgICAgICBnb29nbGVfc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBnb29nbGVfc2Vjb25k"
    "cykpCiAgICAgICAgZW1haWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFs"
    "X21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCgogICAgICAgIGdvb2dsZV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZ29vZ2xl"
    "X3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCAoc2Vjb25kcyk6IikpCiAgICAgICAgZ29vZ2xl"
    "X2JveCA9IFFTcGluQm94KCkKICAgICAgICBnb29nbGVfYm94LnNldFJhbmdlKDUsIDYwMCkKICAgICAgICBnb29nbGVfYm94LnNl"
    "dFZhbHVlKGdvb2dsZV9zZWNvbmRzKQogICAgICAgIGdvb2dsZV9ib3gudmFsdWVDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5f"
    "c2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoZ29vZ2xlX2JveCwgMSkKICAg"
    "ICAgICBnb29nbGVfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIGdvb2dsZV9ob3N0LnNldExheW91dChnb29nbGVfcm93KQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoZ29vZ2xlX2hvc3QpCgogICAgICAgIGVtYWlsX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBlbWFpbF9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiRW1haWwgcmVmcmVzaCBpbnRlcnZhbCAobWludXRlcyk6IikpCiAgICAgICAg"
    "ZW1haWxfYm94ID0gUUNvbWJvQm94KCkKICAgICAgICBlbWFpbF9ib3guc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAgICBlbWFpbF9i"
    "b3guYWRkSXRlbXMoWyIxIiwgIjUiLCAiMTAiLCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBlbWFpbF9ib3guc2V0Q3VycmVu"
    "dFRleHQoc3RyKGVtYWlsX21pbnV0ZXMpKQogICAgICAgIGVtYWlsX2JveC5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9kZWNrLl9zZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KGVt"
    "YWlsX2JveCwgMSkKICAgICAgICBlbWFpbF9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgZW1haWxfaG9zdC5zZXRMYXlvdXQoZW1h"
    "aWxfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZW1haWxfaG9zdCkKCiAgICAgICAgbm90ZSA9IFFMYWJlbCgiRW1haWwg"
    "cG9sbGluZyBmb3VuZGF0aW9uIGlzIGNvbmZpZ3VyYXRpb24tb25seSB1bmxlc3MgYW4gZW1haWwgYmFja2VuZCBpcyBlbmFibGVk"
    "LiIpCiAgICAgICAgbm90ZS5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5vdGUpCgogICAgZGVmIF9idWlsZF91aV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hM"
    "YXlvdXQpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIldpbmRvdyBTaGVsbCIpKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fYmxf"
    "YnRuKQoKCmNsYXNzIERpY2VHbHlwaChRV2lkZ2V0KToKICAgICIiIlNpbXBsZSAyRCBzaWxob3VldHRlIHJlbmRlcmVyIGZvciBk"
    "aWUtdHlwZSByZWNvZ25pdGlvbi4iIiIKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyID0gImQyMCIsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kaWVfdHlwZSA9IGRpZV90eXBl"
    "CiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg3MCwgNzApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtU2l6ZSg5MCwgOTApCgog"
    "ICAgZGVmIHNldF9kaWVfdHlwZShzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RpZV90eXBlID0g"
    "ZGllX3R5cGUKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHBh"
    "aW50ZXIgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHBhaW50ZXIuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFu"
    "dGlhbGlhc2luZykKICAgICAgICByZWN0ID0gc2VsZi5yZWN0KCkuYWRqdXN0ZWQoOCwgOCwgLTgsIC04KQoKICAgICAgICBkaWUg"
    "PSBzZWxmLl9kaWVfdHlwZQogICAgICAgIGxpbmUgPSBRQ29sb3IoQ19HT0xEKQogICAgICAgIGZpbGwgPSBRQ29sb3IoQ19CRzIp"
    "CiAgICAgICAgYWNjZW50ID0gUUNvbG9yKENfQ1JJTVNPTikKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBlbihsaW5lLCAyKSkK"
    "ICAgICAgICBwYWludGVyLnNldEJydXNoKGZpbGwpCgogICAgICAgIHB0cyA9IFtdCiAgICAgICAgaWYgZGllID09ICJkNCI6CiAg"
    "ICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAg"
    "ICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJl"
    "Y3QucmlnaHQoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSA9PSAiZDYiOgogICAgICAg"
    "ICAgICBwYWludGVyLmRyYXdSb3VuZGVkUmVjdChyZWN0LCA0LCA0KQogICAgICAgIGVsaWYgZGllID09ICJkOCI6CiAgICAgICAg"
    "ICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAg"
    "ICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0"
    "LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmNl"
    "bnRlcigpLnkoKSksCiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSBpbiAoImQxMCIsICJkMTAwIik6CiAgICAgICAgICAg"
    "IHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAg"
    "ICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyA4LCByZWN0LnRvcCgpICsgMTYpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qu"
    "bGVmdCgpLCByZWN0LmJvdHRvbSgpIC0gMTIpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0"
    "LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuYm90dG9tKCkgLSAxMiksCiAgICAg"
    "ICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAgXQogICAgICAg"
    "IGVsaWYgZGllID09ICJkMTIiOgogICAgICAgICAgICBjeCA9IHJlY3QuY2VudGVyKCkueCgpOyBjeSA9IHJlY3QuY2VudGVyKCku"
    "eSgpCiAgICAgICAgICAgIHJ4ID0gcmVjdC53aWR0aCgpIC8gMjsgcnkgPSByZWN0LmhlaWdodCgpIC8gMgogICAgICAgICAgICBm"
    "b3IgaSBpbiByYW5nZSg1KToKICAgICAgICAgICAgICAgIGEgPSAobWF0aC5waSAqIDIgKiBpIC8gNSkgLSAobWF0aC5waSAvIDIp"
    "CiAgICAgICAgICAgICAgICBwdHMuYXBwZW5kKFFQb2ludChpbnQoY3ggKyByeCAqIG1hdGguY29zKGEpKSwgaW50KGN5ICsgcnkg"
    "KiBtYXRoLnNpbihhKSkpKQogICAgICAgIGVsc2U6ICAjIGQyMAogICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBR"
    "UG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsg"
    "MTAsIHJlY3QudG9wKCkgKyAxNCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgp"
    "KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSArIDEwLCByZWN0LmJvdHRvbSgpIC0gMTQpLAogICAgICAgICAg"
    "ICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0"
    "LnJpZ2h0KCkgLSAxMCwgcmVjdC5ib3R0b20oKSAtIDE0KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJl"
    "Y3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC50b3AoKSArIDE0"
    "KSwKICAgICAgICAgICAgXQoKICAgICAgICBpZiBwdHM6CiAgICAgICAgICAgIHBhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAg"
    "ICAgICBwYXRoLm1vdmVUbyhwdHNbMF0pCiAgICAgICAgICAgIGZvciBwIGluIHB0c1sxOl06CiAgICAgICAgICAgICAgICBwYXRo"
    "LmxpbmVUbyhwKQogICAgICAgICAgICBwYXRoLmNsb3NlU3VicGF0aCgpCiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1BhdGgocGF0"
    "aCkKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBlbihhY2NlbnQsIDEpKQogICAgICAgIHR4dCA9ICIlIiBpZiBkaWUgPT0gImQx"
    "MDAiIGVsc2UgZGllLnJlcGxhY2UoImQiLCAiIikKICAgICAgICBwYWludGVyLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMiwg"
    "UUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHBhaW50ZXIuZHJhd1RleHQocmVjdCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNl"
    "bnRlciwgdHh0KQoKCmNsYXNzIERpY2VUcmF5RGllKFFGcmFtZSk6CiAgICBzaW5nbGVDbGlja2VkID0gU2lnbmFsKHN0cikKICAg"
    "IGRvdWJsZUNsaWNrZWQgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyLCBkaXNwbGF5"
    "X2xhYmVsOiBzdHIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmRp"
    "ZV90eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxmLmRpc3BsYXlfbGFiZWwgPSBkaXNwbGF5X2xhYmVsCiAgICAgICAgc2VsZi5f"
    "Y2xpY2tfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9jbGlja190aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAg"
    "ICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc2V0SW50ZXJ2YWwoMjIwKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnRpbWVvdXQu"
    "Y29ubmVjdChzZWxmLl9lbWl0X3NpbmdsZSkKCiAgICAgICAgc2VsZi5zZXRPYmplY3ROYW1lKCJEaWNlVHJheURpZSIpCiAgICAg"
    "ICAgc2VsZi5zZXRDdXJzb3IoUXQuQ3Vyc29yU2hhcGUuUG9pbnRpbmdIYW5kQ3Vyc29yKQogICAgICAgIHNlbGYuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJRRnJhbWUjRGljZVRyYXlEaWUge3sgYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogOHB4OyB9fSIKICAgICAgICAgICAgZiJRRnJhbWUjRGljZVRyYXlEaWU6"
    "aG92ZXIge3sgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07IH19IgogICAgICAgICkKCiAgICAgICAgbGF5ID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICBsYXkuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgbGF5LnNldFNwYWNpbmco"
    "MikKCiAgICAgICAgZ2x5cGhfZGllID0gImQxMDAiIGlmIGRpZV90eXBlID09ICJkJSIgZWxzZSBkaWVfdHlwZQogICAgICAgIHNl"
    "bGYuZ2x5cGggPSBEaWNlR2x5cGgoZ2x5cGhfZGllKQogICAgICAgIHNlbGYuZ2x5cGguc2V0Rml4ZWRTaXplKDU0LCA1NCkKICAg"
    "ICAgICBzZWxmLmdseXBoLnNldEF0dHJpYnV0ZShRdC5XaWRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3VzZUV2ZW50"
    "cywgVHJ1ZSkKCiAgICAgICAgc2VsZi5sYmwgPSBRTGFiZWwoZGlzcGxheV9sYWJlbCkKICAgICAgICBzZWxmLmxibC5zZXRBbGln"
    "bm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLmxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6"
    "IHtDX1RFWFR9OyBmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIHNlbGYubGJsLnNldEF0dHJpYnV0ZShRdC5XaWRnZXRBdHRy"
    "aWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAgbGF5LmFkZFdpZGdldChzZWxmLmdseXBo"
    "LCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIGxheS5hZGRXaWRnZXQoc2VsZi5sYmwpCgogICAgZGVm"
    "IG1vdXNlUHJlc3NFdmVudChzZWxmLCBldmVudCk6CiAgICAgICAgaWYgZXZlbnQuYnV0dG9uKCkgPT0gUXQuTW91c2VCdXR0b24u"
    "TGVmdEJ1dHRvbjoKICAgICAgICAgICAgaWYgc2VsZi5fY2xpY2tfdGltZXIuaXNBY3RpdmUoKToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2NsaWNrX3RpbWVyLnN0b3AoKQogICAgICAgICAgICAgICAgc2VsZi5kb3VibGVDbGlja2VkLmVtaXQoc2VsZi5kaWVfdHlw"
    "ZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnN0YXJ0KCkKICAgICAgICAgICAg"
    "ZXZlbnQuYWNjZXB0KCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgog"
    "ICAgZGVmIF9lbWl0X3NpbmdsZShzZWxmKToKICAgICAgICBzZWxmLnNpbmdsZUNsaWNrZWQuZW1pdChzZWxmLmRpZV90eXBlKQoK"
    "CmNsYXNzIERpY2VSb2xsZXJUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLW5hdGl2ZSBEaWNlIFJvbGxlciBtb2R1bGUgdGFiIHdp"
    "dGggdHJheS9wb29sIHdvcmtmbG93IGFuZCBzdHJ1Y3R1cmVkIHJvbGwgZXZlbnRzLiIiIgoKICAgIFRSQVlfT1JERVIgPSBbImQ0"
    "IiwgImQ2IiwgImQ4IiwgImQxMCIsICJkMTIiLCAiZDIwIiwgImQlIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGlhZ25vc3Rp"
    "Y3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNz"
    "X2xvZ2dlciBvciAobGFtYmRhICpfYXJncywgKipfa3dhcmdzOiBOb25lKQoKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzOiBsaXN0"
    "W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLmNvbW1vbl9y"
    "b2xsczogZGljdFtzdHIsIGRpY3RdID0ge30KICAgICAgICBzZWxmLmV2ZW50X2J5X2lkOiBkaWN0W3N0ciwgZGljdF0gPSB7fQog"
    "ICAgICAgIHNlbGYuY3VycmVudF9wb29sOiBkaWN0W3N0ciwgaW50XSA9IHt9CiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRz"
    "OiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBzZWxmLnJ1bGVfZGVmaW5pdGlvbnM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICAg"
    "ICAgICAgInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0IjogewogICAgICAgICAgICAgICAgImlkIjogInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0"
    "IiwKICAgICAgICAgICAgICAgICJuYW1lIjogIkQmRCA1ZSBTdGF0IFJvbGwiLAogICAgICAgICAgICAgICAgImRpY2VfY291bnQi"
    "OiA0LAogICAgICAgICAgICAgICAgImRpY2Vfc2lkZXMiOiA2LAogICAgICAgICAgICAgICAgImRyb3BfbG93ZXN0X2NvdW50Ijog"
    "MSwKICAgICAgICAgICAgICAgICJkcm9wX2hpZ2hlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgIm5vdGVzIjogIlJvbGwg"
    "NGQ2LCBkcm9wIGxvd2VzdCBvbmUuIgogICAgICAgICAgICB9LAogICAgICAgICAgICAicnVsZV8zZDZfc3RyYWlnaHQiOiB7CiAg"
    "ICAgICAgICAgICAgICAiaWQiOiAicnVsZV8zZDZfc3RyYWlnaHQiLAogICAgICAgICAgICAgICAgIm5hbWUiOiAiM2Q2IFN0cmFp"
    "Z2h0IiwKICAgICAgICAgICAgICAgICJkaWNlX2NvdW50IjogMywKICAgICAgICAgICAgICAgICJkaWNlX3NpZGVzIjogNiwKICAg"
    "ICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9jb3VudCI6IDAsCiAgICAgICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50Ijog"
    "MCwKICAgICAgICAgICAgICAgICJub3RlcyI6ICJDbGFzc2ljIDNkNiByb2xsLiIKICAgICAgICAgICAgfSwKICAgICAgICB9Cgog"
    "ICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLl9y"
    "ZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94"
    "TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICByb290LnNldFNw"
    "YWNpbmcoNikKCiAgICAgICAgdHJheV93cmFwID0gUUZyYW1lKCkKICAgICAgICB0cmF5X3dyYXAuc2V0U3R5bGVTaGVldChmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICB0cmF5X2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KHRyYXlfd3JhcCkKICAgICAgICB0cmF5X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAg"
    "ICAgICB0cmF5X2xheW91dC5zZXRTcGFjaW5nKDYpCiAgICAgICAgdHJheV9sYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiRGljZSBU"
    "cmF5IikpCgogICAgICAgIHRyYXlfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHRyYXlfcm93LnNldFNwYWNpbmcoNikKICAg"
    "ICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgYmxvY2sgPSBEaWNlVHJheURpZShkaWUsIGRpZSkK"
    "ICAgICAgICAgICAgYmxvY2suc2luZ2xlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX2FkZF9kaWVfdG9fcG9vbCkKICAgICAgICAgICAg"
    "YmxvY2suZG91YmxlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX3F1aWNrX3JvbGxfc2luZ2xlX2RpZSkKICAgICAgICAgICAgdHJheV9y"
    "b3cuYWRkV2lkZ2V0KGJsb2NrLCAxKQogICAgICAgIHRyYXlfbGF5b3V0LmFkZExheW91dCh0cmF5X3JvdykKICAgICAgICByb290"
    "LmFkZFdpZGdldCh0cmF5X3dyYXApCgogICAgICAgIHBvb2xfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcG9vbF93cmFwLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgcHcg"
    "PSBRVkJveExheW91dChwb29sX3dyYXApCiAgICAgICAgcHcuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAg"
    "cHcuc2V0U3BhY2luZyg2KQoKICAgICAgICBwdy5hZGRXaWRnZXQoUUxhYmVsKCJDdXJyZW50IFBvb2wiKSkKICAgICAgICBzZWxm"
    "LnBvb2xfZXhwcl9sYmwgPSBRTGFiZWwoIlBvb2w6IChlbXB0eSkiKQogICAgICAgIHNlbGYucG9vbF9leHByX2xibC5zZXRTdHls"
    "ZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9OyBmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIHB3LmFkZFdpZGdldChzZWxmLnBv"
    "b2xfZXhwcl9sYmwpCgogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYucG9v"
    "bF9lbnRyaWVzX2xheW91dCA9IFFIQm94TGF5b3V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCkKICAgICAgICBzZWxmLnBvb2xf"
    "ZW50cmllc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5"
    "b3V0LnNldFNwYWNpbmcoNikKICAgICAgICBwdy5hZGRXaWRnZXQoc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0KQoKICAgICAgICBt"
    "ZXRhX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQgPSBRTGluZUVkaXQoKTsgc2VsZi5sYWJlbF9l"
    "ZGl0LnNldFBsYWNlaG9sZGVyVGV4dCgiTGFiZWwgLyBwdXJwb3NlIikKICAgICAgICBzZWxmLm1vZF9zcGluID0gUVNwaW5Cb3go"
    "KTsgc2VsZi5tb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5LCA5OTkpOyBzZWxmLm1vZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2Vs"
    "Zi5ydWxlX2NvbWJvID0gUUNvbWJvQm94KCk7IHNlbGYucnVsZV9jb21iby5hZGRJdGVtKCJNYW51YWwgUm9sbCIsICIiKQogICAg"
    "ICAgIGZvciByaWQsIG1ldGEgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zLml0ZW1zKCk6CiAgICAgICAgICAgIHNlbGYucnVsZV9j"
    "b21iby5hZGRJdGVtKG1ldGEuZ2V0KCJuYW1lIiwgcmlkKSwgcmlkKQoKICAgICAgICBmb3IgdGl0bGUsIHcgaW4gKCgiTGFiZWwi"
    "LCBzZWxmLmxhYmVsX2VkaXQpLCAoIk1vZGlmaWVyIiwgc2VsZi5tb2Rfc3BpbiksICgiUnVsZSIsIHNlbGYucnVsZV9jb21ibykp"
    "OgogICAgICAgICAgICBjb2wgPSBRVkJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0aXRsZSkKICAgICAgICAg"
    "ICAgbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgICAgICBj"
    "b2wuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgY29sLmFkZFdpZGdldCh3KQogICAgICAgICAgICBtZXRhX3Jvdy5hZGRMYXlv"
    "dXQoY29sLCAxKQogICAgICAgIHB3LmFkZExheW91dChtZXRhX3JvdykKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4gPSBRUHVzaEJ1dHRvbigiUm9sbCBQb29sIikKICAgICAgICBzZWxmLnJlc2V0X3Bv"
    "b2xfYnRuID0gUVB1c2hCdXR0b24oIlJlc2V0IFBvb2wiKQogICAgICAgIHNlbGYuc2F2ZV9wb29sX2J0biA9IFFQdXNoQnV0dG9u"
    "KCJTYXZlIFBvb2wiKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucm9sbF9wb29sX2J0bikKICAgICAgICBhY3Rpb25z"
    "LmFkZFdpZGdldChzZWxmLnJlc2V0X3Bvb2xfYnRuKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuc2F2ZV9wb29sX2J0"
    "bikKICAgICAgICBwdy5hZGRMYXlvdXQoYWN0aW9ucykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQocG9vbF93cmFwKQoKICAgICAg"
    "ICByZXN1bHRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcmVzdWx0X3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtD"
    "X0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBybCA9IFFWQm94TGF5b3V0KHJlc3VsdF93cmFw"
    "KQogICAgICAgIHJsLnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJsLmFkZFdpZGdldChRTGFiZWwoIkN1"
    "cnJlbnQgUmVzdWx0IikpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwgPSBRTGFiZWwoIk5vIHJvbGwgeWV0LiIpCiAg"
    "ICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBybC5hZGRXaWRnZXQoc2VsZi5j"
    "dXJyZW50X3Jlc3VsdF9sYmwpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQocmVzdWx0X3dyYXApCgogICAgICAgIG1pZCA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBoaXN0b3J5X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIGhpc3Rvcnlfd3JhcC5zZXRTdHlsZVNoZWV0"
    "KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIGh3ID0gUVZCb3hM"
    "YXlvdXQoaGlzdG9yeV93cmFwKQogICAgICAgIGh3LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQoKICAgICAgICBzZWxm"
    "Lmhpc3RvcnlfdGFicyA9IFFUYWJXaWRnZXQoKQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90"
    "YWJsZSgpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlID0gc2VsZi5fbWFrZV9yb2xsX3RhYmxlKCkKICAgICAgICBzZWxmLmhp"
    "c3RvcnlfdGFicy5hZGRUYWIoc2VsZi5jdXJyZW50X3RhYmxlLCAiQ3VycmVudCBSb2xscyIpCiAgICAgICAgc2VsZi5oaXN0b3J5"
    "X3RhYnMuYWRkVGFiKHNlbGYuaGlzdG9yeV90YWJsZSwgIlJvbGwgSGlzdG9yeSIpCiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYu"
    "aGlzdG9yeV90YWJzLCAxKQoKICAgICAgICBoaXN0b3J5X2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5jbGVh"
    "cl9oaXN0b3J5X2J0biA9IFFQdXNoQnV0dG9uKCJDbGVhciBSb2xsIEhpc3RvcnkiKQogICAgICAgIGhpc3RvcnlfYWN0aW9ucy5h"
    "ZGRXaWRnZXQoc2VsZi5jbGVhcl9oaXN0b3J5X2J0bikKICAgICAgICBoaXN0b3J5X2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAg"
    "ICAgIGh3LmFkZExheW91dChoaXN0b3J5X2FjdGlvbnMpCgogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsID0gUUxhYmVsKCJH"
    "cmFuZCBUb3RhbDogMCIpCiAgICAgICAgc2VsZi5ncmFuZF90b3RhbF9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xE"
    "fTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIGh3LmFkZFdpZGdldChzZWxmLmdyYW5kX3Rv"
    "dGFsX2xibCkKCiAgICAgICAgc2F2ZWRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgc2F2ZWRfd3JhcC5zZXRTdHlsZVNoZWV0KGYi"
    "YmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIHN3ID0gUVZCb3hMYXlv"
    "dXQoc2F2ZWRfd3JhcCkKICAgICAgICBzdy5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBzdy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJTYXZlZCAvIENvbW1vbiBSb2xscyIpKQoKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVsKCJTYXZlZCIpKQog"
    "ICAgICAgIHNlbGYuc2F2ZWRfbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzdy5hZGRXaWRnZXQoc2VsZi5zYXZlZF9saXN0"
    "LCAxKQogICAgICAgIHNhdmVkX2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuID0gUVB1"
    "c2hCdXR0b24oIlJ1biIpCiAgICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJMb2FkL0VkaXQiKQogICAg"
    "ICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJEZWxldGUiKQogICAgICAgIHNhdmVkX2FjdGlvbnMuYWRk"
    "V2lkZ2V0KHNlbGYucnVuX3NhdmVkX2J0bikKICAgICAgICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmxvYWRfc2F2ZWRf"
    "YnRuKQogICAgICAgIHNhdmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuZGVsZXRlX3NhdmVkX2J0bikKICAgICAgICBzdy5hZGRM"
    "YXlvdXQoc2F2ZWRfYWN0aW9ucykKCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiQXV0by1EZXRlY3RlZCBDb21tb24iKSkK"
    "ICAgICAgICBzZWxmLmNvbW1vbl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9s"
    "aXN0LCAxKQogICAgICAgIGNvbW1vbl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25f"
    "YnRuID0gUVB1c2hCdXR0b24oIlByb21vdGUgdG8gU2F2ZWQiKQogICAgICAgIHNlbGYuZGlzbWlzc19jb21tb25fYnRuID0gUVB1"
    "c2hCdXR0b24oIkRpc21pc3MiKQogICAgICAgIGNvbW1vbl9hY3Rpb25zLmFkZFdpZGdldChzZWxmLnByb21vdGVfY29tbW9uX2J0"
    "bikKICAgICAgICBjb21tb25fYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4pCiAgICAgICAgc3cuYWRk"
    "TGF5b3V0KGNvbW1vbl9hY3Rpb25zKQoKICAgICAgICBzZWxmLmNvbW1vbl9oaW50ID0gUUxhYmVsKCJDb21tb24gc2lnbmF0dXJl"
    "IHRyYWNraW5nIGFjdGl2ZS4iKQogICAgICAgIHNlbGYuY29tbW9uX2hpbnQuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhU"
    "X0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2hpbnQpCgogICAgICAgIG1p"
    "ZC5hZGRXaWRnZXQoaGlzdG9yeV93cmFwLCAzKQogICAgICAgIG1pZC5hZGRXaWRnZXQoc2F2ZWRfd3JhcCwgMikKICAgICAgICBy"
    "b290LmFkZExheW91dChtaWQsIDEpCgogICAgICAgIHNlbGYucm9sbF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcm9s"
    "bF9jdXJyZW50X3Bvb2wpCiAgICAgICAgc2VsZi5yZXNldF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcmVzZXRfcG9v"
    "bCkKICAgICAgICBzZWxmLnNhdmVfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcG9vbCkKICAgICAgICBzZWxm"
    "LmNsZWFyX2hpc3RvcnlfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9jbGVhcl9oaXN0b3J5KQoKICAgICAgICBzZWxmLnNhdmVk"
    "X2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkpKQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29u"
    "bmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkp"
    "KQoKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3J1bl9zZWxlY3RlZF9zYXZlZCkKICAg"
    "ICAgICBzZWxmLmxvYWRfc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9sb2FkX3NlbGVjdGVkX3NhdmVkKQogICAgICAg"
    "IHNlbGYuZGVsZXRlX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGVsZXRlX3NlbGVjdGVkX3NhdmVkKQogICAgICAg"
    "IHNlbGYucHJvbW90ZV9jb21tb25fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vbikKICAg"
    "ICAgICBzZWxmLmRpc21pc3NfY29tbW9uX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGlzbWlzc19zZWxlY3RlZF9jb21tb24p"
    "CgogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0"
    "b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1l"
    "bnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVx"
    "dWVzdGVkLmNvbm5lY3QobGFtYmRhIHBvczogc2VsZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLmN1cnJlbnRfdGFibGUs"
    "IHBvcykpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtYmRh"
    "IHBvczogc2VsZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLmhpc3RvcnlfdGFibGUsIHBvcykpCgogICAgZGVmIF9tYWtl"
    "X3JvbGxfdGFibGUoc2VsZikgLT4gUVRhYmxlV2lkZ2V0OgogICAgICAgIHRibCA9IFFUYWJsZVdpZGdldCgwLCA2KQogICAgICAg"
    "IHRibC5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiVGltZXN0YW1wIiwgIkxhYmVsIiwgIkV4cHJlc3Npb24iLCAiUmF3Iiwg"
    "Ik1vZGlmaWVyIiwgIlRvdGFsIl0pCiAgICAgICAgdGJsLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZShR"
    "SGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgdGJsLnZlcnRpY2FsSGVhZGVyKCkuc2V0VmlzaWJsZShGYWxz"
    "ZSkKICAgICAgICB0Ymwuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJz"
    "KQogICAgICAgIHRibC5zZXRTZWxlY3Rpb25CZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxl"
    "Y3RSb3dzKQogICAgICAgIHRibC5zZXRTb3J0aW5nRW5hYmxlZChGYWxzZSkKICAgICAgICByZXR1cm4gdGJsCgogICAgZGVmIF9z"
    "b3J0ZWRfcG9vbF9pdGVtcyhzZWxmKToKICAgICAgICByZXR1cm4gWyhkLCBzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZCwgMCkpIGZv"
    "ciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZCwgMCkgPiAwXQoKICAgIGRlZiBfcG9vbF9l"
    "eHByZXNzaW9uKHNlbGYsIHBvb2w6IGRpY3Rbc3RyLCBpbnRdIHwgTm9uZSA9IE5vbmUpIC0+IHN0cjoKICAgICAgICBwID0gcG9v"
    "bCBpZiBwb29sIGlzIG5vdCBOb25lIGVsc2Ugc2VsZi5jdXJyZW50X3Bvb2wKICAgICAgICBwYXJ0cyA9IFtmIntxdHl9e2RpZX0i"
    "IGZvciBkaWUsIHF0eSBpbiBbKGQsIHAuZ2V0KGQsIDApKSBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVJdIGlmIHF0eSA+IDBdCiAg"
    "ICAgICAgcmV0dXJuICIgKyAiLmpvaW4ocGFydHMpIGlmIHBhcnRzIGVsc2UgIihlbXB0eSkiCgogICAgZGVmIF9ub3JtYWxpemVf"
    "cG9vbF9zaWduYXR1cmUoc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIHJ1bGVfaWQ6IHN0ciA9ICIi"
    "KSAtPiBzdHI6CiAgICAgICAgcGFydHMgPSBbZiJ7cG9vbC5nZXQoZCwgMCl9e2R9IiBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVIg"
    "aWYgcG9vbC5nZXQoZCwgMCkgPiAwXQogICAgICAgIGJhc2UgPSAiKyIuam9pbihwYXJ0cykgaWYgcGFydHMgZWxzZSAiMCIKICAg"
    "ICAgICBzaWcgPSBmIntiYXNlfXttb2RpZmllcjorZH0iCiAgICAgICAgcmV0dXJuIGYie3NpZ31fe3J1bGVfaWR9IiBpZiBydWxl"
    "X2lkIGVsc2Ugc2lnCgogICAgZGVmIF9kaWNlX2xhYmVsKHNlbGYsIGRpZV90eXBlOiBzdHIpIC0+IHN0cjoKICAgICAgICByZXR1"
    "cm4gImQlIiBpZiBkaWVfdHlwZSA9PSAiZCUiIGVsc2UgZGllX3R5cGUKCiAgICBkZWYgX3JvbGxfc2luZ2xlX3ZhbHVlKHNlbGYs"
    "IGRpZV90eXBlOiBzdHIpOgogICAgICAgIGlmIGRpZV90eXBlID09ICJkJSI6CiAgICAgICAgICAgIHRlbnMgPSByYW5kb20ucmFu"
    "ZGludCgwLCA5KSAqIDEwCiAgICAgICAgICAgIHJldHVybiB0ZW5zLCAoIjAwIiBpZiB0ZW5zID09IDAgZWxzZSBzdHIodGVucykp"
    "CiAgICAgICAgc2lkZXMgPSBpbnQoZGllX3R5cGUucmVwbGFjZSgiZCIsICIiKSkKICAgICAgICB2YWwgPSByYW5kb20ucmFuZGlu"
    "dCgxLCBzaWRlcykKICAgICAgICByZXR1cm4gdmFsLCBzdHIodmFsKQoKICAgIGRlZiBfcm9sbF9wb29sX2RhdGEoc2VsZiwgcG9v"
    "bDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIGxhYmVsOiBzdHIsIHJ1bGVfaWQ6IHN0ciA9ICIiKSAtPiBkaWN0Ogog"
    "ICAgICAgIGdyb3VwZWRfbnVtZXJpYzogZGljdFtzdHIsIGxpc3RbaW50XV0gPSB7fQogICAgICAgIGdyb3VwZWRfZGlzcGxheTog"
    "ZGljdFtzdHIsIGxpc3Rbc3RyXV0gPSB7fQogICAgICAgIHN1YnRvdGFsID0gMAogICAgICAgIHVzZWRfcG9vbCA9IGRpY3QocG9v"
    "bCkKCiAgICAgICAgaWYgcnVsZV9pZCBhbmQgcnVsZV9pZCBpbiBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMgYW5kIChub3QgcG9vbCBv"
    "ciBsZW4oW2sgZm9yIGssIHYgaW4gcG9vbC5pdGVtcygpIGlmIHYgPiAwXSkgPT0gMSk6CiAgICAgICAgICAgIHJ1bGUgPSBzZWxm"
    "LnJ1bGVfZGVmaW5pdGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KQogICAgICAgICAgICBzaWRlcyA9IGludChydWxlLmdldCgiZGljZV9z"
    "aWRlcyIsIDYpKQogICAgICAgICAgICBjb3VudCA9IGludChydWxlLmdldCgiZGljZV9jb3VudCIsIDEpKQogICAgICAgICAgICBk"
    "aWUgPSBmImR7c2lkZXN9IgogICAgICAgICAgICB1c2VkX3Bvb2wgPSB7ZGllOiBjb3VudH0KICAgICAgICAgICAgcmF3ID0gW3Jh"
    "bmRvbS5yYW5kaW50KDEsIHNpZGVzKSBmb3IgXyBpbiByYW5nZShjb3VudCldCiAgICAgICAgICAgIGRyb3BfbG93ID0gaW50KHJ1"
    "bGUuZ2V0KCJkcm9wX2xvd2VzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGRyb3BfaGlnaCA9IGludChydWxlLmdldCgi"
    "ZHJvcF9oaWdoZXN0X2NvdW50IiwgMCkgb3IgMCkKICAgICAgICAgICAga2VwdCA9IGxpc3QocmF3KQogICAgICAgICAgICBpZiBk"
    "cm9wX2xvdyA+IDA6CiAgICAgICAgICAgICAgICBrZXB0ID0gc29ydGVkKGtlcHQpW2Ryb3BfbG93Ol0KICAgICAgICAgICAgaWYg"
    "ZHJvcF9oaWdoID4gMDoKICAgICAgICAgICAgICAgIGtlcHQgPSBzb3J0ZWQoa2VwdClbOi1kcm9wX2hpZ2hdIGlmIGRyb3BfaGln"
    "aCA8IGxlbihrZXB0KSBlbHNlIFtdCiAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gcmF3CiAgICAgICAgICAgIGdy"
    "b3VwZWRfZGlzcGxheVtkaWVdID0gW3N0cih2KSBmb3IgdiBpbiByYXddCiAgICAgICAgICAgIHN1YnRvdGFsID0gc3VtKGtlcHQp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgICAgICBxdHkg"
    "PSBpbnQocG9vbC5nZXQoZGllLCAwKSBvciAwKQogICAgICAgICAgICAgICAgaWYgcXR5IDw9IDA6CiAgICAgICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gW10KICAgICAgICAgICAgICAgIGdyb3Vw"
    "ZWRfZGlzcGxheVtkaWVdID0gW10KICAgICAgICAgICAgICAgIGZvciBfIGluIHJhbmdlKHF0eSk6CiAgICAgICAgICAgICAgICAg"
    "ICAgbnVtLCBkaXNwID0gc2VsZi5fcm9sbF9zaW5nbGVfdmFsdWUoZGllKQogICAgICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVt"
    "ZXJpY1tkaWVdLmFwcGVuZChudW0pCiAgICAgICAgICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0uYXBwZW5kKGRpc3Ap"
    "CiAgICAgICAgICAgICAgICAgICAgc3VidG90YWwgKz0gaW50KG51bSkKCiAgICAgICAgdG90YWwgPSBzdWJ0b3RhbCArIGludCht"
    "b2RpZmllcikKICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgZXhwciA9IHNl"
    "bGYuX3Bvb2xfZXhwcmVzc2lvbih1c2VkX3Bvb2wpCiAgICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0g"
    "c2VsZi5ydWxlX2RlZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9pZCkKICAgICAgICAgICAgZXhw"
    "ciA9IGYie2V4cHJ9ICh7cnVsZV9uYW1lfSkiCgogICAgICAgIGV2ZW50ID0gewogICAgICAgICAgICAiaWQiOiBmInJvbGxfe3V1"
    "aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdHMsCiAgICAgICAgICAgICJsYWJlbCI6IGxh"
    "YmVsLAogICAgICAgICAgICAicG9vbCI6IHVzZWRfcG9vbCwKICAgICAgICAgICAgImdyb3VwZWRfcmF3IjogZ3JvdXBlZF9udW1l"
    "cmljLAogICAgICAgICAgICAiZ3JvdXBlZF9yYXdfZGlzcGxheSI6IGdyb3VwZWRfZGlzcGxheSwKICAgICAgICAgICAgInN1YnRv"
    "dGFsIjogc3VidG90YWwsCiAgICAgICAgICAgICJtb2RpZmllciI6IGludChtb2RpZmllciksCiAgICAgICAgICAgICJmaW5hbF90"
    "b3RhbCI6IGludCh0b3RhbCksCiAgICAgICAgICAgICJleHByZXNzaW9uIjogZXhwciwKICAgICAgICAgICAgInNvdXJjZSI6ICJk"
    "aWNlX3JvbGxlciIsCiAgICAgICAgICAgICJydWxlX2lkIjogcnVsZV9pZCBvciBOb25lLAogICAgICAgIH0KICAgICAgICByZXR1"
    "cm4gZXZlbnQKCiAgICBkZWYgX2FkZF9kaWVfdG9fcG9vbChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuY3VycmVudF9wb29sW2RpZV90eXBlXSA9IGludChzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZGllX3R5cGUsIDApKSArIDEKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KGYi"
    "Q3VycmVudCBQb29sOiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX2FkanVzdF9wb29sX2RpZShzZWxmLCBk"
    "aWVfdHlwZTogc3RyLCBkZWx0YTogaW50KSAtPiBOb25lOgogICAgICAgIG5ld192YWwgPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wu"
    "Z2V0KGRpZV90eXBlLCAwKSkgKyBpbnQoZGVsdGEpCiAgICAgICAgaWYgbmV3X3ZhbCA8PSAwOgogICAgICAgICAgICBzZWxmLmN1"
    "cnJlbnRfcG9vbC5wb3AoZGllX3R5cGUsIE5vbmUpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xb"
    "ZGllX3R5cGVdID0gbmV3X3ZhbAogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQoKICAgIGRlZiBfcmVmcmVzaF9w"
    "b29sX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHdoaWxlIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5jb3VudCgpOgog"
    "ICAgICAgICAgICBpdGVtID0gc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3ID0gaXRlbS53"
    "aWRnZXQoKQogICAgICAgICAgICBpZiB3IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgdy5kZWxldGVMYXRlcigpCgogICAg"
    "ICAgIGZvciBkaWUsIHF0eSBpbiBzZWxmLl9zb3J0ZWRfcG9vbF9pdGVtcygpOgogICAgICAgICAgICBib3ggPSBRRnJhbWUoKQog"
    "ICAgICAgICAgICBib3guc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JP"
    "UkRFUn07IGJvcmRlci1yYWRpdXM6IDZweDsiKQogICAgICAgICAgICBsYXkgPSBRSEJveExheW91dChib3gpCiAgICAgICAgICAg"
    "IGxheS5zZXRDb250ZW50c01hcmdpbnMoNiwgNCwgNiwgNCkKICAgICAgICAgICAgbGF5LnNldFNwYWNpbmcoNCkKICAgICAgICAg"
    "ICAgbGJsID0gUUxhYmVsKGYie2RpZX0geHtxdHl9IikKICAgICAgICAgICAgbWludXNfYnRuID0gUVB1c2hCdXR0b24oIuKIkiIp"
    "CiAgICAgICAgICAgIHBsdXNfYnRuID0gUVB1c2hCdXR0b24oIisiKQogICAgICAgICAgICBtaW51c19idG4uc2V0Rml4ZWRXaWR0"
    "aCgyNCkKICAgICAgICAgICAgcGx1c19idG4uc2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgbWludXNfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChsYW1iZGEgXz1GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCAtMSkpCiAgICAgICAgICAgIHBs"
    "dXNfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgXz1GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCArMSkp"
    "CiAgICAgICAgICAgIGxheS5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KG1pbnVzX2J0bikKICAgICAg"
    "ICAgICAgbGF5LmFkZFdpZGdldChwbHVzX2J0bikKICAgICAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LmFkZFdpZGdl"
    "dChib3gpCgogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5wb29sX2V4"
    "cHJfbGJsLnNldFRleHQoZiJQb29sOiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX3F1aWNrX3JvbGxfc2lu"
    "Z2xlX2RpZShzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEo"
    "e2RpZV90eXBlOiAxfSwgaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSksIHNlbGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwg"
    "c2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIiIpCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQp"
    "CgogICAgZGVmIF9yb2xsX2N1cnJlbnRfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAgIHBvb2wgPSBkaWN0KHNlbGYuY3VycmVu"
    "dF9wb29sKQogICAgICAgIHJ1bGVfaWQgPSBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERhdGEoKSBvciAiIgogICAgICAgIGlmIG5v"
    "dCBwb29sIGFuZCBub3QgcnVsZV9pZDoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9s"
    "bGVyIiwgIkN1cnJlbnQgUG9vbCBpcyBlbXB0eS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA9IHNlbGYuX3Jv"
    "bGxfcG9vbF9kYXRhKHBvb2wsIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlw"
    "KCksIHJ1bGVfaWQpCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9yZWNvcmRfcm9sbF9l"
    "dmVudChzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzLmFwcGVuZChldmVudCkKICAg"
    "ICAgICBzZWxmLmV2ZW50X2J5X2lkW2V2ZW50WyJpZCJdXSA9IGV2ZW50CiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzID0g"
    "W2V2ZW50WyJpZCJdXQoKICAgICAgICBzZWxmLl9yZXBsYWNlX2N1cnJlbnRfcm93cyhbZXZlbnRdKQogICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9oaXN0b3J5X3JvdyhldmVudCkKICAgICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuX3Vw"
    "ZGF0ZV9yZXN1bHRfZGlzcGxheShldmVudCkKICAgICAgICBzZWxmLl90cmFja19jb21tb25fc2lnbmF0dXJlKGV2ZW50KQogICAg"
    "ICAgIHNlbGYuX3BsYXlfcm9sbF9zb3VuZCgpCgogICAgZGVmIF9yZXBsYWNlX2N1cnJlbnRfcm93cyhzZWxmLCBldmVudHM6IGxp"
    "c3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGV2"
    "ZW50IGluIGV2ZW50czoKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmN1cnJlbnRfdGFibGUsIGV2ZW50"
    "KQoKICAgIGRlZiBfYXBwZW5kX2hpc3Rvcnlfcm93KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Fw"
    "cGVuZF90YWJsZV9yb3coc2VsZi5oaXN0b3J5X3RhYmxlLCBldmVudCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2Nyb2xs"
    "VG9Cb3R0b20oKQoKICAgIGRlZiBfZm9ybWF0X3JhdyhzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAgIGdyb3VwZWQg"
    "PSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBiaXRzID0gW10KICAgICAgICBmb3Ig"
    "ZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYg"
    "dmFsczoKICAgICAgICAgICAgICAgIGJpdHMuYXBwZW5kKGYie2RpZX06IHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFscyl9"
    "IikKICAgICAgICByZXR1cm4gIiB8ICIuam9pbihiaXRzKQoKICAgIGRlZiBfYXBwZW5kX3RhYmxlX3JvdyhzZWxmLCB0YWJsZTog"
    "UVRhYmxlV2lkZ2V0LCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICByb3cgPSB0YWJsZS5yb3dDb3VudCgpCiAgICAgICAg"
    "dGFibGUuaW5zZXJ0Um93KHJvdykKCiAgICAgICAgdHNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZXZlbnRbInRpbWVzdGFtcCJd"
    "KQogICAgICAgIHRzX2l0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGV2ZW50WyJpZCJdKQogICAgICAgIHRh"
    "YmxlLnNldEl0ZW0ocm93LCAwLCB0c19pdGVtKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVt"
    "KGV2ZW50LmdldCgibGFiZWwiLCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKGV2"
    "ZW50LmdldCgiZXhwcmVzc2lvbiIsICIiKSkpCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdldEl0ZW0o"
    "c2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQoKICAgICAgICBtb2Rfc3BpbiA9IFFTcGluQm94KCkKICAgICAgICBtb2Rfc3Bpbi5z"
    "ZXRSYW5nZSgtOTk5LCA5OTkpCiAgICAgICAgbW9kX3NwaW4uc2V0VmFsdWUoaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkp"
    "CiAgICAgICAgbW9kX3NwaW4udmFsdWVDaGFuZ2VkLmNvbm5lY3QobGFtYmRhIHZhbCwgZWlkPWV2ZW50WyJpZCJdOiBzZWxmLl9v"
    "bl9tb2RpZmllcl9jaGFuZ2VkKGVpZCwgdmFsKSkKICAgICAgICB0YWJsZS5zZXRDZWxsV2lkZ2V0KHJvdywgNCwgbW9kX3NwaW4p"
    "CgogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCA1LCBRVGFibGVXaWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFs"
    "IiwgMCkpKSkKCiAgICBkZWYgX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIGV2ZW50X2lk"
    "OiBzdHIsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGZvciByb3cgaW4gcmFuZ2UodGFibGUucm93Q291bnQoKSk6CiAg"
    "ICAgICAgICAgIGl0ID0gdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgICAgIGlmIGl0IGFuZCBpdC5kYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSkgPT0gZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwgUVRhYmxlV2lk"
    "Z2V0SXRlbShzdHIoZXZlbnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSkpCiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJv"
    "dywgMywgUVRhYmxlV2lkZ2V0SXRlbShzZWxmLl9mb3JtYXRfcmF3KGV2ZW50KSkpCiAgICAgICAgICAgICAgICBicmVhawoKICAg"
    "IGRlZiBfb25fbW9kaWZpZXJfY2hhbmdlZChzZWxmLCBldmVudF9pZDogc3RyLCB2YWx1ZTogaW50KSAtPiBOb25lOgogICAgICAg"
    "IGV2dCA9IHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGV2ZW50X2lkKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIGV2dFsibW9kaWZpZXIiXSA9IGludCh2YWx1ZSkKICAgICAgICBldnRbImZpbmFsX3RvdGFsIl0gPSBpbnQoZXZ0"
    "LmdldCgic3VidG90YWwiLCAwKSkgKyBpbnQodmFsdWUpCiAgICAgICAgc2VsZi5fc3luY19yb3dfYnlfZXZlbnRfaWQoc2VsZi5o"
    "aXN0b3J5X3RhYmxlLCBldmVudF9pZCwgZXZ0KQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYuY3VycmVu"
    "dF90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIGlmIHNlbGYu"
    "Y3VycmVudF9yb2xsX2lkcyBhbmQgc2VsZi5jdXJyZW50X3JvbGxfaWRzWzBdID09IGV2ZW50X2lkOgogICAgICAgICAgICBzZWxm"
    "Ll91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZ0KQoKICAgIGRlZiBfdXBkYXRlX2dyYW5kX3RvdGFsKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgdG90YWwgPSBzdW0oaW50KGV2dC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpIGZvciBldnQgaW4gc2VsZi5yb2xsX2V2ZW50"
    "cykKICAgICAgICBzZWxmLmdyYW5kX3RvdGFsX2xibC5zZXRUZXh0KGYiR3JhbmQgVG90YWw6IHt0b3RhbH0iKQoKICAgIGRlZiBf"
    "dXBkYXRlX3Jlc3VsdF9kaXNwbGF5KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGdyb3VwZWQgPSBldmVudC5n"
    "ZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBsaW5lcyA9IFtdCiAgICAgICAgZm9yIGRpZSBpbiBz"
    "ZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAg"
    "ICAgICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJ7ZGllfSB4e2xlbih2YWxzKX0g4oaSIFt7JywnLmpvaW4oc3RyKHYpIGZvciB2"
    "IGluIHZhbHMpfV0iKQogICAgICAgIHJ1bGVfaWQgPSBldmVudC5nZXQoInJ1bGVfaWQiKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAg"
    "ICAgICAgICAgIHJ1bGVfbmFtZSA9IHNlbGYucnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1"
    "bGVfaWQpCiAgICAgICAgICAgIGxpbmVzLmFwcGVuZChmIlJ1bGU6IHtydWxlX25hbWV9IikKICAgICAgICBsaW5lcy5hcHBlbmQo"
    "ZiJNb2RpZmllcjoge2ludChldmVudC5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIpCiAgICAgICAgbGluZXMuYXBwZW5kKGYiVG90"
    "YWw6IHtldmVudC5nZXQoJ2ZpbmFsX3RvdGFsJywgMCl9IikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0"
    "KCJcbiIuam9pbihsaW5lcykpCgoKICAgIGRlZiBfc2F2ZV9wb29sKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYu"
    "Y3VycmVudF9wb29sOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRGljZSBSb2xsZXIiLCAiQnVp"
    "bGQgYSBDdXJyZW50IFBvb2wgYmVmb3JlIHNhdmluZy4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWZhdWx0X25hbWUg"
    "PSBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlwKCkgb3Igc2VsZi5fcG9vbF9leHByZXNzaW9uKCkKICAgICAgICBuYW1lLCBv"
    "ayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJTYXZlIFBvb2wiLCAiU2F2ZWQgcm9sbCBuYW1lOiIsIHRleHQ9ZGVmYXVs"
    "dF9uYW1lKQogICAgICAgIGlmIG5vdCBvazoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZCA9IHsKICAgICAgICAg"
    "ICAgImlkIjogZiJzYXZlZF97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogbmFtZS5zdHJpcCgp"
    "IG9yIGRlZmF1bHRfbmFtZSwKICAgICAgICAgICAgInBvb2wiOiBkaWN0KHNlbGYuY3VycmVudF9wb29sKSwKICAgICAgICAgICAg"
    "Im1vZGlmaWVyIjogaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSksCiAgICAgICAgICAgICJydWxlX2lkIjogc2VsZi5ydWxlX2Nv"
    "bWJvLmN1cnJlbnREYXRhKCkgb3IgTm9uZSwKICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICJjYXRlZ29yeSI6"
    "ICJzYXZlZCIsCiAgICAgICAgfQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHBheWxvYWQpCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9yZWZyZXNoX3NhdmVkX2xpc3RzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5zYXZlZF9saXN0LmNsZWFyKCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLnNhdmVkX3JvbGxzOgogICAgICAgICAgICBl"
    "eHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntpdGVt"
    "LmdldCgnbmFtZScpfSDigJQge2V4cHJ9IHtpbnQoaXRlbS5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIKICAgICAgICAgICAgbHcg"
    "PSBRTGlzdFdpZGdldEl0ZW0odHh0KQogICAgICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRl"
    "bSkKICAgICAgICAgICAgc2VsZi5zYXZlZF9saXN0LmFkZEl0ZW0obHcpCgogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuY2xlYXIo"
    "KQogICAgICAgIHJhbmtlZCA9IHNvcnRlZChzZWxmLmNvbW1vbl9yb2xscy52YWx1ZXMoKSwga2V5PWxhbWJkYSB4OiB4LmdldCgi"
    "Y291bnQiLCAwKSwgcmV2ZXJzZT1UcnVlKQogICAgICAgIGZvciBpdGVtIGluIHJhbmtlZDoKICAgICAgICAgICAgaWYgaW50KGl0"
    "ZW0uZ2V0KCJjb3VudCIsIDApKSA8IDI6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBleHByID0gc2VsZi5f"
    "cG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntleHByfSB7aW50KGl0ZW0u"
    "Z2V0KCdtb2RpZmllcicsIDApKTorZH0gKHh7aXRlbS5nZXQoJ2NvdW50JywgMCl9KSIKICAgICAgICAgICAgbHcgPSBRTGlzdFdp"
    "ZGdldEl0ZW0odHh0KQogICAgICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAgICAg"
    "ICAgICAgc2VsZi5jb21tb25fbGlzdC5hZGRJdGVtKGx3KQoKICAgIGRlZiBfdHJhY2tfY29tbW9uX3NpZ25hdHVyZShzZWxmLCBl"
    "dmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBzaWcgPSBzZWxmLl9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmUoZXZlbnQuZ2V0"
    "KCJwb29sIiwge30pLCBpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwgc3RyKGV2ZW50LmdldCgicnVsZV9pZCIpIG9yICIi"
    "KSkKICAgICAgICBpZiBzaWcgbm90IGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9yb2xsc1tz"
    "aWddID0gewogICAgICAgICAgICAgICAgInNpZ25hdHVyZSI6IHNpZywKICAgICAgICAgICAgICAgICJjb3VudCI6IDAsCiAgICAg"
    "ICAgICAgICAgICAibmFtZSI6IGV2ZW50LmdldCgibGFiZWwiLCAiIikgb3Igc2lnLAogICAgICAgICAgICAgICAgInBvb2wiOiBk"
    "aWN0KGV2ZW50LmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQoZXZlbnQuZ2V0KCJtb2Rp"
    "ZmllciIsIDApKSwKICAgICAgICAgICAgICAgICJydWxlX2lkIjogZXZlbnQuZ2V0KCJydWxlX2lkIiksCiAgICAgICAgICAgICAg"
    "ICAibm90ZXMiOiAiIiwKICAgICAgICAgICAgICAgICJjYXRlZ29yeSI6ICJjb21tb24iLAogICAgICAgICAgICB9CiAgICAgICAg"
    "c2VsZi5jb21tb25fcm9sbHNbc2lnXVsiY291bnQiXSA9IGludChzZWxmLmNvbW1vbl9yb2xsc1tzaWddLmdldCgiY291bnQiLCAw"
    "KSkgKyAxCiAgICAgICAgaWYgc2VsZi5jb21tb25fcm9sbHNbc2lnXVsiY291bnQiXSA+PSAzOgogICAgICAgICAgICBzZWxmLmNv"
    "bW1vbl9oaW50LnNldFRleHQoZiJTdWdnZXN0aW9uOiBwcm9tb3RlIHtzZWxmLl9wb29sX2V4cHJlc3Npb24oZXZlbnQuZ2V0KCdw"
    "b29sJywge30pKX0gdG8gU2F2ZWQuIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3J1bl9z"
    "YXZlZF9yb2xsKHNlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKToKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxmLl9yb2xsX3Bvb2xfZGF0YSgKICAgICAgICAgICAgZGljdChwYXlsb2FkLmdldCgi"
    "cG9vbCIsIHt9KSksCiAgICAgICAgICAgIGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgIHN0cihw"
    "YXlsb2FkLmdldCgibmFtZSIsICIiKSkuc3RyaXAoKSwKICAgICAgICAgICAgc3RyKHBheWxvYWQuZ2V0KCJydWxlX2lkIikgb3Ig"
    "IiIpLAogICAgICAgICkKICAgICAgICBzZWxmLl9yZWNvcmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX2xvYWRfcGF5bG9h"
    "ZF9pbnRvX3Bvb2woc2VsZiwgcGF5bG9hZDogZGljdCB8IE5vbmUpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuY3VycmVudF9wb29sID0gZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSkK"
    "ICAgICAgICBzZWxmLm1vZF9zcGluLnNldFZhbHVlKGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgc2Vs"
    "Zi5sYWJlbF9lZGl0LnNldFRleHQoc3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICByaWQgPSBwYXlsb2FkLmdl"
    "dCgicnVsZV9pZCIpCiAgICAgICAgaWR4ID0gc2VsZi5ydWxlX2NvbWJvLmZpbmREYXRhKHJpZCBvciAiIikKICAgICAgICBpZiBp"
    "ZHggPj0gMDoKICAgICAgICAgICAgc2VsZi5ydWxlX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fcmVm"
    "cmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDog"
    "e3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9ydW5fc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgaXRl"
    "bSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUpCgogICAgZGVmIF9sb2FkX3NlbGVjdGVkX3NhdmVkKHNl"
    "bGYpOgogICAgICAgIGl0ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdGVtLmRh"
    "dGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9sb2FkX3BheWxvYWRfaW50b19wb29sKHBheWxvYWQpCgogICAgICAgIG5hbWUs"
    "IG9rID0gUUlucHV0RGlhbG9nLmdldFRleHQoc2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOYW1lOiIsIHRleHQ9c3RyKHBheWxv"
    "YWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBheWxvYWRb"
    "Im5hbWUiXSA9IG5hbWUuc3RyaXAoKSBvciBwYXlsb2FkLmdldCgibmFtZSIsICIiKQogICAgICAgIHBheWxvYWRbInBvb2wiXSA9"
    "IGRpY3Qoc2VsZi5jdXJyZW50X3Bvb2wpCiAgICAgICAgcGF5bG9hZFsibW9kaWZpZXIiXSA9IGludChzZWxmLm1vZF9zcGluLnZh"
    "bHVlKCkpCiAgICAgICAgcGF5bG9hZFsicnVsZV9pZCJdID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgTm9uZQog"
    "ICAgICAgIG5vdGVzLCBva19ub3RlcyA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTm90"
    "ZXMgLyBjYXRlZ29yeToiLCB0ZXh0PXN0cihwYXlsb2FkLmdldCgibm90ZXMiLCAiIikpKQogICAgICAgIGlmIG9rX25vdGVzOgog"
    "ICAgICAgICAgICBwYXlsb2FkWyJub3RlcyJdID0gbm90ZXMKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAg"
    "ICBkZWYgX2RlbGV0ZV9zZWxlY3RlZF9zYXZlZChzZWxmKToKICAgICAgICByb3cgPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudFJv"
    "dygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuc2F2ZWRfcm9sbHMpOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLnBvcChyb3cpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAg"
    "ZGVmIF9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vbihzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50"
    "SXRlbSgpCiAgICAgICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBO"
    "b25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHByb21vdGVkID0gewogICAgICAg"
    "ICAgICAiaWQiOiBmInNhdmVkX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgIm5hbWUiOiBwYXlsb2FkLmdl"
    "dCgibmFtZSIpIG9yIHNlbGYuX3Bvb2xfZXhwcmVzc2lvbihwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJw"
    "b29sIjogZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJtb2RpZmllciI6IGludChwYXlsb2FkLmdl"
    "dCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgICJydWxlX2lkIjogcGF5bG9hZC5nZXQoInJ1bGVfaWQiKSwKICAgICAgICAg"
    "ICAgIm5vdGVzIjogcGF5bG9hZC5nZXQoIm5vdGVzIiwgIiIpLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiAic2F2ZWQiLAogICAg"
    "ICAgIH0KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLmFwcGVuZChwcm9tb3RlZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVk"
    "X2xpc3RzKCkKCiAgICBkZWYgX2Rpc21pc3Nfc2VsZWN0ZWRfY29tbW9uKHNlbGYpOgogICAgICAgIGl0ZW0gPSBzZWxmLmNvbW1v"
    "bl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkg"
    "aWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2lnID0g"
    "cGF5bG9hZC5nZXQoInNpZ25hdHVyZSIpCiAgICAgICAgaWYgc2lnIGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBz"
    "ZWxmLmNvbW1vbl9yb2xscy5wb3Aoc2lnLCBOb25lKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRl"
    "ZiBfcmVzZXRfcG9vbChzZWxmKToKICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbCA9IHt9CiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5z"
    "ZXRWYWx1ZSgwKQogICAgICAgIHNlbGYubGFiZWxfZWRpdC5jbGVhcigpCiAgICAgICAgc2VsZi5ydWxlX2NvbWJvLnNldEN1cnJl"
    "bnRJbmRleCgwKQogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRf"
    "bGJsLnNldFRleHQoIk5vIHJvbGwgeWV0LiIpCgogICAgZGVmIF9jbGVhcl9oaXN0b3J5KHNlbGYpOgogICAgICAgIHNlbGYucm9s"
    "bF9ldmVudHMuY2xlYXIoKQogICAgICAgIHNlbGYuZXZlbnRfYnlfaWQuY2xlYXIoKQogICAgICAgIHNlbGYuY3VycmVudF9yb2xs"
    "X2lkcyA9IFtdCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5jdXJyZW50X3Rh"
    "YmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLmN1cnJlbnRf"
    "cmVzdWx0X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfZXZlbnRfZnJvbV90YWJsZV9wb3NpdGlvbihzZWxm"
    "LCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3MpIC0+IGRpY3QgfCBOb25lOgogICAgICAgIGl0ZW0gPSB0YWJsZS5pdGVtQXQocG9z"
    "KQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJvdyA9IGl0ZW0ucm93KCkKICAg"
    "ICAgICB0c19pdGVtID0gdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYgbm90IHRzX2l0ZW06CiAgICAgICAgICAgIHJldHVy"
    "biBOb25lCiAgICAgICAgZWlkID0gdHNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICByZXR1cm4g"
    "c2VsZi5ldmVudF9ieV9pZC5nZXQoZWlkKQoKICAgIGRlZiBfc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLCB0YWJsZTogUVRh"
    "YmxlV2lkZ2V0LCBwb3MpIC0+IE5vbmU6CiAgICAgICAgZXZ0ID0gc2VsZi5fZXZlbnRfZnJvbV90YWJsZV9wb3NpdGlvbih0YWJs"
    "ZSwgcG9zKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdl"
    "dHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9IFFNZW51KHNlbGYpCiAgICAgICAgYWN0X3NlbmQgPSBtZW51LmFkZEFjdGlv"
    "bigiU2VuZCB0byBQcm9tcHQiKQogICAgICAgIGNob3NlbiA9IG1lbnUuZXhlYyh0YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFs"
    "KHBvcykpCiAgICAgICAgaWYgY2hvc2VuID09IGFjdF9zZW5kOgogICAgICAgICAgICBzZWxmLl9zZW5kX2V2ZW50X3RvX3Byb21w"
    "dChldnQpCgogICAgZGVmIF9mb3JtYXRfZXZlbnRfZm9yX3Byb21wdChzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAg"
    "IGxhYmVsID0gKGV2ZW50LmdldCgibGFiZWwiKSBvciAiUm9sbCIpLnN0cmlwKCkKICAgICAgICBncm91cGVkID0gZXZlbnQuZ2V0"
    "KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgc2VnbWVudHMgPSBbXQogICAgICAgIGZvciBkaWUgaW4g"
    "c2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgog"
    "ICAgICAgICAgICAgICAgc2VnbWVudHMuYXBwZW5kKGYie2RpZX0gcm9sbGVkIHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFs"
    "cyl9IikKICAgICAgICBtb2QgPSBpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKQogICAgICAgIHRvdGFsID0gaW50KGV2ZW50"
    "LmdldCgiZmluYWxfdG90YWwiLCAwKSkKICAgICAgICByZXR1cm4gZiJ7bGFiZWx9OiB7JzsgJy5qb2luKHNlZ21lbnRzKX07IG1v"
    "ZGlmaWVyIHttb2Q6K2R9OyB0b3RhbCB7dG90YWx9IgoKICAgIGRlZiBfc2VuZF9ldmVudF90b19wcm9tcHQoc2VsZiwgZXZlbnQ6"
    "IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgd2luZG93ID0gc2VsZi53aW5kb3coKQogICAgICAgIGlmIG5vdCB3aW5kb3cgb3Igbm90"
    "IGhhc2F0dHIod2luZG93LCAiX2lucHV0X2ZpZWxkIik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGxpbmUgPSBzZWxmLl9m"
    "b3JtYXRfZXZlbnRfZm9yX3Byb21wdChldmVudCkKICAgICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldFRleHQobGluZSkKICAg"
    "ICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICBkZWYgX3BsYXlfcm9sbF9zb3VuZChzZWxmKToKICAgICAg"
    "ICBpZiBub3QgV0lOU09VTkRfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgd2luc291bmQu"
    "QmVlcCg4NDAsIDMwKQogICAgICAgICAgICB3aW5zb3VuZC5CZWVwKDYyMCwgMzUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcGFzcwoKCgpjbGFzcyBNYWdpYzhCYWxsVGFiKFFXaWRnZXQpOgogICAgIiIiTWFnaWMgOC1CYWxsIG1vZHVs"
    "ZSB3aXRoIGNpcmN1bGFyIG9yYiBkaXNwbGF5IGFuZCBwdWxzaW5nIGFuc3dlciB0ZXh0LiIiIgoKICAgIEFOU1dFUlMgPSBbCiAg"
    "ICAgICAgIkl0IGlzIGNlcnRhaW4uIiwKICAgICAgICAiSXQgaXMgZGVjaWRlZGx5IHNvLiIsCiAgICAgICAgIldpdGhvdXQgYSBk"
    "b3VidC4iLAogICAgICAgICJZZXMgZGVmaW5pdGVseS4iLAogICAgICAgICJZb3UgbWF5IHJlbHkgb24gaXQuIiwKICAgICAgICAi"
    "QXMgSSBzZWUgaXQsIHllcy4iLAogICAgICAgICJNb3N0IGxpa2VseS4iLAogICAgICAgICJPdXRsb29rIGdvb2QuIiwKICAgICAg"
    "ICAiWWVzLiIsCiAgICAgICAgIlNpZ25zIHBvaW50IHRvIHllcy4iLAogICAgICAgICJSZXBseSBoYXp5LCB0cnkgYWdhaW4uIiwK"
    "ICAgICAgICAiQXNrIGFnYWluIGxhdGVyLiIsCiAgICAgICAgIkJldHRlciBub3QgdGVsbCB5b3Ugbm93LiIsCiAgICAgICAgIkNh"
    "bm5vdCBwcmVkaWN0IG5vdy4iLAogICAgICAgICJDb25jZW50cmF0ZSBhbmQgYXNrIGFnYWluLiIsCiAgICAgICAgIkRvbid0IGNv"
    "dW50IG9uIGl0LiIsCiAgICAgICAgIk15IHJlcGx5IGlzIG5vLiIsCiAgICAgICAgIk15IHNvdXJjZXMgc2F5IG5vLiIsCiAgICAg"
    "ICAgIk91dGxvb2sgbm90IHNvIGdvb2QuIiwKICAgICAgICAiVmVyeSBkb3VidGZ1bC4iLAogICAgXQoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBvbl90aHJvdz1Ob25lLCBkaWFnbm9zdGljc19sb2dnZXI9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygp"
    "CiAgICAgICAgc2VsZi5fb25fdGhyb3cgPSBvbl90aHJvdwogICAgICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBv"
    "ciAobGFtYmRhICpfYXJncywgKipfa3dhcmdzOiBOb25lKQogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gIiIKCiAgICAg"
    "ICAgc2VsZi5fY2xlYXJfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci5zZXRTaW5nbGVTaG90"
    "KFRydWUpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2ZhZGVfb3V0X2Fuc3dlcikKCiAg"
    "ICAgICAgc2VsZi5fYnVpbGRfdWkoKQogICAgICAgIHNlbGYuX2J1aWxkX2FuaW1hdGlvbnMoKQogICAgICAgIHNlbGYuX3NldF9p"
    "ZGxlX3Zpc3VhbCgpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDE2LCAxNiwgMTYsIDE2KQogICAgICAgIHJvb3Quc2V0U3BhY2lu"
    "ZygxNCkKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKCiAgICAgICAgc2VsZi5fb3JiX2ZyYW1lID0gUUZyYW1lKCkKICAgICAg"
    "ICBzZWxmLl9vcmJfZnJhbWUuc2V0Rml4ZWRTaXplKDIyOCwgMjI4KQogICAgICAgIHNlbGYuX29yYl9mcmFtZS5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsiCiAgICAgICAgICAgICJiYWNrZ3JvdW5kLWNvbG9yOiAjMDQwNDA2OyIKICAgICAg"
    "ICAgICAgImJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjM0LCAyMzcsIDI1NSwgMC42Mik7IgogICAgICAgICAgICAiYm9yZGVyLXJh"
    "ZGl1czogMTE0cHg7IgogICAgICAgICAgICAifSIKICAgICAgICApCgogICAgICAgIG9yYl9sYXlvdXQgPSBRVkJveExheW91dChz"
    "ZWxmLl9vcmJfZnJhbWUpCiAgICAgICAgb3JiX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMjAsIDIwLCAyMCwgMjApCiAgICAg"
    "ICAgb3JiX2xheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX29yYl9pbm5lciA9IFFGcmFtZSgpCiAgICAgICAgc2Vs"
    "Zi5fb3JiX2lubmVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICJRRnJhbWUgeyIKICAgICAgICAgICAgImJhY2tncm91bmQt"
    "Y29sb3I6ICMwNzA3MGE7IgogICAgICAgICAgICAiYm9yZGVyOiAxcHggc29saWQgcmdiYSgyNTUsIDI1NSwgMjU1LCAwLjEyKTsi"
    "CiAgICAgICAgICAgICJib3JkZXItcmFkaXVzOiA4NHB4OyIKICAgICAgICAgICAgIn0iCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X29yYl9pbm5lci5zZXRNaW5pbXVtU2l6ZSgxNjgsIDE2OCkKICAgICAgICBzZWxmLl9vcmJfaW5uZXIuc2V0TWF4aW11bVNpemUo"
    "MTY4LCAxNjgpCgogICAgICAgIGlubmVyX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX29yYl9pbm5lcikKICAgICAgICBpbm5l"
    "cl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDE2LCAxNiwgMTYsIDE2KQogICAgICAgIGlubmVyX2xheW91dC5zZXRTcGFjaW5n"
    "KDApCgogICAgICAgIHNlbGYuX2VpZ2h0X2xibCA9IFFMYWJlbCgiOCIpCiAgICAgICAgc2VsZi5fZWlnaHRfbGJsLnNldEFsaWdu"
    "bWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICAiY29sb3I6IHJnYmEoMjU1LCAyNTUsIDI1NSwgMC45NSk7ICIKICAgICAgICAgICAgImZvbnQtc2l6ZTogODBw"
    "eDsgZm9udC13ZWlnaHQ6IDcwMDsgIgogICAgICAgICAgICAiZm9udC1mYW1pbHk6IEdlb3JnaWEsIHNlcmlmOyBib3JkZXI6IG5v"
    "bmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuYW5zd2VyX2xi"
    "bC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0V29y"
    "ZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "R09MRH07IGZvbnQtc2l6ZTogMTZweDsgZm9udC1zdHlsZTogaXRhbGljOyAiCiAgICAgICAgICAgICJmb250LXdlaWdodDogNjAw"
    "OyBib3JkZXI6IG5vbmU7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBpbm5lcl9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2VpZ2h0X2xibCwgMSkKICAgICAgICBpbm5lcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuYW5zd2VyX2xibCwgMSkKICAgICAg"
    "ICBvcmJfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9vcmJfaW5uZXIsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCgog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX29yYl9mcmFtZSwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkhDZW50ZXIpCgog"
    "ICAgICAgIHNlbGYudGhyb3dfYnRuID0gUVB1c2hCdXR0b24oIlRocm93IHRoZSA4LUJhbGwiKQogICAgICAgIHNlbGYudGhyb3df"
    "YnRuLnNldEZpeGVkSGVpZ2h0KDM4KQogICAgICAgIHNlbGYudGhyb3dfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90aHJvd19i"
    "YWxsKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYudGhyb3dfYnRuLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduSENlbnRl"
    "cikKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxkX2FuaW1hdGlvbnMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eSA9IFFHcmFwaGljc09wYWNpdHlFZmZlY3Qoc2VsZi5hbnN3ZXJfbGJsKQogICAgICAg"
    "IHNlbGYuYW5zd2VyX2xibC5zZXRHcmFwaGljc0VmZmVjdChzZWxmLl9hbnN3ZXJfb3BhY2l0eSkKICAgICAgICBzZWxmLl9hbnN3"
    "ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuMCkKCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbSA9IFFQcm9wZXJ0eUFuaW1hdGlvbihz"
    "ZWxmLl9hbnN3ZXJfb3BhY2l0eSwgYiJvcGFjaXR5Iiwgc2VsZikKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldER1cmF0aW9u"
    "KDc2MCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldFN0YXJ0VmFsdWUoMC4zNSkKICAgICAgICBzZWxmLl9wdWxzZV9hbmlt"
    "LnNldEVuZFZhbHVlKDEuMCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldEVhc2luZ0N1cnZlKFFFYXNpbmdDdXJ2ZS5UeXBl"
    "LkluT3V0U2luZSkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldExvb3BDb3VudCgtMSkKCiAgICAgICAgc2VsZi5fZmFkZV9v"
    "dXQgPSBRUHJvcGVydHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAgc2Vs"
    "Zi5fZmFkZV9vdXQuc2V0RHVyYXRpb24oNTYwKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldFN0YXJ0VmFsdWUoMS4wKQogICAg"
    "ICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVuZFZhbHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFYXNpbmdDdXJ2ZShR"
    "RWFzaW5nQ3VydmUuVHlwZS5Jbk91dFF1YWQpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9j"
    "bGVhcl90b19pZGxlKQoKICAgIGRlZiBfc2V0X2lkbGVfdmlzdWFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY3VycmVu"
    "dF9hbnN3ZXIgPSAiIgogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5zaG93KCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuY2xlYXIo"
    "KQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5oaWRlKCkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAu"
    "MCkKCiAgICBkZWYgX3Rocm93X2JhbGwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci5zdG9wKCkKICAg"
    "ICAgICBzZWxmLl9wdWxzZV9hbmltLnN0b3AoKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnN0b3AoKQoKICAgICAgICBhbnN3ZXIg"
    "PSByYW5kb20uY2hvaWNlKHNlbGYuQU5TV0VSUykKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9IGFuc3dlcgoKICAgICAg"
    "ICBzZWxmLl9laWdodF9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFRleHQoYW5zd2VyKQogICAgICAgIHNl"
    "bGYuYW5zd2VyX2xibC5zaG93KCkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuMCkKICAgICAgICBz"
    "ZWxmLl9wdWxzZV9hbmltLnN0YXJ0KCkKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci5zdGFydCg2MDAwMCkKICAgICAgICBzZWxm"
    "Ll9sb2coZiJbOEJBTExdIFRocm93IHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYu"
    "X29uX3Rocm93KToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fb25fdGhyb3coYW5zd2VyKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9nKGYiWzhCQUxMXVtXQVJOXSBJbnRl"
    "cm5hbCBwcm9tcHQgZGlzcGF0Y2ggZmFpbGVkOiB7ZXh9IiwgIldBUk4iKQoKICAgIGRlZiBfZmFkZV9vdXRfYW5zd2VyKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdG9wKCkK"
    "ICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZhbHVlKGZsb2F0KHNl"
    "bGYuX2Fuc3dlcl9vcGFjaXR5Lm9wYWNpdHkoKSkpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RW5kVmFsdWUoMC4wKQogICAg"
    "ICAgIHNlbGYuX2ZhZGVfb3V0LnN0YXJ0KCkKCiAgICBkZWYgX2NsZWFyX3RvX2lkbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9mYWRlX291dC5zdG9wKCkKICAgICAgICBzZWxmLl9zZXRfaWRsZV92aXN1YWwoKQoKIyDilIDilIAgTUFJTiBXSU5ET1cg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExvY2tBd2FyZVRhYkJhcihRVGFiQmFyKToKICAg"
    "ICIiIlRhYiBiYXIgdGhhdCBibG9ja3MgZHJhZyBpbml0aWF0aW9uIGZvciBsb2NrZWQgdGFicy4iIiIKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgaXNfbG9ja2VkX2J5X2lkLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5faXNfbG9ja2VkX2J5X2lkID0gaXNfbG9ja2VkX2J5X2lkCiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRleCA9"
    "IC0xCgogICAgZGVmIF90YWJfaWQoc2VsZiwgaW5kZXg6IGludCk6CiAgICAgICAgaWYgaW5kZXggPCAwOgogICAgICAgICAgICBy"
    "ZXR1cm4gTm9uZQogICAgICAgIHJldHVybiBzZWxmLnRhYkRhdGEoaW5kZXgpCgogICAgZGVmIG1vdXNlUHJlc3NFdmVudChzZWxm"
    "LCBldmVudCk6CiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRleCA9IHNlbGYudGFiQXQoZXZlbnQucG9zKCkpCiAgICAgICAgaWYg"
    "KGV2ZW50LmJ1dHRvbigpID09IFF0Lk1vdXNlQnV0dG9uLkxlZnRCdXR0b24gYW5kIHNlbGYuX3ByZXNzZWRfaW5kZXggPj0gMCk6"
    "CiAgICAgICAgICAgIHRhYl9pZCA9IHNlbGYuX3RhYl9pZChzZWxmLl9wcmVzc2VkX2luZGV4KQogICAgICAgICAgICBpZiB0YWJf"
    "aWQgYW5kIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCh0YWJfaWQpOgogICAgICAgICAgICAgICAgc2VsZi5zZXRDdXJyZW50SW5kZXgo"
    "c2VsZi5fcHJlc3NlZF9pbmRleCkKICAgICAgICAgICAgICAgIGV2ZW50LmFjY2VwdCgpCiAgICAgICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzdXBlcigpLm1vdXNlUHJlc3NFdmVudChldmVudCkKCiAgICBkZWYgbW91c2VNb3ZlRXZlbnQoc2VsZiwgZXZlbnQp"
    "OgogICAgICAgIGlmIHNlbGYuX3ByZXNzZWRfaW5kZXggPj0gMDoKICAgICAgICAgICAgdGFiX2lkID0gc2VsZi5fdGFiX2lkKHNl"
    "bGYuX3ByZXNzZWRfaW5kZXgpCiAgICAgICAgICAgIGlmIHRhYl9pZCBhbmQgc2VsZi5faXNfbG9ja2VkX2J5X2lkKHRhYl9pZCk6"
    "CiAgICAgICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3Vz"
    "ZU1vdmVFdmVudChldmVudCkKCiAgICBkZWYgbW91c2VSZWxlYXNlRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHNlbGYuX3By"
    "ZXNzZWRfaW5kZXggPSAtMQogICAgICAgIHN1cGVyKCkubW91c2VSZWxlYXNlRXZlbnQoZXZlbnQpCgoKY2xhc3MgRWNob0RlY2so"
    "UU1haW5XaW5kb3cpOgogICAgIiIiCiAgICBUaGUgbWFpbiBFY2hvIERlY2sgd2luZG93LgogICAgQXNzZW1ibGVzIGFsbCB3aWRn"
    "ZXRzLCBjb25uZWN0cyBhbGwgc2lnbmFscywgbWFuYWdlcyBhbGwgc3RhdGUuCiAgICAiIiIKCiAgICAjIOKUgOKUgCBUb3Jwb3Ig"
    "dGhyZXNob2xkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgIF9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQiAgICA9IDEuNSAgICMgZXh0ZXJuYWwgVlJBTSA+IHRoaXMg4oaSIGNvbnNpZGVy"
    "IHRvcnBvcgogICAgX0VYVEVSTkFMX1ZSQU1fV0FLRV9HQiAgICAgID0gMC44ICAgIyBleHRlcm5hbCBWUkFNIDwgdGhpcyDihpIg"
    "Y29uc2lkZXIgd2FrZQogICAgX1RPUlBPUl9TVVNUQUlORURfVElDS1MgICAgID0gNiAgICAgIyA2IMOXIDVzID0gMzAgc2Vjb25k"
    "cyBzdXN0YWluZWQKICAgIF9XQUtFX1NVU1RBSU5FRF9USUNLUyAgICAgICA9IDEyICAgICMgNjAgc2Vjb25kcyBzdXN0YWluZWQg"
    "bG93IHByZXNzdXJlCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQoKICAgICAgICAj"
    "IOKUgOKUgCBDb3JlIHN0YXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXR1cyAgICAgICAgICAgICAgPSAiT0ZGTElORSIKICAgICAgICBzZWxm"
    "Ll9zZXNzaW9uX3N0YXJ0ICAgICAgID0gdGltZS50aW1lKCkKICAgICAgICBzZWxmLl90b2tlbl9jb3VudCAgICAgICAgID0gMAog"
    "ICAgICAgIHNlbGYuX2ZhY2VfbG9ja2VkICAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlICAgICAgICAg"
    "PSBUcnVlCiAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgICAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAg"
    "ICAgICAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2Vs"
    "Zi5fYWN0aXZlX3RocmVhZHM6IGxpc3QgPSBbXSAgIyBrZWVwIHJlZnMgdG8gcHJldmVudCBHQyB3aGlsZSBydW5uaW5nCiAgICAg"
    "ICAgc2VsZi5fZmlyc3RfdG9rZW46IGJvb2wgPSBUcnVlICAgIyB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCBzdHJl"
    "YW1pbmcgdG9rZW4KCiAgICAgICAgIyBUb3Jwb3IgLyBWUkFNIHRyYWNraW5nCiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlICAg"
    "ICAgICA9ICJBV0FLRSIKICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSAgPSAwLjAgICAjIGJhc2VsaW5lIFZSQU0gYWZ0ZXIg"
    "bW9kZWwgbG9hZAogICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwICAgICAjIHN1c3RhaW5lZCBwcmVzc3VyZSBj"
    "b3VudGVyCiAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAgICAgICMgc3VzdGFpbmVkIHJlbGllZiBjb3VudGVy"
    "CiAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSAgICAgICAg"
    "PSBOb25lICAjIGRhdGV0aW1lIHdoZW4gdG9ycG9yIGJlZ2FuCiAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uICA9ICIi"
    "ICAgIyBmb3JtYXR0ZWQgZHVyYXRpb24gc3RyaW5nCgogICAgICAgICMg4pSA4pSAIE1hbmFnZXJzIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X21lbW9yeSAgID0gTWVtb3J5TWFuYWdlcigpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMgPSBTZXNzaW9uTWFuYWdlcigpCiAgICAg"
    "ICAgc2VsZi5fbGVzc29ucyAgPSBMZXNzb25zTGVhcm5lZERCKCkKICAgICAgICBzZWxmLl90YXNrcyAgICA9IFRhc2tNYW5hZ2Vy"
    "KCkKICAgICAgICBzZWxmLl9yZWNvcmRzX2NhY2hlOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9yZWNvcmRzX2luaXRp"
    "YWxpemVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2Vs"
    "Zi5fZ29vZ2xlX2F1dGhfcmVhZHkgPSBGYWxzZQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyOiBPcHRpb25hbFtR"
    "VGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0g"
    "PSBOb25lCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9"
    "IC0xCiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRl"
    "ciA9ICJuZXh0XzNfbW9udGhzIgoKICAgICAgICAjIFJpZ2h0IHN5c3RlbXMgdGFiLXN0cmlwIHByZXNlbnRhdGlvbiBzdGF0ZSAo"
    "c3RhYmxlIElEcyArIHZpc3VhbCBvcmRlcikKICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVmczogbGlzdFtkaWN0XSA9IFtdCiAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9t"
    "b3ZlX21vZGVfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2ln"
    "bmFsID0gRmFsc2UKICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxsX3RhYnMgPSBGYWxzZQoKICAgICAgICAjIOKU"
    "gOKUgCBHb29nbGUgU2VydmljZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgIyBJbnN0YW50aWF0ZSBzZXJ2aWNlIHdyYXBwZXJzIHVwLWZyb250OyBhdXRoIGlzIGZvcmNlZCBsYXRlcgog"
    "ICAgICAgICMgZnJvbSBtYWluKCkgYWZ0ZXIgd2luZG93LnNob3coKSB3aGVuIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAg"
    "ICAgICAgZ19jcmVkc19wYXRoID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAiY3JlZGVudGlh"
    "bHMiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIikKICAgICAg"
    "ICApKQogICAgICAgIGdfdG9rZW5fcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgInRv"
    "a2VuIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIikKICAgICAgICApKQogICAgICAg"
    "IHNlbGYuX2djYWwgPSBHb29nbGVDYWxlbmRhclNlcnZpY2UoZ19jcmVkc19wYXRoLCBnX3Rva2VuX3BhdGgpCiAgICAgICAgc2Vs"
    "Zi5fZ2RyaXZlID0gR29vZ2xlRG9jc0RyaXZlU2VydmljZSgKICAgICAgICAgICAgZ19jcmVkc19wYXRoLAogICAgICAgICAgICBn"
    "X3Rva2VuX3BhdGgsCiAgICAgICAgICAgIGxvZ2dlcj1sYW1iZGEgbXNnLCBsZXZlbD0iSU5GTyI6IHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltHRFJJVkVdIHttc2d9IiwgbGV2ZWwpCiAgICAgICAgKQoKICAgICAgICAjIFNlZWQgTFNMIHJ1bGVzIG9uIGZpcnN0IHJ1"
    "bgogICAgICAgIHNlbGYuX2xlc3NvbnMuc2VlZF9sc2xfcnVsZXMoKQoKICAgICAgICAjIExvYWQgZW50aXR5IHN0YXRlCiAgICAg"
    "ICAgc2VsZi5fc3RhdGUgPSBzZWxmLl9tZW1vcnkubG9hZF9zdGF0ZSgpCiAgICAgICAgc2VsZi5fc3RhdGVbInNlc3Npb25fY291"
    "bnQiXSA9IHNlbGYuX3N0YXRlLmdldCgic2Vzc2lvbl9jb3VudCIsMCkgKyAxCiAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc3Rh"
    "cnR1cCJdICA9IGxvY2FsX25vd19pc28oKQogICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAg"
    "ICAgICAjIEJ1aWxkIGFkYXB0b3IKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpCgog"
    "ICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIChzZXQgdXAgYWZ0ZXIgd2lkZ2V0cyBidWlsdCkKICAgICAgICBzZWxmLl9mYWNl"
    "X3RpbWVyX21ncjogT3B0aW9uYWxbRmFjZVRpbWVyTWFuYWdlcl0gPSBOb25lCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIFVJIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoQVBQX05BTUUpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMjAwLCA3"
    "NTApCiAgICAgICAgc2VsZi5yZXNpemUoMTM1MCwgODUwKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKCiAgICAg"
    "ICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciB3aXJlZCB0byB3aWRnZXRzCiAgICAgICAg"
    "c2VsZi5fZmFjZV90aW1lcl9tZ3IgPSBGYWNlVGltZXJNYW5hZ2VyKAogICAgICAgICAgICBzZWxmLl9taXJyb3IsIHNlbGYuX2Vt"
    "b3Rpb25fYmxvY2sKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRpbWVycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0"
    "c190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9z"
    "dGF0cykKICAgICAgICBzZWxmLl9zdGF0c190aW1lci5zdGFydCgxMDAwKQoKICAgICAgICBzZWxmLl9ibGlua190aW1lciA9IFFU"
    "aW1lcigpCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2JsaW5rKQogICAgICAgIHNlbGYu"
    "X2JsaW5rX3RpbWVyLnN0YXJ0KDgwMCkKCiAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIgPSBRVGltZXIoKQogICAgICAg"
    "IGlmIEFJX1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl9mb290ZXJfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYu"
    "X3N0YXRlX3N0cmlwX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9mb290ZXJfc3RyaXAucmVmcmVzaCkKICAgICAgICAgICAg"
    "c2VsZi5fc3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyID0g"
    "UVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dv"
    "b2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIuc3RhcnQoc2VsZi5fZ2V0"
    "X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIg"
    "PSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnRpbWVvdXQuY29ubmVjdChz"
    "ZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVm"
    "cmVzaF90aW1lci5zdGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMoKSkKCiAgICAgICAgIyDilIDilIAg"
    "U2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVudGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAg"
    "IyBEbyBOT1QgY2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMgQm90"
    "aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRlcgogICAgICAgICMgd2luZG93LnNo"
    "b3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJT04g4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAg"
    "ICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAg"
    "ICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAg"
    "ICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAg"
    "ICAgIyDilIDilIAgQm9keTogSm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGJvZHkgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgYm9keS5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgSm91cm5hbCBzaWRlYmFyIChsZWZ0KQogICAg"
    "ICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAgICAgIHNlbGYuX2pv"
    "dXJuYWxfc2lkZWJhci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2xvYWRfam91cm5h"
    "bF9zZXNzaW9uKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5jb25uZWN0KAog"
    "ICAgICAgICAgICBzZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgYm9keS5hZGRXaWRnZXQoc2VsZi5fam91cm5h"
    "bF9zaWRlYmFyKQoKICAgICAgICAjIENoYXQgcGFuZWwgKGNlbnRlciwgZXhwYW5kcykKICAgICAgICBib2R5LmFkZExheW91dChz"
    "ZWxmLl9idWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAgICAgICMgU3lzdGVtcyAocmlnaHQpCiAgICAgICAgYm9keS5hZGRMYXlv"
    "dXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCkpCgogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJvZHksIDEpCgogICAgICAg"
    "ICMg4pSA4pSAIEZvb3RlciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYi4pymIHtBUFBf"
    "TkFNRX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldEFsaWdu"
    "bWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGZvb3RlcikKCiAgICBkZWYg"
    "X2J1aWxkX3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIGJhciA9IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRG"
    "aXhlZEhlaWdodCgzNikKICAgICAgICBiYXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9"
    "OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7Igog"
    "ICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChiYXIpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygxMCwgMCwgMTAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNikKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYg"
    "e0FQUF9OQU1FfSIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07"
    "IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBi"
    "b3JkZXI6IG5vbmU7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgcnVuZXMgPSBR"
    "TGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19"
    "OyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHJ1bmVzLnNldEFsaWdubWVudChRdC5B"
    "bGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbChmIuKXiSB7VUlfT0ZG"
    "TElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAg"
    "ICMgU3VzcGVuc2lvbiBwYW5lbAogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IE5vbmUKICAgICAgICBpZiBTVVNQRU5TSU9O"
    "X0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkKICAgICAgICAgICAgc2VsZi5f"
    "dG9ycG9yX3BhbmVsLnN0YXRlX2NoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKCiAgICAgICAg"
    "IyBJZGxlIHRvZ2dsZQogICAgICAgIGlkbGVfZW5hYmxlZCA9IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJpZGxl"
    "X2VuYWJsZWQiLCBGYWxzZSkpCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRvbigiSURMRSBPTiIgaWYgaWRsZV9l"
    "bmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBz"
    "ZWxmLl9pZGxlX2J0bi5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2VkKGlkbGVfZW5h"
    "YmxlZCkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3Jk"
    "ZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6"
    "IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fb25faWRsZV90"
    "b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAgICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGdWxs"
    "c2NyZWVuIikKICAgICAgICBzZWxmLl9ibF9idG4gPSBRUHVzaEJ1dHRvbigiQm9yZGVybGVzcyIpCiAgICAgICAgc2VsZi5fZXhw"
    "b3J0X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0biA9IFFQdXNoQnV0dG9uKCJT"
    "aHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9ydF9idG4p"
    "OgogICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBm"
    "ImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRGaXhl"
    "ZFdpZHRoKDQ2KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4uc2V0Rml4ZWRXaWR0aCg2OCkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQkxPT0R9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQkxPT0R9OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAwOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZnNfYnRuLnNldFRvb2xUaXAoIkZ1bGxzY3JlZW4gKEYxMSkiKQogICAgICAg"
    "IHNlbGYuX2JsX2J0bi5zZXRUb29sVGlwKCJCb3JkZXJsZXNzIChGMTApIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldFRv"
    "b2xUaXAoIkV4cG9ydCBjaGF0IHNlc3Npb24gdG8gVFhUIGZpbGUiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRUb29s"
    "VGlwKGYiR3JhY2VmdWwgc2h1dGRvd24g4oCUIHtERUNLX05BTUV9IHNwZWFrcyB0aGVpciBsYXN0IHdvcmRzIikKICAgICAgICBz"
    "ZWxmLl9mc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKQogICAgICAgIHNlbGYuX2JsX2J0bi5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZXhwb3J0X2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9p"
    "bml0aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGl0bGUpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChydW5lcywgMSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQogICAgICAgIGxheW91"
    "dC5hZGRTcGFjaW5nKDgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9jaGF0X3BhbmVs"
    "KHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0U3Bh"
    "Y2luZyg0KQoKICAgICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBzZWxm"
    "Ll9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWIge3sgYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXpl"
    "OiAxMHB4OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQkcyfTsgY29s"
    "b3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059OyB9fSIKICAg"
    "ICAgICApCgogICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJzb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IHNlYW5jZV9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6"
    "ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fY2hh"
    "dF9kaXNwbGF5KQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NIQVRfV0lO"
    "RE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNlbGZfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBz"
    "ZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVl"
    "KQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01P"
    "TklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFk"
    "ZFRhYihzZWxmLl9zZWxmX3RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fbWFp"
    "bl90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jlc291cmNlIGJsb2NrIHJvdyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICAjIE1hbmRhdG9yeSBwZXJtYW5lbnQgc3RydWN0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBNSVJST1IgfCBb"
    "TE9XRVItTUlERExFIFBFUk1BTkVOVCBGT09UUFJJTlRdCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "IGJsb2NrX3Jvdy5zZXRTcGFjaW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZlciBjb2xsYXBzZXMpCiAgICAgICAgbWlycm9y"
    "X3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVkJveExheW91dChtaXJyb3Jfd3JhcCkKICAgICAgICBtd19s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAg"
    "ICBtd19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyB7VUlfTUlSUk9SX0xBQkVMfSIpKQogICAgICAgIHNlbGYu"
    "X21pcnJvciA9IE1pcnJvcldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgxNjAsIDE2MCkKICAgICAg"
    "ICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pcnJvcl93cmFw"
    "LCAwKQoKICAgICAgICAjIE1pZGRsZSBsb3dlciBibG9jayBrZWVwcyBhIHBlcm1hbmVudCBmb290cHJpbnQ6CiAgICAgICAgIyBs"
    "ZWZ0ID0gY29tcGFjdCBzdGFjayBhcmVhLCByaWdodCA9IGZpeGVkIGV4cGFuZGVkLXJvdyBzbG90cy4KICAgICAgICBtaWRkbGVf"
    "d3JhcCA9IFFXaWRnZXQoKQogICAgICAgIG1pZGRsZV9sYXlvdXQgPSBRSEJveExheW91dChtaWRkbGVfd3JhcCkKICAgICAgICBt"
    "aWRkbGVfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1pZGRsZV9sYXlvdXQuc2V0U3BhY2lu"
    "ZygyKQoKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tf"
    "d3JhcC5zZXRNaW5pbXVtV2lkdGgoMTMwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWF4aW11bVdpZHRoKDEz"
    "MCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9sb3dlcl9zdGFja193cmFwKQog"
    "ICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxm"
    "Ll9sb3dlcl9zdGFja19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0VmlzaWJs"
    "ZShGYWxzZSkKICAgICAgICBtaWRkbGVfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9sb3dlcl9zdGFja193cmFwLCAwKQoKICAgICAg"
    "ICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3cgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5"
    "b3V0ID0gUUdyaWRMYXlvdXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93KQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jv"
    "d19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xh"
    "eW91dC5zZXRIb3Jpem9udGFsU3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0VmVy"
    "dGljYWxTcGFjaW5nKDIpCiAgICAgICAgbWlkZGxlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93LCAx"
    "KQoKICAgICAgICAjIEVtb3Rpb24gYmxvY2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90"
    "aW9uQmxvY2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAg"
    "IGYi4p2nIHtVSV9FTU9USU9OU19MQUJFTH0iLCBzZWxmLl9lbW90aW9uX2Jsb2NrLAogICAgICAgICAgICBleHBhbmRlZD1UcnVl"
    "LCBtaW5fd2lkdGg9MTMwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgTGVmdCByZXNvdXJjZSBvcmIg"
    "KGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9MRUZUX09S"
    "Ql9MQUJFTCwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAgICAgIHNlbGYuX2xlZnRfb3JiX3dyYXAgPSBD"
    "b2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfTEVGVF9PUkJfVElUTEV9Iiwgc2VsZi5fbGVmdF9vcmIsCiAg"
    "ICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIENlbnRlciBjeWNs"
    "ZSB3aWRnZXQgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldCA9IEN5Y2xlV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9jeWNsZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0NZQ0xFX1RJVExFfSIsIHNl"
    "bGYuX2N5Y2xlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgog"
    "ICAgICAgICMgUmlnaHQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9yaWdodF9vcmIgPSBTcGhlcmVX"
    "aWRnZXQoCiAgICAgICAgICAgIFVJX1JJR0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9SSUdIVF9P"
    "UkJfVElUTEV9Iiwgc2VsZi5fcmlnaHRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQog"
    "ICAgICAgICkKCiAgICAgICAgIyBFc3NlbmNlICgyIGdhdWdlcywgY29sbGFwc2libGUpCiAgICAgICAgZXNzZW5jZV93aWRnZXQg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBlc3NlbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KGVzc2VuY2Vfd2lkZ2V0KQogICAgICAgIGVz"
    "c2VuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldFNwYWNp"
    "bmcoNCkKICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2UgICA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0VfUFJJTUFS"
    "WSwgICAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UgPSBHYXVnZVdp"
    "ZGdldChVSV9FU1NFTkNFX1NFQ09OREFSWSwgIiUiLCAxMDAuMCwgQ19HUkVFTikKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9l"
    "c3NlbmNlX3NlY29uZGFyeV9nYXVnZSkKICAgICAgICBzZWxmLl9lc3NlbmNlX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAg"
    "ICAgICAgICBmIuKdpyB7VUlfRVNTRU5DRV9USVRMRX0iLCBlc3NlbmNlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTEx"
    "MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIEV4cGFuZGVkIHJvdyBzbG90cyBtdXN0IHN0YXkgaW4g"
    "Y2Fub25pY2FsIHZpc3VhbCBvcmRlci4KICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90X29yZGVyID0gWwogICAgICAg"
    "ICAgICAiZW1vdGlvbnMiLCAicHJpbWFyeSIsICJjeWNsZSIsICJzZWNvbmRhcnkiLCAiZXNzZW5jZSIKICAgICAgICBdCiAgICAg"
    "ICAgc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlciA9IFsKICAgICAgICAgICAgImN5Y2xlIiwgInByaW1hcnkiLCAic2Vj"
    "b25kYXJ5IiwgImVzc2VuY2UiLCAiZW1vdGlvbnMiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcyA9"
    "IHsKICAgICAgICAgICAgImVtb3Rpb25zIjogc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwLAogICAgICAgICAgICAicHJpbWFyeSI6"
    "IHNlbGYuX2xlZnRfb3JiX3dyYXAsCiAgICAgICAgICAgICJjeWNsZSI6IHNlbGYuX2N5Y2xlX3dyYXAsCiAgICAgICAgICAgICJz"
    "ZWNvbmRhcnkiOiBzZWxmLl9yaWdodF9vcmJfd3JhcCwKICAgICAgICAgICAgImVzc2VuY2UiOiBzZWxmLl9lc3NlbmNlX3dyYXAs"
    "CiAgICAgICAgfQoKICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHMgPSB7fQogICAgICAgIGZvciBjb2wsIGtleSBpbiBlbnVt"
    "ZXJhdGUoc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcik6CiAgICAgICAgICAgIHNsb3QgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICAgICAgc2xvdF9sYXlvdXQgPSBRVkJveExheW91dChzbG90KQogICAgICAgICAgICBzbG90X2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgICAgICBzZWxmLl9s"
    "b3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LmFkZFdpZGdldChzbG90LCAwLCBjb2wpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX2V4"
    "cGFuZGVkX3Jvd19sYXlvdXQuc2V0Q29sdW1uU3RyZXRjaChjb2wsIDEpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX3Jvd19zbG90"
    "c1trZXldID0gc2xvdF9sYXlvdXQKCiAgICAgICAgZm9yIHdyYXAgaW4gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzLnZhbHVlcygp"
    "OgogICAgICAgICAgICB3cmFwLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQpCgogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dCgpCgogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlkZGxl"
    "X3dyYXAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMgRm9vdGVyIHN0YXRlIHN0cmlw"
    "IChiZWxvdyBibG9jayByb3cg4oCUIHBlcm1hbmVudCBVSSBzdHJ1Y3R1cmUpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwID0g"
    "Rm9vdGVyU3RyaXBXaWRnZXQoKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcC5zZXRfbGFiZWwoVUlfRk9PVEVSX1NUUklQX0xB"
    "QkVMKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZm9vdGVyX3N0cmlwKQoKICAgICAgICAjIOKUgOKUgCBJbnB1dCBy"
    "b3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9zeW0gPSBRTGFiZWwoIuKcpiIpCiAg"
    "ICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXpl"
    "OiAxNnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRG"
    "aXhlZFdpZHRoKDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5faW5wdXRf"
    "ZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lOUFVUX1BMQUNFSE9MREVSKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnJl"
    "dHVyblByZXNzZWQuY29ubmVjdChzZWxmLl9zZW5kX21lc3NhZ2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxl"
    "ZChGYWxzZSkKCiAgICAgICAgc2VsZi5fc2VuZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "c2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5h"
    "ZGRXaWRnZXQocHJvbXB0X3N5bSkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQogICAgICAg"
    "IGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChpbnB1dF9yb3cpCgog"
    "ICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2NsZWFyX2xheW91dF93aWRnZXRzKHNlbGYsIGxheW91dDogUVZCb3hMYXlv"
    "dXQpIC0+IE5vbmU6CiAgICAgICAgd2hpbGUgbGF5b3V0LmNvdW50KCk6CiAgICAgICAgICAgIGl0ZW0gPSBsYXlvdXQudGFrZUF0"
    "KDApCiAgICAgICAgICAgIHdpZGdldCA9IGl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgd2lkZ2V0LnNldFBhcmVudChOb25lKQoKICAgIGRlZiBfcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0"
    "KHNlbGYsICpfYXJncykgLT4gTm9uZToKICAgICAgICBjb2xsYXBzZWRfY291bnQgPSAwCgogICAgICAgICMgUmVidWlsZCBleHBh"
    "bmRlZCByb3cgc2xvdHMgaW4gZml4ZWQgZXhwYW5kZWQgb3JkZXIuCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9sb3dlcl9leHBh"
    "bmRlZF9zbG90X29yZGVyOgogICAgICAgICAgICBzbG90X2xheW91dCA9IHNlbGYuX2xvd2VyX3Jvd19zbG90c1trZXldCiAgICAg"
    "ICAgICAgIHNlbGYuX2NsZWFyX2xheW91dF93aWRnZXRzKHNsb3RfbGF5b3V0KQogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93"
    "ZXJfbW9kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgd3JhcC5pc19leHBhbmRlZCgpOgogICAgICAgICAgICAgICAgc2xv"
    "dF9sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBjb2xsYXBzZWRfY291bnQg"
    "Kz0gMQogICAgICAgICAgICAgICAgc2xvdF9sYXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgICAgICAjIFJlYnVpbGQgY29tcGFjdCBz"
    "dGFjayBpbiBjYW5vbmljYWwgY29tcGFjdCBvcmRlci4KICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzZWxmLl9s"
    "b3dlcl9zdGFja19sYXlvdXQpCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9sb3dlcl9jb21wYWN0X3N0YWNrX29yZGVyOgogICAg"
    "ICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgbm90IHdyYXAuaXNfZXhw"
    "YW5kZWQoKToKICAgICAgICAgICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRXaWRnZXQod3JhcCkKCiAgICAgICAg"
    "c2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LmFkZFN0cmV0Y2goMSkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZp"
    "c2libGUoY29sbGFwc2VkX2NvdW50ID4gMCkKCiAgICBkZWYgX2J1aWxkX3NwZWxsYm9va19wYW5lbChzZWxmKSAtPiBRVkJveExh"
    "eW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAw"
    "LCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0"
    "KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5z"
    "ZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBv"
    "bGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIgPSBMb2NrQXdhcmVUYWJC"
    "YXIoc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCwgc2VsZi5fc3BlbGxfdGFicykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNl"
    "dFRhYkJhcihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0TW92YWJsZShUcnVlKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9t"
    "Q29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0"
    "KHNlbGYuX3Nob3dfc3BlbGxfdGFiX2NvbnRleHRfbWVudSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnRhYk1vdmVkLmNv"
    "bm5lY3Qoc2VsZi5fb25fc3BlbGxfdGFiX2RyYWdfbW92ZWQpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5jdXJyZW50Q2hhbmdl"
    "ZC5jb25uZWN0KGxhbWJkYSBfaWR4OiBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKSkKICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5fZm9jdXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzOgogICAgICAgICAgICBhcHAgPSBRQXBwbGljYXRpb24uaW5zdGFuY2UoKQog"
    "ICAgICAgICAgICBpZiBhcHAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBhcHAuZm9jdXNDaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fZ2xvYmFsX2ZvY3VzX2NoYW5nZWQpCiAgICAgICAgICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxsX3Rh"
    "YnMgPSBUcnVlCgogICAgICAgICMgQnVpbGQgRGlhZ25vc3RpY3NUYWIgZWFybHkgc28gc3RhcnR1cCBsb2dzIGFyZSBzYWZlIGV2"
    "ZW4gYmVmb3JlCiAgICAgICAgIyB0aGUgRGlhZ25vc3RpY3MgdGFiIGlzIGF0dGFjaGVkIHRvIHRoZSB3aWRnZXQuCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIgPSBEaWFnbm9zdGljc1RhYigpCgogICAgICAgICMg4pSA4pSAIEluc3RydW1lbnRzIHRhYiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9od19wYW5lbCA9"
    "IEhhcmR3YXJlUGFuZWwoKQoKICAgICAgICAjIOKUgOKUgCBSZWNvcmRzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIgPSBSZWNvcmRzVGFiKCkKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAg"
    "ICMg4pSA4pSAIFRhc2tzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2Zp"
    "bHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19l"
    "ZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90"
    "YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAg"
    "IG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2VsZi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJn"
    "ZV9jb21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZD1zZWxm"
    "Ll9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9y"
    "X2dvb2dsZV9maXJzdCwKICAgICAgICAgICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3Nw"
    "YWNlLAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDi"
    "lIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKCiAgICAgICAgIyDilIDi"
    "lIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2Vy"
    "IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNz"
    "b25zX3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4g"
    "YXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBp"
    "ZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSA"
    "IE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBEaWNlIFJvbGxlciB0"
    "YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5f"
    "ZGljZV9yb2xsZXJfdGFiID0gRGljZVJvbGxlclRhYihkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nKQoKICAg"
    "ICAgICAjIOKUgOKUgCBNYWdpYyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21hZ2ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxUYWIoCiAgICAgICAgICAgIG9uX3Ro"
    "cm93PXNlbGYuX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPXNlbGYuX2Rp"
    "YWdfdGFiLmxvZywKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFNldHRpbmdzIHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29u"
    "dHJvbHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nl"
    "dHRpbmdzX3RhYiA9IFNldHRpbmdzVGFiKHNlbGYpCgogICAgICAgICMgRGVzY3JpcHRvci1iYXNlZCBvcmRlcmluZyAoc3RhYmxl"
    "IGlkZW50aXR5ICsgdmlzdWFsIG9yZGVyIG9ubHkpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnMgPSBbCiAgICAgICAgICAg"
    "IHsiaWQiOiAiaW5zdHJ1bWVudHMiLCAidGl0bGUiOiAiSW5zdHJ1bWVudHMiLCAid2lkZ2V0Ijogc2VsZi5faHdfcGFuZWwsICJk"
    "ZWZhdWx0X29yZGVyIjogMH0sCiAgICAgICAgICAgIHsiaWQiOiAicmVjb3JkcyIsICJ0aXRsZSI6ICJSZWNvcmRzIiwgIndpZGdl"
    "dCI6IHNlbGYuX3JlY29yZHNfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDF9LAogICAgICAgICAgICB7ImlkIjogInRhc2tzIiwgInRp"
    "dGxlIjogIlRhc2tzIiwgIndpZGdldCI6IHNlbGYuX3Rhc2tzX3RhYiwgImRlZmF1bHRfb3JkZXIiOiAyfSwKICAgICAgICAgICAg"
    "eyJpZCI6ICJzbF9zY2FucyIsICJ0aXRsZSI6ICJTTCBTY2FucyIsICJ3aWRnZXQiOiBzZWxmLl9zbF9zY2FucywgImRlZmF1bHRf"
    "b3JkZXIiOiAzfSwKICAgICAgICAgICAgeyJpZCI6ICJzbF9jb21tYW5kcyIsICJ0aXRsZSI6ICJTTCBDb21tYW5kcyIsICJ3aWRn"
    "ZXQiOiBzZWxmLl9zbF9jb21tYW5kcywgImRlZmF1bHRfb3JkZXIiOiA0fSwKICAgICAgICAgICAgeyJpZCI6ICJqb2JfdHJhY2tl"
    "ciIsICJ0aXRsZSI6ICJKb2IgVHJhY2tlciIsICJ3aWRnZXQiOiBzZWxmLl9qb2JfdHJhY2tlciwgImRlZmF1bHRfb3JkZXIiOiA1"
    "fSwKICAgICAgICAgICAgeyJpZCI6ICJsZXNzb25zIiwgInRpdGxlIjogIkxlc3NvbnMiLCAid2lkZ2V0Ijogc2VsZi5fbGVzc29u"
    "c190YWIsICJkZWZhdWx0X29yZGVyIjogNn0sCiAgICAgICAgICAgIHsiaWQiOiAibW9kdWxlcyIsICJ0aXRsZSI6ICJNb2R1bGVz"
    "IiwgIndpZGdldCI6IHNlbGYuX21vZHVsZV90cmFja2VyLCAiZGVmYXVsdF9vcmRlciI6IDd9LAogICAgICAgICAgICB7ImlkIjog"
    "ImRpY2Vfcm9sbGVyIiwgInRpdGxlIjogIkRpY2UgUm9sbGVyIiwgIndpZGdldCI6IHNlbGYuX2RpY2Vfcm9sbGVyX3RhYiwgImRl"
    "ZmF1bHRfb3JkZXIiOiA4fSwKICAgICAgICAgICAgeyJpZCI6ICJtYWdpY184X2JhbGwiLCAidGl0bGUiOiAiTWFnaWMgOC1CYWxs"
    "IiwgIndpZGdldCI6IHNlbGYuX21hZ2ljXzhiYWxsX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA5fSwKICAgICAgICAgICAgeyJpZCI6"
    "ICJkaWFnbm9zdGljcyIsICJ0aXRsZSI6ICJEaWFnbm9zdGljcyIsICJ3aWRnZXQiOiBzZWxmLl9kaWFnX3RhYiwgImRlZmF1bHRf"
    "b3JkZXIiOiAxMH0sCiAgICAgICAgICAgIHsiaWQiOiAic2V0dGluZ3MiLCAidGl0bGUiOiAiU2V0dGluZ3MiLCAid2lkZ2V0Ijog"
    "c2VsZi5fc2V0dGluZ3NfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDExfSwKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG9hZF9zcGVs"
    "bF90YWJfc3RhdGVfZnJvbV9jb25maWcoKQogICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCgogICAgICAgIHJpZ2h0"
    "X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW91dChyaWdodF93"
    "b3Jrc3BhY2UpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAg"
    "ICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5fc3BlbGxfdGFicywgMSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKdpyBDQUxFTkRB"
    "UiIpCiAgICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZv"
    "bnQtc2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAg"
    "ICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVsKQoKICAgICAgICBzZWxm"
    "LmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6"
    "ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4aW11bQogICAgICAgICkK"
    "ICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dp"
    "ZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2RhdGUpCiAgICAgICAgcmlnaHRfd29y"
    "a3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl93aWRnZXQsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xh"
    "eW91dC5hZGRTdHJldGNoKDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNlLCAxKQogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2FsZW5kYXIgcmVzdG9yZWQgKHBlcnNp"
    "c3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHBlcnNpc3RlbnQgbWluaSBjYWxlbmRhciByZXN0b3JlZC9jb25maXJt"
    "ZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgcmV0"
    "dXJuIGxheW91dAoKICAgIGRlZiBfdGFiX2luZGV4X2J5X3NwZWxsX2lkKHNlbGYsIHRhYl9pZDogc3RyKSAtPiBpbnQ6CiAgICAg"
    "ICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpKToKICAgICAgICAgICAgaWYgc2VsZi5fc3BlbGxfdGFi"
    "cy50YWJCYXIoKS50YWJEYXRhKGkpID09IHRhYl9pZDoKICAgICAgICAgICAgICAgIHJldHVybiBpCiAgICAgICAgcmV0dXJuIC0x"
    "CgogICAgZGVmIF9pc19zcGVsbF90YWJfbG9ja2VkKHNlbGYsIHRhYl9pZDogT3B0aW9uYWxbc3RyXSkgLT4gYm9vbDoKICAgICAg"
    "ICBpZiBub3QgdGFiX2lkOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBzdGF0ZSA9IHNlbGYuX3NwZWxsX3RhYl9z"
    "dGF0ZS5nZXQodGFiX2lkLCB7fSkKICAgICAgICByZXR1cm4gYm9vbChzdGF0ZS5nZXQoImxvY2tlZCIsIEZhbHNlKSkKCiAgICBk"
    "ZWYgX2xvYWRfc3BlbGxfdGFiX3N0YXRlX2Zyb21fY29uZmlnKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2F2ZWQgPSBDRkcuZ2V0"
    "KCJtb2R1bGVfdGFiX29yZGVyIiwgW10pCiAgICAgICAgc2F2ZWRfbWFwID0ge30KICAgICAgICBpZiBpc2luc3RhbmNlKHNhdmVk"
    "LCBsaXN0KToKICAgICAgICAgICAgZm9yIGVudHJ5IGluIHNhdmVkOgogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShlbnRy"
    "eSwgZGljdCkgYW5kIGVudHJ5LmdldCgiaWQiKToKICAgICAgICAgICAgICAgICAgICBzYXZlZF9tYXBbc3RyKGVudHJ5WyJpZCJd"
    "KV0gPSBlbnRyeQoKICAgICAgICBzZWxmLl9zcGVsbF90YWJfc3RhdGUgPSB7fQogICAgICAgIGZvciB0YWIgaW4gc2VsZi5fc3Bl"
    "bGxfdGFiX2RlZnM6CiAgICAgICAgICAgIHRhYl9pZCA9IHRhYlsiaWQiXQogICAgICAgICAgICBkZWZhdWx0X29yZGVyID0gaW50"
    "KHRhYlsiZGVmYXVsdF9vcmRlciJdKQogICAgICAgICAgICBlbnRyeSA9IHNhdmVkX21hcC5nZXQodGFiX2lkLCB7fSkKICAgICAg"
    "ICAgICAgb3JkZXJfdmFsID0gZW50cnkuZ2V0KCJvcmRlciIsIGRlZmF1bHRfb3JkZXIpCiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIG9yZGVyX3ZhbCA9IGludChvcmRlcl92YWwpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgICAgICBvcmRlcl92YWwgPSBkZWZhdWx0X29yZGVyCiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRd"
    "ID0gewogICAgICAgICAgICAgICAgIm9yZGVyIjogb3JkZXJfdmFsLAogICAgICAgICAgICAgICAgImxvY2tlZCI6IGJvb2woZW50"
    "cnkuZ2V0KCJsb2NrZWQiLCBGYWxzZSkpLAogICAgICAgICAgICAgICAgImRlZmF1bHRfb3JkZXIiOiBkZWZhdWx0X29yZGVyLAog"
    "ICAgICAgICAgICB9CgogICAgZGVmIF9vcmRlcmVkX3NwZWxsX3RhYl9kZWZzKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAg"
    "cmV0dXJuIHNvcnRlZCgKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnMsCiAgICAgICAgICAgIGtleT1sYW1iZGEgdDog"
    "KAogICAgICAgICAgICAgICAgaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZS5nZXQodFsiaWQiXSwge30pLmdldCgib3JkZXIiLCB0"
    "WyJkZWZhdWx0X29yZGVyIl0pKSwKICAgICAgICAgICAgICAgIGludCh0WyJkZWZhdWx0X29yZGVyIl0pLAogICAgICAgICAgICAp"
    "LAogICAgICAgICkKCiAgICBkZWYgX3JlYnVpbGRfc3BlbGxfdGFicyhzZWxmKSAtPiBOb25lOgogICAgICAgIGN1cnJlbnRfaWQg"
    "PSBOb25lCiAgICAgICAgaWR4ID0gc2VsZi5fc3BlbGxfdGFicy5jdXJyZW50SW5kZXgoKQogICAgICAgIGlmIGlkeCA+PSAwOgog"
    "ICAgICAgICAgICBjdXJyZW50X2lkID0gc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS50YWJEYXRhKGlkeCkKCiAgICAgICAgc2Vs"
    "Zi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gVHJ1ZQogICAgICAgIHdoaWxlIHNlbGYuX3NwZWxsX3RhYnMuY291"
    "bnQoKToKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5yZW1vdmVUYWIoMCkKCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJf"
    "aW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgZm9yIHRhYiBpbiBzZWxmLl9vcmRl"
    "cmVkX3NwZWxsX3RhYl9kZWZzKCk6CiAgICAgICAgICAgIGkgPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYih0YWJbIndpZGdldCJd"
    "LCB0YWJbInRpdGxlIl0pCiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkuc2V0VGFiRGF0YShpLCB0YWJbImlk"
    "Il0pCiAgICAgICAgICAgIGlmIHRhYlsiaWQiXSA9PSAicmVjb3JkcyI6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzX3Rh"
    "Yl9pbmRleCA9IGkKICAgICAgICAgICAgZWxpZiB0YWJbImlkIl0gPT0gInRhc2tzIjoKICAgICAgICAgICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYl9pbmRleCA9IGkKCiAgICAgICAgaWYgY3VycmVudF9pZDoKICAgICAgICAgICAgbmV3X2lkeCA9IHNlbGYuX3RhYl9p"
    "bmRleF9ieV9zcGVsbF9pZChjdXJyZW50X2lkKQogICAgICAgICAgICBpZiBuZXdfaWR4ID49IDA6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9zcGVsbF90YWJzLnNldEN1cnJlbnRJbmRleChuZXdfaWR4KQoKICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJf"
    "bW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9wZXJz"
    "aXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9z"
    "cGVsbF90YWJzLmNvdW50KCkpOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRhdGEo"
    "aSkKICAgICAgICAgICAgaWYgdGFiX2lkIGluIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZToKICAgICAgICAgICAgICAgIHNlbGYuX3Nw"
    "ZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJvcmRlciJdID0gaQoKICAgICAgICBDRkdbIm1vZHVsZV90YWJfb3JkZXIiXSA9IFsKICAg"
    "ICAgICAgICAgeyJpZCI6IHRhYlsiaWQiXSwgIm9yZGVyIjogaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJbImlkIl1dWyJv"
    "cmRlciJdKSwgImxvY2tlZCI6IGJvb2woc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bImxvY2tlZCJdKX0KICAgICAg"
    "ICAgICAgZm9yIHRhYiBpbiBzb3J0ZWQoc2VsZi5fc3BlbGxfdGFiX2RlZnMsIGtleT1sYW1iZGEgdDogdFsiZGVmYXVsdF9vcmRl"
    "ciJdKQogICAgICAgIF0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3Jhbmdl"
    "KHNlbGYsIGZyb21faWR4OiBpbnQsIHRvX2lkeDogaW50KSAtPiBib29sOgogICAgICAgIGlmIGZyb21faWR4IDwgMCBvciB0b19p"
    "ZHggPCAwOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBtb3ZpbmdfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJh"
    "cigpLnRhYkRhdGEodG9faWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQobW92aW5nX2lkKToKICAgICAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgbGVmdCA9IG1pbihmcm9tX2lkeCwgdG9faWR4KQogICAgICAgIHJpZ2h0ID0gbWF4"
    "KGZyb21faWR4LCB0b19pZHgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UobGVmdCwgcmlnaHQgKyAxKToKICAgICAgICAgICAgaWYg"
    "aSA9PSB0b19pZHg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBvdGhlcl9pZCA9IHNlbGYuX3NwZWxsX3Rh"
    "YnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKG90aGVyX2lkKToK"
    "ICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHJldHVybiBUcnVlCgogICAgZGVmIF9vbl9zcGVsbF90YWJfZHJh"
    "Z19tb3ZlZChzZWxmLCBmcm9tX2lkeDogaW50LCB0b19pZHg6IGludCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9zdXBwcmVz"
    "c19zcGVsbF90YWJfbW92ZV9zaWduYWw6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBzZWxmLl9jYW5fY3Jvc3Nf"
    "c3BlbGxfdGFiX3JhbmdlKGZyb21faWR4LCB0b19pZHgpOgogICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92"
    "ZV9zaWduYWwgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYih0b19pZHgsIGZyb21faWR4KQog"
    "ICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc3Bl"
    "bGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgIGRlZiBfc2hvd19zcGVsbF90YWJfY29udGV4dF9tZW51KHNlbGYsIHBvczogUVBv"
    "aW50KSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiQXQocG9zKQogICAgICAgIGlmIGlkeCA8"
    "IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YShpZHgpCiAg"
    "ICAgICAgaWYgbm90IHRhYl9pZDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAg"
    "IG1vdmVfYWN0aW9uID0gbWVudS5hZGRBY3Rpb24oIk1vdmUiKQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQo"
    "dGFiX2lkKToKICAgICAgICAgICAgbG9ja19hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiVW5sb2NrIikKICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICBsb2NrX2FjdGlvbiA9IG1lbnUuYWRkQWN0aW9uKCJTZWN1cmUiKQogICAgICAgIG1lbnUuYWRkU2VwYXJhdG9y"
    "KCkKICAgICAgICByZXNldF9hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiUmVzZXQgdG8gRGVmYXVsdCBPcmRlciIpCgogICAgICAg"
    "IGNob2ljZSA9IG1lbnUuZXhlYyhzZWxmLl9zcGVsbF90YWJfYmFyLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgaWYgY2hvaWNl"
    "ID09IG1vdmVfYWN0aW9uOgogICAgICAgICAgICBpZiBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZW50ZXJfc3BlbGxfdGFiX21vdmVfbW9kZSh0YWJfaWQpCiAgICAgICAgZWxpZiBjaG9pY2UgPT0g"
    "bG9ja19hY3Rpb246CiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJsb2NrZWQiXSA9IG5vdCBzZWxm"
    "Ll9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9pZCkKICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF9zcGVsbF90YWJfb3JkZXJfdG9f"
    "Y29uZmlnKCkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCiAgICAgICAgZWxpZiBj"
    "aG9pY2UgPT0gcmVzZXRfYWN0aW9uOgogICAgICAgICAgICBmb3IgdGFiIGluIHNlbGYuX3NwZWxsX3RhYl9kZWZzOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bIm9yZGVyIl0gPSBpbnQodGFiWyJkZWZhdWx0X29yZGVy"
    "Il0pCiAgICAgICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCiAgICAgICAgICAgIHNlbGYuX3BlcnNpc3Rfc3BlbGxf"
    "dGFiX29yZGVyX3RvX2NvbmZpZygpCgogICAgZGVmIF9lbnRlcl9zcGVsbF90YWJfbW92ZV9tb2RlKHNlbGYsIHRhYl9pZDogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSB0YWJfaWQKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkKCiAgICBkZWYgX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSBOb25lCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVs"
    "bF90YWJfbW92ZV9jb250cm9scygpCgogICAgZGVmIF9vbl9nbG9iYWxfZm9jdXNfY2hhbmdlZChzZWxmLCBfb2xkLCBub3cpIC0+"
    "IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIGlmIG5vdyBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICBpZiBub3cgaXMgc2VsZi5fc3BlbGxfdGFiX2JhcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "aWYgaXNpbnN0YW5jZShub3csIFFUb29sQnV0dG9uKSBhbmQgbm93LnBhcmVudCgpIGlzIHNlbGYuX3NwZWxsX3RhYl9iYXI6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9yZWZyZXNo"
    "X3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxf"
    "dGFicy5jb3VudCgpKToKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci5CdXR0"
    "b25Qb3NpdGlvbi5MZWZ0U2lkZSwgTm9uZSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwg"
    "UVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIE5vbmUpCgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9t"
    "b3ZlX21vZGVfaWQKICAgICAgICBpZiBub3QgdGFiX2lkIG9yIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToKICAg"
    "ICAgICAgICAgcmV0dXJuCgogICAgICAgIGlkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAg"
    "aWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGxlZnRfYnRuID0gUVRvb2xCdXR0b24oc2VsZi5fc3BlbGxf"
    "dGFiX2JhcikKICAgICAgICBsZWZ0X2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBsZWZ0X2J0bi5zZXRBdXRvUmFpc2UoVHJ1ZSkK"
    "ICAgICAgICBsZWZ0X2J0bi5zZXRGaXhlZFNpemUoMTQsIDE0KQogICAgICAgIGxlZnRfYnRuLnNldEVuYWJsZWQoaWR4ID4gMCBh"
    "bmQgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlkeCAtIDEpKSkKICAg"
    "ICAgICBsZWZ0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9tb3ZlX3NwZWxsX3RhYl9zdGVwKHRhYl9pZCwgLTEp"
    "KQoKICAgICAgICByaWdodF9idG4gPSBRVG9vbEJ1dHRvbihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIHJpZ2h0X2J0bi5z"
    "ZXRUZXh0KCI+IikKICAgICAgICByaWdodF9idG4uc2V0QXV0b1JhaXNlKFRydWUpCiAgICAgICAgcmlnaHRfYnRuLnNldEZpeGVk"
    "U2l6ZSgxNCwgMTQpCiAgICAgICAgcmlnaHRfYnRuLnNldEVuYWJsZWQoCiAgICAgICAgICAgIGlkeCA8IChzZWxmLl9zcGVsbF90"
    "YWJzLmNvdW50KCkgLSAxKSBhbmQKICAgICAgICAgICAgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxf"
    "dGFiX2Jhci50YWJEYXRhKGlkeCArIDEpKQogICAgICAgICkKICAgICAgICByaWdodF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJk"
    "YTogc2VsZi5fbW92ZV9zcGVsbF90YWJfc3RlcCh0YWJfaWQsIDEpKQoKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldFRh"
    "YkJ1dHRvbihpZHgsIFFUYWJCYXIuQnV0dG9uUG9zaXRpb24uTGVmdFNpZGUsIGxlZnRfYnRuKQogICAgICAgIHNlbGYuX3NwZWxs"
    "X3RhYl9iYXIuc2V0VGFiQnV0dG9uKGlkeCwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIHJpZ2h0X2J0bikKCiAg"
    "ICBkZWYgX21vdmVfc3BlbGxfdGFiX3N0ZXAoc2VsZiwgdGFiX2lkOiBzdHIsIGRlbHRhOiBpbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjdXJyZW50X2lk"
    "eCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAgaWYgY3VycmVudF9pZHggPCAwOgogICAgICAg"
    "ICAgICByZXR1cm4KCiAgICAgICAgdGFyZ2V0X2lkeCA9IGN1cnJlbnRfaWR4ICsgZGVsdGEKICAgICAgICBpZiB0YXJnZXRfaWR4"
    "IDwgMCBvciB0YXJnZXRfaWR4ID49IHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IHRhcmdldF9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YSh0YXJnZXRfaWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3Nw"
    "ZWxsX3RhYl9sb2NrZWQodGFyZ2V0X2lkKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxs"
    "X3RhYl9tb3ZlX3NpZ25hbCA9IFRydWUKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLm1vdmVUYWIoY3VycmVudF9pZHgsIHRh"
    "cmdldF9pZHgpCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVf"
    "Y29udHJvbHMoKQoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3N0YXJ0dXBf"
    "c2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge0FQUF9OQU1F"
    "fSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7UlVORVN9IOKcpiIpCgog"
    "ICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJvb3Rz"
    "dHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAjIGNvbnN1bWVk"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0"
    "ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2V0X2RpYWdub3N0"
    "aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5jeUNoZWNrZXIu"
    "Y2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQgcGFzdCBzdGF0"
    "ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iLCIiKQogICAg"
    "ICAgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NUQVJU"
    "VVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICMgQmVn"
    "aW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBVSV9BV0FLRU5JTkdf"
    "TElORSkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1tb25pbmcge0RFQ0tfTkFN"
    "RX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgogICAgICAgIHNlbGYuX2xvYWRl"
    "ciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgc2VsZi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgK"
    "ICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICBzZWxmLl9sb2FkZXIu"
    "ZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIsIGUpKQogICAgICAg"
    "IHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICBzZWxmLl9s"
    "b2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVh"
    "ZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fbG9hZF9jb21w"
    "bGV0ZShzZWxmLCBzdWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAgIHNlbGYuX21v"
    "ZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAg"
    "ICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1cmUgVlJBTSBiYXNlbGluZSBh"
    "ZnRlciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92cmFtX2Jhc2VsaW5lKQog"
    "ICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICAgICAjIFZh"
    "bXBpcmUgc3RhdGUgZ3JlZXRpbmcKICAgICAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgICAgICBzdGF0"
    "ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX3N0YXRlX2dyZWV0aW5nc19t"
    "YXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAgICAgICAgIlNZU1RFTSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4iKQogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyBzaHV0ZG93biByZWNvcmRlZCwgaW5qZWN0IGNvbnRleHQKICAg"
    "ICAgICAgICAgIyBzbyBNb3JnYW5uYSBjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgc2hlIHNsZXB0CiAgICAg"
    "ICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQogICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJwYW5pY2tl"
    "ZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgICAgICIiIkZvcm1h"
    "dCBlbGFwc2VkIHNlY29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYgc2Vjb25kcyA8IDYwOgog"
    "ICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3MnIGlmIHNlY29uZHMgIT0gMSBlbHNlICcnfSIKICAg"
    "ICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0gaW50KHNlY29uZHMgLy8gNjApCiAgICAgICAgICAgIHMg"
    "PSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7bX0gbWludXRleydzJyBpZiBtICE9IDEgZWxzZSAnJ30i"
    "ICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMgPCA4NjQwMDoKICAgICAgICAgICAgaCA9IGlu"
    "dChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2MCkKICAgICAgICAgICAg"
    "cmV0dXJuIGYie2h9IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBlbHNlICIiKQogICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQoc2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9IGludCgoc2Vjb25kcyAl"
    "IDg2NDAwKSAvLyAzNjAwKQogICAgICAgICAgICByZXR1cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEgZWxzZSAnJ30iICsgKGYi"
    "IHtofWgiIGlmIGggZWxzZSAiIikKCiAgICBkZWYgX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdyhzZWxmLCBhbnN3ZXI6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICAiIiJUcmlnZ2VyIGhpZGRlbiBpbnRlcm5hbCBBSSBmb2xsb3ctdXAgYWZ0ZXIgYSBNYWdpYyA4LUJh"
    "bGwgdGhyb3cuIiIiCiAgICAgICAgaWYgbm90IGFuc3dlcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHNlbGYu"
    "X21vZGVsX2xvYWRlZCBvciBzZWxmLl90b3Jwb3Jfc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgICAgICAiWzhCQUxMXVtXQVJOXSBUaHJvdyByZWNlaXZlZCB3aGlsZSBtb2RlbCB1bmF2YWlsYWJs"
    "ZTsgaW50ZXJwcmV0YXRpb24gc2tpcHBlZC4iLAogICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHJldHVybgoKICAgICAgICBwcm9tcHQgPSAoCiAgICAgICAgICAgICJJbnRlcm5hbCBldmVudDogdGhlIHVzZXIgaGFzIHRo"
    "cm93biB0aGUgTWFnaWMgOC1CYWxsLlxuIgogICAgICAgICAgICBmIk1hZ2ljIDgtQmFsbCByZXN1bHQ6IHthbnN3ZXJ9XG4iCiAg"
    "ICAgICAgICAgICJSZXNwb25kIHRvIHRoZSB1c2VyIHdpdGggYSBzaG9ydCBteXN0aWNhbCBpbnRlcnByZXRhdGlvbiBpbiB5b3Vy"
    "ICIKICAgICAgICAgICAgImN1cnJlbnQgcGVyc29uYSB2b2ljZS4gS2VlcCB0aGUgaW50ZXJwcmV0YXRpb24gY29uY2lzZSBhbmQg"
    "ZXZvY2F0aXZlLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiWzhCQUxMXSBEaXNwYXRjaGluZyBoaWRk"
    "ZW4gaW50ZXJwcmV0YXRpb24gcHJvbXB0IGZvciByZXN1bHQ6IHthbnN3ZXJ9IiwgIklORk8iKQoKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsi"
    "cm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBwcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MTgwCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbWFnaWM4X3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJz"
    "dF90b2tlbiA9IFRydWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAg"
    "ICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29y"
    "a2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "WzhCQUxMXVtFUlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdl"
    "ZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxl"
    "dGVMYXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdW0VSUk9SXSBIaWRkZW4gcHJvbXB0IGZhaWxlZDoge2V4fSIsICJFUlJP"
    "UiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGhpZGRlbiB3YWtl"
    "LXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9hZHMuIiIiCiAgICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRl"
    "LmdldCgibGFzdF9zaHV0ZG93biIpCiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVybiAgIyBG"
    "aXJzdCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMgQ2FsY3VsYXRlIGVsYXBzZWQg"
    "dGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBkYXRldGltZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1"
    "dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgICAgICMgTWFrZSBib3RoIG5haXZlIGZv"
    "ciBjb21wYXJpc29uCiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAg"
    "IHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxhY2UodHppbmZvPU5vbmUpCiAgICAgICAgICAgIGVs"
    "YXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3duX2R0KS50b3RhbF9zZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIg"
    "PSBzZWxmLl9mb3JtYXRfZWxhcHNlZChlbGFwc2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBl"
    "bGFwc2VkX3N0ciA9ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBzdG9yZWQgZmFyZXdlbGwgYW5kIGxhc3Qg"
    "Y29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9mYXJld2VsbCIsICIiKQogICAgICAg"
    "IGxhc3RfY29udGV4dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAgICMgQnVp"
    "bGQgd2FrZS11cCBwcm9tcHQKICAgICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAgICBpZiBsYXN0X2NvbnRleHQ6CiAgICAg"
    "ICAgICAgIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBmaW5hbCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW9uOlxuIgogICAg"
    "ICAgICAgICBmb3IgaXRlbSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBzcGVha2VyID0gaXRlbS5nZXQoInJvbGUi"
    "LCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQgICAgPSBpdGVtLmdldCgiY29udGVudCIsICIiKVs6MjAw"
    "XQogICAgICAgICAgICAgICAgY29udGV4dF9ibG9jayArPSBmIntzcGVha2VyfToge3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxs"
    "X2Jsb2NrID0gIiIKICAgICAgICBpZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSBmIlxuXG5Zb3VyIGZp"
    "bmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3ZWxsfVwiIgoKICAgICAgICB3YWtldXBfcHJvbXB0"
    "ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1c3QgYmVlbiByZWFjdGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRv"
    "cm1hbmN5LiIKICAgICAgICAgICAgZiJ7ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKICAg"
    "ICAgICAgICAgZiJcbkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHlvdSBoYXZlIGJlZW4gYWJz"
    "ZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2FpZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFj"
    "dGVyZnVsLiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmpl"
    "Y3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3Rvcnku"
    "YXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YWtldXBfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3Ry"
    "ZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBt"
    "YXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3dha2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAg"
    "ICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYu"
    "X29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUp"
    "CiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29y"
    "a2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNv"
    "bm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBX"
    "YWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAg"
    "ICApCgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgRm9yY2Ug"
    "R29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIElmIHRv"
    "a2VuIGlzIG1pc3NpbmcvaW52YWxpZCwgdGhlIGJyb3dzZXIgT0F1dGggZmxvdyBvcGVucyBuYXR1cmFsbHkuCiAgICAgICAgIiIi"
    "CiAgICAgICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBk"
    "ZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBpZiBHT09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1b"
    "U1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBpZiBub3Qgc2VsZi5fZ2NhbCBvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBz"
    "a2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICAgICAgICAgICJXQVJO"
    "IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltHT09HTEVdW1NUQVJUVVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2suIiwgIklORk8iKQogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIGNyZWRlbnRpYWxzPXtz"
    "ZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYuX2dj"
    "YWwudG9rZW5fcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHNlbGYuX2dj"
    "YWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIENhbGVu"
    "ZGFyIGF1dGggcmVhZHkuIiwgIk9LIikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5lbnN1cmVfc2VydmljZXMoKQogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIERyaXZlL0RvY3MgYXV0aCByZWFkeS4iLCAiT0siKQog"
    "ICAgICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRydWUKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygi"
    "W0dPT0dMRV1bU1RBUlRVUF0gU2NoZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRlciBhdXRoLiIsICJJTkZPIikK"
    "ICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9jcykKCiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gUG9zdC1hdXRoIHRhc2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwg"
    "IklORk8iKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGluYm91bmQgc3luYyB0cmlnZ2VyZWQgYWZ0"
    "ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJf"
    "aW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAg"
    "ICAgZiJbR09PR0xFXVtTVEFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1wb3J0ZWRfY291"
    "bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4"
    "OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIp"
    "CgoKICAgIGRlZiBfcmVmcmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJl"
    "bnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoIkxvYWRp"
    "bmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnBhdGhfbGFiZWwuc2V0VGV4dCgi"
    "UGF0aDogTXkgRHJpdmUiKQogICAgICAgIGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1z"
    "ZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGUg"
    "PSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIu"
    "c2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3Rp"
    "Y2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwg"
    "c2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVd"
    "W1RJTUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCBwb2xsLiIsICJJTkZPIikK"
    "ICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwgY29tcGxldGUg4oCU"
    "IHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxl"
    "ZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1vbj1UcnVlKS5z"
    "dGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1b"
    "VElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJlZnJl"
    "c2ggdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5n"
    "IGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERy"
    "aXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4Ogog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZ"
    "TkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQogICAgICAg"
    "IF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNr"
    "c19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkK"
    "ICAgICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsi"
    "OgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2Zp"
    "bHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNl"
    "bGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmls"
    "dGVyfSBzaG93X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAg"
    "ICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtu"
    "b3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJb"
    "VEFTS1NdW0ZJTFRFUl0gaG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQoK"
    "ICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSA9IDAKICAgICAgICBm"
    "b3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxv"
    "d2VyKCkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRl"
    "ZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQo"
    "ImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVl"
    "X3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMg"
    "Tm9uZToKICAgICAgICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIGRh"
    "dGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGR1ZV9k"
    "dCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06"
    "CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmlsdGVyZWQuc29ydChrZXk9X3Rhc2tfZHVl"
    "X3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBi"
    "ZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFs"
    "aWRfZHVlfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgogICAgZGVmIF9n"
    "b29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAgICAgICBzdGFydCA9IChldmVudCBvciB7fSku"
    "Z2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0ZV90aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0"
    "ZV90aW1lOgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJnb29n"
    "bGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAg"
    "ICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAgICBpZiBkYXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNl"
    "ZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2Rh"
    "dGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgcmV0dXJuIE5v"
    "bmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIo"
    "c2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAgICAgICAgICAgdmlzaWJsZV9jb3VudCA9IGxlbihzZWxmLl9maWx0ZXJl"
    "ZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0g"
    "cmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4"
    "fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hf"
    "d29ya2VyKHJlYXNvbj0icmVnaXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IHN0b3BfZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1Nd"
    "W1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtlciBjbGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAg"
    "ICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2Vs"
    "ZiwgZmlsdGVyX2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBzdHIoZmlsdGVyX2tl"
    "eSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRh"
    "dGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkCiAgICAg"
    "ICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNl"
    "bGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0"
    "W3N0cl06CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJl"
    "dHVybiBbXQogICAgICAgIHJldHVybiBzZWxmLl90YXNrc190YWIuc2VsZWN0ZWRfdGFza19pZHMoKQoKICAgIGRlZiBfc2V0X3Rh"
    "c2tfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGlmIHN0"
    "YXR1cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNvbXBsZXRlKHRhc2tfaWQpCiAg"
    "ICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jYW5jZWwo"
    "dGFza19pZCkKICAgICAgICBlbHNlOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MudXBkYXRlX3N0YXR1cyh0YXNr"
    "X2lkLCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBnb29n"
    "bGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29v"
    "Z2xlX2V2ZW50X2lkOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0ZV9ldmVudF9mb3Jf"
    "dGFzayhnb29nbGVfZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW1dBUk5dIEdvb2dsZSBldmVudCBjbGVhbnVw"
    "IGZhaWxlZCBmb3IgdGFza19pZD17dGFza19pZH06IHtleH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAg"
    "ICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgIGRv"
    "bmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExFVEUgU0VMRUNURUQgYXBwbGllZCB0byB7"
    "ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBk"
    "ZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19p"
    "ZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19p"
    "ZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RB"
    "U0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVm"
    "cmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJlbW92ZWQgPSBzZWxmLl90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltUQVNLU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6"
    "IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9u"
    "ZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc3RhdHVzKHRleHQsIG9rPW9rKQoKICAgIGRl"
    "ZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFz"
    "a3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93"
    "KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEobWludXRlcz0zMCkKICAgICAgICBzZWxmLl90YXNr"
    "c190YWIudGFza19lZGl0b3JfbmFtZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFy"
    "dF9kYXRlLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNr"
    "X2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tz"
    "X3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBz"
    "ZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikpCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4dCgiIikKICAgICAgICBzZWxmLl90YXNr"
    "c190YWIudGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jf"
    "cmVjdXJyZW5jZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNldENoZWNr"
    "ZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhl"
    "biBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkKICAgICAgICBzZWxmLl90YXNrc190YWIub3Blbl9lZGl0b3Io"
    "KQoKICAgIGRlZiBfY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihz"
    "ZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuY2xvc2VfZWRp"
    "dG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9j"
    "bG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4"
    "dDogc3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxsX2RheTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2UpOgogICAgICAgIGRhdGVf"
    "dGV4dCA9IChkYXRlX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0aW1lX3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5zdHJp"
    "cCgpCiAgICAgICAgaWYgbm90IGRhdGVfdGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBhbGxfZGF5Ogog"
    "ICAgICAgICAgICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBtaW51dGUgPSA1OSBpZiBpc19lbmQgZWxz"
    "ZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge2hvdXI6MDJkfTp7bWludXRl"
    "OjAyZH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0"
    "aW1lKGYie2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIG5vcm1hbGl6ZWQgPSBub3Jt"
    "YWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0PSJ0YXNrX2VkaXRvcl9wYXJzZV9kdCIpCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtp"
    "c19lbmR9LCBhbGxfZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fScg"
    "LT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25lJ30iLAogICAgICAgICAgICAiSU5GTyIs"
    "CiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJz"
    "dChzZWxmKSAtPiBOb25lOgogICAgICAgIHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAgIGlm"
    "IHRhYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50YXNrX2VkaXRvcl9uYW1lLnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2VkaXRvcl9hbGxfZGF5LmlzQ2hlY2tlZCgpCiAgICAgICAgc3Rh"
    "cnRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRh"
    "Yi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUgPSB0YWIudGFza19lZGl0b3Jf"
    "ZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfdGltZS50ZXh0KCku"
    "c3RyaXAoKQogICAgICAgIG5vdGVzID0gdGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAg"
    "IGxvY2F0aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQoKS5zdHJpcCgpCiAgICAgICAgcmVjdXJyZW5jZSA9IHRh"
    "Yi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgogICAgICAgIGlmIG5vdCB0aXRsZToKICAgICAgICAgICAg"
    "c2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiVGFzayBOYW1lIGlzIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBub3QgZW5kX2RhdGUgb3IgKG5vdCBhbGxfZGF5IGFuZCAobm90"
    "IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1lKSk6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0"
    "YXJ0L0VuZCBkYXRlIGFuZCB0aW1lIGFyZSByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShzdGFydF9kYXRlLCBzdGFydF90"
    "aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGlt"
    "ZShlbmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXksIGlzX2VuZD1UcnVlKQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQgb3Ig"
    "bm90IGVuZF9kdDoKICAgICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZhaWxlZCIpCiAgICAg"
    "ICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygi"
    "RW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQgZGF0ZXRpbWUuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJbnZh"
    "bGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBISDpNTS4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0"
    "dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBwYXls"
    "b2FkID0geyJzdW1tYXJ5IjogdGl0bGV9CiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9"
    "IHsiZGF0ZSI6IHN0YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGUi"
    "OiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0YShkYXlzPTEpKS5pc29mb3JtYXQoKX0KICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0"
    "ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9u"
    "ZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbImRlc2NyaXB0aW9uIl0gPSBub3Rlcwog"
    "ICAgICAgIGlmIGxvY2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJdID0gbG9jYXRpb24KICAgICAgICBpZiBy"
    "ZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1cnJlbmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgi"
    "UlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJlbmNlfSIKICAgICAgICAgICAgcGF5bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1"
    "bGVdCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdGFydCBmb3IgdGl0"
    "bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV2ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5j"
    "cmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBheWxvYWQsIGNhbGVuZGFyX2lkPSJwcmltYXJ5IikKICAgICAgICAgICAgdGFza3Mg"
    "PSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiBmInRhc2tf"
    "e3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAg"
    "ICAgICAgICAgICAgICAiZHVlX2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAg"
    "ICAgICAicHJlX3RyaWdnZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICJwZW5kaW5n"
    "IiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgInJldHJ5X2NvdW50Ijog"
    "MCwKICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9h"
    "dCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAogICAgICAgICAgICAgICAgInNvdXJjZSI6"
    "ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAic3luY2VkIiwKICAgICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAg"
    "ICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFza19lZGl0b3JfZ29vZ2xl"
    "X2ZpcnN0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3RlcywKICAgICAgICAgICAgICAgICAgICAic3RhcnRfYXQi"
    "OiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiZW5kX2F0IjogZW5k"
    "X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5IjogYm9vbChhbGxf"
    "ZGF5KSwKICAgICAgICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwKICAgICAgICAgICAgICAgICAgICAicmVjdXJy"
    "ZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICB9CiAgICAgICAgICAgIHRhc2tzLmFwcGVu"
    "ZCh0YXNrKQogICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tf"
    "ZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3VjY2VlZGVkIGFuZCB0YXNrIHJlZ2lzdHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkK"
    "ICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3VjY2VzcyBmb3IgdGl0bGU9J3t0aXRs"
    "ZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICAgICAiT0siLAogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAg"
    "ICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZhbHNlKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXVtFUlJPUl0gR29v"
    "Z2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0nOiB7ZXh9IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9j"
    "YWxlbmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF0ZS50b1N0cmlu"
    "ZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJub25lIgoKICAgICAgICBmb2N1c193aWRnZXQgPSBRQXBw"
    "bGljYXRpb24uZm9jdXNXaWRnZXQoKQogICAgICAgIGRpcmVjdF90YXJnZXRzID0gWwogICAgICAgICAgICAoInRhc2tfZWRpdG9y"
    "X3N0YXJ0X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX3N0YXJ0"
    "X2RhdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5kX2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwg"
    "Il90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgTm9uZSkpLAogICAgICAgIF0KICAgICAgICBmb3Ig"
    "bmFtZSwgd2lkZ2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAgICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5vbmUgYW5kIGZvY3Vz"
    "X3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAgICAgICAgICB3aWRnZXQuc2V0VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgICAg"
    "ICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgcm91dGVkX3RhcmdldCA9PSAi"
    "bm9uZSI6CiAgICAgICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIpIGFuZCBzZWxmLl9pbnB1dF9maWVsZCBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdldCBpcyBzZWxmLl9pbnB1dF9maWVsZDoKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5pbnNlcnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90"
    "YXJnZXQgPSAiaW5wdXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0"
    "X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIpIGFuZCBzZWxmLl90YXNrc190YWIgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkNhbGVuZGFyIGRhdGUg"
    "c2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2RpYWdfdGFiIikgYW5kIHNlbGYuX2Rp"
    "YWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxF"
    "TkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0u"
    "IiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJv"
    "dW5kX3N5bmMoc2VsZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNlKToKICAgICAgICAiIiIKICAgICAgICBTeW5jIEdvb2dsZSBD"
    "YWxlbmRhciBldmVudHMg4oaSIGxvY2FsIHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBBUEkuCgogICAgICAgIFN0YWdl"
    "IDEgKGZpcnN0IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3luY1Rva2VuLgogICAgICAgIFN0YWdlIDIg"
    "KGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVzaW5nIHN0b3JlZCBzeW5jVG9rZW4g4oCUCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJucyBPTkxZIHdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0cy9jYW5jZWxz"
    "KS4KICAgICAgICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZhbGxzIGJhY2sgdG8gZnVsbCBz"
    "eW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFuZCBub3QgYm9vbChDRkcuZ2V0KCJzZXR0aW5ncyIs"
    "IHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJsZWQiLCBUcnVlKSk6CiAgICAgICAgICAgIHJldHVybiAwCgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgbm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRf"
    "YWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7CiAgICAgICAgICAgICAgICAodC5nZXQoImdvb2dsZV9ldmVu"
    "dF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAgICAgICAgICAgICBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgaWYg"
    "KHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICB9CgogICAgICAgICAgICAjIOKUgOKU"
    "gCBGZXRjaCBmcm9tIEdvb2dsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICAgICAgc3RvcmVkX3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIpCgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5vdCBmb3JjZV9vbmNlOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEluY3Jl"
    "bWVudGFsIHN5bmMgKHN5bmNUb2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAg"
    "IHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xF"
    "XVtTWU5DXSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAg"
    "ICAgICAgICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAg"
    "ICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCgogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoKICAgICAgICAgICAgICAgIGlmICI0MTAiIGluIHN0cihhcGlfZXgpIG9yICJH"
    "b25lIiBpbiBzdHIoYXBpX2V4KToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDigJQgZnVsbCByZXN5bmMuIiwgIldBUk4i"
    "CiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3N0YXRlLnBvcCgiZ29vZ2xlX2NhbGVuZGFy"
    "X3N5bmNfdG9rZW4iLCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBsYWNl"
    "KG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2"
    "NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYu"
    "X2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAg"
    "ICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHJhaXNlCgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3Rl"
    "X2V2ZW50cyl9IGV2ZW50KHMpLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2VuIGZv"
    "ciBuZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICAgICAgICAgICAgIHNlbGYuX3N0"
    "YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF90b2tlbgogICAgICAgICAgICAgICAgc2VsZi5fbWVtb3J5"
    "LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQg"
    "PSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9IDAKICAgICAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAg"
    "ICBmb3IgZXZlbnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2ZW50LmdldCgiaWQiKSBv"
    "ciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CgogICAgICAgICAgICAgICAgIyBEZWxldGVkIC8gY2FuY2VsbGVkIG9uIEdvb2dsZSdzIHNpZGUKICAgICAgICAgICAgICAgIGlm"
    "IGV2ZW50LmdldCgic3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19i"
    "eV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgi"
    "c3RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sic3RhdHVzIl0gICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJjYW5jZWxs"
    "ZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSAgICA9ICJk"
    "ZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNv"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pWyJnb29nbGVfZGVsZXRl"
    "ZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3ZlZF9jb3VudCArPSAxCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4dCcsJz8n"
    "KX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAg"
    "ICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnkiKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50Iikuc3RyaXAo"
    "KSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9k"
    "dWVfZGF0ZXRpbWUoZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9p"
    "ZCkKCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgICAgICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBj"
    "aGFuZ2VkCiAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBpZiAoZXhp"
    "c3RpbmcuZ2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rp"
    "bmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAg"
    "ICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgZHVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQoImR1ZV9hdCIpICE9IGR1ZV9p"
    "c286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0Il0gICAgICAgPSBkdWVfaXNvCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJlX3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9"
    "MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQg"
    "PSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0YXR1cyIpICE9ICJzeW5jZWQiOgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICB1cGRh"
    "dGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBVcGRhdGVk"
    "OiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJpZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAg"
    "ICAgIGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90cmln"
    "Z2VyIjogICAgICAgKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgInN0YXR1cyI6ICAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0"
    "IjogICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6"
    "ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgICBGYWxzZSwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICAgImdvb2dsZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVf"
    "ZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICAic3luY2Vk"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9pbXBvcnRlZF9hdCI6IG5vd19p"
    "c28sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAgICAgZXZlbnQuZ2V0KCJ1cGRhdGVkIiks"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIH0sCiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tz"
    "LmFwcGVuZChuZXdfdGFzaykKICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtldmVudF9pZF0gPSBuZXdfdGFz"
    "awogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3VtbWFy"
    "eX0iLCAiSU5GTyIpCgogICAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9j"
    "b3VudH0gIgogICAgICAgICAgICAgICAgZiJ1cGRhdGVkPXt1cGRhdGVkX2NvdW50fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIs"
    "ICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIs"
    "ICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAwCgoKICAgIGRlZiBfbWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVt"
    "ID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBzZWxmLl9kZWNrX3Zy"
    "YW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgICAgIGYiW1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2VsZi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIKICAgICAg"
    "ICAgICAgICAgICAgICBmIih7REVDS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNTQUdFIEhBTkRMSU5H"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZW5kX21lc3NhZ2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5f"
    "bW9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0ZXh0OgogICAgICAgICAgICBy"
    "ZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBjaGF0IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAg"
    "ICAgIGlmIHNlbGYuX21haW5fdGFicy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0"
    "Q3VycmVudEluZGV4KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2Fn"
    "ZSgidXNlciIsIHRleHQpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1c2Vy"
    "IiwgdGV4dCkKCiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVkaWF0ZWx5CiAg"
    "ICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLmludGVycnVwdCgi"
    "YWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21wdCB3aXRoIHZhbXBpcmUgY29udGV4dCArIG1lbW9yeSBjb250ZXh0CiAgICAg"
    "ICAgdmFtcGlyZV9jdHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1v"
    "cnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nl"
    "c3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9z"
    "ZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAgICAg"
    "ICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNF"
    "CiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBp"
    "ZiBqb3VybmFsX2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9"
    "IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50IGlucHV0CiAgICAgICAgaWYg"
    "YW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24i"
    "KSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAgICAg"
    "ICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2UobGFuZykKICAgICAgICAg"
    "ICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAgICAg"
    "IyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21p"
    "c3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJzb21lIHRpbWUiCiAgICAg"
    "ICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxuIgogICAgICAgICAg"
    "ICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5nX3Ry"
    "YW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcgdGhhdCB0aW1lLiBB"
    "Y2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJh"
    "bC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBz"
    "ZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3Rv"
    "cnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAg"
    "ICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElO"
    "RyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQog"
    "ICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBMYXVuY2ggc3RyZWFtaW5nIHdvcmtlcgogICAg"
    "ICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgc3lzdGVtLCBoaXN0"
    "b3J5LCBtYXhfdG9rZW5zPTUxMgogICAgICAgICkKICAgICAgICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxm"
    "Ll9vbl90b2tlbikKICAgICAgICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2Rv"
    "bmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qoc2VsZi5fb25fZXJyb3IpCiAgICAgICAgc2Vs"
    "Zi5fd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICBzZWxmLl9maXJzdF90b2tl"
    "biA9IFRydWUgICMgZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAgICAgIHNlbGYuX3dv"
    "cmtlci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYWJlbCBhbmQgdGltZXN0YW1wIGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5z"
    "LgogICAgICAgIENhbGxlZCBvbiBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQgZGlyZWN0bHkuCiAg"
    "ICAgICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICAj"
    "IFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEgbmV3bGluZSBzbyB0b2tlbnMKICAgICAgICAjIGZs"
    "b3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5saW5lCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgZidbe3Rp"
    "bWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0NSSU1TT059OyBmb250LXdlaWdo"
    "dDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNLX05BTUUudXBwZXIoKX0g4p2pPC9zcGFuPiAnCiAgICAgICAgKQogICAgICAg"
    "ICMgTW92ZSBjdXJzb3IgdG8gZW5kIHNvIGluc2VydFBsYWluVGV4dCBhcHBlbmRzIGNvcnJlY3RseQogICAgICAgIGN1cnNvciA9"
    "IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1v"
    "dmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKCiAgICBkZWYg"
    "X29uX3Rva2VuKHNlbGYsIHRva2VuOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiQXBwZW5kIHN0cmVhbWluZyB0b2tlbiB0byBj"
    "aGF0IGRpc3BsYXkuIiIiCiAgICAgICAgaWYgc2VsZi5fZmlyc3RfdG9rZW46CiAgICAgICAgICAgIHNlbGYuX2JlZ2luX3BlcnNv"
    "bmFfcmVzcG9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IEZhbHNlCiAgICAgICAgY3Vyc29yID0gc2VsZi5f"
    "Y2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJh"
    "dGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2No"
    "YXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQodG9rZW4pCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xs"
    "QmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0o"
    "KQogICAgICAgICkKCiAgICBkZWYgX29uX3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAg"
    "ICAjIEVuc3VyZSByZXNwb25zZSBpcyBvbiBpdHMgb3duIGxpbmUKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "dGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmlu"
    "c2VydFBsYWluVGV4dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW9yeSBhbmQgc2Vzc2lvbgogICAgICAgIHNlbGYuX3Rv"
    "a2VuX2NvdW50ICs9IGxlbihyZXNwb25zZS5zcGxpdCgpKQogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJhc3Np"
    "c3RhbnQiLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgImFz"
    "c2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVtb3J5KHNlbGYuX3Nlc3Npb25faWQsICIi"
    "LCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUgYmxvb2Qgc3BoZXJlCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90"
    "IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4oMS4wLCBzZWxmLl90"
    "b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAogICAgICAgIHNlbGYu"
    "X3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBpZGxlIHRpbWVyCiAgICAgICAgc2F2ZV9j"
    "b25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1bGUgc2VudGlt"
    "ZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYu"
    "X3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBO"
    "b25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3Nl"
    "bnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29y"
    "a2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQo"
    "KQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9mYWNl"
    "X3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAgICBkZWYgX29u"
    "X2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3Ip"
    "CiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAg"
    "IGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNr"
    "ZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRy"
    "dWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQi"
    "OgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIp"
    "CiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRj"
    "aGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3Qg"
    "dW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAgICAgICAgICAg"
    "IHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAg"
    "c2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHBy"
    "ZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAi"
    "bWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJl"
    "dHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAg"
    "ICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAg"
    "ICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNl"
    "KHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9y"
    "bWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBu"
    "b3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAg"
    "IHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBN"
    "b2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNl"
    "dF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRu"
    "LnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4"
    "aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYg"
    "c2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNl"
    "CiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRz"
    "KCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9S"
    "UE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAg"
    "ICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAg"
    "ICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7"
    "REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5"
    "J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNv"
    "bm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAg"
    "ICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0"
    "RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8t"
    "dG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxv"
    "YWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAg"
    "ICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAgICAgICAg"
    "ICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldv"
    "cmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAg"
    "ICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9y"
    "LmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAg"
    "ICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAg"
    "c2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9h"
    "Y3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRl"
    "ZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSA1IHNl"
    "Y29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9y"
    "cG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBu"
    "ZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5f"
    "dG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdw"
    "dV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAg"
    "ICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5"
    "SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAgICAgICAg"
    "ICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwg"
    "PiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBu"
    "b3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291"
    "bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRl"
    "cm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAg"
    "ICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURf"
    "VElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRl"
    "cm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3Rh"
    "aW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9"
    "IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92"
    "cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dh"
    "a2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZh"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNLUyk6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAg"
    "ICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9zY2hl"
    "ZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5i"
    "YWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91"
    "bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0KICAgICAg"
    "ICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2"
    "YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAi"
    "V0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5n"
    "cyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5f"
    "c2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51"
    "dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChl"
    "dmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVz"
    "c3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAg"
    "ICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRs"
    "ZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdb"
    "InNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiAr"
    "IGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9maXJlX2lk"
    "bGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3Ry"
    "YW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAg"
    "ICAgaWYgc2VsZi5fY3ljbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAg"
    "IGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQo"
    "KSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIu"
    "c2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVu"
    "bmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0YXJ0X3Nj"
    "aGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0"
    "ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50"
    "IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlmIHNl"
    "bGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nj"
    "aGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVS"
    "XSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9z"
    "YXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAg"
    "ICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNp"
    "bmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVf"
    "aW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBT"
    "ZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNz"
    "aW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdF"
    "TkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAg"
    "ICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAgICAg"
    "IGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJu"
    "CgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAg"
    "ICAgdmFtcGlyZV9jdHggPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5n"
    "ZXRfaGlzdG9yeSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRh"
    "cHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBtb2Rl"
    "PW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9p"
    "ZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBhcHBlbmQgdGhlcmUK"
    "ICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAg"
    "ICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidb"
    "e3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+"
    "e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUi"
    "LCB0KQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkK"
    "ICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJST1JdIHtlfSIsICJFUlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVf"
    "d29ya2VyLnN0YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Np"
    "b24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25f"
    "YXNfY29udGV4dChkYXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChk"
    "YXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9u"
    "IGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRo"
    "YXQgY29udmVyc2F0aW9uLiIsICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAg"
    "ICAgICAgIGYiQSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVyLiIKICAg"
    "ICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAg"
    "IG5vdGUgPSAoCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5h"
    "bCBmcm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB5b3Ugbm93"
    "IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYXRpb24uIgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5h"
    "bF9zZXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pvdXJuYWwoKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVkLiIsICJJTkZPIikKICAgICAg"
    "ICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJl"
    "c2VudCByZW1haW5zLiIKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgp"
    "IC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDAp"
    "IC8vIDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogICAg"
    "ICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAgICAgICAgICAg"
    "IENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAgICAgIHNlc3Npb25fc3RyLAogICAgICAg"
    "ICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAogICAgICAgICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMo"
    "KQoKICAgICAgICAjIExlZnQgc3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAgICAgICBs"
    "ZWZ0X29yYl9maWxsID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgaWYgc2VsZi5fbGVmdF9v"
    "cmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwobGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxl"
    "PVRydWUpCgogICAgICAgICMgUmlnaHQgc3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9yaWdodF9v"
    "cmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAg"
    "ICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHZyYW1fdG90"
    "ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9vcmJfZmlsbCA9IG1heCgwLjAsIDEuMCAt"
    "ICh2cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwocmlnaHRf"
    "b3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAjIFByaW1hcnkg"
    "ZXNzZW5jZSA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGVzc2VuY2VfcHJpbWFyeV9yYXRpbyA9IDEuMCAt"
    "IGxlZnRfb3JiX2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmlt"
    "YXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEw"
    "MDouMGZ9JSIpCgogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFC"
    "TEVEOgogICAgICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVt"
    "ICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAgICBlc3NlbmNlX3NlY29uZGFyeV9yYXRp"
    "byAgPSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRh"
    "cnlfZ2F1Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBm"
    "Intlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2"
    "YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5z"
    "ZXRVbmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAogICAgICAgIHNl"
    "bGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigp"
    "OkNfR09MRCwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAog"
    "ICAgICAgIH0KICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKICAgICAg"
    "ICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAg"
    "ICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2Vy"
    "LCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAgICAg"
    "ICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzcGVha2VyID09"
    "ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBz"
    "dHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9"
    "XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08"
    "L3NwYW4+JwogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgK"
    "ICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAg"
    "ICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOnts"
    "YWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcK"
    "ICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAgICAp"
    "CgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcp"
    "CiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFw"
    "cGVuZCgiIikKCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAg"
    "ICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICAjIOKUgOKU"
    "gCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2dldF9nb29nbGVf"
    "cmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9"
    "KQogICAgICAgIHZhbCA9IHNldHRpbmdzLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMDAwMDApCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX2dldF9lbWFpbF9yZWZyZXNoX2ludGVydmFsX21zKHNlbGYpIC0+IGludDoK"
    "ICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdmFsID0gc2V0dGluZ3MuZ2V0KCJlbWFp"
    "bF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIG1heCgxMDAwLCBp"
    "bnQodmFsKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gMzAwMDAwCgogICAgZGVmIF9zZXRf"
    "Z29vZ2xlX3JlZnJlc2hfc2Vjb25kcyhzZWxmLCBzZWNvbmRzOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBzZWNvbmRzID0gbWF4KDUsIG1pbig2MDAsIGludChzZWNvbmRzKSkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyJdID0gc2Vjb25k"
    "cyAqIDEwMDAKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgZm9yIHRpbWVyIGluIChzZWxmLl9nb29nbGVfaW5ib3Vu"
    "ZF90aW1lciwgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcik6CiAgICAgICAgICAgIGlmIHRpbWVyIGlzIG5vdCBO"
    "b25lOgogICAgICAgICAgICAgICAgdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdTXSBHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge3NlY29u"
    "ZHN9IHNlY29uZChzKS4iLCAiT0siKQoKICAgIGRlZiBfc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQoc2VsZiwg"
    "dGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgbWludXRlcyA9IG1heCgxLCBpbnQoZmxvYXQoc3Ry"
    "KHRleHQpLnN0cmlwKCkpKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBDRkdb"
    "InNldHRpbmdzIl1bImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiXSA9IG1pbnV0ZXMgKiA2MDAwMAogICAgICAgIHNhdmVfY29u"
    "ZmlnKENGRykKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1NFVFRJTkdTXSBFbWFpbCByZWZyZXNo"
    "IGludGVydmFsIHNldCB0byB7bWludXRlc30gbWludXRlKHMpIChjb25maWcgZm91bmRhdGlvbikuIiwKICAgICAgICAgICAgIklO"
    "Rk8iLAogICAgICAgICkKCiAgICBkZWYgX3NldF90aW1lem9uZV9hdXRvX2RldGVjdChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBO"
    "b25lOgogICAgICAgIENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfYXV0b19kZXRlY3QiXSA9IGJvb2woZW5hYmxlZCkKICAgICAg"
    "ICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW1NFVFRJTkdTXSBUaW1l"
    "IHpvbmUgbW9kZSBzZXQgdG8gYXV0by1kZXRlY3QuIiBpZiBlbmFibGVkIGVsc2UgIltTRVRUSU5HU10gVGltZSB6b25lIG1vZGUg"
    "c2V0IHRvIG1hbnVhbCBvdmVycmlkZS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRlZiBfc2V0X3RpbWV6"
    "b25lX292ZXJyaWRlKHNlbGYsIHR6X25hbWU6IHN0cikgLT4gTm9uZToKICAgICAgICB0el92YWx1ZSA9IHN0cih0el9uYW1lIG9y"
    "ICIiKS5zdHJpcCgpCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJ0aW1lem9uZV9vdmVycmlkZSJdID0gdHpfdmFsdWUKICAgICAg"
    "ICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgdHpfdmFsdWU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltT"
    "RVRUSU5HU10gVGltZSB6b25lIG92ZXJyaWRlIHNldCB0byB7dHpfdmFsdWV9LiIsICJJTkZPIikKCiAgICBkZWYgX3NldF9zdGF0"
    "dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVz"
    "X2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19D"
    "UklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxP"
    "T0QsCiAgICAgICAgICAgICJPRkZMSU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9E"
    "SU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAg"
    "ICB0b3Jwb3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJ"
    "IHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3Rh"
    "dHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAi"
    "R0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAg"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl9z"
    "dGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLiipgi"
    "CiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9S"
    "X1NUQVRVU30iCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJz"
    "ZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9O"
    "IiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNvbG9y"
    "OiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsg"
    "Zm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxl"
    "ci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBlbmFibGVkOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAiT0siKQogICAgICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gcGF1c2VkLiIsICJJTkZP"
    "IikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKUgOKUgCBXSU5ET1cgQ09OVFJPTFMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2NyZWVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5pc0Z1bGxT"
    "Y3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJmdWxsc2Ny"
    "ZWVuX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWln"
    "aHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuc2hv"
    "d0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3JlZW5fZW5hYmxlZCJdID0gVHJ1ZQogICAg"
    "ICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNP"
    "Tl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsi"
    "CiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF90b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIGlzX2JsID0gYm9vbChzZWxmLndpbmRvd0ZsYWdzKCkgJiBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dp"
    "bmRvd0hpbnQpCiAgICAgICAgaWYgaXNfYmw6CiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAg"
    "ICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2Js"
    "X2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNP"
    "Tl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5"
    "cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgICAgICBzZWxmLnNob3dO"
    "b3JtYWwoKQogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygp"
    "IHwgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5n"
    "cyJdWyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAg"
    "ZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZH"
    "KQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4cG9y"
    "dCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgdGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAg"
    "ICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNl"
    "YW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAg"
    "ICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRU"
    "ZXh0KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lv"
    "biBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtl"
    "eVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkKICAgICAgICBpZiBrZXkg"
    "PT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9"
    "PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09"
    "IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQog"
    "ICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIK"
    "ICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAj"
    "IOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9z"
    "ZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRp"
    "YWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVs"
    "eSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5j"
    "ZSwganVzdCBmb3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2Up"
    "OgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0"
    "IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/"
    "IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0Nf"
    "VEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAg"
    "ZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9"
    "IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQogICAgICAgIGxibC5z"
    "ZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0bl9u"
    "b3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2Vs"
    "IikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5p"
    "bXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBw"
    "YWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5l"
    "Y3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBidG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIp"
    "KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5h"
    "ZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogICAgICAgIGJ0bl9yb3cuYWRk"
    "V2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4"
    "ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAg"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiBy"
    "ZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5f"
    "ZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBz"
    "aHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0"
    "X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyBy"
    "ZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAg"
    "ICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJT"
    "cGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUg"
    "cmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0i"
    "LAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBoZXIgZmluYWwgd29yZHMuLi4iCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0"
    "RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7"
    "InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5n"
    "V29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9r"
    "ZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAg"
    "ICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25l"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhlIHRl"
    "eHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNl"
    "bGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIGZhaWxlZDoge2Vycm9y"
    "fSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9r"
    "ZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChf"
    "b25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3"
    "b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQu"
    "Y29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0"
    "eSB0aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFU"
    "aW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAg"
    "ZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAi"
    "V0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0IHNodXQgZG93bgogICAgICAg"
    "ICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQK"
    "ICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0"
    "ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsi"
    "bGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29u"
    "dGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAg"
    "ICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxs"
    "CiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAg"
    "ICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQnLCAiIikKICAgICAgICAg"
    "ICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAg"
    "ICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwg"
    "PSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxm"
    "Ll9zdGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBw"
    "YXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRv"
    "d24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAg"
    "ICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3No"
    "dXRkb3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9z"
    "dGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIK"
    "ICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1"
    "bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0"
    "PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFBsYXkg"
    "c2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIo"
    "InNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93"
    "bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZ"
    "IFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIK"
    "ICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRl"
    "cGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDi"
    "hpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxz"
    "L1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8g"
    "dGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290"
    "c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0"
    "Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDi"
    "gJQgdXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9u"
    "IGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBE"
    "ZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZv"
    "ciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2"
    "KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5P"
    "VyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhp"
    "cyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFB"
    "cHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJz"
    "dCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBD"
    "RkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxv"
    "ZygpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5l"
    "eGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3Jn"
    "YW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2li"
    "bGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAu"
    "cHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21l"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAgICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBj"
    "b25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0"
    "cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0ciht"
    "b3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5k"
    "cyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAi"
    "c2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIobW9y"
    "Z2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiks"
    "CiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMi"
    "OiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFfaG9t"
    "ZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiKSwKICAg"
    "ICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5u"
    "YV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAg"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJB"
    "bWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNv"
    "bS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIs"
    "CiAgICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDi"
    "lIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVf"
    "XykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2su"
    "cHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIF9zaHV0"
    "aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgog"
    "ICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5n"
    "IiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57"
    "ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHkuIgogICAgICAgICAg"
    "ICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9"
    "IG1vcmdhbm5hX2hvbWUgLyAiY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBl"
    "eGlzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAg"
    "ICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRp"
    "cmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gYm9v"
    "dHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJh"
    "cF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgp"
    "CgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFjZV96aXApLmV4aXN0"
    "cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAgICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5u"
    "YV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6"
    "CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAgICAgIGZvciBtZW1iZXIgaW4gemYubmFt"
    "ZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aXRoIHpmLm9wZW4o"
    "bWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBk"
    "c3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAg"
    "ICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0i"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBa"
    "SVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAg"
    "ICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFj"
    "dCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86"
    "XG57ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQg"
    "cG9pbnRpbmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9"
    "IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYg"
    "V0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAg"
    "ICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAgICAgc2NfcGF0aCAg"
    "ICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5"
    "cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAg"
    "ICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0gUGF0aChz"
    "eXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIp"
    "CiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAgICAgICAgc2MuQXJndW1lbnRz"
    "ICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdh"
    "bm5hX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBE"
    "ZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBU"
    "cnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBD"
    "b3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAg"
    "ICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1t"
    "b24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAg"
    "ICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xp"
    "Y2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAg"
    "IE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RF"
    "Q0tfTkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9"
    "XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdp"
    "bGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gg"
    "e0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20g"
    "c2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDi"
    "lIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFw"
    "X3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3"
    "aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3JlYXRlZCDigJQgY2Fs"
    "bGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIHdpbmRvdy5zaG93KCkgY2FsbGVk"
    "IOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRp"
    "bCBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxz"
    "IHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltU"
    "SU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cu"
    "c3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJd"
    "IF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5k"
    "b3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAgIyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRv"
    "IHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFy"
    "dHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5j"
    "b25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3Rh"
    "cnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoK"
    "CmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5l"
    "IGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBhc3Mg"
    "MyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNgo="
)


def _get_deck_implementation(log_fn=None) -> str:
    """
    Returns the full embedded deck implementation.
    Completely self-contained — no external files required.
    """
    import base64 as _base64
    if log_fn:
        log_fn("[DECK] Using embedded implementation")
    return _base64.b64decode(_DECK_IMPL_B64).decode("utf-8")

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
