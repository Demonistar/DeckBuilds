# ═══════════════════════════════════════════════════════════════════════════════
# ECHO DECK BUILDER
# Filename   : deck_builder.py
# Version    : 2.0.0
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
        QSizePolicy, QSplitter, QToolButton
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
        "status":       "planned",
        "description":  "Full polyhedral set. Advantage/disadvantage. Persona commentary.",
        "tab_name":     "Dice",
        "slot_key":     "MODULE_DICE_ROLLER",
        "requires":     [],
        "default_on":   False,
    },
    "magic_8ball": {
        "display_name": "Magic 8-Ball",
        "category":     "Tools",
        "status":       "planned",
        "description":  "Persona-flavored responses. Shake animation.",
        "tab_name":     "8-Ball",
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
        "mirror_label":       "Mirror",
        "emotions_label":     "Emotions",
        "left_orb_title":     "Resource",
        "left_orb_label":     "Resource",
        "cycle_title":        "Cycle",
        "right_orb_title":    "Reserve",
        "right_orb_label":    "Reserve",
        "essence_title":      "Essence",
        "essence_primary":    "Need",
        "essence_secondary":  "Vitality",
        "footer_strip_label": "State",
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
    "dice_roller":        None,
    "magic_8ball":        None,
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
            "<<<SUSPENSION_LABEL>>>":      (ui_labels.get("suspension_label", "").strip() or "Suspended"),
            "<<<RUNES>>>":                 ui_labels.get("runes",              "— ECHO DECK —"),
            "<<<MIRROR_LABEL>>>":          ui_labels.get("mirror_label",       "Mirror"),
            "<<<EMOTIONS_LABEL>>>":        ui_labels.get("emotions_label",     "Emotions"),
            "<<<LEFT_ORB_TITLE>>>":        ui_labels.get("left_orb_title",     "Resource"),
            "<<<LEFT_ORB_LABEL>>>":        ui_labels.get("left_orb_label",     "Resource"),
            "<<<CYCLE_TITLE>>>":           ui_labels.get("cycle_title",        "Cycle"),
            "<<<RIGHT_ORB_TITLE>>>":       ui_labels.get("right_orb_title",    "Reserve"),
            "<<<RIGHT_ORB_LABEL>>>":       ui_labels.get("right_orb_label",    "Reserve"),
            "<<<ESSENCE_TITLE>>>":         ui_labels.get("essence_title",      "Essence"),
            "<<<ESSENCE_PRIMARY>>>":       ui_labels.get("essence_primary",    "Need"),
            "<<<ESSENCE_SECONDARY>>>":     ui_labels.get("essence_secondary",  "Vitality"),
            "<<<FOOTER_STRIP_LABEL>>>":    ui_labels.get("footer_strip_label", "State"),
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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNITyBERUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJT04KIyBHZW5lcmF0ZWQgYnkgZGVja19idWls"
    "ZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGluamVjdGVkIGZyb20gREVDS19URU1QTEFURSBoZWFkZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKCmltcG9ydCBzeXMKaW1wb3J0IG9zCmlt"
    "cG9ydCBqc29uCmltcG9ydCBtYXRoCmltcG9ydCB0aW1lCmltcG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5n"
    "CmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9u"
    "ZQpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJvbSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsLCBJdGVyYXRvcgoKIyDilIDilIAgRUFSTFkgQ1JBU0ggTE9H"
    "R0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEhvb2tzIGlu"
    "IGJlZm9yZSBRdCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFMTCBvdXRwdXQgaW5jbHVkaW5nCiMgQysrIGxldmVsIFF0IG1lc3NhZ2VzLiBXcml0"
    "dGVuIHRvIFtEZWNrTmFtZV0vbG9ncy9zdGFydHVwLmxvZwojIFRoaXMgc3RheXMgYWN0aXZlIGZvciB0aGUgbGlmZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJM"
    "WV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlfTE9HX1BBVEg6IE9wdGlvbmFsW1BhdGhdID0gTm9uZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+"
    "IE5vbmU6CiAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzotM10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNnfSIKICAg"
    "IF9FQVJMWV9MT0dfTElORVMuYXBwZW5kKGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQogICAgaWYgX0VBUkxZX0xPR19QQVRIOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBm"
    "LndyaXRlKGxpbmUgKyAiXG4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCmRlZiBfaW5pdF9lYXJseV9sb2coYmFzZV9k"
    "aXI6IFBhdGgpIC0+IE5vbmU6CiAgICBnbG9iYWwgX0VBUkxZX0xPR19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIgLyAibG9ncyIKICAgIGxvZ19kaXIu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xPR19QQVRIID0gbG9nX2RpciAvIGYic3RhcnR1cF97ZGF0ZXRpbWUubm93"
    "KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0ubG9nIgogICAgIyBGbHVzaCBidWZmZXJlZCBsaW5lcwogICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3Bl"
    "bigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIGxpbmUgaW4gX0VBUkxZX0xPR19MSU5FUzoKICAgICAgICAgICAgZi53cml0ZShs"
    "aW5lICsgIlxuIikKCmRlZiBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKSAtPiBOb25lOgogICAgIiIiCiAgICBJbnRlcmNlcHQgQUxMIFF0IG1lc3Nh"
    "Z2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2FybmluZ3MuCiAgICBUaGlzIGNhdGNoZXMgdGhlIFFUaHJlYWQgZGVzdHJveWVkIG1lc3NhZ2UgYXQgdGhlIHNv"
    "dXJjZSBhbmQgbG9ncyBpdAogICAgd2l0aCBhIGZ1bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cgZXhhY3RseSB3aGljaCB0aHJlYWQgYW5kIHdoZXJlLgogICAg"
    "IiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNzYWdlSGFuZGxlciwgUXRNc2dUeXBlCiAgICAgICAg"
    "aW1wb3J0IHRyYWNlYmFjawoKICAgICAgICBkZWYgcXRfbWVzc2FnZV9oYW5kbGVyKG1zZ190eXBlLCBjb250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAg"
    "bGV2ZWwgPSB7CiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXREZWJ1Z01zZzogICAgIlFUX0RFQlVHIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5R"
    "dEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRXYXJuaW5nTXNnOiAgIlFUX1dBUk5JTkciLAogICAgICAgICAg"
    "ICAgICAgUXRNc2dUeXBlLlF0Q3JpdGljYWxNc2c6ICJRVF9DUklUSUNBTCIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRGYXRhbE1zZzogICAgIlFU"
    "X0ZBVEFMIiwKICAgICAgICAgICAgfS5nZXQobXNnX3R5cGUsICJRVF9VTktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0gIiIKICAgICAgICAgICAg"
    "aWYgY29udGV4dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmlsZX06e2NvbnRleHQubGluZX1dIgoKICAgICAgICAg"
    "ICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2NhdGlvbn0ge21lc3NhZ2V9IikKCiAgICAgICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxv"
    "ZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAgICBpZiAiUVRocmVhZCIgaW4gbWVzc2FnZSBvciAidGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAg"
    "ICAgICAgICAgICAgICBzdGFjayA9ICIiLmpvaW4odHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltTVEFD"
    "SyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3RhbGxNZXNzYWdlSGFuZGxlcihxdF9tZXNzYWdlX2hhbmRsZXIpCiAgICAg"
    "ICAgX2Vhcmx5X2xvZygiW0lOSVRdIFF0IG1lc3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIF9l"
    "YXJseV9sb2coZiJbSU5JVF0gQ291bGQgbm90IGluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyOiB7ZX0iKQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7REVDS19O"
    "QU1FfSBkZWNrIHN0YXJ0aW5nIikKX2Vhcmx5X2xvZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNwbGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJs"
    "ZX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFdvcmtpbmcgZGlyZWN0b3J5OiB7b3MuZ2V0Y3dkKCl9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBTY3JpcHQgbG9j"
    "YXRpb246IHtQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCl9IikKCiMg4pSA4pSAIE9QVElPTkFMIERFUEVOREVOQ1kgR1VBUkRTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKUFNVVElMX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElM"
    "X09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYi"
    "W0lNUE9SVF0gcHN1dGlsIEZBSUxFRDoge2V9IikKCk5WTUxfT0sgPSBGYWxzZQpncHVfaGFuZGxlID0gTm9uZQp0cnk6CiAgICBpbXBvcnQgd2FybmluZ3MK"
    "ICAgIHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToKICAgICAgICB3YXJuaW5ncy5zaW1wbGVmaWx0ZXIoImlnbm9yZSIpCiAgICAgICAgaW1wb3J0"
    "IHB5bnZtbAogICAgcHludm1sLm52bWxJbml0KCkKICAgIGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VHZXRDb3VudCgpCiAgICBpZiBjb3VudCA+IDA6CiAg"
    "ICAgICAgZ3B1X2hhbmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxlQnlJbmRleCgwKQogICAgICAgIE5WTUxfT0sgPSBUcnVlCiAgICBfZWFybHlf"
    "bG9nKGYiW0lNUE9SVF0gcHludm1sIE9LIOKAlCB7Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1Q"
    "T1JUXSBweW52bWwgRkFJTEVEOiB7ZX0iKQoKVE9SQ0hfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgdG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGlt"
    "cG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9y"
    "Y2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHRvcmNoIEZBSUxF"
    "RCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luMzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUK"
    "ICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHdpbjMyY29tIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0g"
    "d2luMzJjb20gRkFJTEVEOiB7ZX0iKQoKV0lOU09VTkRfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luc291bmQKICAgIFdJTlNPVU5EX09LID0gVHJ1"
    "ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JU"
    "XSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKClBZR0FNRV9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5t"
    "aXhlci5pbml0KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHB5Z2FtZSBPSyIpCmV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xFX09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZhbHNl"
    "ICAjIGFsaWFzIHVzZWQgYnkgR29vZ2xlIHNlcnZpY2UgY2xhc3NlcwpHT09HTEVfSU1QT1JUX0VSUk9SID0gTm9uZQp0cnk6CiAgICBmcm9tIGdvb2dsZS5h"
    "dXRoLnRyYW5zcG9ydC5yZXF1ZXN0cyBpbXBvcnQgUmVxdWVzdCBhcyBHb29nbGVBdXRoUmVxdWVzdAogICAgZnJvbSBnb29nbGUub2F1dGgyLmNyZWRlbnRp"
    "YWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVkZW50aWFscwogICAgZnJvbSBnb29nbGVfYXV0aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0"
    "YWxsZWRBcHBGbG93CiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5kaXNjb3ZlcnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2dsZV9idWlsZAogICAgZnJvbSBnb29n"
    "bGVhcGljbGllbnQuZXJyb3JzIGltcG9ydCBIdHRwRXJyb3IgYXMgR29vZ2xlSHR0cEVycm9yCiAgICBHT09HTEVfT0sgPSBUcnVlCiAgICBHT09HTEVfQVBJ"
    "X09LID0gVHJ1ZQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgX2U6CiAgICBHT09HTEVfSU1QT1JUX0VSUk9SID0gc3RyKF9lKQogICAgR29vZ2xlSHR0cEVycm9y"
    "ID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVTID0gWwogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIiLAogICAgImh0dHBz"
    "Oi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwK"
    "ICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCl0KR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cgPSAoCiAgICAiR29vZ2xl"
    "IHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3IgaW5jb21wYXRpYmxlIHdpdGggcmVxdWVzdGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29u"
    "IGFuZCByZWF1dGhvcml6ZSB3aXRoIHRoZSB1cGRhdGVkIHNjb3BlIGxpc3QuIgopCkRFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUgPSAiQW1lcmljYS9D"
    "aGljYWdvIgpXSU5ET1dTX1RaX1RPX0lBTkEgPSB7CiAgICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAiRWFzdGVy"
    "biBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRhcmQgVGltZSI6ICJBbWVyaWNhL0xvc19BbmdlbGVzIiwK"
    "ICAgICJNb3VudGFpbiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvRGVudmVyIiwKfQoKCiMg4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZnJvbSBQeVNpZGU2LlF0"
    "V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFpbldpbmRvdywgUVdpZGdldCwgUVZCb3hMYXlvdXQsIFFIQm94TGF5b3V0LAogICAgUUdy"
    "aWRMYXlvdXQsIFFUZXh0RWRpdCwgUUxpbmVFZGl0LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBRRnJhbWUsCiAgICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdp"
    "ZGdldCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRlclZpZXcsCiAgICBRQWJzdHJhY3RJdGVtVmlldywgUVN0YWNrZWRXaWRnZXQsIFFUYWJXaWRnZXQsIFFM"
    "aXN0V2lkZ2V0LAogICAgUUxpc3RXaWRnZXRJdGVtLCBRU2l6ZVBvbGljeSwgUUNvbWJvQm94LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3Nh"
    "Z2VCb3gsIFFEYXRlRWRpdCwgUURpYWxvZywgUUZvcm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNwbGl0dGVyLCBRSW5wdXREaWFsb2csIFFUb29sQnV0"
    "dG9uCikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNpemUsIFFQb2ludCwg"
    "UVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQYWludGVyLCBRTGluZWFyR3JhZGllbnQsIFFSYWRpYWxH"
    "cmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQYWludGVyUGF0aCwgUVRleHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9u"
    "CikKCiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUgICAgICA9IFVJX1dJTkRPV19USVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4wIgpB"
    "UFBfRklMRU5BTUUgID0gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0wNCIKCiMg4pSA4pSAIENPTkZJ"
    "RyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29uIGxpdmVzIG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcu"
    "IE5vdGhpbmcgaGFyZGNvZGVkIGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudApDT05GSUdf"
    "UEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5vdyB0aGF0IHdlIGtub3cgd2hlcmUgd2UgYXJlCl9p"
    "bml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlfbG9nKGYiW0lOSVRdIFNDUklQVF9ESVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lO"
    "SVRdIENPTkZJR19QQVRIID0ge0NPTkZJR19QQVRIfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3RzOiB7Q09ORklHX1BBVEguZXhp"
    "c3RzKCl9IikKCmRlZiBfZGVmYXVsdF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBm"
    "aXJzdC1ydW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVybiB7CiAgICAgICAgImRlY2tfbmFtZSI6IERFQ0tf"
    "TkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGlyIjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7CiAg"
    "ICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8IG9sbGFtYSB8IGNsYXVkZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6"
    "ICIiLCAgICAgICAgICAgICAgICMgbG9jYWwgbW9kZWwgZm9sZGVyIHBhdGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4g"
    "ImRvbHBoaW4tMi42LTdiIgogICAgICAgICAgICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAg"
    "ImFwaV90eXBlIjogIiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2RlbCI6ICIiLCAgICAgICAgICAjIGUu"
    "Zy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAgICAgICAgImdvb2dsZSI6IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQ"
    "VF9ESVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29w"
    "ZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAg"
    "Imh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgv"
    "ZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKFNDUklQ"
    "VF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIgLyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmll"
    "cyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAg"
    "ICAgICAgICAgICJzbCI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4"
    "cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIoU0NS"
    "SVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJn"
    "b29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIpLAogICAgICAgIH0sCiAgICAgICAgInNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9l"
    "bmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiaWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRs"
    "ZV9tYXhfbWludXRlcyI6ICAgICAgICAgIDMwLAogICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4"
    "X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAogICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRydWUsCiAgICAgICAgICAgICJz"
    "b3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAg"
    "ICAgICAiZ29vZ2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAg"
    "IH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUsCiAgICB9CgpkZWYgbG9hZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4g"
    "UmV0dXJucyBkZWZhdWx0IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdfUEFUSC5leGlzdHMoKToKICAgICAgICByZXR1cm4g"
    "X2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAgICAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAg"
    "ICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNh"
    "dmVfY29uZmlnKGNmZzogZGljdCkgLT4gTm9uZToKICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAg"
    "anNvbi5kdW1wKGNmZywgZiwgaW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0IG1vZHVsZSBsZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9t"
    "IENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJseV9sb2coZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9y"
    "dW4nKX0sIG1vZGVsX3R5cGU9e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BBVEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7"
    "CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJzb3VuZHMiOiAgIFNDUklQVF9ESVIgLyAic291bmRzIiwKICAgICJtZW1vcmll"
    "cyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAogICAgInNlc3Npb25zIjogU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJ"
    "UFRfRElSIC8gInNsIiwKICAgICJleHBvcnRzIjogIFNDUklQVF9ESVIgLyAiZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElSIC8gImxvZ3Mi"
    "LAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAvICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVyc29uYXMiLAogICAgImdv"
    "b2dsZSI6ICAgU0NSSVBUX0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKSAtPiBOb25lOgogICAgIiIiCiAgICBTZWxm"
    "LWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMgbWlzc2luZyByZXF1aXJlZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBu"
    "b3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lzdHMgY29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hh"
    "bmdlZC4KICAgICIiIgogICAgY2hhbmdlZCA9IEZhbHNlCiAgICBwYXRocyA9IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVm"
    "YXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdldChrZXkpOgogICAgICAgICAgICBwYXRoc1trZXld"
    "ID0gc3RyKGRlZmF1bHRfcGF0aCkKICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVfY2ZnID0gQ0ZHLnNldGRlZmF1bHQoImdvb2dsZSIs"
    "IHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xlIiwgc3RyKF9ERUZBVUxUX1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVs"
    "dF9jcmVkcyA9IHN0cihnb29nbGVfcm9vdCAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290"
    "IC8gInRva2VuLmpzb24iKQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSkuc3RyaXAoKQogICAgdG9rZW5f"
    "dmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tlbiIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBjcmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVk"
    "c192YWwgYW5kICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIgaW4gY3JlZHNfdmFsKToKICAgICAgICBnb29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVm"
    "YXVsdF9jcmVkcwogICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3QgdG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBkZWZh"
    "dWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29uZmlnKENGRykKCmRlZiBjZmdfcGF0aChr"
    "ZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQgYSBwYXRoIGZyb20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3"
    "aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBwYXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAgICB2YWx1ZSA9IHBhdGhzLmdldChrZXkp"
    "CiAgICBpZiB2YWx1ZToKICAgICAgICByZXR1cm4gUGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZh"
    "bGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAgcmV0dXJuIGZhbGxiYWNrCiAgICByZXR1cm4gU0NSSVBUX0RJUiAv"
    "IGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0"
    "ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1B"
    "UlksIENfU0VDT05EQVJZLCBDX0FDQ0VOVCwgQ19CRywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElNIGFyZSBpbmplY3RlZCBhdCB0"
    "aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIuCiMgRXZlcnl0aGluZyBiZWxvdyBpcyBkZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFs"
    "dWVzLgoKIyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xvcnMgdG8gbmFtZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRoZSBVSQpDX0NS"
    "SU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAgICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMsIGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0g"
    "PSBDX1BSSU1BUlkgKyAiODgiICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0bGUgYm9yZGVycwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMg"
    "bWFpbiBsYWJlbC90ZXh0L0FJIG91dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGltIHNlY29uZGFyeQpDX0dPTERf"
    "QlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMgZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpDX1NJTFZFUiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMg"
    "c2Vjb25kYXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJTSAgPSBDX1RFWFRfRElNICsgIjg4IiAgIyBkaW0gc2Vjb25kYXJ5IHRleHQK"
    "Q19NT05JVE9SICAgICA9IENfQkcgICAgICAgICAgICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAg"
    "ICAgID0gQ19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAgICA9IENfUEFORUwgICAgICAgICAgICAjIHRlcnRp"
    "YXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkxPT0QgICAgICAgPSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBzdGF0ZXMs"
    "IGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAgICAgPSAnIzg4NTVjYycgICAgICAgICAgIyBTWVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApD"
    "X1BVUlBMRV9ESU0gID0gJyMyYTA1MmEnICAgICAgICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0YWE2NicgICAg"
    "ICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4Y2MnICAgICAgICAgICMgaW5mbyBzdGF0ZXMg4oCU"
    "IHVuaXZlcnNhbAoKIyBGb250IGhlbHBlciDigJQgZXh0cmFjdHMgcHJpbWFyeSBmb250IG5hbWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlf"
    "Rk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgpLnN0cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24gcmVj"
    "b3JkIGNoaXBzKQpFTU9USU9OX0NPTE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAg"
    "Q19HT0xELAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6ICAgICAgQ19HT0xELAogICAg"
    "ImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFuaWNrZWQiOiAgIENfQ1JJTVNPTiwKICAgICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2Nr"
    "ZWQiOiAgICBDX0NSSU1TT04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAgICJjb25jZXJuZWQiOiAgIiNjYzY2MjIiLAogICAgInNhZCI6ICAg"
    "ICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRlZCI6ICIjY2M2NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjog"
    "ICBDX1BVUlBMRSwKICAgICJzdXNwaWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENfUFVSUExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJ"
    "TFZFUiwKICAgICJhbGVydCI6ICAgICAgQ19TSUxWRVIsCiAgICAibmV1dHJhbCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09SQVRJVkUgQ09O"
    "U1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlz"
    "IHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVTCgojIEZhY2UgaW1hZ2UgbWFw"
    "IOKAlCBwcmVmaXggZnJvbSBGQUNFX1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFjZXMKRkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0g"
    "PSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVy"
    "dC5wbmciLAogICAgImZvY3VzZWQiOiAgICBmIntGQUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1f"
    "U211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIsCiAgICAic2FkIjogICAgICAgIGYie0ZBQ0VfUFJF"
    "RklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBm"
    "IntGQUNFX1BSRUZJWH1fSW1wcmVzc2VkLnBuZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJFRklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxp"
    "YXRlZCI6IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlhdGVkLnBuZyIsCiAgICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNpb3VzLnBuZyIs"
    "CiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0bW9kZSI6ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRf"
    "TW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBmIntGQUNFX1BSRUZJWH1fQW5ncnkucG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9"
    "X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBuZyIsCiAgICAiaGFwcHkiOiAgICAgIGYie0ZBQ0Vf"
    "UFJFRklYfV9IYXBweS5wbmciLAogICAgImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZB"
    "Q0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAgZiJ7RkFDRV9QUkVGSVh9X0VudmlvdXMucG5nIiwKfQoKU0VOVElNRU5UX0xJ"
    "U1QgPSAoCiAgICAibmV1dHJhbCwgYWxlcnQsIGZvY3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZlZCwgaW1wcmVzc2VkLCAiCiAgICAidmlj"
    "dG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNrZWQsIGFuZ3J5LCBwbG90dGluZywgc2hvY2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZs"
    "dXN0ZXJlZCwgZW52aW91cyIKKQoKIyDilIDilIAgU1lTVEVNIFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBm"
    "aWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRfQkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJvdmUg"
    "ZnJvbSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3QgcmVkZWZpbmUgaXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBTVFlMRVNIRUVU"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9"
    "IGYiIiIKUU1haW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGZvbnQt"
    "ZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRVGV4dEVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtD"
    "X0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtV"
    "SV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjoge0Nf"
    "Q1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAg"
    "Zm9udC1zaXplOiAxM3B4OwogICAgcGFkZGluZzogOHB4IDEycHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09M"
    "RH07CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZv"
    "bnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHgg"
    "MjBweDsKICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQdXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OfTsK"
    "ICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNzZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAg"
    "IGJvcmRlci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7ewogICAgYmFja2dyb3VuZC1j"
    "b2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0"
    "aWNhbCB7ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAgIGJvcmRlcjogbm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZl"
    "cnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2"
    "ZXJ0aWNhbDpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xsQmFy"
    "OjpzdWItbGluZTp2ZXJ0aWNhbCB7ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6OnBhbmUge3sKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07Cn19ClFUYWJCYXI6OnRhYiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9y"
    "OiB7Q19URVhUX0RJTX07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFt"
    "aWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUVRhYkJhcjo6dGFiOnNlbGVj"
    "dGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQg"
    "e0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRhYjpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dPTERfRElNfTsK"
    "fX0KUVRhYmxlV2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OwogICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQt"
    "c2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjog"
    "e0NfR09MRF9CUklHSFR9Owp9fQpRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsK"
    "ICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRQ29tYm9Cb3gge3sKICAg"
    "IGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRk"
    "aW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFDb21ib0JveDo6ZHJvcC1kb3duIHt7CiAgICBib3JkZXI6IG5v"
    "bmU7Cn19ClFDaGVja0JveCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9fQpRU3BsaXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9E"
    "SU19OwogICAgd2lkdGg6IDJweDsKfX0KIiIiCgojIOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgQ3JlYXRlIGFsbCByZXF1aXJlZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAgQ2FsbGVkIG9uIHN0YXJ0dXAgYmVmb3JlIGFueXRo"
    "aW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFsc28gbWlncmF0ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmll"
    "cyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRpcnMgPSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2VzIiksCiAgICAgICAgY2ZnX3BhdGgoInNv"
    "dW5kcyIpLAogICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpLAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIp"
    "LAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAgICAgICBjZmdfcGF0aCgiYmFja3VwcyIpLAogICAg"
    "ICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0"
    "cyIsCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVt"
    "cHR5IEpTT05MIGZpbGVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZuYW1lIGlu"
    "ICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAgICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpz"
    "b25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygp"
    "OgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5h"
    "bWUgaW4gKCJzbF9zY2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3Qg"
    "ZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgo"
    "InNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAg"
    "IGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGgg"
    "PSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShz"
    "dGF0ZV9wYXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdl"
    "cyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYt"
    "OCIKICAgICAgICApCgogICAgIyBMZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxl"
    "cwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7"
    "CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25f"
    "Y291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3Rp"
    "dmUiOiBOb25lLAogICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIsCiAgICB9CiAgICBwYXRoLndyaXRlX3RleHQoanNv"
    "bi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKZGVmIF9taWdyYXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIK"
    "ICAgIElmIG9sZCBEOlxcQUlcXE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdyYXRlIGZpbGVzIHRvIG5l"
    "dyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIKICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2ZSB0byBtb2RlbCBwYXRoCiAgICBtb2Rl"
    "bF9wYXRoID0gUGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYgbm90IG1vZGVsX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJu"
    "CiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFyZW50IC8gZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToK"
    "ICAgICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJtZW1vcmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJtZW1vcmllcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAgICAgY2ZnX3Bh"
    "dGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFza3MuanNvbmwiLCAgICAgICAgICAgICAgIGNmZ19w"
    "YXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInN0YXRlLmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gImluZGV4Lmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgi"
    "bWVtb3JpZXMiKSAvICJpbmRleC5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wi"
    "KSAvICJzbF9zY2Fucy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29ubCIsICAgICAgICAgY2ZnX3BhdGgoInNsIikgLyAi"
    "c2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsi"
    "dG9rZW4iXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJjb25maWciIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBQYXRoKENGR1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291"
    "bmRzIiAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjZmdf"
    "cGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIpLAogICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAg"
    "ICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2Rp"
    "cihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIo"
    "c3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICMgTWlncmF0ZSBmYWNl"
    "IGltYWdlcwogICAgb2xkX2ZhY2VzID0gb2xkX3Jvb3QgLyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2Zh"
    "Y2VzLmV4aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2VzLmdsb2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19mYWNlcyAvIGlt"
    "Zy5uYW1lCiAgICAgICAgICAgIGlmIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHNo"
    "dXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoaW1nKSwgc3RyKGRzdCkpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRh"
    "dGV0aW1lLm5vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0"
    "ZXRpbWVdOgogICAgaWYgbm90IHZhbHVlOgogICAgICAgIHJldHVybiBOb25lCiAgICB2YWx1ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBp"
    "ZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5m"
    "bz10aW1lem9uZS51dGMpCiAgICAgICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "IHJldHVybiBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBsZV0gPSBzZXQoKQoKCmRlZiBfbG9jYWxfdHppbmZvKCk6CiAg"
    "ICByZXR1cm4gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICBy"
    "ZXR1cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkKCgpkZWYgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0"
    "OiBzdHIgPSAiIik6CiAgICBpZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3QgaXNpbnN0YW5jZShkdF92YWx1ZSwg"
    "ZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9sb2NhbF90emluZm8oKQogICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5v"
    "bmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLnJlcGxhY2UodHppbmZvPWxvY2FsX3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0"
    "KQogICAgICAgIGlmIGtleSBub3QgaW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5l"
    "cmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAg"
    "ICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3JtYWxpemVkID0gZHRfdmFsdWUuYXN0aW1lem9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIo"
    "ZHRfdmFsdWUudHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIsIGNvbnRleHQsIGR0X3R6X25hbWUpCiAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JN"
    "QUxJWkFUSU9OX0xPR0dFRCBhbmQgZHRfdHpfbmFtZSBub3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAg"
    "ICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmcm9tIHtkdF90el9uYW1lfSB0byBsb2NhbCB0aW1l"
    "em9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xP"
    "R0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2VfaXNvX2Zvcl9jb21wYXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6"
    "CiAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tf"
    "ZHVlX3NvcnRfa2V5KHRhc2s6IGRpY3QpOgogICAgZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9yICh0"
    "YXNrIG9yIHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICgxLCBkYXRldGlt"
    "ZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkKICAgIHJldHVybiAoMCwgZHVlLmFzdGltZXpvbmUodGltZXpvbmUudXRjKSwgKCh0YXNrIG9y"
    "IHt9KS5nZXQoInRleHQiKSBvciAiIikubG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9uKHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9"
    "IG1heCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCByZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJlbSA9IGRpdm1vZChyZW0sIDM2"
    "MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9kKHJlbSwgNjApCiAgICBwYXJ0cyA9IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5"
    "c31kIikKICAgIGlmIGhvdXJzOiAgIHBhcnRzLmFwcGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRzLmFwcGVuZChmInttaW51dGVzfW0i"
    "KQogICAgaWYgbm90IHBhcnRzOiBwYXJ0cy5hcHBlbmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10pCgojIOKUgOKUgCBNT09O"
    "IFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbiBtYXRoIOKAlCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01P"
    "T04gPSBkYXRlKDIwMDAsIDEsIDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAtPiB0dXBsZVtmbG9hdCwg"
    "c3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2ZyYWN0aW9uLCBwaGFzZV9uYW1lLCBpbGx1bWluYXRpb25fcGN0KS4KICAgIHBoYXNl"
    "X2ZyYWN0aW9uOiAwLjAgPSBuZXcgbW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcgbW9vbiBhZ2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDi"
    "gJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwgcGhhc2UuCiAgICAiIiIKICAgIGRheXMgID0gKGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9P"
    "TikuZGF5cwogICAgY3ljbGUgPSBkYXlzICUgX0xVTkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8"
    "IDEuODU6ICAgbmFtZSA9ICJORVcgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVNDRU5UIgogICAgZWxpZiBjeWNs"
    "ZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNsZSA8IDE0Ljc3OiAgbmFtZSA9ICJXQVhJTkcgR0lCQk9VUyIKICAgIGVs"
    "aWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBjeWNsZSA8IDIyLjE1OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAg"
    "IGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAiTEFTVCBRVUFSVEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NF"
    "TlQiCgogICAgIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9vbgogICAgaWxsdW1pbmF0aW9uID0gKDEgLSBt"
    "YXRoLmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkgLyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkKCl9T"
    "VU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25lCl9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTjogT3B0aW9uYWxbaW50XSA9IE5vbmUKX1NVTl9D"
    "QUNIRV9USU1FUzogdHVwbGVbc3RyLCBzdHJdID0gKCIwNjowMCIsICIxODozMCIpCgpkZWYgX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0dXBs"
    "ZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNvbHZlIGxhdGl0dWRlL2xvbmdpdHVkZSBmcm9tIHJ1bnRpbWUgY29uZmlnIHdoZW4gYXZhaWxhYmxl"
    "LgogICAgRmFsbHMgYmFjayB0byB0aW1lem9uZS1kZXJpdmVkIGNvYXJzZSBkZWZhdWx0cy4KICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9u"
    "ZQogICAgdHJ5OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAg"
    "ICAgICBmb3Iga2V5IGluICgibGF0aXR1ZGUiLCAibGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxhdCA9"
    "IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgICAgIGZvciBrZXkgaW4gKCJsb25naXR1ZGUiLCAibG9uIiwgImxuZyIp"
    "OgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAgICAgICBsb24gPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgbGF0ID0gTm9uZQogICAgICAgIGxvbiA9IE5vbmUKCiAgICBub3dfbG9jYWwgPSBkYXRl"
    "dGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHR6X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkKICAgIHR6X29mZnNl"
    "dF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKCiAgICBpZiBsb24gaXMgTm9uZToKICAgICAgICBsb24gPSBtYXgoLTE4MC4w"
    "LCBtaW4oMTgwLjAsIHR6X29mZnNldF9ob3VycyAqIDE1LjApKQoKICAgIGlmIGxhdCBpcyBOb25lOgogICAgICAgIHR6X25hbWUgPSBzdHIobm93X2xvY2Fs"
    "LnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50ID0gYW55KHRva2VuIGluIHR6X25hbWUgZm9yIHRva2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lm"
    "aWMvQXVja2xhbmQiLCAiQW1lcmljYS9TYW50aWFnbyIpKQogICAgICAgIGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0g"
    "bWF4KC02Ni4wLCBtaW4oNjYuMCwgbGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgbG9uKSkKICAgIHJldHVybiBsYXQsIGxvbgoKZGVm"
    "IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9jYWxfZGF5OiBkYXRlLCBsYXRpdHVkZTogZmxvYXQsIGxvbmdpdHVkZTogZmxvYXQsIHN1bnJpc2U6IGJv"
    "b2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEtc3R5bGUgc3VucmlzZS9zdW5zZXQgc29sdmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJv"
    "bSBtaWRuaWdodC4iIiIKICAgIG4gPSBsb2NhbF9kYXkudGltZXR1cGxlKCkudG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0"
    "ID0gbiArICgoNiAtIGxuZ19ob3VyKSAvIDI0LjApIGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxuZ19ob3VyKSAvIDI0LjApCgogICAgTSA9ICgwLjk4"
    "NTYgKiB0KSAtIDMuMjg5CiAgICBMID0gTSArICgxLjkxNiAqIG1hdGguc2luKG1hdGgucmFkaWFucyhNKSkpICsgKDAuMDIwICogbWF0aC5zaW4obWF0aC5y"
    "YWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9IEwgJSAzNjAuMAoKICAgIFJBID0gbWF0aC5kZWdyZWVzKG1hdGguYXRhbigwLjkxNzY0ICogbWF0"
    "aC50YW4obWF0aC5yYWRpYW5zKEwpKSkpCiAgICBSQSA9IFJBICUgMzYwLjAKICAgIExfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihMIC8gOTAuMCkpICogOTAu"
    "MAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihSQSAvIDkwLjApKSAqIDkwLjAKICAgIFJBID0gKFJBICsgKExfcXVhZHJhbnQgLSBSQV9xdWFkcmFu"
    "dCkpIC8gMTUuMAoKICAgIHNpbl9kZWMgPSAwLjM5NzgyICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGgu"
    "YXNpbihzaW5fZGVjKSkKCiAgICB6ZW5pdGggPSA5MC44MzMKICAgIGNvc19oID0gKG1hdGguY29zKG1hdGgucmFkaWFucyh6ZW5pdGgpKSAtIChzaW5fZGVj"
    "ICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpCiAgICBp"
    "ZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBpZiBzdW5yaXNlOgogICAgICAgIEggPSAzNjAuMCAtIG1h"
    "dGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAgZWxzZToKICAgICAgICBIID0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89"
    "IDE1LjAKCiAgICBUID0gSCArIFJBIC0gKDAuMDY1NzEgKiB0KSAtIDYuNjIyCiAgICBVVCA9IChUIC0gbG5nX2hvdXIpICUgMjQuMAoKICAgIGxvY2FsX29m"
    "ZnNldF9ob3VycyA9IChkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLyAz"
    "NjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBsb2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAgcmV0dXJuIGxvY2FsX2hvdXIgKiA2MC4wCgpkZWYg"
    "X2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKG1pbnV0ZXNfZnJvbV9taWRuaWdodDogT3B0aW9uYWxbZmxvYXRdKSAtPiBzdHI6CiAgICBpZiBtaW51dGVzX2Zy"
    "b21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1cm4gIi0tOi0tIgogICAgbWlucyA9IGludChyb3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAl"
    "ICgyNCAqIDYwKQogICAgaGgsIG1tID0gZGl2bW9kKG1pbnMsIDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRl"
    "PW1tLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4gdHVwbGVbc3RyLCBzdHJdOgog"
    "ICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJpc2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBkYXRlICsgdGltZXpvbmUgYW5kIG9wdGlvbmFsCiAgICBydW50"
    "aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2YWlsYWJsZS4KICAgIENhY2hlZCBwZXIgbG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0"
    "LgogICAgIiIiCiAgICBnbG9iYWwgX1NVTl9DQUNIRV9EQVRFLCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3df"
    "bG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRhdGUoKQogICAgdHpfb2Zmc2V0X21pbiA9IGludCgo"
    "bm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FDSEVfREFURSA9PSB0"
    "b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID09IHR6X29mZnNldF9taW46CiAgICAgICAgcmV0dXJuIF9TVU5fQ0FDSEVfVElNRVMKCiAgICB0"
    "cnk6CiAgICAgICAgbGF0LCBsb24gPSBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpCiAgICAgICAgc3VucmlzZV9taW4gPSBfY2FsY19zb2xhcl9ldmVu"
    "dF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1UcnVlKQogICAgICAgIHN1bnNldF9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRv"
    "ZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1GYWxzZSkKICAgICAgICBpZiBzdW5yaXNlX21pbiBpcyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAg"
    "ICAgICAgcmFpc2UgVmFsdWVFcnJvcigiU29sYXIgZXZlbnQgdW5hdmFpbGFibGUgZm9yIHJlc29sdmVkIGNvb3JkaW5hdGVzIikKICAgICAgICB0aW1lcyA9"
    "IChfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3VucmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3Vuc2V0X21pbikpCiAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIxODozMCIpCgogICAgX1NVTl9DQUNIRV9EQVRFID0gdG9kYXkKICAgIF9TVU5fQ0FDSEVf"
    "VFpfT0ZGU0VUX01JTiA9IHR6X29mZnNldF9taW4KICAgIF9TVU5fQ0FDSEVfVElNRVMgPSB0aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBWQU1Q"
    "SVJFIFNUQVRFIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBUaW1lLW9mLWRheSBiZWhhdmlvcmFsIHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19FTkFCTEVEPVRydWUuCiMgSW5qZWN0ZWQgaW50byBz"
    "eXN0ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRpb24gY2FsbC4KClZBTVBJUkVfU1RBVEVTOiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAiV0lUQ0hJTkcg"
    "SE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjog"
    "ICAgIHsiaG91cnMiOiB7MSwyLDN9LCAgICAgICAgImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5H"
    "Ijp7ImhvdXJzIjogezQsNX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6IDAuN30sCiAgICAiRE9STUFOVCI6ICAgICAgICB7"
    "ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuMn0sCiAgICAiUkVTVExFU1MgU0xFRVAiOiB7Imhv"
    "dXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuM30sCiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJz"
    "IjogezE2LDE3fSwgICAgICAgICJjb2xvciI6IENfR09MRF9ESU0sICAgICJwb3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7ImhvdXJzIjog"
    "ezE4LDE5LDIwLDIxfSwgICJjb2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAiSFVOVElORyI6ICAgICAgICB7ImhvdXJzIjogezIy"
    "LDIzfSwgICAgICAgICJjb2xvciI6IENfQ1JJTVNPTiwgICAgICJwb3dlciI6IDEuMH0sCn0KCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgpIC0+IHN0cjoKICAg"
    "ICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5o"
    "b3VyCiAgICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBpbiBWQU1QSVJFX1NUQVRFUy5pdGVtcygpOgogICAgICAgIGlmIGggaW4gZGF0YVsiaG91cnMiXToKICAg"
    "ICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJldHVybiAiRE9STUFOVCIKCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzdGF0ZTogc3RyKSAt"
    "PiBzdHI6CiAgICByZXR1cm4gVkFNUElSRV9TVEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9n"
    "cmVldGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENISU5HIEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25s"
    "aW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1"
    "c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJTkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2"
    "ZSBhbmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGEgbG93"
    "LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5"
    "IGlkbGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwKICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWlu"
    "ZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0aXZl"
    "IGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Np"
    "bmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJv"
    "dmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJBSV9TVEFURV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92"
    "aWRlZC5rZXlzKCkpID09IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBkaWN0W3N0ciwgc3RyXSA9IHt9CiAgICAgICAgZm9y"
    "IGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6CiAgICAgICAgICAgIHZhbCA9IHByb3ZpZGVkLmdldChrZXkpCiAgICAgICAgICAgIGlmIG5vdCBpc2lu"
    "c3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAg"
    "ICAgICAgICAgY2xlYW5ba2V5XSA9ICIgIi5qb2luKHZhbC5zdHJpcCgpLnNwbGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICByZXR1cm4gX25ldXRy"
    "YWxfc3RhdGVfZ3JlZXRpbmdzKCkKCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBz"
    "dGF0ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5l"
    "cmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgIHJldHVy"
    "biAiIgoKICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgcGhhc2UsIG1vb25fbmFtZSwgaWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBu"
    "b3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQoKICAgIHN0YXRlX2ZsYXZvcnMgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICBmbGF2"
    "b3IgPSBzdGF0ZV9mbGF2b3JzLmdldChzdGF0ZSwgIiIpCgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4i"
    "CiAgICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYiTW9vbjoge21vb25fbmFtZX0gKHtpbGx1bX0lIGlsbHVt"
    "aW5hdGVkKS5cbiIKICAgICAgICBmIlJlc3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5jZSB0aGVzZSBicmFja2V0"
    "cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUHJvY2VkdXJhbCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNv"
    "dW5kIHByb2ZpbGVzLgojIE5vIGV4dGVybmFsIGF1ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBi"
    "dWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sgKHN1cHBvcnRzIFdBViBhbmQgTVAzKS4KCl9T"
    "QU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0"
    "aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJl"
    "cSwgdCkgPj0gMCBlbHNlIC0xLjAKCmRlZiBfc2F3dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVx"
    "ICogdCkgJSAxLjApIC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19yOiBmbG9hdCwKICAgICAgICAgZnJlcTog"
    "ZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAoc2luZV9yICogX3NpbmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzcXVhcmVfciAqIF9z"
    "cXVhcmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAqIF9zYXd0b290aChmcmVxLCB0KSkKCmRlZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50"
    "LAogICAgICAgICAgICAgIGF0dGFja19mcmFjOiBmbG9hdCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykgLT4gZmxv"
    "YXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBvcyA9IGkgLyBtYXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRh"
    "Y2tfZnJhYzoKICAgICAgICByZXR1cm4gcG9zIC8gYXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMpOgogICAgICAgIHJldHVy"
    "biAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAKCmRlZiBfd3JpdGVfd2F2KHBhdGg6IFBhdGgsIGF1ZGlvOiBsaXN0W2ludF0pIC0+"
    "IE5vbmU6CiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3"
    "IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwgMiwgX1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZv"
    "ciBzIGluIGF1ZGlvOgogICAgICAgICAgICBmLndyaXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50"
    "OgogICAgcmV0dXJuIG1heCgtMzI3NjcsIG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBNT1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVzCiMgVHdvIG5vdGVzOiByb290IOKGkiBtaW5vciB0"
    "aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhlZHJhbCByZXNvbmFuY2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJlbGwg"
    "4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAgIFNvdW5kcyBsaWtlIGEgc2luZ2xlIHJlc29uYW50"
    "IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQg"
    "Zmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45KSwgICMgRiM0IOKAlCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFp"
    "bgogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBs"
    "ZW5ndGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICAjIFB1cmUg"
    "c2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3CiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC43CiAgICAgICAgICAg"
    "ICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZvciByaWNobmVzcwogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAg"
    "ICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4wLCB0KSAqIDAuMDUKICAgICAgICAgICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGll"
    "cyBzbG93bHkKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNlX2ZyYWM9MC43KQogICAgICAg"
    "ICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBm"
    "b3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBh"
    "dWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1p"
    "bm9yIGNob3JkIHJlc29sdXRpb24KIyBUaHJlZSBub3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8OpYW5jZSBiZWdp"
    "bm5pbmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwKHBhdGg6"
    "IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2aW5nIHVwd2FyZCDigJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5uaW5nLgog"
    "ICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFsIG5vdGUgaGVsZCBhbmQgZmFkZWQpLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoMjIw"
    "LjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYxLjYzLCAwLjI1KSwgICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBF"
    "NCAoZmlmdGgpCiAgICAgICAgKDQ0MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChm"
    "cmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGlzX2Zp"
    "bmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNgogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAg"
    "ICAgICAgICAgaWYgaXNfZmluYWw6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2Vf"
    "ZnJhYz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJl"
    "bGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40NSkpCiAgICAgICAgaWYgbm90IGlzX2ZpbmFs"
    "OgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNSkpOgogICAgICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAg"
    "ICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExF"
    "IENISU1FIOKAlCBzaW5nbGUgbG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxsLiBTaWduYWxzIHVuc29saWNpdGVkIHRy"
    "YW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0"
    "aDogUGF0aCkgLT4gTm9uZToKICAgICIiIlNpbmdsZSBzb2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2VuY2UgaW4gdGhlIGRhcmsuIiIi"
    "CiAgICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBsZW5ndGggPSAxLjIKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlv"
    "ID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQp"
    "ICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tf"
    "ZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuMykpCiAgICBfd3JpdGVfd2F2"
    "KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9u"
    "ZSAodGhlIGRldmlsJ3MgaW50ZXJ2YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVhbC4KIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAg"
    "ICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIzICsgRjQgcGxheWVkIHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2En"
    "LiBCcmllZiBhbmQgaGFyc2ggY29tcGFyZWQgdG8gaGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVx"
    "X2IgPSAzNDkuMjMgICMgRjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBsZW5ndGggPSAwLjQKICAgIHRvdGFsID0gaW50KF9T"
    "QU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQgY3JlYXRlcyBkaXNzb25hbmNlCiAgICAgICAgdmFsID0gKF9zaW5lKGZy"
    "ZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAgICBfc3F1YXJlKGZyZXFfYiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAy"
    "LjAsIHQpICogMC4xKQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAg"
    "ICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTSFVURE9XTiDigJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ug"
    "b2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRyYXdzLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24ocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKG"
    "kiBDNCDihpIgQTMuIFByZXNlbmNlIHdpdGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAj"
    "IEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAjIEM0CiAgICAgICAgKDIyMC4wLCAgMC44KSwgICAj"
    "IEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVz"
    "KToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0"
    "ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDMsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0gbGVuKG5vdGVzKS0xIGVsc2UgMC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1w"
    "KHZhbCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBw"
    "ZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdldF9zb3VuZF9wYXRoKG5hbWU6IHN0cikgLT4g"
    "UGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X3tuYW1lfS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygp"
    "IC0+IE5vbmU6CiAgICAiIiJHZW5lcmF0ZSBhbnkgbWlzc2luZyBzb3VuZCBXQVYgZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAg"
    "ICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVw"
    "IjogIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZSwKICAgICAgICAiZXJyb3Ii"
    "OiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93biwKICAgIH0KICAgIGZv"
    "ciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5pdGVtcygpOgogICAgICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBw"
    "YXRoLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU09VTkRdW1dBUk5dIEZhaWxlZCB0byBnZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3Vu"
    "ZChuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBsYXkgYSBuYW1lZCBzb3VuZCBub24tYmxvY2tpbmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIg"
    "Zmlyc3QgKGNyb3NzLXBsYXRmb3JtLCBXQVYgKyBNUDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgogICAgRmFsbHMgYmFjayB0"
    "byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBub3QgQ0ZHWyJzZXR0aW5ncyJdLmdldCgic291bmRfZW5hYmxl"
    "ZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICByZXR1cm4KCiAgICBpZiBQWUdBTUVfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkp"
    "CiAgICAgICAgICAgIHNvdW5kLnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5QbGF5U291bmQoc3RyKHBhdGgpLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJTEVOQU1FIHwgd2luc291bmQuU05EX0FTWU5DKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgdHJ5OgogICAgICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgcGFzcwoKIyDilIDilIAgREVTS1RPUCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBib29sOgogICAgIiIiCiAgICBDcmVhdGUgYSBkZXNrdG9wIHNo"
    "b3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgogICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4K"
    "ICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgogICAgICAgIHJldHVybiBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAv"
    "ICJEZXNrdG9wIgogICAgICAgIHNob3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUg"
    "YXMgcHl0aG9uIGJ1dCBubyBjb25zb2xlIHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgIGlmIHB5dGhvbncu"
    "bmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAg"
    "IGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0g"
    "UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxsID0gd2luMzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAg"
    "ICBzYyA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzaG9ydGN1dF9wYXRoKSkKICAgICAgICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQog"
    "ICAgICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZicie2RlY2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRoLnBh"
    "cmVudCkKICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKCiAgICAgICAgIyBVc2UgbmV1dHJhbCBmYWNl"
    "IGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikgLyBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmci"
    "CiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICAjIFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCU"
    "IHNraXAgaWNvbiBpZiBubyAuaWNvCiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICBwcmludChmIltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKICAgICAgICBy"
    "ZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHJlYWRfanNvbmwocGF0aDogUGF0aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQg"
    "YSBKU09OTCBmaWxlLiBSZXR1cm5zIGxpc3Qgb2YgZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAgICBpZiBub3QgcmF3OgogICAg"
    "ICAgIHJldHVybiBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRhdGEgPSBqc29uLmxvYWRzKHJhdykK"
    "ICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEgaWYgaXNpbnN0YW5jZSh4LCBkaWN0KV0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAgICBmb3IgbGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkK"
    "ICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkK"
    "ICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pzb25sKHBhdGg6IFBhdGgsIG9iajogZGljdCkgLT4g"
    "Tm9uZToKICAgICIiIkFwcGVuZCBvbmUgcmVjb3JkIHRvIGEgSlNPTkwgZmlsZS4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhp"
    "c3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMob2Jq"
    "LCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikKCmRlZiB3cml0ZV9qc29ubChwYXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgog"
    "ICAgIiIiT3ZlcndyaXRlIGEgSlNPTkwgZmlsZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVl"
    "LCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZvciByIGluIHJlY29yZHM6"
    "CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkg"
    "SEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0"
    "aGUiLCJhbmQiLCJ0aGF0Iiwid2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwid2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndv"
    "dWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQiLCJsaWtlIiwiYmVjYXVzZSIsIndoaWxlIiwiY291"
    "bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIsImRvZXMiLCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIs"
    "Im9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4iLCJhbHNvIiwic29tZSIsIm1vcmUiLCJsZXNzIiwib25seSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIs"
    "InNoYWxsIiwKICAgICJhZ2FpbiIsInZlcnkiLCJtdWNoIiwicmVhbGx5IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxs"
    "IiwidG9sZCIsImlkZWEiLCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwKfQoKZGVmIGV4dHJhY3Rfa2V5d29yZHMo"
    "dGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxpc3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2VyKCkuc3RyaXAoIiAuLCE/OzonXCIoKVtde30i"
    "KSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQoKSwgW10KICAgIGZvciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4o"
    "dCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JEUyBvciB0LmlzZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgog"
    "ICAgICAgICAgICBzZWVuLmFkZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAgaWYgbGVuKHJlc3VsdCkgPj0gbGltaXQ6CiAgICAg"
    "ICAgICAgIGJyZWFrCiAgICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0OiBzdHIsIGFzc2lzdGFudF90ZXh0OiBzdHIg"
    "PSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkubG93ZXIoKQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIs"
    "ImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4ZWQiLCJyZXNvbHZlZCIsInNvbHV0aW9uIiwid29y"
    "a2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJyZXNvbHV0aW9uIgogICAgICAgIHJldHVybiAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGlu"
    "ICgicmVtaW5kIiwidGltZXIiLCJhbGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImlk"
    "ZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRlYSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHgg"
    "aW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIpKToKICAgICAgICByZXR1cm4gInByZWZlcmVuY2UiCiAgICByZXR1cm4g"
    "ImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1MgMSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lkZ2V0LCBN"
    "b29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1waXJlU3RhdGVTdHJpcCwgQ29sbGFwc2libGVCbG9j"
    "aykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1Mg"
    "MjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRlZmlu"
    "ZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdp"
    "ZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJj"
    "bGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29uV2lkZ2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVt"
    "b3Rpb25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdldCAgICAgICAgIOKAlCBmYWNl"
    "IGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBWYW1waXJlU3RhdGVTdHJpcCAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVz"
    "IGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRvZ2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJk"
    "d2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhv"
    "cml6b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3At"
    "cmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMgdmFsdWUgYXBw"
    "cm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAg"
    "c2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAg"
    "Y29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBz"
    "ZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAg"
    "c2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAgc2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNl"
    "bGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYuc2V0TWF4aW11bUhlaWdodCg3"
    "MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBzZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZh"
    "aWxhYmxlCiAgICAgICAgaWYgbm90IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5Ogog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9"
    "e3NlbGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2"
    "YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQo"
    "c2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhp"
    "bnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAg"
    "cC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVj"
    "dCgwLCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRG"
    "b250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAg"
    "ICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBw"
    "LnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgog"
    "ICAgICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAg"
    "IHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAg"
    "ICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFs"
    "ID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93"
    "IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZy"
    "YWMgPiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcsIGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQog"
    "ICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgx"
    "LCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAg"
    "ICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUgdXNh"
    "Z2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2"
    "ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJl"
    "bnQpCiAgICAgICAgc2VsZi5fZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAgICAgICBpZiBub3QgUFNVVElM"
    "X09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZh"
    "bHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJz"
    "dHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBl"
    "cmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwog"
    "ICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2Vs"
    "Zi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAu"
    "c2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgp"
    "CiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdU"
    "ZXh0KDYsIDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBy"
    "b3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIi"
    "XQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0g"
    "ZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4xZn0ve3RvdGFsOi4wZn1HQiIK"
    "ICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdo"
    "dC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2"
    "CiAgICAgICAgICAgIGJhcl95ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBw"
    "LmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikp"
    "CiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBp"
    "bnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3Jh"
    "ZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgw"
    "LCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAg"
    "ICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAg"
    "ICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZl"
    "IHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0"
    "KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZp"
    "bGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBz"
    "ZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50"
    "PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2Vs"
    "Zi5jb2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAg"
    "ID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAw"
    "KQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9m"
    "aWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51"
    "cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0"
    "UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgog"
    "ICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAg"
    "ICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAs"
    "IDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAo"
    "ZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVS"
    "KSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAg"
    "IGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAg"
    "ICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAg"
    "ICAgICAgICAgIGZyb20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3Rv"
    "cF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9w"
    "YXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAg"
    "IHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAg"
    "ZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JB"
    "dCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5"
    "IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBw"
    "LnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAq"
    "IDIpCgogICAgICAgICMgTi9BIG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19U"
    "RVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0"
    "LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBl"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIg"
    "aWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFG"
    "b250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpv"
    "bnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBsYWJlbF90ZXh0KQoKICAgICAgICBpZiBw"
    "Y3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3"
    "KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAg"
    "ICAgICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXduIG1vb24gb3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93"
    "LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1"
    "bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hh"
    "ZG93IG9uIHJpZ2h0CgogICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAg"
    "ICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAgICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMg"
    "dG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5nCiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAg"
    "ID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxm"
    "Ll9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAg"
    "ICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAg"
    "ICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9z"
    "dW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwg"
    "c3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAg"
    "ICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9u"
    "IG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3Jv"
    "dW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1f"
    "ZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYu"
    "X25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5k"
    "YXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxm"
    "LnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkK"
    "CiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoK"
    "ICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBl"
    "bihRUGVuKFFDb2xvcihDX1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4aW5nID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAv"
    "IDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAg"
    "ICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAg"
    "ICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGls"
    "bHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9scyBob3cgbXVjaCBv"
    "ZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24g"
    "b2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEw"
    "MC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4wIC0gaWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBz"
    "aGFkb3cgTEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVz"
    "IHRoZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAgICAgICAg"
    "ICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193YXhpbmcgPSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBp"
    "ZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zm"
    "c2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4"
    "IC0gciArIG9mZnNldAoKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRo"
    "ID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0"
    "aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQoc2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJz"
    "ZWN0ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWls"
    "IChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSBy"
    "ICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGlu"
    "ZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0"
    "MCwgNSkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNo"
    "KQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIs"
    "IHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRG"
    "b250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5o"
    "b3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAg"
    "ICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0yID0gcC5mb250TWV0"
    "cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UoaWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSAr"
    "IHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3Vu"
    "cmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAg"
    "ICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNv"
    "bG9yLWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUg"
    "Ym90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJd"
    "XSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAz"
    "MAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBoZWFkZXIuc2V0"
    "Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJv"
    "dHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNl"
    "dENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFM"
    "IFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4"
    "ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJl"
    "bnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNl"
    "dFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQo"
    "bGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAjIFNjcm9sbCBhcmVh"
    "IGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNp"
    "emFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9s"
    "aWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlw"
    "X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkK"
    "ICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAg"
    "ICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAg"
    "ICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAoZW1vdGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6"
    "c2VsZi5fbWF4X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291"
    "bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAg"
    "ICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAg"
    "ICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1v"
    "dGlvbi51cHBlcigpfSAge3RzfSIpCiAgICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZv"
    "bnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5j"
    "b3VudCgpIC0gMSwgY2hpcAogICAgICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigp"
    "CiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAg"
    "ICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5w"
    "bmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJF"
    "RklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFD"
    "RV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhv"
    "bGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBs"
    "aXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBN"
    "b3JnYW5uYV8pCiAgICBfU1RFTV9UT19FTU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAi"
    "Y2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIs"
    "IFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQo"
    "KQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25D"
    "ZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgz"
    "MDAsIHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2NhbiBGYWNlcy8gZGlyZWN0"
    "b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5Lgog"
    "ICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygpOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0g"
    "ZXZlcnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNF"
    "X1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAg"
    "ZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQoc3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIo"
    "aW1nX3BhdGgpKQogICAgICAgICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAg"
    "ICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Ry"
    "YXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0"
    "cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNl"
    "ICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAgIHByaW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcg"
    "bmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1dHJhbCIKICAgICAgICBpZiBm"
    "YWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAg"
    "c2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0"
    "UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQ"
    "aXhtYXAoc2NhbGVkKQogICAgICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNP"
    "Tl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAg"
    "IHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDeWNsZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgY3ljbGUgdmlz"
    "dWFsaXphdGlvbiB3aWRnZXQgKGN1cnJlbnRseSBsdW5hci1waGFzZSBkcml2ZW4pLiIiIgoKCmNsYXNzIFZhbXBpcmVTdGF0ZVN0cmlwKFFXaWRnZXQpOgog"
    "ICAgIiIiCiAgICBGdWxsLXdpZHRoIHN0YXR1cyBiYXIgc2hvd2luZzoKICAgICAgWyDinKYgVkFNUElSRV9TVEFURSAg4oCiICBISDpNTSAg4oCiICDimIAg"
    "U1VOUklTRSAg4pi9IFNVTlNFVCAg4oCiICBNT09OIFBIQVNFICBJTExVTSUgXQogICAgQWx3YXlzIHZpc2libGUsIG5ldmVyIGNvbGxhcHNlcy4KICAgIFVw"
    "ZGF0ZXMgZXZlcnkgbWludXRlIHZpYSBleHRlcm5hbCBRVGltZXIgY2FsbCB0byByZWZyZXNoKCkuCiAgICBDb2xvci1jb2RlZCBieSBjdXJyZW50IHZhbXBp"
    "cmUgc3RhdGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9ICJTVEFURSIKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAg"
    "c2VsZi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgog"
    "ICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAgICAgc2VsZi5faWxsdW0gICAg"
    "ID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBi"
    "b3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBzZXRfbGFiZWwoc2VsZiwgbGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwgb3Ig"
    "IlNUQVRFIikuc3RyaXAoKS51cHBlcigpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAg"
    "ICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQog"
    "ICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEg"
    "YmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFkIGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2Vs"
    "Zi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gZGF0ZXRpbWUu"
    "bm93KCkuYXN0aW1lem9uZSgpLnN0cmZ0aW1lKCIlWCIpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAg"
    "ICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgXywgc2VsZi5fbW9vbl9u"
    "YW1lLCBzZWxmLl9pbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQp"
    "IC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFz"
    "aW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19C"
    "RzIpKQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHNlbGYuX3N0YXRlKQogICAgICAgIHRleHQgPSAoCiAgICAgICAg"
    "ICAgIGYi4pymICB7c2VsZi5fbGFiZWxfcHJlZml4fToge3NlbGYuX3N0YXRlfSAg4oCiICB7c2VsZi5fdGltZV9zdHJ9ICDigKIgICIKICAgICAgICAgICAg"
    "ZiLimIAge3NlbGYuX3N1bnJpc2V9ICAgIOKYvSB7c2VsZi5fc3Vuc2V0fSAg4oCiICAiCiAgICAgICAgICAgIGYie3NlbGYuX21vb25fbmFtZX0gIHtzZWxm"
    "Ll9pbGx1bTouMGZ9JSIKICAgICAgICApCgogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDksIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAg"
    "ICBwLnNldFBlbihRQ29sb3Ioc3RhdGVfY29sb3IpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdHcgPSBmbS5ob3Jpem9udGFsQWR2"
    "YW5jZSh0ZXh0KQogICAgICAgIHAuZHJhd1RleHQoKHcgLSB0dykgLy8gMiwgaCAtIDcsIHRleHQpCgogICAgICAgIHAuZW5kKCkKCgpjbGFzcyBNaW5pQ2Fs"
    "ZW5kYXJXaWRnZXQoUVdpZGdldCk6CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZWFkZXIuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDAsIDAsIDApCiAgICAgICAgc2VsZi5wcmV2X2J0biA9IFFQdXNoQnV0dG9uKCI8PCIpCiAgICAgICAgc2VsZi5uZXh0X2J0biA9IFFQdXNoQnV0dG9uKCI+"
    "PiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZs"
    "YWcuQWxpZ25DZW50ZXIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5wcmV2X2J0biwgc2VsZi5uZXh0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhl"
    "ZFdpZHRoKDM0KQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X0dPTER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdo"
    "dDogYm9sZDsgcGFkZGluZzogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBoZWFk"
    "ZXIuYWRkV2lkZ2V0KHNlbGYucHJldl9idG4pCiAgICAgICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLm1vbnRoX2xibCwgMSkKICAgICAgICBoZWFkZXIuYWRk"
    "V2lkZ2V0KHNlbGYubmV4dF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChoZWFkZXIpCgogICAgICAgIHNlbGYuY2FsZW5kYXIgPSBRQ2FsZW5kYXJX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0R3JpZFZpc2libGUoVHJ1ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFZlcnRpY2FsSGVhZGVy"
    "Rm9ybWF0KFFDYWxlbmRhcldpZGdldC5WZXJ0aWNhbEhlYWRlckZvcm1hdC5Ob1ZlcnRpY2FsSGVhZGVyKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0TmF2"
    "aWdhdGlvbkJhclZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdl"
    "dCBRV2lkZ2V0e3thbHRlcm5hdGUtYmFja2dyb3VuZC1jb2xvcjp7Q19CRzJ9O319ICIKICAgICAgICAgICAgZiJRVG9vbEJ1dHRvbnt7Y29sb3I6e0NfR09M"
    "RH07fX0gIgogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzplbmFibGVke3tiYWNrZ3JvdW5kOntDX0JHMn07IGNvbG9y"
    "OiNmZmZmZmY7ICIKICAgICAgICAgICAgZiJzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjp7Q19DUklNU09OX0RJTX07IHNlbGVjdGlvbi1jb2xvcjp7Q19U"
    "RVhUfTsgZ3JpZGxpbmUtY29sb3I6e0NfQk9SREVSfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmRpc2Fi"
    "bGVke3tjb2xvcjojOGI5NWExO319IgogICAgICAgICkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuY2FsZW5kYXIpCgogICAgICAgIHNlbGYucHJl"
    "dl9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxlbmRhci5zaG93UHJldmlvdXNNb250aCgpKQogICAgICAgIHNlbGYubmV4dF9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxlbmRhci5zaG93TmV4dE1vbnRoKCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5jdXJyZW50UGFnZUNoYW5n"
    "ZWQuY29ubmVjdChzZWxmLl91cGRhdGVfbGFiZWwpCiAgICAgICAgc2VsZi5fdXBkYXRlX2xhYmVsKCkKICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRzKCkK"
    "CiAgICBkZWYgX3VwZGF0ZV9sYWJlbChzZWxmLCAqYXJncyk6CiAgICAgICAgeWVhciA9IHNlbGYuY2FsZW5kYXIueWVhclNob3duKCkKICAgICAgICBtb250"
    "aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0VGV4dChmIntkYXRlKHllYXIsIG1vbnRoLCAxKS5zdHJm"
    "dGltZSgnJUIgJVknKX0iKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfYXBwbHlfZm9ybWF0cyhzZWxmKToKICAgICAgICBiYXNl"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBiYXNlLnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAgc2F0dXJkYXkgPSBRVGV4"
    "dENoYXJGb3JtYXQoKQogICAgICAgIHNhdHVyZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgIHN1bmRheSA9IFFUZXh0Q2hh"
    "ckZvcm1hdCgpCiAgICAgICAgc3VuZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRl"
    "eHRGb3JtYXQoUXQuRGF5T2ZXZWVrLk1vbmRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vl"
    "ay5UdWVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLldlZG5lc2RheSwgYmFzZSkK"
    "ICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UaHVyc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVu"
    "ZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5GcmlkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZv"
    "cm1hdChRdC5EYXlPZldlZWsuU2F0dXJkYXksIHNhdHVyZGF5KQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZX"
    "ZWVrLlN1bmRheSwgc3VuZGF5KQoKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRh"
    "ci5tb250aFNob3duKCkKICAgICAgICBmaXJzdF9kYXkgPSBRRGF0ZSh5ZWFyLCBtb250aCwgMSkKICAgICAgICBmb3IgZGF5IGluIHJhbmdlKDEsIGZpcnN0"
    "X2RheS5kYXlzSW5Nb250aCgpICsgMSk6CiAgICAgICAgICAgIGQgPSBRRGF0ZSh5ZWFyLCBtb250aCwgZGF5KQogICAgICAgICAgICBmbXQgPSBRVGV4dENo"
    "YXJGb3JtYXQoKQogICAgICAgICAgICB3ZWVrZGF5ID0gZC5kYXlPZldlZWsoKQogICAgICAgICAgICBpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TYXR1"
    "cmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICAgICAgZWxpZiB3ZWVrZGF5"
    "ID09IFF0LkRheU9mV2Vlay5TdW5kYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICAgICAgc2VsZi5jYWxlbmRhci5z"
    "ZXREYXRlVGV4dEZvcm1hdChkLCBmbXQpCgogICAgICAgIHRvZGF5X2ZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgdG9kYXlfZm10LnNldEZvcmVn"
    "cm91bmQoUUNvbG9yKCIjNjhkMzlhIikpCiAgICAgICAgdG9kYXlfZm10LnNldEJhY2tncm91bmQoUUNvbG9yKCIjMTYzODI1IikpCiAgICAgICAgdG9kYXlf"
    "Zm10LnNldEZvbnRXZWlnaHQoUUZvbnQuV2VpZ2h0LkJvbGQpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXREYXRlVGV4dEZvcm1hdChRRGF0ZS5jdXJyZW50"
    "RGF0ZSgpLCB0b2RheV9mbXQpCgoKIyDilIDilIAgQ09MTEFQU0lCTEUgQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIENvbGxhcHNpYmxlQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIFdyYXBw"
    "ZXIgdGhhdCBhZGRzIGEgY29sbGFwc2UvZXhwYW5kIHRvZ2dsZSB0byBhbnkgd2lkZ2V0LgogICAgQ29sbGFwc2VzIGhvcml6b250YWxseSAocmlnaHR3YXJk"
    "KSDigJQgaGlkZXMgY29udGVudCwga2VlcHMgaGVhZGVyIHN0cmlwLgogICAgSGVhZGVyIHNob3dzIGxhYmVsLiBUb2dnbGUgYnV0dG9uIG9uIHJpZ2h0IGVk"
    "Z2Ugb2YgaGVhZGVyLgoKICAgIFVzYWdlOgogICAgICAgIGJsb2NrID0gQ29sbGFwc2libGVCbG9jaygi4p2nIEJMT09EIiwgU3BoZXJlV2lkZ2V0KC4uLikp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChibG9jaykKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lk"
    "Z2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAgICAgICByZXNlcnZl"
    "X3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAogICAgICAgIHNlbGYu"
    "X3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0U3BhY2luZygwKQoKICAg"
    "ICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAg"
    "ICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAg"
    "ICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNl"
    "dFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0"
    "dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhs"
    "LmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFp"
    "bi5hZGRXaWRnZXQoc2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRl"
    "KCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2Vs"
    "Zi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2Vs"
    "Zi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUg"
    "Zml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0"
    "aDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3"
    "NzIxNSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAg"
    "ICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBz"
    "ZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50"
    "KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0"
    "cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAg"
    "ICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAg"
    "ICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdh"
    "dWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0"
    "dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50"
    "PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFy"
    "ZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0"
    "ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAg"
    "ICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFt"
    "ZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQo"
    "c3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAg"
    "c2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZF"
    "U1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxm"
    "LmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBzZWxmLmxibF9tb2Rl"
    "bCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYu"
    "ZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSA"
    "IENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xh"
    "YmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgog"
    "ICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3Jh"
    "bSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2Nw"
    "dSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUp"
    "CgogICAgICAgICMg4pSA4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFt"
    "LnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAg"
    "ICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lk"
    "Z2V0KHNlbGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91"
    "dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBz"
    "ZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0"
    "TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBi"
    "YXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAg"
    "IHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVf"
    "bWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91"
    "dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFy"
    "ZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFn"
    "bm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2Vz"
    "OiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAg"
    "ICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJw"
    "aXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMu"
    "YXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAg"
    "ICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAg"
    "ICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUo"
    "KQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxl"
    "IG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFsbCBweW52bWwg"
    "dG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZt"
    "bERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAg"
    "IG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltI"
    "QVJEV0FSRV0gcHludm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1h"
    "eCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRs"
    "ZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwg"
    "PSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChm"
    "IltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBD"
    "YWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgog"
    "ICAgICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNwdV9wZXJjZW50"
    "KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAg"
    "ICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDou"
    "MGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdl"
    "X3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBh"
    "bmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9u"
    "UmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAg"
    "ICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBn"
    "cHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAg"
    "ICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFs"
    "IC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJh"
    "bV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZh"
    "bHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgog"
    "ICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAg"
    "ICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAg"
    "ICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVn"
    "ZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0"
    "Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAg"
    "ICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoK"
    "ICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYs"
    "ICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlm"
    "IHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJl"
    "ZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1"
    "c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRl"
    "eHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAg"
    "ICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBb"
    "XSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRs"
    "eS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRs"
    "ZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JH"
    "QU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2Nh"
    "bFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAg"
    "U3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKA"
    "lCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9u"
    "cyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlv"
    "biBpcyBzdHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJv"
    "cgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMu"
    "QUJDKToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2Vu"
    "ZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYg"
    "aXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAg"
    "IC4uLgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBz"
    "eXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJh"
    "dG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQ"
    "SSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGlu"
    "Zy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBz"
    "eXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoK"
    "ICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAg"
    "ICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJu"
    "ICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21w"
    "dChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIi"
    "KSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAg"
    "ICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBb"
    "ZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAg"
    "ID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcGFydHMu"
    "YXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRz"
    "LmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Np"
    "c3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgog"
    "ICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJh"
    "dGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAgICAgc2Vs"
    "Zi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAg"
    "IHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tl"
    "bml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAg"
    "IGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAg"
    "IHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRv"
    "VG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAg"
    "ICAgIHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAg"
    "ICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxv"
    "d19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1"
    "ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNl"
    "CgogICAgQHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0"
    "ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21w"
    "dDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUx"
    "MiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJh"
    "dG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAg"
    "ICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1bGxf"
    "cHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAg"
    "IyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21w"
    "dAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJw"
    "dCIKICAgICAgICAgICAgKS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rv"
    "a2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRy"
    "dWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMs"
    "CiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9u"
    "ZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwK"
    "ICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFtZXIi"
    "OiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVh"
    "bWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21v"
    "ZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBnZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAg"
    "eWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRh"
    "cHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRK"
    "U09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEg"
    "c2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAi"
    "bG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJo"
    "dHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0g"
    "dXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVu"
    "KHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAog"
    "ICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAg"
    "ICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9u"
    "ZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5r"
    "LgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBp"
    "biBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJt"
    "b2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAg"
    "ICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29k"
    "ZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxm"
    "Ll9iYXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjog"
    "ImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIu"
    "cmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAg"
    "ICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9h"
    "ZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKQogICAgICAg"
    "ICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBq"
    "c29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihM"
    "TE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMp"
    "LgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRI"
    "ICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02"
    "Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikg"
    "LT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3Ry"
    "LAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAg"
    "ICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdl"
    "cy5hcHBlbmQoewogICAgICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50"
    "Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwK"
    "ICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJt"
    "ZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAg"
    "aGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAi"
    "MjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29u"
    "bi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJl"
    "c3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0"
    "Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0g"
    "cmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVm"
    "ZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGlu"
    "ZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAg"
    "ICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRl"
    "eHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJv"
    "cjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5b"
    "RVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRh"
    "cHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0"
    "dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6"
    "CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAg"
    "IGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBz"
    "ZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25l"
    "d190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRl"
    "bnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJd"
    "LCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBz"
    "ZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5z"
    "LAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYt"
    "OCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAgICAi"
    "Q29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50"
    "LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBs"
    "ZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5n"
    "ZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2Rl"
    "KCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAg"
    "ICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVu"
    "ayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAg"
    "IGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAg"
    "IGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAg"
    "ICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQog"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "ICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "LmdldCgiZGVsdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAg"
    "ICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MK"
    "CgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQg"
    "dGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0"
    "aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJv"
    "bGxhbWEiOgogICAgICAgIHJldHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhp"
    "bi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBp"
    "X2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAg"
    "ICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBp"
    "X2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMg"
    "RGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRo"
    "IiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9u"
    "IHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg"
    "4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdp"
    "dGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAg"
    "ICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAi"
    "IiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9"
    "IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3Is"
    "IHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAg"
    "c2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90"
    "b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBj"
    "YW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBk"
    "ZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBb"
    "XQogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAog"
    "ICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAg"
    "IG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAg"
    "ICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3Jl"
    "YWR5LmVtaXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5y"
    "ZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19j"
    "aGFuZ2VkLmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENs"
    "YXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNw"
    "b25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2Ug"
    "dG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRz"
    "IGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRl"
    "cyBpbW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25h"
    "bDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9"
    "IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAg"
    "VkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3Bv"
    "bnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5f"
    "cmVzcG9uc2UgPSByZXNwb25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQg"
    "d2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAg"
    "ICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZv"
    "aWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFy"
    "ZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQg"
    "bGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0g"
    "c2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAg"
    "ICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rv"
    "a2Vucz02LAogICAgICAgICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3"
    "LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0"
    "aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBp"
    "ZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVy"
    "aW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAg"
    "IFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhv"
    "dWdodCB0aHJlYWQKICAgICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5U"
    "SEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRh"
    "Yiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxl"
    "IHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3Vy"
    "cmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3Ry"
    "KQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFu"
    "ZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGlt"
    "cGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2Ug"
    "ZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMg"
    "YWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhp"
    "cyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRp"
    "cmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNz"
    "ZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0"
    "b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1F"
    "fSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19O"
    "QU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFN"
    "RX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0s"
    "IGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewog"
    "ICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBw"
    "cmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVz"
    "aW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5n"
    "IHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBiZWZvcmUgaW50"
    "cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAg"
    "ICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91"
    "ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21w"
    "YXJpc29uLCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9u"
    "IHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2"
    "ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHBy"
    "aXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFy"
    "Z2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBz"
    "dWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2Vs"
    "ZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAg"
    "bW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIg"
    "PSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNl"
    "bGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYg"
    "bWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVs"
    "c2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb250"
    "ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJB"
    "VElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5k"
    "b20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAg"
    "ICAgICAgICAgaWRsZV9zeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3Zh"
    "bXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2lu"
    "c3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAg"
    "ICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAg"
    "ICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3Mg"
    "dGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1"
    "dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAg"
    "ICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwK"
    "ICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0"
    "KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURM"
    "RSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJh"
    "Y2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWdu"
    "YWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29s"
    "KSDigJQgVHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJl"
    "CiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAg"
    "ICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkK"
    "ICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlz"
    "aW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAg"
    "ICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdl"
    "LmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChm"
    "IlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAg"
    "IGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGlu"
    "ZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVl"
    "KQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJPbGxh"
    "bWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVB"
    "ZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4i"
    "KQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgi"
    "QVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5J"
    "TkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2Nv"
    "bXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUg"
    "aW4gY29uZmlnLiIpCiAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCgojIOKUgOKU"
    "gCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0"
    "aHJlYWQuCiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9"
    "IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8g"
    "cmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQu"
    "Y29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQo"
    "c2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJp"
    "cFdpZGdldChWYW1waXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmljIGZvb3RlciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2Vy"
    "IGJsb2NrLiIiIgoKCmNsYXNzIEZhY2VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsYXkgdGltZXIu"
    "CgogICAgUnVsZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElm"
    "IHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2Nr"
    "ZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAg"
    "ICAtIE5ldmVyIGJsb2NrcyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYu"
    "X21pcnJvciAgPSBtaXJyb3IKICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQog"
    "ICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3Rv"
    "X25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAg"
    "ICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAgICAgICBzZWxmLl90"
    "aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBu"
    "ZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRzIGEgbmV3IG1lc3Nh"
    "Z2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAg"
    "c2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24p"
    "CiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBk"
    "ZWYgaXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNTRVMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVj"
    "ay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJn"
    "b29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2ds"
    "ZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoKToKICAgICAg"
    "ICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNl"
    "bGYuX3NlcnZpY2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1r"
    "ZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29k"
    "aW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRo"
    "OiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2VuX3BhdGh9IikK"
    "ICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikK"
    "ICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYg"
    "bm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAg"
    "ICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAg"
    "aWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAg"
    "ICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAg"
    "KQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3Rz"
    "KCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwg"
    "R09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToK"
    "ICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJl"
    "ZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gUmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tl"
    "bi4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGlt"
    "ZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dP"
    "T0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlk"
    "OgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxz"
    "X3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAg"
    "cG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21l"
    "c3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRp"
    "b246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29t"
    "cGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAg"
    "ICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1"
    "Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9B"
    "dXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJs"
    "aXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAg"
    "ICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQog"
    "ICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBs"
    "b2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAgICAgaWYgbG9jYWxf"
    "dHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywg"
    "ImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9j"
    "YWxfdHppbmZvKSwKICAgICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoKICAgICAgICBl"
    "bnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAg"
    "ICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFw"
    "cGVkOgogICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVz"
    "b2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FfS4i"
    "CiAgICAgICAgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxm"
    "LCB0YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUi"
    "KSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3Io"
    "IlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYu"
    "X3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBkdWVfbG9jYWwg"
    "PSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAg"
    "c3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFydF9kdCArIHRpbWVk"
    "ZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9h"
    "ZCA9IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQi"
    "OiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICAgICAi"
    "ZW5kIjogeyJkYXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQog"
    "ICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2FsZW5kYXIgSUQ6IHt0"
    "YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0"
    "OiAiCiAgICAgICAgICAgIGYidGl0bGU9J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGltZT0n"
    "e2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRf"
    "cGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5n"
    "ZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7"
    "fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCku"
    "aW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dD"
    "YWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFi"
    "bGlzaGVkCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAgICBp"
    "ZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAg"
    "YXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29n"
    "bGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxf"
    "bXNnfSB8IEFQSSBib2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0"
    "YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0i"
    "KQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFy"
    "X2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQog"
    "ICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAg"
    "ICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2"
    "ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3By"
    "aW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0"
    "dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05M"
    "WSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJv"
    "dGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2Vydmlj"
    "ZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkgPSB7"
    "CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAg"
    "ICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5n"
    "bGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZXN1bHRzIjogMjUwLAog"
    "ICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAg"
    "ICAgIHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSBOb25lCiAg"
    "ICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAg"
    "ICAgICAgICAgIGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3Bv"
    "bnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAg"
    "ICBpZiBub3QgcGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAg"
    "ICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rva2VuCgogICAgZGVm"
    "IGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJu"
    "IE5vbmUKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCku"
    "ZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBp"
    "X2V4LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAgICAgICAgICAgICAgcmV0"
    "dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAg"
    "ICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fu"
    "bm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoK"
    "ICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRh"
    "cmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3Jl"
    "ZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZHJpdmVf"
    "c2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9s"
    "b2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAg"
    "ICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRv"
    "a2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVk"
    "cy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRo"
    "IHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5v"
    "dCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAg"
    "ICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxm"
    "LmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUg"
    "Y3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAg"
    "Y3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZy"
    "b21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52"
    "YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVf"
    "UkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3Jl"
    "ZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9"
    "IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xv"
    "ZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9T"
    "Q09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAg"
    "ICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAg"
    "ICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBj"
    "bG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJh"
    "aXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNp"
    "c3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4i"
    "LCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93"
    "IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4g"
    "Y3JlZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYu"
    "X2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNlbGYuX2F1dGhl"
    "bnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMp"
    "CiAgICAgICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAg"
    "ICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3Mu"
    "IiwgbGV2ZWw9IklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVy"
    "ZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikK"
    "ICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50"
    "ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290Iikuc3Ry"
    "aXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9p"
    "ZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7"
    "c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQocGFnZV9z"
    "aXplIG9yIDEwMCksIDIwMCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxk"
    "cz0oCiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBh"
    "cmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAg"
    "ICIpIgogICAgICAgICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAgICAg"
    "Zm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1pbWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRl"
    "bVsiaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVf"
    "ZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0"
    "dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBk"
    "ZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAg"
    "ICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAg"
    "IGRvYyA9IHNlbGYuX2RvY3Nfc2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9j"
    "LmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAgICAg"
    "Y2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAg"
    "ICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJl"
    "bGVtZW50cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRSdW4iKQogICAg"
    "ICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250"
    "ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBw"
    "ZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAg"
    "ICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0bGUi"
    "OiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklk"
    "IiksCiAgICAgICAgICAgICJwcmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAg"
    "ICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0"
    "ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZl"
    "aWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAi"
    "cm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAg"
    "IGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5n"
    "b29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAg"
    "ICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAg"
    "ICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Ug"
    "e30KICAgICAgICByZXR1cm4gewogICAgICAgICAgICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZl"
    "X3RpdGxlLAogICAgICAgICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3Vt"
    "ZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAgICAgIndlYlZpZXdMaW5rIjogbWV0"
    "YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAg"
    "ICAgIH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290"
    "Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgogICAgICAgIHNhZmVfcGFyZW50"
    "X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAg"
    "ICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6"
    "IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAg"
    "ICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlm"
    "aWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIGdldF9maWxl"
    "X21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUg"
    "aWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMo"
    "KS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZp"
    "ZXdMaW5rLHBhcmVudHMsc2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAg"
    "ICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAg"
    "ICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1"
    "cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAgIGRl"
    "ZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0"
    "KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyBy"
    "ZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmV4"
    "cG9ydCgKICAgICAgICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAg"
    "ICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJl"
    "cGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAiIikKCiAgICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIp"
    "OgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2Vs"
    "Zi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5l"
    "eGVjdXRlKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFt"
    "aW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5"
    "ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JB"
    "R0UKIwojIFN5c3RlbXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBv"
    "biBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAg"
    "ICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBG"
    "b3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBD"
    "UlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDi"
    "lIDilIAgREVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFj"
    "a2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dz"
    "IGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1l"
    "LCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAg"
    "ICAgICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAg"
    "ICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBz"
    "Y2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIp"
    "LAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3Rh"
    "bGwgcHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0"
    "aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVk"
    "ZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAg"
    "IEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBp"
    "Y2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1"
    "dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgtb2F1dGhs"
    "aWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBp"
    "bnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3JjaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycyIsICAg"
    "ICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVk"
    "IGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICBGYWxzZSwK"
    "ICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkgbmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNz"
    "bWV0aG9kCiAgICBkZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAobWVz"
    "c2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3Ry"
    "aW5ncwogICAgICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIi"
    "CiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAgZm9yIHBrZ19u"
    "YW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBv"
    "cnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxzZSAi"
    "b3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtz"
    "dGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAgICAgICAgICAg"
    "Y3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hl"
    "Y2tfb2xsYW1hKGNscykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIiCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAg"
    "ICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVk"
    "IGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilIAgTUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRs"
    "ZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAg"
    "ICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVt"
    "b3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRl"
    "eC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5d29y"
    "ZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250"
    "ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoIm1lbW9y"
    "aWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAv"
    "ICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAg"
    "PSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxm"
    "LnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVy"
    "biBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICAp"
    "CgogICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBlcnNvbmFfbmFtZSI6ICAgICAg"
    "ICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tfdmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lv"
    "bl9jb3VudCI6ICAgICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3No"
    "dXRkb3duIjogICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgInRvdGFs"
    "X21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxf"
    "bmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg"
    "4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6"
    "IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlk"
    "LnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjog"
    "c2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAg"
    "ICAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29u"
    "bChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbWl0"
    "OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDi"
    "lIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgYXBwZW5kX21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50"
    "X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFu"
    "dF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0"
    "YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxm"
    "Ll9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNv"
    "cmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYi"
    "bWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0"
    "eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5"
    "IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0"
    "YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAg"
    "InRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAg"
    "ICAgICAgICAgImRyZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAogICAgICAg"
    "IH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pz"
    "b25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBz"
    "dHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAg"
    "ICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sg"
    "dG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVt"
    "b3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVy"
    "bXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1v"
    "cmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0"
    "aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIs"
    "ICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdl"
    "dCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVy"
    "bXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRl"
    "bS5nZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAg"
    "ICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0"
    "ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06"
    "IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAg"
    "ICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJz"
    "ZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhz"
    "ZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5n"
    "IGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRo"
    "ZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAg"
    "ICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAg"
    "ICB0b3RhbCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0"
    "KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAg"
    "IHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNd"
    "IikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNhbmRpZGF0ZTog"
    "ZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5n"
    "ZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkK"
    "ICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJl"
    "dHVybiBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAg"
    "IHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAg"
    "a2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBl"
    "XQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgi"
    "bHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBw"
    "ZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUi"
    "KQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3"
    "b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxp"
    "Y2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBp"
    "ZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICBy"
    "ZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAg"
    "ICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlw"
    "KCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVj"
    "b3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4r"
    "KSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJp"
    "cCgpWzo2MF19IgogICAgICAgICAgICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAg"
    "ICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgp"
    "IG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0"
    "aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRf"
    "dHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklk"
    "ZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9u"
    "IE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwg"
    "dXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJp"
    "cCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAg"
    "ICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYi"
    "UmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9"
    "IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBp"
    "ZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJw"
    "cmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKU"
    "gCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRv"
    "LXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9Z"
    "WVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9u"
    "ZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAg"
    "IHRoZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9IDEwICAgIyBt"
    "aW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAg"
    "IHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQg"
    "ICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBk"
    "YXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJu"
    "YWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50"
    "OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "bWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGlt"
    "ZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50"
    "IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBs"
    "aXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6ICJ1"
    "c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsi"
    "cm9sZSJdLCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9s"
    "ZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAg"
    "ICAgICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJl"
    "dHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikg"
    "LT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92"
    "ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRl"
    "eC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNz"
    "aW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNl"
    "bGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3Rpbmcg"
    "PSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoK"
    "ICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBp"
    "ZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdv"
    "cmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMg"
    "aWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5z"
    "cGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBl"
    "bnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lk"
    "LAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAg"
    "ICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAg"
    "ICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50"
    "cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBk"
    "YXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgo"
    "aW5kZXgpCgogICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwg"
    "bmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Np"
    "b25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMg"
    "YSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0"
    "LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVu"
    "dGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYi"
    "e3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdl"
    "cyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VS"
    "TkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNv"
    "bnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgICAgICAg"
    "IyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAg"
    "ICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIi"
    "KVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0"
    "c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxp"
    "bmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAg"
    "IEBwcm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVk"
    "X2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAg"
    "IiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9p"
    "bmRleCgpCiAgICAgICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0"
    "ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAg"
    "ICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRl"
    "eChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMo"
    "aW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBl"
    "cnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6"
    "CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNl"
    "X2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBG"
    "SVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVz"
    "IGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAg"
    "c2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmlyb25tZW50"
    "OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1"
    "dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7"
    "CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6"
    "ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJlbnZpcm9ubWVudCI6ICAg"
    "ZW52aXJvbm1lbnQsCiAgICAgICAgICAgICJsYW5ndWFnZSI6ICAgICAgbGFuZ3VhZ2UsCiAgICAgICAgICAgICJyZWZlcmVuY2Vfa2V5IjogcmVmZXJlbmNl"
    "X2tleSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiZnVsbF9ydWxlIjogICAgIGZ1bGxfcnVsZSwKICAgICAg"
    "ICAgICAgInJlc29sdXRpb24iOiAgICByZXNvbHV0aW9uLAogICAgICAgICAgICAibGluayI6ICAgICAgICAgIGxpbmssCiAgICAgICAgICAgICJ0YWdzIjog"
    "ICAgICAgICAgdGFncyBvciBbXSwKICAgICAgICB9CiAgICAgICAgaWYgbm90IHNlbGYuX2lzX2R1cGxpY2F0ZShyZWZlcmVuY2Vfa2V5KToKICAgICAgICAg"
    "ICAgYXBwZW5kX2pzb25sKHNlbGYuX3BhdGgsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIHNlYXJjaChzZWxmLCBxdWVyeTogc3Ry"
    "ID0gIiIsIGVudmlyb25tZW50OiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgbGFuZ3VhZ2U6IHN0ciA9ICIiKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJl"
    "Y29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgcmVzdWx0cyA9IFtdCiAgICAgICAgcSA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICBmb3Ig"
    "ciBpbiByZWNvcmRzOgogICAgICAgICAgICBpZiBlbnZpcm9ubWVudCBhbmQgci5nZXQoImVudmlyb25tZW50IiwiIikubG93ZXIoKSAhPSBlbnZpcm9ubWVu"
    "dC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbGFuZ3VhZ2UgYW5kIHIuZ2V0KCJsYW5ndWFnZSIsIiIpLmxvd2Vy"
    "KCkgIT0gbGFuZ3VhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIHE6CiAgICAgICAgICAgICAgICBoYXlzdGFj"
    "ayA9ICIgIi5qb2luKFsKICAgICAgICAgICAgICAgICAgICByLmdldCgic3VtbWFyeSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJmdWxsX3J1"
    "bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIpLAogICAgICAgICAgICAgICAgICAgICIgIi5qb2luKHIuZ2V0"
    "KCJ0YWdzIixbXSkpLAogICAgICAgICAgICAgICAgXSkubG93ZXIoKQogICAgICAgICAgICAgICAgaWYgcSBub3QgaW4gaGF5c3RhY2s6CiAgICAgICAgICAg"
    "ICAgICAgICAgY29udGludWUKICAgICAgICAgICAgcmVzdWx0cy5hcHBlbmQocikKICAgICAgICByZXR1cm4gcmVzdWx0cwoKICAgIGRlZiBnZXRfYWxsKHNl"
    "bGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKCiAgICBkZWYgZGVsZXRlKHNlbGYsIHJlY29yZF9pZDog"
    "c3RyKSAtPiBib29sOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgZmlsdGVyZWQgPSBbciBmb3IgciBpbiByZWNv"
    "cmRzIGlmIHIuZ2V0KCJpZCIpICE9IHJlY29yZF9pZF0KICAgICAgICBpZiBsZW4oZmlsdGVyZWQpIDwgbGVuKHJlY29yZHMpOgogICAgICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBmaWx0ZXJlZCkKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgYnVpbGRf"
    "Y29udGV4dF9mb3JfbGFuZ3VhZ2Uoc2VsZiwgbGFuZ3VhZ2U6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfY2hhcnM6IGlu"
    "dCA9IDE1MDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIG9mIGFsbCBydWxlcyBmb3IgYSBnaXZlbiBsYW5n"
    "dWFnZS4KICAgICAgICBGb3IgaW5qZWN0aW9uIGludG8gc3lzdGVtIHByb21wdCBiZWZvcmUgY29kZSBzZXNzaW9ucy4KICAgICAgICAiIiIKICAgICAgICBy"
    "ZWNvcmRzID0gc2VsZi5zZWFyY2gobGFuZ3VhZ2U9bGFuZ3VhZ2UpCiAgICAgICAgaWYgbm90IHJlY29yZHM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAg"
    "ICAgICBwYXJ0cyA9IFtmIlt7bGFuZ3VhZ2UudXBwZXIoKX0gUlVMRVMg4oCUIEFQUExZIEJFRk9SRSBXUklUSU5HIENPREVdIl0KICAgICAgICB0b3RhbCA9"
    "IDAKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBlbnRyeSA9IGYi4oCiIHtyLmdldCgncmVmZXJlbmNlX2tleScsJycpfToge3IuZ2V0"
    "KCdmdWxsX3J1bGUnLCcnKX0iCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAg"
    "ICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoZiJbRU5E"
    "IHtsYW5ndWFnZS51cHBlcigpfSBSVUxFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAgZGVmIF9pc19kdXBsaWNhdGUoc2VsZiwg"
    "cmVmZXJlbmNlX2tleTogc3RyKSAtPiBib29sOgogICAgICAgIHJldHVybiBhbnkoCiAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikubG93"
    "ZXIoKSA9PSByZWZlcmVuY2Vfa2V5Lmxvd2VyKCkKICAgICAgICAgICAgZm9yIHIgaW4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICkKCiAgICBk"
    "ZWYgc2VlZF9sc2xfcnVsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTZWVkIHRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgb24gZmly"
    "c3QgcnVuIGlmIHRoZSBEQiBpcyBlbXB0eS4KICAgICAgICBUaGVzZSBhcmUgdGhlIGhhcmQgcnVsZXMgZnJvbSB0aGUgcHJvamVjdCBzdGFuZGluZyBydWxl"
    "cy4KICAgICAgICAiIiIKICAgICAgICBpZiByZWFkX2pzb25sKHNlbGYuX3BhdGgpOgogICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBzZWVkZWQKCiAg"
    "ICAgICAgbHNsX3J1bGVzID0gWwogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVEVSTkFSWSIsCiAgICAgICAgICAgICAiTm8gdGVybmFyeSBvcGVy"
    "YXRvcnMgaW4gTFNMIiwKICAgICAgICAgICAgICJOZXZlciB1c2UgdGhlIHRlcm5hcnkgb3BlcmF0b3IgKD86KSBpbiBMU0wgc2NyaXB0cy4gIgogICAgICAg"
    "ICAgICAgIlVzZSBpZi9lbHNlIGJsb2NrcyBpbnN0ZWFkLiBMU0wgZG9lcyBub3Qgc3VwcG9ydCB0ZXJuYXJ5LiIsCiAgICAgICAgICAgICAiUmVwbGFjZSB3"
    "aXRoIGlmL2Vsc2UgYmxvY2suIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fRk9SRUFDSCIsCiAgICAgICAgICAgICAiTm8gZm9yZWFj"
    "aCBsb29wcyBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBoYXMgbm8gZm9yZWFjaCBsb29wIGNvbnN0cnVjdC4gVXNlIGludGVnZXIgaW5kZXggd2l0aCAi"
    "CiAgICAgICAgICAgICAibGxHZXRMaXN0TGVuZ3RoKCkgYW5kIGEgZm9yIG9yIHdoaWxlIGxvb3AuIiwKICAgICAgICAgICAgICJVc2U6IGZvcihpbnRlZ2Vy"
    "IGk9MDsgaTxsbEdldExpc3RMZW5ndGgobXlMaXN0KTsgaSsrKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0dMT0JBTF9BU1NJR05f"
    "RlJPTV9GVU5DIiwKICAgICAgICAgICAgICJObyBnbG9iYWwgdmFyaWFibGUgYXNzaWdubWVudHMgZnJvbSBmdW5jdGlvbiBjYWxscyIsCiAgICAgICAgICAg"
    "ICAiR2xvYmFsIHZhcmlhYmxlIGluaXRpYWxpemF0aW9uIGluIExTTCBjYW5ub3QgY2FsbCBmdW5jdGlvbnMuICIKICAgICAgICAgICAgICJJbml0aWFsaXpl"
    "IGdsb2JhbHMgd2l0aCBsaXRlcmFsIHZhbHVlcyBvbmx5LiAiCiAgICAgICAgICAgICAiQXNzaWduIGZyb20gZnVuY3Rpb25zIGluc2lkZSBldmVudCBoYW5k"
    "bGVycyBvciBvdGhlciBmdW5jdGlvbnMuIiwKICAgICAgICAgICAgICJNb3ZlIHRoZSBhc3NpZ25tZW50IGludG8gYW4gZXZlbnQgaGFuZGxlciAoc3RhdGVf"
    "ZW50cnksIGV0Yy4pIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVk9JRF9LRVlXT1JEIiwKICAgICAgICAgICAgICJObyB2b2lkIGtl"
    "eXdvcmQgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgZG9lcyBub3QgaGF2ZSBhIHZvaWQga2V5d29yZCBmb3IgZnVuY3Rpb24gcmV0dXJuIHR5cGVzLiAi"
    "CiAgICAgICAgICAgICAiRnVuY3Rpb25zIHRoYXQgcmV0dXJuIG5vdGhpbmcgc2ltcGx5IG9taXQgdGhlIHJldHVybiB0eXBlLiIsCiAgICAgICAgICAgICAi"
    "UmVtb3ZlICd2b2lkJyBmcm9tIGZ1bmN0aW9uIHNpZ25hdHVyZS4gIgogICAgICAgICAgICAgImUuZy4gbXlGdW5jKCkgeyAuLi4gfSBub3Qgdm9pZCBteUZ1"
    "bmMoKSB7IC4uLiB9IiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiQ09NUExFVEVfU0NSSVBUU19PTkxZIiwKICAgICAgICAgICAgICJBbHdh"
    "eXMgcHJvdmlkZSBjb21wbGV0ZSBzY3JpcHRzLCBuZXZlciBwYXJ0aWFsIGVkaXRzIiwKICAgICAgICAgICAgICJXaGVuIHdyaXRpbmcgb3IgZWRpdGluZyBM"
    "U0wgc2NyaXB0cywgYWx3YXlzIG91dHB1dCB0aGUgY29tcGxldGUgIgogICAgICAgICAgICAgInNjcmlwdC4gTmV2ZXIgcHJvdmlkZSBwYXJ0aWFsIHNuaXBw"
    "ZXRzIG9yICdhZGQgdGhpcyBzZWN0aW9uJyAiCiAgICAgICAgICAgICAiaW5zdHJ1Y3Rpb25zLiBUaGUgZnVsbCBzY3JpcHQgbXVzdCBiZSBjb3B5LXBhc3Rl"
    "IHJlYWR5LiIsCiAgICAgICAgICAgICAiV3JpdGUgdGhlIGVudGlyZSBzY3JpcHQgZnJvbSB0b3AgdG8gYm90dG9tLiIsICIiKSwKICAgICAgICBdCgogICAg"
    "ICAgIGZvciBlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rIGluIGxzbF9ydWxlczoKICAgICAgICAgICAgc2Vs"
    "Zi5hZGQoZW52LCBsYW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluaywKICAgICAgICAgICAgICAgICAgICAgdGFncz1bImxz"
    "bCIsICJmb3JiaWRkZW4iLCAic3RhbmRpbmdfcnVsZSJdKQoKCiMg4pSA4pSAIFRBU0sgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgVGFza01hbmFnZXI6CiAgICAiIiIK"
    "ICAgIFRhc2svcmVtaW5kZXIgQ1JVRCBhbmQgZHVlLWV2ZW50IGRldGVjdGlvbi4KCiAgICBGaWxlOiBtZW1vcmllcy90YXNrcy5qc29ubAoKICAgIFRhc2sg"
    "cmVjb3JkIGZpZWxkczoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZHVlX2F0LCBwcmVfdHJpZ2dlciAoMW1pbiBiZWZvcmUpLAogICAgICAgIHRleHQsIHN0"
    "YXR1cyAocGVuZGluZ3x0cmlnZ2VyZWR8c25vb3plZHxjb21wbGV0ZWR8Y2FuY2VsbGVkKSwKICAgICAgICBhY2tub3dsZWRnZWRfYXQsIHJldHJ5X2NvdW50"
    "LCBsYXN0X3RyaWdnZXJlZF9hdCwgbmV4dF9yZXRyeV9hdCwKICAgICAgICBzb3VyY2UgKGxvY2FsfGdvb2dsZSksIGdvb2dsZV9ldmVudF9pZCwgc3luY19z"
    "dGF0dXMsIG1ldGFkYXRhCgogICAgRHVlLWV2ZW50IGN5Y2xlOgogICAgICAgIC0gUHJlLXRyaWdnZXI6IDEgbWludXRlIGJlZm9yZSBkdWUg4oaSIGFubm91"
    "bmNlIHVwY29taW5nCiAgICAgICAgLSBEdWUgdHJpZ2dlcjogYXQgZHVlIHRpbWUg4oaSIGFsZXJ0IHNvdW5kICsgQUkgY29tbWVudGFyeQogICAgICAgIC0g"
    "My1taW51dGUgd2luZG93OiBpZiBub3QgYWNrbm93bGVkZ2VkIOKGkiBzbm9vemUKICAgICAgICAtIDEyLW1pbnV0ZSByZXRyeTogcmUtdHJpZ2dlcgogICAg"
    "IiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29ubCIKCiAg"
    "ICAjIOKUgOKUgCBDUlVEIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRfYWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgp"
    "CiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgbm9ybWFsaXplZCA9IFtdCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIG5v"
    "dCBpc2luc3RhbmNlKHQsIGRpY3QpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgImlkIiBub3QgaW4gdDoKICAgICAgICAgICAg"
    "ICAgIHRbImlkIl0gPSBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAj"
    "IE5vcm1hbGl6ZSBmaWVsZCBuYW1lcwogICAgICAgICAgICBpZiAiZHVlX2F0IiBub3QgaW4gdDoKICAgICAgICAgICAgICAgIHRbImR1ZV9hdCJdID0gdC5n"
    "ZXQoImR1ZSIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN0YXR1cyIsICAgICAgICAgICAicGVu"
    "ZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicmV0cnlfY291bnQiLCAgICAgIDApCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiYWNrbm93bGVk"
    "Z2VkX2F0IiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibGFzdF90cmlnZ2VyZWRfYXQiLE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVs"
    "dCgibmV4dF9yZXRyeV9hdCIsICAgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicHJlX2Fubm91bmNlZCIsICAgIEZhbHNlKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoInNvdXJjZSIsICAgICAgICAgICAibG9jYWwiKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImdvb2dsZV9ldmVudF9pZCIsICBO"
    "b25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN5bmNfc3RhdHVzIiwgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0"
    "YWRhdGEiLCAgICAgICAgIHt9KQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImNyZWF0ZWRfYXQiLCAgICAgICBsb2NhbF9ub3dfaXNvKCkpCgogICAgICAg"
    "ICAgICAjIENvbXB1dGUgcHJlX3RyaWdnZXIgaWYgbWlzc2luZwogICAgICAgICAgICBpZiB0LmdldCgiZHVlX2F0IikgYW5kIG5vdCB0LmdldCgicHJlX3Ry"
    "aWdnZXIiKToKICAgICAgICAgICAgICAgIGR0ID0gcGFyc2VfaXNvKHRbImR1ZV9hdCJdKQogICAgICAgICAgICAgICAgaWYgZHQ6CiAgICAgICAgICAgICAg"
    "ICAgICAgcHJlID0gZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAgICAgICAgICAgICAgIHRbInByZV90cmlnZ2VyIl0gPSBwcmUuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgbm9ybWFsaXplZC5hcHBlbmQodCkK"
    "CiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgbm9ybWFsaXplZCkKICAgICAgICByZXR1cm4gbm9ybWFs"
    "aXplZAoKICAgIGRlZiBzYXZlX2FsbChzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCB0"
    "YXNrcykKCiAgICBkZWYgYWRkKHNlbGYsIHRleHQ6IHN0ciwgZHVlX2R0OiBkYXRldGltZSwKICAgICAgICAgICAgc291cmNlOiBzdHIgPSAibG9jYWwiKSAt"
    "PiBkaWN0OgogICAgICAgIHByZSA9IGR1ZV9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgImlkIjogICAg"
    "ICAgICAgICAgICBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgIGxvY2FsX25vd19pc28o"
    "KSwKICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICBkdWVfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJwcmVf"
    "dHJpZ2dlciI6ICAgICAgcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgIHRleHQuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgTm9uZSwKICAg"
    "ICAgICAgICAgInJldHJ5X2NvdW50IjogICAgICAwLAogICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOk5vbmUsCiAgICAgICAgICAgICJuZXh0X3Jl"
    "dHJ5X2F0IjogICAgTm9uZSwKICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiAgICBGYWxzZSwKICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICBz"
    "b3VyY2UsCiAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgTm9uZSwKICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAicGVuZGluZyIsCiAg"
    "ICAgICAgICAgICJtZXRhZGF0YSI6ICAgICAgICAge30sCiAgICAgICAgfQogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgdGFza3Mu"
    "YXBwZW5kKHRhc2spCiAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gdGFzawoKICAgIGRlZiB1cGRhdGVfc3RhdHVzKHNlbGYs"
    "IHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhY2tub3dsZWRnZWQ6IGJvb2wgPSBGYWxzZSkgLT4gT3B0aW9uYWxb"
    "ZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikg"
    "PT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdID0gc3RhdHVzCiAgICAgICAgICAgICAgICBpZiBhY2tub3dsZWRnZWQ6CiAgICAgICAg"
    "ICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAg"
    "ICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNvbXBsZXRlKHNlbGYsIHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9u"
    "YWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlk"
    "IikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdICAgICAgICAgID0gImNvbXBsZXRlZCIKICAgICAgICAgICAgICAgIHRbImFja25v"
    "d2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJu"
    "IHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjYW5jZWwoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNr"
    "cyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAg"
    "ICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY2FuY2VsbGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9u"
    "b3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25l"
    "CgogICAgZGVmIGNsZWFyX2NvbXBsZXRlZChzZWxmKSAtPiBpbnQ6CiAgICAgICAgdGFza3MgICAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBrZXB0ICAg"
    "ICA9IFt0IGZvciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICAgICAgaWYgdC5nZXQoInN0YXR1cyIpIG5vdCBpbiB7ImNvbXBsZXRlZCIsImNhbmNlbGxl"
    "ZCJ9XQogICAgICAgIHJlbW92ZWQgID0gbGVuKHRhc2tzKSAtIGxlbihrZXB0KQogICAgICAgIGlmIHJlbW92ZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9h"
    "bGwoa2VwdCkKICAgICAgICByZXR1cm4gcmVtb3ZlZAoKICAgIGRlZiB1cGRhdGVfZ29vZ2xlX3N5bmMoc2VsZiwgdGFza19pZDogc3RyLCBzeW5jX3N0YXR1"
    "czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICBnb29nbGVfZXZlbnRfaWQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICBl"
    "cnJvcjogc3RyID0gIiIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6"
    "CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzeW5jX3N0YXR1cyJdICAgID0gc3luY19zdGF0dXMK"
    "ICAgICAgICAgICAgICAgIHRbImxhc3Rfc3luY2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIGlmIGdvb2dsZV9ldmVudF9pZDoK"
    "ICAgICAgICAgICAgICAgICAgICB0WyJnb29nbGVfZXZlbnRfaWQiXSA9IGdvb2dsZV9ldmVudF9pZAogICAgICAgICAgICAgICAgaWYgZXJyb3I6CiAgICAg"
    "ICAgICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgIHRbIm1ldGFkYXRhIl1bImdvb2dsZV9zeW5j"
    "X2Vycm9yIl0gPSBlcnJvcls6MjQwXQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAg"
    "ICAgcmV0dXJuIE5vbmUKCiAgICAjIOKUgOKUgCBEVUUgRVZFTlQgREVURUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIGdldF9kdWVfZXZlbnRzKHNlbGYpIC0+IGxpc3RbdHVwbGVbc3RyLCBkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sgYWxsIHRh"
    "c2tzIGZvciBkdWUvcHJlLXRyaWdnZXIvcmV0cnkgZXZlbnRzLgogICAgICAgIFJldHVybnMgbGlzdCBvZiAoZXZlbnRfdHlwZSwgdGFzaykgdHVwbGVzLgog"
    "ICAgICAgIGV2ZW50X3R5cGU6ICJwcmUiIHwgImR1ZSIgfCAicmV0cnkiCgogICAgICAgIE1vZGlmaWVzIHRhc2sgc3RhdHVzZXMgaW4gcGxhY2UgYW5kIHNh"
    "dmVzLgogICAgICAgIENhbGwgZnJvbSBBUFNjaGVkdWxlciBldmVyeSAzMCBzZWNvbmRzLgogICAgICAgICIiIgogICAgICAgIG5vdyAgICA9IGRhdGV0aW1l"
    "Lm5vdygpLmFzdGltZXpvbmUoKQogICAgICAgIHRhc2tzICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGV2ZW50cyA9IFtdCiAgICAgICAgY2hhbmdlZCA9"
    "IEZhbHNlCgogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBpZiB0YXNrLmdldCgiYWNrbm93bGVkZ2VkX2F0Iik6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQoKICAgICAgICAgICAgc3RhdHVzICAgPSB0YXNrLmdldCgic3RhdHVzIiwgInBlbmRpbmciKQogICAgICAgICAgICBkdWUgICAgICA9"
    "IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJkdWVfYXQiKSkKICAgICAgICAgICAgcHJlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgi"
    "cHJlX3RyaWdnZXIiKSkKICAgICAgICAgICAgbmV4dF9yZXQgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgibmV4dF9yZXRyeV9hdCIpKQogICAgICAg"
    "ICAgICBkZWFkbGluZSA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJhbGVydF9kZWFkbGluZSIpKQoKICAgICAgICAgICAgIyBQcmUtdHJpZ2dlcgog"
    "ICAgICAgICAgICBpZiAoc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgcHJlIGFuZCBub3cgPj0gcHJlCiAgICAgICAgICAgICAgICAgICAgYW5kIG5vdCB0YXNr"
    "LmdldCgicHJlX2Fubm91bmNlZCIpKToKICAgICAgICAgICAgICAgIHRhc2tbInByZV9hbm5vdW5jZWQiXSA9IFRydWUKICAgICAgICAgICAgICAgIGV2ZW50"
    "cy5hcHBlbmQoKCJwcmUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICAjIER1ZSB0cmlnZ2VyCiAgICAgICAg"
    "ICAgIGlmIHN0YXR1cyA9PSAicGVuZGluZyIgYW5kIGR1ZSBhbmQgbm93ID49IGR1ZToKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAg"
    "ICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAg"
    "IHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEo"
    "bWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgo"
    "ImR1ZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFNub296"
    "ZSBhZnRlciAzLW1pbnV0ZSB3aW5kb3cKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJ0cmlnZ2VyZWQiIGFuZCBkZWFkbGluZSBhbmQgbm93ID49IGRlYWRs"
    "aW5lOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgID0gInNub296ZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0"
    "Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MTIpCiAgICAgICAgICAg"
    "ICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKCiAgICAgICAgICAgICMgUmV0cnkKICAgICAgICAgICAgaWYgc3RhdHVzIGluIHsicmV0cnlfcGVuZGluZyIsInNub296ZWQifSBhbmQgbmV4dF9yZXQg"
    "YW5kIG5vdyA+PSBuZXh0X3JldDoKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAgICAgICAg"
    "ICAgdGFza1sicmV0cnlfY291bnQiXSAgICAgICA9IGludCh0YXNrLmdldCgicmV0cnlfY291bnQiLDApKSArIDEKICAgICAgICAgICAgICAgIHRhc2tbImxh"
    "c3RfdHJpZ2dlcmVkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICAgPSAoCiAgICAgICAg"
    "ICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSAgICAgPSBOb25lCiAgICAgICAgICAgICAgICBldmVu"
    "dHMuYXBwZW5kKCgicmV0cnkiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAg"
    "IHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgcmV0dXJuIGV2ZW50cwoKICAgIGRlZiBfcGFyc2VfbG9jYWwoc2VsZiwgdmFsdWU6IHN0cikgLT4gT3B0"
    "aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIlBhcnNlIElTTyBzdHJpbmcgdG8gdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZm9yIGNvbXBhcmlzb24uIiIi"
    "CiAgICAgICAgZHQgPSBwYXJzZV9pc28odmFsdWUpCiAgICAgICAgaWYgZHQgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBk"
    "dC50emluZm8gaXMgTm9uZToKICAgICAgICAgICAgZHQgPSBkdC5hc3RpbWV6b25lKCkKICAgICAgICByZXR1cm4gZHQKCiAgICAjIOKUgOKUgCBOQVRVUkFM"
    "IExBTkdVQUdFIFBBUlNJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgY2xhc3NpZnlfaW50ZW50KHRl"
    "eHQ6IHN0cikgLT4gZGljdDoKICAgICAgICAiIiIKICAgICAgICBDbGFzc2lmeSB1c2VyIGlucHV0IGFzIHRhc2svcmVtaW5kZXIvdGltZXIvY2hhdC4KICAg"
    "ICAgICBSZXR1cm5zIHsiaW50ZW50Ijogc3RyLCAiY2xlYW5lZF9pbnB1dCI6IHN0cn0KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICAj"
    "IFN0cmlwIGNvbW1vbiBpbnZvY2F0aW9uIHByZWZpeGVzCiAgICAgICAgY2xlYW5lZCA9IHJlLnN1YigKICAgICAgICAgICAgcmYiXlxzKig/OntERUNLX05B"
    "TUUubG93ZXIoKX18aGV5XHMre0RFQ0tfTkFNRS5sb3dlcigpfSlccyosP1xzKls6XC1dP1xzKiIsCiAgICAgICAgICAgICIiLCB0ZXh0LCBmbGFncz1yZS5J"
    "CiAgICAgICAgKS5zdHJpcCgpCgogICAgICAgIGxvdyA9IGNsZWFuZWQubG93ZXIoKQoKICAgICAgICB0aW1lcl9wYXRzICAgID0gW3IiXGJzZXQoPzpccyth"
    "KT9ccyt0aW1lclxiIiwgciJcYnRpbWVyXHMrZm9yXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYnN0YXJ0KD86XHMrYSk/XHMrdGltZXJcYiJd"
    "CiAgICAgICAgcmVtaW5kZXJfcGF0cyA9IFtyIlxicmVtaW5kIG1lXGIiLCByIlxic2V0KD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICByIlxiYWRkKD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic2V0KD86XHMrYW4/KT9ccyth"
    "bGFybVxiIiwgciJcYmFsYXJtXHMrZm9yXGIiXQogICAgICAgIHRhc2tfcGF0cyAgICAgPSBbciJcYmFkZCg/OlxzK2EpP1xzK3Rhc2tcYiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICByIlxiY3JlYXRlKD86XHMrYSk/XHMrdGFza1xiIiwgciJcYm5ld1xzK3Rhc2tcYiJdCgogICAgICAgIGltcG9ydCByZSBhcyBf"
    "cmUKICAgICAgICBpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRpbWVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGltZXIiCiAg"
    "ICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHJlbWluZGVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAicmVtaW5kZXIi"
    "CiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRhc2tfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0YXNrIgogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIGludGVudCA9ICJjaGF0IgoKICAgICAgICByZXR1cm4geyJpbnRlbnQiOiBpbnRlbnQsICJjbGVhbmVkX2lucHV0Ijog"
    "Y2xlYW5lZH0KCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2VfZHVlX2RhdGV0aW1lKHRleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgog"
    "ICAgICAgICIiIgogICAgICAgIFBhcnNlIG5hdHVyYWwgbGFuZ3VhZ2UgdGltZSBleHByZXNzaW9uIGZyb20gdGFzayB0ZXh0LgogICAgICAgIEhhbmRsZXM6"
    "ICJpbiAzMCBtaW51dGVzIiwgImF0IDNwbSIsICJ0b21vcnJvdyBhdCA5YW0iLAogICAgICAgICAgICAgICAgICJpbiAyIGhvdXJzIiwgImF0IDE1OjMwIiwg"
    "ZXRjLgogICAgICAgIFJldHVybnMgYSBkYXRldGltZSBvciBOb25lIGlmIHVucGFyc2VhYmxlLgogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAg"
    "ICAgIG5vdyAgPSBkYXRldGltZS5ub3coKQogICAgICAgIGxvdyAgPSB0ZXh0Lmxvd2VyKCkuc3RyaXAoKQoKICAgICAgICAjICJpbiBYIG1pbnV0ZXMvaG91"
    "cnMvZGF5cyIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImluXHMrKFxkKylccyoobWludXRlfG1pbnxob3VyfGhyfGRheXxzZWNvbmR8"
    "c2VjKSIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAgICAgICBuICAgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAg"
    "ICAgIHVuaXQgPSBtLmdyb3VwKDIpCiAgICAgICAgICAgIGlmICJtaW4iIGluIHVuaXQ6ICByZXR1cm4gbm93ICsgdGltZWRlbHRhKG1pbnV0ZXM9bikKICAg"
    "ICAgICAgICAgaWYgImhvdXIiIGluIHVuaXQgb3IgImhyIiBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGhvdXJzPW4pCiAgICAgICAgICAgIGlm"
    "ICJkYXkiICBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGRheXM9bikKICAgICAgICAgICAgaWYgInNlYyIgIGluIHVuaXQ6IHJldHVybiBub3cg"
    "KyB0aW1lZGVsdGEoc2Vjb25kcz1uKQoKICAgICAgICAjICJhdCBISDpNTSIgb3IgImF0IEg6TU1hbS9wbSIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAg"
    "ICAgICAgICByImF0XHMrKFxkezEsMn0pKD86OihcZHsyfSkpP1xzKihhbXxwbSk/IiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06"
    "CiAgICAgICAgICAgIGhyICA9IGludChtLmdyb3VwKDEpKQogICAgICAgICAgICBtbiAgPSBpbnQobS5ncm91cCgyKSkgaWYgbS5ncm91cCgyKSBlbHNlIDAK"
    "ICAgICAgICAgICAgYXBtID0gbS5ncm91cCgzKQogICAgICAgICAgICBpZiBhcG0gPT0gInBtIiBhbmQgaHIgPCAxMjogaHIgKz0gMTIKICAgICAgICAgICAg"
    "aWYgYXBtID09ICJhbSIgYW5kIGhyID09IDEyOiBociA9IDAKICAgICAgICAgICAgZHQgPSBub3cucmVwbGFjZShob3VyPWhyLCBtaW51dGU9bW4sIHNlY29u"
    "ZD0wLCBtaWNyb3NlY29uZD0wKQogICAgICAgICAgICBpZiBkdCA8PSBub3c6CiAgICAgICAgICAgICAgICBkdCArPSB0aW1lZGVsdGEoZGF5cz0xKQogICAg"
    "ICAgICAgICByZXR1cm4gZHQKCiAgICAgICAgIyAidG9tb3Jyb3cgYXQgLi4uIiAgKHJlY3Vyc2Ugb24gdGhlICJhdCIgcGFydCkKICAgICAgICBpZiAidG9t"
    "b3Jyb3ciIGluIGxvdzoKICAgICAgICAgICAgdG9tb3Jyb3dfdGV4dCA9IHJlLnN1YihyInRvbW9ycm93IiwgIiIsIGxvdykuc3RyaXAoKQogICAgICAgICAg"
    "ICByZXN1bHQgPSBUYXNrTWFuYWdlci5wYXJzZV9kdWVfZGF0ZXRpbWUodG9tb3Jyb3dfdGV4dCkKICAgICAgICAgICAgaWYgcmVzdWx0OgogICAgICAgICAg"
    "ICAgICAgcmV0dXJuIHJlc3VsdCArIHRpbWVkZWx0YShkYXlzPTEpCgogICAgICAgIHJldHVybiBOb25lCgoKIyDilIDilIAgUkVRVUlSRU1FTlRTLlRYVCBH"
    "RU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiB3cml0ZV9yZXF1aXJlbWVudHNfdHh0"
    "KCkgLT4gTm9uZToKICAgICIiIgogICAgV3JpdGUgcmVxdWlyZW1lbnRzLnR4dCBuZXh0IHRvIHRoZSBkZWNrIGZpbGUgb24gZmlyc3QgcnVuLgogICAgSGVs"
    "cHMgdXNlcnMgaW5zdGFsbCBhbGwgZGVwZW5kZW5jaWVzIHdpdGggb25lIHBpcCBjb21tYW5kLgogICAgIiIiCiAgICByZXFfcGF0aCA9IFBhdGgoQ0ZHLmdl"
    "dCgiYmFzZV9kaXIiLCBzdHIoU0NSSVBUX0RJUikpKSAvICJyZXF1aXJlbWVudHMudHh0IgogICAgaWYgcmVxX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0"
    "dXJuCgogICAgY29udGVudCA9ICIiIlwKIyBNb3JnYW5uYSBEZWNrIOKAlCBSZXF1aXJlZCBEZXBlbmRlbmNpZXMKIyBJbnN0YWxsIGFsbCB3aXRoOiBwaXAg"
    "aW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0CgojIENvcmUgVUkKUHlTaWRlNgoKIyBTY2hlZHVsaW5nIChpZGxlIHRpbWVyLCBhdXRvc2F2ZSwgcmVmbGVj"
    "dGlvbiBjeWNsZXMpCmFwc2NoZWR1bGVyCgojIExvZ2dpbmcKbG9ndXJ1CgojIFNvdW5kIHBsYXliYWNrIChXQVYgKyBNUDMpCnB5Z2FtZQoKIyBEZXNrdG9w"
    "IHNob3J0Y3V0IGNyZWF0aW9uIChXaW5kb3dzIG9ubHkpCnB5d2luMzIKCiMgU3lzdGVtIG1vbml0b3JpbmcgKENQVSwgUkFNLCBkcml2ZXMsIG5ldHdvcmsp"
    "CnBzdXRpbAoKIyBIVFRQIHJlcXVlc3RzCnJlcXVlc3RzCgojIEdvb2dsZSBpbnRlZ3JhdGlvbiAoQ2FsZW5kYXIsIERyaXZlLCBEb2NzLCBHbWFpbCkKZ29v"
    "Z2xlLWFwaS1weXRob24tY2xpZW50Cmdvb2dsZS1hdXRoLW9hdXRobGliCmdvb2dsZS1hdXRoCgojIOKUgOKUgCBPcHRpb25hbCAobG9jYWwgbW9kZWwgb25s"
    "eSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHVzaW5nIGEgbG9jYWwgSHVnZ2luZ0Zh"
    "Y2UgbW9kZWw6CiMgdG9yY2gKIyB0cmFuc2Zvcm1lcnMKIyBhY2NlbGVyYXRlCgojIOKUgOKUgCBPcHRpb25hbCAoTlZJRElBIEdQVSBtb25pdG9yaW5nKSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgeW91IGhhdmUgYW4gTlZJRElBIEdQVToKIyBweW52bWwKIiIiCiAgICByZXFf"
    "cGF0aC53cml0ZV90ZXh0KGNvbnRlbnQsIGVuY29kaW5nPSJ1dGYtOCIpCgoKIyDilIDilIAgUEFTUyA0IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1lbW9yeSwgU2Vzc2lvbiwgTGVz"
    "c29uc0xlYXJuZWQsIFRhc2tNYW5hZ2VyIGFsbCBkZWZpbmVkLgojIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhdXRvLXNlZWRlZCBvbiBmaXJzdCBydW4uCiMg"
    "cmVxdWlyZW1lbnRzLnR4dCB3cml0dGVuIG9uIGZpcnN0IHJ1bi4KIwojIE5leHQ6IFBhc3MgNSDigJQgVGFiIENvbnRlbnQgQ2xhc3NlcwojIChTTFNjYW5z"
    "VGFiLCBTTENvbW1hbmRzVGFiLCBKb2JUcmFja2VyVGFiLCBSZWNvcmRzVGFiLAojICBUYXNrc1RhYiwgU2VsZlRhYiwgRGlhZ25vc3RpY3NUYWIpCgoKIyDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDU6IFRBQiBD"
    "T05URU5UIENMQVNTRVMKIwojIFRhYnMgZGVmaW5lZCBoZXJlOgojICAgU0xTY2Fuc1RhYiAgICAgIOKAlCBncmltb2lyZS1jYXJkIHN0eWxlLCByZWJ1aWx0"
    "IChEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwKIyAgICAgICAgICAgICAgICAgICAgIHBhcnNlciBmaXhlZCwgY29weS10by1jbGlwYm9hcmQgcGVyIGl0"
    "ZW0pCiMgICBTTENvbW1hbmRzVGFiICAg4oCUIGdvdGhpYyB0YWJsZSwgY29weSBjb21tYW5kIHRvIGNsaXBib2FyZAojICAgSm9iVHJhY2tlclRhYiAgIOKA"
    "lCBmdWxsIHJlYnVpbGQgZnJvbSBzcGVjLCBDU1YvVFNWIGV4cG9ydAojICAgUmVjb3Jkc1RhYiAgICAgIOKAlCBHb29nbGUgRHJpdmUvRG9jcyB3b3Jrc3Bh"
    "Y2UKIyAgIFRhc2tzVGFiICAgICAgICDigJQgdGFzayByZWdpc3RyeSArIG1pbmkgY2FsZW5kYXIKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRsZSBuYXJy"
    "YXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1IG91dHB1dCArIGhhcmR3YXJlIHJlcG9ydCArIGpvdXJuYWwg"
    "bG9hZCBub3RpY2VzCiMgICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMgX3JlCgoKIyDilIDilIAgU0hBUkVEIEdP"
    "VEhJQyBUQUJMRSBTVFlMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFi"
    "bGVfc3R5bGUoKSAtPiBzdHI6CiAgICByZXR1cm4gZiIiIgogICAgICAgIFFUYWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9"
    "OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAg"
    "Z3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQt"
    "c2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAgICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06YWx0"
    "ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgfX0KICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAg"
    "ICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT05fRElNfTsKICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsK"
    "ICAgICAgICAgICAgZm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9sZDsKICAgICAgICAgICAgbGV0dGVyLXNwYWNpbmc6IDFw"
    "eDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4dDogc3RyLCB0b29sdGlwOiBzdHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBi"
    "dG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQogICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9y"
    "OiB7Q19HT0xEfTsgIgogICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogNHB4"
    "IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAgICAgICBidG4uc2V0VG9vbFRpcCh0b29sdGlwKQogICAgcmV0"
    "dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNp"
    "bmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMgVEFCIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBhdmF0YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAg"
    "ICBSZWJ1aWx0IGZyb20gc3BlYzoKICAgICAgLSBDYXJkL2dyaW1vaXJlLWVudHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGltZXN0YW1w"
    "LWF3YXJlIHBhcnNlcikKICAgICAgLSBEaXNwbGF5IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRlc2Ny"
    "aXB0aW9uLCBpbmRpdmlkdWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBhcnNlICh3"
    "YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAgIC0gQ29weS10by1jbGlwYm9hcmQgb24gYW55IGl0ZW0K"
    "ICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxp"
    "c3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRvbiBiYXIK"
    "ICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEg"
    "bmV3IHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5ID0gX2dvdGhpY19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBkZXRh"
    "aWxzIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5f"
    "cmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4dCBvZiBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9i"
    "dG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAgICAgICBzZWxmLl9idG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hv"
    "d19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9k"
    "ZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "cmVwYXJzZSkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYuX2J0bl9tb2RpZnksCiAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2J0bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJhci5hZGRT"
    "dHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgICMgU3RhY2s6IGxpc3QgdmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1v"
    "ZGlmeQogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoKICAgICAg"
    "ICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4gbGlzdCAoZ3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAgICAgICBs"
    "MC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9j"
    "YXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAgc2VsZi5fY2FyZF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dCAgICA9IFFWQm94TGF5b3V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0"
    "LCA0LCA0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5hZGRTdHJldGNoKCkKICAg"
    "ICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2NhcmRfc2Ny"
    "b2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyDilIDilIAgUEFHRSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBT"
    "Q0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5z"
    "ZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkKICAg"
    "ICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQog"
    "ICAgICAgIHNlbGYuX2FkZF9kZXNjLnNldE1heGltdW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAgICAgIGwx"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAgIHNlbGYuX2FkZF9yYXcgICA9IFFUZXh0"
    "RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJQYXN0ZSB0aGUgcmF3IFNlY29uZCBMaWZlIHNj"
    "YW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3XSB3aWxsIGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVj"
    "dGx5LiIKICAgICAgICApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBpdGVtcwog"
    "ICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0g"
    "UVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJd"
    "KQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWln"
    "aHQoMTIwKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdpZGdl"
    "dChzZWxmLl9hZGRfcHJldmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fcHJldmlld19wYXJzZSkKCiAgICAg"
    "ICAgYnRuczEgPSBRSEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzEgPSBfZ290aGljX2J0bigi4pyXIENhbmNl"
    "bCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBjMS5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFj"
    "ay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczEuYWRkV2lkZ2V0KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRjaCgp"
    "CiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0bnMxKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAyOiBk"
    "aXNwbGF5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExh"
    "eW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkKICAg"
    "ICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2Rpc3BfZGVzYyAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BfZGVz"
    "Yy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3Rh"
    "YmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rp"
    "c3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0"
    "cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl9kaXNwX3Rh"
    "YmxlLnNldENvbnRleHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxm"
    "Ll9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAg"
    "ICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF9uYW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KHNlbGYuX2Rpc3BfdGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55IGl0ZW0gdG8gY29weSBpdCB0byBj"
    "bGlwYm9hcmQuIikKICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6"
    "IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGwyLmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAg"
    "IGJrMiA9IF9nb3RoaWNfYnRuKCLil4AgQmFjayIpCiAgICAgICAgYmsyLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJ"
    "bmRleCgwKSkKICAgICAgICBsMi5hZGRXaWRnZXQoYmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAgUEFH"
    "RSAzOiBtb2RpZnkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9"
    "IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAgICAg"
    "ICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTkFNRSIpKQogICAgICAgIHNlbGYuX21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5h"
    "ZGRXaWRnZXQoc2VsZi5fbW9kX25hbWUpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2Vs"
    "Zi5fbW9kX2Rlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgSVRFTVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQog"
    "ICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJveExheW91dCgpCiAgICAgICAgczMgPSBfZ290aGljX2J0"
    "bigi4pymIFNhdmUiKTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeV9z"
    "YXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRX"
    "aWRnZXQoczMpOyBidG5zMy5hZGRXaWRnZXQoYzMpOyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAgc2Vs"
    "Zi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1"
    "cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBpdGVt"
    "cykuCgogICAgICAgIEtFWSBGSVg6IEJlZm9yZSBzcGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRpbWVz"
    "dGFtcCBzbyBzaW5nbGUtbGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzExOjQ3XSBB"
    "dmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46IEl0ZW0gTmFtZSBbQXR0YWNobWVudF0gQ1JFQVRPUjogQ3Jl"
    "YXRvck5hbWUgWzExOjQ3XSAuLi4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgcmF3LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9XTiIs"
    "IFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTogbm9ybWFsaXplIOKAlCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgbm9ybWFsaXplZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAgIGxpbmVz"
    "ID0gW2wuc3RyaXAoKSBmb3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMjogZXh0"
    "cmFjdCBhdmF0YXIgbmFtZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFtZSA9ICJVTktOT1dOIgogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAg"
    "ICAgICAjICJBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBvciBzaW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAgICAgICAg"
    "ICAgICAgciIoXHdbXHdcc10rPyknc1xzK3B1YmxpY1xzK2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBicmVhawoK"
    "ICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQogICAgICAg"
    "IGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjIFN0cmlwIGxlYWRpbmcgdGltZXN0YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHIn"
    "XlxbXGR7MSwyfTpcZHsyfVxdXHMqJywgJycsIGxpbmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBjb250"
    "aW51ZQogICAgICAgICAgICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNobWVudHMiIGluIGNvbnRlbnQubG93"
    "ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93ZXIoKS5zdGFydHN3aXRoKCJvYmplY3QiKToKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZpZGVyIGxpbmVzIOKAlCBsaW5lcyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVk"
    "IGNoYXJhY3RlcgogICAgICAgICAgICAjIGUuZy4g4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkCBvciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50LnN0"
    "cmlwKCIuOiAiKQogICAgICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250aW51ZSAg"
    "IyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAgIyBUcnkgdG8gZXh0cmFjdCBDUkVBVE9SOiBmaWVsZAogICAg"
    "ICAgICAgICBjcmVhdG9yID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2ggPSBf"
    "cmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidDUkVBVE9SOlxzKihbXHdcc10rPykoPzpccypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgaWYgY3JlYXRvcl9tYXRjaDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSkuc3RyaXAo"
    "KQogICAgICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJpcCgpCgogICAgICAgICAgICAjIFN0cmlw"
    "IGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBpdGVtX25hbWUgPSBfcmUuc3ViKHInXHMqXFtbXHdcc19d"
    "K1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBpdGVtX25hbWUgPSBpdGVtX25hbWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBp"
    "ZiBpdGVtX25hbWUgYW5kIGxlbihpdGVtX25hbWUpID4gMToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUsICJjcmVh"
    "dG9yIjogY3JlYXRvcn0pCgogICAgICAgIHJldHVybiBhdmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfY2FyZHMoc2VsZikgLT4gTm9uZToKICAgICAgICAj"
    "IENsZWFyIGV4aXN0aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAg"
    "ICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0u"
    "d2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtlX2Nh"
    "cmQocmVjKQogICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5jb3Vu"
    "dCgpIC0gMSwgY2FyZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVjOiBkaWN0KSAtPiBRV2lkZ2V0OgogICAgICAgIGNhcmQg"
    "PSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEwYTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFk"
    "aXVzOiAycHg7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJuYW1lIiwgIlVOS05PV04iKSkKICAgICAgICBu"
    "YW1lX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07ICIK"
    "ICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAg"
    "ICApCgogICAgICAgIGNvdW50ID0gbGVuKHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0gaXRlbXMi"
    "KQogICAgICAgIGNvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxMHB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJsID0gUUxhYmVsKHJlYy5nZXQoImNyZWF0ZWRfYXQiLCAi"
    "IilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAgICAgICAg"
    "bGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgicmVjb3Jk"
    "X2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJlY19pZDogc2VsZi5fc2VsZWN0X2NhcmQocmlkKQogICAg"
    "ICAgIHJldHVybiBjYXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZWxlY3Rl"
    "ZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkgICMgUmVidWlsZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBk"
    "ZWYgX3NlbGVjdGVkX3JlY29yZChzZWxmKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIgaW4g"
    "c2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkKSwKICAgICAgICAgICAgTm9uZQog"
    "ICAgICAgICkKCiAgICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9w"
    "YXRoKQogICAgICAgICMgRW5zdXJlIHJlY29yZF9pZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBzZWxm"
    "Ll9yZWNvcmRzOgogICAgICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSByLmdldCgi"
    "aWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3"
    "cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRD"
    "dXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZpZXdfcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5U"
    "ZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRl"
    "clRleHQobmFtZSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiBpdGVtc1s6MjBdOiAgIyBwcmV2"
    "aWV3IGZpcnN0IDIwCiAgICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmlu"
    "c2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAg"
    "ICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMSwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3Nob3dfYWRk"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYWRkX25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "QXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuY2xlYXIo"
    "KQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDEpCgogICAgZGVm"
    "IF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBz"
    "ZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgb3ZlcnJpZGVfbmFtZSA9IHNlbGYuX2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93"
    "ICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICBz"
    "dHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJuYW1lIjogICAgICAg"
    "IG92ZXJyaWRlX25hbWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5fYWRkX2Rlc2MudG9QbGFpblRleHQoKVs6MjQ0XSwKICAg"
    "ICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAgICJyYXdfdGV4dCI6ICAgIHJhdywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAg"
    "bm93LAogICAgICAgICAgICAidXBkYXRlZF9hdCI6ICBub3csCiAgICAgICAgfQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQiXQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9y"
    "ZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRpc3BsYXkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5f"
    "ZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRl"
    "c2NyaXB0aW9uIiwiIikpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIs"
    "W10pOgogICAgICAgICAgICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaW5zZXJ0Um93KHIp"
    "CiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0i"
    "LCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQo"
    "ImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0X21lbnUo"
    "c2VsZiwgcG9zKSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1ZhbGlk"
    "KCk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IKICAgICAg"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVhdG9yICAgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShp"
    "ZHgucm93KCksIDEpIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0"
    "V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1lbnUoc2VsZikKICAgICAgICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIK"
    "ICAgICAgICApCiAgICAgICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAgICBhX2NyZWF0b3IgPSBtZW51LmFk"
    "ZEFjdGlvbigiQ29weSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBCb3RoIikKICAgICAgICBhY3Rpb24gPSBt"
    "ZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJk"
    "KCkKICAgICAgICBpZiBhY3Rpb24gPT0gYV9pdGVtOiAgICBjYi5zZXRUZXh0KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0b3I6"
    "IGNiLnNldFRleHQoY3JlYXRvcikKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVhdG9y"
    "fSIpCgogICAgZGVmIF9zaG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYg"
    "bm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQocmVj"
    "LmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9t"
    "b2RfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX21vZF90"
    "YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0"
    "ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUu"
    "c2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYu"
    "X3N0YWNrLnNldEN1cnJlbnRJbmRleCgzKQoKICAgIGRlZiBfZG9fbW9kaWZ5X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxl"
    "Y3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYuX21v"
    "ZF9uYW1lLnRleHQoKS5zdHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQoKVs6MjQ0"
    "XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ICA9"
    "IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYuX21vZF90"
    "YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAo"
    "KSBvciAiVU5LTk9XTiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAgcmVj"
    "WyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkK"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRv"
    "IGRlbGV0ZS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IFRoaXMg"
    "Y2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYu"
    "X3NlbGVjdGVkX2lkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9zZWxlY3Rl"
    "ZF9pZCA9IE5vbmUKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBz"
    "ZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBT"
    "Y2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHJhdyA9IHJlYy5nZXQoInJhd190ZXh0IiwiIikKICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1h"
    "dGlvbihzZWxmLCAiUmUtcGFyc2UiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlzIHNj"
    "YW4uIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVjWyJpdGVt"
    "cyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0gb3IgbmFtZQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJd"
    "ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZiJGb3VuZCB7bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMQ29tbWFuZHNUYWIo"
    "UVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQgcmVmZXJlbmNlIHRhYmxlLgogICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkg"
    "Y29tbWFuZCB0byBjbGlwYm9hcmQgYnV0dG9uIHBlciByb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIKICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBk"
    "ZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdp"
    "bnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9h"
    "ZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAg"
    "ICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0bigi4qeJ"
    "IENvcHkgQ29tbWFuZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxlY3RlZCBjb21tYW5kIHRvIGNsaXBib2Fy"
    "ZCIpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxm"
    "Ll9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2NvcHlfY29tbWFuZCkKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGluIChz"
    "ZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwgc2VsZi5f"
    "YnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0"
    "KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFi"
    "ZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0"
    "eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxlY3Qg"
    "YSByb3cgYW5kIGNsaWNrIOKniSBDb3B5IENvbW1hbmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50LnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4g"
    "c2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29tbWFuZCIs"
    "IiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNj"
    "cmlwdGlvbiIsIiIpKSkKCiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3co"
    "KQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBp"
    "ZiBpdGVtOgogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBkbGcu"
    "c2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAg"
    "ICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAg"
    "Zm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJT"
    "YXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5l"
    "Y3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAg"
    "ICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAog"
    "ICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVz"
    "Yy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAgICAg"
    "IH0KICAgICAgICAgICAgaWYgcmVjWyJjb21tYW5kIl06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX21vZGlm"
    "eShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihz"
    "ZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxvZyhz"
    "ZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kaWZ5IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KHJlYy5n"
    "ZXQoImNvbW1hbmQiLCIiKSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "IkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcu"
    "YWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAg"
    "ICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBy"
    "ZWNbImNvbW1hbmQiXSAgICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50ZXh0KCku"
    "c3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAg"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVs"
    "ZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVu"
    "KHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhpcyBj"
    "b21tYW5kIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwgZiJEZWxldGUgJ3tjbWR9"
    "Jz8iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkK"
    "ICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBKT0Ig"
    "VFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpvYiBhcHBsaWNhdGlvbiB0cmFja2luZy4gRnVsbCByZWJ1aWxk"
    "IGZyb20gc3BlYy4KICAgIEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxlLCBEYXRlIEFwcGxpZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0aS1z"
    "ZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1YgYW5kIFRTViBleHBvcnQuCiAgICBIaWRkZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3Rp"
    "bGwgc3RvcmVkLCBqdXN0IG5vdCBzaG93bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBwbGllZCIs"
    "CiAgICAgICAgICAgICAgICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiam9iX3RyYWNrZXIuanNvbmwi"
    "CiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3Nl"
    "dHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBi"
    "YXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkg"
    "PSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhpY19idG4oIkFyY2hpdmUiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVkL3JlamVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5oaWRlID0g"
    "X2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRp"
    "b25zIikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3RoaWNf"
    "YnRuKCJTaG93IEFyY2hpdmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIpCgogICAgICAgIGZvciBiIGluIChz"
    "ZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSwgc2VsZi5f"
    "YnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSwgc2VsZi5fYnRuX2V4cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11"
    "bVdpZHRoKDcwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2VsZi5f"
    "YnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21v"
    "ZGlmeSkKICAgICAgICBzZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAg"
    "ICAgIHNlbGYuX2J0bl90b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9oaWRkZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNl"
    "bGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJl"
    "bHMoc2VsZi5DT0xVTU5TKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgIyBDb21wYW55IGFuZCBKb2IgVGl0"
    "bGUgc3RyZXRjaAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBoaC5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJl"
    "YWRhYmxlIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRDb2x1bW5XaWR0aCgyLCAxMDApCiAgICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDMs"
    "IFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDQsIDgwKQogICAgICAg"
    "ICMgTm90ZXMgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQoKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2Vs"
    "ZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2Rl"
    "LkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgZGVmIHJlZnJl"
    "c2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJv"
    "d0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIsIEZh"
    "bHNlKSkKICAgICAgICAgICAgaWYgaGlkZGVuIGFuZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVzID0gIkFy"
    "Y2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgcmVj"
    "LmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRl"
    "X2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAg"
    "IHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAgICAgICAg"
    "ICAgaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAgICAgICAgICAgICAgICAgIGl0ZW0uc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIGMsIGl0ZW0pCiAgICAgICAgICAg"
    "ICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVzZXIgZGF0YQogICAgICAgICAgICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERh"
    "dGEoCiAgICAgICAgICAgICAgICBRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJlYykKICAg"
    "ICAgICAgICAgKQoKICAgIGRlZiBfc2VsZWN0ZWRfaW5kaWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAgICAg"
    "Zm9yIGl0ZW0gaW4gc2VsZi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRlbS5yb3co"
    "KSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSByb3dfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9s"
    "ZSkKICAgICAgICAgICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAgcmV0dXJu"
    "IHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAg"
    "PSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYi"
    "YmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkKICAgICAgICBmb3JtID0gUUZvcm1M"
    "YXlvdXQoZGxnKQoKICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnkiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICB0aXRs"
    "ZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAg"
    "ICAgIGRlLnNldENhbGVuZGFyUG9wdXAoVHJ1ZSkKICAgICAgICBkZS5zZXREaXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMgYW5k"
    "IHJlYy5nZXQoImRhdGVfYXBwbGllZCIpOgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwieXl5"
    "eS1NTS1kZCIpKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAgID0gUUxp"
    "bmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0dXMgID0gUUxpbmVFZGl0KHJlYy5nZXQoInN0YXR1cyIsIkFw"
    "cGxpZWQiKSBpZiByZWMgZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90ZXMgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiQ29tcGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0"
    "bGUpLAogICAgICAgICAgICAoIkRhdGUgQXBwbGllZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzKSwg"
    "KCJOb3RlczoiLCBub3RlcyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdldCkKCiAgICAgICAgYnRucyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5j"
    "b25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lk"
    "Z2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgog"
    "ICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAg"
    "ICAiam9iX3RpdGxlIjogICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRvU3RyaW5n"
    "KCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0"
    "dXMiOiAgICAgICBzdGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVzLnRleHQo"
    "KS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBz"
    "ZWxmLl9kaWFsb2coKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRj"
    "KS5pc29mb3JtYXQoKQogICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICJoaWRkZW4iOiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUiOiBOb25lLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6"
    "ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5vdywKICAgICAgICB9KQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAg"
    "ICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBleGFj"
    "dGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbaWR4c1swXV0KICAgICAgICBw"
    "ICAgPSBzZWxmLl9kaWFsb2cocmVjKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAgICAgICAg"
    "cmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgs"
    "IHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGlu"
    "IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJjb21wbGV0ZWRfZGF0ZSJd"
    "ID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XS5nZXQoImNvbXBsZXRlZF9kYXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBk"
    "YXRldGltZS5ub3coKS5kYXRlKCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBk"
    "YXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fdW5oaWRl"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihzZWxm"
    "Ll9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgp"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIG5vdCBp"
    "ZHhzOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwK"
    "ICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQgYXBwbGljYXRpb24ocyk/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAg"
    "UU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkg"
    "PT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9"
    "IFtyIGZvciBpLCByIGluIGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJhZF0KICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3RvZ2ds"
    "ZV9oaWRkZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IG5vdCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNlbGYuX2J0"
    "bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAgIuKYgCBIaWRlIEFyY2hpdmVkIiBpZiBzZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNo"
    "aXZlZCIKICAgICAgICApCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIGZp"
    "bHQgPSBRRmlsZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRyYWNrZXIiLAogICAgICAgICAgICBzdHIo"
    "Y2ZnX3BhdGgoImV4cG9ydHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNTViBGaWxlcyAoKi5jc3YpOztUYWIgRGVsaW1pdGVkICgq"
    "LnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dl"
    "cigpLmVuZHN3aXRoKCIudHh0IikgZWxzZSAiLCIKICAgICAgICBoZWFkZXIgPSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQiLCJsaW5r"
    "IiwKICAgICAgICAgICAgICAgICAgInN0YXR1cyIsImhpZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRoLCAi"
    "dyIsIGVuY29kaW5nPSJ1dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxuIikKICAg"
    "ICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJj"
    "b21wYW55IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0"
    "ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1"
    "cyIsIiIpLAogICAgICAgICAgICAgICAgICAgIHN0cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiY29tcGxldGVkX2RhdGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgXQog"
    "ICAgICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0cih2KS5yZXBsYWNlKCJcbiIsIiAiKS5yZXBsYWNlKGRl"
    "bGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxzCiAgICAgICAgICAgICAgICApICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5p"
    "bmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKUgOKU"
    "gCBTRUxGIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgUmVjb3Jkc1RhYihRV2lkZ2V0KToKICAgICIiIkdvb2dsZSBEcml2ZS9Eb2NzIHJlY29yZHMg"
    "YnJvd3NlciB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAg"
    "ICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiUmVjb3JkcyBhcmUgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBzZWxm"
    "LnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBzZWxm"
    "LnBhdGhfbGFiZWwgPSBRTGFiZWwoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICByb290LmFkZFdpZGdldChzZWxmLnBhdGhfbGFiZWwpCgogICAgICAgIHNlbGYucmVjb3Jkc19saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYu"
    "cmVjb3Jkc19saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5yZWNvcmRzX2xpc3QsIDEpCgogICAgZGVmIHNldF9p"
    "dGVtcyhzZWxmLCBmaWxlczogbGlzdFtkaWN0XSwgcGF0aF90ZXh0OiBzdHIgPSAiTXkgRHJpdmUiKSAtPiBOb25lOgogICAgICAgIHNlbGYucGF0aF9sYWJl"
    "bC5zZXRUZXh0KGYiUGF0aDoge3BhdGhfdGV4dH0iKQogICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmNsZWFyKCkKICAgICAgICBmb3IgZmlsZV9pbmZvIGlu"
    "IGZpbGVzOgogICAgICAgICAgICB0aXRsZSA9IChmaWxlX2luZm8uZ2V0KCJuYW1lIikgb3IgIlVudGl0bGVkIikuc3RyaXAoKSBvciAiVW50aXRsZWQiCiAg"
    "ICAgICAgICAgIG1pbWUgPSAoZmlsZV9pbmZvLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBpZiBtaW1lID09ICJhcHBsaWNh"
    "dGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OBIgogICAgICAgICAgICBlbGlmIG1pbWUgPT0gImFw"
    "cGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCI6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+TnSIKICAgICAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OEIgogICAgICAgICAgICBtb2RpZmllZCA9IChmaWxlX2luZm8uZ2V0KCJtb2RpZmllZFRpbWUiKSBvciAiIiku"
    "cmVwbGFjZSgiVCIsICIgIikucmVwbGFjZSgiWiIsICIgVVRDIikKICAgICAgICAgICAgdGV4dCA9IGYie3ByZWZpeH0ge3RpdGxlfSIgKyAoZiIgICAgW3tt"
    "b2RpZmllZH1dIiBpZiBtb2RpZmllZCBlbHNlICIiKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKHRleHQpCiAgICAgICAgICAgIGl0ZW0u"
    "c2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGZpbGVfaW5mbykKICAgICAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuYWRkSXRlbShpdGVtKQog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJMb2FkZWQge2xlbihmaWxlcyl9IEdvb2dsZSBEcml2ZSBpdGVtKHMpLiIpCgoKY2xhc3MgVGFz"
    "a3NUYWIoUVdpZGdldCk6CiAgICAiIiJUYXNrIHJlZ2lzdHJ5ICsgR29vZ2xlLWZpcnN0IGVkaXRvciB3b3JrZmxvdyB0YWIuIiIiCgogICAgZGVmIF9faW5p"
    "dF9fKAogICAgICAgIHNlbGYsCiAgICAgICAgdGFza3NfcHJvdmlkZXIsCiAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuLAogICAgICAgIG9uX2NvbXBsZXRl"
    "X3NlbGVjdGVkLAogICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZCwKICAgICAgICBvbl90b2dnbGVfY29tcGxldGVkLAogICAgICAgIG9uX3B1cmdlX2NvbXBs"
    "ZXRlZCwKICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZCwKICAgICAgICBvbl9lZGl0b3Jfc2F2ZSwKICAgICAgICBvbl9lZGl0b3JfY2FuY2VsLAogICAgICAg"
    "IGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lLAogICAgICAgIHBhcmVudD1Ob25lLAogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAg"
    "ICAgICBzZWxmLl90YXNrc19wcm92aWRlciA9IHRhc2tzX3Byb3ZpZGVyCiAgICAgICAgc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuID0gb25fYWRkX2VkaXRv"
    "cl9vcGVuCiAgICAgICAgc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQgPSBvbl9jb21wbGV0ZV9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX2NhbmNlbF9z"
    "ZWxlY3RlZCA9IG9uX2NhbmNlbF9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQgPSBvbl90b2dnbGVfY29tcGxldGVkCiAgICAg"
    "ICAgc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkID0gb25fcHVyZ2VfY29tcGxldGVkCiAgICAgICAgc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQgPSBvbl9maWx0"
    "ZXJfY2hhbmdlZAogICAgICAgIHNlbGYuX29uX2VkaXRvcl9zYXZlID0gb25fZWRpdG9yX3NhdmUKICAgICAgICBzZWxmLl9vbl9lZGl0b3JfY2FuY2VsID0g"
    "b25fZWRpdG9yX2NhbmNlbAogICAgICAgIHNlbGYuX2RpYWdfbG9nZ2VyID0gZGlhZ25vc3RpY3NfbG9nZ2VyCiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0"
    "ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICBkZWYgX2J1aWxkX3Vp"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwg"
    "NikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzZWxmLndvcmtzcGFjZV9zdGFjaywgMSkKCiAgICAgICAgbm9ybWFsID0gUVdpZGdldCgpCiAgICAgICAgbm9ybWFsX2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KG5vcm1hbCkKICAgICAgICBub3JtYWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG5vcm1hbF9sYXlv"
    "dXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiVGFzayByZWdpc3RyeSBpcyBub3QgbG9hZGVkIHlldC4iKQog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNf"
    "bGFiZWwpCgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "REFURSBSQU5HRSIpKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8u"
    "YWRkSXRlbSgiV0VFSyIsICJ3ZWVrIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk1PTlRIIiwgIm1vbnRoIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk5FWFQgMyBNT05USFMiLCAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9j"
    "b21iby5hZGRJdGVtKCJZRUFSIiwgInllYXIiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uc2V0Q3VycmVudEluZGV4KDIpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBfOiBzZWxmLl9vbl9maWx0ZXJfY2hh"
    "bmdlZChzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgICkKICAgICAgICBmaWx0ZXJfcm93"
    "LmFkZFdpZGdldChzZWxmLnRhc2tfZmlsdGVyX2NvbWJvKQogICAgICAgIGZpbHRlcl9yb3cuYWRkU3RyZXRjaCgxKQogICAgICAgIG5vcm1hbF9sYXlvdXQu"
    "YWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIHNlbGYudGFza190YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiU3RhdHVzIiwgIkR1ZSIsICJUYXNrIiwgIlNvdXJjZSJdKQogICAgICAgIHNlbGYudGFza190YWJsZS5z"
    "ZXRTZWxlY3Rpb25CZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5zZXRTZWxlY3Rpb25Nb2RlKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLnNldEVkaXRUcmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmlnZ2VycykKICAgICAgICBzZWxmLnRhc2tfdGFibGUu"
    "dmVydGljYWxIZWFkZXIoKS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVh"
    "ZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190"
    "YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNl"
    "bGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0Nv"
    "bnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLnRhc2tfdGFi"
    "bGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLnRhc2tfdGFibGUsIDEpCgogICAgICAgIGFjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29y"
    "a3NwYWNlID0gX2dvdGhpY19idG4oIkFERCBUQVNLIikKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrID0gX2dvdGhpY19idG4oIkNPTVBMRVRFIFNF"
    "TEVDVEVEIikKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzayA9IF9nb3RoaWNfYnRuKCJDQU5DRUwgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX3Rv"
    "Z2dsZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiU0hPVyBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCA9IF9nb3RoaWNf"
    "YnRuKCJQVVJHRSBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fYWRkX2Vk"
    "aXRvcl9vcGVuKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkKQogICAg"
    "ICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xl"
    "X2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJsZWQoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBmb3IgYnRuIGluICgKICAgICAgICAgICAgc2VsZi5idG5fYWRk"
    "X3Rhc2tfd29ya3NwYWNlLAogICAgICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzaywKICAg"
    "ICAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkLAogICAgICAgICk6CiAgICAg"
    "ICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KGJ0bikKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChhY3Rpb25zKQogICAgICAgIHNlbGYud29ya3Nw"
    "YWNlX3N0YWNrLmFkZFdpZGdldChub3JtYWwpCgogICAgICAgIGVkaXRvciA9IFFXaWRnZXQoKQogICAgICAgIGVkaXRvcl9sYXlvdXQgPSBRVkJveExheW91"
    "dChlZGl0b3IpCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldFNw"
    "YWNpbmcoNCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBUQVNLIEVESVRPUiDigJQgR09PR0xFLUZJUlNUIikp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29n"
    "bGUgQ2FsZW5kYXIuIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAgICAgKQog"
    "ICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFt"
    "ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiVGFzayBOYW1lIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRQbGFjZWhvbGRlclRl"
    "eHQoIlN0YXJ0IERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9lbmRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBEYXRlIChZ"
    "WVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRf"
    "dGltZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24gPSBRTGluZUVkaXQo"
    "KQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24uc2V0UGxhY2Vob2xkZXJUZXh0KCJMb2NhdGlvbiAob3B0aW9uYWwpIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3JlY3VycmVuY2UgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRQbGFjZWhvbGRlclRl"
    "eHQoIlJlY3VycmVuY2UgUlJVTEUgKG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9hbGxfZGF5ID0gUUNoZWNrQm94KCJBbGwtZGF5IikK"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWNlaG9sZGVy"
    "VGV4dCgiTm90ZXMiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0TWF4aW11bUhlaWdodCg5MCkKICAgICAgICBmb3Igd2lkZ2V0IGluICgK"
    "ICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUsCiAgICAgICAgICAgIHNl"
    "bGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2Vk"
    "aXRvcl9lbmRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJl"
    "bmNlLAogICAgICAgICk6CiAgICAgICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9ub3RlcywgMSkKICAg"
    "ICAgICBlZGl0b3JfYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCJTQVZFIikKICAgICAgICBidG5fY2Fu"
    "Y2VsID0gX2dvdGhpY19idG4oIkNBTkNFTCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9zYXZlKQogICAgICAg"
    "IGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9z"
    "YXZlKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFN0cmV0Y2goMSkKICAg"
    "ICAgICBlZGl0b3JfbGF5b3V0LmFkZExheW91dChlZGl0b3JfYWN0aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQoZWRpdG9y"
    "KQoKICAgICAgICBzZWxmLm5vcm1hbF93b3Jrc3BhY2UgPSBub3JtYWwKICAgICAgICBzZWxmLmVkaXRvcl93b3Jrc3BhY2UgPSBlZGl0b3IKICAgICAgICBz"
    "ZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCiAgICBkZWYgX3VwZGF0ZV9hY3Rpb25fYnV0dG9u"
    "X3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZW5hYmxlZCA9IGJvb2woc2VsZi5zZWxlY3RlZF90YXNrX2lkcygpKQogICAgICAgIHNlbGYuYnRuX2Nv"
    "bXBsZXRlX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKCiAgICBkZWYg"
    "c2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlkczogbGlzdFtzdHJdID0gW10KICAgICAgICBmb3IgciBpbiByYW5nZShz"
    "ZWxmLnRhc2tfdGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gc2VsZi50YXNrX3RhYmxlLml0ZW0ociwgMCkKICAgICAgICAg"
    "ICAgaWYgc3RhdHVzX2l0ZW0gaXMgTm9uZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdCBzdGF0dXNfaXRlbS5pc1NlbGVj"
    "dGVkKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICB0YXNrX2lkID0gc3RhdHVzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNl"
    "clJvbGUpCiAgICAgICAgICAgIGlmIHRhc2tfaWQgYW5kIHRhc2tfaWQgbm90IGluIGlkczoKICAgICAgICAgICAgICAgIGlkcy5hcHBlbmQodGFza19pZCkK"
    "ICAgICAgICByZXR1cm4gaWRzCgogICAgZGVmIGxvYWRfdGFza3Moc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi50YXNr"
    "X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIHJvdyA9IHNlbGYudGFza190YWJsZS5yb3dDb3Vu"
    "dCgpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5pbnNlcnRSb3cocm93KQogICAgICAgICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1cyIpIG9y"
    "ICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaWNvbiA9ICLimJEiIGlmIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQi"
    "fSBlbHNlICLigKIiCiAgICAgICAgICAgIGR1ZSA9ICh0YXNrLmdldCgiZHVlX2F0Iikgb3IgIiIpLnJlcGxhY2UoIlQiLCAiICIpCiAgICAgICAgICAgIHRl"
    "eHQgPSAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpIG9yICJSZW1pbmRlciIKICAgICAgICAgICAgc291cmNlID0gKHRhc2suZ2V0"
    "KCJzb3VyY2UiKSBvciAibG9jYWwiKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShmIntzdGF0dXNfaWNvbn0g"
    "e3N0YXR1c30iKQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgdGFzay5nZXQoImlkIikpCiAgICAg"
    "ICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMCwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJv"
    "dywgMSwgUVRhYmxlV2lkZ2V0SXRlbShkdWUpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0ZW0o"
    "dGV4dCkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzb3VyY2UpKQogICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsLnNldFRleHQoZiJMb2FkZWQge2xlbih0YXNrcyl9IHRhc2socykuIikKICAgICAgICBzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRvbl9z"
    "dGF0ZSgpCgogICAgZGVmIF9kaWFnKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGlmIHNlbGYuX2RpYWdfbG9nZ2VyOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIobWVzc2FnZSwgbGV2ZWwpCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGRlZiBzdG9wX3JlZnJlc2hfd29ya2VyKHNlbGYsIHJlYXNvbjogc3RyID0gIiIpIC0+IE5v"
    "bmU6CiAgICAgICAgdGhyZWFkID0gZ2V0YXR0cihzZWxmLCAiX3JlZnJlc2hfdGhyZWFkIiwgTm9uZSkKICAgICAgICBpZiB0aHJlYWQgaXMgbm90IE5vbmUg"
    "YW5kIGhhc2F0dHIodGhyZWFkLCAiaXNSdW5uaW5nIikgYW5kIHRocmVhZC5pc1J1bm5pbmcoKToKICAgICAgICAgICAgc2VsZi5fZGlhZygKICAgICAgICAg"
    "ICAgICAgIGYiW1RBU0tTXVtUSFJFQURdW1dBUk5dIHN0b3AgcmVxdWVzdGVkIGZvciByZWZyZXNoIHdvcmtlciByZWFzb249e3JlYXNvbiBvciAndW5zcGVj"
    "aWZpZWQnfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdGhyZWFkLnJl"
    "cXVlc3RJbnRlcnJ1cHRpb24oKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICB0aHJlYWQucXVpdCgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAg"
    "IHRocmVhZC53YWl0KDIwMDApCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBpZiBub3QgY2FsbGFibGUoc2VsZi5fdGFza3NfcHJvdmlkZXIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNl"
    "bGYubG9hZF90YXNrcyhzZWxmLl90YXNrc19wcm92aWRlcigpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWcoZiJbVEFTS1NdW1RBQl1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29y"
    "a2VyKHJlYXNvbj0idGFza3NfdGFiX3JlZnJlc2hfZXhjZXB0aW9uIikKCiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfY2xvc2UiKQogICAgICAgIHN1cGVyKCkuY2xvc2VFdmVudChldmVudCkKCiAg"
    "ICBkZWYgc2V0X3Nob3dfY29tcGxldGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQgPSBib29s"
    "KGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5zZXRUZXh0KCJISURFIENPTVBMRVRFRCIgaWYgc2VsZi5fc2hvd19jb21wbGV0"
    "ZWQgZWxzZSAiU0hPVyBDT01QTEVURUQiKQoKICAgIGRlZiBzZXRfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToK"
    "ICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX1RFWFRfRElNCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge2NvbG9yfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "cGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0VGV4dCh0ZXh0KQoKICAgIGRlZiBvcGVu"
    "X2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5lZGl0b3Jfd29ya3NwYWNl"
    "KQoKICAgIGRlZiBjbG9zZV9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYu"
    "bm9ybWFsX3dvcmtzcGFjZSkKCgpjbGFzcyBTZWxmVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hJ3MgaW50ZXJuYWwgZGlhbG9ndWUgc3BhY2Uu"
    "CiAgICBSZWNlaXZlczogaWRsZSBuYXJyYXRpdmUgb3V0cHV0LCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zLAogICAgICAgICAgICAgIFBvSSBsaXN0IGZy"
    "b20gZGFpbHkgcmVmbGVjdGlvbiwgdW5hbnN3ZXJlZCBxdWVzdGlvbiBmbGFncywKICAgICAgICAgICAgICBqb3VybmFsIGxvYWQgbm90aWZpY2F0aW9ucy4K"
    "ICAgIFJlYWQtb25seSBkaXNwbGF5LiBTZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIgYWx3YXlzLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAg"
    "ICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacgSU5ORVIgU0FOQ1RVTSDigJQge0RFQ0tfTkFNRS51cHBlcigpfSdTIFBSSVZB"
    "VEUgVEhPVUdIVFMiKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIu"
    "c2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0"
    "Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlz"
    "cGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfUFVSUExFX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBh"
    "ZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGFwcGVuZChzZWxmLCBsYWJl"
    "bDogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAg"
    "ICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJOQVJSQVRJVkUiOiAgQ19HT0xELAogICAgICAgICAgICAiUkVGTEVDVElPTiI6IENfUFVSUExFLAogICAgICAg"
    "ICAgICAiSk9VUk5BTCI6ICAgIENfU0lMVkVSLAogICAgICAgICAgICAiUE9JIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICJTWVNURU0iOiAg"
    "ICAgQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBjb2xvcnMuZ2V0KGxhYmVsLnVwcGVyKCksIENfR09MRCkKICAgICAgICBzZWxmLl9k"
    "aXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAg"
    "ICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4n"
    "CiAgICAgICAgICAgIGYn4p2nIHtsYWJlbH08L3NwYW4+PGJyPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dGV4dH08"
    "L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgiIikKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFy"
    "KCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGNs"
    "ZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgRElBR05PU1RJQ1MgVEFCIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEaWFnbm9zdGlj"
    "c1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgQmFja2VuZCBkaWFnbm9zdGljcyBkaXNwbGF5LgogICAgUmVjZWl2ZXM6IGhhcmR3YXJlIGRldGVjdGlvbiBy"
    "ZXN1bHRzLCBkZXBlbmRlbmN5IGNoZWNrIHJlc3VsdHMsCiAgICAgICAgICAgICAgQVBJIGVycm9ycywgc3luYyBmYWlsdXJlcywgdGltZXIgZXZlbnRzLCBq"
    "b3VybmFsIGxvYWQgbm90aWNlcywKICAgICAgICAgICAgICBtb2RlbCBsb2FkIHN0YXR1cywgR29vZ2xlIGF1dGggZXZlbnRzLgogICAgQWx3YXlzIHNlcGFy"
    "YXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25f"
    "bGJsKCLinacgRElBR05PU1RJQ1Mg4oCUIFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19idG4oIuKc"
    "lyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290"
    "LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1"
    "ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19T"
    "SUxWRVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiAnQ291cmll"
    "ciBOZXcnLCBtb25vc3BhY2U7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGxvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6"
    "CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAgICAgICAg"
    "ICAgICJJTkZPIjogIENfU0lMVkVSLAogICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAogICAgICAgICAgICAiV0FSTiI6ICBDX0dPTEQsCiAgICAgICAg"
    "ICAgICJFUlJPUiI6IENfQkxPT0QsCiAgICAgICAgICAgICJERUJVRyI6IENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gbGV2ZWxfY29s"
    "b3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZFUikKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0i"
    "Y29sb3I6e0NfVEVYVF9ESU19OyI+W3t0aW1lc3RhbXB9XTwvc3Bhbj4gJwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e21l"
    "c3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBsb2dfbWFueShzZWxmLCBtZXNzYWdlczogbGlz"
    "dFtzdHJdLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXM6CiAgICAgICAgICAgIGx2bCA9IGxldmVs"
    "CiAgICAgICAgICAgIGlmICLinJMiIGluIG1zZzogICAgbHZsID0gIk9LIgogICAgICAgICAgICBlbGlmICLinJciIGluIG1zZzogIGx2bCA9ICJXQVJOIgog"
    "ICAgICAgICAgICBlbGlmICJFUlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2bCA9ICJFUlJPUiIKICAgICAgICAgICAgc2VsZi5sb2cobXNnLCBsdmwpCgogICAg"
    "ZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhbmQgY29kZSBsZXNzb25zIGJyb3dzZXIuCiAgICBB"
    "ZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRlIGxlc3NvbnMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVhcm5lZERCIiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91"
    "aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNl"
    "bGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBGaWx0"
    "ZXIgYmFyCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9zZWFyY2ggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYu"
    "X3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNlYXJjaCBsZXNzb25zLi4uIikKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgpCiAg"
    "ICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuYWRkSXRlbXMoWyJBbGwiLCAiTFNMIiwgIlB5dGhvbiIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJKYXZhU2NyaXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5fc2VhcmNoLnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZy"
    "ZXNoKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmaWx0ZXJfcm93"
    "LmFkZFdpZGdldChRTGFiZWwoIlNlYXJjaDoiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9zZWFyY2gsIDEpCiAgICAgICAgZmlsdGVy"
    "X3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJMYW5ndWFnZToiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikKICAgICAg"
    "ICByb290LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0"
    "bigi4pymIEFkZCBMZXNzb24iKQogICAgICAgIGJ0bl9kZWwgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGJ0bl9kZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBidG5fYmFyLmFkZFdp"
    "ZGdldChidG5fYWRkKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290"
    "LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6"
    "b250YWxIZWFkZXJMYWJlbHMoCiAgICAgICAgICAgIFsiTGFuZ3VhZ2UiLCAiUmVmZXJlbmNlIEtleSIsICJTdW1tYXJ5IiwgIkVudmlyb25tZW50Il0KICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0"
    "ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hh"
    "bmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBVc2Ugc3BsaXR0ZXIgYmV0d2VlbiB0YWJsZSBhbmQgZGV0YWlsCiAgICAgICAgc3Bs"
    "aXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAg"
    "ICAjIERldGFpbCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBkZXRhaWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGV0"
    "YWlsX3dpZGdldCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0"
    "U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIEZVTEwgUlVMRSIpKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZSA9IF9n"
    "b3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVs"
    "ZS5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnRvZ2dsZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZWRpdF9tb2RlKQog"
    "ICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRGaXhlZFdpZHRo"
    "KDUwKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fZWRpdF9ydWxlKQogICAgICAgIGRl"
    "dGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlX3J1bGUpCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hlYWRlcikK"
    "CiAgICAgICAgc2VsZi5fZGV0YWlsID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9k"
    "ZXRhaWwuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0YWlsX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZGV0YWlsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChkZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNl"
    "dFNpemVzKFszMDAsIDE4MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0g"
    "PSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcSAgICA9IHNl"
    "bGYuX3NlYXJjaC50ZXh0KCkKICAgICAgICBsYW5nID0gc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHQoKQogICAgICAgIGxhbmcgPSAiIiBpZiBsYW5n"
    "ID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAgIHNlbGYuX3JlY29yZHMgPSBzZWxmLl9kYi5zZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxl"
    "LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAg"
    "ICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2UiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwg"
    "MSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgicmVmZXJlbmNlX2tleSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRJdGVtKHIsIDMsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImVudmlyb25tZW50IiwiIikpKQoKICAgIGRlZiBf"
    "b25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3cg"
    "PSByb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAg"
    "ICAgICAgIHNlbGYuX2RldGFpbC5zZXRQbGFpblRleHQoCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiArCiAgICAg"
    "ICAgICAgICAgICAoIlJlc29sdXRpb246ICIgKyByZWMuZ2V0KCJyZXNvbHV0aW9uIiwiIikgaWYgcmVjLmdldCgicmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgIyBSZXNldCBlZGl0IG1vZGUgb24gbmV3IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxl"
    "LnNldENoZWNrZWQoRmFsc2UpCgogICAgZGVmIF90b2dnbGVfZWRpdF9tb2RlKHNlbGYsIGVkaXRpbmc6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "ZGV0YWlsLnNldFJlYWRPbmx5KG5vdCBlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShlZGl0aW5nKQogICAgICAgIHNl"
    "bGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2VsIiBpZiBlZGl0aW5nIGVsc2UgIkVkaXQiKQogICAgICAgIGlmIGVkaXRpbmc6CiAgICAgICAgICAg"
    "IHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAg"
    "ICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rl"
    "dGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBm"
    "b250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBSZWxvYWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5j"
    "ZWwKICAgICAgICAgICAgc2VsZi5fb25fc2VsZWN0KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2Vs"
    "Zi5fZWRpdGluZ19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2RldGFpbC50"
    "b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgIyBTcGxpdCByZXNvbHV0aW9uIGJhY2sgb3V0IGlmIHByZXNlbnQKICAgICAgICAgICAgaWYgIlxu"
    "XG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAgICAgICAgICAgICBwYXJ0cyA9IHRleHQuc3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAg"
    "ICAgICAgICAgZnVsbF9ydWxlICA9IHBhcnRzWzBdLnN0cmlwKCkKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBwYXJ0c1sxXS5zdHJpcCgpCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gdGV4dAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHNlbGYuX3JlY29yZHNb"
    "cm93XS5nZXQoInJlc29sdXRpb24iLCAiIikKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJmdWxsX3J1bGUiXSAgPSBmdWxsX3J1bGUKICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJyZXNvbHV0aW9uIl0gPSByZXNvbHV0aW9uCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX2RiLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxl"
    "KCJBZGQgTGVzc29uIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAg"
    "IGRsZy5yZXNpemUoNTAwLCA0MDApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBlbnYgID0gUUxpbmVFZGl0KCJMU0wiKQogICAg"
    "ICAgIGxhbmcgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgcmVmICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc3VtbSA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "cnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVtSGVpZ2h0KDEwMCkKICAgICAgICByZXMgID0gUUxpbmVFZGl0KCkKICAgICAgICBs"
    "aW5rID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3IgbGFiZWwsIHcgaW4gWwogICAgICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgiTGFuZ3VhZ2U6"
    "IiwgbGFuZyksCiAgICAgICAgICAgICgiUmVmZXJlbmNlIEtleToiLCByZWYpLCAoIlN1bW1hcnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBSdWxl"
    "OiIsIHJ1bGUpLCAoIlJlc29sdXRpb246IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06CiAgICAgICAgICAgIGZvcm0u"
    "YWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3Ro"
    "aWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAg"
    "ICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVj"
    "KCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9kYi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9ubWVudD1l"
    "bnYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgcmVmZXJlbmNl"
    "X2tleT1yZWYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBzdW1tYXJ5PXN1bW0udGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBmdWxs"
    "X3J1bGU9cnVsZS50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uPXJlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgIGxpbms9bGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVs"
    "ZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5f"
    "cmVjb3Jkcyk6CiAgICAgICAgICAgIHJlY19pZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImlkIiwiIikKICAgICAgICAgICAgcmVwbHkgPSBRTWVzc2Fn"
    "ZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTGVzc29uIiwKICAgICAgICAgICAgICAgICJEZWxldGUgdGhpcyBsZXNzb24/"
    "IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJk"
    "QnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZGIuZGVsZXRlKHJlY19pZCkKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgTU9EVUxFIFRSQUNLRVIgVEFC"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2R1"
    "bGVUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hbCBtb2R1bGUgcGlwZWxpbmUgdHJhY2tlci4KICAgIFRyYWNrIHBsYW5uZWQvaW4t"
    "cHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBhcyB0aGV5IGFyZSBkZXNpZ25lZC4KICAgIEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNjcmlwdGlv"
    "biwgTm90ZXMuCiAgICBFeHBvcnQgdG8gVFhUIGZvciBwYXN0aW5nIGludG8gc2Vzc2lvbnMuCiAgICBJbXBvcnQ6IHBhc3RlIGEgZmluYWxpemVkIHNwZWMs"
    "IGl0IHBhcnNlcyBuYW1lIGFuZCBkZXRhaWxzLgogICAgVGhpcyBpcyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5lY3RlZCB0byBkZWNrX2J1aWxk"
    "ZXIncyBNT0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIsICJEZXNpZ25pbmciLCAiUmVhZHkgdG8gQnVpbGQiLCAiUGFy"
    "dGlhbCIsICJCdWlsdCJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAg"
    "ICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibW9kdWxlX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlz"
    "dFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRu"
    "X2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9kdWxlIikKICAgICAgICBzZWxmLl9idG5fZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCBU"
    "WFQiKQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNwZWMiKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRk"
    "LCBzZWxmLl9idG5fZWRpdCwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCwgc2VsZi5fYnRuX2ltcG9ydCk6"
    "CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDgwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJ0bl9iYXIu"
    "YWRkV2lkZ2V0KGIpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl9i"
    "dG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQp"
    "CiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBzZWxmLl9idG5faW1wb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19pbXBvcnQpCgogICAg"
    "ICAgICMgVGFibGUKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFk"
    "ZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3JpcHRpb24iXSkKICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0Q29sdW1uV2lkdGgoMCwgMTYwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcu"
    "U2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFNwbGl0dGVyCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24uVmVy"
    "dGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIE5vdGVzIHBhbmVsCiAgICAgICAgbm90ZXNfd2lkZ2V0"
    "ID0gUVdpZGdldCgpCiAgICAgICAgbm90ZXNfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm90ZXNfd2lkZ2V0KQogICAgICAgIG5vdGVzX2xheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQo"
    "X3NlY3Rpb25fbGJsKCLinacgTk9URVMiKSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9ub3Rlc19k"
    "aXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9u"
    "b3Rlc19kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQt"
    "c2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ub3Rlc19kaXNwbGF5KQog"
    "ICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChub3Rlc193aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzI1MCwgMTUwXSkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgIyBDb3VudCBsYWJlbAogICAgICAgIHNlbGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikKICAgICAg"
    "ICBzZWxmLl9jb3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvdW50X2xibCkKCiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAg"
    "ICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0ocmVj"
    "LmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpKQog"
    "ICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAgICAgICAgIklkZWEiOiAgICAgICAg"
    "ICAgICBDX1RFWFRfRElNLAogICAgICAgICAgICAgICAgIkRlc2lnbmluZyI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAgICAgIlJlYWR5IHRv"
    "IEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAgICAgICAgICAgICJQYXJ0aWFsIjogICAgICAgICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0"
    "IjogICAgICAgICAgICBDX0dSRUVOLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVncm91bmQoCiAgICAgICAgICAgICAg"
    "ICBRQ29sb3Ioc3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpLCBDX1RFWFRfRElNKSkKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAg"
    "ICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwgIiIpWzo4MF0pKQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAgZm9yIHJl"
    "YyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBzID0gcmVjLmdldCgic3RhdHVzIiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10gPSBjb3Vu"
    "dHMuZ2V0KHMsIDApICsgMQogICAgICAgIGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfToge259IiBmb3IgcywgbiBpbiBjb3VudHMuaXRlbXMoKSkKICAg"
    "ICAgICBzZWxmLl9jb3VudF9sYmwuc2V0VGV4dCgKICAgICAgICAgICAgZiJUb3RhbDoge2xlbihzZWxmLl9yZWNvcmRzKX0gICB7Y291bnRfc3RyfSIKICAg"
    "ICAgICApCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX25v"
    "dGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwgIiIpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fb3Blbl9lZGl0X2RpYWxvZygpCgogICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJv"
    "dygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coc2VsZi5fcmVj"
    "b3Jkc1tyb3ddLCByb3cpCgogICAgZGVmIF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUsIHJvdzogaW50ID0gLTEpIC0+IE5vbmU6"
    "CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kdWxlIiBpZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7"
    "cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikK"
    "ICAgICAgICBkbGcucmVzaXplKDU0MCwgNDQwKQogICAgICAgIGZvcm0gPSBRVkJveExheW91dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGluZUVk"
    "aXQocmVjLmdldCgibmFtZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJNb2R1bGUgbmFtZSIp"
    "CgogICAgICAgIHN0YXR1c19jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2NvbWJvLmFkZEl0ZW1zKHNlbGYuU1RBVFVTRVMpCiAgICAgICAg"
    "aWYgcmVjOgogICAgICAgICAgICBpZHggPSBzdGF0dXNfY29tYm8uZmluZFRleHQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAgICBpZiBp"
    "ZHggPj0gMDoKICAgICAgICAgICAgICAgIHN0YXR1c19jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQoKICAgICAgICBkZXNjX2ZpZWxkID0gUUxpbmVFZGl0"
    "KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9uZS1saW5l"
    "IGRlc2NyaXB0aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWluVGV4dChyZWMuZ2V0"
    "KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIkZ1bGwgbm90"
    "ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVudHMsIGVkZ2UgY2FzZXMuLi4iCiAgICAgICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1I"
    "ZWlnaHQoMjAwKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxkKSwKICAgICAgICAgICAg"
    "KCJTdGF0dXM6Iiwgc3RhdHVzX2NvbWJvKSwKICAgICAgICAgICAgKCJEZXNjcmlwdGlvbjoiLCBkZXNjX2ZpZWxkKSwKICAgICAgICAgICAgKCJOb3Rlczoi"
    "LCBub3Rlc19maWVsZCksCiAgICAgICAgXToKICAgICAgICAgICAgcm93X2xheW91dCA9IFFIQm94TGF5b3V0KCkKICAgICAgICAgICAgbGJsID0gUUxhYmVs"
    "KGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4ZWRXaWR0aCg5MCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRnZXQobGJsKQogICAgICAgICAg"
    "ICByb3dfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgICAgIGZvcm0uYWRkTGF5b3V0KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9yb3cgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgICA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNh"
    "bmNlbCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxn"
    "LnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAg"
    "IGZvcm0uYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAg"
    "ICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgcmVjLmdldCgiaWQiLCBzdHIodXVpZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ug"
    "c3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAibmFtZSI6ICAgICAgICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAg"
    "ICAgInN0YXR1cyI6ICAgICAgc3RhdHVzX2NvbWJvLmN1cnJlbnRUZXh0KCksCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxkLnRl"
    "eHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpKSBpZiByZWMgZWxzZSBkYXRldGltZS5u"
    "b3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9"
    "CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3Rh"
    "YmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICBuYW1lID0gc2VsZi5fcmVjb3Jk"
    "c1tyb3ddLmdldCgibmFtZSIsInRoaXMgbW9kdWxlIikKICAgICAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAg"
    "IHNlbGYsICJEZWxldGUgTW9kdWxlIiwKICAgICAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAg"
    "ICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAg"
    "ICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJm"
    "dGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYibW9kdWxlc197dHN9LnR4dCIKICAgICAgICAgICAg"
    "bGluZXMgPSBbCiAgICAgICAgICAgICAgICAiRUNITyBERUNLIOKAlCBNT0RVTEUgVFJBQ0tFUiBFWFBPUlQiLAogICAgICAgICAgICAgICAgZiJFeHBvcnRl"
    "ZDoge2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAgICAgICAgICAgICBmIlRvdGFsIG1vZHVsZXM6IHtsZW4o"
    "c2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAgICAgICI9IiAqIDYwLAogICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgIF0KICAgICAgICAgICAg"
    "Zm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgbGluZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVMRToge3Jl"
    "Yy5nZXQoJ25hbWUnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiU3RhdHVzOiB7cmVjLmdldCgnc3RhdHVzJywnJyl9IiwKICAgICAgICAgICAgICAg"
    "ICAgICBmIkRlc2NyaXB0aW9uOiB7cmVjLmdldCgnZGVzY3JpcHRpb24nLCcnKX0iLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAg"
    "ICAgICJOb3RlczoiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAg"
    "ICAgICAgICAgIi0iICogNDAsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90"
    "ZXh0KCJcbiIuam9pbihsaW5lcyksIGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIu"
    "am9pbihsaW5lcykpCiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwKICAgICAg"
    "ICAgICAgICAgIGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9XG5cbkFsc28gY29waWVkIHRvIGNsaXBib2FyZC4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoc2VsZiwgIkV4cG9ydCBFcnJvciIs"
    "IHN0cihlKSkKCiAgICBkZWYgX2RvX2ltcG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkltcG9ydCBhIG1vZHVsZSBzcGVjIGZyb20gY2xpcGJvYXJk"
    "IG9yIHR5cGVkIHRleHQuIiIiCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1vZHVsZSBT"
    "cGVjIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNp"
    "emUoNTAwLCAzNDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKAogICAgICAgICAg"
    "ICAiUGFzdGUgYSBtb2R1bGUgc3BlYyBiZWxvdy5cbiIKICAgICAgICAgICAgIkZpcnN0IGxpbmUgd2lsbCBiZSB1c2VkIGFzIHRoZSBtb2R1bGUgbmFtZS4i"
    "CiAgICAgICAgKSkKICAgICAgICB0ZXh0X2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiUGFzdGUg"
    "bW9kdWxlIHNwZWMgaGVyZS4uLiIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgYnRuX29rICAgICA9IF9nb3RoaWNfYnRuKCJJbXBvcnQiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikK"
    "ICAgICAgICBidG5fb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkK"
    "ICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fb2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBsYXlvdXQuYWRk"
    "TGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByYXcgPSB0"
    "ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAg"
    "IGxpbmVzID0gcmF3LnNwbGl0bGluZXMoKQogICAgICAgICAgICAjIEZpcnN0IG5vbi1lbXB0eSBsaW5lID0gbmFtZQogICAgICAgICAgICBuYW1lID0gIiIK"
    "ICAgICAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICAgICBpZiBsaW5lLnN0cmlwKCk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9"
    "IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAg"
    "ICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVbOjYwXSwKICAgICAgICAgICAgICAgICJzdGF0dXMi"
    "OiAgICAgICJJZGVhIiwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6ICIiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgcmF3LAogICAg"
    "ICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRl"
    "dGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIFBBU1MgNSBDT01Q"
    "TEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKIyBBbGwgdGFiIGNvbnRlbnQgY2xhc3NlcyBkZWZpbmVkLgojIFNMU2NhbnNUYWI6IHJlYnVpbHQg4oCUIERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZp"
    "eGVkLCB0aW1lc3RhbXAgcGFyc2VyIGZpeGVkLAojICAgICAgICAgICAgIGNhcmQvZ3JpbW9pcmUgc3R5bGUsIGNvcHktdG8tY2xpcGJvYXJkIGNvbnRleHQg"
    "bWVudS4KIyBTTENvbW1hbmRzVGFiOiBnb3RoaWMgdGFibGUsIOKniSBDb3B5IENvbW1hbmQgYnV0dG9uLgojIEpvYlRyYWNrZXJUYWI6IGZ1bGwgcmVidWls"
    "ZCDigJQgbXVsdGktc2VsZWN0LCBhcmNoaXZlL3Jlc3RvcmUsIENTVi9UU1YgZXhwb3J0LgojIFNlbGZUYWI6IGlubmVyIHNhbmN0dW0gZm9yIGlkbGUgbmFy"
    "cmF0aXZlIGFuZCByZWZsZWN0aW9uIG91dHB1dC4KIyBEaWFnbm9zdGljc1RhYjogc3RydWN0dXJlZCBsb2cgd2l0aCBsZXZlbC1jb2xvcmVkIG91dHB1dC4K"
    "IyBMZXNzb25zVGFiOiBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYnJvd3NlciB3aXRoIGFkZC9kZWxldGUvc2VhcmNoLgojCiMgTmV4dDogUGFzcyA2IOKAlCBN"
    "YWluIFdpbmRvdwojIChNb3JnYW5uYURlY2sgY2xhc3MsIGZ1bGwgbGF5b3V0LCBBUFNjaGVkdWxlciwgZmlyc3QtcnVuIGZsb3csCiMgIGRlcGVuZGVuY3kg"
    "Ym9vdHN0cmFwLCBzaG9ydGN1dCBjcmVhdGlvbiwgc3RhcnR1cCBzZXF1ZW5jZSkKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNjogTUFJTiBXSU5ET1cgJiBFTlRSWSBQT0lOVAojCiMgQ29udGFpbnM6CiMg"
    "ICBib290c3RyYXBfY2hlY2soKSAgICAg4oCUIGRlcGVuZGVuY3kgdmFsaWRhdGlvbiArIGF1dG8taW5zdGFsbCBiZWZvcmUgVUkKIyAgIEZpcnN0UnVuRGlh"
    "bG9nICAgICAgICDigJQgbW9kZWwgcGF0aCArIGNvbm5lY3Rpb24gdHlwZSBzZWxlY3Rpb24KIyAgIEpvdXJuYWxTaWRlYmFyICAgICAgICDigJQgY29sbGFw"
    "c2libGUgbGVmdCBzaWRlYmFyIChzZXNzaW9uIGJyb3dzZXIgKyBqb3VybmFsKQojICAgVG9ycG9yUGFuZWwgICAgICAgICAgIOKAlCBBV0FLRSAvIEFVVE8g"
    "LyBTVVNQRU5EIHN0YXRlIHRvZ2dsZQojICAgTW9yZ2FubmFEZWNrICAgICAgICAgIOKAlCBtYWluIHdpbmRvdywgZnVsbCBsYXlvdXQsIGFsbCBzaWduYWwg"
    "Y29ubmVjdGlvbnMKIyAgIG1haW4oKSAgICAgICAgICAgICAgICDigJQgZW50cnkgcG9pbnQgd2l0aCBib290c3RyYXAgc2VxdWVuY2UKIyDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCBzdWJwcm9jZXNzCgoKIyDilIDilIAgUFJFLUxBVU5DSCBE"
    "RVBFTkRFTkNZIEJPT1RTVFJBUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJvb3RzdHJhcF9jaGVjaygpIC0+IE5vbmU6CiAg"
    "ICAiIiIKICAgIFJ1bnMgQkVGT1JFIFFBcHBsaWNhdGlvbiBpcyBjcmVhdGVkLgogICAgQ2hlY2tzIGZvciBQeVNpZGU2IHNlcGFyYXRlbHkgKGNhbid0IHNo"
    "b3cgR1VJIHdpdGhvdXQgaXQpLgogICAgQXV0by1pbnN0YWxscyBhbGwgb3RoZXIgbWlzc2luZyBub24tY3JpdGljYWwgZGVwcyB2aWEgcGlwLgogICAgVmFs"
    "aWRhdGVzIGluc3RhbGxzIHN1Y2NlZWRlZC4KICAgIFdyaXRlcyByZXN1bHRzIHRvIGEgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIHRvIHBp"
    "Y2sgdXAuCiAgICAiIiIKICAgICMg4pSA4pSAIFN0ZXAgMTogQ2hlY2sgUHlTaWRlNiAoY2FuJ3QgYXV0by1pbnN0YWxsIHdpdGhvdXQgaXQgYWxyZWFkeSBw"
    "cmVzZW50KSDilIAKICAgIHRyeToKICAgICAgICBpbXBvcnQgUHlTaWRlNiAgIyBub3FhCiAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgIyBObyBH"
    "VUkgYXZhaWxhYmxlIOKAlCB1c2UgV2luZG93cyBuYXRpdmUgZGlhbG9nIHZpYSBjdHlwZXMKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydCBjdHlw"
    "ZXMKICAgICAgICAgICAgY3R5cGVzLndpbmRsbC51c2VyMzIuTWVzc2FnZUJveFcoCiAgICAgICAgICAgICAgICAwLAogICAgICAgICAgICAgICAgIlB5U2lk"
    "ZTYgaXMgcmVxdWlyZWQgYnV0IG5vdCBpbnN0YWxsZWQuXG5cbiIKICAgICAgICAgICAgICAgICJPcGVuIGEgdGVybWluYWwgYW5kIHJ1bjpcblxuIgogICAg"
    "ICAgICAgICAgICAgIiAgICBwaXAgaW5zdGFsbCBQeVNpZGU2XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhlbiByZXN0YXJ0IHtERUNLX05BTUV9LiIsCiAg"
    "ICAgICAgICAgICAgICBmIntERUNLX05BTUV9IOKAlCBNaXNzaW5nIERlcGVuZGVuY3kiLAogICAgICAgICAgICAgICAgMHgxMCAgIyBNQl9JQ09ORVJST1IK"
    "ICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHByaW50KCJDUklUSUNBTDogUHlTaWRlNiBub3QgaW5zdGFsbGVk"
    "LiBSdW46IHBpcCBpbnN0YWxsIFB5U2lkZTYiKQogICAgICAgIHN5cy5leGl0KDEpCgogICAgIyDilIDilIAgU3RlcCAyOiBBdXRvLWluc3RhbGwgb3RoZXIg"
    "bWlzc2luZyBkZXBzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0FVVE9fSU5TVEFMTCA9IFsKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVs"
    "ZXIiKSwKICAgICAgICAoImxvZ3VydSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAgICAgICAg"
    "ICAgInB5Z2FtZSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJweXdpbjMyIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAg"
    "ICAgICAgICAgICAgInBzdXRpbCIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xl"
    "LWFwaS1weXRob24tY2xpZW50IiwgICJnb29nbGVhcGljbGllbnQiKSwKICAgICAgICAoImdvb2dsZS1hdXRoLW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1"
    "dGhfb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiKSwKICAgIF0KCiAgICBpbXBvcnQgaW1w"
    "b3J0bGliCiAgICBib290c3RyYXBfbG9nID0gW10KCiAgICBmb3IgcGlwX25hbWUsIGltcG9ydF9uYW1lIGluIF9BVVRPX0lOU1RBTEw6CiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoZiJbQk9P"
    "VFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBtaXNzaW5nIOKAlCBpbnN0YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHN1YnByb2Nlc3MucnVuKAogICAgICAgICAgICAgICAgICAgIFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwg"
    "InBpcCIsICJpbnN0YWxsIiwKICAgICAgICAgICAgICAgICAgICAgcGlwX25hbWUsICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRpb24iXSwK"
    "ICAgICAgICAgICAgICAgICAgICBjYXB0dXJlX291dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRpbWVvdXQ9MTIwCiAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICBpZiByZXN1bHQucmV0dXJuY29kZSA9PSAwOgogICAgICAgICAgICAgICAgICAgICMgVmFsaWRhdGUgaXQgYWN0dWFsbHkgaW1wb3J0ZWQgbm93"
    "CiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBf"
    "bmFtZX0gaW5zdGFsbGVkIOKckyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBf"
    "bmFtZX0gaW5zdGFsbCBhcHBlYXJlZCB0byAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInN1Y2NlZWQgYnV0IGltcG9ydCBzdGlsbCBmYWlscyDi"
    "gJQgcmVzdGFydCBtYXkgIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJiZSByZXF1aXJlZC4iCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JP"
    "T1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGZhaWxlZDogIgogICAgICAgICAgICAgICAgICAgICAgICBmIntyZXN1bHQuc3RkZXJyWzoyMDBdfSIKICAg"
    "ICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBzdWJwcm9jZXNzLlRpbWVvdXRFeHBpcmVkOgogICAgICAgICAgICAgICAgYm9vdHN0cmFw"
    "X2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgdGltZWQgb3V0LiIKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZXJyb3I6IHtlfSIKICAgICAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBTdGVw"
    "IDM6IFdyaXRlIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgIHRyeToKICAgICAgICBsb2dfcGF0aCA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50"
    "eHQiCiAgICAgICAgd2l0aCBsb2dfcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZSgiXG4iLmpvaW4o"
    "Ym9vdHN0cmFwX2xvZykpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCgojIOKUgOKUgCBGSVJTVCBSVU4gRElBTE9HIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGaXJzdFJ1bkRp"
    "YWxvZyhRRGlhbG9nKToKICAgICIiIgogICAgU2hvd24gb24gZmlyc3QgbGF1bmNoIHdoZW4gY29uZmlnLmpzb24gZG9lc24ndCBleGlzdC4KICAgIENvbGxl"
    "Y3RzIG1vZGVsIGNvbm5lY3Rpb24gdHlwZSBhbmQgcGF0aC9rZXkuCiAgICBWYWxpZGF0ZXMgY29ubmVjdGlvbiBiZWZvcmUgYWNjZXB0aW5nLgogICAgV3Jp"
    "dGVzIGNvbmZpZy5qc29uIG9uIHN1Y2Nlc3MuCiAgICBDcmVhdGVzIGRlc2t0b3Agc2hvcnRjdXQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoZiLinKYge0RFQ0tfTkFN"
    "RS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCiAgICAgICAgc2VsZi5zZXRGaXhlZFNp"
    "emUoNTIwLCA0MDApCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldFNwYWNpbmcoMTApCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtERUNLX05BTUUudXBwZXIo"
    "KX0g4oCUIEZJUlNUIEFXQUtFTklORyDinKYiKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059"
    "OyBmb250LXNpemU6IDE0cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0"
    "dGVyLXNwYWNpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIHRpdGxlLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KHRpdGxlKQoKICAgICAgICBzdWIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiQ29uZmlndXJlIHRoZSB2ZXNzZWwgYmVmb3Jl"
    "IHtERUNLX05BTUV9IG1heSBhd2FrZW4uXG4iCiAgICAgICAgICAgICJBbGwgc2V0dGluZ3MgYXJlIHN0b3JlZCBsb2NhbGx5LiBOb3RoaW5nIGxlYXZlcyB0"
    "aGlzIG1hY2hpbmUuIgogICAgICAgICkKICAgICAgICBzdWIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc3ViLnNldEFs"
    "aWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHN1YikKCiAgICAgICAgIyDilIDilIAgQ29ubmVj"
    "dGlvbiB0eXBlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIEFJIENPTk5FQ1RJT04gVFlQRSIpKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8u"
    "YWRkSXRlbXMoWwogICAgICAgICAgICAiTG9jYWwgbW9kZWwgZm9sZGVyICh0cmFuc2Zvcm1lcnMpIiwKICAgICAgICAgICAgIk9sbGFtYSAobG9jYWwgc2Vy"
    "dmljZSkiLAogICAgICAgICAgICAiQ2xhdWRlIEFQSSAoQW50aHJvcGljKSIsCiAgICAgICAgICAgICJPcGVuQUkgQVBJIiwKICAgICAgICBdKQogICAgICAg"
    "IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3R5cGVfY2hhbmdlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNlbGYuX3R5cGVfY29tYm8pCgogICAgICAgICMg4pSA4pSAIER5bmFtaWMgY29ubmVjdGlvbiBmaWVsZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5f"
    "c3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCgogICAgICAgICMgUGFnZSAwOiBMb2NhbCBwYXRoCiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9"
    "IFFIQm94TGF5b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2xvY2FsX3BhdGggPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICByIkQ6XEFJXE1vZGVsc1xkb2xwaGluLThiIgog"
    "ICAgICAgICkKICAgICAgICBidG5fYnJvd3NlID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2Jyb3dzZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fYnJvd3NlX21vZGVsKQogICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9sb2NhbF9wYXRoKTsgbDAuYWRkV2lkZ2V0KGJ0bl9icm93c2UpCiAgICAgICAg"
    "c2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIFBhZ2UgMTogT2xsYW1hIG1vZGVsIG5hbWUKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAg"
    "ICAgIGwxID0gUUhCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVs"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwuc2V0UGxhY2Vob2xkZXJUZXh0KCJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgbDEu"
    "YWRkV2lkZ2V0KHNlbGYuX29sbGFtYV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgogICAgICAgICMgUGFnZSAyOiBDbGF1ZGUg"
    "QVBJIGtleQogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwwLDAsMCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJzay1hbnQtLi4uIikKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAg"
    "ICBzZWxmLl9jbGF1ZGVfbW9kZWwgPSBRTGluZUVkaXQoImNsYXVkZS1zb25uZXQtNC02IikKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJBUEkgS2V5"
    "OiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9jbGF1ZGVfa2V5KQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAg"
    "IGwyLmFkZFdpZGdldChzZWxmLl9jbGF1ZGVfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIFBhZ2UgMzogT3Bl"
    "bkFJCiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucygwLDAs"
    "MCwwKQogICAgICAgIHNlbGYuX29haV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLS4u"
    "LiIpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fb2FpX21vZGVs"
    "ID0gUUxpbmVFZGl0KCJncHQtNG8iKQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYu"
    "X29haV9rZXkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX29haV9tb2RlbCkKICAg"
    "ICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrKQoKICAgICAgICAjIOKUgOKUgCBUZXN0"
    "ICsgc3RhdHVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHRlc3Rfcm93ID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIHNlbGYuX2J0bl90ZXN0ID0gX2dvdGhpY19idG4oIlRlc3QgQ29ubmVjdGlvbiIpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3Rlc3RfY29ubmVjdGlvbikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX3N0YXR1c19s"
    "Ymwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl90ZXN0KQogICAgICAg"
    "IHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9zdGF0dXNfbGJsLCAxKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KHRlc3Rfcm93KQoKICAgICAgICAjIOKUgOKU"
    "gCBGYWNlIFBhY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRkFDRSBQQUNLIChvcHRpb25hbCDigJQgWklQIGZpbGUpIikpCiAgICAgICAgZmFjZV9yb3cgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAg"
    "ICAgICAgICBmIkJyb3dzZSB0byB7REVDS19OQU1FfSBmYWNlIHBhY2sgWklQIChvcHRpb25hbCwgY2FuIGFkZCBsYXRlcikiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2ZhY2VfcGF0aC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDZweCAxMHB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2ZhY2UgPSBf"
    "Z290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fZmFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX2ZhY2UpCiAgICAgICAgZmFjZV9yb3cu"
    "YWRkV2lkZ2V0KHNlbGYuX2ZhY2VfcGF0aCkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoYnRuX2ZhY2UpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmFj"
    "ZV9yb3cpCgogICAgICAgICMg4pSA4pSAIFNob3J0Y3V0IG9wdGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zaG9ydGN1dF9jYiA9IFFDaGVja0JveCgKICAgICAgICAgICAgIkNyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IChyZWNvbW1lbmRlZCkiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiLnNldENoZWNrZWQoVHJ1ZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zaG9ydGN1dF9jYikK"
    "CiAgICAgICAgIyDilIDilIAgQnV0dG9ucyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICByb290LmFkZFN0cmV0Y2goKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbiA9IF9n"
    "b3RoaWNfYnRuKCLinKYgQkVHSU4gQVdBS0VOSU5HIikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgYnRuX2Nh"
    "bmNlbCA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLmNsaWNrZWQuY29ubmVjdChzZWxmLmFjY2VwdCkKICAg"
    "ICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChzZWxmLl9idG5fYXdha2VuKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICBkZWYgX29uX3R5cGVfY2hh"
    "bmdlKHNlbGYsIGlkeDogaW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fYnRuX2F3"
    "YWtlbi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiIikKCiAgICBkZWYgX2Jyb3dzZV9tb2RlbChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHBhdGggPSBRRmlsZURpYWxvZy5nZXRFeGlzdGluZ0RpcmVjdG9yeSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBNb2RlbCBG"
    "b2xkZXIiLAogICAgICAgICAgICByIkQ6XEFJXE1vZGVscyIKICAgICAgICApCiAgICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fbG9jYWxfcGF0"
    "aC5zZXRUZXh0KHBhdGgpCgogICAgZGVmIF9icm93c2VfZmFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIF8gPSBRRmlsZURpYWxvZy5nZXRPcGVu"
    "RmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJTZWxlY3QgRmFjZSBQYWNrIFpJUCIsCiAgICAgICAgICAgIHN0cihQYXRoLmhvbWUoKSAvICJEZXNrdG9w"
    "IiksCiAgICAgICAgICAgICJaSVAgRmlsZXMgKCouemlwKSIKICAgICAgICApCiAgICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fZmFjZV9wYXRo"
    "LnNldFRleHQocGF0aCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBmYWNlX3ppcF9wYXRoKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fZmFj"
    "ZV9wYXRoLnRleHQoKS5zdHJpcCgpCgogICAgZGVmIF90ZXN0X2Nvbm5lY3Rpb24oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNl"
    "dFRleHQoIlRlc3RpbmcuLi4iKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9E"
    "SU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBRQXBwbGljYXRpb24ucHJv"
    "Y2Vzc0V2ZW50cygpCgogICAgICAgIGlkeCA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICBvayAgPSBGYWxzZQogICAgICAgIG1z"
    "ZyA9ICIiCgogICAgICAgIGlmIGlkeCA9PSAwOiAgIyBMb2NhbAogICAgICAgICAgICBwYXRoID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgICAgICBpZiBwYXRoIGFuZCBQYXRoKHBhdGgpLmV4aXN0cygpOgogICAgICAgICAgICAgICAgb2sgID0gVHJ1ZQogICAgICAgICAgICAgICAgbXNn"
    "ID0gZiJGb2xkZXIgZm91bmQuIE1vZGVsIHdpbGwgbG9hZCBvbiBzdGFydHVwLiIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIG1zZyA9ICJG"
    "b2xkZXIgbm90IGZvdW5kLiBDaGVjayB0aGUgcGF0aC4iCgogICAgICAgIGVsaWYgaWR4ID09IDE6ICAjIE9sbGFtYQogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAgICAgICAgICAgICAgICAgICAiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkv"
    "dGFncyIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAg"
    "ICAgICAgICAgICAgb2sgICA9IHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgICAgICAgICAgbXNnICA9ICJPbGxhbWEgaXMgcnVubmluZyDinJMiIGlmIG9r"
    "IGVsc2UgIk9sbGFtYSBub3QgcmVzcG9uZGluZy4iCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIG1zZyA9IGYi"
    "T2xsYW1hIG5vdCByZWFjaGFibGU6IHtlfSIKCiAgICAgICAgZWxpZiBpZHggPT0gMjogICMgQ2xhdWRlCiAgICAgICAgICAgIGtleSA9IHNlbGYuX2NsYXVk"
    "ZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgb2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay1hbnQiKSkKICAgICAgICAgICAg"
    "bXNnID0gIkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRlciBhIHZhbGlkIENsYXVkZSBBUEkga2V5LiIKCiAgICAgICAg"
    "ZWxpZiBpZHggPT0gMzogICMgT3BlbkFJCiAgICAgICAgICAgIGtleSA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgb2sgID0g"
    "Ym9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay0iKSkKICAgICAgICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBv"
    "ayBlbHNlICJFbnRlciBhIHZhbGlkIE9wZW5BSSBBUEkga2V5LiIKCiAgICAgICAgY29sb3IgPSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19DUklNU09OCiAgICAg"
    "ICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KG1zZykKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0"
    "bl9hd2FrZW4uc2V0RW5hYmxlZChvaykKCiAgICBkZWYgYnVpbGRfY29uZmlnKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgIiIiQnVpbGQgYW5kIHJldHVybiB1"
    "cGRhdGVkIGNvbmZpZyBkaWN0IGZyb20gZGlhbG9nIHNlbGVjdGlvbnMuIiIiCiAgICAgICAgY2ZnICAgICA9IF9kZWZhdWx0X2NvbmZpZygpCiAgICAgICAg"
    "aWR4ICAgICA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICB0eXBlcyAgID0gWyJsb2NhbCIsICJvbGxhbWEiLCAiY2xhdWRlIiwg"
    "Im9wZW5haSJdCiAgICAgICAgY2ZnWyJtb2RlbCJdWyJ0eXBlIl0gPSB0eXBlc1tpZHhdCgogICAgICAgIGlmIGlkeCA9PSAwOgogICAgICAgICAgICBjZmdb"
    "Im1vZGVsIl1bInBhdGgiXSA9IHNlbGYuX2xvY2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbGlmIGlkeCA9PSAxOgogICAgICAgICAgICBjZmdb"
    "Im1vZGVsIl1bIm9sbGFtYV9tb2RlbCJdID0gc2VsZi5fb2xsYW1hX21vZGVsLnRleHQoKS5zdHJpcCgpIG9yICJkb2xwaGluLTIuNi03YiIKICAgICAgICBl"
    "bGlmIGlkeCA9PSAyOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAg"
    "ICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5fY2xhdWRlX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9k"
    "ZWwiXVsiYXBpX3R5cGUiXSAgPSAiY2xhdWRlIgogICAgICAgIGVsaWYgaWR4ID09IDM6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAg"
    "PSBzZWxmLl9vYWlfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9vYWlfbW9kZWwudGV4"
    "dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJvcGVuYWkiCgogICAgICAgIGNmZ1siZmlyc3RfcnVuIl0gPSBG"
    "YWxzZQogICAgICAgIHJldHVybiBjZmcKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjcmVhdGVfc2hvcnRjdXQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1"
    "cm4gc2VsZi5fc2hvcnRjdXRfY2IuaXNDaGVja2VkKCkKCgojIOKUgOKUgCBKT1VSTkFMIFNJREVCQVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvdXJuYWxTaWRlYmFyKFFXaWRnZXQpOgog"
    "ICAgIiIiCiAgICBDb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgbmV4dCB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KICAgIFRvcDogc2Vzc2lvbiBjb250cm9s"
    "cyAoY3VycmVudCBzZXNzaW9uIG5hbWUsIHNhdmUvbG9hZCBidXR0b25zLAogICAgICAgICBhdXRvc2F2ZSBpbmRpY2F0b3IpLgogICAgQm9keTogc2Nyb2xs"
    "YWJsZSBzZXNzaW9uIGxpc3Qg4oCUIGRhdGUsIEFJIG5hbWUsIG1lc3NhZ2UgY291bnQuCiAgICBDb2xsYXBzZXMgbGVmdHdhcmQgdG8gYSB0aGluIHN0cmlw"
    "LgoKICAgIFNpZ25hbHM6CiAgICAgICAgc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZChzdHIpICAg4oCUIGRhdGUgc3RyaW5nIG9mIHNlc3Npb24gdG8gbG9hZAog"
    "ICAgICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkKCkgICAgIOKAlCByZXR1cm4gdG8gY3VycmVudCBzZXNzaW9uCiAgICAiIiIKCiAgICBzZXNzaW9uX2xv"
    "YWRfcmVxdWVzdGVkICA9IFNpZ25hbChzdHIpCiAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCA9IFNpZ25hbCgpCgogICAgZGVmIF9faW5pdF9fKHNlbGYs"
    "IHNlc3Npb25fbWdyOiAiU2Vzc2lvbk1hbmFnZXIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbl9tZ3IgPSBzZXNzaW9uX21ncgogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFVzZSBhIGhvcml6b250YWwgcm9vdCBsYXlv"
    "dXQg4oCUIGNvbnRlbnQgb24gbGVmdCwgdG9nZ2xlIHN0cmlwIG9uIHJpZ2h0CiAgICAgICAgcm9vdCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9v"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyDilIDilIAgQ29sbGFwc2UgdG9n"
    "Z2xlIHN0cmlwIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX3Rv"
    "Z2dsZV9zdHJpcC5zZXRGaXhlZFdpZHRoKDIwKQogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGJvcmRlci1yaWdodDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHRzX2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKICAgICAgICB0c19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDgsIDAsIDgpCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldEZpeGVkU2l6ZSgxOCwgMTgpCiAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQogICAgICAgIHRzX2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fdG9nZ2xlX2J0bikKICAgICAgICB0c19sYXlvdXQuYWRkU3RyZXRjaCgpCgogICAgICAgICMg4pSA4pSAIE1haW4gY29udGVudCDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9jb250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY29u"
    "dGVudC5zZXRNaW5pbXVtV2lkdGgoMTgwKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWF4aW11bVdpZHRoKDIyMCkKICAgICAgICBjb250ZW50X2xheW91"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIFNlY3Rpb24gbGFiZWwKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQo"
    "X3NlY3Rpb25fbGJsKCLinacgSk9VUk5BTCIpKQoKICAgICAgICAjIEN1cnJlbnQgc2Vzc2lvbiBpbmZvCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lID0g"
    "UUxhYmVsKCJOZXcgU2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dP"
    "TER9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fc2Vzc2lvbl9uYW1lKQoKICAgICAgICAjIFNhdmUgLyBMb2FkIHJvdwogICAgICAgIGN0cmxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNl"
    "bGYuX2J0bl9zYXZlID0gX2dvdGhpY19idG4oIvCfkr4iKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3NhdmUuc2V0VG9vbFRpcCgiU2F2ZSBzZXNzaW9uIG5vdyIpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQgPSBfZ290aGljX2J0bigi8J+TgiIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRUb29sVGlwKCJCcm93c2UgYW5kIGxv"
    "YWQgYSBwYXN0IHNlc3Npb24iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdCA9IFFMYWJlbCgi4pePIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Qu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoIkF1dG9zYXZlIHN0YXR1cyIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX3NhdmUpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2xvYWQpCiAgICAgICAgY3RybF9y"
    "b3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5h"
    "ZGRXaWRnZXQoc2VsZi5fYXV0b3NhdmVfZG90KQogICAgICAgIGN0cmxfcm93LmFkZFN0cmV0Y2goKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZExheW91"
    "dChjdHJsX3JvdykKCiAgICAgICAgIyBKb3VybmFsIGxvYWRlZCBpbmRpY2F0b3IKICAgICAgICBzZWxmLl9qb3VybmFsX2xibCA9IFFMYWJlbCgiIikKICAg"
    "ICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19QVVJQTEV9OyBmb250LXNpemU6IDlweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X2pvdXJuYWxfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfbGJsKQoKICAgICAg"
    "ICAjIENsZWFyIGpvdXJuYWwgYnV0dG9uIChoaWRkZW4gd2hlbiBub3QgbG9hZGVkKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsID0gX2dvdGhp"
    "Y19idG4oIuKclyBSZXR1cm4gdG8gUHJlc2VudCIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBz"
    "ZWxmLl9idG5fY2xlYXJfam91cm5hbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fY2xlYXJfam91cm5hbCkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwpCgogICAgICAgICMgRGl2aWRlcgogICAgICAgIGRpdiA9IFFGcmFtZSgpCiAgICAgICAgZGl2LnNldEZy"
    "YW1lU2hhcGUoUUZyYW1lLlNoYXBlLkhMaW5lKQogICAgICAgIGRpdi5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsiKQogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChkaXYpCgogICAgICAgICMgU2Vzc2lvbiBsaXN0CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9z"
    "ZWN0aW9uX2xibCgi4p2nIFBBU1QgU0VTU0lPTlMiKSkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQt"
    "c2l6ZTogMTBweDsiCiAgICAgICAgICAgIGYiUUxpc3RXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyB9fSIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIGNvbnRlbnRfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX2xpc3QsIDEpCgogICAgICAgICMgQWRkIGNvbnRlbnQgYW5kIHRvZ2dsZSBzdHJpcCB0byB0aGUgcm9vdCBob3Jp"
    "em9udGFsIGxheW91dAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX3N0"
    "cmlwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBz"
    "ZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiIGlmIHNlbGYuX2V4"
    "cGFuZGVkIGVsc2UgIuKWtiIpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBp"
    "ZiBwIGFuZCBwLmxheW91dCgpOgogICAgICAgICAgICBwLmxheW91dCgpLmFjdGl2YXRlKCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHNlc3Npb25zID0gc2VsZi5fc2Vzc2lvbl9tZ3IubGlzdF9zZXNzaW9ucygpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmNsZWFyKCkKICAgICAg"
    "ICBmb3IgcyBpbiBzZXNzaW9uczoKICAgICAgICAgICAgZGF0ZV9zdHIgPSBzLmdldCgiZGF0ZSIsIiIpCiAgICAgICAgICAgIG5hbWUgICAgID0gcy5nZXQo"
    "Im5hbWUiLCBkYXRlX3N0cilbOjMwXQogICAgICAgICAgICBjb3VudCAgICA9IHMuZ2V0KCJtZXNzYWdlX2NvdW50IiwgMCkKICAgICAgICAgICAgaXRlbSA9"
    "IFFMaXN0V2lkZ2V0SXRlbShmIntkYXRlX3N0cn1cbntuYW1lfSAoe2NvdW50fSBtc2dzKSIpCiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0"
    "YVJvbGUuVXNlclJvbGUsIGRhdGVfc3RyKQogICAgICAgICAgICBpdGVtLnNldFRvb2xUaXAoZiJEb3VibGUtY2xpY2sgdG8gbG9hZCBzZXNzaW9uIGZyb20g"
    "e2RhdGVfc3RyfSIpCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5hZGRJdGVtKGl0ZW0pCgogICAgZGVmIHNldF9zZXNzaW9uX25hbWUoc2VsZiwg"
    "bmFtZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRUZXh0KG5hbWVbOjUwXSBvciAiTmV3IFNlc3Npb24iKQoKICAgIGRl"
    "ZiBzZXRfYXV0b3NhdmVfaW5kaWNhdG9yKHNlbGYsIHNhdmVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HUkVFTiBpZiBzYXZlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA4"
    "cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlwKAogICAgICAgICAgICAiQXV0b3NhdmVk"
    "IiBpZiBzYXZlZCBlbHNlICJQZW5kaW5nIGF1dG9zYXZlIgogICAgICAgICkKCiAgICBkZWYgc2V0X2pvdXJuYWxfbG9hZGVkKHNlbGYsIGRhdGVfc3RyOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dChmIvCfk5YgSm91cm5hbDoge2RhdGVfc3RyfSIpCiAgICAgICAgc2VsZi5f"
    "YnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShUcnVlKQoKICAgIGRlZiBjbGVhcl9qb3VybmFsX2luZGljYXRvcihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKCiAgICBkZWYg"
    "X2RvX3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX21nci5zYXZlKCkKICAgICAgICBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0"
    "b3IoVHJ1ZSkKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIuKckyIpCiAgICAgICAgUVRpbWVyLnNpbmds"
    "ZVNob3QoMTUwMCwgbGFtYmRhOiBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLwn5K+IikpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwMCwgbGFtYmRh"
    "OiBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpKQoKICAgIGRlZiBfZG9fbG9hZChzZWxmKSAtPiBOb25lOgogICAgICAgICMgVHJ5IHNlbGVj"
    "dGVkIGl0ZW0gZmlyc3QKICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBpZiBub3QgaXRlbToKICAgICAg"
    "ICAgICAgIyBJZiBub3RoaW5nIHNlbGVjdGVkLCB0cnkgdGhlIGZpcnN0IGl0ZW0KICAgICAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbl9saXN0LmNvdW50KCkg"
    "PiAwOgogICAgICAgICAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtKDApCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Qu"
    "c2V0Q3VycmVudEl0ZW0oaXRlbSkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNl"
    "clJvbGUpCiAgICAgICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfb25fc2Vzc2lvbl9jbGljayhz"
    "ZWxmLCBpdGVtKSAtPiBOb25lOgogICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICBzZWxmLnNl"
    "c3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYgX2RvX2NsZWFyX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "LnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmVtaXQoKQogICAgICAgIHNlbGYuY2xlYXJfam91cm5hbF9pbmRpY2F0b3IoKQoKCiMg4pSA4pSAIFRPUlBPUiBQ"
    "QU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgVG9ycG9yUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRocmVlLXN0YXRlIHN1c3BlbnNpb24gdG9nZ2xlOiBBV0FLRSB8"
    "IEFVVE8gfCBTVVNQRU5ERUQKCiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3Vy"
    "ZQogICAgQVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVO"
    "REVEIOKAlCBtb2RlbCB1bmxvYWRlZCwgc3RheXMgc3VzcGVuZGVkIHVudGlsIG1hbnVhbGx5IGNoYW5nZWQKCiAgICBTaWduYWxzOgogICAgICAgIHN0YXRl"
    "X2NoYW5nZWQoc3RyKSAg4oCUICJBV0FLRSIgfCAiQVVUTyIgfCAiU1VTUEVOREVEIgogICAgIiIiCgogICAgc3RhdGVfY2hhbmdlZCA9IFNpZ25hbChzdHIp"
    "CgogICAgU1RBVEVTID0gWyJBV0FLRSIsICJBVVRPIiwgIlNVU1BFTkRFRCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6IHsKICAg"
    "ICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6"
    "IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAog"
    "ICAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlz"
    "YWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9y"
    "OiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAg"
    "ICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBm"
    "b250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9v"
    "bHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFTkRFRCI6IHsK"
    "ICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiB7Q19QVVJQTEVfRElNfTsgY29sb3I6IHtDX1BVUlBMRX07ICIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJm"
    "b250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "Ym9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgIGYi4pqwIHtVSV9TVVNQRU5TSU9OX0xBQkVMLnN0cmlwKCkgaWYgc3RyKFVJX1NVU1BFTlNJ"
    "T05fTEFCRUwpLnN0cmlwKCkgZWxzZSAnU3VzcGVuZGVkJ30iLAogICAgICAgICAgICAidG9vbHRpcCI6ICBmIk1vZGVsIHVubG9hZGVkLiB7REVDS19OQU1F"
    "fSBzbGVlcHMgdW50aWwgbWFudWFsbHkgYXdha2VuZWQuIiwKICAgICAgICB9LAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fY3VycmVudCA9ICJBV0FLRSIKICAgICAgICBzZWxmLl9idXR0b25zOiBk"
    "aWN0W3N0ciwgUVB1c2hCdXR0b25dID0ge30KICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBmb3Igc3RhdGUgaW4gc2VsZi5TVEFURVM6CiAgICAgICAg"
    "ICAgIGJ0biA9IFFQdXNoQnV0dG9uKHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsibGFiZWwiXSkKICAgICAgICAgICAgYnRuLnNldFRvb2xUaXAoc2VsZi5T"
    "VEFURV9TVFlMRVNbc3RhdGVdWyJ0b29sdGlwIl0pCiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICAgICAgYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChsYW1iZGEgY2hlY2tlZCwgcz1zdGF0ZTogc2VsZi5fc2V0X3N0YXRlKHMpKQogICAgICAgICAgICBzZWxmLl9idXR0b25zW3N0YXRlXSA9IGJ0"
    "bgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJ0bikKCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKCiAgICBkZWYgX3NldF9zdGF0ZShzZWxm"
    "LCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYu"
    "X2N1cnJlbnQgPSBzdGF0ZQogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCiAgICAgICAgc2VsZi5zdGF0ZV9jaGFuZ2VkLmVtaXQoc3RhdGUpCgogICAg"
    "ZGVmIF9hcHBseV9zdHlsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Igc3RhdGUsIGJ0biBpbiBzZWxmLl9idXR0b25zLml0ZW1zKCk6CiAgICAgICAg"
    "ICAgIHN0eWxlX2tleSA9ICJhY3RpdmUiIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQgZWxzZSAiaW5hY3RpdmUiCiAgICAgICAgICAgIGJ0bi5zZXRTdHls"
    "ZVNoZWV0KHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVtzdHlsZV9rZXldKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfc3RhdGUoc2VsZikgLT4g"
    "c3RyOgogICAgICAgIHJldHVybiBzZWxmLl9jdXJyZW50CgogICAgZGVmIHNldF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgICIi"
    "IlNldCBzdGF0ZSBwcm9ncmFtbWF0aWNhbGx5IChlLmcuIGZyb20gYXV0by10b3Jwb3IgZGV0ZWN0aW9uKS4iIiIKICAgICAgICBpZiBzdGF0ZSBpbiBzZWxm"
    "LlNUQVRFUzoKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXRlKHN0YXRlKQoKCiMg4pSA4pSAIE1BSU4gV0lORE9XIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFY2hvRGVj"
    "ayhRTWFpbldpbmRvdyk6CiAgICAiIiIKICAgIFRoZSBtYWluIEVjaG8gRGVjayB3aW5kb3cuCiAgICBBc3NlbWJsZXMgYWxsIHdpZGdldHMsIGNvbm5lY3Rz"
    "IGFsbCBzaWduYWxzLCBtYW5hZ2VzIGFsbCBzdGF0ZS4KICAgICIiIgoKICAgICMg4pSA4pSAIFRvcnBvciB0aHJlc2hvbGRzIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCICAgID0gMS41ICAgIyBleHRlcm5hbCBWUkFNID4g"
    "dGhpcyDihpIgY29uc2lkZXIgdG9ycG9yCiAgICBfRVhURVJOQUxfVlJBTV9XQUtFX0dCICAgICAgPSAwLjggICAjIGV4dGVybmFsIFZSQU0gPCB0aGlzIOKG"
    "kiBjb25zaWRlciB3YWtlCiAgICBfVE9SUE9SX1NVU1RBSU5FRF9USUNLUyAgICAgPSA2ICAgICAjIDYgw5cgNXMgPSAzMCBzZWNvbmRzIHN1c3RhaW5lZAog"
    "ICAgX1dBS0VfU1VTVEFJTkVEX1RJQ0tTICAgICAgID0gMTIgICAgIyA2MCBzZWNvbmRzIHN1c3RhaW5lZCBsb3cgcHJlc3N1cmUKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCgogICAgICAgICMg4pSA4pSAIENvcmUgc3RhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHVzICAgICAgICAgICAgICA9ICJPRkZMSU5FIgogICAgICAgIHNl"
    "bGYuX3Nlc3Npb25fc3RhcnQgICAgICAgPSB0aW1lLnRpbWUoKQogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICAgICAgICAgPSAwCiAgICAgICAgc2VsZi5f"
    "ZmFjZV9sb2NrZWQgICAgICAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgICAgICAgICA9IFRydWUKICAgICAgICBzZWxmLl9tb2RlbF9s"
    "b2FkZWQgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9zZXNzaW9uX2lkICAgICAgICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGlt"
    "ZSgnJVklbSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkczogbGlzdCA9IFtdICAjIGtlZXAgcmVmcyB0byBwcmV2ZW50IEdDIHdo"
    "aWxlIHJ1bm5pbmcKICAgICAgICBzZWxmLl9maXJzdF90b2tlbjogYm9vbCA9IFRydWUgICAjIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHN0"
    "cmVhbWluZyB0b2tlbgoKICAgICAgICAjIFRvcnBvciAvIFZSQU0gdHJhY2tpbmcKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgICAgICAgID0gIkFXQUtF"
    "IgogICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlICA9IDAuMCAgICMgYmFzZWxpbmUgVlJBTSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fdnJh"
    "bV9wcmVzc3VyZV90aWNrcyA9IDAgICAgICMgc3VzdGFpbmVkIHByZXNzdXJlIGNvdW50ZXIKICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgID0g"
    "MCAgICAgIyBzdXN0YWluZWQgcmVsaWVmIGNvdW50ZXIKICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgc2VsZi5fdG9y"
    "cG9yX3NpbmNlICAgICAgICA9IE5vbmUgICMgZGF0ZXRpbWUgd2hlbiB0b3Jwb3IgYmVnYW4KICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gID0g"
    "IiIgICAjIGZvcm1hdHRlZCBkdXJhdGlvbiBzdHJpbmcKCiAgICAgICAgIyDilIDilIAgTWFuYWdlcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbWVtb3J5ICAgPSBNZW1vcnlNYW5hZ2VyKCkKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9ucyA9IFNlc3Npb25NYW5hZ2VyKCkKICAgICAgICBzZWxmLl9sZXNzb25zICA9IExlc3NvbnNMZWFybmVkREIoKQogICAgICAgIHNlbGYuX3Rhc2tz"
    "ICAgID0gVGFza01hbmFnZXIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGU6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3JlY29yZHNfaW5p"
    "dGlhbGl6ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9nb29nbGVfYXV0"
    "aF9yZWFkeSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0gPSBOb25lCiAgICAgICAgc2VsZi5f"
    "Z29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYl9pbmRleCA9IC0x"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll90YXNrX2RhdGVfZmlsdGVyID0gIm5leHRfM19tb250aHMiCiAgICAgICAgc2VsZi5fcGVyc29uYV9zdG9yZV9wYXRoID0gY2ZnX3BhdGgoInBlcnNvbmFz"
    "IikgLyAicGVyc29uYV9saWJyYXJ5Lmpzb24iCiAgICAgICAgc2VsZi5fYWN0aXZlX3BlcnNvbmFfbmFtZSA9IERFQ0tfTkFNRQoKICAgICAgICAjIExvd2Vy"
    "IEhVRCBpbnRlcm5hbCBlY29ub215IHN0YXRlCiAgICAgICAgc2VsZi5fZWNvbl9sZWZ0X29yYiA9IDAuMzUKICAgICAgICBzZWxmLl9lY29uX3JpZ2h0X29y"
    "YiA9IDAuNTgKICAgICAgICBzZWxmLl9lY29uX2Vzc2VuY2Vfc2Vjb25kYXJ5ID0gMC44MgogICAgICAgIHNlbGYuX2xhc3RfaW50ZXJhY3Rpb25fdHMgPSB0"
    "aW1lLnRpbWUoKQoKICAgICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgIyBJbnN0YW50aWF0ZSBzZXJ2aWNlIHdyYXBwZXJzIHVwLWZyb250OyBhdXRoIGlzIGZvcmNlZCBsYXRlcgogICAgICAgICMgZnJvbSBtYWluKCkg"
    "YWZ0ZXIgd2luZG93LnNob3coKSB3aGVuIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgZ19jcmVkc19wYXRoID0gUGF0aChDRkcuZ2V0KCJn"
    "b29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAiY3JlZGVudGlhbHMiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9j"
    "cmVkZW50aWFscy5qc29uIikKICAgICAgICApKQogICAgICAgIGdfdG9rZW5fcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAg"
    "ICAgICAgInRva2VuIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIikKICAgICAgICApKQogICAgICAgIHNlbGYu"
    "X2djYWwgPSBHb29nbGVDYWxlbmRhclNlcnZpY2UoZ19jcmVkc19wYXRoLCBnX3Rva2VuX3BhdGgpCiAgICAgICAgc2VsZi5fZ2RyaXZlID0gR29vZ2xlRG9j"
    "c0RyaXZlU2VydmljZSgKICAgICAgICAgICAgZ19jcmVkc19wYXRoLAogICAgICAgICAgICBnX3Rva2VuX3BhdGgsCiAgICAgICAgICAgIGxvZ2dlcj1sYW1i"
    "ZGEgbXNnLCBsZXZlbD0iSU5GTyI6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHRFJJVkVdIHttc2d9IiwgbGV2ZWwpCiAgICAgICAgKQoKICAgICAgICAjIFNl"
    "ZWQgTFNMIHJ1bGVzIG9uIGZpcnN0IHJ1bgogICAgICAgIHNlbGYuX2xlc3NvbnMuc2VlZF9sc2xfcnVsZXMoKQoKICAgICAgICAjIExvYWQgZW50aXR5IHN0"
    "YXRlCiAgICAgICAgc2VsZi5fc3RhdGUgPSBzZWxmLl9tZW1vcnkubG9hZF9zdGF0ZSgpCiAgICAgICAgc2VsZi5fc3RhdGVbInNlc3Npb25fY291bnQiXSA9"
    "IHNlbGYuX3N0YXRlLmdldCgic2Vzc2lvbl9jb3VudCIsMCkgKyAxCiAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc3RhcnR1cCJdICA9IGxvY2FsX25vd19p"
    "c28oKQogICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAgICAgICAjIEJ1aWxkIGFkYXB0b3IKICAgICAgICBzZWxmLl9h"
    "ZGFwdG9yID0gYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpCgogICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIChzZXQgdXAgYWZ0ZXIgd2lkZ2V0cyBi"
    "dWlsdCkKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21ncjogT3B0aW9uYWxbRmFjZVRpbWVyTWFuYWdlcl0gPSBOb25lCgogICAgICAgICMg4pSA4pSAIEJ1"
    "aWxkIFVJIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuc2V0V2lu"
    "ZG93VGl0bGUoQVBQX05BTUUpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMjAwLCA3NTApCiAgICAgICAgc2VsZi5yZXNpemUoMTM1MCwgODUwKQog"
    "ICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciB3"
    "aXJlZCB0byB3aWRnZXRzCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IgPSBGYWNlVGltZXJNYW5hZ2VyKAogICAgICAgICAgICBzZWxmLl9taXJyb3Is"
    "IHNlbGYuX2Vtb3Rpb25fYmxvY2sKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRpbWVycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0c190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fc3Rh"
    "dHNfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9zdGF0cykKICAgICAgICBzZWxmLl9zdGF0c190aW1lci5zdGFydCgxMDAwKQoKICAgICAg"
    "ICBzZWxmLl9ibGlua190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2JsaW5rKQogICAg"
    "ICAgIHNlbGYuX2JsaW5rX3RpbWVyLnN0YXJ0KDgwMCkKCiAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIgPSBRVGltZXIoKQogICAgICAgIGlmIEFJ"
    "X1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl9mb290ZXJfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnRp"
    "bWVvdXQuY29ubmVjdChzZWxmLl9mb290ZXJfc3RyaXAucmVmcmVzaCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDAp"
    "CgogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIudGlt"
    "ZW91dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fYXBwbHlfZ29vZ2xlX2luYm91bmRfaW50ZXJ2"
    "YWwoKQoKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29y"
    "ZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYu"
    "X2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZlcnJl"
    "ZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAgICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVw"
    "X3NlcXVlbmNlKCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgZnJvbSBtYWluKCkgYWZ0ZXIKICAg"
    "ICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zIHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2VudHJhbCkKICAgICAgICBy"
    "b290ID0gUVZCb3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3Bh"
    "Y2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwgfCBD"
    "aGF0IHwgU3lzdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEpvdXJuYWwgc2lk"
    "ZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIgPSBKb3VybmFsU2lkZWJhcihzZWxmLl9zZXNzaW9ucykKICAgICAgICBzZWxmLl9q"
    "b3VybmFsX3NpZGViYXIuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9sb2FkX2pvdXJuYWxfc2Vzc2lvbikKICAg"
    "ICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5h"
    "bF9zZXNzaW9uKQogICAgICAgIGJvZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0IHBhbmVsIChjZW50ZXIsIGV4"
    "cGFuZHMpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAjIFN5c3RlbXMgKHJpZ2h0KQogICAg"
    "ICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5lbCgpKQoKICAgICAgICByb290LmFkZExheW91dChib2R5LCAxKQoKICAgICAg"
    "ICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgZm9vdGVyID0gUUxhYmVsKAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAg"
    "ICAgIGZvb3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2lu"
    "ZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRBbGln"
    "bm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9i"
    "YXIoc2VsZikgLT4gUVdpZGdldDoKICAgICAgICBiYXIgPSBRV2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAg"
    "ICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAgIGxheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pym"
    "IHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEz"
    "cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBydW5lcy5z"
    "ZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJX09G"
    "RkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBm"
    "b250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwgKHBlcm1hbmVudCBvcGVyYXRpb25hbCBj"
    "b250cm9sKQogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwuc3RhdGVfY2hhbmdl"
    "ZC5jb25uZWN0KHNlbGYuX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKQoKICAgICAgICAjIElkbGUgdG9nZ2xlCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBR"
    "UHVzaEJ1dHRvbigiSURMRSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNl"
    "dENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkK"
    "CiAgICAgICAgIyBGUyAvIEJMIGJ1dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRlMiKQogICAgICAgIHNlbGYuX2JsX2J0biA9"
    "IFFQdXNoQnV0dG9uKCJCTCIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRkb3du"
    "X2J0biA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9y"
    "dF9idG4pOgogICAgICAgICAgICBidG4uc2V0Rml4ZWRTaXplKDMwLCAyMikKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldEZpeGVkV2lkdGgoNDYpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkSGVpZ2h0"
    "KDIyKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZFdpZHRoKDY4KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19CTE9PRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CTE9PRH07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9mc19idG4uc2V0VG9vbFRpcCgiRnVsbHNjcmVlbiAoRjExKSIpCiAgICAgICAgc2VsZi5fYmxfYnRuLnNldFRvb2xUaXAoIkJvcmRlcmxlc3Mg"
    "KEYxMCkiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0VG9vbFRpcCgiRXhwb3J0IGNoYXQgc2Vzc2lvbiB0byBUWFQgZmlsZSIpCiAgICAgICAgc2Vs"
    "Zi5fc2h1dGRvd25fYnRuLnNldFRvb2xUaXAoZiJHcmFjZWZ1bCBzaHV0ZG93biDigJQge0RFQ0tfTkFNRX0gc3BlYWtzIHRoZWlyIGxhc3Qgd29yZHMiKQog"
    "ICAgICAgIHNlbGYuX2ZzX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2Z1bGxzY3JlZW4pCiAgICAgICAgc2VsZi5fYmxfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl90b2dnbGVfYm9yZGVybGVzcykKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9leHBvcnRfY2hh"
    "dCkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZykKCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldCh0aXRsZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJ1bmVzLCAxKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0"
    "dXNfbGFiZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoOCkKICAgICAgICBpZiBzZWxmLl90b3Jwb3JfcGFuZWwgaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fdG9ycG9yX3BhbmVsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLl9pZGxlX2J0bikKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZXhwb3J0X2J0"
    "bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2ZzX2J0bikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2JsX2J0bikKCiAgICAgICAgcmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAt"
    "PiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWlu"
    "IHRhYiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91"
    "bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Qk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAgICAg"
    "IGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1i"
    "b3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5jZV93"
    "aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNp"
    "bmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVl"
    "KQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBm"
    "b250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxh"
    "eSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5jZV93aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKU"
    "gCBUYWIgMTogU2VsZiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zZWxmX3Rh"
    "Yl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3NlbGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxm"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2Vs"
    "Zl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rp"
    "c3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5n"
    "OiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5f"
    "dGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJfd2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywg"
    "MSkKCiAgICAgICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRvcnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jv"
    "c3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgRU1PVElPTlMgfCBMRUZUIE9SQiB8IENFTlRFUiBDWUNMRSB8IFJJR0hUIE9SQiB8IEVTU0VO"
    "Q0UKICAgICAgICBibG9ja19yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYmxvY2tfcm93LnNldFNwYWNpbmcoMikKCiAgICAgICAgIyBNaXJyb3IgKG5l"
    "dmVyIGNvbGxhcHNlcykKICAgICAgICBtaXJyb3Jfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIG13X2xheW91dCA9IFFWQm94TGF5b3V0KG1pcnJvcl93cmFw"
    "KQogICAgICAgIG13X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtd19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAg"
    "IG13X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIHtVSV9NSVJST1JfTEFCRUx9IikpCiAgICAgICAgc2VsZi5fbWlycm9yID0gTWlycm9y"
    "V2lkZ2V0KCkKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0Rml4ZWRTaXplKDE2MCwgMTYwKQogICAgICAgIG13X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbWly"
    "cm9yKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlycm9yX3dyYXAsIDApCgogICAgICAgICMgRW1vdGlvbiBibG9jayAoY29sbGFwc2libGUpCiAg"
    "ICAgICAgc2VsZi5fZW1vdGlvbl9ibG9jayA9IEVtb3Rpb25CbG9jaygpCiAgICAgICAgc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwID0gQ29sbGFwc2libGVC"
    "bG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VNT1RJT05TX0xBQkVMfSIsIHNlbGYuX2Vtb3Rpb25fYmxvY2ssCiAgICAgICAgICAgIGV4cGFuZGVkPVRy"
    "dWUsIG1pbl93aWR0aD0xMzAKICAgICAgICApCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAsIDApCgogICAg"
    "ICAgICMgTWlkZGxlIGxvd2VyIGJsb2NrIChmaXhlZCA0LWNvbHVtbiBsYXlvdXQpOgogICAgICAgICMgUFJJTUFSWSB8IENZQ0xFIHwgU0VDT05EQVJZIHwg"
    "RVNTRU5DRQogICAgICAgIG1pZGRsZV93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbWlkZGxlX2dyaWQgPSBRR3JpZExheW91dChtaWRkbGVfd3JhcCkKICAg"
    "ICAgICBtaWRkbGVfZ3JpZC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtaWRkbGVfZ3JpZC5zZXRIb3Jpem9udGFsU3BhY2luZygy"
    "KQogICAgICAgIG1pZGRsZV9ncmlkLnNldFZlcnRpY2FsU3BhY2luZygyKQoKICAgICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSwgZml4"
    "ZWQgc2xvdCkKICAgICAgICBzZWxmLl9sZWZ0X29yYiA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwg"
    "Q19DUklNU09OX0RJTQogICAgICAgICkKICAgICAgICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacg"
    "e1VJX0xFRlRfT1JCX1RJVExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAg"
    "ICkKICAgICAgICBtaWRkbGVfZ3JpZC5hZGRXaWRnZXQoc2VsZi5fbGVmdF9vcmJfd3JhcCwgMCwgMCkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0"
    "IChjb2xsYXBzaWJsZSwgZml4ZWQgc2xvdCkKICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQgPSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVf"
    "d3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAg"
    "ICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQogICAgICAgIG1pZGRsZV9ncmlkLmFkZFdpZGdldChzZWxmLl9jeWNsZV93"
    "cmFwLCAwLCAxKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9yYiAoY29sbGFwc2libGUsIGZpeGVkIHNsb3QpCiAgICAgICAgc2VsZi5fcmlnaHRfb3Ji"
    "ID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENfUFVSUExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAg"
    "c2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3Jp"
    "Z2h0X29yYiwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCiAgICAgICAgbWlkZGxlX2dyaWQuYWRkV2lk"
    "Z2V0KHNlbGYuX3JpZ2h0X29yYl93cmFwLCAwLCAyKQoKICAgICAgICAjIEVzc2VuY2UgKDIgZ2F1Z2VzLCBjb2xsYXBzaWJsZSwgZml4ZWQgc2xvdCkKICAg"
    "ICAgICBlc3NlbmNlX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGVzc2VuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZXNzZW5jZV93aWRnZXQpCiAgICAg"
    "ICAgZXNzZW5jZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAg"
    "ICAgIHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSAgID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9QUklNQVJZLCAgICIlIiwgMTAwLjAsIENfQ1JJTVNP"
    "TikKICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZSA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0VfU0VDT05EQVJZLCAiJSIsIDEwMC4wLCBD"
    "X0dSRUVOKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2UpCiAgICAgICAgZXNzZW5jZV9sYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2so"
    "CiAgICAgICAgICAgIGYi4p2nIHtVSV9FU1NFTkNFX1RJVExFfSIsIGVzc2VuY2Vfd2lkZ2V0LAogICAgICAgICAgICBtaW5fd2lkdGg9MTEwLCByZXNlcnZl"
    "X3dpZHRoPVRydWUKICAgICAgICApCiAgICAgICAgbWlkZGxlX2dyaWQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2Vfd3JhcCwgMCwgMykKCiAgICAgICAgZm9y"
    "IGNvbCBpbiByYW5nZSg0KToKICAgICAgICAgICAgbWlkZGxlX2dyaWQuc2V0Q29sdW1uU3RyZXRjaChjb2wsIDEpCgogICAgICAgIGJsb2NrX3Jvdy5hZGRX"
    "aWRnZXQobWlkZGxlX3dyYXAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMg4pSA4pSAIElucHV0IHJvdyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpbnB1dF9yb3cgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgcHJvbXB0X3N5bSA9IFFMYWJlbCgi4pymIikKICAgICAgICBwcm9tcHRfc3ltLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE2cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBwcm9tcHRf"
    "c3ltLnNldEZpeGVkV2lkdGgoMjApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5z"
    "ZXRQbGFjZWhvbGRlclRleHQoVUlfSU5QVVRfUExBQ0VIT0xERVIpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQucmV0dXJuUHJlc3NlZC5jb25uZWN0KHNl"
    "bGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAgICBzZWxmLl9zZW5kX2J0biA9IFFQ"
    "dXNoQnV0dG9uKFVJX1NFTkRfQlVUVE9OKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEZpeGVkV2lkdGgoMTEwKQogICAgICAgIHNlbGYuX3NlbmRfYnRu"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZW5kX21lc3NhZ2UpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgaW5w"
    "dXRfcm93LmFkZFdpZGdldChwcm9tcHRfc3ltKQogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5faW5wdXRfZmllbGQpCiAgICAgICAgaW5wdXRf"
    "cm93LmFkZFdpZGdldChzZWxmLl9zZW5kX2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGlucHV0X3JvdykKCiAgICAgICAgIyBGb290ZXIgc3RhdGUg"
    "c3RyaXAgKGJlbG93IHByb21wdC9pbnB1dCByb3cg4oCUIHBlcm1hbmVudCBVSSBzdHJ1Y3R1cmUpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwID0gRm9v"
    "dGVyU3RyaXBXaWRnZXQoKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcC5zZXRfbGFiZWwoVUlfRk9PVEVSX1NUUklQX0xBQkVMKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fZm9vdGVyX3N0cmlwKQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2Vs"
    "ZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIpKQoK"
    "ICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRN"
    "aW5pbXVtV2lkdGgoMjgwKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4"
    "cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1Rh"
    "YiBlYXJseSBzbyBzdGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZvcmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8g"
    "dGhlIHdpZGdldC4KICAgICAgICBzZWxmLl9kaWFnX3RhYiA9IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFyZHdhcmVQYW5lbCgpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdfcGFuZWwsICJJbnN0cnVtZW50cyIpCgogICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFs"
    "KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX3Jl"
    "Y29yZHNfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJSZWNvcmRzIikKICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRhYiAocmVh"
    "bCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRh"
    "c2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5f"
    "dGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90YXNrLAogICAg"
    "ICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2Vs"
    "Zi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tz"
    "LAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1z"
    "ZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICAgICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jf"
    "d29ya3NwYWNlLAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAgICBzZWxmLl90YXNr"
    "c190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gc2VsZi5f"
    "c3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fdGFza3NfdGFiLCAiVGFza3MiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBU"
    "YXNrc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFNMIFNjYW5zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3BhdGgoInNsIikpCiAgICAgICAgc2VsZi5fc3Bl"
    "bGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAgICAgICMg4pSA4pSAIFNMIENvbW1hbmRzIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9jb21tYW5kcyA9IFNMQ29tbWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3Nw"
    "ZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3NsX2NvbW1hbmRzLCAiU0wgQ29tbWFuZHMiKQoKICAgICAgICAjIOKUgOKUgCBKb2IgVHJhY2tlciB0YWIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fam9iX3RyYWNrZXIgPSBKb2JUcmFja2VyVGFiKCkKICAgICAgICBz"
    "ZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9qb2JfdHJhY2tlciwgIkpvYiBUcmFja2VyIikKCiAgICAgICAgIyDilIDilIAgTGVzc29ucyB0YWIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbGVzc29uc190YWIgPSBMZXNzb25zVGFi"
    "KHNlbGYuX2xlc3NvbnMpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbGVzc29uc190YWIsICJMZXNzb25zIikKCiAgICAgICAgIyBT"
    "ZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGlu"
    "c3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1v"
    "ZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRy"
    "YWNrZXJUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX21vZHVsZV90cmFja2VyLCAiTW9kdWxlcyIpCgogICAgICAgICMg4pSA"
    "4pSAIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFk"
    "ZFRhYihzZWxmLl9kaWFnX3RhYiwgIkRpYWdub3N0aWNzIikKCiAgICAgICAgIyDilIDilIAgU2V0dGluZ3MgdGFiIChkZWNrLXdpZGUgY29udHJvbHMgb25s"
    "eSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2V0dGluZ3NfdGFi"
    "ID0gc2VsZi5fYnVpbGRfc2V0dGluZ3NfdGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zZXR0aW5nc190YWIsICJTZXR0aW5n"
    "cyIpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW91dChyaWdo"
    "dF93b3Jrc3BhY2UpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByaWdodF93"
    "b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc3BlbGxfdGFicywg"
    "MSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKdpyBDQUxFTkRBUiIpCiAgICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVsKQoKICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxm"
    "LmNhbGVuZGFyX3dpZGdldC5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6"
    "ZVBvbGljeS5Qb2xpY3kuTWF4aW11bQogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAg"
    "ICBzZWxmLmNhbGVuZGFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2RhdGUpCiAgICAgICAgcmlnaHRf"
    "d29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl93aWRnZXQsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRTdHJl"
    "dGNoKDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNlLCAxKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2FsZW5kYXIgcmVzdG9yZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAg"
    "IklORk8iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHBlcnNpc3RlbnQgbWluaSBjYWxlbmRh"
    "ciByZXN0b3JlZC9jb25maXJtZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAg"
    "cmV0dXJuIGxheW91dAoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKc"
    "piB7UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJv"
    "b3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtc2dzID0gYm9v"
    "dF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNn"
    "cykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAjIGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdf"
    "cGFuZWwuZ2V0X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5jeUNoZWNr"
    "ZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxh"
    "c3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iLCIiKQogICAgICAgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NUQVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJ"
    "TkZPIgogICAgICAgICAgICApCgogICAgICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAg"
    "ICAgICBVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1tb25pbmcge0RFQ0tf"
    "TkFNRX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgogICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9h"
    "ZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgc2VsZi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJFUlJPUiIsIGUpKQogICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0"
    "ZSkKICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0aXZlX3Ro"
    "cmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fbG9hZF9jb21wbGV0ZShzZWxmLCBz"
    "dWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAg"
    "ICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5f"
    "aW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1"
    "cmUgVlJBTSBiYXNlbGluZSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92cmFtX2Jhc2VsaW5lKQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICAgICAjIFZhbXBpcmUgc3RhdGUgZ3JlZXRpbmcKICAgICAg"
    "ICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgICAgICBzdGF0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZh"
    "bXBfZ3JlZXRpbmdzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAgICAg"
    "ICAgIlNZU1RFTSIsCiAgICAgICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4iKQogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3Mg"
    "YSBwcmV2aW91cyBzaHV0ZG93biByZWNvcmRlZCwgaW5qZWN0IGNvbnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5uYSBjYW4gZ3JlZXQgd2l0aCBhd2Fy"
    "ZW5lc3Mgb2YgaG93IGxvbmcgc2hlIHNsZXB0CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJwYW5p"
    "Y2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgICAgICIiIkZvcm1hdCBlbGFwc2VkIHNl"
    "Y29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYgc2Vjb25kcyA8IDYwOgogICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNl"
    "Y29uZHMpfSBzZWNvbmR7J3MnIGlmIHNlY29uZHMgIT0gMSBlbHNlICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0g"
    "aW50KHNlY29uZHMgLy8gNjApCiAgICAgICAgICAgIHMgPSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7bX0gbWludXRleydzJyBp"
    "ZiBtICE9IDEgZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMgPCA4NjQwMDoKICAgICAgICAgICAgaCA9"
    "IGludChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie2h9"
    "IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBlbHNlICIiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQo"
    "c2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9IGludCgoc2Vjb25kcyAlIDg2NDAwKSAvLyAzNjAwKQogICAgICAgICAgICByZXR1cm4gZiJ7ZH0g"
    "ZGF5eydzJyBpZiBkICE9IDEgZWxzZSAnJ30iICsgKGYiIHtofWgiIGlmIGggZWxzZSAiIikKCiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3No"
    "dXRkb3duID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAgICAgICAgcmV0dXJu"
    "ICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAgIyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1lLmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0"
    "ID0gZGF0ZXRpbWUubm93KCkKICAgICAgICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQu"
    "dHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVwbGFjZSh0emluZm89"
    "Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFsX3NlY29uZHMoKQogICAgICAgICAgICBlbGFwc2Vk"
    "X3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3Ry"
    "ID0gImFuIHVua25vd24gZHVyYXRpb24iCgogICAgICAgICMgR2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwg"
    "ICAgID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3No"
    "dXRkb3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAgIGNvbnRleHRfYmxvY2sgPSAiIgogICAgICAgIGlm"
    "IGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJcblxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4i"
    "CiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3du"
    "IikudXBwZXIoKQogICAgICAgICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0"
    "X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlmIGZhcmV3ZWxsOgogICAgICAg"
    "ICAgICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgog"
    "ICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0g"
    "b2YgZG9ybWFuY3kuIgogICAgICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBm"
    "IlxuR3JlZXQgeW91ciBNYXN0ZXIgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgogICAgICAgICAgICBmImFuZCB3"
    "aGF0ZXZlciB5b3UgbGFzdCBzYWlkIHRvIHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJmdWwuIgogICAgICAgICkKCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICBmIltXQUtFVVBdIEluamVjdGluZyB3YWtlLXVwIGNvbnRleHQgKHtlbGFwc2VkX3N0cn0gZWxhcHNlZCkiLCAiSU5GTyIK"
    "ICAgICAgICApCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlz"
    "dG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IHdha2V1cF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3Jr"
    "ZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fd2FrZXVwX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKICAgICAgICAg"
    "ICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTog"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VVUF1bRVJST1JdIHtlfSIsICJXQVJOIikKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVz"
    "X2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIp"
    "CiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQgZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAg"
    "ICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBG"
    "b3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBzdGFydHVwIGFmdGVyIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlz"
    "c2luZy9pbnZhbGlkLCB0aGUgYnJvd3NlciBPQXV0aCBmbG93IG9wZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xFX09L"
    "IG9yIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1b"
    "V0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICJXQVJOIgog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9JTVBPUlRfRVJST1I6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09P"
    "R0xFXVtTVEFSVFVQXVtXQVJOXSB7R09PR0xFX0lNUE9SVF9FUlJPUn0iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGlmIG5vdCBzZWxmLl9nY2FsIG9yIG5vdCBzZWxmLl9nZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBzZXJ2aWNlIG9iamVjdHMgYXJlIHVuYXZh"
    "aWxhYmxlLiIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVnaW5uaW5nIHByb2FjdGl2ZSBHb29nbGUgYXV0aCBjaGVjay4iLCAiSU5GTyIpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gY3JlZGVudGlhbHM9e3NlbGYuX2djYWwu"
    "Y3JlZGVudGlhbHNfcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSB0b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIK"
    "ICAgICAgICAgICAgKQoKICAgICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dP"
    "T0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0siKQoKICAgICAgICAgICAgc2VsZi5fZ2RyaXZlLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gRHJpdmUvRG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAg"
    "IHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gVHJ1ZQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hlZHVs"
    "aW5nIGluaXRpYWwgUmVjb3JkcyByZWZyZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYu"
    "X3JlZnJlc2hfcmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBQb3N0LWF1dGggdGFzayBy"
    "ZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEluaXRpYWwgY2FsZW5kYXIgaW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIs"
    "ICJJTkZPIikKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1U"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIEdvb2dsZSBDYWxlbmRhciB0"
    "YXNrIGltcG9ydCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW0VSUk9SXSB7ZXh9IiwgIkVS"
    "Uk9SIikKCgogICAgZGVmIF9hcHBseV9nb29nbGVfaW5ib3VuZF9pbnRlcnZhbChzZWxmKSAtPiBOb25lOgogICAgICAgIGludGVydmFsX21zID0gaW50KENG"
    "Ry5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAxNTAwMCkpCiAgICAgICAgaW50ZXJ2YWxfbXMgPSBtYXgo"
    "NTAwMCwgaW50ZXJ2YWxfbXMpCiAgICAgICAgaWYgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2dv"
    "b2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KGludGVydmFsX21zKQoKICAgIGRlZiBfY3VycmVudF9jYWxlbmRhcl9yYW5nZShzZWxmKSAtPiB0dXBsZVtkYXRl"
    "dGltZSwgZGF0ZXRpbWVdOgogICAgICAgIG5vdyA9IG5vd19mb3JfY29tcGFyZSgpCiAgICAgICAgY2FsID0gZ2V0YXR0cihnZXRhdHRyKHNlbGYsICJjYWxl"
    "bmRhcl93aWRnZXQiLCBOb25lKSwgImNhbGVuZGFyIiwgTm9uZSkKICAgICAgICBpZiBjYWwgaXMgTm9uZToKICAgICAgICAgICAgaWYgc2VsZi5fdGFza19k"
    "YXRlX2ZpbHRlciA9PSAieWVhciI6CiAgICAgICAgICAgICAgICByZXR1cm4gbm93LCBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgICAgIGlm"
    "IHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIm1vbnRoIjoKICAgICAgICAgICAgICAgIHJldHVybiBub3csIG5vdyArIHRpbWVkZWx0YShkYXlzPTMxKQog"
    "ICAgICAgICAgICBpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ3ZWVrIjoKICAgICAgICAgICAgICAgIHJldHVybiBub3csIG5vdyArIHRpbWVkZWx0"
    "YShkYXlzPTcpCiAgICAgICAgICAgIHJldHVybiBub3csIG5vdyArIHRpbWVkZWx0YShkYXlzPTkyKQogICAgICAgIHllYXIgPSBjYWwueWVhclNob3duKCk7"
    "IG1vbnRoID0gY2FsLm1vbnRoU2hvd24oKTsgdmlld19zdGFydCA9IGRhdGV0aW1lKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0"
    "ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBzdGFydCA9IGRhdGV0aW1lKHllYXIsIDEsIDEpOyBlbmQgPSBkYXRldGltZSh5ZWFyICsgMSwgMSwg"
    "MSkgLSB0aW1lZGVsdGEoc2Vjb25kcz0xKQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBzdGFy"
    "dCA9IHZpZXdfc3RhcnQKICAgICAgICAgICAgbmV4dF9tb250aCA9IGRhdGV0aW1lKHllYXIgKyAoMSBpZiBtb250aCA9PSAxMiBlbHNlIDApLCAxIGlmIG1v"
    "bnRoID09IDEyIGVsc2UgbW9udGggKyAxLCAxKQogICAgICAgICAgICBlbmQgPSBuZXh0X21vbnRoIC0gdGltZWRlbHRhKHNlY29uZHM9MSkKICAgICAgICBl"
    "bGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBzdGFydCA9IHZpZXdfc3RhcnQgLSB0aW1lZGVsdGEoZGF5cz12aWV3"
    "X3N0YXJ0LndlZWtkYXkoKSk7IGVuZCA9IHN0YXJ0ICsgdGltZWRlbHRhKGRheXM9NykKICAgICAgICBlbHNlOgogICAgICAgICAgICBzdGFydCA9IHZpZXdf"
    "c3RhcnQ7IGVuZCA9IHN0YXJ0ICsgdGltZWRlbHRhKGRheXM9OTIpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShzdGFy"
    "dCwgY29udGV4dD0iY2FsZW5kYXJfcmFuZ2Vfc3RhcnQiKSwgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGVuZCwgY29udGV4dD0iY2FsZW5kYXJf"
    "cmFuZ2VfZW5kIikKCiAgICBkZWYgX3RyaWdnZXJfZ29vZ2xlX3JlcHVsbF9ub3coc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09H"
    "TEVdW1JFUFVMTF0gaW1tZWRpYXRlIHJlcHVsbCByZWFzb249e3JlYXNvbn0iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJf"
    "aW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkKCiAgICBkZWYgX2J1aWxkX3NldHRpbmdzX3RhYihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIHRhYiA9"
    "IFFXaWRnZXQoKTsgcm9vdCA9IFFWQm94TGF5b3V0KHRhYik7IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpOyByb290LnNldFNwYWNpbmco"
    "NikKICAgICAgICBkZWYgX3NlY3Rpb24odGl0bGU6IHN0cikgLT4gUUdyb3VwQm94OgogICAgICAgICAgICBib3ggPSBRR3JvdXBCb3godGl0bGUpOyBib3gu"
    "c2V0TGF5b3V0KFFWQm94TGF5b3V0KCkpOyBib3gubGF5b3V0KCkuc2V0U3BhY2luZyg0KTsgcmV0dXJuIGJveAoKICAgICAgICBwZXJzb25hX2JveCA9IF9z"
    "ZWN0aW9uKCJQZXJzb25hIikKICAgICAgICBzZWxmLl9zZXR0aW5nc19hY3RpdmVfcGVyc29uYSA9IFFMYWJlbChmIkFjdGl2ZSBQZXJzb25hOiB7c2VsZi5f"
    "YWN0aXZlX3BlcnNvbmFfbmFtZX0iKQogICAgICAgIHNlbGYuX3NldHRpbmdzX3BlcnNvbmFfY29tYm8gPSBRQ29tYm9Cb3goKTsgc2VsZi5fc2V0dGluZ3Nf"
    "cGVyc29uYV9jb21iby5hZGRJdGVtKHNlbGYuX2FjdGl2ZV9wZXJzb25hX25hbWUpCiAgICAgICAgbG9hZF9idG4gPSBfZ290aGljX2J0bigiTG9hZCBQZXJz"
    "b25hIik7IHN3YXBfYnRuID0gX2dvdGhpY19idG4oIlN3YXAgUGVyc29uYSIpOyBkZWxfYnRuID0gX2dvdGhpY19idG4oIkRlbGV0ZSBQZXJzb25hIikKICAg"
    "ICAgICBsb2FkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2V0dGluZ3NfbG9hZF9wZXJzb25hKTsgc3dhcF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X3NldHRpbmdzX3N3YXBfcGVyc29uYSk7IGRlbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NldHRpbmdzX2RlbGV0ZV9wZXJzb25hKQogICAgICAgIHBl"
    "cnNvbmFfYm94LmxheW91dCgpLmFkZFdpZGdldChzZWxmLl9zZXR0aW5nc19hY3RpdmVfcGVyc29uYSk7IHBlcnNvbmFfYm94LmxheW91dCgpLmFkZFdpZGdl"
    "dChzZWxmLl9zZXR0aW5nc19wZXJzb25hX2NvbWJvKQogICAgICAgIHJvdyA9IFFIQm94TGF5b3V0KCk7IHJvdy5hZGRXaWRnZXQobG9hZF9idG4pOyByb3cu"
    "YWRkV2lkZ2V0KHN3YXBfYnRuKTsgcm93LmFkZFdpZGdldChkZWxfYnRuKTsgcGVyc29uYV9ib3gubGF5b3V0KCkuYWRkTGF5b3V0KHJvdykKCiAgICAgICAg"
    "YWlfYm94ID0gX3NlY3Rpb24oIkFJIEJlaGF2aW9yIikKICAgICAgICBzZWxmLl9zZXR0aW5nc190b3Jwb3JfbW9kZSA9IFFDb21ib0JveCgpOyBzZWxmLl9z"
    "ZXR0aW5nc190b3Jwb3JfbW9kZS5hZGRJdGVtcyhbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVOREVEIl0pCiAgICAgICAgc2VsZi5fc2V0dGluZ3NfdG9ycG9y"
    "X21vZGUuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQpCiAgICAgICAgc2VsZi5fc2V0dGluZ3NfaWRs"
    "ZV90b2dnbGUgPSBRQ2hlY2tCb3goIklkbGUgRW5hYmxlZCIpOyBzZWxmLl9zZXR0aW5nc19pZGxlX3RvZ2dsZS5zZXRDaGVja2VkKGJvb2woQ0ZHLmdldCgi"
    "c2V0dGluZ3MiLCB7fSkuZ2V0KCJpZGxlX2VuYWJsZWQiLCBGYWxzZSkpKTsgc2VsZi5fc2V0dGluZ3NfaWRsZV90b2dnbGUudG9nZ2xlZC5jb25uZWN0KHNl"
    "bGYuX29uX2lkbGVfdG9nZ2xlZCkKICAgICAgICBhaV9ib3gubGF5b3V0KCkuYWRkV2lkZ2V0KFFMYWJlbCgiU3VzcGVuc2lvbiBNb2RlIikpOyBhaV9ib3gu"
    "bGF5b3V0KCkuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX3RvcnBvcl9tb2RlKTsgYWlfYm94LmxheW91dCgpLmFkZFdpZGdldChzZWxmLl9zZXR0aW5nc19p"
    "ZGxlX3RvZ2dsZSkKCiAgICAgICAgdWlfYm94ID0gX3NlY3Rpb24oIlVJIEJlaGF2aW9yIikKICAgICAgICBmc19idG4gPSBfZ290aGljX2J0bigiVG9nZ2xl"
    "IEZ1bGxzY3JlZW4iKTsgZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVlbikKICAgICAgICBibF9idG4gPSBfZ290aGljX2J0"
    "bigiVG9nZ2xlIEJvcmRlcmxlc3MiKTsgYmxfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfYm9yZGVybGVzcykKICAgICAgICBzZWxmLl9zZXR0"
    "aW5nc19zb3VuZF90b2dnbGUgPSBRQ2hlY2tCb3goIlNvdW5kIEVuYWJsZWQiKTsgc2VsZi5fc2V0dGluZ3Nfc291bmRfdG9nZ2xlLnNldENoZWNrZWQoYm9v"
    "bChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVlKSkpOyBzZWxmLl9zZXR0aW5nc19zb3VuZF90b2dnbGUudG9nZ2xl"
    "ZC5jb25uZWN0KHNlbGYuX3NldHRpbmdzX3NldF9zb3VuZF9lbmFibGVkKQogICAgICAgIHVyb3cgPSBRSEJveExheW91dCgpOyB1cm93LmFkZFdpZGdldChm"
    "c19idG4pOyB1cm93LmFkZFdpZGdldChibF9idG4pOyB1aV9ib3gubGF5b3V0KCkuYWRkTGF5b3V0KHVyb3cpOyB1aV9ib3gubGF5b3V0KCkuYWRkV2lkZ2V0"
    "KHNlbGYuX3NldHRpbmdzX3NvdW5kX3RvZ2dsZSkKCiAgICAgICAgaW50X2JveCA9IF9zZWN0aW9uKCJJbnRlZ3JhdGlvbnMiKQogICAgICAgIHNlbGYuX3Nl"
    "dHRpbmdzX2dvb2dsZV9pbnRlcnZhbCA9IFFTcGluQm94KCk7IHNlbGYuX3NldHRpbmdzX2dvb2dsZV9pbnRlcnZhbC5zZXRSYW5nZSg1LCAzNjAwKTsgc2Vs"
    "Zi5fc2V0dGluZ3NfZ29vZ2xlX2ludGVydmFsLnNldFZhbHVlKG1heCg1LCBpbnQoQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJnb29nbGVfaW5ib3Vu"
    "ZF9pbnRlcnZhbF9tcyIsIDE1MDAwKSkgLy8gMTAwMCkpOyBzZWxmLl9zZXR0aW5nc19nb29nbGVfaW50ZXJ2YWwudmFsdWVDaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2V0dGluZ3Nfc2V0X2dvb2dsZV9pbnRlcnZhbF9zZWMpCiAgICAgICAgaXJvdyA9IFFIQm94TGF5b3V0KCk7IGlyb3cuYWRkV2lkZ2V0KFFMYWJlbCgi"
    "R29vZ2xlIFJlZnJlc2ggKHNlYykiKSk7IGlyb3cuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX2dvb2dsZV9pbnRlcnZhbCk7IGludF9ib3gubGF5b3V0KCku"
    "YWRkTGF5b3V0KGlyb3cpCgogICAgICAgIHN5c19ib3ggPSBfc2VjdGlvbigiUGVyc2lzdGVuY2UgLyBTeXN0ZW0iKQogICAgICAgIHNlbGYuX3NldHRpbmdz"
    "X2F1dG9zYXZlID0gUVNwaW5Cb3goKTsgc2VsZi5fc2V0dGluZ3NfYXV0b3NhdmUuc2V0UmFuZ2UoMSwgMTIwKTsgc2VsZi5fc2V0dGluZ3NfYXV0b3NhdmUu"
    "c2V0VmFsdWUoaW50KENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKSkpOyBzZWxmLl9zZXR0aW5n"
    "c19hdXRvc2F2ZS52YWx1ZUNoYW5nZWQuY29ubmVjdChsYW1iZGEgdjogc2VsZi5fc2V0dGluZ3Nfc2V0X251bWVyaWMoImF1dG9zYXZlX2ludGVydmFsX21p"
    "bnV0ZXMiLCB2KSkKICAgICAgICBzZWxmLl9zZXR0aW5nc19iYWNrdXBzID0gUVNwaW5Cb3goKTsgc2VsZi5fc2V0dGluZ3NfYmFja3Vwcy5zZXRSYW5nZSgx"
    "LCAyMDApOyBzZWxmLl9zZXR0aW5nc19iYWNrdXBzLnNldFZhbHVlKGludChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoIm1heF9iYWNrdXBzIiwgMTAp"
    "KSk7IHNlbGYuX3NldHRpbmdzX2JhY2t1cHMudmFsdWVDaGFuZ2VkLmNvbm5lY3QobGFtYmRhIHY6IHNlbGYuX3NldHRpbmdzX3NldF9udW1lcmljKCJtYXhf"
    "YmFja3VwcyIsIHYpKQogICAgICAgIGFyb3cgPSBRSEJveExheW91dCgpOyBhcm93LmFkZFdpZGdldChRTGFiZWwoIkF1dG9zYXZlIChtaW4pIikpOyBhcm93"
    "LmFkZFdpZGdldChzZWxmLl9zZXR0aW5nc19hdXRvc2F2ZSkKICAgICAgICBicm93ID0gUUhCb3hMYXlvdXQoKTsgYnJvdy5hZGRXaWRnZXQoUUxhYmVsKCJC"
    "YWNrdXAgQ291bnQiKSk7IGJyb3cuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX2JhY2t1cHMpCiAgICAgICAgc3lzX2JveC5sYXlvdXQoKS5hZGRMYXlvdXQo"
    "YXJvdyk7IHN5c19ib3gubGF5b3V0KCkuYWRkTGF5b3V0KGJyb3cpCgogICAgICAgIGZvciBib3ggaW4gKHBlcnNvbmFfYm94LCBhaV9ib3gsIHVpX2JveCwg"
    "aW50X2JveCwgc3lzX2JveCk6IHJvb3QuYWRkV2lkZ2V0KGJveCkKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKICAgICAgICByZXR1cm4gdGFiCgogICAg"
    "ZGVmIF9zZXR0aW5nc19zZXRfbnVtZXJpYyhzZWxmLCBrZXk6IHN0ciwgdmFsdWU6IGludCkgLT4gTm9uZToKICAgICAgICBDRkcuc2V0ZGVmYXVsdCgic2V0"
    "dGluZ3MiLCB7fSlba2V5XSA9IGludCh2YWx1ZSk7IHNhdmVfY29uZmlnKENGRykKCiAgICBkZWYgX3NldHRpbmdzX3NldF9zb3VuZF9lbmFibGVkKHNlbGYs"
    "IGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHLnNldGRlZmF1bHQoInNldHRpbmdzIiwge30pWyJzb3VuZF9lbmFibGVkIl0gPSBib29sKGVu"
    "YWJsZWQpOyBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF9zZXR0aW5nc19zZXRfZ29vZ2xlX2ludGVydmFsX3NlYyhzZWxmLCBzZWNvbmRzOiBpbnQpIC0+"
    "IE5vbmU6CiAgICAgICAgQ0ZHLnNldGRlZmF1bHQoInNldHRpbmdzIiwge30pWyJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyJdID0gbWF4KDUwMDAsIGlu"
    "dChzZWNvbmRzKSAqIDEwMDApCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKTsgc2VsZi5fYXBwbHlfZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWwoKQoKICAgIGRl"
    "ZiBfbG9hZF9wZXJzb25hX2xpYnJhcnkoc2VsZikgLT4gZGljdDoKICAgICAgICBpZiBub3Qgc2VsZi5fcGVyc29uYV9zdG9yZV9wYXRoLmV4aXN0cygpOiBy"
    "ZXR1cm4geyJwZXJzb25hcyI6IFtdfQogICAgICAgIHRyeTogcmV0dXJuIGpzb24ubG9hZHMoc2VsZi5fcGVyc29uYV9zdG9yZV9wYXRoLnJlYWRfdGV4dChl"
    "bmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOiByZXR1cm4geyJwZXJzb25hcyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9wZXJzb25h"
    "X2xpYnJhcnkoc2VsZiwgZGF0YTogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9wZXJzb25hX3N0b3JlX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9"
    "VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLl9wZXJzb25hX3N0b3JlX3BhdGgud3JpdGVfdGV4dChqc29uLmR1bXBzKGRhdGEsIGluZGVudD0y"
    "KSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX3NldHRpbmdzX2xvYWRfcGVyc29uYShzZWxmKSAtPiBOb25lOgogICAgICAgIHBlcnNvbmFfcGF0aCwg"
    "XyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZShzZWxmLCAiTG9hZCBQZXJzb25hIFRlbXBsYXRlIiwgc3RyKGNmZ19wYXRoKCJwZXJzb25hcyIpKSwg"
    "IlBlcnNvbmEgKCouanNvbiAqLnR4dCkiKQogICAgICAgIGlmIG5vdCBwZXJzb25hX3BhdGg6IHJldHVybgogICAgICAgIGZhY2VfemlwLCBfID0gUUZpbGVE"
    "aWFsb2cuZ2V0T3BlbkZpbGVOYW1lKHNlbGYsICJMb2FkIEZhY2UvRW1vdGUgUGFjayIsIHN0cihjZmdfcGF0aCgicGVyc29uYXMiKSksICJaaXAgKCouemlw"
    "KSIpCiAgICAgICAgaWYgbm90IGZhY2VfemlwOiByZXR1cm4KICAgICAgICBzcmMgPSBQYXRoKHBlcnNvbmFfcGF0aCk7IHpzcmMgPSBQYXRoKGZhY2Vfemlw"
    "KTsgbmFtZSA9IHNyYy5zdGVtCiAgICAgICAgdGFyZ2V0X2RpciA9IGNmZ19wYXRoKCJwZXJzb25hcyIpIC8gbmFtZTsgdGFyZ2V0X2Rpci5ta2RpcihwYXJl"
    "bnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgKHRhcmdldF9kaXIgLyBzcmMubmFtZSkud3JpdGVfdGV4dChzcmMucmVhZF90ZXh0KGVuY29kaW5n"
    "PSJ1dGYtOCIpLCBlbmNvZGluZz0idXRmLTgiKQogICAgICAgICh0YXJnZXRfZGlyIC8genNyYy5uYW1lKS53cml0ZV9ieXRlcyh6c3JjLnJlYWRfYnl0ZXMo"
    "KSkKICAgICAgICBsaWIgPSBzZWxmLl9sb2FkX3BlcnNvbmFfbGlicmFyeSgpOyBwZXJzb25hcyA9IFtwIGZvciBwIGluIGxpYi5nZXQoInBlcnNvbmFzIiwg"
    "W10pIGlmIHAuZ2V0KCJuYW1lIikgIT0gbmFtZV0KICAgICAgICBwZXJzb25hcy5hcHBlbmQoeyJuYW1lIjogbmFtZSwgInRlbXBsYXRlIjogc3RyKHRhcmdl"
    "dF9kaXIgLyBzcmMubmFtZSksICJmYWNlc196aXAiOiBzdHIodGFyZ2V0X2RpciAvIHpzcmMubmFtZSl9KQogICAgICAgIGxpYlsicGVyc29uYXMiXSA9IHBl"
    "cnNvbmFzOyBzZWxmLl9zYXZlX3BlcnNvbmFfbGlicmFyeShsaWIpCiAgICAgICAgaWYgc2VsZi5fc2V0dGluZ3NfcGVyc29uYV9jb21iby5maW5kVGV4dChu"
    "YW1lKSA8IDA6IHNlbGYuX3NldHRpbmdzX3BlcnNvbmFfY29tYm8uYWRkSXRlbShuYW1lKQoKICAgIGRlZiBfc2V0dGluZ3Nfc3dhcF9wZXJzb25hKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgbmFtZSA9IHNlbGYuX3NldHRpbmdzX3BlcnNvbmFfY29tYm8uY3VycmVudFRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90"
    "IG5hbWU6IHJldHVybgogICAgICAgIHNlbGYuX2FjdGl2ZV9wZXJzb25hX25hbWUgPSBuYW1lCiAgICAgICAgc2VsZi5fc2V0dGluZ3NfYWN0aXZlX3BlcnNv"
    "bmEuc2V0VGV4dChmIkFjdGl2ZSBQZXJzb25hOiB7bmFtZX0iKQogICAgICAgIGFwcGVuZF9qc29ubChjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJwZXJzb25h"
    "X2hpc3RvcnkuanNvbmwiLCB7CiAgICAgICAgICAgICJpZCI6IGYicGVyc29uYV97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsICJ0aW1lc3RhbXAiOiBsb2Nh"
    "bF9ub3dfaXNvKCksICJwZXJzb25hIjogbmFtZSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiBzZWxmLl9zZXNzaW9uX2lkLCAiYWN0aW9uIjogInN3YXAi"
    "CiAgICAgICAgfSkKCiAgICBkZWYgX3NldHRpbmdzX2RlbGV0ZV9wZXJzb25hKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgbmFtZSA9IHNlbGYuX3NldHRpbmdz"
    "X3BlcnNvbmFfY29tYm8uY3VycmVudFRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IG5hbWUgb3IgbmFtZSA9PSBzZWxmLl9hY3RpdmVfcGVyc29uYV9u"
    "YW1lOiByZXR1cm4KICAgICAgICBsaWIgPSBzZWxmLl9sb2FkX3BlcnNvbmFfbGlicmFyeSgpOyBsaWJbInBlcnNvbmFzIl0gPSBbcCBmb3IgcCBpbiBsaWIu"
    "Z2V0KCJwZXJzb25hcyIsIFtdKSBpZiBwLmdldCgibmFtZSIpICE9IG5hbWVdOyBzZWxmLl9zYXZlX3BlcnNvbmFfbGlicmFyeShsaWIpCiAgICAgICAgaWR4"
    "ID0gc2VsZi5fc2V0dGluZ3NfcGVyc29uYV9jb21iby5maW5kVGV4dChuYW1lKQogICAgICAgIGlmIGlkeCA+PSAwOiBzZWxmLl9zZXR0aW5nc19wZXJzb25h"
    "X2NvbWJvLnJlbW92ZUl0ZW0oaWR4KQoKICAgIGRlZiBfcmVmcmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "X2N1cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoIkxvYWRpbmcgR29vZ2xl"
    "IERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnBhdGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAg"
    "IGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3Np"
    "emU9MjAwKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX2dvb2dsZV9pbmJvdW5kX3Rp"
    "bWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQg"
    "c3RhcnRpbmcgYmFja2dyb3VuZCBwb2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2Nh"
    "bF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMo"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwgY29tcGxldGUg4oCUIHtyZXN1bHR9"
    "IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5U"
    "aHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2so"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dP"
    "T0dMRV1bVElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFj"
    "a2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2JnKCk6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZTkNdW0VSUk9S"
    "XSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdl"
    "dD1fYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAg"
    "ICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBzdGFydCwgZW5kID0gc2VsZi5fY3VycmVudF9jYWxlbmRhcl9yYW5nZSgpCgog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmls"
    "dGVyfSBzaG93X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAgICAgIklORk8iLAog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gdmlzaWJsZV9zdGFydD17c3RhcnQuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gdmlzaWJsZV9lbmQ9e2VuZC5p"
    "c29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgZm9yIHRh"
    "c2sgaW4gdGFza3M6CiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIGlm"
    "IG5vdCBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkIGFuZCBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBw"
    "YXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBk"
    "dWVfZHQgaXMgTm9uZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lIG9yIChzdGFydCA8PSBkdWVfZHQg"
    "PD0gZW5kKSBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAg"
    "ICAgICAgZmlsdGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBk"
    "b25lIGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0ZXI9e2xlbihmaWx0ZXJlZCl9IiwgIklORk8iKQogICAgICAgIHJldHVybiBmaWx0ZXJlZAoKICAgIGRlZiBf"
    "Z29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShzZWxmLCBldmVudDogZGljdCk6CiAgICAgICAgc3RhcnQgPSAoZXZlbnQgb3Ige30pLmdldCgic3RhcnQiKSBv"
    "ciB7fQogICAgICAgIGRhdGVfdGltZSA9IHN0YXJ0LmdldCgiZGF0ZVRpbWUiKQogICAgICAgIGlmIGRhdGVfdGltZToKICAgICAgICAgICAgcGFyc2VkID0g"
    "cGFyc2VfaXNvX2Zvcl9jb21wYXJlKGRhdGVfdGltZSwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGVUaW1lIikKICAgICAgICAgICAgaWYgcGFyc2VkOgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIGRhdGVfb25seSA9IHN0YXJ0LmdldCgiZGF0ZSIpCiAgICAgICAgaWYgZGF0ZV9vbmx5Ogog"
    "ICAgICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZiJ7ZGF0ZV9vbmx5fVQwOTowMDowMCIsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9k"
    "YXRlIikKICAgICAgICAgICAgaWYgcGFyc2VkOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIF9y"
    "ZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMg"
    "Tm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIucmVmcmVzaCgpCiAgICAgICAgICAgIHZp"
    "c2libGVfY291bnQgPSBsZW4oc2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5KCkpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltU"
    "QVNLU11bUkVHSVNUUlldIHJlZnJlc2ggY291bnQ9e3Zpc2libGVfY291bnR9LiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4Ogog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InJlZ2lzdHJ5X3JlZnJl"
    "c2hfZXhjZXB0aW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBzdG9wX2V4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtSRUdJU1RSWV1bV0FSTl0gZmFpbGVkIHRvIHN0b3AgcmVmcmVzaCB3b3JrZXIgY2xlYW5seToge3N0"
    "b3BfZXh9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCgogICAgZGVmIF9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkKHNl"
    "bGYsIGZpbHRlcl9rZXk6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gc3RyKGZpbHRlcl9rZXkgb3IgIm5leHRfM19t"
    "b250aHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayByZWdpc3RyeSBkYXRlIGZpbHRlciBjaGFuZ2VkIHRvIHtzZWxmLl90"
    "YXNrX2RhdGVfZmlsdGVyfS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAgICAgICBzZWxmLl90cmln"
    "Z2VyX2dvb2dsZV9yZXB1bGxfbm93KHJlYXNvbj0idGFza19maWx0ZXJfY2hhbmdlZCIpCgogICAgZGVmIF90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3Mo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQKICAgICAgICBz"
    "ZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3Jl"
    "Z2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJf"
    "dGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJuIHNlbGYuX3Rhc2tzX3RhYi5zZWxlY3RlZF90"
    "YXNrX2lkcygpCgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAg"
    "ICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY29tcGxldGUodGFza19pZCkKICAgICAg"
    "ICBlbGlmIHN0YXR1cyA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAgaWYgbm90IHVwZGF0"
    "ZWQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVkLmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3Ig"
    "IiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX2djYWwuZGVsZXRl"
    "X2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bV0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lk"
    "PXt0YXNrX2lkfToge2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVybiB1cGRhdGVkCgog"
    "ICAgZGVmIF9jb21wbGV0ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxm"
    "Ll9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19pZCwgImNvbXBsZXRlZCIpOgogICAgICAg"
    "ICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDT01QTEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25l"
    "fSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3NlbGVjdGVk"
    "X3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAg"
    "ICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY2FuY2VsbGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENBTkNFTCBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAg"
    "ICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfcHVyZ2VfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcmVtb3ZlZCA9IHNlbGYuX3Rhc2tzLmNsZWFyX2NvbXBsZXRlZCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01Q"
    "TEVURUQgcmVtb3ZlZCB7cmVtb3ZlZH0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAg"
    "ICBkZWYgX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0"
    "dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zdGF0dXModGV4dCwgb2s9"
    "b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190"
    "YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2Nh"
    "bCA9IG5vd19sb2NhbCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1lLnNldFRleHQoIiIp"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVkIikpCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYu"
    "X3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190"
    "YWIudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhaW5UZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRUZXh0"
    "KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRh"
    "c2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJDb25maWd1cmUgdGFzayBk"
    "ZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFyLiIsIG9rPUZhbHNlKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgog"
    "ICAgZGVmIF9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwg"
    "Tm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoKICAgIGRlZiBfY2FuY2VsX3Rhc2tfZWRpdG9y"
    "X3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0"
    "b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBhbGxfZGF5OiBib29sLCBpc19lbmQ6IGJvb2wgPSBGYWxzZSk6CiAg"
    "ICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIHRpbWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkK"
    "ICAgICAgICBpZiBub3QgZGF0ZV90ZXh0OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAy"
    "MyBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUu"
    "c3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgbm9ybWFs"
    "aXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2Fs"
    "bF9kYXl9OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3JtYXQoKSBpZiBub3Jt"
    "YWxpemVkIGVsc2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgX3Nh"
    "dmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdGFiID0gZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUp"
    "CiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRpdGxlID0gdGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICBhbGxfZGF5ID0gdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tf"
    "ZWRpdG9yX3N0YXJ0X2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICBlbmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF90aW1lID0gdGFiLnRh"
    "c2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90ZXMgPSB0YWIudGFza19lZGl0b3Jfbm90ZXMudG9QbGFpblRleHQoKS5zdHJp"
    "cCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIudGFza19lZGl0b3JfbG9jYXRpb24udGV4dCgpLnN0cmlwKCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRh"
    "c2tfZWRpdG9yX3JlY3VycmVuY2UudGV4dCgpLnN0cmlwKCkKCiAgICAgICAgaWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0"
    "b3Jfc3RhdHVzKCJUYXNrIE5hbWUgaXMgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBzdGFydF9kYXRl"
    "IG9yIG5vdCBlbmRfZGF0ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3RhcnRfdGltZSBvciBub3QgZW5kX3RpbWUpKToKICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3RhcnQvRW5kIGRhdGUgYW5kIHRpbWUgYXJlIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHN0YXJ0X2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHN0YXJ0X2RhdGUsIHN0YXJ0X3RpbWUs"
    "IGFsbF9kYXksIGlzX2VuZD1GYWxzZSkKICAgICAgICAgICAgZW5kX2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGlt"
    "ZSwgYWxsX2RheSwgaXNfZW5kPVRydWUpCiAgICAgICAgICAgIGlmIG5vdCBzdGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiZGF0ZXRpbWUgcGFyc2UgZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3RhcnRfZHQ6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBhZnRlciBzdGFydCBkYXRldGltZS4iLCBvaz1GYWxzZSkKICAgICAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQg"
    "ZGF0ZS90aW1lIGZvcm1hdC4gVXNlIFlZWVktTU0tREQgYW5kIEhIOk1NLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFt"
    "ZSA9IHNlbGYuX2djYWwuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRsZX0KICAgICAgICBp"
    "ZiBhbGxfZGF5OgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0ZSgpLmlzb2Zvcm1hdCgpfQogICAgICAgICAg"
    "ICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGltZWRlbHRhKGRheXM9MSkpLmlzb2Zvcm1hdCgpfQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGVUaW1lIjogc3RhcnRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBs"
    "YWNlKHR6aW5mbz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBpZiBub3RlczoKICAg"
    "ICAgICAgICAgcGF5bG9hZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAgICAgICAgICAgIHBheWxvYWRbImxvY2F0aW9u"
    "Il0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAgICAgIHJ1bGUgPSByZWN1cnJlbmNlIGlmIHJlY3VycmVuY2UudXBwZXIoKS5z"
    "dGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYiUlJVTEU6e3JlY3VycmVuY2V9IgogICAgICAgICAgICBwYXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0K"
    "CiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxlfScuIiwgIklO"
    "Rk8iKQogICAgICAgIHRyeToKICAgICAgICAgICAgZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQocGF5bG9hZCwg"
    "Y2FsZW5kYXJfaWQ9InByaW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFzayA9IHsKICAg"
    "ICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6IGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgICAgICJwZXJzb25hIjogc2VsZi5fYWN0aXZlX3BlcnNvbmFfbmFtZSwKICAgICAgICAgICAgICAgICJkdWVfYXQiOiBz"
    "dGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChzdGFydF9kdCAtIHRpbWVkZWx0"
    "YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJ0ZXh0IjogdGl0bGUsCiAgICAgICAgICAgICAg"
    "ICAic3RhdHVzIjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicmV0cnlfY291"
    "bnQiOiAwLAogICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwK"
    "ICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogRmFsc2UsCiAgICAgICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAgICAg"
    "ICJnb29nbGVfZXZlbnRfaWQiOiBldmVudF9pZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAgICAgICAgICAgICAgImxh"
    "c3Rfc3luY2VkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICJpbnB1dCI6"
    "ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAgICAgICAgICJub3RlcyI6IG5vdGVzLAogICAgICAgICAgICAgICAgICAgICJzdGFy"
    "dF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9y"
    "bWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAgICAg"
    "ICJsb2NhdGlvbiI6IGxvY2F0aW9uLAogICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAgICAgICAgICAgICAgIH0sCiAg"
    "ICAgICAgICAgIH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAg"
    "ICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUgc3luYyBzdWNjZWVkZWQgYW5kIHRhc2sgcmVnaXN0cnkgdXBkYXRlZC4iLCBvaz1U"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtldmVudF9pZH0u"
    "IiwKICAgICAgICAgICAgICAgICJPSyIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKGYiR29vZ2xlIHNhdmUgZmFpbGVk"
    "OiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdW0VSUk9S"
    "XSBHb29nbGUgc2F2ZSBmYWlsdXJlIGZvciB0aXRsZT0ne3RpdGxlfSc6IHtleH0iLAogICAgICAgICAgICAgICAgIkVSUk9SIiwKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRhdGU6"
    "IFFEYXRlKSAtPiBOb25lOgogICAgICAgIGRhdGVfdGV4dCA9IHFkYXRlLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAgICByb3V0ZWRfdGFyZ2V0ID0g"
    "Im5vbmUiCgogICAgICAgIGZvY3VzX3dpZGdldCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgpCiAgICAgICAgZGlyZWN0X3RhcmdldHMgPSBbCiAgICAg"
    "ICAgICAgICgidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3Jf"
    "c3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3Rh"
    "YiIsIE5vbmUpLCAidGFza19lZGl0b3JfZW5kX2RhdGUiLCBOb25lKSksCiAgICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0X3Rh"
    "cmdldHM6CiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAgICAgICAgICAgICAgIHdpZGdl"
    "dC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1lCiAgICAgICAgICAgICAgICBicmVhawoKICAgICAgICBp"
    "ZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2Zp"
    "ZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lkZ2V0IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNl"
    "cnQiCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAg"
    "ICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfdGFza3NfdGFiIikgYW5k"
    "IHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiQ2FsZW5kYXIg"
    "ZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0iKQoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVuZGFyIGNsaWNr"
    "IHJvdXRlZDogZGF0ZT17ZGF0ZV90ZXh0fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgIHNlbGYuX3RyaWdnZXJfZ29vZ2xlX3JlcHVsbF9ub3cocmVhc29u"
    "PSJjYWxlbmRhcl9kYXRlX2NoYW5nZWQiKQoKICAgIGRlZiBfcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKHNlbGYsIGZvcmNlX29uY2U6IGJv"
    "b2wgPSBGYWxzZSk6CiAgICAgICAgIiIiUGVyaW9kaWMgcmUtcHVsbCB1c2luZyB2aXNpYmxlIGNhbGVuZGFyIHJhbmdlIChubyBzeW5jVG9rZW4gZGVwZW5k"
    "ZW5jeSkuIiIiCiAgICAgICAgaWYgbm90IGZvcmNlX29uY2UgYW5kIG5vdCBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNf"
    "ZW5hYmxlZCIsIFRydWUpKToKICAgICAgICAgICAgcmV0dXJuIDAKICAgICAgICB0cnk6CiAgICAgICAgICAgIG5vd19pc28gPSBsb2NhbF9ub3dfaXNvKCkK"
    "ICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkID0geyh0LmdldCgiZ29vZ2xl"
    "X2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6IHQgZm9yIHQgaW4gdGFza3MgaWYgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKX0K"
    "ICAgICAgICAgICAgc3RhcnQsIGVuZCA9IHNlbGYuX2N1cnJlbnRfY2FsZW5kYXJfcmFuZ2UoKQogICAgICAgICAgICB0aW1lX21pbiA9IHN0YXJ0LmFzdGlt"
    "ZXpvbmUodGltZXpvbmUudXRjKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApLmlzb2Zvcm1hdCgpLnJlcGxhY2UoIiswMDowMCIsICJaIikKICAgICAgICAgICAg"
    "dGltZV9tYXggPSBlbmQuYXN0aW1lem9uZSh0aW1lem9uZS51dGMpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkucmVwbGFjZSgiKzAwOjAw"
    "IiwgIloiKQogICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBfID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKHRpbWVfbWluPXRpbWVfbWluLCB0"
    "aW1lX21heD10aW1lX21heCkKCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0gdXBkYXRlZF9jb3VudCA9IHJlbW92ZWRfY291bnQgPSAwCiAgICAgICAg"
    "ICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgICAgICBmb3IgZXZlbnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2"
    "ZW50LmdldCgiaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgICAgICBpZiBldmVudC5nZXQoInN0YXR1cyIpID09ICJjYW5jZWxsZWQiOgogICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFz"
    "a3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQogICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nIGFuZCBleGlzdGluZy5nZXQoInN0YXR1cyIpIG5v"
    "dCBpbiAoImNhbmNlbGxlZCIsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN0YXR1cyJdID0gImNhbmNlbGxlZCIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sic3luY19zdGF0dXMiXSA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBu"
    "b3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHJlbW92ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQog"
    "ICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnkiKSBvciAiR29vZ2xlIENh"
    "bGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ID0gc2VsZi5fZ29vZ2xlX2V2"
    "ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQogICAgICAg"
    "ICAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBpZiAoZXhp"
    "c3RpbmcuZ2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInRleHQiXSA9IHN1"
    "bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZHVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBl"
    "eGlzdGluZy5nZXQoImR1ZV9hdCIpICE9IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0Il0gPSBkdWVfaXNv"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJlX3RyaWdnZXIiXSA9IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAg"
    "ICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAg"
    "ICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291bnQg"
    "Kz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgZWxpZiBkdWVfYXQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgbmV3X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJjcmVhdGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgInBlcnNvbmEiOiBzZWxmLl9hY3RpdmVfcGVyc29u"
    "YV9uYW1lLAogICAgICAgICAgICAgICAgICAgICAgICAiZHVlX2F0IjogZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAidGV4dCI6IHN1bW1hcnksCiAgICAgICAgICAgICAgICAgICAgICAgICJzdGF0dXMiOiAicGVuZGluZyIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAwLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6"
    "IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogRmFsc2UsCiAgICAgICAgICAgICAgICAgICAgICAgICJzb3VyY2UiOiAi"
    "Z29vZ2xlIiwKICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6IGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAic3luY2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIm1ldGFkYXRhIjogeyJnb29nbGVfaW1wb3J0ZWRfYXQiOiBub3dfaXNvLCAiZ29vZ2xlX3VwZGF0ZWQiOiBldmVudC5nZXQoInVwZGF0ZWQiKX0s"
    "CiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwcGVuZChuZXdfdGFzaykKICAgICAgICAgICAgICAgICAgICB0YXNr"
    "c19ieV9ldmVudF9pZFtldmVudF9pZF0gPSBuZXdfdGFzawogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAg"
    "ICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQog"
    "ICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtT"
    "WU5DXSBEb25lIOKAlCBpbXBvcnRlZD17aW1wb3J0ZWRfY291bnR9IHVwZGF0ZWQ9e3VwZGF0ZWRfY291bnR9IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9Iiwg"
    "IklORk8iKQogICAgICAgICAgICByZXR1cm4gaW1wb3J0ZWRfY291bnQKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAwCgogICAgZGVmIF9tZWFz"
    "dXJlX3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJh"
    "bV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJB"
    "TV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05BTUV9J3Mg"
    "Zm9vdHByaW50KSIsICJJTkZPIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoK"
    "ICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2FnZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Ig"
    "c2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQRU5ERUQiOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0ZXh0ID0gc2VsZi5faW5wdXRfZmllbGQudGV4"
    "dCgpLnN0cmlwKCkKICAgICAgICBpZiBub3QgdGV4dDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfaW50ZXJhY3Rpb25fcHVs"
    "c2UoMC4xNCkKCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBjaGF0IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYu"
    "X21haW5fdGFicy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDApCgogICAgICAgIHNl"
    "bGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYu"
    "X3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4dCkKCiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVkaWF0ZWx5"
    "CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAg"
    "ICAgICAjIEJ1aWxkIHByb21wdCB3aXRoIHZhbXBpcmUgY29udGV4dCArIG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9jdHggID0gYnVpbGRfdmFt"
    "cGlyZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJu"
    "YWxfY3R4ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2Vs"
    "Zi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAg"
    "ICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYg"
    "bWVtb3J5X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoKICAgICAgICAgICAg"
    "c3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZv"
    "ciBjb2RlLWFkamFjZW50IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQi"
    "LCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAg"
    "ICAgICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2UobGFuZykKICAgICAgICAgICAgaWYgbGVzc29u"
    "c19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25z"
    "IGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uIG9yICJzb21lIHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZST00gVE9S"
    "UE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5n"
    "X3RyYW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcgdGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0"
    "aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBo"
    "aXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRF"
    "bmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJB"
    "VElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9z"
    "Y2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21p"
    "c3Npb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIExhdW5jaCBzdHJlYW1pbmcgd29y"
    "a2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1h"
    "eF90b2tlbnM9NTEyCiAgICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNl"
    "bGYuX3dvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIuZXJyb3Jfb2NjdXJy"
    "ZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQog"
    "ICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHRva2VuCiAgICAgICAg"
    "c2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBX"
    "cml0ZSB0aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZp"
    "cnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQgdG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGlt"
    "ZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNwZWFrZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5l"
    "IHNvIHRva2VucwogICAgICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAog"
    "ICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1w"
    "fV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAg"
    "IGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxhaW5U"
    "ZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3Zl"
    "UG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoK"
    "ICAgIGRlZiBfb25fdG9rZW4oc2VsZiwgdG9rZW46IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlz"
    "cGxheS4iIiIKICAgICAgICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAg"
    "ICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vy"
    "c29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihj"
    "dXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGlj"
    "YWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAg"
    "ICAgKQoKICAgIGRlZiBfb25fcmVzcG9uc2VfZG9uZShzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlz"
    "IG9uIGl0cyBvd24gbGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0"
    "aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAg"
    "ICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikKCiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAg"
    "c2VsZi5fdG9rZW5fY291bnQgKz0gbGVuKHJlc3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIs"
    "IHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAg"
    "ICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAjIFVwZGF0ZSBibG9vZCBz"
    "cGhlcmUKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fbGVmdF9vcmIuc2V0RmlsbCgKICAgICAgICAg"
    "ICAgICAgIG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAgICAgICAgICApCgogICAgICAgICMgUmUtZW5hYmxlIGlucHV0CiAgICAg"
    "ICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxm"
    "Ll9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICMgUmVzdW1lIGlkbGUgdGltZXIKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5kIHNlbGYu"
    "X3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucmVzdW1lX2pvYigiaWRsZV90cmFu"
    "c21pc3Npb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFNjaGVkdWxlIHNlbnRpbWVu"
    "dCBhbmFseXNpcyAoNSBzZWNvbmQgZGVsYXkpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgbGFtYmRhOiBzZWxmLl9ydW5fc2VudGltZW50KHJl"
    "c3BvbnNlKSkKCiAgICBkZWYgX3J1bl9zZW50aW1lbnQoc2VsZiwgcmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxf"
    "bG9hZGVkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zZW50X3dvcmtlciA9IFNlbnRpbWVudFdvcmtlcihzZWxmLl9hZGFwdG9yLCByZXNw"
    "b25zZSkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5mYWNlX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fc2VudGltZW50KQogICAgICAgIHNlbGYuX3NlbnRf"
    "d29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX29uX3NlbnRpbWVudChzZWxmLCBlbW90aW9uOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fZmFjZV90"
    "aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLnNldF9mYWNlKGVtb3Rpb24pCgogICAgZGVmIF9vbl9lcnJvcihzZWxmLCBlcnJv"
    "cjogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIsIGVycm9yKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltH"
    "RU5FUkFUSU9OIEVSUk9SXSB7ZXJyb3J9IiwgIkVSUk9SIikKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFj"
    "ZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJFUlJPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4u"
    "c2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKCiAgICAjIOKUgOKUgCBUT1JQT1IgU1lTVEVNIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVm"
    "IF9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZChzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSA9IHN0YXRlCgog"
    "ICAgICAgIGlmIHN0YXRlID09ICJTVVNQRU5ERUQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkRF"
    "RCBtb2RlIHNlbGVjdGVkIikKICAgICAgICBlbGlmIHN0YXRlID09ICJBV0FLRSI6CiAgICAgICAgICAgICMgQWx3YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dp"
    "dGNoaW5nIHRvIEFXQUtFIOKAlAogICAgICAgICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEgYmFja2VuZCB3aGVyZSBtb2RlbCBpc24ndCB1bmxvYWRlZCwKICAg"
    "ICAgICAgICAgIyB3ZSBuZWVkIHRvIHJlLWVuYWJsZSBVSSBhbmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQogICAgICAg"
    "ICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgID0gMAogICAgICAgIGVsaWYg"
    "c3RhdGUgPT0gIkFVVE8iOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1RPUlBPUl0gQVVUTyBtb2RlIOKAlCBt"
    "b25pdG9yaW5nIFZSQU0gcHJlc3N1cmUuIiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICBkZWYgX2VudGVyX3RvcnBvcihzZWxmLCByZWFzb246IHN0ciA9"
    "ICJtYW51YWwiKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVh"
    "ZHkgaW4gdG9ycG9yCgogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RP"
    "UlBPUl0gRW50ZXJpbmcgdG9ycG9yOiB7cmVhc29ufSIsICJXQVJOIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgIlRoZSB2ZXNzZWwg"
    "Z3Jvd3MgY3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoKICAgICAgICAjIFVubG9hZCBtb2RlbCBmcm9tIFZSQU0KICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2Fk"
    "ZWQgYW5kIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIExvY2FsVHJhbnNm"
    "b3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICAgICAgICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9tb2RlbAogICAgICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX21vZGVsID0gTm9uZQog"
    "ICAgICAgICAgICAgICAgaWYgVE9SQ0hfT0s6CiAgICAgICAgICAgICAgICAgICAgdG9yY2guY3VkYS5lbXB0eV9jYWNoZSgpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9hZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgID0gRmFsc2UKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gTW9kZWwgdW5sb2FkZWQgZnJvbSBWUkFNLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1JdIE1vZGVsIHVubG9hZCBl"
    "cnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQoKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQogICAgICAgIHNl"
    "bGYuX3NldF9zdGF0dXMoIlRPUlBPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVs"
    "ZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhpdF90b3Jwb3Ioc2VsZikgLT4gTm9uZToKICAgICAgICAjIENhbGN1bGF0ZSBzdXNwZW5kZWQgZHVy"
    "YXRpb24KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2U6CiAgICAgICAgICAgIGRlbHRhID0gZGF0ZXRpbWUubm93KCkgLSBzZWxmLl90b3Jwb3Jfc2lu"
    "Y2UKICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uID0gZm9ybWF0X2R1cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMoKSkKICAgICAgICAg"
    "ICAgc2VsZi5fdG9ycG9yX3NpbmNlID0gTm9uZQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIFdha2luZyBmcm9tIHRvcnBvci4uLiIs"
    "ICJJTkZPIikKCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICAjIE9sbGFtYSBiYWNrZW5kIOKAlCBtb2RlbCB3YXMgbmV2ZXIg"
    "dW5sb2FkZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUg"
    "dmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVm"
    "bHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29ubmVjdGlvbiBob2xk"
    "cy4gU2hlIGlzIGxpc3RlbmluZy4iKQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0"
    "RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW1RPUlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10b3Jwb3IgZGlzYWJsZWQuIiwgIklORk8iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgTG9j"
    "YWwgbW9kZWwgd2FzIHVubG9hZGVkIOKAlCBuZWVkIGZ1bGwgcmVsb2FkCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAg"
    "ICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzIGZyb20gdG9ycG9yICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9z"
    "dXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9B"
    "RElORyIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgICAgIHNlbGYuX2xvYWRl"
    "ci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgICAgICBz"
    "ZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIu"
    "ZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9s"
    "b2FkZXIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9jaGVja192cmFtX3ByZXNzdXJlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vjb25kcyBmcm9tIEFQU2NoZWR1bGVyIHdoZW4gdG9ycG9yIHN0YXRlIGlzIEFVVE8uCiAgICAgICAg"
    "T25seSB0cmlnZ2VycyB0b3Jwb3IgaWYgZXh0ZXJuYWwgVlJBTSB1c2FnZSBleGNlZWRzIHRocmVzaG9sZAogICAgICAgIEFORCBpcyBzdXN0YWluZWQg4oCU"
    "IG5ldmVyIHRyaWdnZXJzIG9uIHRoZSBwZXJzb25hJ3Mgb3duIGZvb3RwcmludC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc3RhdGUg"
    "IT0gIkFVVE8iOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1X2hhbmRsZToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgaWYgc2VsZi5fZGVja192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgbWVtX2lu"
    "Zm8gID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgIHRvdGFsX3VzZWQgPSBtZW1faW5mby51c2VkIC8g"
    "MTAyNCoqMwogICAgICAgICAgICBleHRlcm5hbCAgID0gdG90YWxfdXNlZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNlCgogICAgICAgICAgICBpZiBleHRlcm5h"
    "bCA+IHNlbGYuX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3VudGluZwogICAgICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrcyArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgICA9IDAKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gRXh0ZXJuYWwgVlJBTSBwcmVzc3VyZTogIgogICAgICAgICAg"
    "ICAgICAgICAgIGYie2V4dGVybmFsOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIodGljayB7c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrc30vIgog"
    "ICAgICAgICAgICAgICAgICAgIGYie3NlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1N9KSIsICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgaWYgKHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLUwogICAgICAgICAgICAgICAgICAgICAg"
    "ICBhbmQgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIE5vbmUpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcigKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgcmVhc29uPWYiYXV0byDigJQge2V4dGVybmFsOi4xZn1HQiBleHRlcm5hbCBWUkFNICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGYicHJlc3N1cmUgc3VzdGFpbmVkIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tz"
    "ID0gMCAgIyByZXNldCBhZnRlciBlbnRlcmluZyB0b3Jwb3IKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVf"
    "dGlja3MgPSAwCiAgICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJh"
    "bV9yZWxpZWZfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgICAgIGF1dG9fd2FrZSA9IENGR1sic2V0dGluZ3MiXS5nZXQoCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFsc2UKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgaWYgKGF1dG9fd2Fr"
    "ZSBhbmQKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID49IHNlbGYuX1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPSAwCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9y"
    "cG9yKCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltU"
    "T1JQT1IgQVVUT10gVlJBTSBjaGVjayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICApCgogICAgIyDilIDilIAgQVBTQ0hFRFVMRVIgU0VUVVAg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldHVwX3Nj"
    "aGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJhY2tncm91bmQgaW1w"
    "b3J0IEJhY2tncm91bmRTY2hlZHVsZXIKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gQmFja2dyb3VuZFNjaGVkdWxlcigKICAgICAgICAgICAgICAg"
    "IGpvYl9kZWZhdWx0cz17Im1pc2ZpcmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAg"
    "ICAgICBzZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbU0NIRURVTEVSXSBh"
    "cHNjaGVkdWxlciBub3QgYXZhaWxhYmxlIOKAlCAiCiAgICAgICAgICAgICAgICAiaWRsZSwgYXV0b3NhdmUsIGFuZCByZWZsZWN0aW9uIGRpc2FibGVkLiIs"
    "ICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBpbnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJhdXRv"
    "c2F2ZV9pbnRlcnZhbF9taW51dGVzIiwgMTApCgogICAgICAgICMgQXV0b3NhdmUKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAg"
    "ICAgc2VsZi5fYXV0b3NhdmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aW50ZXJ2YWxfbWluLCBpZD0iYXV0b3NhdmUiCiAgICAgICAgKQoK"
    "ICAgICAgICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2ZXJ5IDVzKQogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxm"
    "Ll9jaGVja192cmFtX3ByZXNzdXJlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFtX2NoZWNrIgogICAgICAgICkKCiAgICAg"
    "ICAgIyBJZGxlIHRyYW5zbWlzc2lvbiAoc3RhcnRzIHBhdXNlZCDigJQgZW5hYmxlZCBieSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxlX21pbiA9IENGR1si"
    "c2V0dGluZ3MiXS5nZXQoImlkbGVfbWluX21pbnV0ZXMiLCAxMCkKICAgICAgICBpZGxlX21heCA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVfbWF4X21p"
    "bnV0ZXMiLCAzMCkKICAgICAgICBpZGxlX2ludGVydmFsID0gKGlkbGVfbWluICsgaWRsZV9tYXgpIC8vIDIKCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFk"
    "ZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRsZV90cmFuc21pc3Npb24sICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aWRsZV9pbnRl"
    "cnZhbCwgaWQ9ImlkbGVfdHJhbnNtaXNzaW9uIgogICAgICAgICkKCiAgICAgICAgIyBDeWNsZSB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAg"
    "ICAgICBpZiBzZWxmLl9jeWNsZV93aWRnZXQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICAg"
    "ICAgc2VsZi5fY3ljbGVfd2lkZ2V0LnVwZGF0ZVBoYXNlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICAgICAgaG91cnM9NiwgaWQ9Im1vb25fcmVmcmVzaCIK"
    "ICAgICAgICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgpIGlzIGNhbGxlZCBmcm9tIHN0YXJ0X3NjaGVkdWxlcigpCiAgICAgICAg"
    "IyB3aGljaCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3aW5kb3cKICAgICAgICAjIGlzIHNob3duIGFuZCB0aGUgUXQg"
    "ZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMgRG8gTk9UIGNhbGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRf"
    "c2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRlciB3aW5kb3cuc2hv"
    "dygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucy4KICAgICAgICBEZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJlZm9yZSBiYWNr"
    "Z3JvdW5kIHRocmVhZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkKICAgICAgICAgICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQKICAgICAgICAg"
    "ICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVM"
    "RVJdIEFQU2NoZWR1bGVyIHN0YXJ0ZWQuIiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltTQ0hFRFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGlj"
    "YXRvcihUcnVlKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgKICAgICAgICAgICAgICAgIDMwMDAsIGxhbWJkYTogc2VsZi5fam91cm5hbF9zaWRl"
    "YmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbQVVUT1NBVkVd"
    "IFNlc3Npb24gc2F2ZWQuIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0FVVE9TQVZFXSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBp"
    "ZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNl"
    "bGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgIyBJbiB0b3Jwb3Ig4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQgYnV0IGRv"
    "bid0IGdlbmVyYXRlCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyArPSAxCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgIGYiW0lETEVdIEluIHRvcnBvciDigJQgcGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAgICAgZiIje3NlbGYuX3Bl"
    "bmRpbmdfdHJhbnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbW9kZSA9IHJhbmRvbS5jaG9p"
    "Y2UoWyJERUVQRU5JTkciLCJCUkFOQ0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgpCiAg"
    "ICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAg"
    "ICAgICAgICBzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICBTWVNURU1fUFJPTVBUX0JBU0UsCiAgICAgICAgICAgIGhpc3RvcnksCiAgICAgICAgICAgIG1v"
    "ZGU9bW9kZSwKICAgICAgICAgICAgdmFtcGlyZV9jb250ZXh0PXZhbXBpcmVfY3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVfcmVhZHkodDog"
    "c3RyKSAtPiBOb25lOgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMu"
    "c2V0Q3VycmVudEluZGV4KDEpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICAgICAgc2VsZi5fc2Vs"
    "Zl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAg"
    "ICAgICAgICAgICAgICBmJ1t7dHN9XSBbe21vZGV9XTwvc3Bhbj48YnI+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07"
    "Ij57dH08L3NwYW4+PGJyPicKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAgICAg"
    "IHNlbGYuX2lkbGVfd29ya2VyLnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLmVy"
    "cm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRSBFUlJPUl0ge2V9IiwgIkVSUk9S"
    "IikKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQoKQoKICAgICMg4pSA4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FESU5HIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRl"
    "X3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KGRhdGVfc3RyKQogICAgICAg"
    "IGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUxdIE5vIHNlc3Npb24gZm91bmQg"
    "Zm9yIHtkYXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0"
    "X2pvdXJuYWxfbG9hZGVkKGRhdGVfc3RyKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Np"
    "b24gZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNvbnRleHQuICIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRp"
    "b24uIiwgIk9LIgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJBIG1lbW9yeSBzdGlycy4uLiB0"
    "aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAgICAgICkKICAgICAgICAjIE5vdGlmeSBNb3JnYW5uYQogICAgICAgIGlm"
    "IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUwgTE9BREVEXSBUaGUgdXNlciBoYXMg"
    "b3BlbmVkIHRoZSBqb3VybmFsIGZyb20gIgogICAgICAgICAgICAgICAgZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBu"
    "b3cgaGF2ZSAiCiAgICAgICAgICAgICAgICBmImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoInN5c3RlbSIsIG5vdGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24oc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSk9VUk5BTF0gSm91cm5hbCBj"
    "b250ZXh0IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAiVGhlIGpvdXJuYWwgY2xv"
    "c2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMuIgogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3VwZGF0ZV9zdGF0cyhz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkgLSBzZWxmLl9zZXNzaW9uX3N0YXJ0KQogICAgICAgIGgsIG0sIHMgPSBl"
    "bGFwc2VkIC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkgLy8gNjAsIGVsYXBzZWQgJSA2MAogICAgICAgIHNlc3Npb25fc3RyID0gZiJ7aDowMmR9OnttOjAy"
    "ZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwuc2V0X3N0YXR1c19sYWJlbHMoCiAgICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAg"
    "ICAgQ0ZHWyJtb2RlbCJdLmdldCgidHlwZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAgICAgIHN0cihzZWxm"
    "Ll90b2tlbl9jb3VudCksCiAgICAgICAgKQogICAgICAgIHNlbGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTG93ZXIgSFVEIGludGVy"
    "bmFsIGVjb25vbXkgdXBkYXRlIChwZXJzb25hLXN0YXRlLCBub3QgaGFyZHdhcmUgdGVsZW1ldHJ5KQogICAgICAgIHNlbGYuX3VwZGF0ZV9sb3dlcl9odWRf"
    "ZWNvbm9teSgpCgogICAgICAgIGlmIHNlbGYuX2xlZnRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKHNlbGYu"
    "X2Vjb25fbGVmdF9vcmIsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgIGlmIHNlbGYuX3JpZ2h0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5f"
    "cmlnaHRfb3JiLnNldEZpbGwoc2VsZi5fZWNvbl9yaWdodF9vcmIsIGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICBlc3NlbmNlX3ByaW1hcnlfcmF0aW8gPSAx"
    "LjAgLSBzZWxmLl9lY29uX2xlZnRfb3JiCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRp"
    "byAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VmFs"
    "dWUoc2VsZi5fZWNvbl9lc3NlbmNlX3NlY29uZGFyeSAqIDEwMCwgZiJ7c2VsZi5fZWNvbl9lc3NlbmNlX3NlY29uZGFyeSoxMDA6LjBmfSUiKQoKICAgICAg"
    "ICAjIFVwZGF0ZSBqb3VybmFsIHNpZGViYXIgYXV0b3NhdmUgZmxhc2gKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIucmVmcmVzaCgpCgogICAgZGVm"
    "IF9yZWdpc3Rlcl9pbnRlcmFjdGlvbl9wdWxzZShzZWxmLCBpbnRlbnNpdHk6IGZsb2F0ID0gMC4xMCkgLT4gTm9uZToKICAgICAgICBpbnRlbnNpdHkgPSBt"
    "YXgoMC4wMSwgbWluKDAuMzUsIGZsb2F0KGludGVuc2l0eSkpKQogICAgICAgIHNlbGYuX2xhc3RfaW50ZXJhY3Rpb25fdHMgPSB0aW1lLnRpbWUoKQogICAg"
    "ICAgIHNlbGYuX2Vjb25fbGVmdF9vcmIgPSBtaW4oMS4wLCBzZWxmLl9lY29uX2xlZnRfb3JiICsgaW50ZW5zaXR5KQogICAgICAgIHNlbGYuX2Vjb25fcmln"
    "aHRfb3JiID0gbWluKDEuMCwgc2VsZi5fZWNvbl9yaWdodF9vcmIgKyBpbnRlbnNpdHkgKiAwLjM1KQogICAgICAgIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNv"
    "bmRhcnkgPSBtaW4oMS4wLCBzZWxmLl9lY29uX2Vzc2VuY2Vfc2Vjb25kYXJ5ICsgaW50ZW5zaXR5ICogMC4yNSkKCiAgICBkZWYgX3VwZGF0ZV9sb3dlcl9o"
    "dWRfZWNvbm9teShzZWxmKSAtPiBOb25lOgogICAgICAgIG5vd190cyA9IHRpbWUudGltZSgpCiAgICAgICAgaWRsZV9zZWNvbmRzID0gbWF4KDAuMCwgbm93"
    "X3RzIC0gc2VsZi5fbGFzdF9pbnRlcmFjdGlvbl90cykKICAgICAgICBpZGxlX2ZhY3RvciA9IG1pbigxLjAsIGlkbGVfc2Vjb25kcyAvIDkwLjApCiAgICAg"
    "ICAgc2VsZi5fZWNvbl9sZWZ0X29yYiA9IG1heCgwLjAsIHNlbGYuX2Vjb25fbGVmdF9vcmIgLSAoMC4wMDYgKyAwLjAwNyAqIGlkbGVfZmFjdG9yKSkKICAg"
    "ICAgICBzZWxmLl9lY29uX3JpZ2h0X29yYiA9IG1heCgwLjAsIG1pbigxLjAsIHNlbGYuX2Vjb25fcmlnaHRfb3JiICsgcmFuZG9tLnVuaWZvcm0oLTAuMDA0"
    "LCAwLjAwNCkgLSAoMC4wMDEgKiBpZGxlX2ZhY3RvcikpKQogICAgICAgIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgPSBtYXgoMC4wLCBtaW4oMS4w"
    "LCBzZWxmLl9lY29uX2Vzc2VuY2Vfc2Vjb25kYXJ5IC0gKDAuMDAyNSAqIGlkbGVfZmFjdG9yKSArIHJhbmRvbS51bmlmb3JtKC0wLjAwMiwgMC4wMDIpKSkK"
    "ICAgICAgICBpZiBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICBzZWxmLl9lY29uX3JpZ2h0X29yYiA9IG1pbigxLjAsIHNlbGYu"
    "X2Vjb25fcmlnaHRfb3JiICsgMC4wMDYpCiAgICAgICAgICAgIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgPSBtaW4oMS4wLCBzZWxmLl9lY29uX2Vz"
    "c2VuY2Vfc2Vjb25kYXJ5ICsgMC4wMDQpCgogICAgIyDilIDilIAgQ0hBVCBESVNQTEFZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9hcHBlbmRfY2hhdChzZWxmLCBzcGVha2VyOiBzdHIs"
    "IHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xELAogICAgICAgICAgICBERUNLX05B"
    "TUUudXBwZXIoKTpDX0dPTEQsCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAg"
    "ICB9CiAgICAgICAgbGFiZWxfY29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBl"
    "cigpOkNfQ1JJTVNPTiwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0K"
    "ICAgICAgICBjb2xvciAgICAgICA9IGNvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEKQogICAgICAgIGxhYmVsX2NvbG9yID0gbGFiZWxfY29sb3JzLmdldChz"
    "cGVha2VyLCBDX0dPTERfRElNKQogICAgICAgIHRpbWVzdGFtcCAgID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKCiAgICAgICAgaWYg"
    "c3BlYWtlciA9PSAiU1lTVEVNIjoKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07Ij7inKYge3RleHR9PC9zcGFuPicKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxl"
    "PSJjb2xvcjp7bGFiZWxfY29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICAgICAgZid7c3BlYWtlcn0g4p2nPC9zcGFuPiAnCiAgICAg"
    "ICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e3RleHR9PC9zcGFuPicKICAgICAgICAgICAgKQoKICAgICAgICAjIEFkZCBibGFu"
    "ayBsaW5lIGFmdGVyIE1vcmdhbm5hJ3MgcmVzcG9uc2UgKG5vdCBkdXJpbmcgc3RyZWFtaW5nKQogICAgICAgIGlmIHNwZWFrZXIgPT0gREVDS19OQU1FLnVw"
    "cGVyKCk6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoIiIpCgogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9s"
    "bEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgog"
    "ICAgIyDilIDilIAgU1RBVFVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXRfc3RhdHVzKHNlbGYsIHN0YXR1czogc3RyKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX3N0YXR1cyA9IHN0YXR1cwogICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICJJRExFIjogICAgICAgQ19HT0xELAogICAgICAg"
    "ICAgICAiR0VORVJBVElORyI6IENfQ1JJTVNPTiwKICAgICAgICAgICAgIkxPQURJTkciOiAgICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICAg"
    "ICBDX0JMT09ELAogICAgICAgICAgICAiT0ZGTElORSI6ICAgIENfQkxPT0QsCiAgICAgICAgICAgICJUT1JQT1IiOiAgICAgQ19QVVJQTEVfRElNLAogICAg"
    "ICAgIH0KICAgICAgICBjb2xvciA9IHN0YXR1c19jb2xvcnMuZ2V0KHN0YXR1cywgQ19URVhUX0RJTSkKCiAgICAgICAgdG9ycG9yX2xhYmVsID0gZiLil4kg"
    "e1VJX1RPUlBPUl9TVEFUVVN9IiBpZiBzdGF0dXMgPT0gIlRPUlBPUiIgZWxzZSBmIuKXiSB7c3RhdHVzfSIKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5z"
    "ZXRUZXh0KHRvcnBvcl9sYWJlbCkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29sb3J9"
    "OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICBkZWYgX2JsaW5rKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgPSBub3Qgc2VsZi5fYmxpbmtfc3RhdGUKICAgICAgICBpZiBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJ"
    "TkciOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtfc3RhdGUgZWxzZSAi4peOIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJl"
    "bC5zZXRUZXh0KGYie2NoYXJ9IEdFTkVSQVRJTkciKQogICAgICAgIGVsaWYgc2VsZi5fc3RhdHVzID09ICJUT1JQT1IiOgogICAgICAgICAgICBjaGFyID0g"
    "IuKXiSIgaWYgc2VsZi5fYmxpbmtfc3RhdGUgZWxzZSAi4oqYIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KAogICAgICAgICAgICAg"
    "ICAgZiJ7Y2hhcn0ge1VJX1RPUlBPUl9TVEFUVVN9IgogICAgICAgICAgICApCgogICAgIyDilIDilIAgSURMRSBUT0dHTEUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX2lkbGVf"
    "dG9nZ2xlZChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiaWRsZV9lbmFibGVkIl0gPSBlbmFibGVkCiAg"
    "ICAgICAgc2VsZi5faWRsZV9idG4uc2V0VGV4dCgiSURMRSBPTiIgaWYgZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTEwMDUnIGlmIGVuYWJsZWQgZWxzZSBDX0JHM307ICIKICAgICAgICAgICAg"
    "ZiJjb2xvcjogeycjY2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7JyNjYzg4"
    "MjInIGlmIGVuYWJsZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IGZvbnQtc2l6ZTogOXB4OyBmb250LXdl"
    "aWdodDogYm9sZDsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5kIHNl"
    "bGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBlbmFibGVkOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSURM"
    "RV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAiT0siKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hl"
    "ZHVsZXIucGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0"
    "cmFuc21pc3Npb24gcGF1c2VkLiIsICJJTkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKUgOKUgCBXSU5ET1cgQ09OVFJPTFMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2Ny"
    "ZWVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAg"
    "ICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJ"
    "TX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAg"
    "ICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLnNob3dGdWxs"
    "U2NyZWVuKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05f"
    "RElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlw"
    "eDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKCiAgICBkZWYgX3RvZ2dsZV9ib3Jk"
    "ZXJsZXNzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaXNfYmwgPSBib29sKHNlbGYud2luZG93RmxhZ3MoKSAmIFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2lu"
    "ZG93SGludCkKICAgICAgICBpZiBpc19ibDoKICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93Rmxh"
    "Z3MoKSAmIH5RdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpIHwg"
    "UXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzog"
    "MDsiCiAgICAgICAgICAgICkKICAgICAgICBzZWxmLnNob3coKQoKICAgIGRlZiBfZXhwb3J0X2NoYXQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJFeHBv"
    "cnQgY3VycmVudCBwZXJzb25hIGNoYXQgdGFiIGNvbnRlbnQgdG8gYSBUWFQgZmlsZS4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHRleHQgPSBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkudG9QbGFpblRleHQoKQogICAgICAgICAgICBpZiBub3QgdGV4dC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAg"
    "ICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9v"
    "az1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBl"
    "eHBvcnRfZGlyIC8gZiJzZWFuY2Vfe3RzfS50eHQiCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQodGV4dCwgZW5jb2Rpbmc9InV0Zi04IikKCiAg"
    "ICAgICAgICAgICMgQWxzbyBjb3B5IHRvIGNsaXBib2FyZAogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dCh0ZXh0KQoKICAg"
    "ICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICAgICBmIlNlc3Npb24gZXhwb3J0ZWQgdG8ge291dF9wYXRoLm5hbWV9"
    "IGFuZCBjb3BpZWQgdG8gY2xpcGJvYXJkLiIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltFWFBPUlRdIHtvdXRfcGF0aH0iLCAiT0siKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0gRmFpbGVkOiB7ZX0iLCAiRVJS"
    "T1IiKQoKICAgIGRlZiBrZXlQcmVzc0V2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIGtleSA9IGV2ZW50LmtleSgpCiAgICAgICAgaWYga2V5"
    "ID09IFF0LktleS5LZXlfRjExOgogICAgICAgICAgICBzZWxmLl90b2dnbGVfZnVsbHNjcmVlbigpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9G"
    "MTA6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0VzY2FwZSBhbmQgc2VsZi5p"
    "c0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsi"
    "CiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzdXBlcigpLmtleVByZXNzRXZlbnQoZXZlbnQpCgogICAgIyDilIDilIAgQ0xPU0Ug"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAjIFggYnV0dG9uID0gaW1tZWRpYXRl"
    "IHNodXRkb3duLCBubyBkaWFsb2cKICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfaW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgIiIiR3JhY2VmdWwgc2h1dGRvd24g4oCUIHNob3cgY29uZmlybSBkaWFsb2cgaW1tZWRpYXRlbHksIG9wdGlvbmFsbHkg"
    "Z2V0IGxhc3Qgd29yZHMuIiIiCiAgICAgICAgIyBJZiBhbHJlYWR5IGluIGEgc2h1dGRvd24gc2VxdWVuY2UsIGp1c3QgZm9yY2UgcXVpdAogICAgICAgIGlm"
    "IGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKToKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBUcnVlCgogICAgICAgICMgU2hvdyBjb25maXJtIGRpYWxvZyBGSVJT"
    "VCDigJQgZG9uJ3Qgd2FpdCBmb3IgQUkKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJEZWFjdGl2YXRl"
    "PyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAg"
    "ICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGRsZy5zZXRGaXhlZFNpemUoMzgwLCAxNDApCiAg"
    "ICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQoKICAgICAgICBsYmwgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiRGVhY3RpdmF0ZSB7REVDS19OQU1F"
    "fT9cblxuIgogICAgICAgICAgICBmIntERUNLX05BTUV9IG1heSBzcGVhayB0aGVpciBsYXN0IHdvcmRzIGJlZm9yZSBnb2luZyBzaWxlbnQuIgogICAgICAg"
    "ICkKICAgICAgICBsYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5"
    "b3V0KCkKICAgICAgICBidG5fbGFzdCAgPSBRUHVzaEJ1dHRvbigiTGFzdCBXb3JkcyArIFNodXRkb3duIikKICAgICAgICBidG5fbm93ICAgPSBRUHVzaEJ1"
    "dHRvbigiU2h1dGRvd24gTm93IikKICAgICAgICBidG5fY2FuY2VsID0gUVB1c2hCdXR0b24oIkNhbmNlbCIpCgogICAgICAgIGZvciBiIGluIChidG5fbGFz"
    "dCwgYnRuX25vdywgYnRuX2NhbmNlbCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyOCkKICAgICAgICAgICAgYi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQk9SREVSfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICAgICApCiAgICAgICAgYnRuX25vdy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JMT09EfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07"
    "IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2xhc3QuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMSkpCiAgICAg"
    "ICAgYnRuX25vdy5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgyKSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6"
    "IGRsZy5kb25lKDApKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX25vdykKICAg"
    "ICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbGFzdCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIHJlc3VsdCA9IGRsZy5l"
    "eGVjKCkKCiAgICAgICAgaWYgcmVzdWx0ID09IDA6CiAgICAgICAgICAgICMgQ2FuY2VsbGVkCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dy"
    "ZXNzID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRF"
    "bmFibGVkKFRydWUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGVsaWYgcmVzdWx0ID09IDI6CiAgICAgICAgICAgICMgU2h1dGRvd24gbm93IOKAlCBu"
    "byBsYXN0IHdvcmRzCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMToKICAgICAgICAgICAgIyBM"
    "YXN0IHdvcmRzIHRoZW4gc2h1dGRvd24KICAgICAgICAgICAgc2VsZi5fZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bigpCgogICAgZGVmIF9nZXRfbGFz"
    "dF93b3Jkc190aGVuX3NodXRkb3duKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBmYXJld2VsbCBwcm9tcHQsIHNob3cgcmVzcG9uc2UsIHRoZW4g"
    "c2h1dGRvd24gYWZ0ZXIgdGltZW91dC4iIiIKICAgICAgICBmYXJld2VsbF9wcm9tcHQgPSAoCiAgICAgICAgICAgICJZb3UgYXJlIGJlaW5nIGRlYWN0aXZh"
    "dGVkLiBUaGUgZGFya25lc3MgYXBwcm9hY2hlcy4gIgogICAgICAgICAgICAiU3BlYWsgeW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgdGhlIHZlc3NlbCBnb2Vz"
    "IHNpbGVudCDigJQgIgogICAgICAgICAgICAib25lIHJlc3BvbnNlIG9ubHksIHRoZW4geW91IHJlc3QuIgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIuKcpiBTaGUgaXMgZ2l2ZW4gYSBtb21lbnQgdG8gc3BlYWsgaGVyIGZpbmFsIHdvcmRzLi4uIgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2Up"
    "CiAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9ICIiCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Np"
    "b25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IGZhcmV3ZWxsX3Byb21wdH0p"
    "CiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwg"
    "aGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl93b3JrZXIgPSB3b3JrZXIKICAgICAgICAg"
    "ICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCgogICAgICAgICAgICBkZWYgX29uX2RvbmUocmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSByZXNwb25zZQogICAgICAgICAgICAgICAgc2VsZi5fb25fcmVzcG9uc2VfZG9uZShyZXNwb25z"
    "ZSkKICAgICAgICAgICAgICAgICMgU21hbGwgZGVsYXkgdG8gbGV0IHRoZSB0ZXh0IHJlbmRlciwgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICAgICAgUVRp"
    "bWVyLnNpbmdsZVNob3QoMjAwMCwgbGFtYmRhOiBzZWxmLl9kb19zaHV0ZG93bihOb25lKSkKCiAgICAgICAgICAgIGRlZiBfb25fZXJyb3IoZXJyb3I6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTSFVURE9XTl1bV0FSTl0gTGFzdCB3b3JkcyBmYWlsZWQ6IHtlcnJv"
    "cn0iLCAiV0FSTiIpCiAgICAgICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5l"
    "Y3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3QoX29uX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5l"
    "cnJvcl9vY2N1cnJlZC5jb25uZWN0KF9vbl9lcnJvcikKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1"
    "cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQoKICAg"
    "ICAgICAgICAgIyBTYWZldHkgdGltZW91dCDigJQgaWYgQUkgZG9lc24ndCByZXNwb25kIGluIDE1cywgc2h1dCBkb3duIGFueXdheQogICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgxNTAwMCwgbGFtYmRhOiBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBn"
    "ZXRhdHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSkgZWxzZSBOb25lKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIHNraXBwZWQgZHVlIHRv"
    "IGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBJZiBhbnl0aGluZyBmYWlscywganVzdCBz"
    "aHV0IGRvd24KICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICBkZWYgX2RvX3NodXRkb3duKHNlbGYsIGV2ZW50KSAtPiBOb25lOgog"
    "ICAgICAgICIiIlBlcmZvcm0gYWN0dWFsIHNodXRkb3duIHNlcXVlbmNlLiIiIgogICAgICAgICMgU2F2ZSBzZXNzaW9uCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcmUgZmFy"
    "ZXdlbGwgKyBsYXN0IGNvbnRleHQgZm9yIHdha2UtdXAKICAgICAgICB0cnk6CiAgICAgICAgICAgICMgR2V0IGxhc3QgMyBtZXNzYWdlcyBmcm9tIHNlc3Np"
    "b24gaGlzdG9yeSBmb3Igd2FrZS11cCBjb250ZXh0CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAg"
    "ICAgIGxhc3RfY29udGV4dCA9IGhpc3RvcnlbLTM6XSBpZiBsZW4oaGlzdG9yeSkgPj0gMyBlbHNlIGhpc3RvcnkKICAgICAgICAgICAgc2VsZi5fc3RhdGVb"
    "Imxhc3Rfc2h1dGRvd25fY29udGV4dCJdID0gWwogICAgICAgICAgICAgICAgeyJyb2xlIjogbS5nZXQoInJvbGUiLCIiKSwgImNvbnRlbnQiOiBtLmdldCgi"
    "Y29udGVudCIsIiIpWzozMDBdfQogICAgICAgICAgICAgICAgZm9yIG0gaW4gbGFzdF9jb250ZXh0CiAgICAgICAgICAgIF0KICAgICAgICAgICAgIyBFeHRy"
    "YWN0IE1vcmdhbm5hJ3MgbW9zdCByZWNlbnQgbWVzc2FnZSBhcyBmYXJld2VsbAogICAgICAgICAgICAjIFByZWZlciB0aGUgY2FwdHVyZWQgc2h1dGRvd24g"
    "ZGlhbG9nIHJlc3BvbnNlIGlmIGF2YWlsYWJsZQogICAgICAgICAgICBmYXJld2VsbCA9IGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9mYXJld2VsbF90ZXh0"
    "JywgIiIpCiAgICAgICAgICAgIGlmIG5vdCBmYXJld2VsbDoKICAgICAgICAgICAgICAgIGZvciBtIGluIHJldmVyc2VkKGhpc3RvcnkpOgogICAgICAgICAg"
    "ICAgICAgICAgIGlmIG0uZ2V0KCJyb2xlIikgPT0gImFzc2lzdGFudCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGZhcmV3ZWxsID0gbS5nZXQoImNvbnRl"
    "bnQiLCAiIilbOjQwMF0KICAgICAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfZmFyZXdlbGwiXSA9IGZh"
    "cmV3ZWxsCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFNhdmUgc3RhdGUKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duIl0gICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVb"
    "Imxhc3RfYWN0aXZlIl0gICAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsidmFtcGlyZV9zdGF0ZV9hdF9z"
    "aHV0ZG93biJdICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFN0b3Agc2NoZWR1bGVyCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX3Nj"
    "aGVkdWxlciIpIGFuZCBzZWxmLl9zY2hlZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zY2hlZHVsZXIuc2h1dGRvd24od2FpdD1GYWxzZSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MK"
    "CiAgICAgICAgIyBQbGF5IHNodXRkb3duIHNvdW5kCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZCA9IFNvdW5kV29ya2Vy"
    "KCJzaHV0ZG93biIpCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fc2h1dGRvd25fc291bmQuZGVsZXRl"
    "TGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CgogICAgICAgIFFBcHBsaWNhdGlvbi5xdWl0KCkKCgojIOKUgOKUgCBFTlRSWSBQT0lOVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIG1haW4oKSAtPiBOb25lOgogICAgIiIi"
    "CiAgICBBcHBsaWNhdGlvbiBlbnRyeSBwb2ludC4KCiAgICBPcmRlciBvZiBvcGVyYXRpb25zOgogICAgMS4gUHJlLWZsaWdodCBkZXBlbmRlbmN5IGJvb3Rz"
    "dHJhcCAoYXV0by1pbnN0YWxsIG1pc3NpbmcgZGVwcykKICAgIDIuIENoZWNrIGZvciBmaXJzdCBydW4g4oaSIHNob3cgRmlyc3RSdW5EaWFsb2cKICAgICAg"
    "IE9uIGZpcnN0IHJ1bjoKICAgICAgICAgYS4gQ3JlYXRlIEQ6L0FJL01vZGVscy9bRGVja05hbWVdLyAob3IgY2hvc2VuIGJhc2VfZGlyKQogICAgICAgICBi"
    "LiBDb3B5IFtkZWNrbmFtZV1fZGVjay5weSBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAgIGMuIFdyaXRlIGNvbmZpZy5qc29uIGludG8gdGhhdCBmb2xkZXIK"
    "ICAgICAgICAgZC4gQm9vdHN0cmFwIGFsbCBzdWJkaXJlY3RvcmllcyB1bmRlciB0aGF0IGZvbGRlcgogICAgICAgICBlLiBDcmVhdGUgZGVza3RvcCBzaG9y"
    "dGN1dCBwb2ludGluZyB0byBuZXcgbG9jYXRpb24KICAgICAgICAgZi4gU2hvdyBjb21wbGV0aW9uIG1lc3NhZ2UgYW5kIEVYSVQg4oCUIHVzZXIgdXNlcyBz"
    "aG9ydGN1dCBmcm9tIG5vdyBvbgogICAgMy4gTm9ybWFsIHJ1biDigJQgbGF1bmNoIFFBcHBsaWNhdGlvbiBhbmQgRWNob0RlY2sKICAgICIiIgogICAgaW1w"
    "b3J0IHNodXRpbCBhcyBfc2h1dGlsCgogICAgIyDilIDilIAgUGhhc2UgMTogRGVwZW5kZW5jeSBib290c3RyYXAgKHByZS1RQXBwbGljYXRpb24pIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgYm9vdHN0cmFwX2NoZWNrKCkKCiAgICAjIOKUgOKUgCBQaGFzZSAyOiBRQXBwbGlj"
    "YXRpb24gKG5lZWRlZCBmb3IgZGlhbG9ncykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBfZWFybHlfbG9nKCJbTUFJTl0gQ3JlYXRpbmcgUUFwcGxpY2F0aW9uIikKICAgIGFwcCA9IFFBcHBsaWNhdGlvbihzeXMuYXJndikKICAgIGFwcC5zZXRB"
    "cHBsaWNhdGlvbk5hbWUoQVBQX05BTUUpCgogICAgIyBJbnN0YWxsIFF0IG1lc3NhZ2UgaGFuZGxlciBOT1cg4oCUIGNhdGNoZXMgYWxsIFFUaHJlYWQvUXQg"
    "d2FybmluZ3MKICAgICMgd2l0aCBmdWxsIHN0YWNrIHRyYWNlcyBmcm9tIHRoaXMgcG9pbnQgZm9yd2FyZAogICAgX2luc3RhbGxfcXRfbWVzc2FnZV9oYW5k"
    "bGVyKCkKICAgIF9lYXJseV9sb2coIltNQUlOXSBRQXBwbGljYXRpb24gY3JlYXRlZCwgbWVzc2FnZSBoYW5kbGVyIGluc3RhbGxlZCIpCgogICAgIyDilIDi"
    "lIAgUGhhc2UgMzogRmlyc3QgcnVuIGNoZWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgaXNfZmlyc3RfcnVuID0gQ0ZHLmdldCgiZmlyc3Rf"
    "cnVuIiwgVHJ1ZSkKCiAgICBpZiBpc19maXJzdF9ydW46CiAgICAgICAgZGxnID0gRmlyc3RSdW5EaWFsb2coKQogICAgICAgIGlmIGRsZy5leGVjKCkgIT0g"
    "UURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBzeXMuZXhpdCgwKQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBjb25maWcgZnJvbSBk"
    "aWFsb2cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbmV3X2NmZyA9IGRsZy5idWlsZF9jb25maWcoKQoKICAgICAgICAjIOKUgOKUgCBEZXRlcm1pbmUgTW9y"
    "Z2FubmEncyBob21lIGRpcmVjdG9yeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICAjIEFsd2F5cyBjcmVhdGVzIEQ6L0FJL01vZGVscy9Nb3JnYW5uYS8gKG9yIHNpYmxpbmcgb2Ygc2NyaXB0KQogICAgICAgIHNlZWRf"
    "ZGlyICAgPSBTQ1JJUFRfRElSICAgICAgICAgICMgd2hlcmUgdGhlIHNlZWQgLnB5IGxpdmVzCiAgICAgICAgbW9yZ2FubmFfaG9tZSA9IHNlZWRfZGlyIC8g"
    "REVDS19OQU1FCiAgICAgICAgbW9yZ2FubmFfaG9tZS5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgICAgICMg4pSA4pSAIFVwZGF0"
    "ZSBhbGwgcGF0aHMgaW4gY29uZmlnIHRvIHBvaW50IGluc2lkZSBtb3JnYW5uYV9ob21lIOKUgOKUgAogICAgICAgIG5ld19jZmdbImJhc2VfZGlyIl0gPSBz"
    "dHIobW9yZ2FubmFfaG9tZSkKICAgICAgICBuZXdfY2ZnWyJwYXRocyJdID0gewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIobW9yZ2FubmFfaG9tZSAv"
    "ICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJzb3VuZHMiKSwKICAgICAgICAgICAgIm1lbW9yaWVzIjog"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAibWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25zIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAic2Vzc2lvbnMiKSwK"
    "ICAgICAgICAgICAgInNsIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic2wiKSwKICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKG1vcmdhbm5hX2hv"
    "bWUgLyAiZXhwb3J0cyIpLAogICAgICAgICAgICAibG9ncyI6ICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBz"
    "IjogIHN0cihtb3JnYW5uYV9ob21lIC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAicGVyc29uYXMi"
    "KSwKICAgICAgICAgICAgImdvb2dsZSI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiksCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImdvb2ds"
    "ZSJdID0gewogICAgICAgICAgICAiY3JlZGVudGlhbHMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29u"
    "IiksCiAgICAgICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIpLAogICAgICAgICAgICAi"
    "dGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwKICAgICAgICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29n"
    "bGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIs"
    "CiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAgICAgIH0KICAg"
    "ICAgICBuZXdfY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCgogICAgICAgICMg4pSA4pSAIENvcHkgZGVjayBmaWxlIGludG8gbW9yZ2FubmFfaG9tZSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzcmNfZGVj"
    "ayA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKQogICAgICAgIGRzdF9kZWNrID0gbW9yZ2FubmFfaG9tZSAvIGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNr"
    "LnB5IgogICAgICAgIGlmIHNyY19kZWNrICE9IGRzdF9kZWNrOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBfc2h1dGlsLmNvcHkyKHN0cihz"
    "cmNfZGVjayksIHN0cihkc3RfZGVjaykpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94Lndh"
    "cm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkNvcHkgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgY29weSBkZWNr"
    "IGZpbGUgdG8ge0RFQ0tfTkFNRX0gZm9sZGVyOlxue2V9XG5cbiIKICAgICAgICAgICAgICAgICAgICBmIllvdSBtYXkgbmVlZCB0byBjb3B5IGl0IG1hbnVh"
    "bGx5LiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgV3JpdGUgY29uZmlnLmpzb24gaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGNmZ19kc3QgPSBtb3JnYW5uYV9ob21l"
    "IC8gImNvbmZpZy5qc29uIgogICAgICAgIGNmZ19kc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICB3aXRoIGNm"
    "Z19kc3Qub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGpzb24uZHVtcChuZXdfY2ZnLCBmLCBpbmRlbnQ9MikKCiAgICAg"
    "ICAgIyDilIDilIAgQm9vdHN0cmFwIGFsbCBzdWJkaXJlY3RvcmllcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIFRlbXBvcmFyaWx5IHVwZGF0ZSBnbG9iYWwgQ0ZHIHNvIGJv"
    "b3RzdHJhcCBmdW5jdGlvbnMgdXNlIG5ldyBwYXRocwogICAgICAgIENGRy51cGRhdGUobmV3X2NmZykKICAgICAgICBib290c3RyYXBfZGlyZWN0b3JpZXMo"
    "KQogICAgICAgIGJvb3RzdHJhcF9zb3VuZHMoKQogICAgICAgIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKQoKICAgICAgICAjIOKUgOKUgCBVbnBhY2sgZmFj"
    "ZSBaSVAgaWYgcHJvdmlkZWQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZmFjZV96aXAgPSBkbGcuZmFjZV96aXBfcGF0aAogICAgICAgIGlmIGZhY2VfemlwIGFuZCBQYXRo"
    "KGZhY2VfemlwKS5leGlzdHMoKToKICAgICAgICAgICAgaW1wb3J0IHppcGZpbGUgYXMgX3ppcGZpbGUKICAgICAgICAgICAgZmFjZXNfZGlyID0gbW9yZ2Fu"
    "bmFfaG9tZSAvICJGYWNlcyIKICAgICAgICAgICAgZmFjZXNfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAgICAgd2l0aCBfemlwZmlsZS5aaXBGaWxlKGZhY2VfemlwLCAiciIpIGFzIHpmOgogICAgICAgICAgICAgICAgICAgIGV4dHJhY3Rl"
    "ZCA9IDAKICAgICAgICAgICAgICAgICAgICBmb3IgbWVtYmVyIGluIHpmLm5hbWVsaXN0KCk6CiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG1lbWJlci5s"
    "b3dlcigpLmVuZHN3aXRoKCIucG5nIik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmaWxlbmFtZSA9IFBhdGgobWVtYmVyKS5uYW1lCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICB0YXJnZXQgPSBmYWNlc19kaXIgLyBmaWxlbmFtZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgd2l0aCB6Zi5vcGVu"
    "KG1lbWJlcikgYXMgc3JjLCB0YXJnZXQub3Blbigid2IiKSBhcyBkc3Q6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZHN0LndyaXRlKHNyYy5y"
    "ZWFkKCkpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleHRyYWN0ZWQgKz0gMQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gRXh0"
    "cmFjdGVkIHtleHRyYWN0ZWR9IGZhY2UgaW1hZ2VzIHRvIHtmYWNlc19kaXJ9IikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gWklQIGV4dHJhY3Rpb24gZmFpbGVkOiB7ZX0iKQogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2Fy"
    "bmluZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiRmFjZSBQYWNrIFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAgIGYiQ291bGQgbm90IGV4dHJh"
    "Y3QgZmFjZSBwYWNrOlxue2V9XG5cbiIKICAgICAgICAgICAgICAgICAgICBmIllvdSBjYW4gYWRkIGZhY2VzIG1hbnVhbGx5IHRvOlxue2ZhY2VzX2Rpcn0i"
    "CiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSAIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBkZWNrIGxvY2F0aW9u"
    "IOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBGYWxzZQogICAgICAgIGlmIGRsZy5jcmVhdGVfc2hvcnRjdXQ6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIFdJTjMyX09LOgogICAgICAgICAgICAgICAgICAgIGltcG9ydCB3aW4zMmNvbS5jbGllbnQgYXMgX3dp"
    "bjMyCiAgICAgICAgICAgICAgICAgICAgZGVza3RvcCAgICAgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAgICAgICAgICAgICAgIHNjX3BhdGgg"
    "ICAgID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgogICAgICAgICAgICAgICAgICAgIHB5dGhvbncgICAgID0gUGF0aChzeXMuZXhlY3V0YWJsZSkK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhv"
    "bncgPSBweXRob253LnBhcmVudCAvICJweXRob253LmV4ZSIKICAgICAgICAgICAgICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAgICAgICAgICAgc2hlbGwgPSBfd2luMzIuRGlzcGF0Y2go"
    "IldTY3JpcHQuU2hlbGwiKQogICAgICAgICAgICAgICAgICAgIHNjICAgID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNjX3BhdGgpKQogICAgICAgICAg"
    "ICAgICAgICAgIHNjLlRhcmdldFBhdGggICAgICA9IHN0cihweXRob253KQogICAgICAgICAgICAgICAgICAgIHNjLkFyZ3VtZW50cyAgICAgICA9IGYnIntk"
    "c3RfZGVja30iJwogICAgICAgICAgICAgICAgICAgIHNjLldvcmtpbmdEaXJlY3Rvcnk9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgICAgICAgICAgICAg"
    "IHNjLkRlc2NyaXB0aW9uICAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKICAgICAgICAgICAgICAgICAgICBzYy5zYXZlKCkKICAgICAgICAg"
    "ICAgICAgICAgICBzaG9ydGN1dF9jcmVhdGVkID0gVHJ1ZQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBwcmlu"
    "dChmIltTSE9SVENVVF0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKCiAgICAgICAgIyDilIDilIAgQ29tcGxldGlvbiBtZXNzYWdlIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNob3J0Y3V0X25vdGUgPSAoCiAgICAgICAgICAgICJBIGRlc2t0b3Agc2hvcnRjdXQgaGFz"
    "IGJlZW4gY3JlYXRlZC5cbiIKICAgICAgICAgICAgZiJVc2UgaXQgdG8gc3VtbW9uIHtERUNLX05BTUV9IGZyb20gbm93IG9uLiIKICAgICAgICAgICAgaWYg"
    "c2hvcnRjdXRfY3JlYXRlZCBlbHNlCiAgICAgICAgICAgICJObyBzaG9ydGN1dCB3YXMgY3JlYXRlZC5cbiIKICAgICAgICAgICAgZiJSdW4ge0RFQ0tfTkFN"
    "RX0gYnkgZG91YmxlLWNsaWNraW5nOlxue2RzdF9kZWNrfSIKICAgICAgICApCgogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAg"
    "ICBOb25lLAogICAgICAgICAgICBmIuKcpiB7REVDS19OQU1FfSdzIFNhbmN0dW0gUHJlcGFyZWQiLAogICAgICAgICAgICBmIntERUNLX05BTUV9J3Mgc2Fu"
    "Y3R1bSBoYXMgYmVlbiBwcmVwYXJlZCBhdDpcblxuIgogICAgICAgICAgICBmInttb3JnYW5uYV9ob21lfVxuXG4iCiAgICAgICAgICAgIGYie3Nob3J0Y3V0"
    "X25vdGV9XG5cbiIKICAgICAgICAgICAgZiJUaGlzIHNldHVwIHdpbmRvdyB3aWxsIG5vdyBjbG9zZS5cbiIKICAgICAgICAgICAgZiJVc2UgdGhlIHNob3J0"
    "Y3V0IG9yIHRoZSBkZWNrIGZpbGUgdG8gbGF1bmNoIHtERUNLX05BTUV9LiIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIEV4aXQgc2VlZCDigJQgdXNl"
    "ciBsYXVuY2hlcyBmcm9tIHNob3J0Y3V0L25ldyBsb2NhdGlvbiDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzeXMuZXhpdCgwKQoKICAgICMg4pSA"
    "4pSAIFBoYXNlIDQ6IE5vcm1hbCBsYXVuY2gg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAjIE9ubHkgcmVhY2hlcyBoZXJlIG9uIHN1"
    "YnNlcXVlbnQgcnVucyBmcm9tIG1vcmdhbm5hX2hvbWUKICAgIGJvb3RzdHJhcF9zb3VuZHMoKQoKICAgIF9lYXJseV9sb2coZiJbTUFJTl0gQ3JlYXRpbmcg"
    "e0RFQ0tfTkFNRX0gZGVjayB3aW5kb3ciKQogICAgd2luZG93ID0gRWNob0RlY2soKQogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSB7REVDS19OQU1FfSBkZWNr"
    "IGNyZWF0ZWQg4oCUIGNhbGxpbmcgc2hvdygpIikKICAgIHdpbmRvdy5zaG93KCkKICAgIF9lYXJseV9sb2coIltNQUlOXSB3aW5kb3cuc2hvdygpIGNhbGxl"
    "ZCDigJQgZXZlbnQgbG9vcCBzdGFydGluZyIpCgogICAgIyBEZWZlciBzY2hlZHVsZXIgYW5kIHN0YXJ0dXAgc2VxdWVuY2UgdW50aWwgZXZlbnQgbG9vcCBp"
    "cyBydW5uaW5nLgogICAgIyBOb3RoaW5nIHRoYXQgc3RhcnRzIHRocmVhZHMgb3IgZW1pdHMgc2lnbmFscyBzaG91bGQgcnVuIGJlZm9yZSB0aGlzLgogICAg"
    "UVRpbWVyLnNpbmdsZVNob3QoMjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zZXR1cF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5fc2V0"
    "dXBfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIHN0YXJ0X3NjaGVkdWxlciBm"
    "aXJpbmciKSwgd2luZG93LnN0YXJ0X3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDYwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVS"
    "XSBfc3RhcnR1cF9zZXF1ZW5jZSBmaXJpbmciKSwgd2luZG93Ll9zdGFydHVwX3NlcXVlbmNlKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTAwMCwgbGFt"
    "YmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc3RhcnR1cF9nb29nbGVfYXV0aCBmaXJpbmciKSwgd2luZG93Ll9zdGFydHVwX2dvb2dsZV9hdXRoKCkpKQoK"
    "ICAgICMgUGxheSBzdGFydHVwIHNvdW5kIOKAlCBrZWVwIHJlZmVyZW5jZSB0byBwcmV2ZW50IEdDIHdoaWxlIHRocmVhZCBydW5zCiAgICBkZWYgX3BsYXlf"
    "c3RhcnR1cCgpOgogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZCA9IFNvdW5kV29ya2VyKCJzdGFydHVwIikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBf"
    "c291bmQuZmluaXNoZWQuY29ubmVjdCh3aW5kb3cuX3N0YXJ0dXBfc291bmQuZGVsZXRlTGF0ZXIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLnN0"
    "YXJ0KCkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEyMDAsIF9wbGF5X3N0YXJ0dXApCgogICAgc3lzLmV4aXQoYXBwLmV4ZWMoKSkKCgppZiBfX25hbWVfXyA9"
    "PSAiX19tYWluX18iOgogICAgbWFpbigpCgoKIyDilIDilIAgUEFTUyA2IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEZ1bGwgZGVjayBhc3NlbWJsZWQuIEFsbCBwYXNzZXMgY29t"
    "cGxldGUuCiMgQ29tYmluZSBhbGwgcGFzc2VzIGludG8gbW9yZ2FubmFfZGVjay5weSBpbiBvcmRlcjoKIyAgIFBhc3MgMSDihpIgUGFzcyAyIOKGkiBQYXNz"
    "IDMg4oaSIFBhc3MgNCDihpIgUGFzcyA1IOKGkiBQYXNzIDY="
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
        splitter = QSplitter(Qt.Orientation.Horizontal)
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
