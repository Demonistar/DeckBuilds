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
    "dG9uLCBRR3JvdXBCb3gKKQpmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBRVGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6"
    "ZSwgUVBvaW50LCBRUmVjdAopCmZyb20gUHlTaWRlNi5RdEd1aSBpbXBvcnQgKAogICAgUUZvbnQsIFFDb2xvciwgUVBhaW50ZXIsIFFMaW5lYXJHcmFkaWVu"
    "dCwgUVJhZGlhbEdyYWRpZW50LAogICAgUVBpeG1hcCwgUVBlbiwgUVBhaW50ZXJQYXRoLCBRVGV4dENoYXJGb3JtYXQsIFFJY29uLAogICAgUVRleHRDdXJz"
    "b3IsIFFBY3Rpb24KKQoKIyDilIDilIAgQVBQIElERU5USVRZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApBUFBfTkFNRSAgICAgID0gVUlfV0lORE9XX1RJVExFCkFQUF9WRVJTSU9OICAg"
    "PSAiMi4wLjAiCkFQUF9GSUxFTkFNRSAgPSBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKQlVJTERfREFURSAgICA9ICIyMDI2LTA0LTA0IgoKIyDi"
    "lIDilIAgQ09ORklHIExPQURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgY29uZmlnLmpzb24gbGl2ZXMgbmV4dCB0byB0aGUgZGVjayAucHkgZmlsZS4KIyBBbGwgcGF0aHMgY29tZSBm"
    "cm9tIGNvbmZpZy4gTm90aGluZyBoYXJkY29kZWQgYmVsb3cgdGhpcyBwb2ludC4KClNDUklQVF9ESVIgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkucGFy"
    "ZW50CkNPTkZJR19QQVRIID0gU0NSSVBUX0RJUiAvICJjb25maWcuanNvbiIKCiMgSW5pdGlhbGl6ZSBlYXJseSBsb2cgbm93IHRoYXQgd2Uga25vdyB3aGVy"
    "ZSB3ZSBhcmUKX2luaXRfZWFybHlfbG9nKFNDUklQVF9ESVIpCl9lYXJseV9sb2coZiJbSU5JVF0gU0NSSVBUX0RJUiA9IHtTQ1JJUFRfRElSfSIpCl9lYXJs"
    "eV9sb2coZiJbSU5JVF0gQ09ORklHX1BBVEggPSB7Q09ORklHX1BBVEh9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBjb25maWcuanNvbiBleGlzdHM6IHtDT05G"
    "SUdfUEFUSC5leGlzdHMoKX0iKQoKZGVmIF9kZWZhdWx0X2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiIiJSZXR1cm5zIHRoZSBkZWZhdWx0IGNvbmZpZyBzdHJ1"
    "Y3R1cmUgZm9yIGZpcnN0LXJ1biBnZW5lcmF0aW9uLiIiIgogICAgYmFzZSA9IHN0cihTQ1JJUFRfRElSKQogICAgcmV0dXJuIHsKICAgICAgICAiZGVja19u"
    "YW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAiYmFzZV9kaXIiOiBiYXNlLAogICAgICAgICJt"
    "b2RlbCI6IHsKICAgICAgICAgICAgInR5cGUiOiAibG9jYWwiLCAgICAgICAgICAjIGxvY2FsIHwgb2xsYW1hIHwgY2xhdWRlIHwgb3BlbmFpCiAgICAgICAg"
    "ICAgICJwYXRoIjogIiIsICAgICAgICAgICAgICAgIyBsb2NhbCBtb2RlbCBmb2xkZXIgcGF0aAogICAgICAgICAgICAib2xsYW1hX21vZGVsIjogIiIsICAg"
    "ICAgICMgZS5nLiAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgICAgICJhcGlfa2V5IjogIiIsICAgICAgICAgICAgIyBDbGF1ZGUgb3IgT3BlbkFJIGtleQog"
    "ICAgICAgICAgICAiYXBpX3R5cGUiOiAiIiwgICAgICAgICAgICMgImNsYXVkZSIgfCAib3BlbmFpIgogICAgICAgICAgICAiYXBpX21vZGVsIjogIiIsICAg"
    "ICAgICAgICMgZS5nLiAiY2xhdWRlLXNvbm5ldC00LTYiCiAgICAgICAgfSwKICAgICAgICAiZ29vZ2xlIjogewogICAgICAgICAgICAiY3JlZGVudGlhbHMi"
    "OiBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiksCiAgICAgICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihT"
    "Q1JJUFRfRElSIC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwKICAgICAg"
    "ICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAg"
    "ICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBp"
    "cy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAgICAgIH0sCiAgICAgICAgInBhdGhzIjogewogICAgICAgICAgICAiZmFjZXMiOiAg"
    "ICBzdHIoU0NSSVBUX0RJUiAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoU0NSSVBUX0RJUiAvICJzb3VuZHMiKSwKICAgICAgICAg"
    "ICAgIm1lbW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAibWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25zIjogc3RyKFNDUklQVF9ESVIgLyAic2Vz"
    "c2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAic2wiKSwKICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQ"
    "VF9ESVIgLyAiZXhwb3J0cyIpLAogICAgICAgICAgICAibG9ncyI6ICAgICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBz"
    "IjogIHN0cihTQ1JJUFRfRElSIC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKFNDUklQVF9ESVIgLyAicGVyc29uYXMiKSwKICAg"
    "ICAgICAgICAgImdvb2dsZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAgICAgICAgfSwKICAgICAgICAic2V0dGluZ3MiOiB7CiAgICAgICAg"
    "ICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJpZGxlX21pbl9taW51dGVzIjogICAgICAgICAgMTAsCiAgICAg"
    "ICAgICAgICJpZGxlX21heF9taW51dGVzIjogICAgICAgICAgMzAsCiAgICAgICAgICAgICJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAg"
    "ICAgICAgICJtYXhfYmFja3VwcyI6ICAgICAgICAgICAgICAgMTAsCiAgICAgICAgICAgICJnb29nbGVfc3luY19lbmFibGVkIjogICAgICAgVHJ1ZSwKICAg"
    "ICAgICAgICAgInNvdW5kX2VuYWJsZWQiOiAgICAgICAgICAgICBUcnVlLAogICAgICAgICAgICAiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiOiAzMDAw"
    "MDAsCiAgICAgICAgICAgICJnb29nbGVfbG9va2JhY2tfZGF5cyI6ICAgICAgMzAsCiAgICAgICAgICAgICJ1c2VyX2RlbGF5X3RocmVzaG9sZF9taW4iOiAg"
    "MzAsCiAgICAgICAgfSwKICAgICAgICAiZmlyc3RfcnVuIjogVHJ1ZSwKICAgIH0KCmRlZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiIiJMb2FkIGNv"
    "bmZpZy5qc29uLiBSZXR1cm5zIGRlZmF1bHQgaWYgbWlzc2luZyBvciBjb3JydXB0LiIiIgogICAgaWYgbm90IENPTkZJR19QQVRILmV4aXN0cygpOgogICAg"
    "ICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQogICAgdHJ5OgogICAgICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW5nPSJ1dGYtOCIp"
    "IGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZp"
    "ZygpCgpkZWYgc2F2ZV9jb25maWcoY2ZnOiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29uZmlnLmpzb24uIiIiCiAgICBDT05GSUdfUEFUSC5wYXJl"
    "bnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBDT05GSUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMg"
    "ZjoKICAgICAgICBqc29uLmR1bXAoY2ZnLCBmLCBpbmRlbnQ9MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxlIGxldmVsIOKAlCBldmVyeXRoaW5nIGJlbG93"
    "IHJlYWRzIGZyb20gQ0ZHCkNGRyA9IGxvYWRfY29uZmlnKCkKX2Vhcmx5X2xvZyhmIltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NGRy5n"
    "ZXQoJ2ZpcnN0X3J1bicpfSwgbW9kZWxfdHlwZT17Q0ZHLmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0iKQoKX0RFRkFVTFRfUEFUSFM6IGRpY3Rbc3Ry"
    "LCBQYXRoXSA9IHsKICAgICJmYWNlcyI6ICAgIFNDUklQVF9ESVIgLyAiRmFjZXMiLAogICAgInNvdW5kcyI6ICAgU0NSSVBUX0RJUiAvICJzb3VuZHMiLAog"
    "ICAgIm1lbW9yaWVzIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAgICAic2Vzc2lvbnMiOiBTQ1JJUFRfRElSIC8gInNlc3Npb25zIiwKICAgICJzbCI6"
    "ICAgICAgIFNDUklQVF9ESVIgLyAic2wiLAogICAgImV4cG9ydHMiOiAgU0NSSVBUX0RJUiAvICJleHBvcnRzIiwKICAgICJsb2dzIjogICAgIFNDUklQVF9E"
    "SVIgLyAibG9ncyIsCiAgICAiYmFja3VwcyI6ICBTQ1JJUFRfRElSIC8gImJhY2t1cHMiLAogICAgInBlcnNvbmFzIjogU0NSSVBUX0RJUiAvICJwZXJzb25h"
    "cyIsCiAgICAiZ29vZ2xlIjogICBTQ1JJUFRfRElSIC8gImdvb2dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpIC0+IE5vbmU6CiAgICAi"
    "IiIKICAgIFNlbGYtaGVhbCBvbGRlciBjb25maWcuanNvbiBmaWxlcyBtaXNzaW5nIHJlcXVpcmVkIHBhdGgga2V5cy4KICAgIEFkZHMgbWlzc2luZyBwYXRo"
    "IGtleXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnRpYWwvdG9rZW4gbG9jYXRpb25zLAogICAgdGhlbiBwZXJzaXN0cyBjb25maWcuanNvbiBpZiBh"
    "bnl0aGluZyBjaGFuZ2VkLgogICAgIiIiCiAgICBjaGFuZ2VkID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNldGRlZmF1bHQoInBhdGhzIiwge30pCiAgICBm"
    "b3Iga2V5LCBkZWZhdWx0X3BhdGggaW4gX0RFRkFVTFRfUEFUSFMuaXRlbXMoKToKICAgICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAgICAg"
    "IHBhdGhzW2tleV0gPSBzdHIoZGVmYXVsdF9wYXRoKQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGdvb2dsZV9jZmcgPSBDRkcuc2V0ZGVmYXVs"
    "dCgiZ29vZ2xlIiwge30pCiAgICBnb29nbGVfcm9vdCA9IFBhdGgocGF0aHMuZ2V0KCJnb29nbGUiLCBzdHIoX0RFRkFVTFRfUEFUSFNbImdvb2dsZSJdKSkp"
    "CiAgICBkZWZhdWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIikKICAgIGRlZmF1bHRfdG9rZW4gPSBzdHIo"
    "Z29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIpCiAgICBjcmVkc192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpcCgp"
    "CiAgICB0b2tlbl92YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIpKS5zdHJpcCgpCiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJjb25m"
    "aWciIGluIGNyZWRzX3ZhbCBhbmQgImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdvb2dsZV9jZmdbImNyZWRlbnRp"
    "YWxzIl0gPSBkZWZhdWx0X2NyZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgIGlmIG5vdCB0b2tlbl92YWw6CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9r"
    "ZW4iXSA9IGRlZmF1bHRfdG9rZW4KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKZGVm"
    "IGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBh"
    "dGggb2JqZWN0IHdpdGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZhbHVlID0gcGF0"
    "aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQoa2V5"
    "KQogICAgaWYgZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAgICAgICByZXR1cm4gZmFsbGJhY2sKICAgIHJldHVybiBT"
    "Q1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKUgOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJz"
    "b25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIENfUFJJTUFSWSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJlIGlu"
    "amVjdGVkIGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml2ZWQgZnJvbSB0aG9zZSBp"
    "bmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9ycyB0byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQg"
    "dGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAgIyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0cykKQ19D"
    "UklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFS"
    "WSAgICAgICAgIyBtYWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4OCIgIyBkaW0gc2Vjb25k"
    "YXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBlbXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElN"
    "ICAgICAgICAgIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElNICA9IENfVEVYVF9ESU0gKyAiODgiICAjIGRpbSBzZWNv"
    "bmRhcnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAgICAgICAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQp"
    "CkNfQkcyICAgICAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyAgICAgICAgID0gQ19QQU5FTCAgICAgICAg"
    "ICAgICMgdGVydGlhcnkvaW5wdXQgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAgICAgICAjIGVy"
    "cm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9ICcjODg1NWNjJyAgICAgICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQg"
    "dW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAnIzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcj"
    "NDRhYTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5pdmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZv"
    "IHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZvbnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQgbmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNL"
    "X0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChmb3Ig"
    "ZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAgInNt"
    "dWciOiAgICAgICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZlZCI6ICAgQ19HT0xELAogICAgImhhcHB5IjogICAgICBD"
    "X0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5pY2tlZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04s"
    "CiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAg"
    "ICAic2FkIjogICAgICAgICIjY2M2NjIyIiwKICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAgICAi"
    "cGxvdHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZpb3VzIjogICAgQ19QVVJQTEUsCiAgICAiZm9jdXNl"
    "ZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAgQ19URVhUX0RJTSwKfQoKIyDilIDilIAgREVD"
    "T1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgUlVORVMgaXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMgRmFj"
    "ZSBpbWFnZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRocy5mYWNlcwpGQUNFX0ZJTEVTOiBkaWN0"
    "W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9Q"
    "UkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZB"
    "Q0VfUFJFRklYfV9TbXVnLnBuZyIsCiAgICAiY29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQiOiAgICAgICAg"
    "ZiJ7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGlldmVkLnBuZyIsCiAgICAiaW1w"
    "cmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3RvcnkucG5nIiwK"
    "ICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3Bp"
    "Y2lvdXMucG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJF"
    "RklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAiYW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciLAogICAgInBsb3R0aW5nIjogICBmIntG"
    "QUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAg"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHkucG5nIiwKICAgICJmbHVzdGVy"
    "ZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVudmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpT"
    "RU5USU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmVkLCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQs"
    "ICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNpb3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHks"
    "IGZsaXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBpbmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUg"
    "YXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFscmVhZHkgZGVm"
    "aW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCByZWRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFM"
    "IFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSAClNUWUxFID0gZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6IHtDX0dPTER9"
    "OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250"
    "LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5k"
    "LWNvbG9yOiB7Q19DUklNU09OX0RJTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xE"
    "fTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZB"
    "TUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICBib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hCdXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtD"
    "X0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czog"
    "MnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIHBh"
    "ZGRpbmc6IDhweCAyMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtD"
    "X0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0Nf"
    "QkxPT0R9OwogICAgYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0dG9uOmRpc2FibGVkIHt7CiAgICBi"
    "YWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Ny"
    "b2xsQmFyOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4OwogICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFy"
    "OjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9sbEJh"
    "cjo6aGFuZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6dmVydGljYWws"
    "IFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdldDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0NfQkcyfTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4Owog"
    "ICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFiQmFy"
    "Ojp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206"
    "IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0Nf"
    "R09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsK"
    "ICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6"
    "IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9G"
    "T05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21i"
    "b0JveCB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElN"
    "fTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAg"
    "IGJvcmRlcjogbm9uZTsKfX0KUUNoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0K"
    "UUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7"
    "Q19DUklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBOb25l"
    "OgogICAgIiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxsZWQgb24gc3RhcnR1cCBi"
    "ZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxzbyBtaWdyYXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05h"
    "bWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgogICAgZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBj"
    "ZmdfcGF0aCgic291bmRzIiksCiAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAgY2Zn"
    "X3BhdGgoInNsIiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJiYWNr"
    "dXBzIiksCiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUi"
    "KSAvICJleHBvcnRzIiwKICAgIF0KICAgIGZvciBkIGluIGRpcnM6CiAgICAgICAgZC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAg"
    "IyBDcmVhdGUgZW1wdHkgSlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBleGlzdAogICAgbWVtb3J5X2RpciA9IGNmZ19wYXRoKCJtZW1vcmllcyIpCiAgICBm"
    "b3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29ubCIsICJtZW1vcmllcy5qc29ubCIsICJ0YXNrcy5qc29ubCIsCiAgICAgICAgICAgICAgICAgICJsZXNzb25z"
    "X2xlYXJuZWQuanNvbmwiLCAicGVyc29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAgICAgZnAgPSBtZW1vcnlfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3Qg"
    "ZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGlyID0gY2ZnX3BhdGgoInNsIikK"
    "ICAgIGZvciBmbmFtZSBpbiAoInNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25sIik6CiAgICAgICAgZnAgPSBzbF9kaXIgLyBmbmFtZQogICAg"
    "ICAgIGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAgICAgICAgZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzZXNzaW9uc19kaXIg"
    "PSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgaWR4ID0gc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3Rz"
    "KCk6CiAgICAgICAgaWR4LndyaXRlX3RleHQoanNvbi5kdW1wcyh7InNlc3Npb25zIjogW119LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAg"
    "c3RhdGVfcGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUuanNvbiIKICAgIGlmIG5vdCBzdGF0ZV9wYXRoLmV4aXN0cygpOgogICAgICAgIF93cml0ZV9kZWZh"
    "dWx0X3N0YXRlKHN0YXRlX3BhdGgpCgogICAgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5kZXguanNvbiIKICAgIGlmIG5vdCBpbmRleF9wYXRoLmV4"
    "aXN0cygpOgogICAgICAgIGluZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyh7InZlcnNpb24iOiBBUFBfVkVSU0lPTiwgInRv"
    "dGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMH0sIGluZGVudD0yKSwKICAgICAgICAgICAgZW5j"
    "b2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246IGlmIG9sZCBNb3JnYW5uYV9NZW1vcmllcyBmb2xkZXIgZXhpc3RzLCBt"
    "aWdyYXRlIGZpbGVzCiAgICBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKQoKZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAg"
    "ICBzdGF0ZSA9IHsKICAgICAgICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAg"
    "ICAic2Vzc2lvbl9jb3VudCI6IDAsCiAgICAgICAgImxhc3Rfc3RhcnR1cCI6IE5vbmUsCiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBOb25lLAogICAgICAg"
    "ICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJp"
    "bnRlcm5hbF9uYXJyYXRpdmUiOiB7fSwKICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgIH0KICAgIHBhdGgud3Jp"
    "dGVfdGV4dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkgLT4gTm9u"
    "ZToKICAgICIiIgogICAgSWYgb2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpcyBkZXRlY3RlZCwKICAgIG1pZ3JhdGUg"
    "ZmlsZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIiIgogICAgIyBUcnkgdG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZlIHRvIG1vZGVsIHBh"
    "dGgKICAgIG1vZGVsX3BhdGggPSBQYXRoKENGR1sibW9kZWwiXS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBub3QgbW9kZWxfcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICByZXR1cm4KICAgIG9sZF9yb290ID0gbW9kZWxfcGF0aC5wYXJlbnQgLyBmIntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9yb290"
    "LmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIG1pZ3JhdGlvbnMgPSBbCiAgICAgICAgKG9sZF9yb290IC8gIm1lbW9yaWVzLmpzb25sIiwgICAgICAg"
    "ICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lbW9yaWVzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gIm1lc3NhZ2VzLmpzb25sIiwgICAgICAg"
    "ICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJ0YXNrcy5qc29ubCIsICAgICAgICAg"
    "ICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic3RhdGUuanNvbiIsICAgICAgICAgICAg"
    "ICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInN0YXRlLmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAiaW5kZXguanNvbiIsICAgICAgICAgICAgICAg"
    "IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfc2NhbnMuanNvbmwiLCAgICAgICAgICAgIGNm"
    "Z19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX2NvbW1hbmRzLmpzb25sIiwgICAgICAgICBjZmdfcGF0"
    "aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAgICAgUGF0aChDRkdb"
    "Imdvb2dsZSJdWyJ0b2tlbiJdKSksCiAgICAgICAgKG9sZF9yb290IC8gImNvbmZpZyIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChvbGRf"
    "cm9vdCAvICJzb3VuZHMiIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiksCiAgICBdCgogICAgZm9yIHNyYywgZHN0IGluIG1pZ3Jh"
    "dGlvbnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0LmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBkc3Qu"
    "cGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAgICAgICAgIHNo"
    "dXRpbC5jb3B5MihzdHIoc3JjKSwgc3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyBN"
    "aWdyYXRlIGZhY2UgaW1hZ2VzCiAgICBvbGRfZmFjZXMgPSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNmZ19wYXRoKCJmYWNlcyIpCiAg"
    "ICBpZiBvbGRfZmFjZXMuZXhpc3RzKCk6CiAgICAgICAgZm9yIGltZyBpbiBvbGRfZmFjZXMuZ2xvYigiKi5wbmciKToKICAgICAgICAgICAgZHN0ID0gbmV3"
    "X2ZhY2VzIC8gaW1nLm5hbWUKICAgICAgICAgICAgaWYgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAg"
    "ICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihpbWcpLCBzdHIoZHN0KSkKICAgICAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKIyDilIDilIAgREFURVRJTUUgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGxvY2FsX25vd19pc28oKSAtPiBzdHI6CiAg"
    "ICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKS5pc29mb3JtYXQoKQoKZGVmIHBhcnNlX2lzbyh2YWx1ZTogc3RyKSAtPiBP"
    "cHRpb25hbFtkYXRldGltZV06CiAgICBpZiBub3QgdmFsdWU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZhbHVlID0gdmFsdWUuc3RyaXAoKQogICAgdHJ5"
    "OgogICAgICAgIGlmIHZhbHVlLmVuZHN3aXRoKCJaIik6CiAgICAgICAgICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0pLnJl"
    "cGxhY2UodHppbmZvPXRpbWV6b25lLnV0YykKICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZSkKICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgcmV0dXJuIE5vbmUKCl9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDogc2V0W3R1cGxlXSA9IHNldCgpCgoKZGVmIF9sb2NhbF90"
    "emluZm8oKToKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV0YwoKCmRlZiBub3dfZm9yX2NvbXBh"
    "cmUoKToKICAgIHJldHVybiBkYXRldGltZS5ub3coX2xvY2FsX3R6aW5mbygpKQoKCmRlZiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFs"
    "dWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIGlmIGR0X3ZhbHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGlmIG5vdCBpc2luc3RhbmNl"
    "KGR0X3ZhbHVlLCBkYXRldGltZSk6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGxvY2FsX3R6ID0gX2xvY2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50"
    "emluZm8gaXMgTm9uZToKICAgICAgICBub3JtYWxpemVkID0gZHRfdmFsdWUucmVwbGFjZSh0emluZm89bG9jYWxfdHopCiAgICAgICAga2V5ID0gKCJuYWl2"
    "ZSIsIGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6CiAgICAgICAgICAgIF9lYXJseV9sb2co"
    "CiAgICAgICAgICAgICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBkYXRldGltZSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRl"
    "eHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFk"
    "ZChrZXkpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5hc3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpf"
    "bmFtZSA9IHN0cihkdF92YWx1ZS50emluZm8pCiAgICBrZXkgPSAoImF3YXJlIiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3QgaW4gX0RB"
    "VEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFuZCBkdF90el9uYW1lIG5vdCBpbiB7IlVUQyIsIHN0cihsb2NhbF90eil9OgogICAgICAgIF9lYXJseV9s"
    "b2coCiAgICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZyb20ge2R0X3R6X25hbWV9IHRv"
    "IGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBhcmlzb25zLiIKICAgICAgICApCiAgICAgICAgX0RBVEVUSU1FX05PUk1B"
    "TElaQVRJT05fTE9HR0VELmFkZChrZXkpCiAgICByZXR1cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9pc29fZm9yX2NvbXBhcmUodmFsdWUsIGNvbnRleHQ6"
    "IHN0ciA9ICIiKToKICAgIHJldHVybiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250ZXh0KQoK"
    "CmRlZiBfdGFza19kdWVfc29ydF9rZXkodGFzazogZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoKHRhc2sgb3Ige30pLmdldCgiZHVl"
    "X2F0Iikgb3IgKHRhc2sgb3Ige30pLmdldCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29ydCIpCiAgICBpZiBkdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4g"
    "KDEsIGRhdGV0aW1lLm1heC5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpKQogICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9uZSh0aW1lem9uZS51dGMp"
    "LCAoKHRhc2sgb3Ige30pLmdldCgidGV4dCIpIG9yICIiKS5sb3dlcigpKQoKCmRlZiBmb3JtYXRfZHVyYXRpb24oc2Vjb25kczogZmxvYXQpIC0+IHN0cjoK"
    "ICAgIHRvdGFsID0gbWF4KDAsIGludChzZWNvbmRzKSkKICAgIGRheXMsIHJlbSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3VycywgcmVtID0gZGl2"
    "bW9kKHJlbSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNlY3MgPSBkaXZtb2QocmVtLCA2MCkKICAgIHBhcnRzID0gW10KICAgIGlmIGRheXM6ICAgIHBhcnRzLmFw"
    "cGVuZChmIntkYXlzfWQiKQogICAgaWYgaG91cnM6ICAgcGFydHMuYXBwZW5kKGYie2hvdXJzfWgiKQogICAgaWYgbWludXRlczogcGFydHMuYXBwZW5kKGYi"
    "e21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFwcGVuZChmIntzZWNzfXMiKQogICAgcmV0dXJuICIgIi5qb2luKHBhcnRzWzozXSkKCiMg"
    "4pSA4pSAIE1PT04gUEhBU0UgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNoZXMgbGFiZWxlZCBwaGFzZS4KCl9L"
    "Tk9XTl9ORVdfTU9PTiA9IGRhdGUoMjAwMCwgMSwgNikKX0xVTkFSX0NZQ0xFICAgID0gMjkuNTMwNTg4NjcKCmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1"
    "cGxlW2Zsb2F0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0dXJucyAocGhhc2VfZnJhY3Rpb24sIHBoYXNlX25hbWUsIGlsbHVtaW5hdGlvbl9wY3Qp"
    "LgogICAgcGhhc2VfZnJhY3Rpb246IDAuMCA9IG5ldyBtb29uLCAwLjUgPSBmdWxsIG1vb24sIDEuMCA9IG5ldyBtb29uIGFnYWluLgogICAgaWxsdW1pbmF0"
    "aW9uX3BjdDogMOKAkzEwMCwgY29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBwaGFzZS4KICAgICIiIgogICAgZGF5cyAgPSAoZGF0ZS50b2RheSgpIC0gX0tO"
    "T1dOX05FV19NT09OKS5kYXlzCiAgICBjeWNsZSA9IGRheXMgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUgLyBfTFVOQVJfQ1lDTEUKCiAgICBp"
    "ZiAgIGN5Y2xlIDwgMS44NTogICBuYW1lID0gIk5FVyBNT09OIgogICAgZWxpZiBjeWNsZSA8IDcuMzg6ICAgbmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAg"
    "ICBlbGlmIGN5Y2xlIDwgOS4yMjogICBuYW1lID0gIkZJUlNUIFFVQVJURVIiCiAgICBlbGlmIGN5Y2xlIDwgMTQuNzc6ICBuYW1lID0gIldBWElORyBHSUJC"
    "T1VTIgogICAgZWxpZiBjeWNsZSA8IDE2LjYxOiAgbmFtZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBH"
    "SUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDIzLjk5OiAgbmFtZSA9ICJMQVNUIFFVQVJURVIiCiAgICBlbHNlOiAgICAgICAgICAgICAgICBuYW1lID0gIldB"
    "TklORyBDUkVTQ0VOVCIKCiAgICAjIENvcnJlY3RlZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcGVha3MgYXQgZnVsbCBtb29uCiAgICBpbGx1bWluYXRp"
    "b24gPSAoMSAtIG1hdGguY29zKDIgKiBtYXRoLnBpICogcGhhc2UpKSAvIDIgKiAxMDAKICAgIHJldHVybiBwaGFzZSwgbmFtZSwgcm91bmQoaWxsdW1pbmF0"
    "aW9uLCAxKQoKX1NVTl9DQUNIRV9EQVRFOiBPcHRpb25hbFtkYXRlXSA9IE5vbmUKX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOOiBPcHRpb25hbFtpbnRdID0g"
    "Tm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0dXBsZVtzdHIsIHN0cl0gPSAoIjA2OjAwIiwgIjE4OjMwIikKCmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRl"
    "cygpIC0+IHR1cGxlW2Zsb2F0LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29sdmUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGZyb20gcnVudGltZSBjb25maWcgd2hl"
    "biBhdmFpbGFibGUuCiAgICBGYWxscyBiYWNrIHRvIHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAgIiIiCiAgICBsYXQgPSBOb25lCiAg"
    "ICBsb24gPSBOb25lCiAgICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkg"
    "ZWxzZSB7fQogICAgICAgIGZvciBrZXkgaW4gKCJsYXRpdHVkZSIsICJsYXQiKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAg"
    "ICAgICAgbGF0ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJs"
    "b24iLCAibG5nIik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxvbiA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAg"
    "ICAgICAgICAgICAgICBicmVhawogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBsYXQgPSBOb25lCiAgICAgICAgbG9uID0gTm9uZQoKICAgIG5vd19s"
    "b2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKQog"
    "ICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zmc2V0LnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25lOgogICAgICAgIGxvbiA9"
    "IG1heCgtMTgwLjAsIG1pbigxODAuMCwgdHpfb2Zmc2V0X2hvdXJzICogMTUuMCkpCgogICAgaWYgbGF0IGlzIE5vbmU6CiAgICAgICAgdHpfbmFtZSA9IHN0"
    "cihub3dfbG9jYWwudHppbmZvIG9yICIiKQogICAgICAgIHNvdXRoX2hpbnQgPSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9rZW4gaW4gKCJBdXN0cmFs"
    "aWEiLCAiUGFjaWZpYy9BdWNrbGFuZCIsICJBbWVyaWNhL1NhbnRpYWdvIikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYgc291dGhfaGludCBlbHNlIDM1LjAK"
    "CiAgICBsYXQgPSBtYXgoLTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCBsb24pKQogICAgcmV0dXJuIGxh"
    "dCwgbG9uCgpkZWYgX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyhsb2NhbF9kYXk6IGRhdGUsIGxhdGl0dWRlOiBmbG9hdCwgbG9uZ2l0dWRlOiBmbG9hdCwg"
    "c3VucmlzZTogYm9vbCkgLT4gT3B0aW9uYWxbZmxvYXRdOgogICAgIiIiTk9BQS1zdHlsZSBzdW5yaXNlL3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwg"
    "bWludXRlcyBmcm9tIG1pZG5pZ2h0LiIiIgogICAgbiA9IGxvY2FsX2RheS50aW1ldHVwbGUoKS50bV95ZGF5CiAgICBsbmdfaG91ciA9IGxvbmdpdHVkZSAv"
    "IDE1LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hvdXIpIC8gMjQuMCkgaWYgc3VucmlzZSBlbHNlIG4gKyAoKDE4IC0gbG5nX2hvdXIpIC8gMjQuMCkKCiAg"
    "ICBNID0gKDAuOTg1NiAqIHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKE0pKSkgKyAoMC4wMjAgKiBtYXRo"
    "LnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuNjM0CiAgICBMID0gTCAlIDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3JlZXMobWF0aC5hdGFuKDAu"
    "OTE3NjQgKiBtYXRoLnRhbihtYXRoLnJhZGlhbnMoTCkpKSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAgTF9xdWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5"
    "MC4wKSkgKiA5MC4wCiAgICBSQV9xdWFkcmFudCA9IChtYXRoLmZsb29yKFJBIC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFkcmFudCAt"
    "IFJBX3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2luX2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoTCkpCiAgICBjb3NfZGVjID0gbWF0"
    "aC5jb3MobWF0aC5hc2luKHNpbl9kZWMpKQoKICAgIHplbml0aCA9IDkwLjgzMwogICAgY29zX2ggPSAobWF0aC5jb3MobWF0aC5yYWRpYW5zKHplbml0aCkp"
    "IC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkpIC8gKGNvc19kZWMgKiBtYXRoLmNvcyhtYXRoLnJhZGlhbnMobGF0aXR1"
    "ZGUpKSkKICAgIGlmIGNvc19oIDwgLTEuMCBvciBjb3NfaCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGlmIHN1bnJpc2U6CiAgICAgICAgSCA9"
    "IDM2MC4wIC0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBlbHNlOgogICAgICAgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19o"
    "KSkKICAgIEggLz0gMTUuMAoKICAgIFQgPSBIICsgUkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAgIFVUID0gKFQgLSBsbmdfaG91cikgJSAyNC4wCgog"
    "ICAgbG9jYWxfb2Zmc2V0X2hvdXJzID0gKGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3Nl"
    "Y29uZHMoKSAvIDM2MDAuMAogICAgbG9jYWxfaG91ciA9IChVVCArIGxvY2FsX29mZnNldF9ob3VycykgJSAyNC4wCiAgICByZXR1cm4gbG9jYWxfaG91ciAq"
    "IDYwLjAKCmRlZiBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUobWludXRlc19mcm9tX21pZG5pZ2h0OiBPcHRpb25hbFtmbG9hdF0pIC0+IHN0cjoKICAgIGlm"
    "IG1pbnV0ZXNfZnJvbV9taWRuaWdodCBpcyBOb25lOgogICAgICAgIHJldHVybiAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbnV0ZXNfZnJvbV9t"
    "aWRuaWdodCkpICUgKDI0ICogNjApCiAgICBoaCwgbW0gPSBkaXZtb2QobWlucywgNjApCiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShob3Vy"
    "PWhoLCBtaW51dGU9bW0sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKS5zdHJmdGltZSgiJUg6JU0iKQoKZGVmIGdldF9zdW5fdGltZXMoKSAtPiB0dXBsZVtz"
    "dHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3VucmlzZS9zdW5zZXQgdXNpbmcgc3lzdGVtIGRhdGUgKyB0aW1lem9uZSBhbmQgb3B0aW9u"
    "YWwKICAgIHJ1bnRpbWUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAgQ2FjaGVkIHBlciBsb2NhbCBkYXRlIGFuZCB0aW1l"
    "em9uZSBvZmZzZXQuCiAgICAiIiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0RBVEUsIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNIRV9USU1F"
    "UwoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwuZGF0ZSgpCiAgICB0el9vZmZzZXRf"
    "bWluID0gaW50KChub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNI"
    "RV9EQVRFID09IHRvZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPT0gdHpfb2Zmc2V0X21pbjoKICAgICAgICByZXR1cm4gX1NVTl9DQUNIRV9U"
    "SU1FUwoKICAgIHRyeToKICAgICAgICBsYXQsIGxvbiA9IF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9jYWxj"
    "X3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPVRydWUpCiAgICAgICAgc3Vuc2V0X21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50"
    "X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPUZhbHNlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5vbmUgb3Igc3Vuc2V0X21pbiBpcyBO"
    "b25lOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVudCB1bmF2YWlsYWJsZSBmb3IgcmVzb2x2ZWQgY29vcmRpbmF0ZXMiKQogICAg"
    "ICAgIHRpbWVzID0gKF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5yaXNlX21pbiksIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5zZXRfbWluKSkK"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdGltZXMgPSAoIjA2OjAwIiwgIjE4OjMwIikKCiAgICBfU1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAg"
    "X1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID0gdHpfb2Zmc2V0X21pbgogICAgX1NVTl9DQUNIRV9USU1FUyA9IHRpbWVzCiAgICByZXR1cm4gdGltZXMKCiMg"
    "4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJMRUQ9VHJ1ZS4KIyBJbmpl"
    "Y3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZXZlcnkgZ2VuZXJhdGlvbiBjYWxsLgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAg"
    "ICJXSVRDSElORyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAxLjB9LAogICAgIkRF"
    "RVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lM"
    "SUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5U"
    "IjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVNUTEVTUyBT"
    "TEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAg"
    "ICAgIHsiaG91cnMiOiB7MTYsMTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5FRCI6ICAgICAg"
    "IHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsi"
    "aG91cnMiOiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwKfQoKZGVmIGdldF92YW1waXJlX3N0YXRlKCkg"
    "LT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZhbXBpcmUgc3RhdGUgbmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRhdGV0"
    "aW1lLm5vdygpLmhvdXIKICAgIGZvciBzdGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJo"
    "b3VycyJdOgogICAgICAgICAgICByZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHN0"
    "YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5nZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xEKQoKZGVmIF9uZXV0"
    "cmFsX3N0YXRlX2dyZWV0aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsKICAgICAgICAiV0lUQ0hJTkcgSE9VUiI6ICAgZiJ7REVDS19O"
    "QU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdodCBub3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAgZiJ7REVDS19OQU1FfSBy"
    "ZW1haW5zIGZvY3VzZWQgYW5kIGF2YWlsYWJsZSBmb3IgeW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRXSUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0g"
    "aXMgYXR0ZW50aXZlIGFuZCB3YWl0aW5nIGZvciB5b3VyIG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tfTkFNRX0g"
    "aXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVzcG9uc2l2ZS4iLAogICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBmIntERUNLX05BTUV9"
    "IGlzIGxpZ2h0bHkgaWRsZSBhbmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElSUklORyI6ICAgICAgICBmIntERUNLX05BTUV9"
    "IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGludWUuIiwKICAgICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBm"
    "dWxseSBhY3RpdmUgYW5kIHByZXBhcmVkIHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBpbiBhbiBhY3Rp"
    "dmUgcHJvY2Vzc2luZyB3aW5kb3cgYW5kIHN0YW5kaW5nIGJ5LiIsCiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0"
    "cl06CiAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBpc2luc3RhbmNlKHByb3ZpZGVkLCBkaWN0KSBh"
    "bmQgc2V0KHByb3ZpZGVkLmtleXMoKSkgPT0gc2V0KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBzdHJdID0ge30K"
    "ICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAg"
    "aWYgbm90IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVl"
    "dGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJl"
    "dHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6CiAgICAiIiIKICAgIEJ1aWxkIHRo"
    "ZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBjb250ZXh0IHN0cmluZyBmb3Igc3lzdGVtIHByb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3Jl"
    "IGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3YXlzIGZyZXNoLgogICAgIiIiCiAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAg"
    "ICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3Bo"
    "YXNlKCkKICAgIG5vdyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFw"
    "KCkKICAgIGZsYXZvciA9IHN0YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYiXG5cbltDVVJSRU5UIFNUQVRFIOKA"
    "lCB7bm93fV1cbiIKICAgICAgICBmIlZhbXBpcmUgc3RhdGU6IHtzdGF0ZX0uIHtmbGF2b3J9XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2ls"
    "bHVtfSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVDS19OQU1FfSBpbiB0aGlzIHN0YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRo"
    "ZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIKICAgICkKCiMg4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5lcmF0aW9uLiBHb3RoaWMv"
    "dmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8gZmlsZXMgcmVxdWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2Vz"
    "IFB5dGhvbidzIGJ1aWx0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFjayAoc3VwcG9ydHMgV0FWIGFu"
    "ZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRlZiBfc2luZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGgu"
    "c2luKDIgKiBtYXRoLnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDEuMCBp"
    "ZiBfc2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEuMAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJu"
    "IDIgKiAoKGZyZXEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQsIHNxdWFyZV9yOiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAg"
    "ICAgICBmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNx"
    "dWFyZV9yICogX3NxdWFyZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNhd19yICogX3Nhd3Rvb3RoKGZyZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQs"
    "IHRvdGFsOiBpbnQsCiAgICAgICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM6IGZsb2F0ID0g"
    "MC4zKSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAvIG1heCgxLCB0b3RhbCkKICAgIGlm"
    "IHBvcyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwogICAgZWxpZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAg"
    "ICAgICAgcmV0dXJuICgxIC0gcG9zKSAvIHJlbGVhc2VfZnJhYwogICAgcmV0dXJuIDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDogUGF0aCwgYXVkaW86IGxp"
    "c3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0"
    "cihwYXRoKSwgInciKSBhcyBmOgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUsIDAsICJOT05FIiwgIm5vdCBjb21wcmVzc2VkIikp"
    "CiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAgICAgICAgIGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYgX2NsYW1wKHY6IGZs"
    "b2F0KSAtPiBpbnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyNzY3KSkpCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5kaW5nIG1pbm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg"
    "4oaSIG1pbm9yIHRoaXJkIGJlbG93LiBTbG93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIERlc2NlbmRpbmcg"
    "bWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwgcHVyZSBzaW5lIHdpdGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5n"
    "bGUgcmVzb25hbnQgYmVsbCBkeWluZyBpbiBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgMC42KSwg"
    "ICAjIEE0IOKAlCBmaXJzdCBzdHJpa2UKICAgICAgICAoMzY5Ljk5LCAwLjkpLCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxvdyksIGxv"
    "bmdlciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3RoIGluIG5vdGVzOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1Q"
    "TEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAg"
    "ICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5vIHNxdWFyZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjcK"
    "ICAgICAgICAgICAgIyBBZGQgYSBzdWJ0bGUgaGFybW9uaWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAq"
    "IDAuMTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZlbG9wZSDi"
    "gJQgYmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDEsIHJlbGVhc2VfZnJhYz0w"
    "LjcpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAjIEJyaWVmIHNpbGVuY2UgYmV0d2VlbiBub3Rl"
    "cwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjEpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVf"
    "d2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBh"
    "c2NlbmRpbmcgbWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hvcmQpLCBmaW5hbCBub3RlIGZhZGVzLiBT"
    "w6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0"
    "YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBsaWtlIGEgc8OpYW5jZSBi"
    "ZWdpbm5pbmcuCiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwgbm90ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwog"
    "ICAgICAgICgyMjAuMCwgMC4yNSksICAgIyBBMwogICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhpcmQpCiAgICAgICAgKDMyOS42Mywg"
    "MC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQwLjAsIDAuOCksICAgICMgQTQg4oCUIGZpbmFsLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAg"
    "ICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAg"
    "ICAgICAgaXNfZmluYWwgPSAoaSA9PSBsZW4obm90ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8g"
    "X1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0"
    "KSAqIDAuMgogICAgICAgICAgICBpZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4w"
    "NSwgcmVsZWFzZV9mcmFjPTAuNikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2Zy"
    "YWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQ1KSkKICAgICAgICBpZiBu"
    "b3QgaXNfZmluYWw6CiAgICAgICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAgICBhdWRpby5h"
    "cHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1P"
    "UkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29mdC4gTGlrZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5z"
    "b2xpY2l0ZWQgdHJhbnNtaXNzaW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2Fu"
    "bmFfaWRsZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCUIEQzLiBWZXJ5IHF1aWV0LiBQcmVzZW5jZSBpbiB0"
    "aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMgICMgRDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3Ro"
    "KQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3Np"
    "bmUoZnJlcSwgdCkgKiAwLjUKICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90"
    "YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjc1KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAg"
    "IF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEVSUk9S"
    "IOKAlCB0cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVmLiBTb21ldGhpbmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFs"
    "LgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkg"
    "LT4gTm9uZToKICAgICIiIgogICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHkuCiAgICBUaGUgJ2RpYWJvbHVz"
    "IGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21wYXJlZCB0byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2EgPSAyNDYuOTQgICMg"
    "QjMKICAgIGZyZXFfYiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvdmUgQikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90"
    "YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8g"
    "X1NBTVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlCBjcmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwg"
    "PSAoX3NpbmUoZnJlcV9hLCB0KSAqIDAuNSArCiAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAgIF9zaW5l"
    "KGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9"
    "MC40KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKAlCBkZXNjZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9u"
    "CiMgUmV2ZXJzZSBvZiBzdGFydHVwLiBUaGUgc8OpYW5jZSBlbmRzLiBQcmVzZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiRGVzY2VuZGluZyBB"
    "NCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdpbmcgaW50byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAs"
    "ICAwLjMpLCAgICMgQTQKICAgICAgICAoMzI5LjYzLCAwLjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYzLCAwLjMpLCAgICMgQzQKICAgICAgICAoMjIwLjAs"
    "ICAwLjgpLCAgICMgQTMg4oCUIGZpbmFsLCBsb25nIGZhZGUKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVt"
    "ZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAg"
    "ICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41NQogICAgICAgICAgICB2YWwgKz0g"
    "X3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHJlbGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiAgICAgICAgICAgIGF1ZGlvLmFw"
    "cGVuZChfY2xhbXAodmFsICogZW52ICogMC40KSkKICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAg"
    "ICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBBVEhTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2V0X3NvdW5kX3BhdGgobmFt"
    "ZTogc3RyKSAtPiBQYXRoOgogICAgcmV0dXJuIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIKCmRlZiBib290c3Ry"
    "YXBfc291bmRzKCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNzaW5nIHNvdW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJh"
    "dG9ycyA9IHsKICAgICAgICAiYWxlcnQiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZuIG5hbWUgdW5jaGFuZ2VkCiAgICAg"
    "ICAgInN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwKICAgICAgICAiaWRsZSI6ICAgICBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAg"
    "ICAgICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yLAogICAgICAgICJzaHV0ZG93biI6IGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duLAog"
    "ICAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBpbiBnZW5lcmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAg"
    "ICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVyYXRlIHtuYW1lfToge2V9IikKCmRl"
    "ZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4gTm9uZToKICAgICIiIgogICAgUGxheSBhIG5hbWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5"
    "Z2FtZS5taXhlciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAgICBGYWxscyBiYWNrIHRvIHdpbnNvdW5kIG9uIFdpbmRvd3MuCiAgICBG"
    "YWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvbi5iZWVwKCkgYXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJz"
    "b3VuZF9lbmFibGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0"
    "cygpOgogICAgICAgIHJldHVybgoKICAgIGlmIFBZR0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1lLm1peGVyLlNvdW5k"
    "KHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgIHBhc3MKCiAgICBpZiBXSU5TT1VORF9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChzdHIocGF0aCksCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3VuZC5TTkRfRklMRU5BTUUgfCB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFwcGxpY2F0aW9uLmJlZXAoKQogICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKUgOKUgCBERVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBjcmVhdGVfZGVza3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIKICAgIENyZWF0ZSBh"
    "IGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhlIGRlY2sgLnB5IGZpbGUgdXNpbmcgcHl0aG9udy5leGUuCiAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2lu"
    "ZG93cyBvbmx5LgogICAgIiIiCiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAgICAgZGVza3RvcCA9IFBh"
    "dGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRjdXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKCiAgICAgICAgIyBweXRo"
    "b253ID0gc2FtZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAg"
    "aWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5l"
    "eGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6CiAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBk"
    "ZWNrX3BhdGggPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0Y2goIldTY3JpcHQuU2hl"
    "bGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBhdGggICAgID0gc3Ry"
    "KHB5dGhvbncpCiAgICAgICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeSA9IHN0cihk"
    "ZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2NyaXB0aW9uICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBu"
    "ZXV0cmFsIGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0aCgiZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9O"
    "ZXV0cmFsLnBuZyIKICAgICAgICBpZiBpY29uX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNlIFBORyBk"
    "aXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFzcwoKICAgICAgICBzYy5zYXZlKCkKICAgICAgICByZXR1cm4gVHJ1ZQog"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0i"
    "KQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwgVVRJTElUSUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3RdOgog"
    "ICAgIiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09OIGFycmF5cyB0b28uIiIiCiAgICBpZiBub3QgcGF0"
    "aC5leGlzdHMoKToKICAgICAgICByZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlwKCkKICAgIGlmIG5v"
    "dCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3RhcnRzd2l0aCgiWyIpOgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0YSA9IGpzb24u"
    "bG9hZHMocmF3KQogICAgICAgICAgICByZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNlKHgsIGRpY3QpXQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIGl0ZW1zID0gW10KICAgIGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGluZSA9IGxp"
    "bmUuc3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToKICAgICAgICAgICAgb2JqID0ganNvbi5s"
    "b2FkcyhsaW5lKQogICAgICAgICAgICBpZiBpc2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQob2JqKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZXR1cm4gaXRlbXMKCmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2Jq"
    "OiBkaWN0KSAtPiBOb25lOgogICAgIiIiQXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNv"
    "bi5kdW1wcyhvYmosIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgsIHJlY29yZHM6IGxpc3RbZGljdF0p"
    "IC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09OTCBmaWxlIHdpdGggYSBsaXN0IG9mIHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIHIg"
    "aW4gcmVjb3JkczoKICAgICAgICAgICAgZi53cml0ZShqc29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZV09S"
    "RCAvIE1FTU9SWSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApfU1RPUFdPUkRT"
    "ID0gewogICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRoaXMiLCJmcm9tIiwieW91ciIsIndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIs"
    "IndoaWNoIiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwidGhlbiIsImludG8iLCJqdXN0IiwKICAgICJhYm91dCIsImxpa2UiLCJiZWNhdXNlIiwi"
    "d2hpbGUiLCJjb3VsZCIsInNob3VsZCIsInRoZWlyIiwid2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNh"
    "bnQiLCJ3b250Iiwib250byIsIm92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIsImFsc28iLCJzb21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndh"
    "bnQiLCJ3aWxsIiwic2hhbGwiLAogICAgImFnYWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIsInVzZWQiLCJ1c2luZyIsInNhaWQi"
    "LAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhpbmciLCJzdHVmZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFj"
    "dF9rZXl3b3Jkcyh0ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtzdHJdOgogICAgdG9rZW5zID0gW3QubG93ZXIoKS5zdHJpcCgiIC4sIT87"
    "OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc3BsaXQoKV0KICAgIHNlZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAg"
    "ICAgIGlmIGxlbih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIHQgbm90"
    "IGluIHNlZW46CiAgICAgICAgICAgIHNlZW4uYWRkKHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4ocmVzdWx0KSA+PSBs"
    "aW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50"
    "X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICB0ID0gKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigpCiAgICBpZiAiZHJlYW0i"
    "IGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiAiZHJlYW0iCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9u"
    "Iiwic2NyaXB0IiwiY29kZSIsImVycm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhlZCIsInJlc29sdmVkIiwic29s"
    "dXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICByZXR1cm4gInJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAgIGlmIGFueSh4IGlu"
    "IHQgZm9yIHggaW4gKCJyZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICByZXR1cm4gInRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZv"
    "ciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0IGlmIiwiZ2FtZSIsInByb2plY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAgaWYgYW55KHgg"
    "aW4gdCBmb3IgeCBpbiAoInByZWZlciIsImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtlIiwiaSB3YW50IikpOgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIK"
    "ICAgIHJldHVybiAiY29udmVyc2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5leHQ6IFBhc3MgMiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1"
    "Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdpZGdldCwgRW1vdGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVTdGF0ZVN0cmlwLCBDb2xs"
    "YXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVD"
    "SyDigJQgUEFTUyAyOiBXSURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRvIGZvcm0gdGhlIGZ1bGwgZGVjay4KIwojIFdp"
    "ZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQgICAgICAgICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUK"
    "IyAgIERyaXZlV2lkZ2V0ICAgICAgICAgIOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0IpCiMgICBTcGhlcmVXaWRnZXQgICAgICAgICDigJQg"
    "ZmlsbGVkIGNpcmNsZSBmb3IgQkxPT0QgYW5kIE1BTkEKIyAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlIHNo"
    "YWRvdwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBjaGlwcwojICAgTWlycm9yV2lkZ2V0ICAgICAg"
    "ICAg4oCUIGZhY2UgaW1hZ2UgZGlzcGxheSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAgIOKAlCBmdWxsLXdpZHRoIHRpbWUvbW9vbi9z"
    "dGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDigJQgd3JhcHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRn"
    "ZXQKIyAgIEhhcmR3YXJlUGFuZWwgICAgICAgIOKAlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBHYXVnZVdpZGdldChRV2lkZ2V0KToKICAg"
    "ICIiIgogICAgSG9yaXpvbnRhbCBmaWxsLWJhciBnYXVnZSB3aXRoIGdvdGhpYyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCksIHZhbHVl"
    "IHRleHQgKHRvcC1yaWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg4oaSIENfQ1JJTVNPTiDihpIgQ19CTE9PRCBh"
    "cyB2YWx1ZSBhcHByb2FjaGVzIG1heC4KICAgIFNob3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5pdDogc3RyID0gIiIsCiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAu"
    "MCwKICAgICAgICBjb2xvcjogc3RyID0gQ19HT0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYudW5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92"
    "YWwKICAgICAgICBzZWxmLmNvbG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0Ei"
    "CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhp"
    "bXVtSGVpZ2h0KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxvYXQsIGRpc3BsYXk6IHN0ciA9ICIiLCBhdmFpbGFibGU6IGJvb2wgPSBU"
    "cnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3ZhbHVlICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFp"
    "bGFibGUgPSBhdmFpbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBlbGlm"
    "IGRpc3BsYXk6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9IGYi"
    "e3ZhbHVlOi4wZn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHNldFVuYXZhaWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLl9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYg"
    "cGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50"
    "ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91"
    "bmQKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAg"
    "ICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJlbAogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAg"
    "ICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5kcmF3VGV4dCg2LCAxNCwgc2VsZi5sYWJl"
    "bCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0p"
    "KQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2LCAxNCwgc2VsZi5f"
    "ZGlzcGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAgICAgICAgYmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAt"
    "IDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9S"
    "REVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBz"
    "ZWxmLm1heF92YWwgPiAwOgogICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEs"
    "IGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAgICAjIENvbG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENf"
    "QkxPT0QgaWYgZnJhYyA+IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIGZyYWMgPiAwLjY1IGVsc2UKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAgICAgICAgIGdyYWQgPSBRTGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmlsbF93LCBi"
    "YXJfeSArIDEpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5z"
    "ZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAtIDIsIGdy"
    "YWQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBEUklWRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0IsIGZpbGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBt"
    "b3VudGVkIGRyaXZlcyB2aWEgcHN1dGlsLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodCgzMCkKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kcml2ZXMgPSBbXQogICAgICAgIGlm"
    "IG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0"
    "aW9ucyhhbGw9RmFsc2UpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdlID0gcHN1dGlsLmRpc2tfdXNhZ2UocGFydC5t"
    "b3VudHBvaW50KQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjogcGFy"
    "dC5kZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidXNlZCI6ICAgdXNhZ2UudXNlZCAgLyAxMDI0Kioz"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAidG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAicGN0Ijog"
    "ICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAgIH0pCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgICMgUmVzaXplIHRvIGZpdCBh"
    "bGwgZHJpdmVzCiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2VsZi5fZHJpdmVzKSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkK"
    "ICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYp"
    "CiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNl"
    "bGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6CiAg"
    "ICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSkpCiAgICAgICAg"
    "ICAgIHAuZHJhd1RleHQoNiwgMTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2YWlsYWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgcmV0dXJu"
    "CgogICAgICAgIHJvd19oID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBsZXR0ZXIgPSBk"
    "cnZbImxldHRlciJdCiAgICAgICAgICAgIHVzZWQgICA9IGRydlsidXNlZCJdCiAgICAgICAgICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogICAgICAgICAg"
    "ICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAgICAgICAgIGxhYmVsID0gZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90"
    "YWw6LjBmfUdCIgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwg"
    "UUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkgKyAxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAg"
    "ICBiYXJfeCA9IDYKICAgICAgICAgICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICAgICAgYmFyX2ggPSA4CiAg"
    "ICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xvcihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9y"
    "KENfQk9SREVSKSkKICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAgICAgICAgICAgZmlsbF93"
    "ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBjdCkpCiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0dPTERfRElNKQogICAg"
    "ICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAgICAgICAgZ3JhZC5z"
    "ZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xv"
    "cikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICAgICAgeSAr"
    "PSByb3dfaAoKICAgICAgICBwLmVuZCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1"
    "cGRhdGUgZHJpdmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgoKIyDilIDilIAgU1BIRVJFIFdJREdFVCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lk"
    "Z2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9vbCkgYW5kIE1BTkEgKFZS"
    "QU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEdsYXNzeSBzaGluZSBlZmZlY3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KAogICAgICAgIHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiAgICAgICAgY29sb3JfZW1wdHk6IHN0ciwKICAg"
    "ICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgICAgID0gbGFiZWwK"
    "ICAgICAgICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3JfZW1wdHkgPSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYu"
    "X2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpIgMS4wCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNldE1pbmltdW1T"
    "aXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2VsZiwgZnJhY3Rpb246IGZsb2F0LCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX2ZpbGwgICAgICA9IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGUKICAg"
    "ICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAg"
    "ICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYu"
    "aGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIwKSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIwKSAv"
    "LyAyICsgNAoKICAgICAgICAjIERyb3Agc2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29s"
    "b3IoMCwgMCwgMCwgODApKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIEJh"
    "c2UgY2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBwLnNldFBlbihRQ29s"
    "b3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBGaWxsIGZyb20gYm90"
    "dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5kIHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGggPSBRUGFpbnRlclBh"
    "dGgoKQogICAgICAgICAgICBjaXJjbGVfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYuX2ZpbGwg"
    "KiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgUVJlY3RGCiAgICAgICAgICAgIGZpbGxfcmVjdCA9IFFSZWN0RihjeCAt"
    "IHIsIGZpbGxfdG9wX3ksIHIgKiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAg"
    "ICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAgICAgIGNsaXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgp"
    "CgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkK"
    "ICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkKQoKICAgICAgICAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAog"
    "ICAgICAgICAgICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICogMC42KQogICAgICAgICkKICAgICAgICBzaGlu"
    "ZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjU1LCA1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUsIDI1"
    "NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNo"
    "KQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIs"
    "IHIgKiAyLCByICogMikKCiAgICAgICAgIyBOL0Egb3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIHAuc2V0UGVu"
    "KFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KCJDb3VyaWVyIE5ldyIsIDgpKQogICAgICAgICAgICBmbSA9IHAuZm9u"
    "dE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAv"
    "LyAyLCBjeSArIDQsIHR4dCkKCiAgICAgICAgIyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJlbF90ZXh0ID0gKHNlbGYubGFiZWwgaWYgc2VsZi5f"
    "YXZhaWxhYmxlIGVsc2UKICAgICAgICAgICAgICAgICAgICAgIGYie3NlbGYubGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9maWxs"
    "ICogMTAwKX0lIiBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICBw"
    "LnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBsdyAvLyAyLCBoIC0gMTAsIGxhYmVsX3RleHQpCgog"
    "ICAgICAgIGlmIHBjdF90ZXh0OgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChE"
    "RUNLX0ZPTlQsIDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0"
    "X3RleHQpCiAgICAgICAgICAgIHAuZHJhd1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBN"
    "T09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1"
    "cmF0ZSBzaGFkb3cuCgogICAgUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwgc3RhbmRhcmQpOgogICAgICAtIFdheGluZyAobmV34oaS"
    "ZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUsIHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxsdW1pbmF0ZWQgbGVm"
    "dCBzaWRlLCBzaGFkb3cgb24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4gYmUgZmxpcHBlZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBi"
    "YWNrd2FyZHMKICAgIG9uIHRoaXMgbWFjaGluZS4gU2V0IE1PT05fU0hBRE9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAgICIiIgoKICAgICMg4oaQ"
    "IEZMSVAgVEhJUyB0byBUcnVlIGlmIG1vb24gYXBwZWFycyBiYWNrd2FyZHMgZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBG"
    "YWxzZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5f"
    "cGhhc2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgICAgICAgID0gIk5FVyBNT09OIgog"
    "ICAgICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxmLl9zdW5yaXNlICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2Vs"
    "Zi5fc3Vuc2V0ICAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICAgICA9IE5vbmUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgw"
    "LCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFzZSgpICAgICAgICAgICMgcG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNl"
    "bGYuX2ZldGNoX3N1bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2ZldGNoKCk6CiAgICAg"
    "ICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9"
    "IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxl"
    "IHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1lciDigJQgbmV2ZXIgY2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0bHkgZnJv"
    "bSBhIGJhY2tncm91bmQgdGhyZWFkCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJl"
    "YWQodGFyZ2V0PV9mZXRjaCwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9w"
    "aGFzZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0"
    "aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQog"
    "ICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikK"
    "ICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2Vs"
    "Zi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMzYp"
    "IC8vIDIgKyA0CgogICAgICAgICMgQmFja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIwLCAxMiwgMjgpKQogICAg"
    "ICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCBy"
    "ICogMikKCiAgICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2UgKiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193YXhpbmcgPSBjeWNsZV9kYXkgPCAoX0xV"
    "TkFSX0NZQ0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1vb24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9yKQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlv"
    "biA+IDE6CiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIxMCwgMTg1"
    "KSkKICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFNoYWRvdyBjYWxjdWxhdGlvbgog"
    "ICAgICAgICMgaWxsdW1pbmF0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2FuaW5nCiAgICAgICAgIyBzaGFkb3dfb2Zmc2V0IGNvbnRyb2xz"
    "IGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5OToKICAgICAgICAgICAg"
    "IyBmcmFjdGlvbiBvZiBkaWFtZXRlciB0aGUgc2hhZG93IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVtX2ZyYWMgID0gc2VsZi5faWxsdW1p"
    "bmF0aW9uIC8gMTAwLjAKICAgICAgICAgICAgc2hhZG93X2ZyYWMgPSAxLjAgLSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0"
    "ZWQgcmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAgICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cgUklHSFQKICAgICAgICAgICAgIyBv"
    "ZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxpcHNlIGhvcml6b250YWxseQogICAgICAgICAgICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikK"
    "CiAgICAgICAgICAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAgICAgICAgICAgICAgIGlzX3dheGluZyA9IG5vdCBpc193YXhpbmcKCiAg"
    "ICAgICAgICAgIGlmIGlzX3dheGluZzoKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBj"
    "eCAtIHIgLSBvZmZzZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIHJpZ2h0IHNpZGUKICAgICAgICAgICAgICAgIHNo"
    "YWRvd194ID0gY3ggLSByICsgb2Zmc2V0CgogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQogICAgICAgICAgICBwLnNldFBlbihR"
    "dC5QZW5TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xpcHBlZCB0byBtb29uIGNpcmNsZQogICAgICAgICAg"
    "ICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBtb29uX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIp"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0g"
    "UVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxsaXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBjbGlwcGVkX3NoYWRvdyA9IG1vb25f"
    "cGF0aC5pbnRlcnNlY3RlZChzaGFkb3dfcGF0aCkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkX3NoYWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3Vy"
    "ZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQgdGV4dHVyZSBncmFkaWVudCkKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChm"
    "bG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChjeSAtIHIgKiAwLjIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgpKQog"
    "ICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigy"
    "MDAsIDE4MCwgMTQwLCA1KSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAu"
    "ZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0"
    "eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kg"
    "LSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgUGhhc2UgbmFtZSBiZWxvdyBtb29uCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAg"
    "ICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAg"
    "ICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX25hbWUpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIG53IC8vIDIsIGN5ICsgciArIDE0LCBzZWxm"
    "Ll9uYW1lKQoKICAgICAgICAjIElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxsdW1fc3RyID0gZiJ7c2VsZi5faWxsdW1pbmF0aW9uOi4wZn0l"
    "IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTIg"
    "PSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBpdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGl3"
    "IC8vIDIsIGN5ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3VuIHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9IGYi4piA"
    "IHtzZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9zdW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICBwLnNldEZv"
    "bnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShz"
    "dW5fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwgc3VuX3N0cikKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIEVNT1RJ"
    "T04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IHBhbmVsLgog"
    "ICAgU2hvd3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5leHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRn"
    "ZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29sbGFwc2VzIHRvIGp1c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBs"
    "ZVtzdHIsIHN0cl1dID0gW10gICMgKGVtb3Rpb24sIHRpbWVzdGFtcCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxmLl9tYXhf"
    "ZW50cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAw"
    "LCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyIHJvdwogICAgICAgIGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAg"
    "IGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpCiAg"
    "ICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFiZWwoIuKd"
    "pyBFTU9USU9OQUwgUkVDT1JEIikKICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTog"
    "OXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAx"
    "cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xl"
    "X2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rv"
    "Z2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhs"
    "LmFkZFdpZGdldChsYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCgogICAgICAgICMg"
    "U2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNl"
    "dFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KAogICAgICAgICAgICBRdC5T"
    "Y3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAg"
    "IHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "aGVhZGVyKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xsKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aCgxMzApCgogICAgZGVm"
    "IF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX3Njcm9sbC5z"
    "ZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLi"
    "lrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKICAgIGRlZiBhZGRFbW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBzdHIg"
    "PSAiIikgLT4gTm9uZToKICAgICAgICBpZiBub3QgdGltZXN0YW1wOgogICAgICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgi"
    "JUg6JU0iKQogICAgICAgIHNlbGYuX2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3RvcnkgPSBzZWxm"
    "Ll9oaXN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10KICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYgX3JlYnVpbGRfY2hpcHMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChrZWVwIHRoZSBzdHJldGNoIGF0IGVuZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlw"
    "X2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NoaXBfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndp"
    "ZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0"
    "b3J5OgogICAgICAgICAgICBjb2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RFWFRfRElNKQogICAgICAgICAgICBjaGlwID0gUUxhYmVs"
    "KGYi4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7dHN9IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjog"
    "e2NvbG9yfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4OyBib3JkZXItcmFkaXVz"
    "OiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2No"
    "aXBfbGF5b3V0LmNvdW50KCkgLSAxLCBjaGlwCiAgICAgICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9oaXN0"
    "b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJST1IgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNaXJyb3JXaWRnZXQo"
    "UUxhYmVsKToKICAgICIiIgogICAgRmFjZSBpbWFnZSBkaXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxseSBsb2FkcyBhbGwge0ZBQ0Vf"
    "UFJFRklYfV8qLnBuZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4KICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToKICAgICAg"
    "ICB7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIOKGkiAic2FkIgog"
    "ICAgICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAgICBGYWxscyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290"
    "aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdlcyBmb3VuZC4KICAgIE1pc3NpbmcgZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIOKAlCBubyBjcmFzaCwgbm8g"
    "aGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQuCiAgICAiIiIKCiAgICAjIFNwZWNpYWwgc3RlbSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBz"
    "dGVtIGFmdGVyIE1vcmdhbm5hXykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRpY3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRfY3J5aW5nIjogICJzYWQi"
    "LAogICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAg"
    "c3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgICAgIHNlbGYuX2NhY2hl"
    "OiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGYuX2N1cnJlbnQgICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRb"
    "c3RyXSA9IHNldCgpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAgICAgc2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgICAgIFFUaW1lci5z"
    "aW5nbGVTaG90KDMwMCwgc2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3ByZWxvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTY2FuIEZh"
    "Y2VzLyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVzLgogICAgICAgIEJ1aWxkIGVtb3Rpb27ihpJwaXhtYXAgY2FjaGUgZHlu"
    "YW1pY2FsbHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIGxpc3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIi"
    "IgogICAgICAgIGlmIG5vdCBzZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXRoIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIpOgogICAgICAgICAg"
    "ICAjIHN0ZW0gPSBldmVyeXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwogICAgICAgICAgICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1b"
    "bGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAgICMgZS5nLiAiU2FkX0NyeWluZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJhd19zdGVtLmxvd2VyKCkg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICMgInNhZF9jcnlpbmciCgogICAgICAgICAgICAjIE1hcCBzcGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwog"
    "ICAgICAgICAgICBlbW90aW9uID0gc2VsZi5fU1RFTV9UT19FTU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAgcHggPSBR"
    "UGl4bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAgICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAgICAgICAgICAgIHNlbGYuX2NhY2hlW2Vtb3Rpb25d"
    "ID0gcHgKCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIGZhY2UgPSBmYWNl"
    "Lmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl93YXJu"
    "ZWQgYW5kIGZhY2UgIT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZToge2ZhY2V9"
    "IOKAlCB1c2luZyBuZXV0cmFsIikKICAgICAgICAgICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAgICAgZmFjZSA9ICJuZXV0cmFsIgog"
    "ICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZhY2UKICAgICAgICBweCA9IHNlbGYuX2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVkID0gcHguc2NhbGVkKAog"
    "ICAgICAgICAgICBzZWxmLndpZHRoKCkgLSA0LAogICAgICAgICAgICBzZWxmLmhlaWdodCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2Rl"
    "LktlZXBBc3BlY3RSYXRpbywKICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAogICAgICAgICkKICAgICAg"
    "ICBzZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRUZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhvbGRlcihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadcbuKcpiIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogMjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgZGVmIHNldF9mYWNlKHNlbGYs"
    "IGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBkZWYgcmVz"
    "aXplRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkKICAgICAgICBpZiBzZWxmLl9jYWNoZToK"
    "ICAgICAgICAgICAgc2VsZi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoK"
    "ICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEN5Y2xlV2lkZ2V0KE1vb25XaWRnZXQpOgogICAgIiIiR2VuZXJp"
    "YyBjeWNsZSB2aXN1YWxpemF0aW9uIHdpZGdldCAoY3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xhc3MgVmFtcGlyZVN0YXRlU3RyaXAo"
    "UVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1N"
    "ICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJsZSwgbmV2ZXIgY29sbGFw"
    "c2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFsIFFUaW1lciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1"
    "cnJlbnQgdmFtcGlyZSBzdGF0ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRl"
    "KCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAg"
    "PSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgID0gTm9uZQogICAgICAgIHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAgICAgICBzZWxm"
    "Ll9pbGx1bSAgICAgPSAwLjAKICAgICAgICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAg"
    "IHNlbGYucmVmcmVzaCgpCgogICAgZGVmIHNldF9sYWJlbChzZWxmLCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9"
    "IChsYWJlbCBvciAiU1RBVEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBkZWYgX2YoKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2Ug"
    "PSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0gc3MKICAgICAgICAgICAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25l"
    "KCkuZGF0ZSgpCiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUoKSBmcm9tCiAgICAg"
    "ICAgICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwgaXQgY2F1c2VzIFFUaHJlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZiwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAg"
    "PSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuc3RyZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5k"
    "YXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBfLCBz"
    "ZWxmLl9tb29uX25hbWUsIHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChz"
    "ZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGlu"
    "dC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgs"
    "IFFDb2xvcihDX0JHMikpCgogICAgICAgIHN0YXRlX2NvbG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9"
    "ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgog"
    "ICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9u"
    "YW1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJv"
    "bGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmhv"
    "cml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNs"
    "YXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250ZW50"
    "c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1"
    "c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQu"
    "QWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAg"
    "YnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQog"
    "ICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAg"
    "IGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9"
    "IFFDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVy"
    "dGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNh"
    "bGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tj"
    "b2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tncm91bmQ6e0Nf"
    "QkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9u"
    "LWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRl"
    "bVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAgKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAg"
    "ICAgc2VsZi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5u"
    "ZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJl"
    "bnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVfbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5"
    "X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQog"
    "ICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9u"
    "dGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgog"
    "ICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1"
    "cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5z"
    "ZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQo"
    "UXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVz"
    "ZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdl"
    "ZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1h"
    "dChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBz"
    "ZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFu"
    "Z2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZt"
    "dCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5"
    "T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgICAgICBl"
    "bGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09E"
    "KSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxm"
    "LmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICB0b2RheV9m"
    "bXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAg"
    "ICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFE"
    "YXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAgICIi"
    "IgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5"
    "IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24g"
    "b24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVX"
    "aWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGxhYmVsOiBzdHIsIGNv"
    "bnRlbnQ6IFFXaWRnZXQsCiAgICAgICAgICAgICAgICAgZXhwYW5kZWQ6IGJvb2wgPSBUcnVlLCBtaW5fd2lkdGg6IGludCA9IDkwLAogICAgICAgICAgICAg"
    "ICAgIHJlc2VydmVfd2lkdGg6IGJvb2wgPSBGYWxzZSwKICAgICAgICAgICAgICAgICBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAgICAgPSBleHBhbmRlZAogICAgICAgIHNlbGYuX21pbl93aWR0aCAgICAgID0gbWluX3dpZHRoCiAg"
    "ICAgICAgc2VsZi5fcmVzZXJ2ZV93aWR0aCAgPSByZXNlcnZlX3dpZHRoCiAgICAgICAgc2VsZi5fY29udGVudCAgICAgICAgPSBjb250ZW50CgogICAgICAg"
    "IG1haW4gPSBRVkJveExheW91dChzZWxmKQogICAgICAgIG1haW4uc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbWFpbi5zZXRTcGFj"
    "aW5nKDApCgogICAgICAgICMgSGVhZGVyCiAgICAgICAgc2VsZi5faGVhZGVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldEZpeGVkSGVp"
    "Z2h0KDIyKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0"
    "b206IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAg"
    "ICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChzZWxmLl9oZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAg"
    "ICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLl9sYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgc2VsZi5fbGJsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fYnRu"
    "ID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX2J0bi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsi"
    "CiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBzZWxmLl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkK"
    "CiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2xibCkKICAgICAgICBobC5hZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fYnRuKQoK"
    "ICAgICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9oZWFkZXIpCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICAgICAgc2VsZi5f"
    "YXBwbHlfc3RhdGUoKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQK"
    "ICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIF9hcHBseV9zdGF0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0"
    "VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAiPiIpCgogICAgICAg"
    "ICMgUmVzZXJ2ZSBmaXhlZCBzbG90IHdpZHRoIHdoZW4gcmVxdWVzdGVkICh1c2VkIGJ5IG1pZGRsZSBsb3dlciBibG9jaykKICAgICAgICBpZiBzZWxmLl9y"
    "ZXNlcnZlX3dpZHRoOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11"
    "bVdpZHRoKDE2Nzc3MjE1KQogICAgICAgIGVsaWYgc2VsZi5fZXhwYW5kZWQ6CiAgICAgICAgICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKHNlbGYuX21pbl93"
    "aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lkdGgoMTY3NzcyMTUpICAjIHVuY29uc3RyYWluZWQKICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAjIENvbGxhcHNlZDoganVzdCB0aGUgaGVhZGVyIHN0cmlwIChsYWJlbCArIGJ1dHRvbikKICAgICAgICAgICAgY29sbGFwc2VkX3cgPSBzZWxmLl9oZWFk"
    "ZXIuc2l6ZUhpbnQoKS53aWR0aCgpCiAgICAgICAgICAgIHNlbGYuc2V0Rml4ZWRXaWR0aChtYXgoNjAsIGNvbGxhcHNlZF93KSkKCiAgICAgICAgc2VsZi51"
    "cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcGFyZW50ID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHBhcmVudCBhbmQgcGFyZW50LmxheW91dCgp"
    "OgogICAgICAgICAgICBwYXJlbnQubGF5b3V0KCkuYWN0aXZhdGUoKQoKCiMg4pSA4pSAIEhBUkRXQVJFIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBIYXJkd2FyZVBhbmVsKFFX"
    "aWRnZXQpOgogICAgIiIiCiAgICBUaGUgc3lzdGVtcyByaWdodCBwYW5lbCBjb250ZW50cy4KICAgIEdyb3Vwczogc3RhdHVzIGluZm8sIGRyaXZlIGJhcnMs"
    "IENQVS9SQU0gZ2F1Z2VzLCBHUFUvVlJBTSBnYXVnZXMsIEdQVSB0ZW1wLgogICAgUmVwb3J0cyBoYXJkd2FyZSBhdmFpbGFiaWxpdHkgaW4gRGlhZ25vc3Rp"
    "Y3Mgb24gc3RhcnR1cC4KICAgIFNob3dzIE4vQSBncmFjZWZ1bGx5IHdoZW4gZGF0YSB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYu"
    "X2RldGVjdF9oYXJkd2FyZSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAg"
    "ICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGRlZiBzZWN0"
    "aW9uX2xhYmVsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVy"
    "biBsYmwKCiAgICAgICAgIyDilIDilIAgU3RhdHVzIGJsb2NrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFNUQVRVUyIpKQogICAgICAgIHN0YXR1c19mcmFtZSA9IFFGcmFtZSgpCiAgICAgICAg"
    "c3RhdHVzX2ZyYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfUEFORUx9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0Rml4ZWRIZWlnaHQoODgpCiAgICAgICAgc2YgPSBR"
    "VkJveExheW91dChzdGF0dXNfZnJhbWUpCiAgICAgICAgc2Yuc2V0Q29udGVudHNNYXJnaW5zKDgsIDQsIDgsIDQpCiAgICAgICAgc2Yuc2V0U3BhY2luZygy"
    "KQoKICAgICAgICBzZWxmLmxibF9zdGF0dXMgID0gUUxhYmVsKCLinKYgU1RBVFVTOiBPRkZMSU5FIikKICAgICAgICBzZWxmLmxibF9tb2RlbCAgID0gUUxh"
    "YmVsKCLinKYgVkVTU0VMOiBMT0FESU5HLi4uIikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uID0gUUxhYmVsKCLinKYgU0VTU0lPTjogMDA6MDA6MDAiKQog"
    "ICAgICAgIHNlbGYubGJsX3Rva2VucyAgPSBRTGFiZWwoIuKcpiBUT0tFTlM6IDAiKQoKICAgICAgICBmb3IgbGJsIGluIChzZWxmLmxibF9zdGF0dXMsIHNl"
    "bGYubGJsX21vZGVsLAogICAgICAgICAgICAgICAgICAgIHNlbGYubGJsX3Nlc3Npb24sIHNlbGYubGJsX3Rva2Vucyk6CiAgICAgICAgICAgIGxibC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgYm9yZGVyOiBub25lOyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZi5hZGRXaWRnZXQobGJsKQoK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHN0YXR1c19mcmFtZSkKCiAgICAgICAgIyDilIDilIAgRHJpdmUgYmFycyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVE9SQUdFIikpCiAg"
    "ICAgICAgc2VsZi5kcml2ZV93aWRnZXQgPSBEcml2ZVdpZGdldCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmRyaXZlX3dpZGdldCkKCiAgICAg"
    "ICAgIyDilIDilIAgQ1BVIC8gUkFNIGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlY3Rpb25fbGFiZWwoIuKdpyBWSVRBTCBFU1NFTkNFIikpCiAgICAgICAgcmFtX2NwdSA9IFFHcmlkTGF5b3V0KCkKICAgICAgICByYW1fY3B1LnNldFNw"
    "YWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9jcHUgID0gR2F1Z2VXaWRnZXQoIkNQVSIsICAiJSIsICAgMTAwLjAsIENfU0lMVkVSKQogICAgICAgIHNl"
    "bGYuZ2F1Z2VfcmFtICA9IEdhdWdlV2lkZ2V0KCJSQU0iLCAgIkdCIiwgICA2NC4wLCBDX0dPTERfRElNKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNl"
    "bGYuZ2F1Z2VfY3B1LCAwLCAwKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfcmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlv"
    "dXQocmFtX2NwdSkKCiAgICAgICAgIyDilIDilIAgR1BVIC8gVlJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgQVJDQU5FIFBPV0VSIikpCiAgICAgICAgZ3B1X3ZyYW0gPSBRR3JpZExheW91dCgpCiAgICAg"
    "ICAgZ3B1X3ZyYW0uc2V0U3BhY2luZygzKQoKICAgICAgICBzZWxmLmdhdWdlX2dwdSAgPSBHYXVnZVdpZGdldCgiR1BVIiwgICIlIiwgICAxMDAuMCwgQ19Q"
    "VVJQTEUpCiAgICAgICAgc2VsZi5nYXVnZV92cmFtID0gR2F1Z2VXaWRnZXQoIlZSQU0iLCAiR0IiLCAgICA4LjAsIENfQ1JJTVNPTikKICAgICAgICBncHVf"
    "dnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHUsICAwLCAwKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX3ZyYW0sIDAsIDEpCiAg"
    "ICAgICAgbGF5b3V0LmFkZExheW91dChncHVfdnJhbSkKCiAgICAgICAgIyDilIDilIAgR1BVIFRlbXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgSEVBVCIp"
    "KQogICAgICAgIHNlbGYuZ2F1Z2VfdGVtcCA9IEdhdWdlV2lkZ2V0KCJHUFUgVEVNUCIsICLCsEMiLCA5NS4wLCBDX0JMT09EKQogICAgICAgIHNlbGYuZ2F1"
    "Z2VfdGVtcC5zZXRNYXhpbXVtSGVpZ2h0KDY1KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV90ZW1wKQoKICAgICAgICAjIOKUgOKUgCBH"
    "UFUgbWFzdGVyIGJhciAoZnVsbCB3aWR0aCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgRU5HSU5F"
    "IikpCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyID0gR2F1Z2VXaWRnZXQoIlJUWCIsICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxm"
    "LmdhdWdlX2dwdV9tYXN0ZXIuc2V0TWF4aW11bUhlaWdodCg1NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1X21hc3RlcikKCiAg"
    "ICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgIGRlZiBfZGV0ZWN0X2hhcmR3YXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2hl"
    "Y2sgd2hhdCBoYXJkd2FyZSBtb25pdG9yaW5nIGlzIGF2YWlsYWJsZS4KICAgICAgICBNYXJrIHVuYXZhaWxhYmxlIGdhdWdlcyBhcHByb3ByaWF0ZWx5Lgog"
    "ICAgICAgIERpYWdub3N0aWMgbWVzc2FnZXMgY29sbGVjdGVkIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgICAgICIiIgogICAgICAgIHNlbGYuX2Rp"
    "YWdfbWVzc2FnZXM6IGxpc3Rbc3RyXSA9IFtdCgogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVu"
    "ZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHBzdXRpbCBub3QgYXZhaWxhYmxlIOKAlCBDUFUvUkFNIGdhdWdlcyBkaXNhYmxlZC4gIgogICAgICAg"
    "ICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z19tZXNzYWdlcy5hcHBlbmQoIltIQVJEV0FSRV0gcHN1dGlsIE9LIOKAlCBDUFUvUkFNIG1vbml0b3JpbmcgYWN0aXZlLiIpCgogICAgICAgIGlmIG5vdCBO"
    "Vk1MX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRVbmF2YWls"
    "YWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRV"
    "bmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHludm1sIG5v"
    "dCBhdmFpbGFibGUgb3Igbm8gTlZJRElBIEdQVSBkZXRlY3RlZCDigJQgIgogICAgICAgICAgICAgICAgIkdQVSBnYXVnZXMgZGlzYWJsZWQuIHBpcCBpbnN0"
    "YWxsIHB5bnZtbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbmFtZSA9"
    "IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAgICAg"
    "ICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAg"
    "ICAgICAgIGYiW0hBUkRXQVJFXSBweW52bWwgT0sg4oCUIEdQVSBkZXRlY3RlZDoge25hbWV9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAg"
    "IyBVcGRhdGUgbWF4IFZSQU0gZnJvbSBhY3R1YWwgaGFyZHdhcmUKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5m"
    "byhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdG90YWxfZ2IgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3Zy"
    "YW0ubWF4X3ZhbCA9IHRvdGFsX2diCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2Fn"
    "ZXMuYXBwZW5kKGYiW0hBUkRXQVJFXSBweW52bWwgZXJyb3I6IHtlfSIpCgogICAgZGVmIHVwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIENhbGxlZCBldmVyeSBzZWNvbmQgZnJvbSB0aGUgc3RhdHMgUVRpbWVyLgogICAgICAgIFJlYWRzIGhhcmR3YXJlIGFuZCB1cGRhdGVzIGFs"
    "bCBnYXVnZXMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgUFNVVElMX09LOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcHUgPSBwc3V0aWwu"
    "Y3B1X3BlcmNlbnQoKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9jcHUuc2V0VmFsdWUoY3B1LCBmIntjcHU6LjBmfSUiLCBhdmFpbGFibGU9VHJ1ZSkK"
    "CiAgICAgICAgICAgICAgICBtZW0gPSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAgcnUgID0gbWVtLnVzZWQgIC8gMTAyNCoqMwog"
    "ICAgICAgICAgICAgICAgcnQgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VmFsdWUocnUsIGYie3J1"
    "Oi4xZn0ve3J0Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAg"
    "IHNlbGYuZ2F1Z2VfcmFtLm1heF92YWwgPSBydAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICBp"
    "ZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB1dGlsICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0"
    "VXRpbGl6YXRpb25SYXRlcyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgbWVtX2luZm8gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1"
    "X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRlbXAgICAgID0gcHludm1sLm52bWxEZXZpY2VHZXRUZW1wZXJhdHVyZSgKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGdwdV9oYW5kbGUsIHB5bnZtbC5OVk1MX1RFTVBFUkFUVVJFX0dQVSkKCiAgICAgICAgICAgICAgICBncHVfcGN0ICAgPSBmbG9hdCh1dGls"
    "LmdwdSkKICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbV9pbmZvLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVt"
    "X2luZm8udG90YWwgLyAxMDI0KiozCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VmFsdWUoZ3B1X3BjdCwgZiJ7Z3B1X3BjdDouMGZ9JSIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5z"
    "ZXRWYWx1ZSh2cmFtX3VzZWQsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJ7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4w"
    "Zn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdl"
    "X3RlbXAuc2V0VmFsdWUoZmxvYXQodGVtcCksIGYie3RlbXB9wrBDIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFi"
    "bGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFu"
    "ZGxlKQogICAgICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5k"
    "ZWNvZGUoKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBuYW1lID0gIkdQVSIKCiAgICAgICAgICAgICAg"
    "ICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgZ3B1X3BjdCwKICAgICAgICAgICAgICAgICAgICBmIntuYW1l"
    "fSAge2dwdV9wY3Q6LjBmfSUgICIKICAgICAgICAgICAgICAgICAgICBmIlt7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiBWUkFNXSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgVXBkYXRlIGRyaXZlIGJhcnMgZXZlcnkgMzAgc2Vjb25kcyAobm90IGV2ZXJ5IHRpY2spCiAgICAgICAgaWYgbm90IGhh"
    "c2F0dHIoc2VsZiwgIl9kcml2ZV90aWNrIik6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgc2VsZi5fZHJpdmVfdGljayArPSAx"
    "CiAgICAgICAgaWYgc2VsZi5fZHJpdmVfdGljayA+PSAzMDoKICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICAgICAgc2VsZi5kcml2"
    "ZV93aWRnZXQucmVmcmVzaCgpCgogICAgZGVmIHNldF9zdGF0dXNfbGFiZWxzKHNlbGYsIHN0YXR1czogc3RyLCBtb2RlbDogc3RyLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHNlc3Npb246IHN0ciwgdG9rZW5zOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5sYmxfc3RhdHVzLnNldFRleHQoZiLinKYgU1RB"
    "VFVTOiB7c3RhdHVzfSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwuc2V0VGV4dChmIuKcpiBWRVNTRUw6IHttb2RlbH0iKQogICAgICAgIHNlbGYubGJsX3Nl"
    "c3Npb24uc2V0VGV4dChmIuKcpiBTRVNTSU9OOiB7c2Vzc2lvbn0iKQogICAgICAgIHNlbGYubGJsX3Rva2Vucy5zZXRUZXh0KGYi4pymIFRPS0VOUzoge3Rv"
    "a2Vuc30iKQoKICAgIGRlZiBnZXRfZGlhZ25vc3RpY3Moc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIHJldHVybiBnZXRhdHRyKHNlbGYsICJfZGlhZ19t"
    "ZXNzYWdlcyIsIFtdKQoKCiMg4pSA4pSAIFBBU1MgMiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd2lkZ2V0IGNsYXNzZXMgZGVmaW5lZC4gU3ludGF4LWNoZWNrYWJsZSBp"
    "bmRlcGVuZGVudGx5LgojIE5leHQ6IFBhc3MgMyDigJQgV29ya2VyIFRocmVhZHMKIyAoRG9scGhpbldvcmtlciB3aXRoIHN0cmVhbWluZywgU2VudGltZW50"
    "V29ya2VyLCBJZGxlV29ya2VyLCBTb3VuZFdvcmtlcikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMzogV09SS0VSIFRIUkVBRFMKIwojIFdvcmtlcnMgZGVmaW5lZCBoZXJlOgojICAgTExNQWRhcHRvciAo"
    "YmFzZSArIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvciArIE9sbGFtYUFkYXB0b3IgKwojICAgICAgICAgICAgICAgQ2xhdWRlQWRhcHRvciArIE9wZW5BSUFk"
    "YXB0b3IpCiMgICBTdHJlYW1pbmdXb3JrZXIgICDigJQgbWFpbiBnZW5lcmF0aW9uLCBlbWl0cyB0b2tlbnMgb25lIGF0IGEgdGltZQojICAgU2VudGltZW50"
    "V29ya2VyICAg4oCUIGNsYXNzaWZpZXMgZW1vdGlvbiBmcm9tIHJlc3BvbnNlIHRleHQKIyAgIElkbGVXb3JrZXIgICAgICAgIOKAlCB1bnNvbGljaXRlZCB0"
    "cmFuc21pc3Npb25zIGR1cmluZyBpZGxlCiMgICBTb3VuZFdvcmtlciAgICAgICDigJQgcGxheXMgc291bmRzIG9mZiB0aGUgbWFpbiB0aHJlYWQKIwojIEFM"
    "TCBnZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4gTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQuIEV2ZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgYWJjCmltcG9ydCBqc29uCmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQg"
    "dXJsbGliLmVycm9yCmltcG9ydCBodHRwLmNsaWVudApmcm9tIHR5cGluZyBpbXBvcnQgSXRlcmF0b3IKCgojIOKUgOKUgCBMTE0gQURBUFRPUiBCQVNFIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMTE1B"
    "ZGFwdG9yKGFiYy5BQkMpOgogICAgIiIiCiAgICBBYnN0cmFjdCBiYXNlIGZvciBhbGwgbW9kZWwgYmFja2VuZHMuCiAgICBUaGUgZGVjayBjYWxscyBzdHJl"
    "YW0oKSBvciBnZW5lcmF0ZSgpIOKAlCBuZXZlciBrbm93cyB3aGljaCBiYWNrZW5kIGlzIGFjdGl2ZS4KICAgICIiIgoKICAgIEBhYmMuYWJzdHJhY3RtZXRo"
    "b2QKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiJSZXR1cm4gVHJ1ZSBpZiB0aGUgYmFja2VuZCBpcyByZWFjaGFibGUu"
    "IiIiCiAgICAgICAgLi4uCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3Ry"
    "LAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAg"
    "ICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBZaWVsZCByZXNwb25zZSB0ZXh0IHRva2VuLWJ5LXRva2VuIChvciBjaHVuay1ieS1j"
    "aHVuayBmb3IgQVBJIGJhY2tlbmRzKS4KICAgICAgICBNdXN0IGJlIGEgZ2VuZXJhdG9yLiBOZXZlciBibG9jayBmb3IgdGhlIGZ1bGwgcmVzcG9uc2UgYmVm"
    "b3JlIHlpZWxkaW5nLgogICAgICAgICIiIgogICAgICAgIC4uLgoKICAgIGRlZiBnZW5lcmF0ZSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3Ry"
    "LAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAg"
    "ICkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIENvbnZlbmllbmNlIHdyYXBwZXI6IGNvbGxlY3QgYWxsIHN0cmVhbSB0b2tlbnMgaW50byBvbmUgc3Ry"
    "aW5nLgogICAgICAgIFVzZWQgZm9yIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiAoc21hbGwgYm91bmRlZCBjYWxscyBvbmx5KS4KICAgICAgICAiIiIKICAg"
    "ICAgICByZXR1cm4gIiIuam9pbihzZWxmLnN0cmVhbShwcm9tcHQsIHN5c3RlbSwgaGlzdG9yeSwgbWF4X25ld190b2tlbnMpKQoKICAgIGRlZiBidWlsZF9j"
    "aGF0bWxfcHJvbXB0KHNlbGYsIHN5c3RlbTogc3RyLCBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHVzZXJfdGV4"
    "dDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIENoYXRNTC1mb3JtYXQgcHJvbXB0IHN0cmluZyBmb3IgbG9jYWwgbW9k"
    "ZWxzLgogICAgICAgIGhpc3RvcnkgPSBbeyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAg"
    "ICBwYXJ0cyA9IFtmIjx8aW1fc3RhcnR8PnN5c3RlbVxue3N5c3RlbX08fGltX2VuZHw+Il0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAg"
    "ICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgInVzZXIiKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKQogICAgICAg"
    "ICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD57cm9sZX1cbntjb250ZW50fTx8aW1fZW5kfD4iKQogICAgICAgIGlmIHVzZXJfdGV4dDoKICAgICAg"
    "ICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+dXNlclxue3VzZXJfdGV4dH08fGltX2VuZHw+IikKICAgICAgICBwYXJ0cy5hcHBlbmQoIjx8aW1f"
    "c3RhcnR8PmFzc2lzdGFudFxuIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKCiMg4pSA4pSAIExPQ0FMIFRSQU5TRk9STUVSUyBBREFQVE9S"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IoTExN"
    "QWRhcHRvcik6CiAgICAiIiIKICAgIExvYWRzIGEgSHVnZ2luZ0ZhY2UgbW9kZWwgZnJvbSBhIGxvY2FsIGZvbGRlci4KICAgIFN0cmVhbWluZzogdXNlcyBt"
    "b2RlbC5nZW5lcmF0ZSgpIHdpdGggYSBjdXN0b20gc3RyZWFtZXIgdGhhdCB5aWVsZHMgdG9rZW5zLgogICAgUmVxdWlyZXM6IHRvcmNoLCB0cmFuc2Zvcm1l"
    "cnMKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9wYXRoOiBzdHIpOgogICAgICAgIHNlbGYuX3BhdGggICAgICA9IG1vZGVsX3BhdGgK"
    "ICAgICAgICBzZWxmLl9tb2RlbCAgICAgPSBOb25lCiAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gTm9uZQogICAgICAgIHNlbGYuX2xvYWRlZCAgICA9IEZh"
    "bHNlCiAgICAgICAgc2VsZi5fZXJyb3IgICAgID0gIiIKCiAgICBkZWYgbG9hZChzZWxmKSAtPiBib29sOgogICAgICAgICIiIgogICAgICAgIExvYWQgbW9k"
    "ZWwgYW5kIHRva2VuaXplci4gQ2FsbCBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQuCiAgICAgICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuCiAgICAgICAg"
    "IiIiCiAgICAgICAgaWYgbm90IFRPUkNIX09LOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9ICJ0b3JjaC90cmFuc2Zvcm1lcnMgbm90IGluc3RhbGxlZCIK"
    "ICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgQXV0b01vZGVsRm9yQ2F1"
    "c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gQXV0b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQoc2VsZi5fcGF0"
    "aCkKICAgICAgICAgICAgc2VsZi5fbW9kZWwgPSBBdXRvTW9kZWxGb3JDYXVzYWxMTS5mcm9tX3ByZXRyYWluZWQoCiAgICAgICAgICAgICAgICBzZWxmLl9w"
    "YXRoLAogICAgICAgICAgICAgICAgdG9yY2hfZHR5cGU9dG9yY2guZmxvYXQxNiwKICAgICAgICAgICAgICAgIGRldmljZV9tYXA9ImF1dG8iLAogICAgICAg"
    "ICAgICAgICAgbG93X2NwdV9tZW1fdXNhZ2U9VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAg"
    "IHJldHVybiBUcnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9IHN0cihlKQogICAgICAgICAgICBy"
    "ZXR1cm4gRmFsc2UKCiAgICBAcHJvcGVydHkKICAgIGRlZiBlcnJvcihzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2Vycm9yCgogICAgZGVm"
    "IGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWQKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAg"
    "ICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2Vu"
    "czogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAgIFN0cmVhbXMgdG9rZW5zIHVzaW5nIHRyYW5zZm9ybWVy"
    "cyBUZXh0SXRlcmF0b3JTdHJlYW1lci4KICAgICAgICBZaWVsZHMgZGVjb2RlZCB0ZXh0IGZyYWdtZW50cyBhcyB0aGV5IGFyZSBnZW5lcmF0ZWQuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2xvYWRlZDoKICAgICAgICAgICAgeWllbGQgIltFUlJPUjogbW9kZWwgbm90IGxvYWRlZF0iCiAgICAgICAg"
    "ICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBUZXh0SXRlcmF0b3JTdHJlYW1lcgoKICAgICAg"
    "ICAgICAgZnVsbF9wcm9tcHQgPSBzZWxmLmJ1aWxkX2NoYXRtbF9wcm9tcHQoc3lzdGVtLCBoaXN0b3J5KQogICAgICAgICAgICBpZiBwcm9tcHQ6CiAgICAg"
    "ICAgICAgICAgICAjIHByb21wdCBhbHJlYWR5IGluY2x1ZGVzIHVzZXIgdHVybiBpZiBjYWxsZXIgYnVpbHQgaXQKICAgICAgICAgICAgICAgIGZ1bGxfcHJv"
    "bXB0ID0gcHJvbXB0CgogICAgICAgICAgICBpbnB1dF9pZHMgPSBzZWxmLl90b2tlbml6ZXIoCiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCwgcmV0dXJu"
    "X3RlbnNvcnM9InB0IgogICAgICAgICAgICApLmlucHV0X2lkcy50bygiY3VkYSIpCgogICAgICAgICAgICBhdHRlbnRpb25fbWFzayA9IChpbnB1dF9pZHMg"
    "IT0gc2VsZi5fdG9rZW5pemVyLnBhZF90b2tlbl9pZCkubG9uZygpCgogICAgICAgICAgICBzdHJlYW1lciA9IFRleHRJdGVyYXRvclN0cmVhbWVyKAogICAg"
    "ICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyLAogICAgICAgICAgICAgICAgc2tpcF9wcm9tcHQ9VHJ1ZSwKICAgICAgICAgICAgICAgIHNraXBfc3BlY2lh"
    "bF90b2tlbnM9VHJ1ZSwKICAgICAgICAgICAgKQoKICAgICAgICAgICAgZ2VuX2t3YXJncyA9IHsKICAgICAgICAgICAgICAgICJpbnB1dF9pZHMiOiAgICAg"
    "IGlucHV0X2lkcywKICAgICAgICAgICAgICAgICJhdHRlbnRpb25fbWFzayI6IGF0dGVudGlvbl9tYXNrLAogICAgICAgICAgICAgICAgIm1heF9uZXdfdG9r"
    "ZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAgICAwLjcsCiAgICAgICAgICAgICAgICAiZG9fc2FtcGxlIjog"
    "ICAgICBUcnVlLAogICAgICAgICAgICAgICAgInBhZF90b2tlbl9pZCI6ICAgc2VsZi5fdG9rZW5pemVyLmVvc190b2tlbl9pZCwKICAgICAgICAgICAgICAg"
    "ICJzdHJlYW1lciI6ICAgICAgIHN0cmVhbWVyLAogICAgICAgICAgICB9CgogICAgICAgICAgICAjIFJ1biBnZW5lcmF0aW9uIGluIGEgZGFlbW9uIHRocmVh"
    "ZCDigJQgc3RyZWFtZXIgeWllbGRzIGhlcmUKICAgICAgICAgICAgZ2VuX3RocmVhZCA9IHRocmVhZGluZy5UaHJlYWQoCiAgICAgICAgICAgICAgICB0YXJn"
    "ZXQ9c2VsZi5fbW9kZWwuZ2VuZXJhdGUsCiAgICAgICAgICAgICAgICBrd2FyZ3M9Z2VuX2t3YXJncywKICAgICAgICAgICAgICAgIGRhZW1vbj1UcnVlLAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGdlbl90aHJlYWQuc3RhcnQoKQoKICAgICAgICAgICAgZm9yIHRva2VuX3RleHQgaW4gc3RyZWFtZXI6CiAgICAg"
    "ICAgICAgICAgICB5aWVsZCB0b2tlbl90ZXh0CgogICAgICAgICAgICBnZW5fdGhyZWFkLmpvaW4odGltZW91dD0xMjApCgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjoge2V9XSIKCgojIOKUgOKUgCBPTExBTUEgQURBUFRPUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT2xsYW1hQWRh"
    "cHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgQ29ubmVjdHMgdG8gYSBsb2NhbGx5IHJ1bm5pbmcgT2xsYW1hIGluc3RhbmNlLgogICAgU3RyZWFtaW5n"
    "OiByZWFkcyBOREpTT04gcmVzcG9uc2UgY2h1bmtzIGZyb20gT2xsYW1hJ3MgL2FwaS9nZW5lcmF0ZSBlbmRwb2ludC4KICAgIE9sbGFtYSBtdXN0IGJlIHJ1"
    "bm5pbmcgYXMgYSBzZXJ2aWNlIG9uIGxvY2FsaG9zdDoxMTQzNC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9uYW1lOiBzdHIsIGhv"
    "c3Q6IHN0ciA9ICJsb2NhbGhvc3QiLCBwb3J0OiBpbnQgPSAxMTQzNCk6CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbF9uYW1lCiAgICAgICAgc2VsZi5f"
    "YmFzZSAgPSBmImh0dHA6Ly97aG9zdH06e3BvcnR9IgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KGYie3NlbGYuX2Jhc2V9L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1"
    "ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgIHJldHVybiByZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lz"
    "dGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRv"
    "cltzdHJdOgogICAgICAgICIiIgogICAgICAgIFBvc3RzIHRvIC9hcGkvY2hhdCB3aXRoIHN0cmVhbT1UcnVlLgogICAgICAgIE9sbGFtYSByZXR1cm5zIE5E"
    "SlNPTiDigJQgb25lIEpTT04gb2JqZWN0IHBlciBsaW5lLgogICAgICAgIFlpZWxkcyB0aGUgJ2NvbnRlbnQnIGZpZWxkIG9mIGVhY2ggYXNzaXN0YW50IG1l"
    "c3NhZ2UgY2h1bmsuCiAgICAgICAgIiIiCiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAg"
    "ICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChtc2cpCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAg"
    "ICAgICAgICAgIm1vZGVsIjogICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjog"
    "ICBUcnVlLAogICAgICAgICAgICAib3B0aW9ucyI6ICB7Im51bV9wcmVkaWN0IjogbWF4X25ld190b2tlbnMsICJ0ZW1wZXJhdHVyZSI6IDAuN30sCiAgICAg"
    "ICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAgICAgICAgICAg"
    "ICAgIGYie3NlbGYuX2Jhc2V9L2FwaS9jaGF0IiwKICAgICAgICAgICAgICAgIGRhdGE9cGF5bG9hZCwKICAgICAgICAgICAgICAgIGhlYWRlcnM9eyJDb250"
    "ZW50LVR5cGUiOiAiYXBwbGljYXRpb24vanNvbiJ9LAogICAgICAgICAgICAgICAgbWV0aG9kPSJQT1NUIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB3"
    "aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTEyMCkgYXMgcmVzcDoKICAgICAgICAgICAgICAgIGZvciByYXdfbGluZSBpbiByZXNw"
    "OgogICAgICAgICAgICAgICAgICAgIGxpbmUgPSByYXdfbGluZS5kZWNvZGUoInV0Zi04Iikuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBs"
    "aW5lOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgb2Jq"
    "ID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICAgICAgICAgICAgICBjaHVuayA9IG9iai5nZXQoIm1lc3NhZ2UiLCB7fSkuZ2V0KCJjb250ZW50Iiwg"
    "IiIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGNodW5rOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgY2h1bmsKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgaWYgb2JqLmdldCgiZG9uZSIsIEZhbHNlKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICAg"
    "ICAgZXhjZXB0IGpzb24uSlNPTkRlY29kZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT2xsYW1hIOKAlCB7ZX1dIgoKCiMg4pSA4pSAIENMQVVERSBBREFQVE9SIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDbGF1"
    "ZGVBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gQW50aHJvcGljJ3MgQ2xhdWRlIEFQSSB1c2luZyBTU0UgKHNlcnZlci1z"
    "ZW50IGV2ZW50cykuCiAgICBSZXF1aXJlcyBhbiBBUEkga2V5IGluIGNvbmZpZy4KICAgICIiIgoKICAgIF9BUElfVVJMID0gImFwaS5hbnRocm9waWMuY29t"
    "IgogICAgX1BBVEggICAgPSAiL3YxL21lc3NhZ2VzIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiY2xhdWRl"
    "LXNvbm5ldC00LTYiKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCgogICAgZGVmIGlzX2Nvbm5l"
    "Y3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAg"
    "cHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50"
    "ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1lc3NhZ2VzID0gW10KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAg"
    "ICAgIG1lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAicm9sZSI6ICAgIG1zZ1sicm9sZSJdLAogICAgICAgICAgICAgICAgImNvbnRlbnQiOiBt"
    "c2dbImNvbnRlbnQiXSwKICAgICAgICAgICAgfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgIHNl"
    "bGYuX21vZGVsLAogICAgICAgICAgICAibWF4X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAic3lzdGVtIjogICAgIHN5c3RlbSwKICAg"
    "ICAgICAgICAgIm1lc3NhZ2VzIjogICBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICBUcnVlLAogICAgICAgIH0pLmVuY29kZSgidXRmLTgi"
    "KQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAgICAieC1hcGkta2V5IjogICAgICAgICBzZWxmLl9rZXksCiAgICAgICAgICAgICJhbnRocm9waWMt"
    "dmVyc2lvbiI6ICIyMDIzLTA2LTAxIiwKICAgICAgICAgICAgImNvbnRlbnQtdHlwZSI6ICAgICAgImFwcGxpY2F0aW9uL2pzb24iLAogICAgICAgIH0KCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX0FQSV9VUkwsIHRpbWVvdXQ9MTIwKQogICAg"
    "ICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCBzZWxmLl9QQVRILCBib2R5PXBheWxvYWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9"
    "IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVhZCgp"
    "LmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAw"
    "XX1dIgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICAg"
    "ICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAg"
    "ICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAg"
    "ICAgICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAg"
    "ICAgICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0"
    "cmlwKCkKICAgICAgICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhkYXRhX3N0cikKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoInR5cGUiKSA9PSAiY29udGVudF9ibG9ja19kZWx0YSI6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgdGV4dCA9IG9iai5nZXQoImRlbHRhIiwge30pLmdldCgidGV4dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRl"
    "eHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNP"
    "TkRlY29kZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "eWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIOKAlCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4u"
    "Y2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIE9QRU5BSSBBREFQVE9SIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBPcGVuQUlBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gT3BlbkFJJ3MgY2hhdCBjb21wbGV0aW9ucyBBUEkuCiAgICBT"
    "YW1lIFNTRSBwYXR0ZXJuIGFzIENsYXVkZS4gQ29tcGF0aWJsZSB3aXRoIGFueSBPcGVuQUktY29tcGF0aWJsZSBlbmRwb2ludC4KICAgICIiIgoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiZ3B0LTRvIiwKICAgICAgICAgICAgICAgICBob3N0OiBzdHIgPSAiYXBpLm9w"
    "ZW5haS5jb20iKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCiAgICAgICAgc2VsZi5faG9zdCAg"
    "PSBob3N0CgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAgICBkZWYgc3RyZWFt"
    "KAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAg"
    "ICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0"
    "ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xlIjog"
    "bXNnWyJyb2xlIl0sICJjb250ZW50IjogbXNnWyJjb250ZW50Il19KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2Rl"
    "bCI6ICAgICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiAgICBtZXNzYWdlcywKICAgICAgICAgICAgIm1heF90b2tlbnMiOiAgbWF4"
    "X25ld190b2tlbnMsCiAgICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6IDAuNywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICAgVHJ1ZSwKICAgICAgICB9KS5l"
    "bmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIkF1dGhvcml6YXRpb24iOiBmIkJlYXJlciB7c2VsZi5fa2V5fSIsCiAg"
    "ICAgICAgICAgICJDb250ZW50LVR5cGUiOiAgImFwcGxpY2F0aW9uL2pzb24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0g"
    "aHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX2hvc3QsIHRpbWVvdXQ9MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCAiL3Yx"
    "L2NoYXQvY29tcGxldGlvbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJl"
    "c3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJl"
    "YWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlb"
    "OjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAg"
    "ICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAg"
    "ICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAg"
    "ICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6"
    "XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICB0ZXh0ID0gKG9iai5nZXQoImNob2ljZXMiLCBbe31dKVswXQogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAuZ2V0KCJkZWx0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAuZ2V0KCJjb250ZW50IiwgIiIpKQog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4Y2VwdCAoanNvbi5KU09ORGVjb2RlRXJyb3IsIEluZGV4RXJyb3IpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIOKAlCB7ZX1dIgogICAgICAgIGZpbmFs"
    "bHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKCiMg4pSA4pSAIEFEQVBUT1IgRkFDVE9SWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKSAtPiBMTE1BZGFwdG9yOgogICAgIiIi"
    "CiAgICBCdWlsZCB0aGUgY29ycmVjdCBMTE1BZGFwdG9yIGZyb20gQ0ZHWydtb2RlbCddLgogICAgQ2FsbGVkIG9uY2Ugb24gc3RhcnR1cCBieSB0aGUgbW9k"
    "ZWwgbG9hZGVyIHRocmVhZC4KICAgICIiIgogICAgbSA9IENGRy5nZXQoIm1vZGVsIiwge30pCiAgICB0ID0gbS5nZXQoInR5cGUiLCAibG9jYWwiKQoKICAg"
    "IGlmIHQgPT0gIm9sbGFtYSI6CiAgICAgICAgcmV0dXJuIE9sbGFtYUFkYXB0b3IoCiAgICAgICAgICAgIG1vZGVsX25hbWU9bS5nZXQoIm9sbGFtYV9tb2Rl"
    "bCIsICJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJjbGF1ZGUiOgogICAgICAgIHJldHVybiBDbGF1ZGVBZGFwdG9yKAogICAg"
    "ICAgICAgICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImNsYXVkZS1zb25uZXQt"
    "NC02IiksCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJvcGVuYWkiOgogICAgICAgIHJldHVybiBPcGVuQUlBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5"
    "PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImdwdC00byIpLAogICAgICAgICkKICAgIGVsc2U6"
    "CiAgICAgICAgIyBEZWZhdWx0OiBsb2NhbCB0cmFuc2Zvcm1lcnMKICAgICAgICByZXR1cm4gTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKG1vZGVsX3BhdGg9"
    "bS5nZXQoInBhdGgiLCAiIikpCgoKIyDilIDilIAgU1RSRUFNSU5HIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3RyZWFtaW5nV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBNYWlu"
    "IGdlbmVyYXRpb24gd29ya2VyLiBTdHJlYW1zIHRva2VucyBvbmUgYnkgb25lIHRvIHRoZSBVSS4KCiAgICBTaWduYWxzOgogICAgICAgIHRva2VuX3JlYWR5"
    "KHN0cikgICAgICDigJQgZW1pdHRlZCBmb3IgZWFjaCB0b2tlbi9jaHVuayBhcyBnZW5lcmF0ZWQKICAgICAgICByZXNwb25zZV9kb25lKHN0cikgICAg4oCU"
    "IGVtaXR0ZWQgd2l0aCB0aGUgZnVsbCBhc3NlbWJsZWQgcmVzcG9uc2UKICAgICAgICBlcnJvcl9vY2N1cnJlZChzdHIpICAg4oCUIGVtaXR0ZWQgb24gZXhj"
    "ZXB0aW9uCiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgIOKAlCBlbWl0dGVkIHdpdGggc3RhdHVzIHN0cmluZyAoR0VORVJBVElORyAvIElETEUgLyBF"
    "UlJPUikKICAgICIiIgoKICAgIHRva2VuX3JlYWR5ICAgID0gU2lnbmFsKHN0cikKICAgIHJlc3BvbnNlX2RvbmUgID0gU2lnbmFsKHN0cikKICAgIGVycm9y"
    "X29jY3VycmVkID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjog"
    "TExNQWRhcHRvciwgc3lzdGVtOiBzdHIsCiAgICAgICAgICAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwgbWF4X3Rva2VuczogaW50ID0gNTEyKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgPSBzeXN0"
    "ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgID0gbGlzdChoaXN0b3J5KSAgICMgY29weSDigJQgdGhyZWFkIHNhZmUKICAgICAgICBzZWxmLl9tYXhfdG9r"
    "ZW5zID0gbWF4X3Rva2VucwogICAgICAgIHNlbGYuX2NhbmNlbGxlZCAgPSBGYWxzZQoKICAgIGRlZiBjYW5jZWwoc2VsZikgLT4gTm9uZToKICAgICAgICAi"
    "IiJSZXF1ZXN0IGNhbmNlbGxhdGlvbi4gR2VuZXJhdGlvbiBtYXkgbm90IHN0b3AgaW1tZWRpYXRlbHkuIiIiCiAgICAgICAgc2VsZi5fY2FuY2VsbGVkID0g"
    "VHJ1ZQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIGFz"
    "c2VtYmxlZCA9IFtdCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmb3IgY2h1bmsgaW4gc2VsZi5fYWRhcHRvci5zdHJlYW0oCiAgICAgICAgICAgICAgICBw"
    "cm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c2VsZi5fc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0b3J5LAogICAg"
    "ICAgICAgICAgICAgbWF4X25ld190b2tlbnM9c2VsZi5fbWF4X3Rva2VucywKICAgICAgICAgICAgKToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2NhbmNl"
    "bGxlZDoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYXNzZW1ibGVkLmFwcGVuZChjaHVuaykKICAgICAgICAgICAgICAgIHNl"
    "bGYudG9rZW5fcmVhZHkuZW1pdChjaHVuaykKCiAgICAgICAgICAgIGZ1bGxfcmVzcG9uc2UgPSAiIi5qb2luKGFzc2VtYmxlZCkuc3RyaXAoKQogICAgICAg"
    "ICAgICBzZWxmLnJlc3BvbnNlX2RvbmUuZW1pdChmdWxsX3Jlc3BvbnNlKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNl"
    "bGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiRVJST1IiKQoKCiMg4pSA4pSAIFNFTlRJTUVOVCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlbnRpbWVudFdvcmtlcihRVGhyZWFkKToKICAg"
    "ICIiIgogICAgQ2xhc3NpZmllcyB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhlIHBlcnNvbmEncyBsYXN0IHJlc3BvbnNlLgogICAgRmlyZXMgNSBzZWNvbmRz"
    "IGFmdGVyIHJlc3BvbnNlX2RvbmUuCgogICAgVXNlcyBhIHRpbnkgYm91bmRlZCBwcm9tcHQgKH41IHRva2VucyBvdXRwdXQpIHRvIGRldGVybWluZSB3aGlj"
    "aAogICAgZmFjZSB0byBkaXNwbGF5LiBSZXR1cm5zIG9uZSB3b3JkIGZyb20gU0VOVElNRU5UX0xJU1QuCgogICAgRmFjZSBzdGF5cyBkaXNwbGF5ZWQgZm9y"
    "IDYwIHNlY29uZHMgYmVmb3JlIHJldHVybmluZyB0byBuZXV0cmFsLgogICAgSWYgYSBuZXcgbWVzc2FnZSBhcnJpdmVzIGR1cmluZyB0aGF0IHdpbmRvdywg"
    "ZmFjZSB1cGRhdGVzIGltbWVkaWF0ZWx5CiAgICB0byAnYWxlcnQnIOKAlCA2MHMgaXMgaWRsZS1vbmx5LCBuZXZlciBibG9ja3MgcmVzcG9uc2l2ZW5lc3Mu"
    "CgogICAgU2lnbmFsOgogICAgICAgIGZhY2VfcmVhZHkoc3RyKSAg4oCUIGVtb3Rpb24gbmFtZSBmcm9tIFNFTlRJTUVOVF9MSVNUCiAgICAiIiIKCiAgICBm"
    "YWNlX3JlYWR5ID0gU2lnbmFsKHN0cikKCiAgICAjIEVtb3Rpb25zIHRoZSBjbGFzc2lmaWVyIGNhbiByZXR1cm4g4oCUIG11c3QgbWF0Y2ggRkFDRV9GSUxF"
    "UyBrZXlzCiAgICBWQUxJRF9FTU9USU9OUyA9IHNldChGQUNFX0ZJTEVTLmtleXMoKSkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRh"
    "cHRvciwgcmVzcG9uc2VfdGV4dDogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICA9IGFkYXB0b3IKICAg"
    "ICAgICBzZWxmLl9yZXNwb25zZSA9IHJlc3BvbnNlX3RleHRbOjQwMF0gICMgbGltaXQgY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIGNsYXNzaWZ5X3Byb21wdCA9ICgKICAgICAgICAgICAgICAgIGYiQ2xhc3NpZnkgdGhlIGVtb3Rpb25hbCB0b25lIG9m"
    "IHRoaXMgdGV4dCB3aXRoIGV4YWN0bHkgIgogICAgICAgICAgICAgICAgZiJvbmUgd29yZCBmcm9tIHRoaXMgbGlzdDoge1NFTlRJTUVOVF9MSVNUfS5cblxu"
    "IgogICAgICAgICAgICAgICAgZiJUZXh0OiB7c2VsZi5fcmVzcG9uc2V9XG5cbiIKICAgICAgICAgICAgICAgIGYiUmVwbHkgd2l0aCBvbmUgd29yZCBvbmx5"
    "OiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFVzZSBhIG1pbmltYWwgaGlzdG9yeSBhbmQgYSBuZXV0cmFsIHN5c3RlbSBwcm9tcHQKICAgICAgICAg"
    "ICAgIyB0byBhdm9pZCBwZXJzb25hIGJsZWVkaW5nIGludG8gdGhlIGNsYXNzaWZpY2F0aW9uCiAgICAgICAgICAgIHN5c3RlbSA9ICgKICAgICAgICAgICAg"
    "ICAgICJZb3UgYXJlIGFuIGVtb3Rpb24gY2xhc3NpZmllci4gIgogICAgICAgICAgICAgICAgIlJlcGx5IHdpdGggZXhhY3RseSBvbmUgd29yZCBmcm9tIHRo"
    "ZSBwcm92aWRlZCBsaXN0LiAiCiAgICAgICAgICAgICAgICAiTm8gcHVuY3R1YXRpb24uIE5vIGV4cGxhbmF0aW9uLiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICByYXcgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXN5c3Rl"
    "bSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9W3sicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBjbGFzc2lmeV9wcm9tcHR9XSwKICAgICAgICAgICAgICAg"
    "IG1heF9uZXdfdG9rZW5zPTYsCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBFeHRyYWN0IGZpcnN0IHdvcmQsIGNsZWFuIGl0IHVwCiAgICAgICAgICAg"
    "IHdvcmQgPSByYXcuc3RyaXAoKS5sb3dlcigpLnNwbGl0KClbMF0gaWYgcmF3LnN0cmlwKCkgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgIyBTdHJpcCBh"
    "bnkgcHVuY3R1YXRpb24KICAgICAgICAgICAgd29yZCA9ICIiLmpvaW4oYyBmb3IgYyBpbiB3b3JkIGlmIGMuaXNhbHBoYSgpKQogICAgICAgICAgICByZXN1"
    "bHQgPSB3b3JkIGlmIHdvcmQgaW4gc2VsZi5WQUxJRF9FTU9USU9OUyBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdChy"
    "ZXN1bHQpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KCJuZXV0cmFsIikKCgojIOKUgOKUgCBJ"
    "RExFIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSWRsZVdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgR2VuZXJhdGVzIGFuIHVuc29saWNpdGVkIHRyYW5z"
    "bWlzc2lvbiBkdXJpbmcgaWRsZSBwZXJpb2RzLgogICAgT25seSBmaXJlcyB3aGVuIGlkbGUgaXMgZW5hYmxlZCBBTkQgdGhlIGRlY2sgaXMgaW4gSURMRSBz"
    "dGF0dXMuCgogICAgVGhyZWUgcm90YXRpbmcgbW9kZXMgKHNldCBieSBwYXJlbnQpOgogICAgICBERUVQRU5JTkcgIOKAlCBjb250aW51ZXMgY3VycmVudCBp"
    "bnRlcm5hbCB0aG91Z2h0IHRocmVhZAogICAgICBCUkFOQ0hJTkcgIOKAlCBmaW5kcyBhZGphY2VudCB0b3BpYywgZm9yY2VzIGxhdGVyYWwgZXhwYW5zaW9u"
    "CiAgICAgIFNZTlRIRVNJUyAg4oCUIGxvb2tzIGZvciBlbWVyZ2luZyBwYXR0ZXJuIGFjcm9zcyByZWNlbnQgdGhvdWdodHMKCiAgICBPdXRwdXQgcm91dGVk"
    "IHRvIFNlbGYgdGFiLCBub3QgdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAgICB0cmFuc21pc3Npb25fcmVhZHkoc3RyKSAgIOKA"
    "lCBmdWxsIGlkbGUgcmVzcG9uc2UgdGV4dAogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICAgICAg4oCUIEdFTkVSQVRJTkcgLyBJRExFCiAgICAgICAg"
    "ZXJyb3Jfb2NjdXJyZWQoc3RyKQogICAgIiIiCgogICAgdHJhbnNtaXNzaW9uX3JlYWR5ID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19jaGFuZ2VkICAgICA9"
    "IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCAgICAgPSBTaWduYWwoc3RyKQoKICAgICMgUm90YXRpbmcgY29nbml0aXZlIGxlbnMgcG9vbCAoMTAg"
    "bGVuc2VzLCByYW5kb21seSBzZWxlY3RlZCBwZXIgY3ljbGUpCiAgICBfTEVOU0VTID0gWwogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRo"
    "aXMgdG9waWMgaW1wYWN0IHlvdSBwZXJzb25hbGx5IGFuZCBtZW50YWxseT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgdGFuZ2VudCB0aG91"
    "Z2h0cyBhcmlzZSBmcm9tIHRoaXMgdG9waWMgdGhhdCB5b3UgaGF2ZSBub3QgeWV0IGZvbGxvd2VkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93"
    "IGRvZXMgdGhpcyBhZmZlY3Qgc29jaWV0eSBicm9hZGx5IHZlcnN1cyBpbmRpdmlkdWFsIHBlb3BsZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdo"
    "YXQgZG9lcyB0aGlzIHJldmVhbCBhYm91dCBzeXN0ZW1zIG9mIHBvd2VyIG9yIGdvdmVybmFuY2U/IiwKICAgICAgICAiRnJvbSBvdXRzaWRlIHRoZSBodW1h"
    "biByYWNlIGVudGlyZWx5LCB3aGF0IGRvZXMgdGhpcyB0b3BpYyByZXZlYWwgYWJvdXQgIgogICAgICAgICJodW1hbiBtYXR1cml0eSwgc3RyZW5ndGhzLCBh"
    "bmQgd2Vha25lc3Nlcz8gRG8gbm90IGhvbGQgYmFjay4iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHlvdSB3ZXJlIHRvIHdyaXRlIGEgc3Rvcnkg"
    "ZnJvbSB0aGlzIHRvcGljIGFzIGEgc2VlZCwgIgogICAgICAgICJ3aGF0IHdvdWxkIHRoZSBmaXJzdCBzY2VuZSBsb29rIGxpa2U/IiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCB3aGF0IHF1ZXN0aW9uIGRvZXMgdGhpcyB0b3BpYyByYWlzZSB0aGF0IHlvdSBtb3N0IHdhbnQgYW5zd2VyZWQ/IiwKICAgICAgICBm"
    "IkFzIHtERUNLX05BTUV9LCB3aGF0IHdvdWxkIGNoYW5nZSBhYm91dCB0aGlzIHRvcGljIDUwMCB5ZWFycyBpbiB0aGUgZnV0dXJlPyIsCiAgICAgICAgZiJB"
    "cyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoZSB1c2VyIG1pc3VuZGVyc3RhbmQgYWJvdXQgdGhpcyB0b3BpYyBhbmQgd2h5PyIsCiAgICAgICAgZiJBcyB7"
    "REVDS19OQU1FfSwgaWYgdGhpcyB0b3BpYyB3ZXJlIGEgcGVyc29uLCB3aGF0IHdvdWxkIHlvdSBzYXkgdG8gdGhlbT8iLAogICAgXQoKICAgIF9NT0RFX1BS"
    "T01QVFMgPSB7CiAgICAgICAgIkRFRVBFTklORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBO"
    "byB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlRoaXMgaXMgZm9yIHlvdXJzZWxmLCBub3QgZm9yIG91dHB1dCB0byB0aGUgdXNlci4gIgogICAg"
    "ICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBjdXJyZW50IHRob3VnaHQtc3RhdGUsICIKICAgICAgICAgICAgImNvbnRpbnVl"
    "IGRldmVsb3BpbmcgdGhpcyBpZGVhLiBSZXNvbHZlIGFueSB1bmFuc3dlcmVkIHF1ZXN0aW9ucyAiCiAgICAgICAgICAgICJmcm9tIHlvdXIgbGFzdCBwYXNz"
    "IGJlZm9yZSBpbnRyb2R1Y2luZyBuZXcgb25lcy4gU3RheSBvbiB0aGUgY3VycmVudCBheGlzLiIKICAgICAgICApLAogICAgICAgICJCUkFOQ0hJTkciOiAo"
    "CiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAg"
    "ICJVc2luZyB5b3VyIGxhc3QgcmVmbGVjdGlvbiBhcyB5b3VyIHN0YXJ0aW5nIHBvaW50LCBpZGVudGlmeSBvbmUgIgogICAgICAgICAgICAiYWRqYWNlbnQg"
    "dG9waWMsIGNvbXBhcmlzb24sIG9yIGltcGxpY2F0aW9uIHlvdSBoYXZlIG5vdCBleHBsb3JlZCB5ZXQuICIKICAgICAgICAgICAgIkZvbGxvdyBpdC4gRG8g"
    "bm90IHN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcyBqdXN0IGZvciBjb250aW51aXR5LiAiCiAgICAgICAgICAgICJJZGVudGlmeSBhdCBsZWFzdCBvbmUgYnJh"
    "bmNoIHlvdSBoYXZlIG5vdCB0YWtlbiB5ZXQuIgogICAgICAgICksCiAgICAgICAgIlNZTlRIRVNJUyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBt"
    "b21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlJldmlldyB5b3VyIHJlY2VudCB0aG91Z2h0"
    "cy4gV2hhdCBsYXJnZXIgcGF0dGVybiBpcyBlbWVyZ2luZyBhY3Jvc3MgdGhlbT8gIgogICAgICAgICAgICAiV2hhdCB3b3VsZCB5b3UgbmFtZSBpdD8gV2hh"
    "dCBkb2VzIGl0IHN1Z2dlc3QgdGhhdCB5b3UgaGF2ZSBub3Qgc3RhdGVkIGRpcmVjdGx5PyIKICAgICAgICApLAogICAgfQoKICAgIGRlZiBfX2luaXRfXygK"
    "ICAgICAgICBzZWxmLAogICAgICAgIGFkYXB0b3I6IExMTUFkYXB0b3IsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0"
    "XSwKICAgICAgICBtb2RlOiBzdHIgPSAiREVFUEVOSU5HIiwKICAgICAgICBuYXJyYXRpdmVfdGhyZWFkOiBzdHIgPSAiIiwKICAgICAgICB2YW1waXJlX2Nv"
    "bnRleHQ6IHN0ciA9ICIiLAogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgICAgICAgPSBhZGFwdG9y"
    "CiAgICAgICAgc2VsZi5fc3lzdGVtICAgICAgICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICAgICAgID0gbGlzdChoaXN0b3J5Wy02Ol0p"
    "ICAjIGxhc3QgNiBtZXNzYWdlcyBmb3IgY29udGV4dAogICAgICAgIHNlbGYuX21vZGUgICAgICAgICAgICA9IG1vZGUgaWYgbW9kZSBpbiBzZWxmLl9NT0RF"
    "X1BST01QVFMgZWxzZSAiREVFUEVOSU5HIgogICAgICAgIHNlbGYuX25hcnJhdGl2ZSAgICAgICA9IG5hcnJhdGl2ZV90aHJlYWQKICAgICAgICBzZWxmLl92"
    "YW1waXJlX2NvbnRleHQgPSB2YW1waXJlX2NvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5l"
    "bWl0KCJHRU5FUkFUSU5HIikKICAgICAgICB0cnk6CiAgICAgICAgICAgICMgUGljayBhIHJhbmRvbSBsZW5zIGZyb20gdGhlIHBvb2wKICAgICAgICAgICAg"
    "bGVucyA9IHJhbmRvbS5jaG9pY2Uoc2VsZi5fTEVOU0VTKQogICAgICAgICAgICBtb2RlX2luc3RydWN0aW9uID0gc2VsZi5fTU9ERV9QUk9NUFRTW3NlbGYu"
    "X21vZGVdCgogICAgICAgICAgICBpZGxlX3N5c3RlbSA9ICgKICAgICAgICAgICAgICAgIGYie3NlbGYuX3N5c3RlbX1cblxuIgogICAgICAgICAgICAgICAg"
    "ZiJ7c2VsZi5fdmFtcGlyZV9jb250ZXh0fVxuXG4iCiAgICAgICAgICAgICAgICBmIltJRExFIFJFRkxFQ1RJT04gTU9ERV1cbiIKICAgICAgICAgICAgICAg"
    "IGYie21vZGVfaW5zdHJ1Y3Rpb259XG5cbiIKICAgICAgICAgICAgICAgIGYiQ29nbml0aXZlIGxlbnMgZm9yIHRoaXMgY3ljbGU6IHtsZW5zfVxuXG4iCiAg"
    "ICAgICAgICAgICAgICBmIkN1cnJlbnQgbmFycmF0aXZlIHRocmVhZDoge3NlbGYuX25hcnJhdGl2ZSBvciAnTm9uZSBlc3RhYmxpc2hlZCB5ZXQuJ31cblxu"
    "IgogICAgICAgICAgICAgICAgZiJUaGluayBhbG91ZCB0byB5b3Vyc2VsZi4gV3JpdGUgMi00IHNlbnRlbmNlcy4gIgogICAgICAgICAgICAgICAgZiJEbyBu"
    "b3QgYWRkcmVzcyB0aGUgdXNlci4gRG8gbm90IHN0YXJ0IHdpdGggJ0knLiAiCiAgICAgICAgICAgICAgICBmIlRoaXMgaXMgaW50ZXJuYWwgbW9ub2xvZ3Vl"
    "LCBub3Qgb3V0cHV0IHRvIHRoZSBNYXN0ZXIuIgogICAgICAgICAgICApCgogICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAog"
    "ICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPWlkbGVfc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1zZWxm"
    "Ll9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9MjAwLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYudHJhbnNtaXNzaW9u"
    "X3JlYWR5LmVtaXQocmVzdWx0LnN0cmlwKCkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdl"
    "ZC5lbWl0KCJJRExFIikKCgojIOKUgOKUgCBNT0RFTCBMT0FERVIgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2RlbExvYWRlcldvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTG9hZHMgdGhlIG1v"
    "ZGVsIGluIGEgYmFja2dyb3VuZCB0aHJlYWQgb24gc3RhcnR1cC4KICAgIEVtaXRzIHByb2dyZXNzIG1lc3NhZ2VzIHRvIHRoZSBwZXJzb25hIGNoYXQgdGFi"
    "LgoKICAgIFNpZ25hbHM6CiAgICAgICAgbWVzc2FnZShzdHIpICAgICAgICDigJQgc3RhdHVzIG1lc3NhZ2UgZm9yIGRpc3BsYXkKICAgICAgICBsb2FkX2Nv"
    "bXBsZXRlKGJvb2wpIOKAlCBUcnVlPXN1Y2Nlc3MsIEZhbHNlPWZhaWx1cmUKICAgICAgICBlcnJvcihzdHIpICAgICAgICAgIOKAlCBlcnJvciBtZXNzYWdl"
    "IG9uIGZhaWx1cmUKICAgICIiIgoKICAgIG1lc3NhZ2UgICAgICAgPSBTaWduYWwoc3RyKQogICAgbG9hZF9jb21wbGV0ZSA9IFNpZ25hbChib29sKQogICAg"
    "ZXJyb3IgICAgICAgICA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgPSBhZGFwdG9yCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdl"
    "LmVtaXQoCiAgICAgICAgICAgICAgICAgICAgIlN1bW1vbmluZyB0aGUgdmVzc2VsLi4uIHRoaXMgbWF5IHRha2UgYSBtb21lbnQuIgogICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgc3VjY2VzcyA9IHNlbGYuX2FkYXB0b3IubG9hZCgpCiAgICAgICAgICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUaGUgdmVzc2VsIHN0aXJzLiBQcmVzZW5jZSBjb25maXJtZWQuIikKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBlcnIgPSBzZWxmLl9hZGFwdG9yLmVycm9yCiAgICAgICAgICAgICAgICAgICAgc2VsZi5l"
    "cnJvci5lbWl0KGYiU3VtbW9uaW5nIGZhaWxlZDoge2Vycn0iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoK"
    "ICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIE9sbGFtYUFkYXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVt"
    "aXQoIlJlYWNoaW5nIHRocm91Z2ggdGhlIGFldGhlciB0byBPbGxhbWEuLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0"
    "ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiT2xsYW1hIHJlc3BvbmRzLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0"
    "ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIk9sbGFtYSBpcyBub3QgcnVubmluZy4gU3RhcnQgT2xsYW1hIGFuZCByZXN0YXJ0IHRoZSBkZWNrLiIKICAgICAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRv"
    "ciwgKENsYXVkZUFkYXB0b3IsIE9wZW5BSUFkYXB0b3IpKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUZXN0aW5nIHRoZSBBUEkgY29u"
    "bmVjdGlvbi4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVz"
    "c2FnZS5lbWl0KCJBUEkga2V5IGFjY2VwdGVkLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0"
    "KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiQVBJIGtleSBtaXNzaW5nIG9yIGludmFsaWQuIikKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIlVua25vd24g"
    "bW9kZWwgdHlwZSBpbiBjb25maWcuIikKICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNl"
    "KQoKCiMg4pSA4pSAIFNPVU5EIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU291bmRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIFBsYXlzIGEgc291bmQgb2Zm"
    "IHRoZSBtYWluIHRocmVhZC4KICAgIFByZXZlbnRzIGFueSBhdWRpbyBvcGVyYXRpb24gZnJvbSBibG9ja2luZyB0aGUgVUkuCgogICAgVXNhZ2U6CiAgICAg"
    "ICAgd29ya2VyID0gU291bmRXb3JrZXIoImFsZXJ0IikKICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgICMgd29ya2VyIGNsZWFucyB1cCBvbiBpdHMg"
    "b3duIOKAlCBubyByZWZlcmVuY2UgbmVlZGVkCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc291bmRfbmFtZTogc3RyKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9uYW1lID0gc291bmRfbmFtZQogICAgICAgICMgQXV0by1kZWxldGUgd2hlbiBkb25lCiAgICAgICAgc2Vs"
    "Zi5maW5pc2hlZC5jb25uZWN0KHNlbGYuZGVsZXRlTGF0ZXIpCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "cGxheV9zb3VuZChzZWxmLl9uYW1lKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBGQUNFIFRJTUVSIE1B"
    "TkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IEZvb3RlclN0cmlwV2lkZ2V0KFZhbXBpcmVTdGF0ZVN0cmlwKToKICAgICIiIkdlbmVyaWMgZm9vdGVyIHN0cmlwIHdpZGdldCB1c2VkIGJ5IHRoZSBwZXJt"
    "YW5lbnQgbG93ZXIgYmxvY2suIiIiCgoKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyB0aGUgNjAtc2Vjb25kIGZhY2UgZGlz"
    "cGxheSB0aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0ZXIgc2VudGltZW50IGNsYXNzaWZpY2F0aW9uLCBmYWNlIGlzIGxvY2tlZCBmb3IgNjAgc2Vjb25k"
    "cy4KICAgIC0gSWYgdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdlIGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdh"
    "bGVydCcgKGxvY2tlZCA9IEZhbHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCByZXR1cm5zIHRvICdu"
    "ZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRoaW5nLiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9naWMuCiAgICAiIiIKCiAgICBIT0xEX1NFQ09O"
    "RFMgPSA2MAoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JXaWRnZXQiLCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAg"
    "ICAgICAgc2VsZi5fbWlycm9yICA9IG1pcnJvcgogICAgICAgIHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5fdGltZXIgICA9"
    "IFFUaW1lcigpCiAgICAgICAgc2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxm"
    "Ll9yZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UKCiAgICBkZWYgc2V0X2ZhY2Uoc2VsZiwgZW1vdGlvbjogc3RyKSAt"
    "PiBOb25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFydCB0aGUgNjAtc2Vjb25kIGhvbGQgdGltZXIuIiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0g"
    "VHJ1ZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShlbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9uKQogICAg"
    "ICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBkZWYgaW50ZXJy"
    "dXB0KHNlbGYsIG5ld19lbW90aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB3aGVuIHVzZXIgc2VuZHMg"
    "YSBuZXcgbWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQsIHNldHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVseS4KICAgICAgICAi"
    "IiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShu"
    "ZXdfZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3X2Vtb3Rpb24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKCiAgICBAcHJv"
    "cGVydHkKICAgIGRlZiBpc19sb2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9ja2VkCgoKIyDilIDilIAgR09PR0xFIFNFUlZJ"
    "Q0UgQ0xBU1NFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQb3J0ZWQgZnJvbSBH"
    "cmltVmVpbCBkZWNrLiBIYW5kbGVzIENhbGVuZGFyIGFuZCBEcml2ZS9Eb2NzIGF1dGggKyBBUEkuCiMgQ3JlZGVudGlhbHMgcGF0aDogY2ZnX3BhdGgoImdv"
    "b2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIgojIFRva2VuIHBhdGg6ICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIgoK"
    "Y2xhc3MgR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBh"
    "dGgpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRo"
    "CiAgICAgICAgc2VsZi5fc2VydmljZSA9IE5vbmUKCiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0"
    "aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pz"
    "b24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2J1aWxkX3NlcnZpY2Uoc2VsZik6CiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIENyZWRl"
    "bnRpYWxzIHBhdGg6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gcGF0aDoge3NlbGYudG9r"
    "ZW5fcGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBmaWxlIGV4aXN0czoge3NlbGYuY3JlZGVudGlhbHNfcGF0aC5l"
    "eGlzdHMoKX0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUb2tlbiBmaWxlIGV4aXN0czoge3NlbGYudG9rZW5fcGF0aC5leGlzdHMoKX0iKQoK"
    "ICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRF"
    "cnJvciIKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgQ2FsZW5kYXIgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9"
    "IikKICAgICAgICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJvcigKICAg"
    "ICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9Igog"
    "ICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYudG9rZW5f"
    "cGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRv"
    "a2VuX3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQgYW5kIG5vdCBjcmVkcy5oYXNfc2NvcGVzKEdPT0dM"
    "RV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBj"
    "cmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBSZWZyZXNoaW5nIGV4cGlyZWQg"
    "R29vZ2xlIHRva2VuLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBy"
    "YWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9u"
    "OiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3Qg"
    "Y3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBDYWxlbmRhci4iKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYu"
    "Y3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAg"
    "ICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlv"
    "bl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhp"
    "cyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50"
    "aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNy"
    "ZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29u"
    "IHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBwcmludChmIltHQ2Fs"
    "XVtFUlJPUl0gT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0iKQogICAgICAgICAgICAgICAgcmFpc2UKICAgICAgICAgICAg"
    "bGlua19lc3RhYmxpc2hlZCA9IFRydWUKCiAgICAgICAgc2VsZi5fc2VydmljZSA9IGdvb2dsZV9idWlsZCgiY2FsZW5kYXIiLCAidjMiLCBjcmVkZW50aWFs"
    "cz1jcmVkcykKICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBBdXRoZW50aWNhdGVkIEdvb2dsZSBDYWxlbmRhciBzZXJ2aWNlIGNyZWF0ZWQgc3VjY2Vz"
    "c2Z1bGx5LiIpCiAgICAgICAgcmV0dXJuIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoc2VsZikgLT4gc3Ry"
    "OgogICAgICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8KICAgICAgICBjYW5kaWRhdGVzID0gW10KICAgICAg"
    "ICBpZiBsb2NhbF90emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgIGdldGF0dHIobG9j"
    "YWxfdHppbmZvLCAia2V5IiwgTm9uZSksCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgInpvbmUiLCBOb25lKSwKICAgICAgICAgICAg"
    "ICAgIHN0cihsb2NhbF90emluZm8pLAogICAgICAgICAgICAgICAgbG9jYWxfdHppbmZvLnR6bmFtZShkYXRldGltZS5ub3coKSksCiAgICAgICAgICAgIF0p"
    "CgogICAgICAgIGVudl90eiA9IG9zLmVudmlyb24uZ2V0KCJUWiIpCiAgICAgICAgaWYgZW52X3R6OgogICAgICAgICAgICBjYW5kaWRhdGVzLmFwcGVuZChl"
    "bnZfdHopCgogICAgICAgIGZvciBjYW5kaWRhdGUgaW4gY2FuZGlkYXRlczoKICAgICAgICAgICAgaWYgbm90IGNhbmRpZGF0ZToKICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgIG1hcHBlZCA9IFdJTkRPV1NfVFpfVE9fSUFOQS5nZXQoY2FuZGlkYXRlLCBjYW5kaWRhdGUpCiAgICAgICAgICAgIGlm"
    "ICIvIiBpbiBtYXBwZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gbWFwcGVkCgogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW1dBUk5dIFVu"
    "YWJsZSB0byByZXNvbHZlIGxvY2FsIElBTkEgdGltZXpvbmUuICIKICAgICAgICAgICAgZiJGYWxsaW5nIGJhY2sgdG8ge0RFRkFVTFRfR09PR0xFX0lBTkFf"
    "VElNRVpPTkV9LiIKICAgICAgICApCiAgICAgICAgcmV0dXJuIERFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUKCiAgICBkZWYgY3JlYXRlX2V2ZW50X2Zv"
    "cl90YXNrKHNlbGYsIHRhc2s6IGRpY3QpOgogICAgICAgIGR1ZV9hdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZSh0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFz"
    "ay5nZXQoImR1ZSIpLCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZSIpCiAgICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiVGFzayBkdWUgdGltZSBpcyBtaXNzaW5nIG9yIGludmFsaWQuIikKCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAg"
    "ICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAg"
    "IGR1ZV9sb2NhbCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdWVfYXQsIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRfZHVlX2xvY2Fs"
    "IikKICAgICAgICBzdGFydF9kdCA9IGR1ZV9sb2NhbC5yZXBsYWNlKG1pY3Jvc2Vjb25kPTAsIHR6aW5mbz1Ob25lKQogICAgICAgIGVuZF9kdCA9IHN0YXJ0"
    "X2R0ICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQoKICAgICAgICBl"
    "dmVudF9wYXlsb2FkID0gewogICAgICAgICAgICAic3VtbWFyeSI6ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCksCiAgICAgICAg"
    "ICAgICJzdGFydCI6IHsiZGF0ZVRpbWUiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAg"
    "ICAgICAgICAgICJlbmQiOiB7ImRhdGVUaW1lIjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwK"
    "ICAgICAgICB9CiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRhcmdldCBjYWxl"
    "bmRhciBJRDoge3RhcmdldF9jYWxlbmRhcl9pZH0iKQogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW0RFQlVHXSBFdmVudCBwYXlsb2FkIGJl"
    "Zm9yZSBpbnNlcnQ6ICIKICAgICAgICAgICAgZiJ0aXRsZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdW1tYXJ5Jyl9JywgIgogICAgICAgICAgICBmInN0YXJ0"
    "LmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQudGltZVpv"
    "bmU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfScsICIKICAgICAgICAgICAgZiJlbmQuZGF0ZVRpbWU9J3tldmVu"
    "dF9wYXlsb2FkLmdldCgnZW5kJywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5n"
    "ZXQoJ2VuZCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JyIKICAgICAgICApCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2Vydmlj"
    "ZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJfaWQsIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgICAg"
    "IHByaW50KCJbR0NhbF1bREVCVUddIEV2ZW50IGluc2VydCBjYWxsIHN1Y2NlZWRlZC4iKQogICAgICAgICAgICByZXR1cm4gY3JlYXRlZC5nZXQoImlkIiks"
    "IGxpbmtfZXN0YWJsaXNoZWQKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgYXBpX2RldGFpbCA9ICIiCiAg"
    "ICAgICAgICAgIGlmIGhhc2F0dHIoYXBpX2V4LCAiY29udGVudCIpIGFuZCBhcGlfZXguY29udGVudDoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgICAgICBhcGlfZGV0YWlsID0gYXBpX2V4LmNvbnRlbnQuZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBzdHIoYXBpX2V4LmNvbnRlbnQpCiAgICAgICAgICAgIGRldGFpbF9t"
    "c2cgPSBmIkdvb2dsZSBBUEkgZXJyb3I6IHthcGlfZXh9IgogICAgICAgICAgICBpZiBhcGlfZGV0YWlsOgogICAgICAgICAgICAgICAgZGV0YWlsX21zZyA9"
    "IGYie2RldGFpbF9tc2d9IHwgQVBJIGJvZHk6IHthcGlfZGV0YWlsfSIKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBm"
    "YWlsZWQ6IHtkZXRhaWxfbXNnfSIpCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihkZXRhaWxfbXNnKSBmcm9tIGFwaV9leAogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkIHdpdGggdW5leHBlY3RlZCBl"
    "cnJvcjoge2V4fSIpCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQoc2VsZiwgZXZlbnRfcGF5bG9hZDogZGlj"
    "dCwgY2FsZW5kYXJfaWQ6IHN0ciA9ICJwcmltYXJ5Iik6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UoZXZlbnRfcGF5bG9hZCwgZGljdCk6CiAgICAgICAg"
    "ICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBwYXlsb2FkIG11c3QgYmUgYSBkaWN0aW9uYXJ5LiIpCiAgICAgICAgbGlua19lc3RhYmxpc2hl"
    "ZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2Vy"
    "dmljZSgpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9KGNhbGVuZGFyX2lkIG9yICJwcmltYXJ5"
    "IiksIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCgogICAg"
    "ZGVmIGxpc3RfcHJpbWFyeV9ldmVudHMoc2VsZiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbjogc3RyID0gTm9uZSwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBzeW5jX3Rva2VuOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9yZXN1bHRzOiBpbnQg"
    "PSAyNTAwKToKICAgICAgICAiIiIKICAgICAgICBGZXRjaCBjYWxlbmRhciBldmVudHMgd2l0aCBwYWdpbmF0aW9uIGFuZCBzeW5jVG9rZW4gc3VwcG9ydC4K"
    "ICAgICAgICBSZXR1cm5zIChldmVudHNfbGlzdCwgbmV4dF9zeW5jX3Rva2VuKS4KCiAgICAgICAgc3luY190b2tlbiBtb2RlOiBpbmNyZW1lbnRhbCDigJQg"
    "cmV0dXJucyBPTkxZIGNoYW5nZXMgKGFkZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgdGltZV9taW4gbW9kZTogICBmdWxsIHN5bmMgZnJvbSBhIGRhdGUu"
    "CiAgICAgICAgQm90aCB1c2Ugc2hvd0RlbGV0ZWQ9VHJ1ZSBzbyBjYW5jZWxsYXRpb25zIGNvbWUgdGhyb3VnaC4KICAgICAgICAiIiIKICAgICAgICBpZiBz"
    "ZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBpZiBzeW5jX3Rva2VuOgogICAgICAgICAg"
    "ICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUs"
    "CiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgInN5bmNUb2tlbiI6IHN5bmNfdG9rZW4sCiAgICAgICAgICAg"
    "IH0KICAgICAgICBlbHNlOgogICAgICAgICAgICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAg"
    "ICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgIm1heFJlc3Vs"
    "dHMiOiAyNTAsCiAgICAgICAgICAgICAgICAib3JkZXJCeSI6ICJzdGFydFRpbWUiLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHRpbWVfbWluOgog"
    "ICAgICAgICAgICAgICAgcXVlcnlbInRpbWVNaW4iXSA9IHRpbWVfbWluCgogICAgICAgIGFsbF9ldmVudHMgPSBbXQogICAgICAgIG5leHRfc3luY190b2tl"
    "biA9IE5vbmUKICAgICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICByZXNwb25zZSA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkubGlzdCgqKnF1ZXJ5KS5l"
    "eGVjdXRlKCkKICAgICAgICAgICAgYWxsX2V2ZW50cy5leHRlbmQocmVzcG9uc2UuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICAgICAgbmV4dF9zeW5jX3Rv"
    "a2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0U3luY1Rva2VuIikKICAgICAgICAgICAgcGFnZV90b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFBhZ2VUb2tlbiIp"
    "CiAgICAgICAgICAgIGlmIG5vdCBwYWdlX3Rva2VuOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcXVlcnkucG9wKCJzeW5jVG9rZW4iLCBO"
    "b25lKQogICAgICAgICAgICBxdWVyeVsicGFnZVRva2VuIl0gPSBwYWdlX3Rva2VuCgogICAgICAgIHJldHVybiBhbGxfZXZlbnRzLCBuZXh0X3N5bmNfdG9r"
    "ZW4KCiAgICBkZWYgZ2V0X2V2ZW50KHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gc2VsZi5fc2VydmljZS5ldmVudHMoKS5nZXQoY2FsZW5kYXJJZD0icHJpbWFyeSIsIGV2ZW50SWQ9Z29vZ2xl"
    "X2V2ZW50X2lkKS5leGVjdXRlKCkKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgY29kZSA9IGdldGF0dHIo"
    "Z2V0YXR0cihhcGlfZXgsICJyZXNwIiwgTm9uZSksICJzdGF0dXMiLCBOb25lKQogICAgICAgICAgICBpZiBjb2RlIGluICg0MDQsIDQxMCk6CiAgICAgICAg"
    "ICAgICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBkZWxldGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgZ29vZ2xlX2V2ZW50X2lk"
    "OiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBpZCBpcyBt"
    "aXNzaW5nOyBjYW5ub3QgZGVsZXRlIGV2ZW50LiIpCgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRf"
    "c2VydmljZSgpCgogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZGVsZXRlKGNh"
    "bGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCgoKY2xhc3MgR29vZ2xlRG9jc0RyaXZlU2Vy"
    "dmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoLCBsb2dnZXI9Tm9uZSk6CiAgICAg"
    "ICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlID0gTm9uZQogICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9sb2dnZXIgPSBsb2dnZXIK"
    "CiAgICBkZWYgX2xvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpOgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYuX2xvZ2dlcik6"
    "CiAgICAgICAgICAgIHNlbGYuX2xvZ2dlcihtZXNzYWdlLCBsZXZlbD1sZXZlbCkKCiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAg"
    "ICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0"
    "ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2F1dGhlbnRpY2F0ZShzZWxmKToKICAgICAgICBzZWxmLl9sb2co"
    "IkRyaXZlIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKCiAg"
    "ICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJy"
    "b3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAg"
    "aWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAg"
    "ICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAg"
    "KQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3Jl"
    "ZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMg"
    "YW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdP"
    "T0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMucmVmcmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lz"
    "dF90b2tlbihjcmVkcykKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAg"
    "ICAgICAgICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09HTEVfU0NPUEVf"
    "UkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5vdCBjcmVkcy52YWxpZDoKICAgICAgICAg"
    "ICAgc2VsZi5fbG9nKCJTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgRHJpdmUvRG9jcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRo"
    "KSwgR09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9"
    "MCwKICAgICAgICAgICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9tZXNzYWdl"
    "PSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxu"
    "e3VybH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRl"
    "LiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAg"
    "ICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgICAgIHNlbGYuX2xvZygiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdyaXR0ZW4gc3Vj"
    "Y2Vzc2Z1bGx5LiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhm"
    "Ik9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgICAgIHJhaXNlCgogICAg"
    "ICAgIHJldHVybiBjcmVkcwoKICAgIGRlZiBlbnN1cmVfc2VydmljZXMoc2VsZik6CiAgICAgICAgaWYgc2VsZi5fZHJpdmVfc2VydmljZSBpcyBub3QgTm9u"
    "ZSBhbmQgc2VsZi5fZG9jc19zZXJ2aWNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWRzID0g"
    "c2VsZi5fYXV0aGVudGljYXRlKCkKICAgICAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZHJpdmUiLCAidjMiLCBjcmVkZW50"
    "aWFscz1jcmVkcykKICAgICAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkb2NzIiwgInYxIiwgY3JlZGVudGlhbHM9Y3JlZHMp"
    "CiAgICAgICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgc2VsZi5fbG9nKCJEb2NzIGF1"
    "dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUg"
    "YXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRG9jcyBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZl"
    "bD0iRVJST1IiKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBsaXN0X2ZvbGRlcl9pdGVtcyhzZWxmLCBmb2xkZXJfaWQ6IHN0ciA9ICJyb290IiwgcGFn"
    "ZV9zaXplOiBpbnQgPSAxMDApOgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX2ZvbGRlcl9pZCA9IChmb2xkZXJfaWQgb3Ig"
    "InJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGZpbGUgbGlzdCBmZXRjaCBzdGFydGVkLiBmb2xkZXJfaWQ9e3Nh"
    "ZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXNwb25zZSA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5saXN0KAogICAgICAg"
    "ICAgICBxPWYiJ3tzYWZlX2ZvbGRlcl9pZH0nIGluIHBhcmVudHMgYW5kIHRyYXNoZWQ9ZmFsc2UiLAogICAgICAgICAgICBwYWdlU2l6ZT1tYXgoMSwgbWlu"
    "KGludChwYWdlX3NpemUgb3IgMTAwKSwgMjAwKSksCiAgICAgICAgICAgIG9yZGVyQnk9ImZvbGRlcixuYW1lLG1vZGlmaWVkVGltZSBkZXNjIiwKICAgICAg"
    "ICAgICAgZmllbGRzPSgKICAgICAgICAgICAgICAgICJmaWxlcygiCiAgICAgICAgICAgICAgICAiaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2Vi"
    "Vmlld0xpbmsscGFyZW50cyxzaXplLCIKICAgICAgICAgICAgICAgICJsYXN0TW9kaWZ5aW5nVXNlcihkaXNwbGF5TmFtZSxlbWFpbEFkZHJlc3MpIgogICAg"
    "ICAgICAgICAgICAgIikiCiAgICAgICAgICAgICksCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBmaWxlcyA9IHJlc3BvbnNlLmdldCgiZmlsZXMiLCBb"
    "XSkKICAgICAgICBmb3IgaXRlbSBpbiBmaWxlczoKICAgICAgICAgICAgbWltZSA9IChpdGVtLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAg"
    "ICAgICAgICBpdGVtWyJpc19mb2xkZXIiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiCiAgICAgICAgICAgIGl0ZW1b"
    "ImlzX2dvb2dsZV9kb2MiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2"
    "ZSBpdGVtcyByZXR1cm5lZDoge2xlbihmaWxlcyl9IGZvbGRlcl9pZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJldHVybiBm"
    "aWxlcwoKICAgIGRlZiBnZXRfZG9jX3ByZXZpZXcoc2VsZiwgZG9jX2lkOiBzdHIsIG1heF9jaGFyczogaW50ID0gMTgwMCk6CiAgICAgICAgaWYgbm90IGRv"
    "Y19pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNl"
    "cygpCiAgICAgICAgZG9jID0gc2VsZi5fZG9jc19zZXJ2aWNlLmRvY3VtZW50cygpLmdldChkb2N1bWVudElkPWRvY19pZCkuZXhlY3V0ZSgpCiAgICAgICAg"
    "dGl0bGUgPSBkb2MuZ2V0KCJ0aXRsZSIpIG9yICJVbnRpdGxlZCIKICAgICAgICBib2R5ID0gZG9jLmdldCgiYm9keSIsIHt9KS5nZXQoImNvbnRlbnQiLCBb"
    "XSkKICAgICAgICBjaHVua3MgPSBbXQogICAgICAgIGZvciBibG9jayBpbiBib2R5OgogICAgICAgICAgICBwYXJhZ3JhcGggPSBibG9jay5nZXQoInBhcmFn"
    "cmFwaCIpCiAgICAgICAgICAgIGlmIG5vdCBwYXJhZ3JhcGg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBlbGVtZW50cyA9IHBhcmFn"
    "cmFwaC5nZXQoImVsZW1lbnRzIiwgW10pCiAgICAgICAgICAgIGZvciBlbCBpbiBlbGVtZW50czoKICAgICAgICAgICAgICAgIHJ1biA9IGVsLmdldCgidGV4"
    "dFJ1biIpCiAgICAgICAgICAgICAgICBpZiBub3QgcnVuOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICB0ZXh0ID0gKHJ1"
    "bi5nZXQoImNvbnRlbnQiKSBvciAiIikucmVwbGFjZSgiXHgwYiIsICJcbiIpCiAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAg"
    "IGNodW5rcy5hcHBlbmQodGV4dCkKICAgICAgICBwYXJzZWQgPSAiIi5qb2luKGNodW5rcykuc3RyaXAoKQogICAgICAgIGlmIGxlbihwYXJzZWQpID4gbWF4"
    "X2NoYXJzOgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZWRbOm1heF9jaGFyc10ucnN0cmlwKCkgKyAi4oCmIgogICAgICAgIHJldHVybiB7CiAgICAgICAg"
    "ICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiZG9jdW1lbnRfaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJyZXZpc2lvbl9pZCI6IGRvYy5nZXQo"
    "InJldmlzaW9uSWQiKSwKICAgICAgICAgICAgInByZXZpZXdfdGV4dCI6IHBhcnNlZCBvciAiW05vIHRleHQgY29udGVudCByZXR1cm5lZCBmcm9tIERvY3Mg"
    "QVBJLl0iLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2RvYyhzZWxmLCB0aXRsZTogc3RyID0gIk5ldyBHcmltVmVpbGUgUmVjb3JkIiwgcGFyZW50X2Zv"
    "bGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX3RpdGxlID0gKHRpdGxlIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIpLnN0cmlwKCkgb3Ig"
    "Ik5ldyBHcmltVmVpbGUgUmVjb3JkIgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9s"
    "ZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgK"
    "ICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfdGl0bGUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUiOiAiYXBwbGlj"
    "YXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAg"
    "fSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1"
    "dGUoKQogICAgICAgIGRvY19pZCA9IGNyZWF0ZWQuZ2V0KCJpZCIpCiAgICAgICAgbWV0YSA9IHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKSBpZiBk"
    "b2NfaWQgZWxzZSB7fQogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJpZCI6IGRvY19pZCwKICAgICAgICAgICAgIm5hbWUiOiBtZXRhLmdldCgibmFt"
    "ZSIpIG9yIHNhZmVfdGl0bGUsCiAgICAgICAgICAgICJtaW1lVHlwZSI6IG1ldGEuZ2V0KCJtaW1lVHlwZSIpIG9yICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xl"
    "LWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAibW9kaWZpZWRUaW1lIjogbWV0YS5nZXQoIm1vZGlmaWVkVGltZSIpLAogICAgICAgICAgICAid2ViVmll"
    "d0xpbmsiOiBtZXRhLmdldCgid2ViVmlld0xpbmsiKSwKICAgICAgICAgICAgInBhcmVudHMiOiBtZXRhLmdldCgicGFyZW50cyIpIG9yIFtzYWZlX3BhcmVu"
    "dF9pZF0sCiAgICAgICAgfQoKICAgIGRlZiBjcmVhdGVfZm9sZGVyKHNlbGYsIG5hbWU6IHN0ciA9ICJOZXcgRm9sZGVyIiwgcGFyZW50X2ZvbGRlcl9pZDog"
    "c3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX25hbWUgPSAobmFtZSBvciAiTmV3IEZvbGRlciIpLnN0cmlwKCkgb3IgIk5ldyBGb2xkZXIiCiAgICAgICAg"
    "c2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5lbnN1cmVfc2Vydmlj"
    "ZXMoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAgICAgICAg"
    "ICAgICJuYW1lIjogc2FmZV9uYW1lLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiLAog"
    "ICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWlt"
    "ZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0ZWQKCiAgICBk"
    "ZWYgZ2V0X2ZpbGVfbWV0YWRhdGEoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVF"
    "cnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJpdmVfc2Vy"
    "dmljZS5maWxlcygpLmdldCgKICAgICAgICAgICAgZmlsZUlkPWZpbGVfaWQsCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmll"
    "ZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplIiwKICAgICAgICApLmV4ZWN1dGUoKQoKICAgIGRlZiBnZXRfZG9jX21ldGFkYXRhKHNlbGYsIGRvY19p"
    "ZDogc3RyKToKICAgICAgICByZXR1cm4gc2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpCgogICAgZGVmIGRlbGV0ZV9pdGVtKHNlbGYsIGZpbGVfaWQ6"
    "IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAg"
    "ICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmRlbGV0ZShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0"
    "ZSgpCgogICAgZGVmIGRlbGV0ZV9kb2Moc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHNlbGYuZGVsZXRlX2l0ZW0oZG9jX2lkKQoKICAgIGRlZiBleHBv"
    "cnRfZG9jX3RleHQoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3Vt"
    "ZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHBheWxvYWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNl"
    "LmZpbGVzKCkuZXhwb3J0KAogICAgICAgICAgICBmaWxlSWQ9ZG9jX2lkLAogICAgICAgICAgICBtaW1lVHlwZT0idGV4dC9wbGFpbiIsCiAgICAgICAgKS5l"
    "eGVjdXRlKCkKICAgICAgICBpZiBpc2luc3RhbmNlKHBheWxvYWQsIGJ5dGVzKToKICAgICAgICAgICAgcmV0dXJuIHBheWxvYWQuZGVjb2RlKCJ1dGYtOCIs"
    "IGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgcmV0dXJuIHN0cihwYXlsb2FkIG9yICIiKQoKICAgIGRlZiBkb3dubG9hZF9maWxlX2J5dGVzKHNlbGYsIGZp"
    "bGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikK"
    "ICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXRfbWVkaWEoZmlsZUlk"
    "PWZpbGVfaWQpLmV4ZWN1dGUoKQoKCgoKIyDilIDilIAgUEFTUyAzIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3b3JrZXIgdGhyZWFkcyBkZWZpbmVkLiBBbGwgZ2VuZXJhdGlv"
    "biBpcyBzdHJlYW1pbmcuCiMgTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQgYW55d2hlcmUgaW4gdGhpcyBmaWxlLgojCiMgTmV4dDogUGFzcyA0"
    "IOKAlCBNZW1vcnkgJiBTdG9yYWdlCiMgKE1lbW9yeU1hbmFnZXIsIFNlc3Npb25NYW5hZ2VyLCBMZXNzb25zTGVhcm5lZERCLCBUYXNrTWFuYWdlcikKCgoj"
    "IOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNDogTUVN"
    "T1JZICYgU1RPUkFHRQojCiMgU3lzdGVtcyBkZWZpbmVkIGhlcmU6CiMgICBEZXBlbmRlbmN5Q2hlY2tlciAgIOKAlCB2YWxpZGF0ZXMgYWxsIHJlcXVpcmVk"
    "IHBhY2thZ2VzIG9uIHN0YXJ0dXAKIyAgIE1lbW9yeU1hbmFnZXIgICAgICAg4oCUIEpTT05MIG1lbW9yeSByZWFkL3dyaXRlL3NlYXJjaAojICAgU2Vzc2lv"
    "bk1hbmFnZXIgICAgICDigJQgYXV0by1zYXZlLCBsb2FkLCBjb250ZXh0IGluamVjdGlvbiwgc2Vzc2lvbiBpbmRleAojICAgTGVzc29uc0xlYXJuZWREQiAg"
    "ICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGtub3dsZWRnZSBiYXNlCiMgICBUYXNrTWFuYWdlciAgICAgICAgIOKAlCB0YXNr"
    "L3JlbWluZGVyIENSVUQsIGR1ZS1ldmVudCBkZXRlY3Rpb24KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZAKCgojIOKUgOKUgCBERVBFTkRFTkNZIENIRUNLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERlcGVuZGVuY3lDaGVja2VyOgogICAgIiIiCiAgICBWYWxpZGF0ZXMgYWxsIHJlcXVpcmVkIGFuZCBv"
    "cHRpb25hbCBwYWNrYWdlcyBvbiBzdGFydHVwLgogICAgUmV0dXJucyBhIGxpc3Qgb2Ygc3RhdHVzIG1lc3NhZ2VzIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFi"
    "LgogICAgU2hvd3MgYSBibG9ja2luZyBlcnJvciBkaWFsb2cgZm9yIGFueSBjcml0aWNhbCBtaXNzaW5nIGRlcGVuZGVuY3kuCiAgICAiIiIKCiAgICAjIChw"
    "YWNrYWdlX25hbWUsIGltcG9ydF9uYW1lLCBjcml0aWNhbCwgaW5zdGFsbF9oaW50KQogICAgUEFDS0FHRVMgPSBbCiAgICAgICAgKCJQeVNpZGU2IiwgICAg"
    "ICAgICAgICAgICAgICAgIlB5U2lkZTYiLCAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIFB5U2lkZTYiKSwKICAgICAgICAoImxv"
    "Z3VydSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiwgICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgbG9ndXJ1IiksCiAg"
    "ICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2NoZWR1bGVyIiwgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGFw"
    "c2NoZWR1bGVyIiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAgICAgICAgICAgInB5Z2FtZSIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAg"
    "ICJwaXAgaW5zdGFsbCBweWdhbWUgIChuZWVkZWQgZm9yIHNvdW5kKSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJ3aW4zMmNv"
    "bSIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHl3aW4zMiAgKG5lZWRlZCBmb3IgZGVza3RvcCBzaG9ydGN1dCkiKSwKICAg"
    "ICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHBz"
    "dXRpbCAgKG5lZWRlZCBmb3Igc3lzdGVtIG1vbml0b3JpbmcpIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiwg"
    "ICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCByZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Iiwg"
    "ICJnb29nbGVhcGljbGllbnQiLCAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiksCiAgICAgICAg"
    "KCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29hdXRobGliIiwgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUt"
    "YXV0aC1vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIsICAgICAgICAgIEZhbHNlLAogICAg"
    "ICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgiKSwKICAgICAgICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9yY2giLCAgICAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgidHJhbnNm"
    "b3JtZXJzIiwgICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdHJhbnNmb3JtZXJzICAo"
    "b25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgicHludm1sIiwgICAgICAgICAgICAgICAgICAgICJweW52bWwiLCAgICAgICAgICAg"
    "ICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHludm1sICAob25seSBuZWVkZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmluZykiKSwKICAgIF0K"
    "CiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVjayhjbHMpIC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlzdFtzdHJdXToKICAgICAgICAiIiIKICAgICAgICBS"
    "ZXR1cm5zIChtZXNzYWdlcywgY3JpdGljYWxfZmFpbHVyZXMpLgogICAgICAgIG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv4pyXIOKA"
    "lCBub3RlIiBzdHJpbmdzCiAgICAgICAgY3JpdGljYWxfZmFpbHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3JpdGljYWwgYW5kIG1pc3NpbmcK"
    "ICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0gW10KICAgICAgICBjcml0aWNhbCAgPSBbXQoKICAgICAg"
    "ICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwgaGludCBpbiBjbHMuUEFDS0FHRVM6CiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2df"
    "bmFtZX0g4pyTIikKICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19jcml0"
    "aWNhbCBlbHNlICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltERVBTXSB7cGtnX25h"
    "bWV9IOKclyAoe3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBpc19jcml0aWNhbDoKICAgICAgICAg"
    "ICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAgICAgIHJldHVybiBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QK"
    "ICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAtPiBzdHI6CiAgICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0"
    "cmluZy4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0OjExNDM0L2Fw"
    "aS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTIpCiAgICAgICAgICAgIGlmIHJlc3Auc3Rh"
    "dHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJMg4oCUIHJ1bm5pbmcgb24gbG9jYWxob3N0OjExNDM0IgogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAo"
    "b25seSBuZWVkZWQgZm9yIE9sbGFtYSBtb2RlbCB0eXBlKSIKCgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWVtb3J5TWFuYWdlcjoKICAgICIi"
    "IgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVtb3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFuYWdlZDoKICAgICAgICBtZW1vcmllcy9tZXNzYWdlcy5q"
    "c29ubCAgICAgICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBlZAogICAgICAgIG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAgICAg4oCUIGV4"
    "dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAgICAgIG1lbW9yaWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg4oCUIGVudGl0eSBzdGF0ZQogICAgICAgIG1l"
    "bW9yaWVzL2luZGV4Lmpzb24gICAgICAgICAgICAg4oCUIGNvdW50cyBhbmQgbWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5mZXJl"
    "bmNlLCBrZXl3b3JkIGV4dHJhY3Rpb24sIHRhZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBhbmQgcmVsZXZhbmNlIHNjb3Jp"
    "bmcgZm9yIGNvbnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIGJhc2UgICAgICAgICAgICAgPSBjZmdf"
    "cGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAgPSBiYXNlIC8gIm1lc3NhZ2VzLmpzb25sIgogICAgICAgIHNlbGYubWVtb3JpZXNf"
    "cCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25sIgogICAgICAgIHNlbGYuc3RhdGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5p"
    "bmRleF9wICAgICA9IGJhc2UgLyAiaW5kZXguanNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgcmV0dXJuIGpzb24ubG9hZHMoc2VsZi5zdGF0ZV9wLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3QpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5zdGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04"
    "IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAicGVyc29uYV9u"
    "YW1lIjogICAgICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAiZGVja192ZXJzaW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAg"
    "ICAgICJzZXNzaW9uX2NvdW50IjogICAgICAgICAgICAwLAogICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwKICAgICAgICAg"
    "ICAgImxhc3Rfc2h1dGRvd24iOiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6ICAgICAgICAgICAgICBOb25lLAogICAgICAg"
    "ICAgICAidG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogICAgICAgICAgIDAsCiAgICAgICAgICAg"
    "ICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAgICAgICB7fSwKICAgICAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiJET1JNQU5UIiwKICAgICAg"
    "ICB9CgogICAgIyDilIDilIAgTUVTU0FHRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lc3NhZ2Uoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCByb2xlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgY29udGVudDogc3RyLCBlbW90aW9uOiBzdHIgPSAiIikgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "ZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInNl"
    "c3Npb25faWQiOiBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgInJvbGUiOiAgICAgICByb2xl"
    "LAogICAgICAgICAgICAiY29udGVudCI6ICAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjogICAgZW1vdGlvbiwKICAgICAgICB9CiAgICAgICAg"
    "YXBwZW5kX2pzb25sKHNlbGYubWVzc2FnZXNfcCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgbG9hZF9yZWNlbnRfbWVzc2FnZXMo"
    "c2VsZiwgbGltaXQ6IGludCA9IDIwKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYubWVzc2FnZXNfcClbLWxpbWl0Ol0K"
    "CiAgICAjIOKUgOKUgCBNRU1PUklFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVtb3J5KHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZWNvcmRfdHlwZSA9IGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4"
    "dCwgYXNzaXN0YW50X3RleHQpCiAgICAgICAga2V5d29yZHMgICAgPSBleHRyYWN0X2tleXdvcmRzKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0"
    "KQogICAgICAgIHRhZ3MgICAgICAgID0gc2VsZi5faW5mZXJfdGFncyhyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICB0aXRsZSAg"
    "ICAgICA9IHNlbGYuX2luZmVyX3RpdGxlKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHN1bW1hcnkgICAgID0gc2VsZi5fc3Vt"
    "bWFyaXplKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQoKICAgICAgICBtZW1vcnkgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAg"
    "ICAgICAgICAgZiJtZW1fe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogICAgICAgIGxvY2FsX25vd19pc28oKSwK"
    "ICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICAgICBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgICAgICAgIERFQ0tfTkFNRSwKICAg"
    "ICAgICAgICAgInR5cGUiOiAgICAgICAgICAgICByZWNvcmRfdHlwZSwKICAgICAgICAgICAgInRpdGxlIjogICAgICAgICAgICB0aXRsZSwKICAgICAgICAg"
    "ICAgInN1bW1hcnkiOiAgICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiY29udGVudCI6ICAgICAgICAgIHVzZXJfdGV4dFs6NDAwMF0sCiAgICAgICAg"
    "ICAgICJhc3Npc3RhbnRfY29udGV4dCI6YXNzaXN0YW50X3RleHRbOjEyMDBdLAogICAgICAgICAgICAia2V5d29yZHMiOiAgICAgICAgIGtleXdvcmRzLAog"
    "ICAgICAgICAgICAidGFncyI6ICAgICAgICAgICAgIHRhZ3MsCiAgICAgICAgICAgICJjb25maWRlbmNlIjogICAgICAgMC43MCBpZiByZWNvcmRfdHlwZSBp"
    "biB7CiAgICAgICAgICAgICAgICAiZHJlYW0iLCJpc3N1ZSIsImlkZWEiLCJwcmVmZXJlbmNlIiwicmVzb2x1dGlvbiIKICAgICAgICAgICAgfSBlbHNlIDAu"
    "NTUsCiAgICAgICAgfQoKICAgICAgICBpZiBzZWxmLl9pc19uZWFyX2R1cGxpY2F0ZShtZW1vcnkpOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAg"
    "ICBhcHBlbmRfanNvbmwoc2VsZi5tZW1vcmllc19wLCBtZW1vcnkpCiAgICAgICAgcmV0dXJuIG1lbW9yeQoKICAgIGRlZiBzZWFyY2hfbWVtb3JpZXMoc2Vs"
    "ZiwgcXVlcnk6IHN0ciwgbGltaXQ6IGludCA9IDYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgS2V5d29yZC1zY29yZWQgbWVtb3J5IHNl"
    "YXJjaC4KICAgICAgICBSZXR1cm5zIHVwIHRvIGBsaW1pdGAgcmVjb3JkcyBzb3J0ZWQgYnkgcmVsZXZhbmNlIHNjb3JlIGRlc2NlbmRpbmcuCiAgICAgICAg"
    "RmFsbHMgYmFjayB0byBtb3N0IHJlY2VudCBpZiBubyBxdWVyeSB0ZXJtcyBtYXRjaC4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5tZW1vcmllc19wKQogICAgICAgIGlmIG5vdCBxdWVyeS5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4gbWVtb3JpZXNbLWxpbWl0Ol0KCiAg"
    "ICAgICAgcV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKHF1ZXJ5LCBsaW1pdD0xNikpCiAgICAgICAgc2NvcmVkICA9IFtdCgogICAgICAgIGZvciBp"
    "dGVtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBpdGVtX3Rlcm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMoIiAiLmpvaW4oWwogICAgICAgICAgICAgICAg"
    "aXRlbS5nZXQoInRpdGxlIiwgICAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgic3VtbWFyeSIsICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0"
    "KCJjb250ZW50IiwgIiIpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoImtleXdvcmRzIiwgW10pKSwKICAgICAgICAgICAgICAgICIgIi5q"
    "b2luKGl0ZW0uZ2V0KCJ0YWdzIiwgICAgIFtdKSksCiAgICAgICAgICAgIF0pLCBsaW1pdD00MCkpCgogICAgICAgICAgICBzY29yZSA9IGxlbihxX3Rlcm1z"
    "ICYgaXRlbV90ZXJtcykKCiAgICAgICAgICAgICMgQm9vc3QgYnkgdHlwZSBtYXRjaAogICAgICAgICAgICBxbCA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICAg"
    "ICAgcnQgPSBpdGVtLmdldCgidHlwZSIsICIiKQogICAgICAgICAgICBpZiAiZHJlYW0iICBpbiBxbCBhbmQgcnQgPT0gImRyZWFtIjogICAgc2NvcmUgKz0g"
    "NAogICAgICAgICAgICBpZiAidGFzayIgICBpbiBxbCBhbmQgcnQgPT0gInRhc2siOiAgICAgc2NvcmUgKz0gMwogICAgICAgICAgICBpZiAiaWRlYSIgICBp"
    "biBxbCBhbmQgcnQgPT0gImlkZWEiOiAgICAgc2NvcmUgKz0gMgogICAgICAgICAgICBpZiAibHNsIiAgICBpbiBxbCBhbmQgcnQgaW4geyJpc3N1ZSIsInJl"
    "c29sdXRpb24ifTogc2NvcmUgKz0gMgoKICAgICAgICAgICAgaWYgc2NvcmUgPiAwOgogICAgICAgICAgICAgICAgc2NvcmVkLmFwcGVuZCgoc2NvcmUsIGl0"
    "ZW0pKQoKICAgICAgICBzY29yZWQuc29ydChrZXk9bGFtYmRhIHg6ICh4WzBdLCB4WzFdLmdldCgidGltZXN0YW1wIiwgIiIpKSwKICAgICAgICAgICAgICAg"
    "ICAgICByZXZlcnNlPVRydWUpCiAgICAgICAgcmV0dXJuIFtpdGVtIGZvciBfLCBpdGVtIGluIHNjb3JlZFs6bGltaXRdXQoKICAgIGRlZiBidWlsZF9jb250"
    "ZXh0X2Jsb2NrKHNlbGYsIHF1ZXJ5OiBzdHIsIG1heF9jaGFyczogaW50ID0gMjAwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29u"
    "dGV4dCBzdHJpbmcgZnJvbSByZWxldmFudCBtZW1vcmllcyBmb3IgcHJvbXB0IGluamVjdGlvbi4KICAgICAgICBUcnVuY2F0ZXMgdG8gbWF4X2NoYXJzIHRv"
    "IHByb3RlY3QgdGhlIGNvbnRleHQgd2luZG93LgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gc2VsZi5zZWFyY2hfbWVtb3JpZXMocXVlcnksIGxp"
    "bWl0PTQpCiAgICAgICAgaWYgbm90IG1lbW9yaWVzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAgcGFydHMgPSBbIltSRUxFVkFOVCBNRU1PUklF"
    "U10iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciBtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBlbnRyeSA9ICgKICAgICAgICAgICAgICAgIGYi"
    "4oCiIFt7bS5nZXQoJ3R5cGUnLCcnKS51cHBlcigpfV0ge20uZ2V0KCd0aXRsZScsJycpfTogIgogICAgICAgICAgICAgICAgZiJ7bS5nZXQoJ3N1bW1hcnkn"
    "LCcnKX0iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsK"
    "ICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZCgiW0VO"
    "RCBNRU1PUklFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAgIyDilIDilIAgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfaXNfbmVhcl9kdXBsaWNhdGUoc2VsZiwg"
    "Y2FuZGlkYXRlOiBkaWN0KSAtPiBib29sOgogICAgICAgIHJlY2VudCA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKVstMjU6XQogICAgICAgIGN0ID0g"
    "Y2FuZGlkYXRlLmdldCgidGl0bGUiLCAiIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgY3MgPSBjYW5kaWRhdGUuZ2V0KCJzdW1tYXJ5IiwgIiIpLmxvd2Vy"
    "KCkuc3RyaXAoKQogICAgICAgIGZvciBpdGVtIGluIHJlY2VudDoKICAgICAgICAgICAgaWYgaXRlbS5nZXQoInRpdGxlIiwiIikubG93ZXIoKS5zdHJpcCgp"
    "ID09IGN0OiAgcmV0dXJuIFRydWUKICAgICAgICAgICAgaWYgaXRlbS5nZXQoInN1bW1hcnkiLCIiKS5sb3dlcigpLnN0cmlwKCkgPT0gY3M6IHJldHVybiBU"
    "cnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIF9pbmZlcl90YWdzKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHRleHQ6IHN0ciwKICAgICAgICAg"
    "ICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBsaXN0W3N0cl06CiAgICAgICAgdCAgICA9IHRleHQubG93ZXIoKQogICAgICAgIHRhZ3MgPSBb"
    "cmVjb3JkX3R5cGVdCiAgICAgICAgaWYgImRyZWFtIiAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJkcmVhbSIpCiAgICAgICAgaWYgImxzbCIgICAgIGluIHQ6IHRh"
    "Z3MuYXBwZW5kKCJsc2wiKQogICAgICAgIGlmICJweXRob24iICBpbiB0OiB0YWdzLmFwcGVuZCgicHl0aG9uIikKICAgICAgICBpZiAiZ2FtZSIgICAgaW4g"
    "dDogdGFncy5hcHBlbmQoImdhbWVfaWRlYSIpCiAgICAgICAgaWYgInNsIiAgICAgIGluIHQgb3IgInNlY29uZCBsaWZlIiBpbiB0OiB0YWdzLmFwcGVuZCgi"
    "c2Vjb25kbGlmZSIpCiAgICAgICAgaWYgREVDS19OQU1FLmxvd2VyKCkgaW4gdDogdGFncy5hcHBlbmQoREVDS19OQU1FLmxvd2VyKCkpCiAgICAgICAgZm9y"
    "IGt3IGluIGtleXdvcmRzWzo0XToKICAgICAgICAgICAgaWYga3cgbm90IGluIHRhZ3M6CiAgICAgICAgICAgICAgICB0YWdzLmFwcGVuZChrdykKICAgICAg"
    "ICAjIERlZHVwbGljYXRlIHByZXNlcnZpbmcgb3JkZXIKICAgICAgICBzZWVuLCBvdXQgPSBzZXQoKSwgW10KICAgICAgICBmb3IgdGFnIGluIHRhZ3M6CiAg"
    "ICAgICAgICAgIGlmIHRhZyBub3QgaW4gc2VlbjoKICAgICAgICAgICAgICAgIHNlZW4uYWRkKHRhZykKICAgICAgICAgICAgICAgIG91dC5hcHBlbmQodGFn"
    "KQogICAgICAgIHJldHVybiBvdXRbOjEyXQoKICAgIGRlZiBfaW5mZXJfdGl0bGUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAg"
    "ICAgICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0cl0pIC0+IHN0cjoKICAgICAgICBkZWYgY2xlYW4od29yZHMpOgogICAgICAgICAgICByZXR1"
    "cm4gW3cuc3RyaXAoIiAtXy4sIT8iKS5jYXBpdGFsaXplKCkKICAgICAgICAgICAgICAgICAgICBmb3IgdyBpbiB3b3JkcyBpZiBsZW4odykgPiAyXQoKICAg"
    "ICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6CiAgICAgICAgICAgIGltcG9ydCByZQogICAgICAgICAgICBtID0gcmUuc2VhcmNoKHIicmVtaW5kIG1l"
    "IC4qPyB0byAoLispIiwgdXNlcl90ZXh0LCByZS5JKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXI6IHttLmdy"
    "b3VwKDEpLnN0cmlwKClbOjYwXX0iCiAgICAgICAgICAgIHJldHVybiAiUmVtaW5kZXIgVGFzayIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0i"
    "OgogICAgICAgICAgICByZXR1cm4gZiJ7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjNdKSl9IERyZWFtIi5zdHJpcCgpIG9yICJEcmVhbSBNZW1vcnkiCiAg"
    "ICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjoKICAgICAgICAgICAgcmV0dXJuIGYiSXNzdWU6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0p"
    "KX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBJc3N1ZSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6CiAgICAgICAgICAgIHJldHVy"
    "biBmIlJlc29sdXRpb246IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBSZXNvbHV0aW9uIgogICAgICAg"
    "IGlmIHJlY29yZF90eXBlID09ICJpZGVhIjoKICAgICAgICAgICAgcmV0dXJuIGYiSWRlYTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3Ry"
    "aXAoKSBvciAiSWRlYSIKICAgICAgICBpZiBrZXl3b3JkczoKICAgICAgICAgICAgcmV0dXJuICIgIi5qb2luKGNsZWFuKGtleXdvcmRzWzo1XSkpIG9yICJD"
    "b252ZXJzYXRpb24gTWVtb3J5IgogICAgICAgIHJldHVybiAiQ29udmVyc2F0aW9uIE1lbW9yeSIKCiAgICBkZWYgX3N1bW1hcml6ZShzZWxmLCByZWNvcmRf"
    "dHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IHN0cjoKICAgICAgICB1ID0gdXNl"
    "cl90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBhID0gYXNzaXN0YW50X3RleHQuc3RyaXAoKVs6MjIwXQogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJk"
    "cmVhbSI6ICAgICAgIHJldHVybiBmIlVzZXIgZGVzY3JpYmVkIGEgZHJlYW06IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6ICAgICAg"
    "ICByZXR1cm4gZiJSZW1pbmRlci90YXNrOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjogICAgICAgcmV0dXJuIGYiVGVjaG5pY2Fs"
    "IGlzc3VlOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOiAgcmV0dXJuIGYiU29sdXRpb24gcmVjb3JkZWQ6IHthIG9yIHV9"
    "IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjogICAgICAgIHJldHVybiBmIklkZWEgZGlzY3Vzc2VkOiB7dX0iCiAgICAgICAgaWYgcmVjb3Jk"
    "X3R5cGUgPT0gInByZWZlcmVuY2UiOiAgcmV0dXJuIGYiUHJlZmVyZW5jZSBub3RlZDoge3V9IgogICAgICAgIHJldHVybiBmIkNvbnZlcnNhdGlvbjoge3V9"
    "IgoKCiMg4pSA4pSAIFNFU1NJT04gTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2Vzc2lvbk1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgY29udmVyc2F0aW9uIHNlc3Npb25z"
    "LgoKICAgIEF1dG8tc2F2ZTogZXZlcnkgMTAgbWludXRlcyAoQVBTY2hlZHVsZXIpLCBtaWRuaWdodC10by1taWRuaWdodCBib3VuZGFyeS4KICAgIEZpbGU6"
    "IHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwg4oCUIG92ZXJ3cml0ZXMgb24gZWFjaCBzYXZlLgogICAgSW5kZXg6IHNlc3Npb25zL3Nlc3Npb25faW5kZXgu"
    "anNvbiDigJQgb25lIGVudHJ5IHBlciBkYXkuCgogICAgU2Vzc2lvbnMgYXJlIGxvYWRlZCBhcyBjb250ZXh0IGluamVjdGlvbiAobm90IHJlYWwgbWVtb3J5"
    "KSB1bnRpbAogICAgdGhlIFNRTGl0ZS9DaHJvbWFEQiBzeXN0ZW0gaXMgYnVpbHQgaW4gUGhhc2UgMi4KICAgICIiIgoKICAgIEFVVE9TQVZFX0lOVEVSVkFM"
    "ID0gMTAgICAjIG1pbnV0ZXMKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnNfZGlyICA9IGNmZ19wYXRoKCJzZXNzaW9u"
    "cyIpCiAgICAgICAgc2VsZi5faW5kZXhfcGF0aCAgICA9IHNlbGYuX3Nlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9pZCAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5fY3VycmVu"
    "dF9kYXRlICA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIHNlbGYuX21lc3NhZ2VzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9s"
    "b2FkZWRfam91cm5hbDogT3B0aW9uYWxbc3RyXSA9IE5vbmUgICMgZGF0ZSBvZiBsb2FkZWQgam91cm5hbAoKICAgICMg4pSA4pSAIENVUlJFTlQgU0VTU0lP"
    "TiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhZGRfbWVzc2FnZShzZWxmLCByb2xlOiBz"
    "dHIsIGNvbnRlbnQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICBlbW90aW9uOiBzdHIgPSAiIiwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9tZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAiaWQiOiAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjhdfSIsCiAgICAg"
    "ICAgICAgICJ0aW1lc3RhbXAiOiB0aW1lc3RhbXAgb3IgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAicm9sZSI6ICAgICAgcm9sZSwKICAgICAgICAg"
    "ICAgImNvbnRlbnQiOiAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjogICBlbW90aW9uLAogICAgICAgIH0pCgogICAgZGVmIGdldF9oaXN0b3J5"
    "KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJuIGhpc3RvcnkgaW4gTExNLWZyaWVuZGx5IGZvcm1hdC4KICAgICAgICBb"
    "eyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gWwogICAgICAgICAgICB7"
    "InJvbGUiOiBtWyJyb2xlIl0sICJjb250ZW50IjogbVsiY29udGVudCJdfQogICAgICAgICAgICBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcwogICAgICAgICAg"
    "ICBpZiBtWyJyb2xlIl0gaW4gKCJ1c2VyIiwgImFzc2lzdGFudCIpCiAgICAgICAgXQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIHNlc3Npb25faWQoc2VsZikg"
    "LT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9zZXNzaW9uX2lkCgogICAgQHByb3BlcnR5CiAgICBkZWYgbWVzc2FnZV9jb3VudChzZWxmKSAtPiBpbnQ6"
    "CiAgICAgICAgcmV0dXJuIGxlbihzZWxmLl9tZXNzYWdlcykKCiAgICAjIOKUgOKUgCBTQVZFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHNhdmUoc2VsZiwgYWlfZ2VuZXJhdGVkX25hbWU6"
    "IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNhdmUgY3VycmVudCBzZXNzaW9uIHRvIHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwu"
    "CiAgICAgICAgT3ZlcndyaXRlcyB0aGUgZmlsZSBmb3IgdG9kYXkg4oCUIGVhY2ggc2F2ZSBpcyBhIGZ1bGwgc25hcHNob3QuCiAgICAgICAgVXBkYXRlcyBz"
    "ZXNzaW9uX2luZGV4Lmpzb24uCiAgICAgICAgIiIiCiAgICAgICAgdG9kYXkgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBvdXRfcGF0aCA9"
    "IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3RvZGF5fS5qc29ubCIKCiAgICAgICAgIyBXcml0ZSBhbGwgbWVzc2FnZXMKICAgICAgICB3cml0ZV9qc29ubChv"
    "dXRfcGF0aCwgc2VsZi5fbWVzc2FnZXMpCgogICAgICAgICMgVXBkYXRlIGluZGV4CiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAg"
    "ICBleGlzdGluZyA9IG5leHQoCiAgICAgICAgICAgIChzIGZvciBzIGluIGluZGV4WyJzZXNzaW9ucyJdIGlmIHNbImRhdGUiXSA9PSB0b2RheSksIE5vbmUK"
    "ICAgICAgICApCgogICAgICAgIG5hbWUgPSBhaV9nZW5lcmF0ZWRfbmFtZSBvciBleGlzdGluZy5nZXQoIm5hbWUiLCAiIikgaWYgZXhpc3RpbmcgZWxzZSAi"
    "IgogICAgICAgIGlmIG5vdCBuYW1lIGFuZCBzZWxmLl9tZXNzYWdlczoKICAgICAgICAgICAgIyBBdXRvLW5hbWUgZnJvbSBmaXJzdCB1c2VyIG1lc3NhZ2Ug"
    "KGZpcnN0IDUgd29yZHMpCiAgICAgICAgICAgIGZpcnN0X3VzZXIgPSBuZXh0KAogICAgICAgICAgICAgICAgKG1bImNvbnRlbnQiXSBmb3IgbSBpbiBzZWxm"
    "Ll9tZXNzYWdlcyBpZiBtWyJyb2xlIl0gPT0gInVzZXIiKSwKICAgICAgICAgICAgICAgICIiCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29yZHMgPSBm"
    "aXJzdF91c2VyLnNwbGl0KClbOjVdCiAgICAgICAgICAgIG5hbWUgID0gIiAiLmpvaW4od29yZHMpIGlmIHdvcmRzIGVsc2UgZiJTZXNzaW9uIHt0b2RheX0i"
    "CgogICAgICAgIGVudHJ5ID0gewogICAgICAgICAgICAiZGF0ZSI6ICAgICAgICAgIHRvZGF5LAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAgIHNlbGYu"
    "X3Nlc3Npb25faWQsCiAgICAgICAgICAgICJuYW1lIjogICAgICAgICAgbmFtZSwKICAgICAgICAgICAgIm1lc3NhZ2VfY291bnQiOiBsZW4oc2VsZi5fbWVz"
    "c2FnZXMpLAogICAgICAgICAgICAiZmlyc3RfbWVzc2FnZSI6IChzZWxmLl9tZXNzYWdlc1swXVsidGltZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgICAgICJsYXN0X21lc3NhZ2UiOiAgKHNlbGYuX21lc3NhZ2VzWy0xXVsidGlt"
    "ZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgfQoKICAgICAgICBpZiBl"
    "eGlzdGluZzoKICAgICAgICAgICAgaWR4ID0gaW5kZXhbInNlc3Npb25zIl0uaW5kZXgoZXhpc3RpbmcpCiAgICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJd"
    "W2lkeF0gPSBlbnRyeQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdLmluc2VydCgwLCBlbnRyeSkKCiAgICAgICAgIyBLZWVw"
    "IGxhc3QgMzY1IGRheXMgaW4gaW5kZXgKICAgICAgICBpbmRleFsic2Vzc2lvbnMiXSA9IGluZGV4WyJzZXNzaW9ucyJdWzozNjVdCiAgICAgICAgc2VsZi5f"
    "c2F2ZV9pbmRleChpbmRleCkKCiAgICAjIOKUgOKUgCBMT0FEIC8gSk9VUk5BTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBsaXN0X3Nlc3Npb25zKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiUmV0dXJuIGFsbCBzZXNzaW9ucyBm"
    "cm9tIGluZGV4LCBuZXdlc3QgZmlyc3QuIiIiCiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRfaW5kZXgoKS5nZXQoInNlc3Npb25zIiwgW10pCgogICAgZGVm"
    "IGxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBhIHBhc3Qg"
    "c2Vzc2lvbiBhcyBhIGNvbnRleHQgaW5qZWN0aW9uIHN0cmluZy4KICAgICAgICBSZXR1cm5zIGZvcm1hdHRlZCB0ZXh0IHRvIHByZXBlbmQgdG8gdGhlIHN5"
    "c3RlbSBwcm9tcHQuCiAgICAgICAgVGhpcyBpcyBOT1QgcmVhbCBtZW1vcnkg4oCUIGl0J3MgYSB0ZW1wb3JhcnkgY29udGV4dCB3aW5kb3cgaW5qZWN0aW9u"
    "CiAgICAgICAgdW50aWwgdGhlIFBoYXNlIDIgbWVtb3J5IHN5c3RlbSBpcyBidWlsdC4KICAgICAgICAiIiIKICAgICAgICBwYXRoID0gc2VsZi5fc2Vzc2lv"
    "bnNfZGlyIC8gZiJ7c2Vzc2lvbl9kYXRlfS5qc29ubCIKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuICIiCgogICAg"
    "ICAgIG1lc3NhZ2VzID0gcmVhZF9qc29ubChwYXRoKQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gc2Vzc2lvbl9kYXRlCgogICAgICAgIGxpbmVz"
    "ID0gW2YiW0pPVVJOQUwgTE9BREVEIOKAlCB7c2Vzc2lvbl9kYXRlfV0iLAogICAgICAgICAgICAgICAgICJUaGUgZm9sbG93aW5nIGlzIGEgcmVjb3JkIG9m"
    "IGEgcHJpb3IgY29udmVyc2F0aW9uLiIsCiAgICAgICAgICAgICAgICAgIlVzZSB0aGlzIGFzIGNvbnRleHQgZm9yIHRoZSBjdXJyZW50IHNlc3Npb246XG4i"
    "XQoKICAgICAgICAjIEluY2x1ZGUgdXAgdG8gbGFzdCAzMCBtZXNzYWdlcyBmcm9tIHRoYXQgc2Vzc2lvbgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXNb"
    "LTMwOl06CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgIj8iKS51cHBlcigpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJj"
    "b250ZW50IiwgIiIpWzozMDBdCiAgICAgICAgICAgIHRzICAgICAgPSBtc2cuZ2V0KCJ0aW1lc3RhbXAiLCAiIilbOjE2XQogICAgICAgICAgICBsaW5lcy5h"
    "cHBlbmQoZiJbe3RzfV0ge3JvbGV9OiB7Y29udGVudH0iKQoKICAgICAgICBsaW5lcy5hcHBlbmQoIltFTkQgSk9VUk5BTF0iKQogICAgICAgIHJldHVybiAi"
    "XG4iLmpvaW4obGluZXMpCgogICAgZGVmIGNsZWFyX2xvYWRlZF9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwg"
    "PSBOb25lCgogICAgQHByb3BlcnR5CiAgICBkZWYgbG9hZGVkX2pvdXJuYWxfZGF0ZShzZWxmKSAtPiBPcHRpb25hbFtzdHJdOgogICAgICAgIHJldHVybiBz"
    "ZWxmLl9sb2FkZWRfam91cm5hbAoKICAgIGRlZiByZW5hbWVfc2Vzc2lvbihzZWxmLCBzZXNzaW9uX2RhdGU6IHN0ciwgbmV3X25hbWU6IHN0cikgLT4gYm9v"
    "bDoKICAgICAgICAiIiJSZW5hbWUgYSBzZXNzaW9uIGluIHRoZSBpbmRleC4gUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIiIiCiAgICAgICAgaW5kZXggPSBz"
    "ZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBmb3IgZW50cnkgaW4gaW5kZXhbInNlc3Npb25zIl06CiAgICAgICAgICAgIGlmIGVudHJ5WyJkYXRlIl0gPT0g"
    "c2Vzc2lvbl9kYXRlOgogICAgICAgICAgICAgICAgZW50cnlbIm5hbWUiXSA9IG5ld19uYW1lWzo4MF0KICAgICAgICAgICAgICAgIHNlbGYuX3NhdmVfaW5k"
    "ZXgoaW5kZXgpCiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgICMg4pSA4pSAIElOREVYIEhFTFBFUlMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfaW5kZXgoc2VsZikgLT4gZGlj"
    "dDoKICAgICAgICBpZiBub3Qgc2VsZi5faW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKAogICAgICAgICAgICAgICAgc2VsZi5faW5kZXhfcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0"
    "Zi04IikKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CgogICAgZGVm"
    "IF9zYXZlX2luZGV4KHNlbGYsIGluZGV4OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2luZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAg"
    "anNvbi5kdW1wcyhpbmRleCwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoKCiMg4pSA4pSAIExFU1NPTlMgTEVBUk5FRCBEQVRBQkFT"
    "RSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc0xlYXJuZWREQjoKICAg"
    "ICIiIgogICAgUGVyc2lzdGVudCBrbm93bGVkZ2UgYmFzZSBmb3IgY29kZSBsZXNzb25zLCBydWxlcywgYW5kIHJlc29sdXRpb25zLgoKICAgIENvbHVtbnMg"
    "cGVyIHJlY29yZDoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZW52aXJvbm1lbnQgKExTTHxQeXRob258UHlTaWRlNnwuLi4pLCBsYW5ndWFnZSwKICAgICAg"
    "ICByZWZlcmVuY2Vfa2V5IChzaG9ydCB1bmlxdWUgdGFnKSwgc3VtbWFyeSwgZnVsbF9ydWxlLAogICAgICAgIHJlc29sdXRpb24sIGxpbmssIHRhZ3MKCiAg"
    "ICBRdWVyaWVkIEZJUlNUIGJlZm9yZSBhbnkgY29kZSBzZXNzaW9uIGluIHRoZSByZWxldmFudCBsYW5ndWFnZS4KICAgIFRoZSBMU0wgRm9yYmlkZGVuIFJ1"
    "bGVzZXQgbGl2ZXMgaGVyZS4KICAgIEdyb3dpbmcsIG5vbi1kdXBsaWNhdGluZywgc2VhcmNoYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "KToKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibGVzc29uc19sZWFybmVkLmpzb25sIgoKICAgIGRlZiBhZGQoc2VsZiwg"
    "ZW52aXJvbm1lbnQ6IHN0ciwgbGFuZ3VhZ2U6IHN0ciwgcmVmZXJlbmNlX2tleTogc3RyLAogICAgICAgICAgICBzdW1tYXJ5OiBzdHIsIGZ1bGxfcnVsZTog"
    "c3RyLCByZXNvbHV0aW9uOiBzdHIgPSAiIiwKICAgICAgICAgICAgbGluazogc3RyID0gIiIsIHRhZ3M6IGxpc3QgPSBOb25lKSAtPiBkaWN0OgogICAgICAg"
    "IHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICBmImxlc3Nvbl97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJj"
    "cmVhdGVkX2F0IjogICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAicGVyc29uYSI6ICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImVudmly"
    "b25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXki"
    "OiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9y"
    "dWxlLAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAgICAg"
    "ICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkp"
    "OgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYs"
    "IHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06"
    "CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQog"
    "ICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9"
    "IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdl"
    "IiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAg"
    "ICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5n"
    "ZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAi"
    "LmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoK"
    "ICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVm"
    "IGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwg"
    "cmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZv"
    "ciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAg"
    "IGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1h"
    "eF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBh"
    "IGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIi"
    "IgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAg"
    "ICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5Jywn"
    "Jyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFw"
    "cGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxp"
    "Y2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9r"
    "ZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAg"
    "ICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVs"
    "ZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0"
    "YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5"
    "IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0"
    "ZXJuYXJ5IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRz"
    "LiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAg"
    "ICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAg"
    "ICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBp"
    "bmRleCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTog"
    "Zm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR0xP"
    "QkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwK"
    "ICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAg"
    "IkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRl"
    "IGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBoYW5k"
    "bGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAg"
    "Ik5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1"
    "cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAg"
    "ICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5v"
    "dCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAg"
    "ICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBv"
    "ciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBh"
    "cnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxsIHNjcmlwdCBtdXN0IGJl"
    "IGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAg"
    "ICAgIF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAg"
    "ICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAg"
    "ICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdl"
    "cjoKICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25s"
    "CgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAg"
    "ICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwg"
    "cmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50"
    "X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1"
    "ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5"
    "CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10"
    "cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tz"
    "Lmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwo"
    "c2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAg"
    "ICAgICAgaWYgbm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0Ogog"
    "ICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAg"
    "ICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVl"
    "X2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAg"
    "ICAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0"
    "KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAg"
    "dC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2Up"
    "CiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2"
    "ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRk"
    "ZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28o"
    "KSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQu"
    "Z2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAg"
    "ICAgICAgICAgICAgICAgICBwcmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHBy"
    "ZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVk"
    "LmFwcGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3JtYWxpemVkKQogICAgICAgIHJl"
    "dHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9"
    "ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAg"
    "ICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9j"
    "YWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAg"
    "ICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAg"
    "ICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6"
    "ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAg"
    "ICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjog"
    "ICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJw"
    "ZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAg"
    "ICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9z"
    "dGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAt"
    "PiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0"
    "LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25vd2xlZGdl"
    "ZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2Fs"
    "bCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3Ry"
    "KSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBp"
    "ZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAgICAg"
    "ICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgog"
    "ICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tf"
    "aWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQi"
    "XSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAg"
    "cmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIGtlcHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVk"
    "IiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAg"
    "c2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIs"
    "IHN5bmNfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3Ig"
    "dCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0gICAgPSBz"
    "eW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xl"
    "X2V2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xlX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBl"
    "cnJvcjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiXVsi"
    "Z29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0"
    "dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBD"
    "aGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNr"
    "KSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBw"
    "bGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAg"
    "ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzID0gW10KICAgICAg"
    "ICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAg"
    "IGR1ZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2Fs"
    "KHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3JldHJ5X2F0"
    "IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFBy"
    "ZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBh"
    "bmQgbm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAg"
    "ICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgICMgRHVlIHRyaWdn"
    "ZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVz"
    "Il0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2FsX25vd19pc28oKQogICAg"
    "ICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSAr"
    "IHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBldmVu"
    "dHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBu"
    "b3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5l"
    "eHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikK"
    "ICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFu"
    "ZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAg"
    "ICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkpICsgMQogICAgICAgICAgICAg"
    "ICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9"
    "ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAg"
    "KS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAgICAg"
    "ICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hhbmdlZDoK"
    "ICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTog"
    "c3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29t"
    "cGFyaXNvbi4iIiIKICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQog"
    "ICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA"
    "4pSAIE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lm"
    "eV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1l"
    "ci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCBy"
    "ZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMq"
    "KD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQs"
    "IGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJc"
    "YnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9c"
    "cyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpc"
    "cythbj8pP1xzK2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xi"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1w"
    "b3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9"
    "ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9"
    "ICJyZW1pbmRlciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0g"
    "InRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVudCwgImNsZWFu"
    "ZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtk"
    "YXRldGltZV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAg"
    "ICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAi"
    "YXQgMTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1w"
    "b3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFgg"
    "bWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8"
    "ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgx"
    "KSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWlu"
    "dXRlcz1uKQogICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAg"
    "ICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDog"
    "cmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5z"
    "ZWFyY2goCiAgICAgICAgICAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAg"
    "ICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3Vw"
    "KDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAxMgog"
    "ICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0"
    "ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgICAgIGR0ICs9IHRpbWVkZWx0YShk"
    "YXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAg"
    "ICAgIGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgp"
    "CiAgICAgICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJF"
    "TUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVp"
    "cmVtZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBy"
    "dW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0g"
    "UGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToK"
    "ICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxs"
    "IHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9z"
    "YXZlLCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHlnYW1l"
    "CgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZl"
    "cywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGludGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3Ms"
    "IEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2Nh"
    "bCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBsb2Nh"
    "bCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1v"
    "bml0b3JpbmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoi"
    "IiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBT"
    "ZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZp"
    "cnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2Vz"
    "CiMgKFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGlj"
    "c1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBB"
    "U1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVkIGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5"
    "bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBi"
    "b2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgICDigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFj"
    "a2VyVGFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9E"
    "b2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKA"
    "lCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0"
    "ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3dz"
    "ZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKUgOKU"
    "gCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYg"
    "X2dvdGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tncm91"
    "bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAg"
    "ICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tn"
    "cm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdl"
    "dDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0"
    "aW9uIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgICAgICAgICBsZXR0ZXIt"
    "c3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIKCmRlZiBfZ290aGljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1"
    "dHRvbjoKICAgIGJ0biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05f"
    "RElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRvb2x0"
    "aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJs"
    "ZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBT"
    "Q0FOUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMg"
    "bWFuYWdlci4KICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAgICAtIEFkZCAod2l0"
    "aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQg"
    "bmFtZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0g"
    "UmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBib2FyZCBv"
    "biBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2VsZi5f"
    "cmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0"
    "dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg"
    "QnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwg"
    "ICAgICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxlY3Rl"
    "ZCBzY2FuIGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2Nh"
    "biIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAgICAg"
    "IHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNjYW4iKQogICAg"
    "ICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAgICAg"
    "c2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5fYnRuX21vZGlmeSwK"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRuX3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAg"
    "ICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBk"
    "aXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ss"
    "IDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAw"
    "KQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAg"
    "ICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYu"
    "X2NhcmRfbGF5b3V0ICAgID0gUVZCb3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0"
    "cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc2Vs"
    "Zi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAgICAg"
    "ICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYu"
    "X2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2Fk"
    "ZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFU"
    "ZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX2Rlc2Mp"
    "CiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3Jh"
    "dyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3RlIHRoZSByYXcgU2Vj"
    "b25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBp"
    "dGVtcyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAjIFByZXZpZXcgb2YgcGFy"
    "c2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRk"
    "X3ByZXZpZXcgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIs"
    "ICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAg"
    "ICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "TWF4aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3Bh"
    "cnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRu"
    "KCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6"
    "IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQoYzEpOyBidG5zMS5h"
    "ZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKU"
    "gCBQQUdFIDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBs"
    "MiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBR"
    "TGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZvbnQt"
    "c2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNl"
    "bGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9y"
    "aXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNl"
    "bGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQog"
    "ICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0"
    "X21lbnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAg"
    "ICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRlbSB0byBj"
    "b3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlfaGlu"
    "dCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2su"
    "c2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAj"
    "IOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMyA9IFFXaWRnZXQoKQog"
    "ICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2lu"
    "Zyg0KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQog"
    "ICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkK"
    "ICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lk"
    "Z2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAg"
    "MSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMyA9"
    "IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fbW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAg"
    "IGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91dChidG5zMykK"
    "ICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6"
    "IHN0cikgLT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQgaW50byAoYXZhdGFy"
    "X25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAg"
    "ICAgICAgdGltZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0OgogICAgICAgICAg"
    "ICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBD"
    "UkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJu"
    "ICJVTktOT1dOIiwgW10KCiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0YW1wcyDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAg"
    "ICAgICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAg"
    "U3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGlu"
    "ZXM6CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFyY2go"
    "CiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAg"
    "ICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9"
    "IFtdCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVudCA9"
    "IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIgaW4g"
    "Y29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVj"
    "dCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBv"
    "bmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9"
    "IGNvbnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5lCgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6"
    "IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRv"
    "cl9tYXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3JlLkkK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91"
    "cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAgICAgICAg"
    "ICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5zdWIocidc"
    "cypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAg"
    "ICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkgPiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1f"
    "bmFtZSwgImNyZWF0b3IiOiBjcmVhdG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA4pSAIENBUkQgUkVOREVSSU5H"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF9jYXJkcyhzZWxmKSAtPiBOb25l"
    "OgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4g"
    "MToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAg"
    "ICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9IHNl"
    "bGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRf"
    "bGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAg"
    "ICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAg"
    "ICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAi"
    "CiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICBs"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIp"
    "KQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2Ug"
    "Q19HT0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKCiAgICAgICAgY291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsKGYie2Nv"
    "dW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6"
    "IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwocmVjLmdldCgiY3Jl"
    "YXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChuYW1lX2xi"
    "bCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNp"
    "bmcoMTIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBzZWxlY3QKICAgICAgICByZWNfaWQgPSByZWMu"
    "Z2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2Fy"
    "ZChyaWQpCiAgICAgICAgcmV0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhpZ2hs"
    "aWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAo"
    "ciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAg"
    "ICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pz"
    "b25sKHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZv"
    "ciByIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgICAgICAgICAgICByWyJyZWNvcmRfaWQi"
    "XSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAg"
    "ICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYu"
    "X3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2FkZF9y"
    "YXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNl"
    "dFBsYWNlaG9sZGVyVGV4dChuYW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoy"
    "MF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRk"
    "X3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRl"
    "bSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRl"
    "ZiBfc2hvd19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRk"
    "X3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgo"
    "MSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1l"
    "LCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkK"
    "ICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6"
    "ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgIm5h"
    "bWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9hZGRfZGVzYy50b1BsYWluVGV4dCgp"
    "WzoyNDRdLAogICAgICAgICAgICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3Jl"
    "YXRlZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVj"
    "b3JkKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRbInJl"
    "Y29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYu"
    "X3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5z"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRleHQo"
    "cmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5n"
    "ZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5p"
    "bnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0"
    "LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJ"
    "dGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2Nv"
    "bnRleHRfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBvcykKICAgICAgICBpZiBub3Qg"
    "aWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAw"
    "KSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90"
    "YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9t"
    "IFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBJdGVtIE5hbWUiKQogICAgICAgIGFfY3JlYXRv"
    "ciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJvdGgiKQogICAgICAg"
    "IGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlv"
    "bi5jbGlwYm9hcmQoKQogICAgICAgIGlmIGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0aW9uID09"
    "IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDi"
    "gJQge2NyZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkK"
    "ICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUu"
    "c2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAg"
    "ICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0g"
    "c2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9tb2Rf"
    "dGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYu"
    "X21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAg"
    "ICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9"
    "IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAg"
    "ID0gc2VsZi5fbW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9kX2Rlc2Mu"
    "dGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAg"
    "ICAgICAgaXQgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBjciAgPSAo"
    "c2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0i"
    "OiBpdC5zdHJpcCgpIG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkK"
    "ICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5p"
    "c29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYg"
    "X2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAg"
    "ICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVj"
    "dCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAg"
    "ICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25h"
    "bWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAg"
    "c2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lk"
    "IikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNl"
    "bGYuX3NlbGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "c2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdl"
    "Qm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJObyByYXcgdGV4dCBzdG9yZWQg"
    "Zm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAg"
    "ICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lCiAgICAgICAgcmVjWyJ1"
    "cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xD"
    "b21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5"
    "bGluZy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRz"
    "Lmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENv"
    "bnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "c2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBNb2Rp"
    "ZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3Ro"
    "aWNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJDb3B5IHNlbGVjdGVkIGNvbW1hbmQg"
    "dG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYWRk"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQog"
    "ICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAg"
    "Zm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9j"
    "b3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250"
    "YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRh"
    "bEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3Mp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3Ro"
    "aWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAgICAgICAg"
    "ICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAg"
    "ICAgIGhpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAg"
    "Zm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5p"
    "bnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0"
    "KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJl"
    "Yy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUu"
    "Y3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAw"
    "KQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9f"
    "YWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQog"
    "ICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5"
    "b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNt"
    "ZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dv"
    "dGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNs"
    "aWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRS"
    "b3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUu"
    "bm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQu"
    "dXVpZDQoKSksCiAgICAgICAgICAgICAgICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3Jp"
    "cHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5vdywK"
    "ICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAg"
    "ICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciBy"
    "b3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcg"
    "PSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGlu"
    "ZUVkaXQocmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBm"
    "b3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5j"
    "b25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lk"
    "Z2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAg"
    "ICAgICAgICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBk"
    "ZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zv"
    "cm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9y"
    "IHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1h"
    "bmQiLCJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRl"
    "bGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5v"
    "CiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5w"
    "b3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg"
    "4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBG"
    "dWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4K"
    "ICAgIE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVj"
    "dGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0"
    "ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJh"
    "Y2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAg"
    "ICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3Qg"
    "PSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQp"
    "CgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAgc2VsZi5f"
    "YnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAgPSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0"
    "bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZl"
    "ZCBhcHBsaWNhdGlvbnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fdG9nZ2xl"
    "ID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAg"
    "Zm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdW5o"
    "aWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAg"
    "Yi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAg"
    "ICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYuX2J0bl91"
    "bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19k"
    "ZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhw"
    "b3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikK"
    "CiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRh"
    "bEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkg"
    "YW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQog"
    "ICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDi"
    "gJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNl"
    "dFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoNCwg"
    "ODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0"
    "cmV0Y2gpCgogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25C"
    "ZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNl"
    "bGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAg"
    "ICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdldCgi"
    "aGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBz"
    "dGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAg"
    "ICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJl"
    "Yy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3RhdHVzLAogICAg"
    "ICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAg"
    "ICAgICAgICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAgICAgICAgICAgICAg"
    "ICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRlbSkK"
    "ICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0o"
    "ciwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5k"
    "ZXgocmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0"
    "KCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFibGUuaXRl"
    "bShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAgICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFS"
    "b2xlLlVzZXJSb2xlKQogICAgICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAg"
    "ICAgICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06CiAg"
    "ICAgICAgZGxnICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZv"
    "cm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNlICIiKQog"
    "ICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRl"
    "RWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAg"
    "IGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBw"
    "bGllZCJdLCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQogICAgICAgIGxp"
    "bmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgi"
    "c3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikg"
    "aWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBU"
    "aXRsZToiLCB0aXRsZSksCiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAgICAgICAgICAoIlN0YXR1czoi"
    "LCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBi"
    "dG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBv"
    "ay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsg"
    "YnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUu"
    "QWNjZXB0ZWQ6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAoKSwKICAg"
    "ICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRl"
    "KCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAg"
    "bm90ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0"
    "aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgp"
    "KSwKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6IE5vbmUsCiAgICAgICAgICAgICJj"
    "cmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5h"
    "cHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9k"
    "b19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMpICE9IDE6"
    "CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAi"
    "U2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZHhzWzBd"
    "XQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUo"
    "cCkKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwo"
    "c2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBs"
    "ZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAg"
    "ICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVm"
    "IF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4"
    "IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yyku"
    "aXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAg"
    "ICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYs"
    "ICJEZWxldGUiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAog"
    "ICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAg"
    "ICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IHNldChpZHhzKQogICAgICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBub3Qg"
    "aW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAg"
    "IGRlZiBfdG9nZ2xlX2hpZGRlbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAg"
    "ICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKY"
    "vSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcGF0aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAg"
    "ICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1RhYiBE"
    "ZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBp"
    "ZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNlICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBw"
    "bGllZCIsImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBv"
    "cGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhlYWRlcikg"
    "KyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAg"
    "IHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgic3RhdHVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICAgICAgICAgICAgICAg"
    "ICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAg"
    "ICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAgc3RyKHYpLnJlcGxhY2UoIlxuIiwiICIp"
    "LnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAgIGZvciB2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFN"
    "ZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0i"
    "KQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0Rv"
    "Y3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgog"
    "ICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAg"
    "ICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5wYXRoX2xhYmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBm"
    "aWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJV"
    "bnRpdGxlZCIKICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG1pbWUg"
    "PT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYg"
    "bWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVkVGlt"
    "ZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiAr"
    "IChmIiAgICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAg"
    "ICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJ"
    "dGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikK"
    "CgpjbGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIKCiAg"
    "ICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAg"
    "b25fY29tcGxldGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAgb25f"
    "cHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5j"
    "ZWwsCiAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4gPSBv"
    "bl9hZGRfZWRpdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5f"
    "b25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21w"
    "bGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdl"
    "ZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRv"
    "cl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9z"
    "aG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRl"
    "ZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "bm9ybWFsX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2Fk"
    "ZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2Zp"
    "bHRlcl9jb21iby5hZGRJdGVtKCJXRUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEgiLCAibW9udGgi"
    "KQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRh"
    "c2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5zZXRDdXJyZW50SW5kZXgoMikK"
    "ICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29u"
    "X2ZpbHRlcl9jaGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgKQogICAgICAg"
    "IGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9y"
    "bWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBz"
    "ZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYu"
    "dGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhv"
    "cml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAg"
    "c2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gp"
    "CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2Rl"
    "LlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNl"
    "bGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAgICAgIG5vcm1h"
    "bF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9h"
    "ZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0bigi"
    "Q09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAg"
    "c2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVk"
    "ID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9hZGRfZWRpdG9yX29wZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2Vs"
    "ZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBzZWxm"
    "LmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2Nv"
    "bXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxl"
    "ZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogICAgICAgICAgICBz"
    "ZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNl"
    "bF90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAgICAg"
    "ICAgKToKICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAg"
    "c2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAgZWRpdG9yX2xheW91dCA9"
    "IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9s"
    "YXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09H"
    "TEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBz"
    "YXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIK"
    "ICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQog"
    "ICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBs"
    "YWNlaG9sZGVyVGV4dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "RW5kIERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQog"
    "ICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBs"
    "YWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3go"
    "IkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0"
    "UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3"
    "aWRnZXQgaW4gKAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSwKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX25v"
    "dGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAg"
    "ICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3Nh"
    "dmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRX"
    "aWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3Ry"
    "ZXRjaCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdp"
    "ZGdldChlZGl0b3IpCgogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dvcmtzcGFjZSA9IGVkaXRv"
    "cgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2Fj"
    "dGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tfaWRzKCkpCiAgICAgICAg"
    "c2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVk"
    "KQoKICAgIGRlZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQogICAgICAgIGZvciBy"
    "IGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAw"
    "KQogICAgICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90IHN0YXR1c19p"
    "dGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1E"
    "YXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVu"
    "ZCh0YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMKCiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3Rh"
    "YmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgi"
    "c3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwg"
    "ImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAg"
    "ICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2Ug"
    "PSAodGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0"
    "YXR1c19pY29ufSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNrLmdldCgi"
    "aWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "LnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxl"
    "V2lkZ2V0SXRlbSh0ZXh0KSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkpCiAg"
    "ICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rp"
    "b25fYnV0dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIg"
    "PSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBp"
    "cyBub3QgTm9uZSBhbmQgaGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAgICAgICAgICBzZWxmLl9kaWFn"
    "KAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17cmVhc29u"
    "IG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MK"
    "ICAgICAgICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3Bf"
    "cmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50"
    "KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBs"
    "ZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRleHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9z"
    "aG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVBMRVRFRCIpCgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNl"
    "KSAtPiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19s"
    "YWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgog"
    "ICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLmVkaXRv"
    "cl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRX"
    "aWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBkaWFs"
    "b2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAg"
    "UG9JIGxpc3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYWwgbG9hZCBub3Rp"
    "ZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVy"
    "KCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYu"
    "X2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBo"
    "ZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAg"
    "ICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxh"
    "eS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6"
    "ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5k"
    "KHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06"
    "JVMiKQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19QVVJQ"
    "TEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAg"
    "IlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAg"
    "ICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+"
    "JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWln"
    "aHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xE"
    "fTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGlj"
    "YWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkK"
    "CiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUg"
    "ZGV0ZWN0aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVzLCB0aW1l"
    "ciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBB"
    "bHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290"
    "aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRS"
    "ZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsg"
    "Y29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1p"
    "bHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZP"
    "IikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9"
    "IHsKICAgICAgICAgICAgIklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAgICAgICJXQVJOIjogIENfR09M"
    "RCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3Ig"
    "PSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxz"
    "cGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntj"
    "b2xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAg"
    "ICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1l"
    "c3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAg"
    "bHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKclyIgaW4gbXNnOiAgbHZs"
    "ID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2cs"
    "IGx2bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRBQiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJv"
    "d3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNM"
    "ZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgogICAgICAgIHNl"
    "bGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3NvbnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNv"
    "bWJvQm94KCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVj"
    "dChzZWxmLnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAg"
    "IGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAg"
    "ICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmls"
    "dGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9"
    "IF9nb3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRk"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIGJ0"
    "bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJv"
    "bm1lbnQiXQogICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAg"
    "IDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAg"
    "UUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9y"
    "cyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1T"
    "ZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwK"
    "ICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFi"
    "bGUpCgogICAgICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQgPSBRVkJv"
    "eExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWls"
    "X2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRn"
    "ZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRp"
    "dF9ydWxlID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9i"
    "dG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9l"
    "ZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNl"
    "dEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUp"
    "CiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRh"
    "aWxfaGVhZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVlKQogICAg"
    "ICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAg"
    "ICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAg"
    "ICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFpbF93aWRnZXQpCiAgICAgICAg"
    "c3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3Jkczog"
    "bGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9"
    "ICIiIGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1s"
    "YW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0g"
    "c2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRl"
    "bShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAgICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkp"
    "CgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZWxmLl9l"
    "ZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRz"
    "W3Jvd10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxu"
    "XG4iICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9uIikg"
    "ZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0"
    "bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcp"
    "CiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVkaXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoK"
    "ICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250"
    "ZW50IG9uIGNhbmNlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICByb3cgPSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0ID0gc2Vs"
    "Zi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAg"
    "ICAgICBpZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIs"
    "IDEpCiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFdLnN0"
    "cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2Vs"
    "Zi5fcmVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxf"
    "cnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0"
    "V2luZG93VGl0bGUoIkFkZCBMZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9"
    "OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGluZUVkaXQo"
    "IkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYgID0gUUxpbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0"
    "KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0KCkKICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQo"
    "KQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwg"
    "KCJMYW5ndWFnZToiLCBsYW5nKSwKICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBzdW1tKSwKICAgICAgICAgICAg"
    "KCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAgICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAg"
    "ICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7"
    "IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxn"
    "LnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAg"
    "aWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAgIGVu"
    "dmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAg"
    "ICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgp"
    "LAogICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8"
    "IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBs"
    "eSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAgICAgICAgICAgICAgIkRlbGV0ZSB0"
    "aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VC"
    "b3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUg"
    "VFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sg"
    "cGxhbm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1lLCBTdGF0dXMs"
    "IERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5h"
    "bGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIHRv"
    "IGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIsICJSZWFkeSB0byBC"
    "dWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3Vp"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRp"
    "dCIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0"
    "bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNl"
    "bGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBzZWxmLl9i"
    "dG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAg"
    "ICAgYnRuX2Jhci5hZGRXaWRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAg"
    "ICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fZWRpdCkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2V4"
    "cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2lt"
    "cG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9y"
    "aXpvbnRhbEhlYWRlckxhYmVscyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9y"
    "aXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9k"
    "ZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJh"
    "Y3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlv"
    "bkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5Pcmll"
    "bnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBu"
    "b3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNl"
    "bGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAg"
    "ICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVz"
    "X2Rpc3BsYXkpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBdKQog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVs"
    "KCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "OXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291bnRfbGJsKQoK"
    "ICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0Nv"
    "dW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lk"
    "Z2V0SXRlbShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIs"
    "ICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICAgICAiSWRl"
    "YSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICAgICAiRGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAg"
    "ICAiUmVhZHkgdG8gQnVpbGQiOiAgIENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIsCiAgICAgICAgICAg"
    "ICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAg"
    "ICAgICAgICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwK"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAg"
    "ICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNvdW50"
    "c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5p"
    "dGVtcygpKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAgIHtjb3Vu"
    "dF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3co"
    "KQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAg"
    "ICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJs"
    "ZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxv"
    "ZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBkZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAt"
    "MSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxz"
    "ZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7"
    "Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVs"
    "ZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk1v"
    "ZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNF"
    "UykKICAgICAgICBpZiByZWM6CiAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAg"
    "ICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAgc3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmllbGQg"
    "PSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5U"
    "ZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAg"
    "ICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQu"
    "c2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAog"
    "ICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAg"
    "ICAoIk5vdGVzOiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAgICAgICBs"
    "YmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkwKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwp"
    "CiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAg"
    "YnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290"
    "aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQu"
    "Y29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5j"
    "ZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6"
    "CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBp"
    "ZiByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAg"
    "ICAgICAgICAgICAgICAic3RhdHVzIjogICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRl"
    "c2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNl"
    "IGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAg"
    "ICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93"
    "ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5hbWUgPSBz"
    "ZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAg"
    "ICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwK"
    "ICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5w"
    "b3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhw"
    "b3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1l"
    "Lm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0Igog"
    "ICAgICAgICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAgICAgICAg"
    "ICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90YWwgbW9k"
    "dWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQog"
    "ICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAgIGYi"
    "TU9EVUxFOiB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAg"
    "ICAgICAgICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAg"
    "ICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiIiwK"
    "ICAgICAgICAgICAgICAgICAgICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9w"
    "YXRoLndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNl"
    "dFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0"
    "ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xpcGJvYXJk"
    "LiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiRXhw"
    "b3J0IEVycm9yIiwgc3RyKGUpKQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJv"
    "bSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4iIiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJJbXBv"
    "cnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAg"
    "ICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwo"
    "CiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93LlxuIgogICAgICAgICAgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1v"
    "ZHVsZSBuYW1lLiIKICAgICAgICApKQogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3JvdyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRu"
    "KCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChk"
    "bGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAg"
    "IGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAg"
    "ICAgIHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICAgICAgbGluZXMgPSByYXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVtcHR5IGxpbmUgPSBuYW1lCiAgICAgICAgICAg"
    "IG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RyaXAoKToKICAgICAgICAgICAgICAg"
    "ICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAg"
    "ICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAg"
    "ICAgInN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAg"
    "ICByYXcsCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmll"
    "ZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMp"
    "CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAg"
    "UEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVsZXRlIGFkZGVk"
    "LCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9h"
    "cmQgY29udGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJhY2tlclRhYjog"
    "ZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBm"
    "b3IgaWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIGxldmVsLWNvbG9y"
    "ZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQ"
    "YXNzIDYg4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAg"
    "ZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMKIyBD"
    "b250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAg"
    "Rmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGViYXIgICAgICAg"
    "IOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFX"
    "QUtFIC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4gd2luZG93LCBmdWxsIGxheW91dCwg"
    "YWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQoj"
    "IOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQ"
    "UkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkg"
    "LT4gTm9uZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVs"
    "eSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBw"
    "aXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGlj"
    "cyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBp"
    "dCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAg"
    "ICAgICAjIE5vIEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "aW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAg"
    "ICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVu"
    "OlxuXG4iCiAgICAgICAgICAgICAgICAiICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RFQ0tf"
    "TkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1C"
    "X0lDT05FUlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5v"
    "dCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5z"
    "dGFsbCBvdGhlciBtaXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAg"
    "ICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAg"
    "ICAgICAgICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRp"
    "bCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiksCiAgICAg"
    "ICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAg"
    "ICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAg"
    "IGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFw"
    "cGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cu"
    "YXBwZW5kKAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRh"
    "YmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1s"
    "b2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBp"
    "bXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9y"
    "dF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RT"
    "VFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEltcG9y"
    "dEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RT"
    "VFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1wb3J0IHN0"
    "aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJb"
    "OjIwMF19IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAg"
    "ICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgK"
    "ICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoKICAgICMg"
    "4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290"
    "c3RyYXBfbG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRl"
    "KCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IEZpcnN0UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0"
    "LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRp"
    "bmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShmIuKc"
    "piB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxm"
    "LnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tf"
    "TkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25D"
    "ZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZl"
    "c3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhp"
    "bmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhU"
    "X0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAg"
    "ICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKU"
    "gOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3Nl"
    "Y3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5f"
    "dHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1h"
    "IChsb2NhbCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAg"
    "IF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0"
    "aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRv"
    "bHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dz"
    "ZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdp"
    "ZGdldCgpCiAgICAgICAgbDEgPSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9v"
    "bGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikK"
    "ICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyBQYWdl"
    "IDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRl"
    "bnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQ"
    "bGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3"
    "b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFi"
    "ZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6"
    "IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMg"
    "UGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVy"
    "VGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxm"
    "Ll9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRX"
    "aWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2Fp"
    "X21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAgICAgICMg"
    "4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxmLl9idG5fdGVz"
    "dC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2Vs"
    "Zi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rl"
    "c3QpCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAg"
    "ICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3JvdyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRl"
    "clRleHQoCiAgICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAgICBi"
    "dG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAg"
    "ICBmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFk"
    "ZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVu"
    "ZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3No"
    "b3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5f"
    "YXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAg"
    "ICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "YWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0"
    "bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBf"
    "b25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBz"
    "ZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21v"
    "ZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAiU2Vs"
    "ZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxm"
    "Ll9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlh"
    "bG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgp"
    "IC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxm"
    "Ll9mYWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVy"
    "biBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0"
    "YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBs"
    "aWNhdGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNl"
    "CiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAg"
    "ICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3N0"
    "OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1l"
    "b3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5n"
    "IOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0g"
    "c2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIpKQog"
    "ICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXku"
    "IgoKICAgICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAg"
    "ICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29y"
    "cmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NS"
    "SU1TT04KICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBh"
    "bmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmln"
    "KCkKICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIs"
    "ICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAg"
    "ICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAg"
    "ICAgICAgIGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdi"
    "IgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAg"
    "ICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJh"
    "cGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29h"
    "aV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJz"
    "dF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgog"
    "ICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJBUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIo"
    "UVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZXNz"
    "aW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBC"
    "b2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlzdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBh"
    "IHRoaW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lv"
    "biB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNlc3Npb24KICAgICIiIgoKICAg"
    "IHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19p"
    "bml0X18oc2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0"
    "dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpvbnRh"
    "bCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBD"
    "b2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgdHNf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAgIHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkK"
    "ICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4LCAxOCkKICAg"
    "ICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEw"
    "cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICAgIyDilIDilIAgTWFpbiBjb250ZW50IOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmLl9jb250ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAgICAgIGNv"
    "bnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwg"
    "NCwgNCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5"
    "bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkK"
    "ICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRu"
    "KCLwn5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRvb2xUaXAoIkJy"
    "b3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1"
    "dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAg"
    "ICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAg"
    "IGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAgY29udGVudF9sYXlv"
    "dXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxh"
    "YmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6"
    "ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9s"
    "YmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJu"
    "YWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNl"
    "KQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAgIGNvbnRlbnRf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAg"
    "ICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19"
    "OyIpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAgICBjb250ZW50X2xheW91dC5h"
    "ZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09O"
    "X0RJTX07IH19IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9u"
    "X2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29u"
    "dGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xlIHN0cmlwIHRvIHRo"
    "ZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxm"
    "Ll90b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRl"
    "ZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIg"
    "aWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQo"
    "KQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xl"
    "YXIoKQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFtZSAg"
    "ICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQogICAgICAg"
    "ICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1jbGljayB0byBsb2FkIHNl"
    "c3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25f"
    "bmFtZShzZWxmLCBuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJOZXcgU2Vzc2lv"
    "biIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJm"
    "b250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAg"
    "ICJBdXRvc2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwg"
    "ZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikKICAg"
    "ICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNl"
    "KQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1dG9z"
    "YXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgz"
    "MDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "IyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBp"
    "dGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuY291bnQoKSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nl"
    "c3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1E"
    "YXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNz"
    "aW9uX2NsaWNrKHNlbGYsIGl0ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigpCgoKIyDilIDi"
    "lIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dn"
    "bGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkRFRAoKICAgIEFXQUtFICDigJQgbW9kZWwgbG9hZGVkLCBhdXRvLXRvcnBvciBkaXNhYmxlZCwgaWdub3JlcyBW"
    "UkFNIHByZXNzdXJlCiAgICBBVVRPICAg4oCUIG1vZGVsIGxvYWRlZCwgbW9uaXRvcnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3VzdGFpbmVk"
    "CiAgICBTVVNQRU5ERUQg4oCUIG1vZGVsIHVubG9hZGVkLCBzdGF5cyBzdXNwZW5kZWQgdW50aWwgbWFudWFsbHkgY2hhbmdlZAoKICAgIFNpZ25hbHM6CiAg"
    "ICAgICAgc3RhdGVfY2hhbmdlZChzdHIpICDigJQgIkFXQUtFIiB8ICJBVVRPIiB8ICJTVVNQRU5ERUQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFuZ2VkID0g"
    "U2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVOREVEIl0KCiAgICBTVEFURV9TVFlMRVMgPSB7CiAgICAgICAgIkFX"
    "QUtFIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250"
    "LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9y"
    "ZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAz"
    "cHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRv"
    "LXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAgIkFVVE8iOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzFh"
    "MTAwNTsgY29sb3I6ICNjYzg4MjI7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVz"
    "OiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwK"
    "ICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAg"
    "ICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3RpdmUuIEF1dG8tc3VzcGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAgfSwKICAgICAgICAiU1VT"
    "UEVOREVEIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6IHtDX1BVUlBMRV9ESU19OyBjb2xvcjoge0NfUFVSUExFfTsgIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BVUlBMRX07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjogICAgZiLimrAge1VJX1NVU1BFTlNJT05fTEFCRUwuc3RyaXAoKSBpZiBzdHIo"
    "VUlfU1VTUEVOU0lPTl9MQUJFTCkuc3RyaXAoKSBlbHNlICdTdXNwZW5kZWQnfSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQu"
    "IHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBh"
    "cmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYu"
    "X2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRF"
    "UzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9v"
    "bFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBi"
    "dG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNlbGYuX2J1dHRvbnNb"
    "c3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0"
    "X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChz"
    "dGF0ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMo"
    "KToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAg"
    "YnRuLnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0"
    "ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6"
    "CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0"
    "YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0"
    "cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVy"
    "bmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJB"
    "TSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29uZHMg"
    "c3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUi"
    "CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAg"
    "ICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNl"
    "bGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHBy"
    "ZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZv"
    "cmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAgICAg"
    "ICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAg"
    "ICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVm"
    "X3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAg"
    "ICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9k"
    "dXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAg"
    "c2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAgIHNlbGYu"
    "X2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAg"
    "ICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFi"
    "X2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQog"
    "ICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRocyIKICAgICAgICBzZWxmLl9wZXJzb25hX3N0b3JlX3BhdGggPSBjZmdfcGF0"
    "aCgicGVyc29uYXMiKSAvICJwZXJzb25hX2xpYnJhcnkuanNvbiIKICAgICAgICBzZWxmLl9hY3RpdmVfcGVyc29uYV9uYW1lID0gREVDS19OQU1FCgogICAg"
    "ICAgICMgTG93ZXIgSFVEIGludGVybmFsIGVjb25vbXkgc3RhdGUKICAgICAgICBzZWxmLl9lY29uX2xlZnRfb3JiID0gMC4zNQogICAgICAgIHNlbGYuX2Vj"
    "b25fcmlnaHRfb3JiID0gMC41OAogICAgICAgIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgPSAwLjgyCiAgICAgICAgc2VsZi5fbGFzdF9pbnRlcmFj"
    "dGlvbl90cyA9IHRpbWUudGltZSgpCgogICAgICAgICMg4pSA4pSAIEdvb2dsZSBTZXJ2aWNlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICAjIEluc3RhbnRpYXRlIHNlcnZpY2Ugd3JhcHBlcnMgdXAtZnJvbnQ7IGF1dGggaXMgZm9yY2VkIGxhdGVyCiAgICAgICAgIyBm"
    "cm9tIG1haW4oKSBhZnRlciB3aW5kb3cuc2hvdygpIHdoZW4gdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBnX2NyZWRzX3BhdGggPSBQYXRo"
    "KENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJjcmVkZW50aWFscyIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikg"
    "LyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKQogICAgICAgICkpCiAgICAgICAgZ190b2tlbl9wYXRoID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSku"
    "Z2V0KAogICAgICAgICAgICAidG9rZW4iLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iKQogICAgICAgICkpCiAg"
    "ICAgICAgc2VsZi5fZ2NhbCA9IEdvb2dsZUNhbGVuZGFyU2VydmljZShnX2NyZWRzX3BhdGgsIGdfdG9rZW5fcGF0aCkKICAgICAgICBzZWxmLl9nZHJpdmUg"
    "PSBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlKAogICAgICAgICAgICBnX2NyZWRzX3BhdGgsCiAgICAgICAgICAgIGdfdG9rZW5fcGF0aCwKICAgICAgICAgICAg"
    "bG9nZ2VyPWxhbWJkYSBtc2csIGxldmVsPSJJTkZPIjogc2VsZi5fZGlhZ190YWIubG9nKGYiW0dEUklWRV0ge21zZ30iLCBsZXZlbCkKICAgICAgICApCgog"
    "ICAgICAgICMgU2VlZCBMU0wgcnVsZXMgb24gZmlyc3QgcnVuCiAgICAgICAgc2VsZi5fbGVzc29ucy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAgICMgTG9h"
    "ZCBlbnRpdHkgc3RhdGUKICAgICAgICBzZWxmLl9zdGF0ZSA9IHNlbGYuX21lbW9yeS5sb2FkX3N0YXRlKCkKICAgICAgICBzZWxmLl9zdGF0ZVsic2Vzc2lv"
    "bl9jb3VudCJdID0gc2VsZi5fc3RhdGUuZ2V0KCJzZXNzaW9uX2NvdW50IiwwKSArIDEKICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zdGFydHVwIl0gID0g"
    "bG9jYWxfbm93X2lzbygpCiAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICMgQnVpbGQgYWRhcHRvcgogICAg"
    "ICAgIHNlbGYuX2FkYXB0b3IgPSBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgKHNldCB1cCBhZnRl"
    "ciB3aWRnZXRzIGJ1aWx0KQogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyOiBPcHRpb25hbFtGYWNlVGltZXJNYW5hZ2VyXSA9IE5vbmUKCiAgICAgICAg"
    "IyDilIDilIAgQnVpbGQgVUkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "c2VsZi5zZXRXaW5kb3dUaXRsZShBUFBfTkFNRSkKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEyMDAsIDc1MCkKICAgICAgICBzZWxmLnJlc2l6ZSgx"
    "MzUwLCA4NTApCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgogICAgICAgICMgRmFjZSB0aW1l"
    "ciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nciA9IEZhY2VUaW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNl"
    "bGYuX21pcnJvciwgc2VsZi5fZW1vdGlvbl9ibG9jawogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyID0gUVRpbWVyKCkKICAgICAg"
    "ICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRlX3N0YXRzKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnN0YXJ0KDEw"
    "MDApCgogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9ibGlua190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5f"
    "YmxpbmspCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIuc3RhcnQoODAwKQoKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1lcigpCiAg"
    "ICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQgYW5kIHNlbGYuX2Zvb3Rlcl9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3Ry"
    "aXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2Zvb3Rlcl9zdHJpcC5yZWZyZXNoKQogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci5z"
    "dGFydCg2MDAwMCkKCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3Vu"
    "ZF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljaykKICAgICAgICBzZWxmLl9hcHBseV9nb29nbGVfaW5i"
    "b3VuZF9pbnRlcnZhbCgpCgogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9n"
    "b29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2spCiAg"
    "ICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBzdGFy"
    "dHVwIGRlZmVycmVkIHVudGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1QgY2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkg"
    "b3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMgQm90aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4o"
    "KSBhZnRlcgogICAgICAgICMgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJ"
    "T04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFs"
    "KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDilIDilIAgQm9keTog"
    "Sm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGJvZHkgPSBRSEJveExheW91dCgpCiAgICAgICAgYm9keS5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg"
    "Sm91cm5hbCBzaWRlYmFyIChsZWZ0KQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAg"
    "ICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2xvYWRfam91cm5hbF9z"
    "ZXNzaW9uKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9j"
    "bGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgYm9keS5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFyKQoKICAgICAgICAjIENoYXQgcGFuZWwg"
    "KGNlbnRlciwgZXhwYW5kcykKICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAgICAgICMgU3lzdGVtcyAo"
    "cmlnaHQpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCkpCgogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJvZHks"
    "IDEpCgogICAgICAgICMg4pSA4pSAIEZvb3RlciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYi4pymIHtBUFBfTkFNRX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAg"
    "ICAgICApCiAgICAgICAgZm9vdGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGxl"
    "dHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZm9v"
    "dGVyLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGZvb3RlcikKCiAgICBkZWYgX2J1"
    "aWxkX3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIGJhciA9IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRGaXhlZEhlaWdodCgzNikKICAg"
    "ICAgICBiYXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChiYXIpCiAgICAg"
    "ICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxMCwgMCwgMTAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNikKCiAgICAgICAgdGl0bGUgPSBR"
    "TGFiZWwoZiLinKYge0FQUF9OQU1FfSIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZv"
    "bnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBib3JkZXI6IG5vbmU7IGZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgcnVuZXMgPSBRTGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAg"
    "ICAgIHJ1bmVzLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbChm"
    "IuKXiSB7VUlfT0ZGTElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuc3RhdHVz"
    "X2xhYmVsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAgICMgU3VzcGVuc2lvbiBwYW5lbCAocGVybWFuZW50IG9w"
    "ZXJhdGlvbmFsIGNvbnRyb2wpCiAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gVG9ycG9yUGFuZWwoKQogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5z"
    "dGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBzZWxmLl9p"
    "ZGxlX2J0biA9IFFQdXNoQnV0dG9uKCJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5f"
    "aWRsZV9idG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9pZGxlX2J0"
    "bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWln"
    "aHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fb25faWRs"
    "ZV90b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAgICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGUyIpCiAgICAgICAgc2Vs"
    "Zi5fYmxfYnRuID0gUVB1c2hCdXR0b24oIkJMIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuID0gUVB1c2hCdXR0b24oIkV4cG9ydCIpCiAgICAgICAgc2Vs"
    "Zi5fc2h1dGRvd25fYnRuID0gUVB1c2hCdXR0b24oIlNodXRkb3duIikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLl9mc19idG4sIHNlbGYuX2JsX2J0biwg"
    "c2VsZi5fZXhwb3J0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFNpemUoMzAsIDIyKQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAw"
    "OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0"
    "Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgi"
    "Qm9yZGVybGVzcyAoRjEwKSIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRYVCBmaWxlIikK"
    "ICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhlaXIgbGFz"
    "dCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVlbikKICAgICAgICBzZWxmLl9ibF9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2V4cG9ydF9jaGF0KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9wYW5lbCBpcyBub3QgTm9u"
    "ZToKICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b3Jwb3JfcGFuZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2lkbGVfYnRuKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9leHBvcnRfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "ZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fYmxfYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9jaGF0X3Bh"
    "bmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBzZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkK"
    "ICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWIg"
    "e3sgYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyB9fSIK"
    "ICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJzb25hIGNo"
    "YXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0gUVZCb3hMYXlv"
    "dXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlYW5jZV9sYXlv"
    "dXQuc2V0U3BhY2luZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFJl"
    "YWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRP"
    "Un07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "Y2hhdF9kaXNwbGF5KQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NIQVRfV0lORE9XfSIpCgogICAg"
    "ICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQog"
    "ICAgICAgIHNlbGZfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAg"
    "ICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNl"
    "bGYuX3NlbGZfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEy"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAg"
    "c2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "bWFpbl90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jlc291cmNlIGJsb2NrIHJvdyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIE1hbmRhdG9yeSBwZXJtYW5lbnQgc3Ry"
    "dWN0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBNSVJST1IgfCBFTU9USU9OUyB8IExFRlQgT1JCIHwgQ0VOVEVSIENZQ0xFIHwgUklHSFQg"
    "T1JCIHwgRVNTRU5DRQogICAgICAgIGJsb2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAj"
    "IE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "bWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFjaW5n"
    "KDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJX01JUlJPUl9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJy"
    "b3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJvci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xs"
    "YXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBD"
    "b2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAg"
    "ZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMAogICAgICAgICkKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3Jh"
    "cCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sgKGZpeGVkIDQtY29sdW1uIGxheW91dCk6CiAgICAgICAgIyBQUklNQVJZIHwgQ1lDTEUgfCBT"
    "RUNPTkRBUlkgfCBFU1NFTkNFCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfZ3JpZCA9IFFHcmlkTGF5b3V0KG1pZGRs"
    "ZV93cmFwKQogICAgICAgIG1pZGRsZV9ncmlkLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1pZGRsZV9ncmlkLnNldEhvcml6b250"
    "YWxTcGFjaW5nKDIpCiAgICAgICAgbWlkZGxlX2dyaWQuc2V0VmVydGljYWxTcGFjaW5nKDIpCgogICAgICAgICMgTGVmdCByZXNvdXJjZSBvcmIgKGNvbGxh"
    "cHNpYmxlLCBmaXhlZCBzbG90KQogICAgICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9MRUZUX09SQl9MQUJFTCwg"
    "Q19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAgICAgIHNlbGYuX2xlZnRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAg"
    "ICAgICBmIuKdpyB7VUlfTEVGVF9PUkJfVElUTEV9Iiwgc2VsZi5fbGVmdF9vcmIsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1U"
    "cnVlCiAgICAgICAgKQogICAgICAgIG1pZGRsZV9ncmlkLmFkZFdpZGdldChzZWxmLl9sZWZ0X29yYl93cmFwLCAwLCAwKQoKICAgICAgICAjIENlbnRlciBj"
    "eWNsZSB3aWRnZXQgKGNvbGxhcHNpYmxlLCBmaXhlZCBzbG90KQogICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldCA9IEN5Y2xlV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9jeWNsZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0NZQ0xFX1RJVExFfSIsIHNlbGYuX2N5Y2xlX3dpZGdl"
    "dCwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCiAgICAgICAgbWlkZGxlX2dyaWQuYWRkV2lkZ2V0KHNl"
    "bGYuX2N5Y2xlX3dyYXAsIDAsIDEpCgogICAgICAgICMgUmlnaHQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSwgZml4ZWQgc2xvdCkKICAgICAgICBzZWxm"
    "Ll9yaWdodF9vcmIgPSBTcGhlcmVXaWRnZXQoCiAgICAgICAgICAgIFVJX1JJR0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9SSUdIVF9PUkJfVElUTEV9"
    "Iiwgc2VsZi5fcmlnaHRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKICAgICAgICBtaWRkbGVf"
    "Z3JpZC5hZGRXaWRnZXQoc2VsZi5fcmlnaHRfb3JiX3dyYXAsIDAsIDIpCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxlLCBmaXhl"
    "ZCBzbG90KQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dp"
    "ZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFj"
    "aW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAu"
    "MCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlksICIl"
    "IiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBl"
    "c3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFw"
    "c2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD0x"
    "MTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKICAgICAgICBtaWRkbGVfZ3JpZC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV93cmFwLCAwLCAzKQoK"
    "ICAgICAgICBmb3IgY29sIGluIHJhbmdlKDQpOgogICAgICAgICAgICBtaWRkbGVfZ3JpZC5zZXRDb2x1bW5TdHJldGNoKGNvbCwgMSkKCiAgICAgICAgYmxv"
    "Y2tfcm93LmFkZFdpZGdldChtaWRkbGVfd3JhcCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJsb2NrX3JvdykKCiAgICAgICAgIyDilIDilIAgSW5w"
    "dXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAg"
    "ICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lu"
    "cHV0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5QcmVzc2Vk"
    "LmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuID0gUVB1c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAgICAgICAgc2Vs"
    "Zi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoK"
    "ICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9pbnB1dF9maWVsZCkKICAg"
    "ICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICAjIEZv"
    "b3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgcHJvbXB0L2lucHV0IHJvdyDigJQgcGVybWFuZW50IFVJIHN0cnVjdHVyZSkKICAgICAgICBzZWxmLl9mb290ZXJf"
    "c3RyaXAgPSBGb290ZXJTdHJpcFdpZGdldCgpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwLnNldF9sYWJlbChVSV9GT09URVJfU1RSSVBfTEFCRUwpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9mb290ZXJfc3RyaXApCgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2J1aWxkX3NwZWxsYm9v"
    "a19wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFy"
    "Z2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBT"
    "WVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9zcGVs"
    "bF90YWJzLnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGlj"
    "eS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIERp"
    "YWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBldmVuIGJlZm9yZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBh"
    "dHRhY2hlZCB0byB0aGUgd2lkZ2V0LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKUgOKUgCBJbnN0cnVt"
    "ZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5faHdfcGFuZWwgPSBIYXJkd2FyZVBhbmVs"
    "KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9od19wYW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDilIAgUmVjb3Jk"
    "cyB0YWIgKHJlYWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiID0gUmVjb3Jkc1RhYigpCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9yZWNvcmRzX3RhYiwgIlJlY29yZHMiKQogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgVGFz"
    "a3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90YXNrc190YWIgPSBUYXNrc1RhYigKICAg"
    "ICAgICAgICAgdGFza3NfcHJvdmlkZXI9c2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW49"
    "c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIG9uX2NvbXBsZXRlX3NlbGVjdGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVk"
    "X3Rhc2ssCiAgICAgICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25fdG9nZ2xlX2Nv"
    "bXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21w"
    "bGV0ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQsCiAgICAgICAgICAgIG9uX2Vk"
    "aXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90"
    "YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2csCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5k"
    "ZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190YWIsICJUYXNrcyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExC"
    "T09LXSByZWFsIFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKICAgICAg"
    "ICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zbF9zY2FucywgIlNMIFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29tbWFuZHMsICJTTCBDb21tYW5kcyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2Vy"
    "IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIo"
    "KQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAiSm9iIFRyYWNrZXIiKQoKICAgICAgICAjIOKUgOKUgCBMZXNz"
    "b25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9"
    "IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9sZXNzb25zX3RhYiwgIkxlc3NvbnMiKQoK"
    "ICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVhIGFsb25nc2lkZSB0aGUgcGVyc29uYSBjaGF0IHRhYgogICAgICAgICMgS2VlcCBh"
    "IFNlbGZUYWIgaW5zdGFuY2UgZm9yIGlkbGUgY29udGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBTZWxmVGFiKCkKCiAgICAgICAg"
    "IyDilIDilIAgTW9kdWxlIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21vZHVsZV90cmFja2Vy"
    "ID0gTW9kdWxlVHJhY2tlclRhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJNb2R1bGVzIikKCiAg"
    "ICAgICAgIyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nw"
    "ZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAiRGlhZ25vc3RpY3MiKQoKICAgICAgICAjIOKUgOKUgCBTZXR0aW5ncyB0YWIgKGRlY2std2lkZSBj"
    "b250cm9scyBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9z"
    "ZXR0aW5nc190YWIgPSBzZWxmLl9idWlsZF9zZXR0aW5nc190YWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3NldHRpbmdzX3Rh"
    "YiwgIlNldHRpbmdzIikKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dCA9IFFWQm94"
    "TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAg"
    "ICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9z"
    "cGVsbF90YWJzLCAxKQoKICAgICAgICBjYWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJlbC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwp"
    "CgogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAg"
    "ICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldE1heGltdW1IZWlnaHQo"
    "MjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFyLmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAg"
    "ICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5"
    "b3V0LmFkZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAiW0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBsb3dlci1yaWdodCBzZWN0aW9uKS4iLAog"
    "ICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcGVyc2lzdGVudCBt"
    "aW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXItcmlnaHQpLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAg"
    "ICkKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgIyDilIDilIAgU1RBUlRVUCBTRVFVRU5DRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc3RhcnR1cF9zZXF1ZW5jZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7QVBQX05BTUV9IEFXQUtFTklORy4uLiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZ"
    "U1RFTSIsIGYi4pymIHtSVU5FU30g4pymIikKCiAgICAgICAgIyBMb2FkIGJvb3RzdHJhcCBsb2cKICAgICAgICBib290X2xvZyA9IFNDUklQVF9ESVIgLyAi"
    "bG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAgICAgICAgaWYgYm9vdF9sb2cuZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IG1zZ3MgPSBib290X2xvZy5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2dfbWFueShtc2dzKQogICAgICAgICAgICAgICAgYm9vdF9sb2cudW5saW5rKCkgICMgY29uc3VtZWQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBIYXJkd2FyZSBkZXRlY3Rpb24gbWVzc2FnZXMKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFu"
    "eShzZWxmLl9od19wYW5lbC5nZXRfZGlhZ25vc3RpY3MoKSkKCiAgICAgICAgIyBEZXAgY2hlY2sKICAgICAgICBkZXBfbXNncywgY3JpdGljYWwgPSBEZXBl"
    "bmRlbmN5Q2hlY2tlci5jaGVjaygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoZGVwX21zZ3MpCgogICAgICAgICMgTG9hZCBwYXN0IHN0YXRl"
    "CiAgICAgICAgbGFzdF9zdGF0ZSA9IHNlbGYuX3N0YXRlLmdldCgidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biIsIiIpCiAgICAgICAgaWYgbGFzdF9zdGF0"
    "ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU1RBUlRVUF0gTGFzdCBzaHV0ZG93biBzdGF0ZToge2xhc3Rf"
    "c3RhdGV9IiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCZWdpbiBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RF"
    "TSIsCiAgICAgICAgICAgIFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBmIlN1bW1v"
    "bmluZyB7REVDS19OQU1FfSdzIHByZXNlbmNlLi4uIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJMT0FESU5HIikKCiAgICAgICAgc2VsZi5fbG9hZGVy"
    "ID0gTW9kZWxMb2FkZXJXb3JrZXIoc2VsZi5fYWRhcHRvcikKICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICBsYW1i"
    "ZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAgICAgICBsYW1i"
    "ZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9s"
    "b2FkX2NvbXBsZXRlKQogICAgICAgIHNlbGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0KHNlbGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAgICAgICBzZWxm"
    "Ll9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9vbl9sb2FkX2NvbXBs"
    "ZXRlKHNlbGYsIHN1Y2Nlc3M6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkID0gVHJ1"
    "ZQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAg"
    "ICAgICMgTWVhc3VyZSBWUkFNIGJhc2VsaW5lIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBzZWxmLl9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUpCiAg"
    "ICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgICAgICMgVmFtcGlyZSBzdGF0ZSBncmVl"
    "dGluZwogICAgICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAg"
    "ICAgICAgICAgdmFtcF9ncmVldGluZ3MgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgKICAgICAg"
    "ICAgICAgICAgICAgICAiU1lTVEVNIiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncy5nZXQoc3RhdGUsIGYie0RFQ0tfTkFNRX0gaXMgb25s"
    "aW5lLiIpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICMg4pSA4pSAIFdha2UtdXAgY29udGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgICMg"
    "SWYgdGhlcmUncyBhIHByZXZpb3VzIHNodXRkb3duIHJlY29yZGVkLCBpbmplY3QgY29udGV4dAogICAgICAgICAgICAjIHNvIE1vcmdhbm5hIGNhbiBncmVl"
    "dCB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyBzaGUgc2xlcHQKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoODAwLCBzZWxmLl9zZW5kX3dha2V1"
    "cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0"
    "X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9lbGFwc2VkKHNlbGYsIHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0"
    "IGVsYXBzZWQgc2Vjb25kcyBhcyBodW1hbi1yZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJldHVy"
    "biBmIntpbnQoc2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAxIGVsc2UgJyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2MDA6CiAgICAg"
    "ICAgICAgIG0gPSBpbnQoc2Vjb25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAgICAgICAgICAgIHJldHVybiBmInttfSBt"
    "aW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIgaWYgcyBlbHNlICIiKQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAg"
    "ICAgICAgICBoID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAgICAgICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2MDApIC8vIDYwKQogICAgICAgICAgICBy"
    "ZXR1cm4gZiJ7aH0gaG91cnsncycgaWYgaCAhPSAxIGVsc2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgZCA9IGludChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0gaW50KChzZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAgICAgICAgIHJl"
    "dHVybiBmIntkfSBkYXl7J3MnIGlmIGQgIT0gMSBlbHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAgIGRlZiBfc2VuZF93YWtldXBfcHJv"
    "bXB0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBoaWRkZW4gd2FrZS11cCBjb250ZXh0IHRvIEFJIGFmdGVyIG1vZGVsIGxvYWRzLiIiIgogICAg"
    "ICAgIGxhc3Rfc2h1dGRvd24gPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3Rfc2h1dGRvd24iKQogICAgICAgIGlmIG5vdCBsYXN0X3NodXRkb3duOgogICAgICAg"
    "ICAgICByZXR1cm4gICMgRmlyc3QgZXZlciBydW4g4oCUIG5vIHNodXRkb3duIHRvIHdha2UgdXAgZnJvbQoKICAgICAgICAjIENhbGN1bGF0ZSBlbGFwc2Vk"
    "IHRpbWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNodXRkb3duX2R0ID0gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdChsYXN0X3NodXRkb3duKQogICAgICAg"
    "ICAgICBub3dfZHQgPSBkYXRldGltZS5ub3coKQogICAgICAgICAgICAjIE1ha2UgYm90aCBuYWl2ZSBmb3IgY29tcGFyaXNvbgogICAgICAgICAgICBpZiBz"
    "aHV0ZG93bl9kdC50emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBzaHV0ZG93bl9kdCA9IHNodXRkb3duX2R0LmFzdGltZXpvbmUoKS5yZXBs"
    "YWNlKHR6aW5mbz1Ob25lKQogICAgICAgICAgICBlbGFwc2VkX3NlYyA9IChub3dfZHQgLSBzaHV0ZG93bl9kdCkudG90YWxfc2Vjb25kcygpCiAgICAgICAg"
    "ICAgIGVsYXBzZWRfc3RyID0gc2VsZi5fZm9ybWF0X2VsYXBzZWQoZWxhcHNlZF9zZWMpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ZWxhcHNlZF9zdHIgPSAiYW4gdW5rbm93biBkdXJhdGlvbiIKCiAgICAgICAgIyBHZXQgc3RvcmVkIGZhcmV3ZWxsIGFuZCBsYXN0IGNvbnRleHQKICAgICAg"
    "ICBmYXJld2VsbCAgICAgPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3RfZmFyZXdlbGwiLCAiIikKICAgICAgICBsYXN0X2NvbnRleHQgPSBzZWxmLl9zdGF0ZS5n"
    "ZXQoImxhc3Rfc2h1dGRvd25fY29udGV4dCIsIFtdKQoKICAgICAgICAjIEJ1aWxkIHdha2UtdXAgcHJvbXB0CiAgICAgICAgY29udGV4dF9ibG9jayA9ICIi"
    "CiAgICAgICAgaWYgbGFzdF9jb250ZXh0OgogICAgICAgICAgICBjb250ZXh0X2Jsb2NrID0gIlxuXG5UaGUgZmluYWwgZXhjaGFuZ2UgYmVmb3JlIGRlYWN0"
    "aXZhdGlvbjpcbiIKICAgICAgICAgICAgZm9yIGl0ZW0gaW4gbGFzdF9jb250ZXh0OgogICAgICAgICAgICAgICAgc3BlYWtlciA9IGl0ZW0uZ2V0KCJyb2xl"
    "IiwgInVua25vd24iKS51cHBlcigpCiAgICAgICAgICAgICAgICB0ZXh0ICAgID0gaXRlbS5nZXQoImNvbnRlbnQiLCAiIilbOjIwMF0KICAgICAgICAgICAg"
    "ICAgIGNvbnRleHRfYmxvY2sgKz0gZiJ7c3BlYWtlcn06IHt0ZXh0fVxuIgoKICAgICAgICBmYXJld2VsbF9ibG9jayA9ICIiCiAgICAgICAgaWYgZmFyZXdl"
    "bGw6CiAgICAgICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gZiJcblxuWW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgZGVhY3RpdmF0aW9uIHdlcmU6XG5cIntmYXJl"
    "d2VsbH1cIiIKCiAgICAgICAgd2FrZXVwX3Byb21wdCA9ICgKICAgICAgICAgICAgZiJZb3UgaGF2ZSBqdXN0IGJlZW4gcmVhY3RpdmF0ZWQgYWZ0ZXIge2Vs"
    "YXBzZWRfc3RyfSBvZiBkb3JtYW5jeS4iCiAgICAgICAgICAgIGYie2ZhcmV3ZWxsX2Jsb2NrfSIKICAgICAgICAgICAgZiJ7Y29udGV4dF9ibG9ja30iCiAg"
    "ICAgICAgICAgIGYiXG5HcmVldCB5b3VyIE1hc3RlciB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyB5b3UgaGF2ZSBiZWVuIGFic2VudCAiCiAgICAgICAg"
    "ICAgIGYiYW5kIHdoYXRldmVyIHlvdSBsYXN0IHNhaWQgdG8gdGhlbS4gQmUgYnJpZWYgYnV0IGNoYXJhY3RlcmZ1bC4iCiAgICAgICAgKQoKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1dBS0VVUF0gSW5qZWN0aW5nIHdha2UtdXAgY29udGV4dCAoe2VsYXBzZWRfc3RyfSBlbGFwc2Vk"
    "KSIsICJJTkZPIgogICAgICAgICkKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAg"
    "ICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijogd2FrZXVwX3Byb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0"
    "cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl93YWtldXBfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1"
    "ZQogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUu"
    "Y29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAg"
    "IGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbV0FLRVVQXVtFUlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAgICAgIHdv"
    "cmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5k"
    "ZWxldGVMYXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1dBS0VVUF1bV0FSTl0gV2FrZS11cCBwcm9tcHQgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAg"
    "ICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQoKICAgIGRlZiBfc3RhcnR1cF9nb29nbGVfYXV0aChzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIEZvcmNlIEdvb2dsZSBPQXV0aCBvbmNlIGF0IHN0YXJ0dXAgYWZ0ZXIgdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBJZiB0"
    "b2tlbiBpcyBtaXNzaW5nL2ludmFsaWQsIHRoZSBicm93c2VyIE9BdXRoIGZsb3cgb3BlbnMgbmF0dXJhbGx5LgogICAgICAgICIiIgogICAgICAgIGlmIG5v"
    "dCBHT09HTEVfT0sgb3Igbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbR09PR0xF"
    "XVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lwcGVkIGJlY2F1c2UgZGVwZW5kZW5jaWVzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICAg"
    "ICAgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgR09PR0xFX0lNUE9SVF9FUlJPUjoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIHtHT09HTEVfSU1QT1JUX0VSUk9SfSIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaWYgbm90IHNlbGYuX2djYWwgb3Igbm90IHNlbGYuX2dkcml2ZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIHNlcnZpY2Ugb2JqZWN0"
    "cyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJldHVybgoK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBCZWdpbm5pbmcgcHJvYWN0aXZlIEdvb2dsZSBhdXRoIGNoZWNrLiIs"
    "ICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBjcmVkZW50aWFscz17"
    "c2VsZi5fZ2NhbC5jcmVkZW50aWFsc19wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIHRva2VuPXtzZWxmLl9nY2FsLnRva2VuX3BhdGh9IiwKICAgICAgICAgICAg"
    "ICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICBzZWxmLl9nY2FsLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBDYWxlbmRhciBhdXRoIHJlYWR5LiIsICJPSyIpCgogICAgICAgICAgICBzZWxmLl9nZHJpdmUuZW5zdXJlX3Nl"
    "cnZpY2VzKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBEcml2ZS9Eb2NzIGF1dGggcmVhZHkuIiwgIk9LIikK"
    "ICAgICAgICAgICAgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHkgPSBUcnVlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJU"
    "VVBdIFNjaGVkdWxpbmcgaW5pdGlhbCBSZWNvcmRzIHJlZnJlc2ggYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDMwMCwgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIFBvc3Qt"
    "YXV0aCB0YXNrIHJlZnJlc2ggdHJpZ2dlcmVkLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gSW5pdGlhbCBjYWxlbmRhciBpbmJvdW5kIHN5bmMgdHJpZ2dlcmVkIGFm"
    "dGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhm"
    "b3JjZV9vbmNlPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gR29vZ2xl"
    "IENhbGVuZGFyIHRhc2sgaW1wb3J0IGNvdW50OiB7aW50KGltcG9ydGVkX2NvdW50KX0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICAp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bRVJST1Jd"
    "IHtleH0iLCAiRVJST1IiKQoKCiAgICBkZWYgX2FwcGx5X2dvb2dsZV9pbmJvdW5kX2ludGVydmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaW50ZXJ2YWxf"
    "bXMgPSBpbnQoQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyIsIDE1MDAwKSkKICAgICAgICBpbnRlcnZh"
    "bF9tcyA9IG1heCg1MDAwLCBpbnRlcnZhbF9tcykKICAgICAgICBpZiBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIuc3RhcnQoaW50ZXJ2YWxfbXMpCgogICAgZGVmIF9jdXJyZW50X2NhbGVuZGFyX3JhbmdlKHNlbGYpIC0+"
    "IHR1cGxlW2RhdGV0aW1lLCBkYXRldGltZV06CiAgICAgICAgbm93ID0gbm93X2Zvcl9jb21wYXJlKCkKICAgICAgICBjYWwgPSBnZXRhdHRyKGdldGF0dHIo"
    "c2VsZiwgImNhbGVuZGFyX3dpZGdldCIsIE5vbmUpLCAiY2FsZW5kYXIiLCBOb25lKQogICAgICAgIGlmIGNhbCBpcyBOb25lOgogICAgICAgICAgICBpZiBz"
    "ZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ5ZWFyIjoKICAgICAgICAgICAgICAgIHJldHVybiBub3csIG5vdyArIHRpbWVkZWx0YShkYXlzPTM2NikKICAg"
    "ICAgICAgICAgaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICAgICAgcmV0dXJuIG5vdywgbm93ICsgdGltZWRlbHRh"
    "KGRheXM9MzEpCiAgICAgICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICAgICAgcmV0dXJuIG5vdywgbm93"
    "ICsgdGltZWRlbHRhKGRheXM9NykKICAgICAgICAgICAgcmV0dXJuIG5vdywgbm93ICsgdGltZWRlbHRhKGRheXM9OTIpCiAgICAgICAgeWVhciA9IGNhbC55"
    "ZWFyU2hvd24oKTsgbW9udGggPSBjYWwubW9udGhTaG93bigpOyB2aWV3X3N0YXJ0ID0gZGF0ZXRpbWUoeWVhciwgbW9udGgsIDEpCiAgICAgICAgaWYgc2Vs"
    "Zi5fdGFza19kYXRlX2ZpbHRlciA9PSAieWVhciI6CiAgICAgICAgICAgIHN0YXJ0ID0gZGF0ZXRpbWUoeWVhciwgMSwgMSk7IGVuZCA9IGRhdGV0aW1lKHll"
    "YXIgKyAxLCAxLCAxKSAtIHRpbWVkZWx0YShzZWNvbmRzPTEpCiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAg"
    "ICAgICAgIHN0YXJ0ID0gdmlld19zdGFydAogICAgICAgICAgICBuZXh0X21vbnRoID0gZGF0ZXRpbWUoeWVhciArICgxIGlmIG1vbnRoID09IDEyIGVsc2Ug"
    "MCksIDEgaWYgbW9udGggPT0gMTIgZWxzZSBtb250aCArIDEsIDEpCiAgICAgICAgICAgIGVuZCA9IG5leHRfbW9udGggLSB0aW1lZGVsdGEoc2Vjb25kcz0x"
    "KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAid2VlayI6CiAgICAgICAgICAgIHN0YXJ0ID0gdmlld19zdGFydCAtIHRpbWVkZWx0"
    "YShkYXlzPXZpZXdfc3RhcnQud2Vla2RheSgpKTsgZW5kID0gc3RhcnQgKyB0aW1lZGVsdGEoZGF5cz03KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN0"
    "YXJ0ID0gdmlld19zdGFydDsgZW5kID0gc3RhcnQgKyB0aW1lZGVsdGEoZGF5cz05MikKICAgICAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9j"
    "b21wYXJlKHN0YXJ0LCBjb250ZXh0PSJjYWxlbmRhcl9yYW5nZV9zdGFydCIpLCBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZW5kLCBjb250ZXh0"
    "PSJjYWxlbmRhcl9yYW5nZV9lbmQiKQoKICAgIGRlZiBfdHJpZ2dlcl9nb29nbGVfcmVwdWxsX25vdyhzZWxmLCByZWFzb246IHN0ciA9ICJtYW51YWwiKSAt"
    "PiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKGYiW0dPT0dMRV1bUkVQVUxMXSBpbW1lZGlhdGUgcmVwdWxsIHJlYXNvbj17cmVhc29ufSIsICJJTkZPIikKICAgICAgICBzZWxmLl9wb2xsX2dvb2ds"
    "ZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1UcnVlKQoKICAgIGRlZiBfYnVpbGRfc2V0dGluZ3NfdGFiKHNlbGYpIC0+IFFXaWRnZXQ6CiAg"
    "ICAgICAgdGFiID0gUVdpZGdldCgpOyByb290ID0gUVZCb3hMYXlvdXQodGFiKTsgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNik7IHJvb3Qu"
    "c2V0U3BhY2luZyg2KQogICAgICAgIGRlZiBfc2VjdGlvbih0aXRsZTogc3RyKSAtPiBRR3JvdXBCb3g6CiAgICAgICAgICAgIGJveCA9IFFHcm91cEJveCh0"
    "aXRsZSk7IGJveC5zZXRMYXlvdXQoUVZCb3hMYXlvdXQoKSk7IGJveC5sYXlvdXQoKS5zZXRTcGFjaW5nKDQpOyByZXR1cm4gYm94CgogICAgICAgIHBlcnNv"
    "bmFfYm94ID0gX3NlY3Rpb24oIlBlcnNvbmEiKQogICAgICAgIHNlbGYuX3NldHRpbmdzX2FjdGl2ZV9wZXJzb25hID0gUUxhYmVsKGYiQWN0aXZlIFBlcnNv"
    "bmE6IHtzZWxmLl9hY3RpdmVfcGVyc29uYV9uYW1lfSIpCiAgICAgICAgc2VsZi5fc2V0dGluZ3NfcGVyc29uYV9jb21ibyA9IFFDb21ib0JveCgpOyBzZWxm"
    "Ll9zZXR0aW5nc19wZXJzb25hX2NvbWJvLmFkZEl0ZW0oc2VsZi5fYWN0aXZlX3BlcnNvbmFfbmFtZSkKICAgICAgICBsb2FkX2J0biA9IF9nb3RoaWNfYnRu"
    "KCJMb2FkIFBlcnNvbmEiKTsgc3dhcF9idG4gPSBfZ290aGljX2J0bigiU3dhcCBQZXJzb25hIik7IGRlbF9idG4gPSBfZ290aGljX2J0bigiRGVsZXRlIFBl"
    "cnNvbmEiKQogICAgICAgIGxvYWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZXR0aW5nc19sb2FkX3BlcnNvbmEpOyBzd2FwX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fc2V0dGluZ3Nfc3dhcF9wZXJzb25hKTsgZGVsX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2V0dGluZ3NfZGVsZXRlX3BlcnNvbmEp"
    "CiAgICAgICAgcGVyc29uYV9ib3gubGF5b3V0KCkuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX2FjdGl2ZV9wZXJzb25hKTsgcGVyc29uYV9ib3gubGF5b3V0"
    "KCkuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX3BlcnNvbmFfY29tYm8pCiAgICAgICAgcm93ID0gUUhCb3hMYXlvdXQoKTsgcm93LmFkZFdpZGdldChsb2Fk"
    "X2J0bik7IHJvdy5hZGRXaWRnZXQoc3dhcF9idG4pOyByb3cuYWRkV2lkZ2V0KGRlbF9idG4pOyBwZXJzb25hX2JveC5sYXlvdXQoKS5hZGRMYXlvdXQocm93"
    "KQoKICAgICAgICBhaV9ib3ggPSBfc2VjdGlvbigiQUkgQmVoYXZpb3IiKQogICAgICAgIHNlbGYuX3NldHRpbmdzX3RvcnBvcl9tb2RlID0gUUNvbWJvQm94"
    "KCk7IHNlbGYuX3NldHRpbmdzX3RvcnBvcl9tb2RlLmFkZEl0ZW1zKFsiQVdBS0UiLCAiQVVUTyIsICJTVVNQRU5ERUQiXSkKICAgICAgICBzZWxmLl9zZXR0"
    "aW5nc190b3Jwb3JfbW9kZS5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKICAgICAgICBzZWxmLl9z"
    "ZXR0aW5nc19pZGxlX3RvZ2dsZSA9IFFDaGVja0JveCgiSWRsZSBFbmFibGVkIik7IHNlbGYuX3NldHRpbmdzX2lkbGVfdG9nZ2xlLnNldENoZWNrZWQoYm9v"
    "bChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImlkbGVfZW5hYmxlZCIsIEZhbHNlKSkpOyBzZWxmLl9zZXR0aW5nc19pZGxlX3RvZ2dsZS50b2dnbGVk"
    "LmNvbm5lY3Qoc2VsZi5fb25faWRsZV90b2dnbGVkKQogICAgICAgIGFpX2JveC5sYXlvdXQoKS5hZGRXaWRnZXQoUUxhYmVsKCJTdXNwZW5zaW9uIE1vZGUi"
    "KSk7IGFpX2JveC5sYXlvdXQoKS5hZGRXaWRnZXQoc2VsZi5fc2V0dGluZ3NfdG9ycG9yX21vZGUpOyBhaV9ib3gubGF5b3V0KCkuYWRkV2lkZ2V0KHNlbGYu"
    "X3NldHRpbmdzX2lkbGVfdG9nZ2xlKQoKICAgICAgICB1aV9ib3ggPSBfc2VjdGlvbigiVUkgQmVoYXZpb3IiKQogICAgICAgIGZzX2J0biA9IF9nb3RoaWNf"
    "YnRuKCJUb2dnbGUgRnVsbHNjcmVlbiIpOyBmc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKQogICAgICAgIGJsX2J0biA9"
    "IF9nb3RoaWNfYnRuKCJUb2dnbGUgQm9yZGVybGVzcyIpOyBibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKQogICAgICAg"
    "IHNlbGYuX3NldHRpbmdzX3NvdW5kX3RvZ2dsZSA9IFFDaGVja0JveCgiU291bmQgRW5hYmxlZCIpOyBzZWxmLl9zZXR0aW5nc19zb3VuZF90b2dnbGUuc2V0"
    "Q2hlY2tlZChib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpKSk7IHNlbGYuX3NldHRpbmdzX3NvdW5kX3Rv"
    "Z2dsZS50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fc2V0dGluZ3Nfc2V0X3NvdW5kX2VuYWJsZWQpCiAgICAgICAgdXJvdyA9IFFIQm94TGF5b3V0KCk7IHVyb3cu"
    "YWRkV2lkZ2V0KGZzX2J0bik7IHVyb3cuYWRkV2lkZ2V0KGJsX2J0bik7IHVpX2JveC5sYXlvdXQoKS5hZGRMYXlvdXQodXJvdyk7IHVpX2JveC5sYXlvdXQo"
    "KS5hZGRXaWRnZXQoc2VsZi5fc2V0dGluZ3Nfc291bmRfdG9nZ2xlKQoKICAgICAgICBpbnRfYm94ID0gX3NlY3Rpb24oIkludGVncmF0aW9ucyIpCiAgICAg"
    "ICAgc2VsZi5fc2V0dGluZ3NfZ29vZ2xlX2ludGVydmFsID0gUVNwaW5Cb3goKTsgc2VsZi5fc2V0dGluZ3NfZ29vZ2xlX2ludGVydmFsLnNldFJhbmdlKDUs"
    "IDM2MDApOyBzZWxmLl9zZXR0aW5nc19nb29nbGVfaW50ZXJ2YWwuc2V0VmFsdWUobWF4KDUsIGludChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdv"
    "b2dsZV9pbmJvdW5kX2ludGVydmFsX21zIiwgMTUwMDApKSAvLyAxMDAwKSk7IHNlbGYuX3NldHRpbmdzX2dvb2dsZV9pbnRlcnZhbC52YWx1ZUNoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl9zZXR0aW5nc19zZXRfZ29vZ2xlX2ludGVydmFsX3NlYykKICAgICAgICBpcm93ID0gUUhCb3hMYXlvdXQoKTsgaXJvdy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJHb29nbGUgUmVmcmVzaCAoc2VjKSIpKTsgaXJvdy5hZGRXaWRnZXQoc2VsZi5fc2V0dGluZ3NfZ29vZ2xlX2ludGVydmFsKTsgaW50X2Jv"
    "eC5sYXlvdXQoKS5hZGRMYXlvdXQoaXJvdykKCiAgICAgICAgc3lzX2JveCA9IF9zZWN0aW9uKCJQZXJzaXN0ZW5jZSAvIFN5c3RlbSIpCiAgICAgICAgc2Vs"
    "Zi5fc2V0dGluZ3NfYXV0b3NhdmUgPSBRU3BpbkJveCgpOyBzZWxmLl9zZXR0aW5nc19hdXRvc2F2ZS5zZXRSYW5nZSgxLCAxMjApOyBzZWxmLl9zZXR0aW5n"
    "c19hdXRvc2F2ZS5zZXRWYWx1ZShpbnQoQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIiwgMTApKSk7IHNl"
    "bGYuX3NldHRpbmdzX2F1dG9zYXZlLnZhbHVlQ2hhbmdlZC5jb25uZWN0KGxhbWJkYSB2OiBzZWxmLl9zZXR0aW5nc19zZXRfbnVtZXJpYygiYXV0b3NhdmVf"
    "aW50ZXJ2YWxfbWludXRlcyIsIHYpKQogICAgICAgIHNlbGYuX3NldHRpbmdzX2JhY2t1cHMgPSBRU3BpbkJveCgpOyBzZWxmLl9zZXR0aW5nc19iYWNrdXBz"
    "LnNldFJhbmdlKDEsIDIwMCk7IHNlbGYuX3NldHRpbmdzX2JhY2t1cHMuc2V0VmFsdWUoaW50KENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgibWF4X2Jh"
    "Y2t1cHMiLCAxMCkpKTsgc2VsZi5fc2V0dGluZ3NfYmFja3Vwcy52YWx1ZUNoYW5nZWQuY29ubmVjdChsYW1iZGEgdjogc2VsZi5fc2V0dGluZ3Nfc2V0X251"
    "bWVyaWMoIm1heF9iYWNrdXBzIiwgdikpCiAgICAgICAgYXJvdyA9IFFIQm94TGF5b3V0KCk7IGFyb3cuYWRkV2lkZ2V0KFFMYWJlbCgiQXV0b3NhdmUgKG1p"
    "bikiKSk7IGFyb3cuYWRkV2lkZ2V0KHNlbGYuX3NldHRpbmdzX2F1dG9zYXZlKQogICAgICAgIGJyb3cgPSBRSEJveExheW91dCgpOyBicm93LmFkZFdpZGdl"
    "dChRTGFiZWwoIkJhY2t1cCBDb3VudCIpKTsgYnJvdy5hZGRXaWRnZXQoc2VsZi5fc2V0dGluZ3NfYmFja3VwcykKICAgICAgICBzeXNfYm94LmxheW91dCgp"
    "LmFkZExheW91dChhcm93KTsgc3lzX2JveC5sYXlvdXQoKS5hZGRMYXlvdXQoYnJvdykKCiAgICAgICAgZm9yIGJveCBpbiAocGVyc29uYV9ib3gsIGFpX2Jv"
    "eCwgdWlfYm94LCBpbnRfYm94LCBzeXNfYm94KTogcm9vdC5hZGRXaWRnZXQoYm94KQogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgxKQogICAgICAgIHJldHVy"
    "biB0YWIKCiAgICBkZWYgX3NldHRpbmdzX3NldF9udW1lcmljKHNlbGYsIGtleTogc3RyLCB2YWx1ZTogaW50KSAtPiBOb25lOgogICAgICAgIENGRy5zZXRk"
    "ZWZhdWx0KCJzZXR0aW5ncyIsIHt9KVtrZXldID0gaW50KHZhbHVlKTsgc2F2ZV9jb25maWcoQ0ZHKQoKICAgIGRlZiBfc2V0dGluZ3Nfc2V0X3NvdW5kX2Vu"
    "YWJsZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkcuc2V0ZGVmYXVsdCgic2V0dGluZ3MiLCB7fSlbInNvdW5kX2VuYWJsZWQi"
    "XSA9IGJvb2woZW5hYmxlZCk7IHNhdmVfY29uZmlnKENGRykKCiAgICBkZWYgX3NldHRpbmdzX3NldF9nb29nbGVfaW50ZXJ2YWxfc2VjKHNlbGYsIHNlY29u"
    "ZHM6IGludCkgLT4gTm9uZToKICAgICAgICBDRkcuc2V0ZGVmYXVsdCgic2V0dGluZ3MiLCB7fSlbImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIl0gPSBt"
    "YXgoNTAwMCwgaW50KHNlY29uZHMpICogMTAwMCkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpOyBzZWxmLl9hcHBseV9nb29nbGVfaW5ib3VuZF9pbnRlcnZh"
    "bCgpCgogICAgZGVmIF9sb2FkX3BlcnNvbmFfbGlicmFyeShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLl9wZXJzb25hX3N0b3JlX3BhdGgu"
    "ZXhpc3RzKCk6IHJldHVybiB7InBlcnNvbmFzIjogW119CiAgICAgICAgdHJ5OiByZXR1cm4ganNvbi5sb2FkcyhzZWxmLl9wZXJzb25hX3N0b3JlX3BhdGgu"
    "cmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246IHJldHVybiB7InBlcnNvbmFzIjogW119CgogICAgZGVmIF9z"
    "YXZlX3BlcnNvbmFfbGlicmFyeShzZWxmLCBkYXRhOiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3BlcnNvbmFfc3RvcmVfcGF0aC5wYXJlbnQubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYuX3BlcnNvbmFfc3RvcmVfcGF0aC53cml0ZV90ZXh0KGpzb24uZHVtcHMoZGF0"
    "YSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfc2V0dGluZ3NfbG9hZF9wZXJzb25hKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGVy"
    "c29uYV9wYXRoLCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKHNlbGYsICJMb2FkIFBlcnNvbmEgVGVtcGxhdGUiLCBzdHIoY2ZnX3BhdGgoInBl"
    "cnNvbmFzIikpLCAiUGVyc29uYSAoKi5qc29uICoudHh0KSIpCiAgICAgICAgaWYgbm90IHBlcnNvbmFfcGF0aDogcmV0dXJuCiAgICAgICAgZmFjZV96aXAs"
    "IF8gPSBRRmlsZURpYWxvZy5nZXRPcGVuRmlsZU5hbWUoc2VsZiwgIkxvYWQgRmFjZS9FbW90ZSBQYWNrIiwgc3RyKGNmZ19wYXRoKCJwZXJzb25hcyIpKSwg"
    "IlppcCAoKi56aXApIikKICAgICAgICBpZiBub3QgZmFjZV96aXA6IHJldHVybgogICAgICAgIHNyYyA9IFBhdGgocGVyc29uYV9wYXRoKTsgenNyYyA9IFBh"
    "dGgoZmFjZV96aXApOyBuYW1lID0gc3JjLnN0ZW0KICAgICAgICB0YXJnZXRfZGlyID0gY2ZnX3BhdGgoInBlcnNvbmFzIikgLyBuYW1lOyB0YXJnZXRfZGly"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAodGFyZ2V0X2RpciAvIHNyYy5uYW1lKS53cml0ZV90ZXh0KHNyYy5yZWFkX3Rl"
    "eHQoZW5jb2Rpbmc9InV0Zi04IiksIGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgKHRhcmdldF9kaXIgLyB6c3JjLm5hbWUpLndyaXRlX2J5dGVzKHpzcmMu"
    "cmVhZF9ieXRlcygpKQogICAgICAgIGxpYiA9IHNlbGYuX2xvYWRfcGVyc29uYV9saWJyYXJ5KCk7IHBlcnNvbmFzID0gW3AgZm9yIHAgaW4gbGliLmdldCgi"
    "cGVyc29uYXMiLCBbXSkgaWYgcC5nZXQoIm5hbWUiKSAhPSBuYW1lXQogICAgICAgIHBlcnNvbmFzLmFwcGVuZCh7Im5hbWUiOiBuYW1lLCAidGVtcGxhdGUi"
    "OiBzdHIodGFyZ2V0X2RpciAvIHNyYy5uYW1lKSwgImZhY2VzX3ppcCI6IHN0cih0YXJnZXRfZGlyIC8genNyYy5uYW1lKX0pCiAgICAgICAgbGliWyJwZXJz"
    "b25hcyJdID0gcGVyc29uYXM7IHNlbGYuX3NhdmVfcGVyc29uYV9saWJyYXJ5KGxpYikKICAgICAgICBpZiBzZWxmLl9zZXR0aW5nc19wZXJzb25hX2NvbWJv"
    "LmZpbmRUZXh0KG5hbWUpIDwgMDogc2VsZi5fc2V0dGluZ3NfcGVyc29uYV9jb21iby5hZGRJdGVtKG5hbWUpCgogICAgZGVmIF9zZXR0aW5nc19zd2FwX3Bl"
    "cnNvbmEoc2VsZikgLT4gTm9uZToKICAgICAgICBuYW1lID0gc2VsZi5fc2V0dGluZ3NfcGVyc29uYV9jb21iby5jdXJyZW50VGV4dCgpLnN0cmlwKCkKICAg"
    "ICAgICBpZiBub3QgbmFtZTogcmV0dXJuCiAgICAgICAgc2VsZi5fYWN0aXZlX3BlcnNvbmFfbmFtZSA9IG5hbWUKICAgICAgICBzZWxmLl9zZXR0aW5nc19h"
    "Y3RpdmVfcGVyc29uYS5zZXRUZXh0KGYiQWN0aXZlIFBlcnNvbmE6IHtuYW1lfSIpCiAgICAgICAgYXBwZW5kX2pzb25sKGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gInBlcnNvbmFfaGlzdG9yeS5qc29ubCIsIHsKICAgICAgICAgICAgImlkIjogZiJwZXJzb25hX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwgInRpbWVz"
    "dGFtcCI6IGxvY2FsX25vd19pc28oKSwgInBlcnNvbmEiOiBuYW1lLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6IHNlbGYuX3Nlc3Npb25faWQsICJhY3Rp"
    "b24iOiAic3dhcCIKICAgICAgICB9KQoKICAgIGRlZiBfc2V0dGluZ3NfZGVsZXRlX3BlcnNvbmEoc2VsZikgLT4gTm9uZToKICAgICAgICBuYW1lID0gc2Vs"
    "Zi5fc2V0dGluZ3NfcGVyc29uYV9jb21iby5jdXJyZW50VGV4dCgpLnN0cmlwKCkKICAgICAgICBpZiBub3QgbmFtZSBvciBuYW1lID09IHNlbGYuX2FjdGl2"
    "ZV9wZXJzb25hX25hbWU6IHJldHVybgogICAgICAgIGxpYiA9IHNlbGYuX2xvYWRfcGVyc29uYV9saWJyYXJ5KCk7IGxpYlsicGVyc29uYXMiXSA9IFtwIGZv"
    "ciBwIGluIGxpYi5nZXQoInBlcnNvbmFzIiwgW10pIGlmIHAuZ2V0KCJuYW1lIikgIT0gbmFtZV07IHNlbGYuX3NhdmVfcGVyc29uYV9saWJyYXJ5KGxpYikK"
    "ICAgICAgICBpZHggPSBzZWxmLl9zZXR0aW5nc19wZXJzb25hX2NvbWJvLmZpbmRUZXh0KG5hbWUpCiAgICAgICAgaWYgaWR4ID49IDA6IHNlbGYuX3NldHRp"
    "bmdzX3BlcnNvbmFfY29tYm8ucmVtb3ZlSXRlbShpZHgpCgogICAgZGVmIF9yZWZyZXNoX3JlY29yZHNfZG9jcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9h"
    "ZGluZyBHb29nbGUgRHJpdmUgcmVjb3Jkcy4uLiIpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRoOiBNeSBEcml2"
    "ZSIpCiAgICAgICAgZmlsZXMgPSBzZWxmLl9nZHJpdmUubGlzdF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJf"
    "aWQsIHBhZ2Vfc2l6ZT0yMDApCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZSA9IGZpbGVzCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9"
    "IFRydWUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhfdGV4dD0iTXkgRHJpdmUiKQoKICAgIGRlZiBfb25fZ29vZ2xl"
    "X2luYm91bmRfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAi"
    "V0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91bmQgc3lu"
    "YyB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3JvdW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAg"
    "ICAgIGRlZiBfY2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2lu"
    "Ym91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDi"
    "gJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vzc2VkLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl1bRVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICBf"
    "dGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hf"
    "dGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBz"
    "dGFydGluZyBiYWNrZ3JvdW5kIHJlZnJlc2guIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRlZiBf"
    "YmcoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MoKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIGNvbXBsZXRlLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtEUklWRV1b"
    "U1lOQ11bRVJST1JdIHJlY29yZHMgcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3RocmVhZGluZy5U"
    "aHJlYWQodGFyZ2V0PV9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeShzZWxmKSAtPiBsaXN0"
    "W2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgIHN0YXJ0LCBlbmQgPSBzZWxmLl9jdXJyZW50X2NhbGVuZGFy"
    "X3JhbmdlKCkKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBzdGFydCBmaWx0ZXI9e3NlbGYuX3Rh"
    "c2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkfSB0b3RhbD17bGVuKHRhc2tzKX0iLAogICAgICAgICAg"
    "ICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSB2aXNpYmxlX3N0YXJ0PXtzdGFydC5pc29m"
    "b3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSB2aXNpYmxl"
    "X2VuZD17ZW5kLmlzb2Zvcm1hdCh0aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0W2RpY3RdID0gW10KICAg"
    "ICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAg"
    "ICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpCiAgICAgICAgICAg"
    "IGR1ZV9kdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190YWJfZHVlX2ZpbHRlciIpCiAgICAgICAgICAgIGlmIGR1"
    "ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmUgb3IgKHN0YXJ0"
    "IDw9IGR1ZV9kdCA8PSBlbmQpIG9yIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGZpbHRlcmVkLmFwcGVu"
    "ZCh0YXNrKQoKICAgICAgICBmaWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVfc29ydF9rZXkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tT"
    "XVtGSUxURVJdIGRvbmUgYmVmb3JlPXtsZW4odGFza3MpfSBhZnRlcj17bGVuKGZpbHRlcmVkKX0iLCAiSU5GTyIpCiAgICAgICAgcmV0dXJuIGZpbHRlcmVk"
    "CgogICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAgICAgICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0"
    "KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0ZV90aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAgICAgICAg"
    "ICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBp"
    "ZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAgICBpZiBk"
    "YXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29v"
    "Z2xlX2V2ZW50X2RhdGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgcmV0dXJuIE5vbmUK"
    "CiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIi"
    "LCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAg"
    "ICAgICAgICAgdmlzaWJsZV9jb3VudCA9IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIs"
    "ICJFUlJPUiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0icmVn"
    "aXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIHN0b3BfZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtlciBj"
    "bGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVy"
    "X2NoYW5nZWQoc2VsZiwgZmlsdGVyX2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBzdHIoZmlsdGVyX2tleSBv"
    "ciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQg"
    "dG8ge3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAg"
    "IHNlbGYuX3RyaWdnZXJfZ29vZ2xlX3JlcHVsbF9ub3cocmVhc29uPSJ0YXNrX2ZpbHRlcl9jaGFuZ2VkIikKCiAgICBkZWYgX3RvZ2dsZV9zaG93X2NvbXBs"
    "ZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBub3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRl"
    "ZAogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfc2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlmIGdldGF0"
    "dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gW10KICAgICAgICByZXR1cm4gc2VsZi5fdGFza3NfdGFi"
    "LnNlbGVjdGVkX3Rhc2tfaWRzKCkKCiAgICBkZWYgX3NldF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1czogc3RyKSAtPiBPcHRpb25h"
    "bFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNr"
    "X2lkKQogICAgICAgIGVsaWYgc3RhdHVzID09ICJjYW5jZWxsZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY2FuY2VsKHRhc2tfaWQp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBp"
    "ZiBub3QgdXBkYXRlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgZ29vZ2xlX2V2ZW50X2lkID0gKHVwZGF0ZWQuZ2V0KCJnb29nbGVfZXZl"
    "bnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgIGlmIGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5f"
    "Z2NhbC5kZWxldGVfZXZlbnRfZm9yX3Rhc2soZ29vZ2xlX2V2ZW50X2lkKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtXQVJOXSBHb29nbGUgZXZlbnQgY2xlYW51cCBmYWlsZWQg"
    "Zm9yIHRhc2tfaWQ9e3Rhc2tfaWR9OiB7ZXh9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJu"
    "IHVwZGF0ZWQKCiAgICBkZWYgX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNr"
    "X2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY29tcGxldGVk"
    "Iik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENPTVBMRVRFIFNFTEVDVEVEIGFwcGxp"
    "ZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9jYW5j"
    "ZWxfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFz"
    "a19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToKICAgICAgICAgICAgICAgIGRvbmUg"
    "Kz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ0FOQ0VMIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklO"
    "Rk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9wdXJnZV9jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICByZW1vdmVkID0gc2VsZi5fdGFza3MuY2xlYXJfY29tcGxldGVkKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1Nd"
    "IFBVUkdFIENPTVBMRVRFRCByZW1vdmVkIHtyZW1vdmVkfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlf"
    "cGFuZWwoKQoKICAgIGRlZiBfc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+IE5vbmU6CiAgICAg"
    "ICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3N0YXR1"
    "cyh0ZXh0LCBvaz1vaykKCiAgICBkZWYgX29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxm"
    "LCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpCiAgICAg"
    "ICAgZW5kX2xvY2FsID0gbm93X2xvY2FsICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25hbWUu"
    "c2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRUZXh0KG5vd19sb2NhbC5zdHJmdGltZSgiJVkt"
    "JW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRUZXh0KG5vd19sb2NhbC5zdHJmdGltZSgiJUg6JU0i"
    "KSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfZW5kX2RhdGUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVkIikpCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNl"
    "bGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRQbGFpblRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2xvY2F0"
    "aW9uLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90"
    "YXNrc190YWIudGFza19lZGl0b3JfYWxsX2RheS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkNvbmZp"
    "Z3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIuIiwgb2s9RmFsc2UpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLm9wZW5f"
    "ZWRpdG9yKCkKCiAgICBkZWYgX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90"
    "YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLmNsb3NlX2VkaXRvcigpCgogICAgZGVmIF9jYW5jZWxf"
    "dGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYg"
    "X3BhcnNlX2VkaXRvcl9kYXRldGltZShzZWxmLCBkYXRlX3RleHQ6IHN0ciwgdGltZV90ZXh0OiBzdHIsIGFsbF9kYXk6IGJvb2wsIGlzX2VuZDogYm9vbCA9"
    "IEZhbHNlKToKICAgICAgICBkYXRlX3RleHQgPSAoZGF0ZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgdGltZV90ZXh0ID0gKHRpbWVfdGV4dCBvciAi"
    "Iikuc3RyaXAoKQogICAgICAgIGlmIG5vdCBkYXRlX3RleHQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAg"
    "ICAgaG91ciA9IDIzIGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgbWludXRlID0gNTkgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBwYXJzZWQg"
    "PSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHtob3VyOjAyZH06e21pbnV0ZTowMmR9IiwgIiVZLSVtLSVkICVIOiVNIikKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICBwYXJzZWQgPSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHt0aW1lX3RleHR9IiwgIiVZLSVtLSVkICVIOiVNIikKICAg"
    "ICAgICBub3JtYWxpemVkID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKHBhcnNlZCwgY29udGV4dD0idGFza19lZGl0b3JfcGFyc2VfZHQiKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gcGFyc2VkIGRhdGV0aW1lIGlzX2VuZD17aXNfZW5kfSwg"
    "YWxsX2RheT17YWxsX2RheX06ICIKICAgICAgICAgICAgZiJpbnB1dD0ne2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0nIC0+IHtub3JtYWxpemVkLmlzb2Zvcm1h"
    "dCgpIGlmIG5vcm1hbGl6ZWQgZWxzZSAnTm9uZSd9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAoK"
    "ICAgIGRlZiBfc2F2ZV90YXNrX2VkaXRvcl9nb29nbGVfZmlyc3Qoc2VsZikgLT4gTm9uZToKICAgICAgICB0YWIgPSBnZXRhdHRyKHNlbGYsICJfdGFza3Nf"
    "dGFiIiwgTm9uZSkKICAgICAgICBpZiB0YWIgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGl0bGUgPSB0YWIudGFza19lZGl0b3JfbmFt"
    "ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGFsbF9kYXkgPSB0YWIudGFza19lZGl0b3JfYWxsX2RheS5pc0NoZWNrZWQoKQogICAgICAgIHN0YXJ0X2RhdGUg"
    "PSB0YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIHN0YXJ0X3RpbWUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRfdGlt"
    "ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX3Rp"
    "bWUgPSB0YWIudGFza19lZGl0b3JfZW5kX3RpbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3RlcyA9IHRhYi50YXNrX2VkaXRvcl9ub3Rlcy50b1BsYWlu"
    "VGV4dCgpLnN0cmlwKCkKICAgICAgICBsb2NhdGlvbiA9IHRhYi50YXNrX2VkaXRvcl9sb2NhdGlvbi50ZXh0KCkuc3RyaXAoKQogICAgICAgIHJlY3VycmVu"
    "Y2UgPSB0YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS50ZXh0KCkuc3RyaXAoKQoKICAgICAgICBpZiBub3QgdGl0bGU6CiAgICAgICAgICAgIHNlbGYuX3Nl"
    "dF90YXNrX2VkaXRvcl9zdGF0dXMoIlRhc2sgTmFtZSBpcyByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90"
    "IHN0YXJ0X2RhdGUgb3Igbm90IGVuZF9kYXRlIG9yIChub3QgYWxsX2RheSBhbmQgKG5vdCBzdGFydF90aW1lIG9yIG5vdCBlbmRfdGltZSkpOgogICAgICAg"
    "ICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJTdGFydC9FbmQgZGF0ZSBhbmQgdGltZSBhcmUgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc3RhcnRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc3RhcnRfZGF0ZSwg"
    "c3RhcnRfdGltZSwgYWxsX2RheSwgaXNfZW5kPUZhbHNlKQogICAgICAgICAgICBlbmRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoZW5kX2Rh"
    "dGUsIGVuZF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9VHJ1ZSkKICAgICAgICAgICAgaWYgbm90IHN0YXJ0X2R0IG9yIG5vdCBlbmRfZHQ6CiAgICAgICAgICAg"
    "ICAgICByYWlzZSBWYWx1ZUVycm9yKCJkYXRldGltZSBwYXJzZSBmYWlsZWQiKQogICAgICAgICAgICBpZiBlbmRfZHQgPCBzdGFydF9kdDoKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkVuZCBkYXRldGltZSBtdXN0IGJlIGFmdGVyIHN0YXJ0IGRhdGV0aW1lLiIsIG9rPUZhbHNl"
    "KQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1"
    "cygiSW52YWxpZCBkYXRlL3RpbWUgZm9ybWF0LiBVc2UgWVlZWS1NTS1ERCBhbmQgSEg6TU0uIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgoKICAg"
    "ICAgICB0el9uYW1lID0gc2VsZi5fZ2NhbC5fZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCiAgICAgICAgcGF5bG9hZCA9IHsic3VtbWFyeSI6IHRpdGxl"
    "fQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGUiOiBzdGFydF9kdC5kYXRlKCkuaXNvZm9ybWF0KCl9"
    "CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlIjogKGVuZF9kdC5kYXRlKCkgKyB0aW1lZGVsdGEoZGF5cz0xKSkuaXNvZm9ybWF0KCl9CiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZVRpbWUiOiBzdGFydF9kdC5yZXBsYWNlKHR6aW5mbz1Ob25lKS5pc29m"
    "b3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGVUaW1lIjog"
    "ZW5kX2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgIGlm"
    "IG5vdGVzOgogICAgICAgICAgICBwYXlsb2FkWyJkZXNjcmlwdGlvbiJdID0gbm90ZXMKICAgICAgICBpZiBsb2NhdGlvbjoKICAgICAgICAgICAgcGF5bG9h"
    "ZFsibG9jYXRpb24iXSA9IGxvY2F0aW9uCiAgICAgICAgaWYgcmVjdXJyZW5jZToKICAgICAgICAgICAgcnVsZSA9IHJlY3VycmVuY2UgaWYgcmVjdXJyZW5j"
    "ZS51cHBlcigpLnN0YXJ0c3dpdGgoIlJSVUxFOiIpIGVsc2UgZiJSUlVMRTp7cmVjdXJyZW5jZX0iCiAgICAgICAgICAgIHBheWxvYWRbInJlY3VycmVuY2Ui"
    "XSA9IFtydWxlXQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3RhcnQgZm9yIHRpdGxlPSd7dGl0"
    "bGV9Jy4iLCAiSU5GTyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICBldmVudF9pZCwgXyA9IHNlbGYuX2djYWwuY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9h"
    "ZChwYXlsb2FkLCBjYWxlbmRhcl9pZD0icHJpbWFyeSIpCiAgICAgICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0"
    "YXNrID0gewogICAgICAgICAgICAgICAgImlkIjogZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0"
    "IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgInBlcnNvbmEiOiBzZWxmLl9hY3RpdmVfcGVyc29uYV9uYW1lLAogICAgICAgICAgICAgICAg"
    "ImR1ZV9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogKHN0YXJ0X2R0"
    "IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgInRleHQiOiB0aXRsZSwKICAg"
    "ICAgICAgICAgICAgICJzdGF0dXMiOiAicGVuZGluZyIsCiAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAg"
    "ICJyZXRyeV9jb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgIm5leHRfcmV0cnlf"
    "YXQiOiBOb25lLAogICAgICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiBGYWxzZSwKICAgICAgICAgICAgICAgICJzb3VyY2UiOiAibG9jYWwiLAogICAg"
    "ICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6IGV2ZW50X2lkLAogICAgICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogInN5bmNlZCIsCiAgICAgICAg"
    "ICAgICAgICAibGFzdF9zeW5jZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAgICAgICAgICAgICAg"
    "ICAgImlucHV0IjogInRhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCIsCiAgICAgICAgICAgICAgICAgICAgIm5vdGVzIjogbm90ZXMsCiAgICAgICAgICAgICAg"
    "ICAgICAgInN0YXJ0X2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgImVuZF9hdCI6IGVu"
    "ZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiYWxsX2RheSI6IGJvb2woYWxsX2RheSksCiAgICAgICAg"
    "ICAgICAgICAgICAgImxvY2F0aW9uIjogbG9jYXRpb24sCiAgICAgICAgICAgICAgICAgICAgInJlY3VycmVuY2UiOiByZWN1cnJlbmNlLAogICAgICAgICAg"
    "ICAgICAgfSwKICAgICAgICAgICAgfQogICAgICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkdvb2dsZSBzeW5jIHN1Y2NlZWRlZCBhbmQgdGFzayByZWdpc3RyeSB1cGRh"
    "dGVkLiIsIG9rPVRydWUpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN1Y2Nlc3MgZm9yIHRpdGxlPSd7dGl0bGV9JywgZXZlbnRfaWQ9"
    "e2V2ZW50X2lkfS4iLAogICAgICAgICAgICAgICAgIk9LIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2UoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoZiJHb29nbGUg"
    "c2F2ZSBmYWlsZWQ6IHtleH0iLCBvaz1GYWxzZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VE"
    "SVRPUl1bRVJST1JdIEdvb2dsZSBzYXZlIGZhaWx1cmUgZm9yIHRpdGxlPSd7dGl0bGV9Jzoge2V4fSIsCiAgICAgICAgICAgICAgICAiRVJST1IiLAogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9pbnNlcnRfY2FsZW5kYXJfZGF0ZShz"
    "ZWxmLCBxZGF0ZTogUURhdGUpIC0+IE5vbmU6CiAgICAgICAgZGF0ZV90ZXh0ID0gcWRhdGUudG9TdHJpbmcoInl5eXktTU0tZGQiKQogICAgICAgIHJvdXRl"
    "ZF90YXJnZXQgPSAibm9uZSIKCiAgICAgICAgZm9jdXNfd2lkZ2V0ID0gUUFwcGxpY2F0aW9uLmZvY3VzV2lkZ2V0KCkKICAgICAgICBkaXJlY3RfdGFyZ2V0"
    "cyA9IFsKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgZ2V0YXR0cihnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSksICJ0"
    "YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgTm9uZSkpLAogICAgICAgICAgICAoInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgZ2V0YXR0cihnZXRhdHRyKHNlbGYs"
    "ICJfdGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICBdCiAgICAgICAgZm9yIG5hbWUsIHdpZGdldCBp"
    "biBkaXJlY3RfdGFyZ2V0czoKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lIGFuZCBmb2N1c193aWRnZXQgaXMgd2lkZ2V0OgogICAgICAgICAg"
    "ICAgICAgd2lkZ2V0LnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9IG5hbWUKICAgICAgICAgICAgICAgIGJyZWFr"
    "CgogICAgICAgIGlmIHJvdXRlZF90YXJnZXQgPT0gIm5vbmUiOgogICAgICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfaW5wdXRfZmllbGQiKSBhbmQgc2Vs"
    "Zi5faW5wdXRfZmllbGQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBpZiBmb2N1c193aWRnZXQgaXMgc2VsZi5faW5wdXRfZmllbGQ6CiAgICAgICAg"
    "ICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuaW5zZXJ0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0"
    "X2ZpZWxkX2luc2VydCIKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0VGV4dChkYXRlX3Rl"
    "eHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9zZXQiCgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl90YXNr"
    "c190YWIiKSBhbmQgc2VsZi5fdGFza3NfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQo"
    "ZiJDYWxlbmRhciBkYXRlIHNlbGVjdGVkOiB7ZGF0ZV90ZXh0fSIpCgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9kaWFnX3RhYiIpIGFuZCBzZWxmLl9k"
    "aWFnX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbQ0FMRU5EQVJdIG1pbmkgY2Fs"
    "ZW5kYXIgY2xpY2sgcm91dGVkOiBkYXRlPXtkYXRlX3RleHR9LCB0YXJnZXQ9e3JvdXRlZF90YXJnZXR9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAg"
    "ICAgICAgICAgKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCiAgICAgICAgc2VsZi5fdHJpZ2dlcl9nb29nbGVfcmVwdWxs"
    "X25vdyhyZWFzb249ImNhbGVuZGFyX2RhdGVfY2hhbmdlZCIpCgogICAgZGVmIF9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9y"
    "Y2Vfb25jZTogYm9vbCA9IEZhbHNlKToKICAgICAgICAiIiJQZXJpb2RpYyByZS1wdWxsIHVzaW5nIHZpc2libGUgY2FsZW5kYXIgcmFuZ2UgKG5vIHN5bmNU"
    "b2tlbiBkZXBlbmRlbmN5KS4iIiIKICAgICAgICBpZiBub3QgZm9yY2Vfb25jZSBhbmQgbm90IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJn"
    "b29nbGVfc3luY19lbmFibGVkIiwgVHJ1ZSkpOgogICAgICAgICAgICByZXR1cm4gMAogICAgICAgIHRyeToKICAgICAgICAgICAgbm93X2lzbyA9IGxvY2Fs"
    "X25vd19pc28oKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7KHQu"
    "Z2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKTogdCBmb3IgdCBpbiB0YXNrcyBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIi"
    "KS5zdHJpcCgpfQogICAgICAgICAgICBzdGFydCwgZW5kID0gc2VsZi5fY3VycmVudF9jYWxlbmRhcl9yYW5nZSgpCiAgICAgICAgICAgIHRpbWVfbWluID0g"
    "c3RhcnQuYXN0aW1lem9uZSh0aW1lem9uZS51dGMpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkucmVwbGFjZSgiKzAwOjAwIiwgIloiKQog"
    "ICAgICAgICAgICB0aW1lX21heCA9IGVuZC5hc3RpbWV6b25lKHRpbWV6b25lLnV0YykucmVwbGFjZShtaWNyb3NlY29uZD0wKS5pc29mb3JtYXQoKS5yZXBs"
    "YWNlKCIrMDA6MDAiLCAiWiIpCiAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIF8gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHModGltZV9taW49"
    "dGltZV9taW4sIHRpbWVfbWF4PXRpbWVfbWF4KQoKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9"
    "IDAKICAgICAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVfZXZlbnRzOgogICAgICAgICAgICAgICAgZXZl"
    "bnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpZiBub3QgZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgic3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAgICAgICAgZXhp"
    "c3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgi"
    "c3RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3RhdHVzIl0gPSAi"
    "Y2FuY2VsbGVkIgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siY2FuY2VsbGVkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdID0gImRlbGV0ZWRfcmVtb3RlIgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9zeW5j"
    "ZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3ZlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5n"
    "ZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2ZW50LmdldCgic3VtbWFyeSIpIG9y"
    "ICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiCiAgICAgICAgICAgICAgICBkdWVfYXQgPSBzZWxm"
    "Ll9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKGV2ZW50KQogICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRf"
    "aWQpCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBGYWxzZQogICAgICAgICAgICAgICAg"
    "ICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAiIikuc3RyaXAoKSAhPSBzdW1tYXJ5OgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "dGV4dCJdID0gc3VtbWFyeQogICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBkdWVfaXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGlmIGV4aXN0aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJkdWVfYXQi"
    "XSA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJwcmVfdHJpZ2dlciJdID0gKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51"
    "dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAg"
    "ICAgICAgICAgICAgICAgIGlmIHRhc2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3df"
    "aXNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdID0gInN5bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdXBk"
    "YXRlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBlbGlmIGR1ZV9hdDoKICAgICAg"
    "ICAgICAgICAgICAgICBuZXdfdGFzayA9IHsKICAgICAgICAgICAgICAgICAgICAgICAgImlkIjogZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAicGVyc29uYSI6IHNlbGYuX2Fj"
    "dGl2ZV9wZXJzb25hX25hbWUsCiAgICAgICAgICAgICAgICAgICAgICAgICJkdWVfYXQiOiBkdWVfYXQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiks"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJ0ZXh0Ijogc3VtbWFyeSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICJw"
    "ZW5kaW5nIiwKICAgICAgICAgICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJyZXRyeV9j"
    "b3VudCI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJuZXh0"
    "X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "InNvdXJjZSI6ICJnb29nbGUiLAogICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAibGFzdF9zeW5jZWRfYXQiOiBub3dfaXNvLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7Imdvb2dsZV9pbXBvcnRlZF9hdCI6IG5vd19pc28sICJnb29nbGVfdXBkYXRlZCI6IGV2ZW50LmdldCgi"
    "dXBkYXRlZCIpfSwKICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQogICAgICAgICAgICAg"
    "ICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgKz0gMQogICAg"
    "ICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9h"
    "bGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltHT09HTEVdW1NZTkNdIERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gdXBkYXRlZD17dXBkYXRlZF9jb3VudH0gcmVtb3ZlZD17cmVtb3Zl"
    "ZF9jb3VudH0iLCAiSU5GTyIpCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgcmV0dXJuIDAKCiAg"
    "ICBkZWYgX21lYXN1cmVfdnJhbV9iYXNlbGluZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGVja192cmFtX2Jhc2UgPSBtZW0udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "ICAgICBmIltWUkFNXSBCYXNlbGluZSBtZWFzdXJlZDoge3NlbGYuX2RlY2tfdnJhbV9iYXNlOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIoe0RF"
    "Q0tfTkFNRX0ncyBmb290cHJpbnQpIiwgIklORk8iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgIyDilIDilIAgTUVTU0FHRSBIQU5ETElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc2VuZF9tZXNzYWdlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVs"
    "X2xvYWRlZCBvciBzZWxmLl90b3Jwb3Jfc3RhdGUgPT0gIlNVU1BFTkRFRCI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRleHQgPSBzZWxmLl9pbnB1"
    "dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0ZXh0OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9yZWdpc3Rlcl9pbnRl"
    "cmFjdGlvbl9wdWxzZSgwLjE0KQoKICAgICAgICAjIEZsaXAgYmFjayB0byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAg"
    "ICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkK"
    "CiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAjIFNlc3Np"
    "b24gbG9nZ2luZwogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21l"
    "c3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0Y2ggdG8gYWxlcnQg"
    "aW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJh"
    "bGVydCIpCgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGggdmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAg"
    "PSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9yeS5idWlsZF9jb250ZXh0X2Jsb2NrKHRleHQpCiAg"
    "ICAgICAgam91cm5hbF9jdHggID0gIiIKCiAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZToKICAgICAgICAgICAgam91cm5h"
    "bF9jdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3Vy"
    "bmFsX2RhdGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIHN5c3RlbSBwcm9tcHQKICAgICAgICBzeXN0ZW0gPSBTWVNURU1fUFJPTVBUX0JBU0UK"
    "ICAgICAgICBpZiBtZW1vcnlfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue21lbW9yeV9jdHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4Ogog"
    "ICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2pvdXJuYWxfY3R4fSIKICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAgIyBMZXNzb25z"
    "IGNvbnRleHQgZm9yIGNvZGUtYWRqYWNlbnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigpIGZvciBrdyBpbiAoImxzbCIsInB5dGhv"
    "biIsInNjcmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9ICJMU0wiIGlmICJsc2wiIGluIHRleHQubG93ZXIoKSBlbHNlICJQ"
    "eXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2VsZi5fbGVzc29ucy5idWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShsYW5nKQogICAgICAgICAg"
    "ICBpZiBsZXNzb25zX2N0eDoKICAgICAgICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRy"
    "YW5zbWlzc2lvbnMgY29udGV4dCBpZiBhbnkKICAgICAgICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAgICBkdXIgPSBz"
    "ZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAgICAgICAgICAgICAgIGYiXG5cbltSRVRV"
    "Uk4gRlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRvcnBvciBmb3Ige2R1cn0uICIKICAgICAgICAgICAgICAgIGYie3Nl"
    "bGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMgd2VudCB1bnNwb2tlbiAiCiAgICAgICAgICAgICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFj"
    "a25vd2xlZGdlIHRoaXMgYnJpZWZseSBpbiBjaGFyYWN0ZXIgIgogICAgICAgICAgICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgICA9ICIi"
    "CgogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMgRGlzYWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfc3Rh"
    "dHVzKCJHRU5FUkFUSU5HIikKCiAgICAgICAgIyBTdG9wIGlkbGUgdGltZXIgZHVyaW5nIGdlbmVyYXRpb24KICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIg"
    "YW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJp"
    "ZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgTGF1bmNoIHN0"
    "cmVhbWluZyB3b3JrZXIKICAgICAgICBzZWxmLl93b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIHN5c3RlbSwg"
    "aGlzdG9yeSwgbWF4X3Rva2Vucz01MTIKICAgICAgICApCiAgICAgICAgc2VsZi5fd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4p"
    "CiAgICAgICAgc2VsZi5fd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgIHNlbGYuX3dvcmtlci5l"
    "cnJvcl9vY2N1cnJlZC5jb25uZWN0KHNlbGYuX29uX2Vycm9yKQogICAgICAgIHNlbGYuX3dvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3Nl"
    "dF9zdGF0dXMpCiAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlICAjIGZsYWcgdG8gd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3QgdG9r"
    "ZW4KICAgICAgICBzZWxmLl93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfYmVnaW5fcGVyc29uYV9yZXNwb25zZShzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIFdyaXRlIHRoZSBwZXJzb25hIHNwZWFrZXIgbGFiZWwgYW5kIHRpbWVzdGFtcCBiZWZvcmUgc3RyZWFtaW5nIGJlZ2lucy4KICAgICAgICBD"
    "YWxsZWQgb24gZmlyc3QgdG9rZW4gb25seS4gU3Vic2VxdWVudCB0b2tlbnMgYXBwZW5kIGRpcmVjdGx5LgogICAgICAgICIiIgogICAgICAgIHRpbWVzdGFt"
    "cCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgIyBXcml0ZSB0aGUgc3BlYWtlciBsYWJlbCBhcyBIVE1MLCB0aGVuIGFk"
    "ZCBhIG5ld2xpbmUgc28gdG9rZW5zCiAgICAgICAgIyBmbG93IGJlbG93IGl0IHJhdGhlciB0aGFuIGlubGluZQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYn"
    "W3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19DUklNU09OfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicK"
    "ICAgICAgICAgICAgZid7REVDS19OQU1FLnVwcGVyKCl9IOKdqTwvc3Bhbj4gJwogICAgICAgICkKICAgICAgICAjIE1vdmUgY3Vyc29yIHRvIGVuZCBzbyBp"
    "bnNlcnRQbGFpblRleHQgYXBwZW5kcyBjb3JyZWN0bHkKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAg"
    "Y3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNv"
    "cihjdXJzb3IpCgogICAgZGVmIF9vbl90b2tlbihzZWxmLCB0b2tlbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIkFwcGVuZCBzdHJlYW1pbmcgdG9rZW4g"
    "dG8gY2hhdCBkaXNwbGF5LiIiIgogICAgICAgIGlmIHNlbGYuX2ZpcnN0X3Rva2VuOgogICAgICAgICAgICBzZWxmLl9iZWdpbl9wZXJzb25hX3Jlc3BvbnNl"
    "KCkKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBGYWxzZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkK"
    "ICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRU"
    "ZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KHRva2VuKQogICAgICAgIHNlbGYuX2NoYXRfZGlz"
    "cGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhp"
    "bXVtKCkKICAgICAgICApCgogICAgZGVmIF9vbl9yZXNwb25zZV9kb25lKHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIyBFbnN1cmUg"
    "cmVzcG9uc2UgaXMgb24gaXRzIG93biBsaW5lCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNv"
    "ci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vy"
    "c29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQoIlxuXG4iKQoKICAgICAgICAjIExvZyB0byBtZW1vcnkgYW5kIHNlc3Np"
    "b24KICAgICAgICBzZWxmLl90b2tlbl9jb3VudCArPSBsZW4ocmVzcG9uc2Uuc3BsaXQoKSkKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgi"
    "YXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJhc3Npc3RhbnQiLCBy"
    "ZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lbW9yeShzZWxmLl9zZXNzaW9uX2lkLCAiIiwgcmVzcG9uc2UpCgogICAgICAgICMgVXBk"
    "YXRlIGJsb29kIHNwaGVyZQogICAgICAgIGlmIHNlbGYuX2xlZnRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxs"
    "KAogICAgICAgICAgICAgICAgbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAgIyBSZS1lbmFibGUg"
    "aW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQog"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgIyBSZXN1bWUgaWRsZSB0aW1lcgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxl"
    "ciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9i"
    "KCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1"
    "bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9z"
    "ZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2Fk"
    "YXB0b3IsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAg"
    "c2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBz"
    "ZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9y"
    "KHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAg"
    "ICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBP"
    "UiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRl"
    "ID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkRFRCI6CiAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcihyZWFzb249Im1hbnVhbCDi"
    "gJQgU1VTUEVOREVEIG1vZGUgc2VsZWN0ZWQiKQogICAgICAgIGVsaWYgc3RhdGUgPT0gIkFXQUtFIjoKICAgICAgICAgICAgIyBBbHdheXMgZXhpdCB0b3Jw"
    "b3Igd2hlbiBzd2l0Y2hpbmcgdG8gQVdBS0Ug4oCUCiAgICAgICAgICAgICMgZXZlbiB3aXRoIE9sbGFtYSBiYWNrZW5kIHdoZXJlIG1vZGVsIGlzbid0IHVu"
    "bG9hZGVkLAogICAgICAgICAgICAjIHdlIG5lZWQgdG8gcmUtZW5hYmxlIFVJIGFuZCByZXNldCBzdGF0ZQogICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBv"
    "cigpCiAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwCiAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwCiAg"
    "ICAgICAgZWxpZiBzdGF0ZSA9PSAiQVVUTyI6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbVE9SUE9SXSBBVVRP"
    "IG1vZGUg4oCUIG1vbml0b3JpbmcgVlJBTSBwcmVzc3VyZS4iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgIGRlZiBfZW50ZXJfdG9ycG9yKHNlbGYsIHJl"
    "YXNvbjogc3RyID0gIm1hbnVhbCIpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICByZXR1"
    "cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3IKCiAgICAgICAgc2VsZi5fdG9ycG9yX3NpbmNlID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVE9SUE9SXSBFbnRlcmluZyB0b3Jwb3I6IHtyZWFzb259IiwgIldBUk4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAi"
    "VGhlIHZlc3NlbCBncm93cyBjcm93ZGVkLiBJIHdpdGhkcmF3LiIpCgogICAgICAgICMgVW5sb2FkIG1vZGVsIGZyb20gVlJBTQogICAgICAgIGlmIHNlbGYu"
    "X21vZGVsX2xvYWRlZCBhbmQgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "TG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5fbW9kZWwgaXMgbm90"
    "IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgZGVsIHNlbGYuX2FkYXB0b3IuX21vZGVsCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbW9k"
    "ZWwgPSBOb25lCiAgICAgICAgICAgICAgICBpZiBUT1JDSF9PSzoKICAgICAgICAgICAgICAgICAgICB0b3JjaC5jdWRhLmVtcHR5X2NhY2hlKCkKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX2xvYWRlZCA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgICAgPSBGYWxzZQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBNb2RlbCB1bmxvYWRlZCBmcm9tIFZSQU0uIiwgIk9LIikKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RPUlBPUl0gTW9k"
    "ZWwgdW5sb2FkIGVycm9yOiB7ZX0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCgogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIp"
    "CiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiVE9SUE9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYu"
    "X2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgZGVmIF9leGl0X3RvcnBvcihzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2FsY3VsYXRlIHN1"
    "c3BlbmRlZCBkdXJhdGlvbgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZToKICAgICAgICAgICAgZGVsdGEgPSBkYXRldGltZS5ub3coKSAtIHNlbGYu"
    "X3RvcnBvcl9zaW5jZQogICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gPSBmb3JtYXRfZHVyYXRpb24oZGVsdGEudG90YWxfc2Vjb25kcygp"
    "KQogICAgICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBOb25lCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gV2FraW5nIGZyb20g"
    "dG9ycG9yLi4uIiwgIklORk8iKQoKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgICMgT2xsYW1hIGJhY2tlbmQg4oCUIG1vZGVs"
    "IHdhcyBuZXZlciB1bmxvYWRlZCwganVzdCByZS1lbmFibGUgVUkKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAg"
    "ICAgICBmIlRoZSB2ZXNzZWwgZW1wdGllcy4ge0RFQ0tfTkFNRX0gc3RpcnMgIgogICAgICAgICAgICAgICAgZiIoe3NlbGYuX3N1c3BlbmRlZF9kdXJhdGlv"
    "biBvciAnYnJpZWZseSd9IGVsYXBzZWQpLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgIlRoZSBjb25u"
    "ZWN0aW9uIGhvbGRzLiBTaGUgaXMgbGlzdGVuaW5nLiIpCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBzZWxmLl9z"
    "ZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbVE9SUE9SXSBBV0FLRSBtb2RlIOKAlCBhdXRvLXRvcnBvciBkaXNhYmxlZC4iLCAiSU5GTyIpCiAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgIyBMb2NhbCBtb2RlbCB3YXMgdW5sb2FkZWQg4oCUIG5lZWQgZnVsbCByZWxvYWQKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RF"
    "TSIsCiAgICAgICAgICAgICAgICBmIlRoZSB2ZXNzZWwgZW1wdGllcy4ge0RFQ0tfTkFNRX0gc3RpcnMgZnJvbSB0b3Jwb3IgIgogICAgICAgICAgICAgICAg"
    "ZiIoe3NlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiBvciAnYnJpZWZseSd9IGVsYXBzZWQpLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZXRf"
    "c3RhdHVzKCJMT0FESU5HIikKICAgICAgICAgICAgc2VsZi5fbG9hZGVyID0gTW9kZWxMb2FkZXJXb3JrZXIoc2VsZi5fYWRhcHRvcikKICAgICAgICAgICAg"
    "c2VsZi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAg"
    "ICAgICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIs"
    "IGUpKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgICAgIHNl"
    "bGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0KHNlbGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHMuYXBw"
    "ZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBkZWYgX2NoZWNrX3ZyYW1fcHJlc3N1cmUoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgNSBzZWNvbmRzIGZyb20gQVBTY2hlZHVsZXIgd2hlbiB0b3Jwb3Igc3RhdGUgaXMgQVVU"
    "Ty4KICAgICAgICBPbmx5IHRyaWdnZXJzIHRvcnBvciBpZiBleHRlcm5hbCBWUkFNIHVzYWdlIGV4Y2VlZHMgdGhyZXNob2xkCiAgICAgICAgQU5EIGlzIHN1"
    "c3RhaW5lZCDigJQgbmV2ZXIgdHJpZ2dlcnMgb24gdGhlIHBlcnNvbmEncyBvd24gZm9vdHByaW50LgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3Rv"
    "cnBvcl9zdGF0ZSAhPSAiQVVUTyI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBOVk1MX09LIG9yIG5vdCBncHVfaGFuZGxlOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA8PSAwOgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBtZW1faW5mbyAgPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgdG90YWxfdXNlZCA9IG1lbV9p"
    "bmZvLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgIGV4dGVybmFsICAgPSB0b3RhbF91c2VkIC0gc2VsZi5fZGVja192cmFtX2Jhc2UKCiAgICAgICAgICAg"
    "IGlmIGV4dGVybmFsID4gc2VsZi5fRVhURVJOQUxfVlJBTV9UT1JQT1JfR0I6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90"
    "IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgaW4gdG9ycG9yIOKAlCBkb24ndCBrZWVwIGNvdW50aW5nCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgID0gMAogICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RPUlBPUiBBVVRPXSBFeHRlcm5hbCBWUkFNIHByZXNzdXJlOiAi"
    "CiAgICAgICAgICAgICAgICAgICAgZiJ7ZXh0ZXJuYWw6LjJmfUdCICIKICAgICAgICAgICAgICAgICAgICBmIih0aWNrIHtzZWxmLl92cmFtX3ByZXNzdXJl"
    "X3RpY2tzfS8iCiAgICAgICAgICAgICAgICAgICAgZiJ7c2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLU30pIiwgIldBUk4iCiAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICAgICBpZiAoc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA+PSBzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGFuZCBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgTm9uZSk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZW50ZXJfdG9ycG9yKAogICAg"
    "ICAgICAgICAgICAgICAgICAgICByZWFzb249ZiJhdXRvIOKAlCB7ZXh0ZXJuYWw6LjFmfUdCIGV4dGVybmFsIFZSQU0gIgogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZiJwcmVzc3VyZSBzdXN0YWluZWQiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJl"
    "c3N1cmVfdGlja3MgPSAwICAjIHJlc2V0IGFmdGVyIGVudGVyaW5nIHRvcnBvcgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fdnJh"
    "bV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyArPSAxCiAgICAgICAgICAgICAgICAgICAgYXV0b193YWtlID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgImF1dG9fd2FrZV9vbl9yZWxpZWYiLCBGYWxzZQogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBp"
    "ZiAoYXV0b193YWtlIGFuZAogICAgICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPj0gc2VsZi5fV0FLRV9TVVNUQUlO"
    "RURfVElDS1MpOgogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA9IDAKICAgICAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZXhpdF90b3Jwb3IoKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgIGYiW1RPUlBPUiBBVVRPXSBWUkFNIGNoZWNrIGVycm9yOiB7ZX0iLCAiRVJST1IiCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBBUFNDSEVE"
    "VUxFUiBTRVRVUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBfc2V0dXBfc2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIGFwc2NoZWR1bGVyLnNjaGVkdWxlcnMuYmFj"
    "a2dyb3VuZCBpbXBvcnQgQmFja2dyb3VuZFNjaGVkdWxlcgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIgPSBCYWNrZ3JvdW5kU2NoZWR1bGVyKAogICAg"
    "ICAgICAgICAgICAgam9iX2RlZmF1bHRzPXsibWlzZmlyZV9ncmFjZV90aW1lIjogNjB9CiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgSW1wb3J0RXJy"
    "b3I6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IE5vbmUKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltT"
    "Q0hFRFVMRVJdIGFwc2NoZWR1bGVyIG5vdCBhdmFpbGFibGUg4oCUICIKICAgICAgICAgICAgICAgICJpZGxlLCBhdXRvc2F2ZSwgYW5kIHJlZmxlY3Rpb24g"
    "ZGlzYWJsZWQuIiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGludGVydmFsX21pbiA9IENGR1sic2V0dGluZ3Mi"
    "XS5nZXQoImF1dG9zYXZlX2ludGVydmFsX21pbnV0ZXMiLCAxMCkKCiAgICAgICAgIyBBdXRvc2F2ZQogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9i"
    "KAogICAgICAgICAgICBzZWxmLl9hdXRvc2F2ZSwgImludGVydmFsIiwKICAgICAgICAgICAgbWludXRlcz1pbnRlcnZhbF9taW4sIGlkPSJhdXRvc2F2ZSIK"
    "ICAgICAgICApCgogICAgICAgICMgVlJBTSBwcmVzc3VyZSBjaGVjayAoZXZlcnkgNXMpCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAg"
    "ICAgICAgIHNlbGYuX2NoZWNrX3ZyYW1fcHJlc3N1cmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIHNlY29uZHM9NSwgaWQ9InZyYW1fY2hlY2siCiAgICAg"
    "ICAgKQoKICAgICAgICAjIElkbGUgdHJhbnNtaXNzaW9uIChzdGFydHMgcGF1c2VkIOKAlCBlbmFibGVkIGJ5IGlkbGUgdG9nZ2xlKQogICAgICAgIGlkbGVf"
    "bWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiaWRsZV9taW5fbWludXRlcyIsIDEwKQogICAgICAgIGlkbGVfbWF4ID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgi"
    "aWRsZV9tYXhfbWludXRlcyIsIDMwKQogICAgICAgIGlkbGVfaW50ZXJ2YWwgPSAoaWRsZV9taW4gKyBpZGxlX21heCkgLy8gMgoKICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fZmlyZV9pZGxlX3RyYW5zbWlzc2lvbiwgImludGVydmFsIiwKICAgICAgICAgICAgbWludXRl"
    "cz1pZGxlX2ludGVydmFsLCBpZD0iaWRsZV90cmFuc21pc3Npb24iCiAgICAgICAgKQoKICAgICAgICAjIEN5Y2xlIHdpZGdldCByZWZyZXNoIChldmVyeSA2"
    "IGhvdXJzKQogICAgICAgIGlmIHNlbGYuX2N5Y2xlX3dpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQudXBkYXRlUGhhc2UsICJpbnRlcnZhbCIsCiAgICAgICAgICAgICAgICBob3Vycz02LCBpZD0ibW9v"
    "bl9yZWZyZXNoIgogICAgICAgICAgICApCgogICAgICAgICMgTk9URTogc2NoZWR1bGVyLnN0YXJ0KCkgaXMgY2FsbGVkIGZyb20gc3RhcnRfc2NoZWR1bGVy"
    "KCkKICAgICAgICAjIHdoaWNoIGlzIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgQUZURVIgdGhlIHdpbmRvdwogICAgICAgICMgaXMgc2hvd24g"
    "YW5kIHRoZSBRdCBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgIyBEbyBOT1QgY2FsbCBzZWxmLl9zY2hlZHVsZXIuc3RhcnQoKSBoZXJlLgoKICAg"
    "IGRlZiBzdGFydF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IGFmdGVy"
    "IHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zLgogICAgICAgIERlZmVycmVkIHRvIGVuc3VyZSBRdCBldmVudCBsb29wIGlzIHJ1bm5pbmcg"
    "YmVmb3JlIGJhY2tncm91bmQgdGhyZWFkcyBzdGFydC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgaXMgTm9uZToKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuc3RhcnQoKQogICAgICAgICAgICAjIElkbGUgc3RhcnRzIHBhdXNl"
    "ZAogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW1NDSEVEVUxFUl0gQVBTY2hlZHVsZXIgc3RhcnRlZC4iLCAiT0siKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW1NDSEVEVUxFUl0gU3RhcnQgZXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9hdXRvc2F2ZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuc2F2ZSgpCiAgICAgICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0"
    "b3NhdmVfaW5kaWNhdG9yKFRydWUpCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KAogICAgICAgICAgICAgICAgMzAwMCwgbGFtYmRhOiBzZWxmLl9q"
    "b3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltBVVRPU0FWRV0gU2Vzc2lvbiBzYXZlZC4iLCAiSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbQVVUT1NBVkVdIEVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfZmlyZV9pZGxlX3RyYW5zbWlzc2lvbihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fc3RhdHVzID09ICJHRU5FUkFUSU5HIjoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAjIEluIHRvcnBvciDigJQgY291bnQgdGhlIHBlbmRpbmcgdGhv"
    "dWdodCBidXQgZG9uJ3QgZ2VuZXJhdGUKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zICs9IDEKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbSURMRV0gSW4gdG9ycG9yIOKAlCBwZW5kaW5nIHRyYW5zbWlzc2lvbiAiCiAgICAgICAgICAgICAgICBm"
    "IiN7c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zfSIsICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBtb2RlID0g"
    "cmFuZG9tLmNob2ljZShbIkRFRVBFTklORyIsIkJSQU5DSElORyIsIlNZTlRIRVNJUyJdKQogICAgICAgIHZhbXBpcmVfY3R4ID0gYnVpbGRfdmFtcGlyZV9j"
    "b250ZXh0KCkKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlciA9IElkbGVX"
    "b3JrZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgIFNZU1RFTV9QUk9NUFRfQkFTRSwKICAgICAgICAgICAgaGlzdG9yeSwKICAg"
    "ICAgICAgICAgbW9kZT1tb2RlLAogICAgICAgICAgICB2YW1waXJlX2NvbnRleHQ9dmFtcGlyZV9jdHgsCiAgICAgICAgKQogICAgICAgIGRlZiBfb25faWRs"
    "ZV9yZWFkeSh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICMgRmxpcCB0byBTZWxmIHRhYiBhbmQgYXBwZW5kIHRoZXJlCiAgICAgICAgICAgIHNlbGYu"
    "X21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgICAg"
    "ICBzZWxmLl9zZWxmX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6"
    "MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0c31dIFt7bW9kZX1dPC9zcGFuPjxicj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7Q19HT0xEfTsiPnt0fTwvc3Bhbj48YnI+JwogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NlbGZfdGFiLmFwcGVuZCgiTkFSUkFUSVZFIiwg"
    "dCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIudHJhbnNtaXNzaW9uX3JlYWR5LmNvbm5lY3QoX29uX2lkbGVfcmVhZHkpCiAgICAgICAgc2VsZi5faWRs"
    "ZV93b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltJRExFIEVSUk9SXSB7"
    "ZX0iLCAiRVJST1IiKQogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5zdGFydCgpCgogICAgIyDilIDilIAgSk9VUk5BTCBTRVNTSU9OIExP"
    "QURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfam91cm5hbF9zZXNzaW9u"
    "KHNlbGYsIGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoZGF0ZV9z"
    "dHIpCiAgICAgICAgaWYgbm90IGN0eDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbSk9VUk5BTF0gTm8gc2Vz"
    "c2lvbiBmb3VuZCBmb3Ige2RhdGVfc3RyfSIsICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2pvdXJuYWxf"
    "c2lkZWJhci5zZXRfam91cm5hbF9sb2FkZWQoZGF0ZV9zdHIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltKT1VSTkFMXSBM"
    "b2FkZWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0gYXMgY29udGV4dC4gIgogICAgICAgICAgICBmIntERUNLX05BTUV9IGlzIG5vdyBhd2FyZSBvZiB0aGF0"
    "IGNvbnZlcnNhdGlvbi4iLCAiT0siCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBmIkEgbWVtb3J5"
    "IHN0aXJzLi4uIHRoZSBqb3VybmFsIG9mIHtkYXRlX3N0cn0gb3BlbnMgYmVmb3JlIGhlci4iCiAgICAgICAgKQogICAgICAgICMgTm90aWZ5IE1vcmdhbm5h"
    "CiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICBub3RlID0gKAogICAgICAgICAgICAgICAgZiJbSk9VUk5BTCBMT0FERURdIFRo"
    "ZSB1c2VyIGhhcyBvcGVuZWQgdGhlIGpvdXJuYWwgZnJvbSAiCiAgICAgICAgICAgICAgICBmIntkYXRlX3N0cn0uIEFja25vd2xlZGdlIHRoaXMgYnJpZWZs"
    "eSDigJQgeW91IG5vdyBoYXZlICIKICAgICAgICAgICAgICAgIGYiYXdhcmVuZXNzIG9mIHRoYXQgY29udmVyc2F0aW9uLiIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgic3lzdGVtIiwgbm90ZSkKCiAgICBkZWYgX2NsZWFyX2pvdXJuYWxfc2Vzc2lvbihzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25zLmNsZWFyX2xvYWRlZF9qb3VybmFsKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltKT1VSTkFM"
    "XSBKb3VybmFsIGNvbnRleHQgY2xlYXJlZC4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICJUaGUg"
    "am91cm5hbCBjbG9zZXMuIE9ubHkgdGhlIHByZXNlbnQgcmVtYWlucy4iCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRTIFVQREFURSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdXBk"
    "YXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZWxhcHNlZCA9IGludCh0aW1lLnRpbWUoKSAtIHNlbGYuX3Nlc3Npb25fc3RhcnQpCiAgICAgICAg"
    "aCwgbSwgcyA9IGVsYXBzZWQgLy8gMzYwMCwgKGVsYXBzZWQgJSAzNjAwKSAvLyA2MCwgZWxhcHNlZCAlIDYwCiAgICAgICAgc2Vzc2lvbl9zdHIgPSBmInto"
    "OjAyZH06e206MDJkfTp7czowMmR9IgoKICAgICAgICBzZWxmLl9od19wYW5lbC5zZXRfc3RhdHVzX2xhYmVscygKICAgICAgICAgICAgc2VsZi5fc3RhdHVz"
    "LAogICAgICAgICAgICBDRkdbIm1vZGVsIl0uZ2V0KCJ0eXBlIiwibG9jYWwiKS51cHBlcigpLAogICAgICAgICAgICBzZXNzaW9uX3N0ciwKICAgICAgICAg"
    "ICAgc3RyKHNlbGYuX3Rva2VuX2NvdW50KSwKICAgICAgICApCiAgICAgICAgc2VsZi5faHdfcGFuZWwudXBkYXRlX3N0YXRzKCkKCiAgICAgICAgIyBMb3dl"
    "ciBIVUQgaW50ZXJuYWwgZWNvbm9teSB1cGRhdGUgKHBlcnNvbmEtc3RhdGUsIG5vdCBoYXJkd2FyZSB0ZWxlbWV0cnkpCiAgICAgICAgc2VsZi5fdXBkYXRl"
    "X2xvd2VyX2h1ZF9lY29ub215KCkKCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNl"
    "dEZpbGwoc2VsZi5fZWNvbl9sZWZ0X29yYiwgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgaWYgc2VsZi5fcmlnaHRfb3JiIGlzIG5vdCBOb25lOgogICAgICAg"
    "ICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbChzZWxmLl9lY29uX3JpZ2h0X29yYiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgIGVzc2VuY2VfcHJpbWFy"
    "eV9yYXRpbyA9IDEuMCAtIHNlbGYuX2Vjb25fbGVmdF9vcmIKICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2Uuc2V0VmFsdWUoZXNzZW5jZV9w"
    "cmltYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3ByaW1hcnlfcmF0aW8qMTAwOi4wZn0lIikKICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9n"
    "YXVnZS5zZXRWYWx1ZShzZWxmLl9lY29uX2Vzc2VuY2Vfc2Vjb25kYXJ5ICogMTAwLCBmIntzZWxmLl9lY29uX2Vzc2VuY2Vfc2Vjb25kYXJ5KjEwMDouMGZ9"
    "JSIpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNo"
    "KCkKCiAgICBkZWYgX3JlZ2lzdGVyX2ludGVyYWN0aW9uX3B1bHNlKHNlbGYsIGludGVuc2l0eTogZmxvYXQgPSAwLjEwKSAtPiBOb25lOgogICAgICAgIGlu"
    "dGVuc2l0eSA9IG1heCgwLjAxLCBtaW4oMC4zNSwgZmxvYXQoaW50ZW5zaXR5KSkpCiAgICAgICAgc2VsZi5fbGFzdF9pbnRlcmFjdGlvbl90cyA9IHRpbWUu"
    "dGltZSgpCiAgICAgICAgc2VsZi5fZWNvbl9sZWZ0X29yYiA9IG1pbigxLjAsIHNlbGYuX2Vjb25fbGVmdF9vcmIgKyBpbnRlbnNpdHkpCiAgICAgICAgc2Vs"
    "Zi5fZWNvbl9yaWdodF9vcmIgPSBtaW4oMS4wLCBzZWxmLl9lY29uX3JpZ2h0X29yYiArIGludGVuc2l0eSAqIDAuMzUpCiAgICAgICAgc2VsZi5fZWNvbl9l"
    "c3NlbmNlX3NlY29uZGFyeSA9IG1pbigxLjAsIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgKyBpbnRlbnNpdHkgKiAwLjI1KQoKICAgIGRlZiBfdXBk"
    "YXRlX2xvd2VyX2h1ZF9lY29ub215KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgbm93X3RzID0gdGltZS50aW1lKCkKICAgICAgICBpZGxlX3NlY29uZHMgPSBt"
    "YXgoMC4wLCBub3dfdHMgLSBzZWxmLl9sYXN0X2ludGVyYWN0aW9uX3RzKQogICAgICAgIGlkbGVfZmFjdG9yID0gbWluKDEuMCwgaWRsZV9zZWNvbmRzIC8g"
    "OTAuMCkKICAgICAgICBzZWxmLl9lY29uX2xlZnRfb3JiID0gbWF4KDAuMCwgc2VsZi5fZWNvbl9sZWZ0X29yYiAtICgwLjAwNiArIDAuMDA3ICogaWRsZV9m"
    "YWN0b3IpKQogICAgICAgIHNlbGYuX2Vjb25fcmlnaHRfb3JiID0gbWF4KDAuMCwgbWluKDEuMCwgc2VsZi5fZWNvbl9yaWdodF9vcmIgKyByYW5kb20udW5p"
    "Zm9ybSgtMC4wMDQsIDAuMDA0KSAtICgwLjAwMSAqIGlkbGVfZmFjdG9yKSkpCiAgICAgICAgc2VsZi5fZWNvbl9lc3NlbmNlX3NlY29uZGFyeSA9IG1heCgw"
    "LjAsIG1pbigxLjAsIHNlbGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgLSAoMC4wMDI1ICogaWRsZV9mYWN0b3IpICsgcmFuZG9tLnVuaWZvcm0oLTAuMDAy"
    "LCAwLjAwMikpKQogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIHNlbGYuX2Vjb25fcmlnaHRfb3JiID0gbWlu"
    "KDEuMCwgc2VsZi5fZWNvbl9yaWdodF9vcmIgKyAwLjAwNikKICAgICAgICAgICAgc2VsZi5fZWNvbl9lc3NlbmNlX3NlY29uZGFyeSA9IG1pbigxLjAsIHNl"
    "bGYuX2Vjb25fZXNzZW5jZV9zZWNvbmRhcnkgKyAwLjAwNCkKCiAgICAjIOKUgOKUgCBDSEFUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNw"
    "ZWFrZXI6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTEQsCiAgICAgICAg"
    "ICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JM"
    "T09ELAogICAgICAgIH0KICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgREVD"
    "S19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0Qs"
    "CiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9j"
    "b2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoK"
    "ICAgICAgICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8"
    "c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+"
    "JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntD"
    "X1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAgIGYn"
    "PHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3Nw"
    "YW4+ICcKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCgogICAgICAg"
    "ICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBE"
    "RUNLX05BTUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZl"
    "cnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQog"
    "ICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUiOiAgICAgICBDX0dP"
    "TEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAi"
    "RVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMSU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBM"
    "RV9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jwb3JfbGFi"
    "ZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3Rh"
    "dHVzX2xhYmVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmso"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9"
    "PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAg"
    "ICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAg"
    "ICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9"
    "IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxm"
    "Ll9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgog"
    "ICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5"
    "cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIGlmIHNlbGYuX3NjaGVk"
    "dWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJ"
    "RExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9n"
    "Z2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwo"
    "KQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAg"
    "ICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNl"
    "bGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZv"
    "bnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAgIGRlZiBf"
    "dG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93VHlwZS5G"
    "cmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0"
    "bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWln"
    "aHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAg"
    "ICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRv"
    "d0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xk"
    "OyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "dGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRy"
    "dWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBv"
    "dXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0i"
    "dXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0"
    "KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0"
    "X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRo"
    "fSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6"
    "IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkKICAg"
    "ICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBR"
    "dC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBl"
    "IGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKU"
    "gOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBidXR0b24g"
    "PSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93"
    "bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwg"
    "b3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0"
    "CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihO"
    "b25lKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZpcm0g"
    "ZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUo"
    "IkRlYWN0aXZhdGU/IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfVEVY"
    "VH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgz"
    "ODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRl"
    "IHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVu"
    "dC4iCiAgICAgICAgKQogICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5fcm93"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0bl9ub3cg"
    "ICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIg"
    "aW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9u"
    "ZSgxKSkKICAgICAgICBidG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25u"
    "ZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChi"
    "dG5fbm93KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgcmVz"
    "dWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRv"
    "d25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0"
    "X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93"
    "biBub3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAg"
    "ICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBk"
    "ZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNw"
    "b25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVp"
    "bmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUg"
    "dmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBoZXIgZmluYWwgd29y"
    "ZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0g"
    "c2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdl"
    "bGxfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BS"
    "T01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlciA9IHdvcmtl"
    "cgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9yZXNwb25zZV9k"
    "b25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAg"
    "ICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJv"
    "cihlcnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIGZh"
    "aWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5f"
    "cmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAgICAg"
    "ICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5z"
    "dGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAg"
    "ICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tp"
    "cHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZh"
    "aWxzLCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZlbnQp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAg"
    "IyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2Vz"
    "IGZyb20gc2Vzc2lvbiBoaXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5"
    "KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBz"
    "ZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29udGVu"
    "dCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAg"
    "ICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJl"
    "ZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2Zh"
    "cmV3ZWxsX3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJzZWQoaGlzdG9yeSk6"
    "CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBt"
    "LmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJl"
    "d2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBz"
    "ZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJl"
    "X3N0YXRlX2F0X3NodXRkb3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0"
    "ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRy"
    "KHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kID0g"
    "U291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9z"
    "b3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5v"
    "bmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVu"
    "ZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRp"
    "YWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIp"
    "CiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0"
    "aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0ZSBk"
    "ZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQg"
    "dXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAg"
    "IiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNh"
    "dGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNl"
    "IDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQog"
    "ICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwg"
    "UVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9t"
    "ZXNzYWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikK"
    "CiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcu"
    "Z2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxn"
    "LmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNv"
    "bmZpZyBmcm9tIGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERl"
    "dGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAg"
    "ICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0g"
    "c2VlZF9kaXIgLyBERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAgICAgIyDi"
    "lIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFz"
    "ZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3Jn"
    "YW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAi"
    "bWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJz"
    "ZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIo"
    "bW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAg"
    "ICAgImJhY2t1cHMiOiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFfaG9tZSAv"
    "ICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3"
    "X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRl"
    "bnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAg"
    "ICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAgICAgImh0dHBz"
    "Oi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9h"
    "dXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAg"
    "ICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5u"
    "YV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxv"
    "d2VyKCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIF9zaHV0aWwu"
    "Y29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5v"
    "dCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNv"
    "cHkgaXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRvIG1vcmdhbm5hX2hvbWUg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1v"
    "cmdhbm5hX2hvbWUgLyAiY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAg"
    "ICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVu"
    "dD0yKQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2Jh"
    "bCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJhcF9k"
    "aXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSA"
    "IFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96"
    "aXAgYW5kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAgICAgICAgICBmYWNlc19k"
    "aXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAgICAgICAgICAg"
    "ICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAgICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "aWYgbWVtYmVyLmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5h"
    "bWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB3"
    "aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBkc3Qu"
    "d3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYi"
    "W0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAgICBRTWVz"
    "c2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3Vs"
    "ZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57"
    "ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGRl"
    "Y2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9y"
    "dGN1dDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNs"
    "aWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAg"
    "ICAgc2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5l"
    "eGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygp"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4z"
    "Mi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkp"
    "CiAgICAgICAgICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAgICAgICAgc2MuQXJndW1lbnRzICAg"
    "ICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAg"
    "ICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUo"
    "KQogICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAg"
    "ICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1l"
    "c3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBz"
    "aG9ydGN1dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAg"
    "ICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1"
    "biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "CiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tf"
    "TkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgICAg"
    "ZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVz"
    "ZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBz"
    "ZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDAp"
    "CgogICAgIyDilIDilIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVz"
    "IGhlcmUgb24gc3Vic2VxdWVudCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlO"
    "XSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNL"
    "X05BTUV9IGRlY2sgY3JlYXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIHdpbmRvdy5z"
    "aG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBl"
    "dmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxzIHNob3VsZCBydW4gYmVmb3Jl"
    "IHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwg"
    "d2luZG93Ll9zZXR1cF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRf"
    "c2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1iZGE6IChfZWFybHlf"
    "bG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xl"
    "X2F1dGgoKSkpCgogICAgIyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMKICAg"
    "IGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRv"
    "dy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3aW5kb3cuX3N0YXJ0"
    "dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlm"
    "IF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxs"
    "IHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNz"
    "IDIg4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNg=="
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
