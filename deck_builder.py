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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNITyBE"
    "RUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJT04KIyBHZW5lcmF0ZWQgYnkgZGVja19idWlsZGVyLnB5CiMgQWxs"
    "IHBlcnNvbmEgdmFsdWVzIGluamVjdGVkIGZyb20gREVDS19URU1QTEFURSBoZWFkZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09V"
    "TkQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoK"
    "CmltcG9ydCBzeXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCBtYXRoCmltcG9ydCB0aW1lCmltcG9ydCB3YXZl"
    "CmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5nCmltcG9ydCB1cmxsaWIucmVxdWVzdApp"
    "bXBvcnQgdXVpZApmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpm"
    "cm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJvbSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsLCBJdGVyYXRvcgoKIyDilIDi"
    "lIAgRUFSTFkgQ1JBU0ggTE9HR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEhvb2tzIGluIGJlZm9yZSBR"
    "dCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFMTCBvdXRwdXQgaW5jbHVkaW5nCiMgQysrIGxldmVsIFF0IG1l"
    "c3NhZ2VzLiBXcml0dGVuIHRvIFtEZWNrTmFtZV0vbG9ncy9zdGFydHVwLmxvZwojIFRoaXMgc3RheXMgYWN0aXZlIGZv"
    "ciB0aGUgbGlmZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJMWV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlfTE9HX1BB"
    "VEg6IE9wdGlvbmFsW1BhdGhdID0gTm9uZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+IE5vbmU6CiAgICB0cyA9"
    "IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzotM10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNn"
    "fSIKICAgIF9FQVJMWV9MT0dfTElORVMuYXBwZW5kKGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQogICAg"
    "aWYgX0VBUkxZX0xPR19QQVRIOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3Bl"
    "bigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBmLndyaXRlKGxpbmUgKyAiXG4iKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCmRlZiBfaW5pdF9lYXJseV9sb2coYmFzZV9k"
    "aXI6IFBhdGgpIC0+IE5vbmU6CiAgICBnbG9iYWwgX0VBUkxZX0xPR19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIg"
    "LyAibG9ncyIKICAgIGxvZ19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xP"
    "R19QQVRIID0gbG9nX2RpciAvIGYic3RhcnR1cF97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMn"
    "KX0ubG9nIgogICAgIyBGbHVzaCBidWZmZXJlZCBsaW5lcwogICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigidyIs"
    "IGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIGxpbmUgaW4gX0VBUkxZX0xPR19MSU5FUzoKICAgICAg"
    "ICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKCmRlZiBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKSAtPiBOb25l"
    "OgogICAgIiIiCiAgICBJbnRlcmNlcHQgQUxMIFF0IG1lc3NhZ2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2FybmluZ3Mu"
    "CiAgICBUaGlzIGNhdGNoZXMgdGhlIFFUaHJlYWQgZGVzdHJveWVkIG1lc3NhZ2UgYXQgdGhlIHNvdXJjZSBhbmQgbG9n"
    "cyBpdAogICAgd2l0aCBhIGZ1bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cgZXhhY3RseSB3aGljaCB0aHJlYWQgYW5kIHdo"
    "ZXJlLgogICAgIiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNz"
    "YWdlSGFuZGxlciwgUXRNc2dUeXBlCiAgICAgICAgaW1wb3J0IHRyYWNlYmFjawoKICAgICAgICBkZWYgcXRfbWVzc2Fn"
    "ZV9oYW5kbGVyKG1zZ190eXBlLCBjb250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAgbGV2ZWwgPSB7CiAgICAgICAg"
    "ICAgICAgICBRdE1zZ1R5cGUuUXREZWJ1Z01zZzogICAgIlFUX0RFQlVHIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlw"
    "ZS5RdEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRXYXJuaW5nTXNnOiAg"
    "IlFUX1dBUk5JTkciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0Q3JpdGljYWxNc2c6ICJRVF9DUklUSUNBTCIs"
    "CiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRGYXRhbE1zZzogICAgIlFUX0ZBVEFMIiwKICAgICAgICAgICAgfS5n"
    "ZXQobXNnX3R5cGUsICJRVF9VTktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0gIiIKICAgICAgICAgICAgaWYg"
    "Y29udGV4dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmlsZX06e2NvbnRleHQu"
    "bGluZX1dIgoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2NhdGlvbn0ge21lc3NhZ2V9IikKCiAg"
    "ICAgICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxvZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAg"
    "ICBpZiAiUVRocmVhZCIgaW4gbWVzc2FnZSBvciAidGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAgICAgICAgICAg"
    "ICAgICBzdGFjayA9ICIiLmpvaW4odHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5"
    "X2xvZyhmIltTVEFDSyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3RhbGxNZXNzYWdl"
    "SGFuZGxlcihxdF9tZXNzYWdlX2hhbmRsZXIpCiAgICAgICAgX2Vhcmx5X2xvZygiW0lOSVRdIFF0IG1lc3NhZ2UgaGFu"
    "ZGxlciBpbnN0YWxsZWQiKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIF9lYXJseV9sb2coZiJbSU5J"
    "VF0gQ291bGQgbm90IGluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyOiB7ZX0iKQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7"
    "REVDS19OQU1FfSBkZWNrIHN0YXJ0aW5nIikKX2Vhcmx5X2xvZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNw"
    "bGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJsZX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFdvcmtpbmcgZGlyZWN0b3J5"
    "OiB7b3MuZ2V0Y3dkKCl9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBTY3JpcHQgbG9jYXRpb246IHtQYXRoKF9fZmlsZV9f"
    "KS5yZXNvbHZlKCl9IikKCiMg4pSA4pSAIE9QVElPTkFMIERFUEVOREVOQ1kgR1VBUkRTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKUFNVVElMX09L"
    "ID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElMX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygi"
    "W0lNUE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9S"
    "VF0gcHN1dGlsIEZBSUxFRDoge2V9IikKCk5WTUxfT0sgPSBGYWxzZQpncHVfaGFuZGxlID0gTm9uZQp0cnk6CiAgICBp"
    "bXBvcnQgd2FybmluZ3MKICAgIHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToKICAgICAgICB3YXJuaW5ncy5z"
    "aW1wbGVmaWx0ZXIoImlnbm9yZSIpCiAgICAgICAgaW1wb3J0IHB5bnZtbAogICAgcHludm1sLm52bWxJbml0KCkKICAg"
    "IGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VHZXRDb3VudCgpCiAgICBpZiBjb3VudCA+IDA6CiAgICAgICAgZ3B1X2hh"
    "bmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxlQnlJbmRleCgwKQogICAgICAgIE5WTUxfT0sgPSBUcnVlCiAg"
    "ICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIE9LIOKAlCB7Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgRkFJTEVEOiB7ZX0iKQoKVE9SQ0hfT0sgPSBG"
    "YWxzZQp0cnk6CiAgICBpbXBvcnQgdG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JD"
    "YXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0g"
    "dG9yY2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xv"
    "ZyhmIltJTVBPUlRdIHRvcmNoIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sgPSBGYWxzZQp0cnk6CiAg"
    "ICBpbXBvcnQgd2luMzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRd"
    "IHdpbjMyY29tIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2lu"
    "MzJjb20gRkFJTEVEOiB7ZX0iKQoKV0lOU09VTkRfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luc291bmQKICAg"
    "IFdJTlNPVU5EX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1w"
    "b3J0RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKTog"
    "e2V9IikKClBZR0FNRV9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5taXhlci5pbml0"
    "KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHB5Z2FtZSBPSyIpCmV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xF"
    "X09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZhbHNlICAjIGFsaWFzIHVzZWQgYnkgR29vZ2xlIHNlcnZpY2UgY2xh"
    "c3NlcwpHT09HTEVfSU1QT1JUX0VSUk9SID0gTm9uZQp0cnk6CiAgICBmcm9tIGdvb2dsZS5hdXRoLnRyYW5zcG9ydC5y"
    "ZXF1ZXN0cyBpbXBvcnQgUmVxdWVzdCBhcyBHb29nbGVBdXRoUmVxdWVzdAogICAgZnJvbSBnb29nbGUub2F1dGgyLmNy"
    "ZWRlbnRpYWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVkZW50aWFscwogICAgZnJvbSBnb29nbGVfYXV0"
    "aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0YWxsZWRBcHBGbG93CiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5kaXNj"
    "b3ZlcnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2dsZV9idWlsZAogICAgZnJvbSBnb29nbGVhcGljbGllbnQuZXJyb3JzIGlt"
    "cG9ydCBIdHRwRXJyb3IgYXMgR29vZ2xlSHR0cEVycm9yCiAgICBHT09HTEVfT0sgPSBUcnVlCiAgICBHT09HTEVfQVBJ"
    "X09LID0gVHJ1ZQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgX2U6CiAgICBHT09HTEVfSU1QT1JUX0VSUk9SID0gc3RyKF9l"
    "KQogICAgR29vZ2xlSHR0cEVycm9yID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVTID0gWwogICAgImh0dHBzOi8vd3d3"
    "Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgv"
    "Y2FsZW5kYXIuZXZlbnRzIiwKICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICJo"
    "dHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCl0KR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cg"
    "PSAoCiAgICAiR29vZ2xlIHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3IgaW5jb21wYXRpYmxlIHdpdGggcmVxdWVz"
    "dGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29uIGFuZCByZWF1dGhvcml6ZSB3aXRoIHRoZSB1cGRhdGVk"
    "IHNjb3BlIGxpc3QuIgopCkRFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUgPSAiQW1lcmljYS9DaGljYWdvIgpXSU5E"
    "T1dTX1RaX1RPX0lBTkEgPSB7CiAgICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2FnbyIsCiAg"
    "ICAiRWFzdGVybiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRhcmQg"
    "VGltZSI6ICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAgICJNb3VudGFpbiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2Ev"
    "RGVudmVyIiwKfQoKCiMg4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFpbldpbmRv"
    "dywgUVdpZGdldCwgUVZCb3hMYXlvdXQsIFFIQm94TGF5b3V0LAogICAgUUdyaWRMYXlvdXQsIFFUZXh0RWRpdCwgUUxp"
    "bmVFZGl0LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBRRnJhbWUsCiAgICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdpZGdl"
    "dCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRlclZpZXcsCiAgICBRQWJzdHJhY3RJdGVtVmlldywgUVN0YWNrZWRXaWRn"
    "ZXQsIFFUYWJXaWRnZXQsIFFMaXN0V2lkZ2V0LAogICAgUUxpc3RXaWRnZXRJdGVtLCBRU2l6ZVBvbGljeSwgUUNvbWJv"
    "Qm94LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3NhZ2VCb3gsIFFEYXRlRWRpdCwgUURpYWxvZywgUUZv"
    "cm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNwbGl0dGVyLCBRSW5wdXREaWFsb2csIFFUb29sQnV0dG9uCikKZnJv"
    "bSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNp"
    "emUsIFFQb2ludCwgUVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQ"
    "YWludGVyLCBRTGluZWFyR3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQYWludGVy"
    "UGF0aCwgUVRleHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9uCikKCiMg4pSA4pSAIEFQ"
    "UCBJREVOVElUWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUg"
    "ICAgICA9IFVJX1dJTkRPV19USVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4wIgpBUFBfRklMRU5BTUUgID0gZiJ7REVD"
    "S19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0wNCIKCiMg4pSA4pSAIENPTkZJ"
    "RyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29u"
    "IGxpdmVzIG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcuIE5vdGhp"
    "bmcgaGFyZGNvZGVkIGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgp"
    "LnBhcmVudApDT05GSUdfUEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkg"
    "bG9nIG5vdyB0aGF0IHdlIGtub3cgd2hlcmUgd2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlf"
    "bG9nKGYiW0lOSVRdIFNDUklQVF9ESVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIENPTkZJR19Q"
    "QVRIID0ge0NPTkZJR19QQVRIfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3RzOiB7Q09ORklH"
    "X1BBVEguZXhpc3RzKCl9IikKCmRlZiBfZGVmYXVsdF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUg"
    "ZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBmaXJzdC1ydW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIo"
    "U0NSSVBUX0RJUikKICAgIHJldHVybiB7CiAgICAgICAgImRlY2tfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVj"
    "a192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGlyIjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7"
    "CiAgICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8IG9sbGFtYSB8IGNsYXVkZSB8IG9w"
    "ZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAgICMgbG9jYWwgbW9kZWwgZm9sZGVyIHBhdGgK"
    "ICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4gImRvbHBoaW4tMi42LTdiIgogICAgICAg"
    "ICAgICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAgImFw"
    "aV90eXBlIjogIiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2RlbCI6"
    "ICIiLCAgICAgICAgICAjIGUuZy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAgICAgICAgImdvb2dsZSI6"
    "IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3Jl"
    "ZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUi"
    "IC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAg"
    "ICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9j"
    "YWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJp"
    "dmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAg"
    "ICAgICAgICAgXSwKICAgICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3Ry"
    "KFNDUklQVF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIgLyAic291"
    "bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiksCiAgICAgICAg"
    "ICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAg"
    "IHN0cihTQ1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4"
    "cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAg"
    "ICAiYmFja3VwcyI6ICBzdHIoU0NSSVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0"
    "cihTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8g"
    "Imdvb2dsZSIpLAogICAgICAgIH0sCiAgICAgICAgInNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9lbmFibGVk"
    "IjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiaWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAog"
    "ICAgICAgICAgICAiaWRsZV9tYXhfbWludXRlcyI6ICAgICAgICAgIDMwLAogICAgICAgICAgICAiYXV0b3NhdmVfaW50"
    "ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAogICAg"
    "ICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRydWUsCiAgICAgICAgICAgICJzb3VuZF9lbmFibGVk"
    "IjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIjogMzAwMDAw"
    "LAogICAgICAgICAgICAiZ29vZ2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxh"
    "eV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUsCiAgICB9Cgpk"
    "ZWYgbG9hZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4gUmV0dXJucyBkZWZhdWx0IGlm"
    "IG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdfUEFUSC5leGlzdHMoKToKICAgICAgICByZXR1"
    "cm4gX2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAgICAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNv"
    "ZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNhdmVfY29uZmlnKGNmZzogZGljdCkgLT4g"
    "Tm9uZToKICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1rZGlyKHBhcmVu"
    "dHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYt"
    "OCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywgZiwgaW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0IG1vZHVs"
    "ZSBsZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9tIENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJs"
    "eV9sb2coZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1v"
    "ZGVsX3R5cGU9e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BBVEhTOiBkaWN0W3N0"
    "ciwgUGF0aF0gPSB7CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJzb3VuZHMiOiAgIFND"
    "UklQVF9ESVIgLyAic291bmRzIiwKICAgICJtZW1vcmllcyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAogICAgInNl"
    "c3Npb25zIjogU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJUFRfRElSIC8gInNsIiwK"
    "ICAgICJleHBvcnRzIjogIFNDUklQVF9ESVIgLyAiZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElSIC8g"
    "ImxvZ3MiLAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAvICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQ"
    "VF9ESVIgLyAicGVyc29uYXMiLAogICAgImdvb2dsZSI6ICAgU0NSSVBUX0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25v"
    "cm1hbGl6ZV9jb25maWdfcGF0aHMoKSAtPiBOb25lOgogICAgIiIiCiAgICBTZWxmLWhlYWwgb2xkZXIgY29uZmlnLmpz"
    "b24gZmlsZXMgbWlzc2luZyByZXF1aXJlZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBu"
    "b3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lzdHMgY29uZmln"
    "Lmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgogICAgY2hhbmdlZCA9IEZhbHNlCiAgICBwYXRocyA9IENG"
    "Ry5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVmYXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhT"
    "Lml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdldChrZXkpOgogICAgICAgICAgICBwYXRoc1trZXldID0gc3Ry"
    "KGRlZmF1bHRfcGF0aCkKICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVfY2ZnID0gQ0ZHLnNldGRl"
    "ZmF1bHQoImdvb2dsZSIsIHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xlIiwgc3RyKF9E"
    "RUZBVUxUX1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0cihnb29nbGVfcm9vdCAvICJnb29n"
    "bGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290IC8gInRva2VuLmpz"
    "b24iKQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSkuc3RyaXAoKQog"
    "ICAgdG9rZW5fdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tlbiIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBj"
    "cmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVkc192YWwgYW5kICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIgaW4g"
    "Y3JlZHNfdmFsKToKICAgICAgICBnb29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVmYXVsdF9jcmVkcwogICAgICAg"
    "IGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3QgdG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBk"
    "ZWZhdWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29u"
    "ZmlnKENGRykKCmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQgYSBw"
    "YXRoIGZyb20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVs"
    "dHMuIiIiCiAgICBwYXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAgICB2YWx1ZSA9IHBhdGhzLmdldChrZXkpCiAg"
    "ICBpZiB2YWx1ZToKICAgICAgICByZXR1cm4gUGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMu"
    "Z2V0KGtleSkKICAgIGlmIGZhbGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAg"
    "cmV0dXJuIGZhbGxiYWNrCiAgICByZXR1cm4gU0NSSVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMo"
    "KQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBDX1BSSU1BUlksIENfU0VDT05EQVJZLCBDX0FDQ0VOVCwgQ19CRywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19U"
    "RVhULCBDX1RFWFRfRElNIGFyZSBpbmplY3RlZCBhdCB0aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIu"
    "CiMgRXZlcnl0aGluZyBiZWxvdyBpcyBkZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoKIyBTZW1hbnRp"
    "YyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xvcnMgdG8gbmFtZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRoZSBV"
    "SQpDX0NSSU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAgICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMs"
    "IGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0gPSBDX1BSSU1BUlkgKyAiODgiICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0"
    "bGUgYm9yZGVycwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMgbWFpbiBsYWJlbC90ZXh0L0FJIG91"
    "dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGltIHNlY29uZGFyeQpDX0dPTERf"
    "QlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMgZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpDX1NJTFZFUiAgICAgID0g"
    "Q19URVhUX0RJTSAgICAgICAgICMgc2Vjb25kYXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJTSAg"
    "PSBDX1RFWFRfRElNICsgIjg4IiAgIyBkaW0gc2Vjb25kYXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENfQkcgICAgICAg"
    "ICAgICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAgICAgID0g"
    "Q19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAgICA9IENfUEFORUwgICAg"
    "ICAgICAgICAjIHRlcnRpYXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkxPT0QgICAgICAg"
    "PSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBzdGF0ZXMsIGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAg"
    "ICAgPSAnIzg4NTVjYycgICAgICAgICAgIyBTWVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBMRV9ESU0g"
    "ID0gJyMyYTA1MmEnICAgICAgICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0"
    "YWE2NicgICAgICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4"
    "Y2MnICAgICAgICAgICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNhbAoKIyBGb250IGhlbHBlciDigJQgZXh0cmFjdHMg"
    "cHJpbWFyeSBmb250IG5hbWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlfRk9OVF9GQU1JTFkuc3BsaXQo"
    "JywnKVswXS5zdHJpcCgpLnN0cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24g"
    "cmVjb3JkIGNoaXBzKQpFTU9USU9OX0NPTE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6ICAgIENf"
    "R09MRCwKICAgICJzbXVnIjogICAgICAgQ19HT0xELAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2"
    "ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6ICAgICAgQ19HT0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAg"
    "ICAicGFuaWNrZWQiOiAgIENfQ1JJTVNPTiwKICAgICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2NrZWQi"
    "OiAgICBDX0NSSU1TT04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAgICJjb25jZXJuZWQiOiAgIiNjYzY2"
    "MjIiLAogICAgInNhZCI6ICAgICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRlZCI6ICIjY2M2NjIyIiwKICAgICJm"
    "bHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjogICBDX1BVUlBMRSwKICAgICJzdXNwaWNpb3VzIjog"
    "Q19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENfUFVSUExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJTFZFUiwKICAg"
    "ICJhbGVydCI6ICAgICAgQ19TSUxWRVIsCiAgICAibmV1dHJhbCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERF"
    "Q09SQVRJVkUgQ09OU1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlzIHNvdXJjZWQgZnJvbSBV"
    "SV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVTCgojIEZhY2UgaW1h"
    "Z2UgbWFwIOKAlCBwcmVmaXggZnJvbSBGQUNFX1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFjZXMK"
    "RkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9OZXV0"
    "cmFsLnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVydC5wbmciLAogICAgImZvY3VzZWQi"
    "OiAgICBmIntGQUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1f"
    "U211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIsCiAgICAic2Fk"
    "IjogICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQiOiAgIGYie0ZBQ0Vf"
    "UFJFRklYfV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBmIntGQUNFX1BSRUZJWH1fSW1wcmVzc2VkLnBu"
    "ZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJFRklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxpYXRlZCI6"
    "IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlhdGVkLnBuZyIsCiAgICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9T"
    "dXNwaWNpb3VzLnBuZyIsCiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAg"
    "ImNoZWF0bW9kZSI6ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBmIntG"
    "QUNFX1BSRUZJWH1fQW5ncnkucG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bsb3R0aW5nLnBu"
    "ZyIsCiAgICAic2hvY2tlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBuZyIsCiAgICAiaGFwcHkiOiAgICAg"
    "IGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmciLAogICAgImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5"
    "LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZBQ0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3Vz"
    "IjogICAgZiJ7RkFDRV9QUkVGSVh9X0VudmlvdXMucG5nIiwKfQoKU0VOVElNRU5UX0xJU1QgPSAoCiAgICAibmV1dHJh"
    "bCwgYWxlcnQsIGZvY3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZlZCwgaW1wcmVzc2VkLCAiCiAgICAi"
    "dmljdG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNrZWQsIGFuZ3J5LCBwbG90dGluZywgc2hvY2tlZCwg"
    "IgogICAgImhhcHB5LCBmbGlydHksIGZsdXN0ZXJlZCwgZW52aW91cyIKKQoKIyDilIDilIAgU1lTVEVNIFBST01QVCDi"
    "gJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBmaWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRfQkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJvdmUgZnJv"
    "bSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3QgcmVkZWZpbmUgaXQgaGVyZS4KCiMg4pSA4pSA"
    "IEdMT0JBTCBTVFlMRVNIRUVUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9IGYiIiIKUU1h"
    "aW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9yOiB7Q19HT0xE"
    "fTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRVGV4dEVkaXQge3sKICAgIGJhY2tncm91bmQt"
    "Y29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07"
    "CiAgICBmb250LXNpemU6IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xv"
    "cjoge0NfQ1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRp"
    "dXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxM3B4OwogICAg"
    "cGFkZGluZzogOHB4IDEycHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09M"
    "RH07CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5k"
    "LWNvbG9yOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHggMjBweDsK"
    "ICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQdXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9y"
    "OiB7Q19DUklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNzZWQge3sK"
    "ICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAgIGJvcmRlci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29s"
    "b3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkcz"
    "fTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9s"
    "bEJhcjp2ZXJ0aWNhbCB7ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAgIGJvcmRlcjog"
    "bm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2ZXJ0aWNhbDpob3ZlciB7ewog"
    "ICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xs"
    "QmFyOjpzdWItbGluZTp2ZXJ0aWNhbCB7ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6OnBhbmUge3sKICAg"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07Cn19ClFUYWJC"
    "YXI6OnRhYiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFtaWx5"
    "OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0K"
    "UVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjog"
    "e0NfR09MRH07CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRhYjpo"
    "b3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dPTERfRElNfTsKfX0KUVRhYmxl"
    "V2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZh"
    "bWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNl"
    "bGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9"
    "Owp9fQpRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19H"
    "T0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZv"
    "bnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307"
    "CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRk"
    "aW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFDb21ib0JveDo6ZHJvcC1k"
    "b3duIHt7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0JveCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9u"
    "dC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9y"
    "ZGVyOiBub25lOwp9fQpRU3BsaXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgd2lkdGg6IDJweDsKfX0KIiIiCgojIOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgogICAgQ3JlYXRlIGFs"
    "bCByZXF1aXJlZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAgQ2FsbGVkIG9uIHN0YXJ0dXAgYmVm"
    "b3JlIGFueXRoaW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFsc28gbWlncmF0ZXMgZmls"
    "ZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRpcnMg"
    "PSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2VzIiksCiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAgIGNm"
    "Z19wYXRoKCJtZW1vcmllcyIpLAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJz"
    "bCIpLAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAgICAgICBj"
    "ZmdfcGF0aCgiYmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAogICAgICAgIGNmZ19wYXRoKCJn"
    "b29nbGUiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0cyIsCiAgICBdCiAgICBmb3IgZCBpbiBk"
    "aXJzOgogICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5"
    "IEpTT05MIGZpbGVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMi"
    "KQogICAgZm9yIGZuYW1lIGluICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwi"
    "LAogICAgICAgICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIp"
    "OgogICAgICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAg"
    "ICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIp"
    "CiAgICBmb3IgZm5hbWUgaW4gKCJzbF9zY2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZw"
    "ID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3Rl"
    "eHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAg"
    "IGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgog"
    "ICAgICAgIGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGlu"
    "Zz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qgc3Rh"
    "dGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShzdGF0ZV9wYXRoKQoKICAgIGluZGV4"
    "X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZF"
    "UlNJT04sICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6"
    "IDB9LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgIyBMZWdhY3kg"
    "bWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxlcwogICAg"
    "X21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBOb25l"
    "OgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJz"
    "aW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAi"
    "OiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAog"
    "ICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50"
    "ZXJuYWxfbmFycmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIs"
    "CiAgICB9CiAgICBwYXRoLndyaXRlX3RleHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRm"
    "LTgiKQoKZGVmIF9taWdyYXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIKICAgIElmIG9sZCBEOlxcQUlc"
    "XE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdyYXRlIGZpbGVzIHRv"
    "IG5ldyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIKICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2"
    "ZSB0byBtb2RlbCBwYXRoCiAgICBtb2RlbF9wYXRoID0gUGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQog"
    "ICAgaWYgbm90IG1vZGVsX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCiAgICBvbGRfcm9vdCA9IG1vZGVsX3Bh"
    "dGgucGFyZW50IC8gZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToKICAg"
    "ICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJtZW1vcmllcy5qc29ubCIs"
    "ICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZW1vcmllcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9v"
    "dCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNv"
    "bmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFza3MuanNvbmwiLCAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpIC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInN0YXRlLmpzb24iLCAgICAgICAgICAg"
    "ICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gImluZGV4"
    "Lmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJpbmRleC5qc29uIiksCiAgICAgICAg"
    "KG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9zY2Fucy5q"
    "c29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29ubCIsICAgICAgICAgY2ZnX3BhdGgoInNs"
    "IikgLyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29u"
    "IiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsidG9rZW4iXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJjb25maWciIC8g"
    "Imdvb2dsZV9jcmVkZW50aWFscy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBQYXRoKENGR1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291"
    "bmRzIiAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIpLAog"
    "ICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAgICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90"
    "IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJl"
    "bnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAg"
    "ICBzaHV0aWwuY29weTIoc3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgcGFzcwoKICAgICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2ZhY2VzID0gb2xkX3Jvb3Qg"
    "LyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2ZhY2VzLmV4aXN0cygp"
    "OgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2VzLmdsb2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19m"
    "YWNlcyAvIGltZy5uYW1lCiAgICAgICAgICAgIGlmIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5Mihz"
    "dHIoaW1nKSwgc3RyKGRzdCkpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAg"
    "ICAgIHBhc3MKCiMg4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UobWlj"
    "cm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRp"
    "bWVdOgogICAgaWYgbm90IHZhbHVlOgogICAgICAgIHJldHVybiBOb25lCiAgICB2YWx1ZSA9IHZhbHVlLnN0cmlwKCkK"
    "ICAgIHRyeToKICAgICAgICBpZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICByZXR1cm4gZGF0ZXRpbWUu"
    "ZnJvbWlzb2Zvcm1hdCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAgICAgICAgcmV0dXJu"
    "IGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBO"
    "b25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBsZV0gPSBzZXQoKQoKCmRlZiBfbG9jYWxf"
    "dHppbmZvKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51"
    "dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkK"
    "CgpkZWYgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAg"
    "ICBpZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3QgaXNpbnN0YW5jZShkdF92"
    "YWx1ZSwgZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9sb2NhbF90emluZm8oKQog"
    "ICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5vbmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLnJlcGxhY2Uo"
    "dHppbmZvPWxvY2FsX3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0KQogICAgICAgIGlmIGtleSBub3Qg"
    "aW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUg"
    "Zm9yIHtjb250ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9E"
    "QVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBu"
    "b3JtYWxpemVkID0gZHRfdmFsdWUuYXN0aW1lem9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIoZHRfdmFs"
    "dWUudHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIsIGNvbnRleHQsIGR0X3R6X25hbWUpCiAgICBpZiBrZXkgbm90IGlu"
    "IF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBhbmQgZHRfdHpfbmFtZSBub3QgaW4geyJVVEMiLCBzdHIobG9j"
    "YWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXpl"
    "ZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmcm9tIHtkdF90el9uYW1lfSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2Nv"
    "bnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAgIF9EQVRFVElNRV9OT1JNQUxJ"
    "WkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2VfaXNvX2Zvcl9jb21w"
    "YXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21w"
    "YXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tfZHVlX3NvcnRfa2V5KHRhc2s6"
    "IGRpY3QpOgogICAgZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9y"
    "ICh0YXNrIG9yIHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6CiAg"
    "ICAgICAgcmV0dXJuICgxLCBkYXRldGltZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkKICAgIHJldHVy"
    "biAoMCwgZHVlLmFzdGltZXpvbmUodGltZXpvbmUudXRjKSwgKCh0YXNrIG9yIHt9KS5nZXQoInRleHQiKSBvciAiIiku"
    "bG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9uKHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9IG1h"
    "eCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCByZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJl"
    "bSA9IGRpdm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9kKHJlbSwgNjApCiAgICBwYXJ0cyA9"
    "IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5c31kIikKICAgIGlmIGhvdXJzOiAgIHBhcnRzLmFw"
    "cGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRzLmFwcGVuZChmInttaW51dGVzfW0iKQogICAgaWYg"
    "bm90IHBhcnRzOiBwYXJ0cy5hcHBlbmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10pCgoj"
    "IOKUgOKUgCBNT09OIFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ29ycmVjdGVk"
    "IGlsbHVtaW5hdGlvbiBtYXRoIOKAlCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05f"
    "TkVXX01PT04gPSBkYXRlKDIwMDAsIDEsIDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21v"
    "b25fcGhhc2UoKSAtPiB0dXBsZVtmbG9hdCwgc3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2Zy"
    "YWN0aW9uLCBwaGFzZV9uYW1lLCBpbGx1bWluYXRpb25fcGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9uOiAwLjAgPSBuZXcg"
    "bW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcgbW9vbiBhZ2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDi"
    "gJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwgcGhhc2UuCiAgICAiIiIKICAgIGRheXMgID0gKGRhdGUudG9k"
    "YXkoKSAtIF9LTk9XTl9ORVdfTU9PTikuZGF5cwogICAgY3ljbGUgPSBkYXlzICUgX0xVTkFSX0NZQ0xFCiAgICBwaGFz"
    "ZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8IDEuODU6ICAgbmFtZSA9ICJORVcgTU9PTiIK"
    "ICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVNDRU5UIgogICAgZWxpZiBjeWNsZSA8IDku"
    "MjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNsZSA8IDE0Ljc3OiAgbmFtZSA9ICJXQVhJTkcg"
    "R0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBjeWNsZSA8"
    "IDIyLjE1OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAiTEFT"
    "VCBRVUFSVEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NFTlQiCgogICAgIyBD"
    "b3JyZWN0ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9vbgogICAgaWxsdW1pbmF0aW9u"
    "ID0gKDEgLSBtYXRoLmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkgLyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5h"
    "bWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkKCl9TVU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25lCl9T"
    "VU5fQ0FDSEVfVFpfT0ZGU0VUX01JTjogT3B0aW9uYWxbaW50XSA9IE5vbmUKX1NVTl9DQUNIRV9USU1FUzogdHVwbGVb"
    "c3RyLCBzdHJdID0gKCIwNjowMCIsICIxODozMCIpCgpkZWYgX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0"
    "dXBsZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNvbHZlIGxhdGl0dWRlL2xvbmdpdHVkZSBmcm9tIHJ1bnRp"
    "bWUgY29uZmlnIHdoZW4gYXZhaWxhYmxlLgogICAgRmFsbHMgYmFjayB0byB0aW1lem9uZS1kZXJpdmVkIGNvYXJzZSBk"
    "ZWZhdWx0cy4KICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9uZQogICAgdHJ5OgogICAgICAgIHNldHRp"
    "bmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgICAg"
    "ICBmb3Iga2V5IGluICgibGF0aXR1ZGUiLCAibGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAg"
    "ICAgICAgICAgICAgIGxhdCA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgICAg"
    "IGZvciBrZXkgaW4gKCJsb25naXR1ZGUiLCAibG9uIiwgImxuZyIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGlu"
    "Z3M6CiAgICAgICAgICAgICAgICBsb24gPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsK"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgbGF0ID0gTm9uZQogICAgICAgIGxvbiA9IE5vbmUKCiAgICBub3df"
    "bG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHR6X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZz"
    "ZXQoKSBvciB0aW1lZGVsdGEoMCkKICAgIHR6X29mZnNldF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkg"
    "LyAzNjAwLjAKCiAgICBpZiBsb24gaXMgTm9uZToKICAgICAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIHR6"
    "X29mZnNldF9ob3VycyAqIDE1LjApKQoKICAgIGlmIGxhdCBpcyBOb25lOgogICAgICAgIHR6X25hbWUgPSBzdHIobm93"
    "X2xvY2FsLnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50ID0gYW55KHRva2VuIGluIHR6X25hbWUgZm9yIHRv"
    "a2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lmaWMvQXVja2xhbmQiLCAiQW1lcmljYS9TYW50aWFnbyIpKQogICAgICAg"
    "IGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0gbWF4KC02Ni4wLCBtaW4oNjYuMCwg"
    "bGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgbG9uKSkKICAgIHJldHVybiBsYXQsIGxvbgoKZGVm"
    "IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9jYWxfZGF5OiBkYXRlLCBsYXRpdHVkZTogZmxvYXQsIGxvbmdpdHVk"
    "ZTogZmxvYXQsIHN1bnJpc2U6IGJvb2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEtc3R5bGUgc3Vucmlz"
    "ZS9zdW5zZXQgc29sdmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJvbSBtaWRuaWdodC4iIiIKICAgIG4gPSBsb2Nh"
    "bF9kYXkudGltZXR1cGxlKCkudG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0ID0gbiAr"
    "ICgoNiAtIGxuZ19ob3VyKSAvIDI0LjApIGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxuZ19ob3VyKSAvIDI0LjAp"
    "CgogICAgTSA9ICgwLjk4NTYgKiB0KSAtIDMuMjg5CiAgICBMID0gTSArICgxLjkxNiAqIG1hdGguc2luKG1hdGgucmFk"
    "aWFucyhNKSkpICsgKDAuMDIwICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9"
    "IEwgJSAzNjAuMAoKICAgIFJBID0gbWF0aC5kZWdyZWVzKG1hdGguYXRhbigwLjkxNzY0ICogbWF0aC50YW4obWF0aC5y"
    "YWRpYW5zKEwpKSkpCiAgICBSQSA9IFJBICUgMzYwLjAKICAgIExfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihMIC8gOTAu"
    "MCkpICogOTAuMAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihSQSAvIDkwLjApKSAqIDkwLjAKICAgIFJBID0g"
    "KFJBICsgKExfcXVhZHJhbnQgLSBSQV9xdWFkcmFudCkpIC8gMTUuMAoKICAgIHNpbl9kZWMgPSAwLjM5NzgyICogbWF0"
    "aC5zaW4obWF0aC5yYWRpYW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGguYXNpbihzaW5fZGVjKSkKCiAg"
    "ICB6ZW5pdGggPSA5MC44MzMKICAgIGNvc19oID0gKG1hdGguY29zKG1hdGgucmFkaWFucyh6ZW5pdGgpKSAtIChzaW5f"
    "ZGVjICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0aC5y"
    "YWRpYW5zKGxhdGl0dWRlKSkpCiAgICBpZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCiAgICBpZiBzdW5yaXNlOgogICAgICAgIEggPSAzNjAuMCAtIG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29z"
    "X2gpKQogICAgZWxzZToKICAgICAgICBIID0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89IDE1"
    "LjAKCiAgICBUID0gSCArIFJBIC0gKDAuMDY1NzEgKiB0KSAtIDYuNjIyCiAgICBVVCA9IChUIC0gbG5nX2hvdXIpICUg"
    "MjQuMAoKICAgIGxvY2FsX29mZnNldF9ob3VycyA9IChkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudXRjb2Zmc2V0"
    "KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBs"
    "b2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAgcmV0dXJuIGxvY2FsX2hvdXIgKiA2MC4wCgpkZWYgX2Zvcm1hdF9s"
    "b2NhbF9zb2xhcl90aW1lKG1pbnV0ZXNfZnJvbV9taWRuaWdodDogT3B0aW9uYWxbZmxvYXRdKSAtPiBzdHI6CiAgICBp"
    "ZiBtaW51dGVzX2Zyb21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1cm4gIi0tOi0tIgogICAgbWlucyA9IGlu"
    "dChyb3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAlICgyNCAqIDYwKQogICAgaGgsIG1tID0gZGl2bW9kKG1pbnMs"
    "IDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRlPW1tLCBzZWNvbmQ9MCwg"
    "bWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4gdHVwbGVbc3RyLCBz"
    "dHJdOgogICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJpc2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBkYXRlICsgdGlt"
    "ZXpvbmUgYW5kIG9wdGlvbmFsCiAgICBydW50aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2YWlsYWJs"
    "ZS4KICAgIENhY2hlZCBwZXIgbG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0LgogICAgIiIiCiAgICBnbG9iYWwg"
    "X1NVTl9DQUNIRV9EQVRFLCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3df"
    "bG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRhdGUoKQogICAg"
    "dHpfb2Zmc2V0X21pbiA9IGludCgobm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vj"
    "b25kcygpIC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FDSEVfREFURSA9PSB0b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZT"
    "RVRfTUlOID09IHR6X29mZnNldF9taW46CiAgICAgICAgcmV0dXJuIF9TVU5fQ0FDSEVfVElNRVMKCiAgICB0cnk6CiAg"
    "ICAgICAgbGF0LCBsb24gPSBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpCiAgICAgICAgc3VucmlzZV9taW4gPSBf"
    "Y2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1UcnVlKQogICAgICAgIHN1bnNl"
    "dF9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1GYWxzZSkKICAg"
    "ICAgICBpZiBzdW5yaXNlX21pbiBpcyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiU29sYXIgZXZlbnQgdW5hdmFpbGFibGUgZm9yIHJlc29sdmVkIGNvb3JkaW5hdGVzIikKICAgICAg"
    "ICB0aW1lcyA9IChfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3VucmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFy"
    "X3RpbWUoc3Vuc2V0X21pbikpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIx"
    "ODozMCIpCgogICAgX1NVTl9DQUNIRV9EQVRFID0gdG9kYXkKICAgIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9IHR6"
    "X29mZnNldF9taW4KICAgIF9TVU5fQ0FDSEVfVElNRVMgPSB0aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBW"
    "QU1QSVJFIFNUQVRFIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBUaW1lLW9mLWRheSBiZWhhdmlvcmFs"
    "IHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19FTkFCTEVEPVRydWUuCiMgSW5qZWN0ZWQgaW50byBzeXN0"
    "ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRpb24gY2FsbC4KClZBTVBJUkVfU1RBVEVTOiBkaWN0W3N0ciwgZGljdF0g"
    "PSB7CiAgICAiV0lUQ0hJTkcgSE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAgImNvbG9yIjogQ19HT0xELCAg"
    "ICAgICAgInBvd2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjogICAgIHsiaG91cnMiOiB7MSwyLDN9LCAgICAgICAg"
    "ImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5HIjp7ImhvdXJz"
    "IjogezQsNX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6IDAuN30sCiAgICAiRE9STUFO"
    "VCI6ICAgICAgICB7ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6"
    "IDAuMn0sCiAgICAiUkVTVExFU1MgU0xFRVAiOiB7ImhvdXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVY"
    "VF9ESU0sICAgICJwb3dlciI6IDAuM30sCiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJzIjogezE2LDE3fSwgICAg"
    "ICAgICJjb2xvciI6IENfR09MRF9ESU0sICAgICJwb3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7Imhv"
    "dXJzIjogezE4LDE5LDIwLDIxfSwgICJjb2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAiSFVO"
    "VElORyI6ICAgICAgICB7ImhvdXJzIjogezIyLDIzfSwgICAgICAgICJjb2xvciI6IENfQ1JJTVNPTiwgICAgICJwb3dl"
    "ciI6IDEuMH0sCn0KCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgpIC0+IHN0cjoKICAgICIiIlJldHVybiB0aGUgY3VycmVu"
    "dCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5o"
    "b3VyCiAgICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBpbiBWQU1QSVJFX1NUQVRFUy5pdGVtcygpOgogICAgICAgIGlmIGgg"
    "aW4gZGF0YVsiaG91cnMiXToKICAgICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJldHVybiAiRE9STUFOVCIK"
    "CmRlZiBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzdGF0ZTogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gVkFNUElSRV9T"
    "VEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9ncmVldGlu"
    "Z3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENISU5HIEhPVVIiOiAgIGYie0RF"
    "Q0tfTkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIsCiAgICAgICAgIkRFRVAgTklH"
    "SFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVz"
    "dC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJTkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBhbmQgd2FpdGlu"
    "ZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlz"
    "IGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xF"
    "RVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwK"
    "ICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWluZyBhY3RpdmUgYW5kIHJlYWR5"
    "IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0"
    "aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tfTkFNRX0g"
    "aXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Npbmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3Rh"
    "dGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJB"
    "SV9TVEFURV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92aWRl"
    "ZC5rZXlzKCkpID09IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBkaWN0W3N0ciwgc3Ry"
    "XSA9IHt9CiAgICAgICAgZm9yIGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6CiAgICAgICAgICAgIHZhbCA9IHBy"
    "b3ZpZGVkLmdldChrZXkpCiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0"
    "cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAgICAgICAgICAg"
    "Y2xlYW5ba2V5XSA9ICIgIi5qb2luKHZhbC5zdHJpcCgpLnNwbGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICBy"
    "ZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3Ry"
    "OgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJpbmcgZm9y"
    "IHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5lcmF0aW9uLiBOZXZlciBj"
    "YWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAg"
    "IHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgcGhhc2UsIG1vb25fbmFtZSwgaWxs"
    "dW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBub3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQoKICAg"
    "IHN0YXRlX2ZsYXZvcnMgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3JzLmdl"
    "dChzdGF0ZSwgIiIpCgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4i"
    "CiAgICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYiTW9vbjoge21vb25f"
    "bmFtZX0gKHtpbGx1bX0lIGlsbHVtaW5hdGVkKS5cbiIKICAgICAgICBmIlJlc3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4g"
    "dGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5jZSB0aGVzZSBicmFja2V0cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKU"
    "gCBTT1VORCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUHJvY2VkdXJh"
    "bCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5kIHByb2ZpbGVzLgojIE5vIGV4dGVybmFsIGF1ZGlv"
    "IGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBidWlsdC1pbiB3YXZl"
    "ICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sgKHN1cHBvcnRzIFdBViBhbmQg"
    "TVAzKS4KCl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9h"
    "dDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJlcTogZmxv"
    "YXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0x"
    "LjAKCmRlZiBfc2F3dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChm"
    "cmVxICogdCkgJSAxLjApIC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19y"
    "OiBmbG9hdCwKICAgICAgICAgZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAoc2luZV9y"
    "ICogX3NpbmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzcXVhcmVfciAqIF9zcXVhcmUoZnJlcSwgdCkgKwogICAgICAg"
    "ICAgICBzYXdfciAqIF9zYXd0b290aChmcmVxLCB0KSkKCmRlZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAog"
    "ICAgICAgICAgICAgIGF0dGFja19mcmFjOiBmbG9hdCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBm"
    "bG9hdCA9IDAuMykgLT4gZmxvYXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBv"
    "cyA9IGkgLyBtYXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRhY2tfZnJhYzoKICAgICAgICByZXR1cm4gcG9zIC8g"
    "YXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMpOgogICAgICAgIHJldHVybiAoMSAtIHBv"
    "cykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAKCmRlZiBfd3JpdGVfd2F2KHBhdGg6IFBhdGgsIGF1ZGlvOiBs"
    "aXN0W2ludF0pIC0+IE5vbmU6CiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUp"
    "CiAgICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwgMiwg"
    "X1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZvciBzIGluIGF1ZGlvOgog"
    "ICAgICAgICAgICBmLndyaXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkg"
    "LT4gaW50OgogICAgcmV0dXJuIG1heCgtMzI3NjcsIG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5O"
    "QSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVzCiMgVHdvIG5vdGVzOiByb290IOKGkiBtaW5vciB0"
    "aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhlZHJhbCByZXNvbmFuY2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5u"
    "YV9hbGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJlbGwg4oCUIHR3"
    "byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAgIFNvdW5kcyBsaWtlIGEg"
    "c2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBub3RlcyA9"
    "IFsKICAgICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQgZmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45"
    "KSwgICMgRiM0IOKAlCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAg"
    "YXVkaW8gPSBbXQogICAgZm9yIGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExF"
    "X1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9T"
    "QU1QTEVfUkFURQogICAgICAgICAgICAjIFB1cmUgc2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3"
    "CiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC43CiAgICAgICAgICAgICMgQWRkIGEgc3VidGxlIGhh"
    "cm1vbmljIGZvciByaWNobmVzcwogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAg"
    "ICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4wLCB0KSAqIDAuMDUKICAgICAgICAgICAgIyBMb25nIHJlbGVh"
    "c2UgZW52ZWxvcGUg4oCUIGJlbGwgZGllcyBzbG93bHkKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFs"
    "LCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNlX2ZyYWM9MC43KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1w"
    "KHZhbCAqIGVudiAqIDAuNSkpCiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBmb3Ig"
    "XyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAg"
    "X3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3Jk"
    "IHJlc29sdXRpb24KIyBUaHJlZSBub3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4g"
    "U8OpYW5jZSBiZWdpbm5pbmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwKHBhdGg6IFBhdGgpIC0+IE5vbmU6"
    "CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2aW5nIHVwd2FyZCDigJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5u"
    "aW5nLgogICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFsIG5vdGUgaGVsZCBhbmQgZmFkZWQpLgogICAgIiIi"
    "CiAgICBub3RlcyA9IFsKICAgICAgICAoMjIwLjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYxLjYzLCAwLjI1KSwg"
    "ICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBFNCAoZmlmdGgpCiAgICAgICAgKDQ0"
    "MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChm"
    "cmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICog"
    "bGVuZ3RoKQogICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4gcmFu"
    "Z2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShm"
    "cmVxLCB0KSAqIDAuNgogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAg"
    "ICAgaWYgaXNfZmluYWw6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFj"
    "PTAuMDUsIHJlbGVhc2VfZnJhYz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52"
    "ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1ZGlv"
    "LmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40NSkpCiAgICAgICAgaWYgbm90IGlzX2ZpbmFsOgogICAgICAgICAg"
    "ICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNSkpOgogICAgICAgICAgICAgICAgYXVkaW8uYXBw"
    "ZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExFIENISU1FIOKAlCBzaW5nbGUg"
    "bG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxsLiBTaWduYWxzIHVuc29saWNpdGVk"
    "IHRyYW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIi"
    "IlNpbmdsZSBzb2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2VuY2UgaW4gdGhlIGRhcmsuIiIiCiAg"
    "ICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBsZW5ndGggPSAxLjIKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAq"
    "IGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9T"
    "QU1QTEVfUkFURQogICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZy"
    "ZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAy"
    "LCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuMykpCiAg"
    "ICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAodGhlIGRldmlsJ3Mg"
    "aW50ZXJ2YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVhbC4KIyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVm"
    "IGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFRyaXRvbmUgaW50"
    "ZXJ2YWwg4oCUIEIzICsgRjQgcGxheWVkIHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2En"
    "LiBCcmllZiBhbmQgaGFyc2ggY29tcGFyZWQgdG8gaGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0g"
    "MjQ2Ljk0ICAjIEIzCiAgICBmcmVxX2IgPSAzNDkuMjMgICMgRjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFi"
    "b3ZlIEIpCiAgICBsZW5ndGggPSAwLjQKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1"
    "ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAg"
    "ICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQgY3JlYXRlcyBkaXNzb25hbmNlCiAgICAgICAg"
    "dmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAgICBfc3F1YXJlKGZyZXFfYiwgdCkgKiAw"
    "LjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAyLjAsIHQpICogMC4xKQogICAgICAgIGVudiA9IF9lbnZl"
    "bG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICBhdWRpby5hcHBl"
    "bmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBT"
    "SFVURE9XTiDigJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ugb2Ygc3RhcnR1cC4gVGhlIHPD"
    "qWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRyYXdzLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24ocGF0aDog"
    "UGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKGkiBDNCDihpIgQTMuIFByZXNlbmNlIHdp"
    "dGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAjIEE0"
    "CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAjIEM0CiAgICAgICAg"
    "KDIyMC4wLCAgMC44KSwgICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBm"
    "b3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExF"
    "X1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9T"
    "QU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9"
    "IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0"
    "dGFja19mcmFjPTAuMDMsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0g"
    "bGVuKG5vdGVzKS0xIGVsc2UgMC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAu"
    "NCkpCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDQpKToKICAgICAgICAgICAgYXVk"
    "aW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdldF9zb3VuZF9wYXRoKG5hbWU6IHN0cikgLT4g"
    "UGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X3tuYW1lfS53YXYiCgpk"
    "ZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6CiAgICAiIiJHZW5lcmF0ZSBhbnkgbWlzc2luZyBzb3VuZCBXQVYg"
    "ZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAgICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVf"
    "bW9yZ2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVwIjogIGdl"
    "bmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZSwK"
    "ICAgICAgICAiZXJyb3IiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5l"
    "cmF0ZV9tb3JnYW5uYV9zaHV0ZG93biwKICAgIH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5pdGVt"
    "cygpOgogICAgICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygp"
    "OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU09VTkRdW1dBUk5dIEZhaWxlZCB0byBnZW5lcmF0"
    "ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3VuZChuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBsYXkg"
    "YSBuYW1lZCBzb3VuZCBub24tYmxvY2tpbmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIgZmlyc3QgKGNyb3NzLXBsYXRm"
    "b3JtLCBXQVYgKyBNUDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgogICAgRmFsbHMgYmFj"
    "ayB0byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBub3QgQ0ZHWyJzZXR0"
    "aW5ncyJdLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAgcGF0aCA9IGdldF9zb3Vu"
    "ZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBpZiBQWUdBTUVf"
    "T0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAg"
    "ICAgICAgICAgIHNvdW5kLnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICBwYXNzCgogICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3Vu"
    "ZC5QbGF5U291bmQoc3RyKHBhdGgpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJ"
    "TEVOQU1FIHwgd2luc291bmQuU05EX0FTWU5DKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICBwYXNzCgogICAgdHJ5OgogICAgICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKIyDilIDilIAgREVTS1RPUCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBib29sOgogICAgIiIiCiAgICBDcmVhdGUgYSBkZXNr"
    "dG9wIHNob3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgogICAgUmV0dXJucyBUcnVl"
    "IG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgogICAgICAgIHJldHVy"
    "biBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAgIHNo"
    "b3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUg"
    "YXMgcHl0aG9uIGJ1dCBubyBjb25zb2xlIHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxl"
    "KQogICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9u"
    "dyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgog"
    "ICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0gUGF0aChf"
    "X2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxsID0gd2luMzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2NyaXB0"
    "LlNoZWxsIikKICAgICAgICBzYyA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzaG9ydGN1dF9wYXRoKSkKICAgICAg"
    "ICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQogICAgICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZicie2Rl"
    "Y2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRoLnBhcmVudCkKICAgICAg"
    "ICBzYy5EZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKCiAgICAgICAgIyBVc2UgbmV1"
    "dHJhbCBmYWNlIGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikg"
    "LyBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgogICAgICAg"
    "ICAgICAjIFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCUIHNraXAgaWNvbiBpZiBubyAu"
    "aWNvCiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZToKICAgICAgICBwcmludChmIltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBz"
    "aG9ydGN1dDoge2V9IikKICAgICAgICByZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHJlYWRfanNvbmwocGF0aDogUGF0aCkgLT4gbGlzdFtk"
    "aWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1cm5zIGxpc3Qgb2YgZGljdHMuIEhhbmRsZXMgSlNPTiBh"
    "cnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBw"
    "YXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAgICBpZiBub3QgcmF3OgogICAgICAgIHJldHVy"
    "biBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRhdGEgPSBqc29u"
    "LmxvYWRzKHJhdykKICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEgaWYgaXNpbnN0YW5jZSh4LCBkaWN0"
    "KV0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAgICBmb3Ig"
    "bGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICBpZiBub3Qg"
    "bGluZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMo"
    "bGluZSkKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAgICAgICAgaXRlbXMuYXBw"
    "ZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0"
    "ZW1zCgpkZWYgYXBwZW5kX2pzb25sKHBhdGg6IFBhdGgsIG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVuZCBv"
    "bmUgcmVjb3JkIHRvIGEgSlNPTkwgZmlsZS4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhp"
    "c3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBm"
    "LndyaXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikKCmRlZiB3cml0ZV9qc29ubChw"
    "YXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgIiIiT3ZlcndyaXRlIGEgSlNPTkwgZmls"
    "ZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlz"
    "dF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZv"
    "ciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9RmFsc2Up"
    "ICsgIlxuIikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9"
    "IHsKICAgICJ0aGUiLCJhbmQiLCJ0aGF0Iiwid2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwi"
    "d2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndvdWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRv"
    "IiwianVzdCIsCiAgICAiYWJvdXQiLCJsaWtlIiwiYmVjYXVzZSIsIndoaWxlIiwiY291bGQiLCJzaG91bGQiLCJ0aGVp"
    "ciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIsImRvZXMiLCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29u"
    "dCIsIm9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4iLCJhbHNvIiwic29tZSIsIm1vcmUiLCJsZXNzIiwib25s"
    "eSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2FpbiIsInZlcnkiLCJtdWNoIiwicmVhbGx5Iiwi"
    "bWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxsIiwidG9sZCIsImlkZWEiLCJjaGF0Iiwi"
    "Y29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwKfQoKZGVmIGV4dHJhY3Rfa2V5d29yZHModGV4"
    "dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxpc3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2VyKCkuc3RyaXAo"
    "IiAuLCE/OzonXCIoKVtde30iKSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQoKSwg"
    "W10KICAgIGZvciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JEUyBvciB0"
    "LmlzZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgogICAgICAgICAg"
    "ICBzZWVuLmFkZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAgaWYgbGVuKHJlc3VsdCkgPj0g"
    "bGltaXQ6CiAgICAgICAgICAgIGJyZWFrCiAgICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNl"
    "cl90ZXh0OiBzdHIsIGFzc2lzdGFudF90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAi"
    "ICIgKyBhc3Npc3RhbnRfdGV4dCkubG93ZXIoKQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImxzbCIsInB5dGhvbiIsInNj"
    "cmlwdCIsImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4ZWQi"
    "LCJyZXNvbHZlZCIsInNvbHV0aW9uIiwid29ya2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJyZXNvbHV0aW9uIgog"
    "ICAgICAgIHJldHVybiAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicmVtaW5kIiwidGltZXIiLCJh"
    "bGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImlk"
    "ZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRlYSIKICAg"
    "IGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIp"
    "KToKICAgICAgICByZXR1cm4gInByZWZlcmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBB"
    "U1MgMSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg"
    "4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lkZ2V0LCBNb29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25C"
    "bG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1waXJlU3RhdGVTdHJpcCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMjogV0lER0VUIENMQVNTRVMK"
    "IyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRl"
    "ZmluZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGggbGFi"
    "ZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFs"
    "IEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMg"
    "ICBNb29uV2lkZ2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rp"
    "b25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdl"
    "dCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBWYW1waXJlU3RhdGVTdHJpcCAg"
    "ICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVzIGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg"
    "4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRvZ2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVs"
    "ICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1"
    "Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3At"
    "cmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaS"
    "IENfQkxPT0QgYXMgdmFsdWUgYXBwcm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFp"
    "bGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBsYWJlbDogc3RyLAog"
    "ICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAgY29sb3I6"
    "IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAg"
    "ICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAgc2Vs"
    "Zi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNlbGYuX2F2YWlsYWJs"
    "ZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYuc2V0TWF4aW11"
    "bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwg"
    "YXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQo"
    "dmFsdWUpLCBzZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYg"
    "bm90IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5"
    "OgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYu"
    "X2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBz"
    "ZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2Vs"
    "ZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50"
    "KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYu"
    "aGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3Io"
    "Q19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCgwLCAwLCB3"
    "IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAg"
    "ICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJh"
    "d1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAgICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2Vs"
    "Zi5jb2xvciBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQo"
    "REVDS19GT05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAg"
    "ICAgdncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3"
    "IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJfeSA9IGggLSAxOAog"
    "ICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAgIHAuZmlsbFJlY3QoNiwgYmFyX3ks"
    "IGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAg"
    "ICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2YWls"
    "YWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5tYXhf"
    "dmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAg"
    "IyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZyYWMgPiAw"
    "Ljg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcs"
    "IGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNv"
    "bG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFy"
    "X2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFk"
    "KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUg"
    "dXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8t"
    "ZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZHJpdmVz"
    "OiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5fcmVm"
    "cmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAg"
    "ICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZv"
    "ciBwYXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBh"
    "cnQuZGV2aWNlLnJzdHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAg"
    "IHVzYWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdlLnRvdGFs"
    "IC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBlcmNlbnQgLyAxMDAuMCwK"
    "ICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICAj"
    "IFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwogICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAg"
    "ICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBw"
    "YWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAu"
    "c2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53"
    "aWR0aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoK"
    "ICAgICAgICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkp"
    "CiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYs"
    "IDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJl"
    "dHVybgoKICAgICAgICByb3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZl"
    "czoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIiXQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQi"
    "XQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0gZHJ2WyJwY3QiXQoK"
    "ICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4xZn0ve3RvdGFs"
    "Oi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAgIHAuc2V0Rm9udChR"
    "Rm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsg"
    "MTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95"
    "ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAg"
    "ICBwLmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAu"
    "c2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAt"
    "IDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQog"
    "ICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBwY3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJ"
    "TSkKICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxf"
    "dywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUw"
    "KSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZp"
    "bGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgICAgIHkg"
    "Kz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "Q2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoK"
    "CiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNl"
    "ZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZpbGxzIGZyb20gYm90dG9tIHVwLiBH"
    "bGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBz"
    "ZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5"
    "OiBzdHIsCiAgICAgICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwK"
    "ICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAgID0gMC4w"
    "ICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRNaW5p"
    "bXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBi"
    "b29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFj"
    "dGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAg"
    "IGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAg"
    "ICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0g"
    "c2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAg"
    "ICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRv"
    "dwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAs"
    "IDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikK"
    "CiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5j"
    "b2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAgIGlm"
    "IHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9wYXRoID0gUVBh"
    "aW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChj"
    "eSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIp"
    "KQoKICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAg"
    "IGZyb20gUHlTaWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3gg"
    "LSByLCBmaWxsX3RvcF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0g"
    "UVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBj"
    "bGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQu"
    "UGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAg"
    "ICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFS"
    "YWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICogMC4zKSwg"
    "ZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUs"
    "IDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5k"
    "cmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBw"
    "LnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNv"
    "bG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgog"
    "ICAgICAgICMgTi9BIG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNl"
    "dFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4"
    "KSkKICAgICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAg"
    "ICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAg"
    "ICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlmIHNlbGYuX2F2"
    "YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQg"
    "PSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAgcC5z"
    "ZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwg"
    "UUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9y"
    "aXpvbnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBs"
    "YWJlbF90ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9E"
    "SU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAgZm0yID0gcC5m"
    "b250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAg"
    "ICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDi"
    "lIDilIAgTU9PTiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXduIG1vb24gb3JiIHdpdGggcGhhc2UtYWNj"
    "dXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToK"
    "ICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAog"
    "ICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0Cgog"
    "ICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dh"
    "cmRzCiAgICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAg"
    "ICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0"
    "ZXN0aW5nCiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAg"
    "ID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJO"
    "RVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3Vu"
    "cmlzZSAgICAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAgICAgICBzZWxm"
    "Ll9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAgICAgIHNl"
    "bGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAgICAg"
    "ICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAg"
    "c2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9z"
    "dW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSBy"
    "ZXBhaW50IG9uIG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVw"
    "ZGF0ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRhZW1vbj1UcnVl"
    "KS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNl"
    "bGYuX25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0"
    "aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAg"
    "ICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50"
    "RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRS"
    "ZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRo"
    "KCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0g"
    "dyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoKICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChz"
    "cGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFD"
    "b2xvcihDX1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwg"
    "ciAqIDIpCgogICAgICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4"
    "aW5nID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24g"
    "c3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBl"
    "bihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAg"
    "ICAgICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFk"
    "b3cgY2FsY3VsYXRpb24KICAgICAgICAjIGlsbHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdh"
    "bmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9scyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFk"
    "b3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24g"
    "b2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNl"
    "bGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4wIC0gaWxsdW1fZnJhYwoK"
    "ICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFkb3cgTEVGVAogICAgICAgICAgICAjIHdh"
    "bmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBz"
    "aGFkb3cgZWxsaXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAq"
    "IDIpCgogICAgICAgICAgICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193"
    "YXhpbmcgPSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNo"
    "YWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFk"
    "b3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAg"
    "ICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlw"
    "c2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkK"
    "ICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBz"
    "aGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQo"
    "c2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChy"
    "ICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJzZWN0"
    "ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3Vi"
    "dGxlIHN1cmZhY2UgZGV0YWlsIChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAg"
    "ICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGluZS5zZXRDb2xv"
    "ckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3Io"
    "MjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5T"
    "dHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0"
    "UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwg"
    "ciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQp"
    "KQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxm"
    "Ll9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAg"
    "ICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5h"
    "dGlvbjouMGZ9JSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFG"
    "b250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9y"
    "aXpvbnRhbEFkdmFuY2UoaWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAy"
    "NCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBm"
    "IuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19H"
    "T0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250"
    "TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdU"
    "ZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9O"
    "IEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFbW90aW9uQmxv"
    "Y2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dz"
    "IGNvbG9yLWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJy"
    "b3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUgYm90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBo"
    "ZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9"
    "IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2Vs"
    "Zi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAg"
    "ICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWln"
    "aHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0g"
    "UUhCb3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAg"
    "IGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFMIFJFQ09SRCIpCiAgICAg"
    "ICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsg"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBs"
    "ZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRu"
    "ID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJl"
    "bnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQobGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2go"
    "KQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAjIFNjcm9sbCBhcmVhIGZvciBl"
    "bW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9s"
    "bC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJh"
    "clBvbGljeSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBz"
    "ZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2No"
    "aXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNl"
    "dFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3Jv"
    "bGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgo"
    "MTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2Vs"
    "Zi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBz"
    "ZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAgICBz"
    "ZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIsIHRpbWVzdGFt"
    "cDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0YW1w"
    "ID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAo"
    "ZW1vdGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5fbWF4"
    "X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAg"
    "ICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9j"
    "aGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0"
    "ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToK"
    "ICAgICAgICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAg"
    "ICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3RzfSIpCiAgICAgICAgICAgIGNoaXAuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9y"
    "ZGVyLXJhZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRX"
    "aWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAgICAgICAg"
    "ICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAg"
    "ICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZh"
    "Y2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BS"
    "RUZJWH1fKi5wbmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8g"
    "ZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQiCiAgICAgICAg"
    "e0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFDRV9QUkVGSVh9X0NoZWF0X01v"
    "ZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFj"
    "ZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQg"
    "bm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaS"
    "IGVtb3Rpb24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9UT19F"
    "TU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAiY2hl"
    "YXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgo"
    "ImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIsIFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9j"
    "dXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAg"
    "ICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVu"
    "dEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "ci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3ByZWxv"
    "YWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2NhbiBGYWNlcy8g"
    "ZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaS"
    "cGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5LgogICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBp"
    "biB0aGUgZm9sZGVyIGlzIGF2YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGly"
    "LmV4aXN0cygpOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToK"
    "ICAgICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAg"
    "ICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNFX1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNh"
    "ZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtl"
    "eXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQoc3RlbV9sb3dlciwgc3RlbV9s"
    "b3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAgICAgICBpZiBub3QgcHgu"
    "aXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAgICAgIGlmIHNlbGYu"
    "X2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNo"
    "ZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAg"
    "ICAgICAgICAgICAgIHByaW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNp"
    "bmcgbmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2Ug"
    "PSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJh"
    "d19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBmYWNlCiAgICAg"
    "ICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2Vs"
    "Zi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJh"
    "dGlvTW9kZS5LZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhUcmFu"
    "c2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAgICAgIHNlbGYuc2V0"
    "VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLmNsZWFy"
    "KCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRp"
    "dXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2"
    "ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAg"
    "aWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0"
    "eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCgoj"
    "IOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBWYW1waXJl"
    "U3RhdGVTdHJpcChRV2lkZ2V0KToKICAgICIiIgogICAgRnVsbC13aWR0aCBzdGF0dXMgYmFyIHNob3dpbmc6CiAgICAg"
    "IFsg4pymIFZBTVBJUkVfU1RBVEUgIOKAoiAgSEg6TU0gIOKAoiAg4piAIFNVTlJJU0UgIOKYvSBTVU5TRVQgIOKAoiAg"
    "TU9PTiBQSEFTRSAgSUxMVU0lIF0KICAgIEFsd2F5cyB2aXNpYmxlLCBuZXZlciBjb2xsYXBzZXMuCiAgICBVcGRhdGVz"
    "IGV2ZXJ5IG1pbnV0ZSB2aWEgZXh0ZXJuYWwgUVRpbWVyIGNhbGwgdG8gcmVmcmVzaCgpLgogICAgQ29sb3ItY29kZWQg"
    "YnkgY3VycmVudCB2YW1waXJlIHN0YXRlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAiU1RB"
    "VEUiCiAgICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVf"
    "c3RyICA9ICIiCiAgICAgICAgc2VsZi5fc3VucmlzZSAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICA9"
    "ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgPSBOb25lCiAgICAgICAgc2VsZi5fbW9vbl9uYW1lID0gIk5F"
    "VyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtICAgICA9IDAuMAogICAgICAgIHNlbGYuc2V0Rml4ZWRIZWlnaHQoMjgp"
    "CiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyLXRvcDogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgc2V0X2xhYmVsKHNlbGYsIGxhYmVsOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "bGFiZWxfcHJlZml4ID0gKGxhYmVsIG9yICJTVEFURSIpLnN0cmlwKCkudXBwZXIoKQogICAgICAgIHNlbGYudXBkYXRl"
    "KCkKCiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgogICAgICAgIGRlZiBfZigpOgogICAgICAg"
    "ICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAg"
    "ICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFz"
    "dGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIOKAlCBu"
    "ZXZlciBjYWxsIHVwZGF0ZSgpIGZyb20KICAgICAgICAgICAgIyBhIGJhY2tncm91bmQgdGhyZWFkLCBpdCBjYXVzZXMg"
    "UVRocmVhZCBjcmFzaCBvbiBzdGFydHVwCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRl"
    "KQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiBy"
    "ZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQog"
    "ICAgICAgIHNlbGYuX3RpbWVfc3RyICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5zdHJmdGltZSgiJVgiKQog"
    "ICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1"
    "bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIF8sIHNlbGYu"
    "X21vb25fbmFtZSwgc2VsZi5faWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAg"
    "IGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAg"
    "ICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0g"
    "c2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENf"
    "QkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3IgPSBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzZWxmLl9zdGF0ZSkKICAg"
    "ICAgICB0ZXh0ID0gKAogICAgICAgICAgICBmIuKcpiAge3NlbGYuX2xhYmVsX3ByZWZpeH06IHtzZWxmLl9zdGF0ZX0g"
    "IOKAoiAge3NlbGYuX3RpbWVfc3RyfSAg4oCiICAiCiAgICAgICAgICAgIGYi4piAIHtzZWxmLl9zdW5yaXNlfSAgICDi"
    "mL0ge3NlbGYuX3N1bnNldH0gIOKAoiAgIgogICAgICAgICAgICBmIntzZWxmLl9tb29uX25hbWV9ICB7c2VsZi5faWxs"
    "dW06LjBmfSUiCiAgICAgICAgKQoKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA5LCBRRm9udC5XZWln"
    "aHQuQm9sZCkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHN0YXRlX2NvbG9yKSkKICAgICAgICBmbSA9IHAuZm9udE1l"
    "dHJpY3MoKQogICAgICAgIHR3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodGV4dCkKICAgICAgICBwLmRyYXdUZXh0KCh3"
    "IC0gdHcpIC8vIDIsIGggLSA3LCB0ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKY2xhc3MgTWluaUNhbGVuZGFyV2lkZ2V0"
    "KFFXaWRnZXQpOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5p"
    "dF9fKHBhcmVudCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBoZWFkZXIg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgaGVhZGVyLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IHNlbGYucHJldl9idG4gPSBRUHVzaEJ1dHRvbigiPDwiKQogICAgICAgIHNlbGYubmV4dF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiPj4iKQogICAgICAgIHNlbGYubW9udGhfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNl"
    "dEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIGZvciBidG4gaW4gKHNlbGYucHJl"
    "dl9idG4sIHNlbGYubmV4dF9idG4pOgogICAgICAgICAgICBidG4uc2V0Rml4ZWRXaWR0aCgzNCkKICAgICAgICAgICAg"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19H"
    "T0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtc2l6"
    "ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgICAgICkKICAgICAgICBzZWxm"
    "Lm1vbnRoX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICApCiAgICAgICAgaGVhZGVyLmFkZFdp"
    "ZGdldChzZWxmLnByZXZfYnRuKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5tb250aF9sYmwsIDEpCiAgICAg"
    "ICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLm5leHRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaGVhZGVyKQoK"
    "ICAgICAgICBzZWxmLmNhbGVuZGFyID0gUUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldEdy"
    "aWRWaXNpYmxlKFRydWUpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRWZXJ0aWNhbEhlYWRlckZvcm1hdChRQ2FsZW5k"
    "YXJXaWRnZXQuVmVydGljYWxIZWFkZXJGb3JtYXQuTm9WZXJ0aWNhbEhlYWRlcikKICAgICAgICBzZWxmLmNhbGVuZGFy"
    "LnNldE5hdmlnYXRpb25CYXJWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUVdpZGdldHt7YWx0ZXJuYXRlLWJhY2tncm91bmQtY29sb3I6e0Nf"
    "QkcyfTt9fSAiCiAgICAgICAgICAgIGYiUVRvb2xCdXR0b257e2NvbG9yOntDX0dPTER9O319ICIKICAgICAgICAgICAg"
    "ZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZW5hYmxlZHt7YmFja2dyb3VuZDp7Q19CRzJ9OyBjb2xv"
    "cjojZmZmZmZmOyAiCiAgICAgICAgICAgIGYic2VsZWN0aW9uLWJhY2tncm91bmQtY29sb3I6e0NfQ1JJTVNPTl9ESU19"
    "OyBzZWxlY3Rpb24tY29sb3I6e0NfVEVYVH07IGdyaWRsaW5lLWNvbG9yOntDX0JPUkRFUn07fX0gIgogICAgICAgICAg"
    "ICBmIlFDYWxlbmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzpkaXNhYmxlZHt7Y29sb3I6IzhiOTVhMTt9fSIKICAg"
    "ICAgICApCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyKQoKICAgICAgICBzZWxmLnByZXZfYnRu"
    "LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd1ByZXZpb3VzTW9udGgoKSkKICAgICAgICBz"
    "ZWxmLm5leHRfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd05leHRNb250aCgpKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuY3VycmVudFBhZ2VDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2xhYmVsKQog"
    "ICAgICAgIHNlbGYuX3VwZGF0ZV9sYWJlbCgpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF91"
    "cGRhdGVfbGFiZWwoc2VsZiwgKmFyZ3MpOgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAg"
    "ICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFRl"
    "eHQoZiJ7ZGF0ZSh5ZWFyLCBtb250aCwgMSkuc3RyZnRpbWUoJyVCICVZJyl9IikKICAgICAgICBzZWxmLl9hcHBseV9m"
    "b3JtYXRzKCkKCiAgICBkZWYgX2FwcGx5X2Zvcm1hdHMoc2VsZik6CiAgICAgICAgYmFzZSA9IFFUZXh0Q2hhckZvcm1h"
    "dCgpCiAgICAgICAgYmFzZS5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgIHNhdHVyZGF5ID0g"
    "UVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzYXR1cmRheS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElNKSkK"
    "ICAgICAgICBzdW5kYXkgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIHN1bmRheS5zZXRGb3JlZ3JvdW5kKFFDb2xv"
    "cihDX0JMT09EKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5N"
    "b25kYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsu"
    "VHVlc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vl"
    "ay5XZWRuZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlP"
    "ZldlZWsuVGh1cnNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5E"
    "YXlPZldlZWsuRnJpZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQu"
    "RGF5T2ZXZWVrLlNhdHVyZGF5LCBzYXR1cmRheSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9y"
    "bWF0KFF0LkRheU9mV2Vlay5TdW5kYXksIHN1bmRheSkKCiAgICAgICAgeWVhciA9IHNlbGYuY2FsZW5kYXIueWVhclNo"
    "b3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAgICAgZmlyc3RfZGF5ID0g"
    "UURhdGUoeWVhciwgbW9udGgsIDEpCiAgICAgICAgZm9yIGRheSBpbiByYW5nZSgxLCBmaXJzdF9kYXkuZGF5c0luTW9u"
    "dGgoKSArIDEpOgogICAgICAgICAgICBkID0gUURhdGUoeWVhciwgbW9udGgsIGRheSkKICAgICAgICAgICAgZm10ID0g"
    "UVRleHRDaGFyRm9ybWF0KCkKICAgICAgICAgICAgd2Vla2RheSA9IGQuZGF5T2ZXZWVrKCkKICAgICAgICAgICAgaWYg"
    "d2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU2F0dXJkYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdy"
    "b3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgICAgIGVsaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU3Vu"
    "ZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAg"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQoZCwgZm10KQoKICAgICAgICB0b2RheV9mbXQgPSBR"
    "VGV4dENoYXJGb3JtYXQoKQogICAgICAgIHRvZGF5X2ZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiIzY4ZDM5YSIpKQog"
    "ICAgICAgIHRvZGF5X2ZtdC5zZXRCYWNrZ3JvdW5kKFFDb2xvcigiIzE2MzgyNSIpKQogICAgICAgIHRvZGF5X2ZtdC5z"
    "ZXRGb250V2VpZ2h0KFFGb250LldlaWdodC5Cb2xkKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3Jt"
    "YXQoUURhdGUuY3VycmVudERhdGUoKSwgdG9kYXlfZm10KQoKCiMg4pSA4pSAIENPTExBUFNJQkxFIEJMT0NLIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDb2xsYXBzaWJsZUJsb2NrKFFXaWRnZXQpOgogICAgIiIi"
    "CiAgICBXcmFwcGVyIHRoYXQgYWRkcyBhIGNvbGxhcHNlL2V4cGFuZCB0b2dnbGUgdG8gYW55IHdpZGdldC4KICAgIENv"
    "bGxhcHNlcyBob3Jpem9udGFsbHkgKHJpZ2h0d2FyZCkg4oCUIGhpZGVzIGNvbnRlbnQsIGtlZXBzIGhlYWRlciBzdHJp"
    "cC4KICAgIEhlYWRlciBzaG93cyBsYWJlbC4gVG9nZ2xlIGJ1dHRvbiBvbiByaWdodCBlZGdlIG9mIGhlYWRlci4KCiAg"
    "ICBVc2FnZToKICAgICAgICBibG9jayA9IENvbGxhcHNpYmxlQmxvY2soIuKdpyBCTE9PRCIsIFNwaGVyZVdpZGdldCgu"
    "Li4pKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoYmxvY2spCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "bGFiZWw6IHN0ciwgY29udGVudDogUVdpZGdldCwKICAgICAgICAgICAgICAgICBleHBhbmRlZDogYm9vbCA9IFRydWUs"
    "IG1pbl93aWR0aDogaW50ID0gOTAsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVkICA9IGV4cGFuZGVkCiAgICAgICAgc2VsZi5fbWlu"
    "X3dpZHRoID0gbWluX3dpZHRoCiAgICAgICAgc2VsZi5fY29udGVudCAgID0gY29udGVudAoKICAgICAgICBtYWluID0g"
    "UVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IG1haW4uc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElN"
    "fTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENv"
    "bnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJs"
    "ID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAg"
    "ICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXpl"
    "KDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0"
    "cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRj"
    "aCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5faGVh"
    "ZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRl"
    "KCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYu"
    "X2V4cGFuZGVkCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5f"
    "YnRuLnNldFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQogICAgICAgIGlmIHNlbGYuX2V4cGFuZGVk"
    "OgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYu"
    "c2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "IyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxh"
    "cHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lk"
    "dGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcGFyZW50"
    "ID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHBhcmVudCBhbmQgcGFyZW50LmxheW91dCgpOgogICAgICAg"
    "ICAgICBwYXJlbnQubGF5b3V0KCkuYWN0aXZhdGUoKQoKCiMg4pSA4pSAIEhBUkRXQVJFIFBBTkVMIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBIYXJkd2FyZVBhbmVsKFFXaWRnZXQpOgogICAgIiIi"
    "CiAgICBUaGUgc3lzdGVtcyByaWdodCBwYW5lbCBjb250ZW50cy4KICAgIEdyb3Vwczogc3RhdHVzIGluZm8sIGRyaXZl"
    "IGJhcnMsIENQVS9SQU0gZ2F1Z2VzLCBHUFUvVlJBTSBnYXVnZXMsIEdQVSB0ZW1wLgogICAgUmVwb3J0cyBoYXJkd2Fy"
    "ZSBhdmFpbGFiaWxpdHkgaW4gRGlhZ25vc3RpY3Mgb24gc3RhcnR1cC4KICAgIFNob3dzIE4vQSBncmFjZWZ1bGx5IHdo"
    "ZW4gZGF0YSB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAg"
    "ICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYu"
    "X2RldGVjdF9oYXJkd2FyZSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAg"
    "ICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGRlZiBzZWN0aW9uX2xhYmVsKHRleHQ6IHN0cikgLT4gUUxh"
    "YmVsOgogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7"
    "ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBsYmwKCiAgICAgICAgIyDilIDilIAgU3RhdHVzIGJs"
    "b2NrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFNUQVRVUyIpKQogICAgICAgIHN0"
    "YXR1c19mcmFtZSA9IFFGcmFtZSgpCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfUEFORUx9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVz"
    "OiAycHg7IgogICAgICAgICkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0Rml4ZWRIZWlnaHQoODgpCiAgICAgICAgc2Yg"
    "PSBRVkJveExheW91dChzdGF0dXNfZnJhbWUpCiAgICAgICAgc2Yuc2V0Q29udGVudHNNYXJnaW5zKDgsIDQsIDgsIDQp"
    "CiAgICAgICAgc2Yuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLmxibF9zdGF0dXMgID0gUUxhYmVsKCLinKYgU1RB"
    "VFVTOiBPRkZMSU5FIikKICAgICAgICBzZWxmLmxibF9tb2RlbCAgID0gUUxhYmVsKCLinKYgVkVTU0VMOiBMT0FESU5H"
    "Li4uIikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uID0gUUxhYmVsKCLinKYgU0VTU0lPTjogMDA6MDA6MDAiKQogICAg"
    "ICAgIHNlbGYubGJsX3Rva2VucyAgPSBRTGFiZWwoIuKcpiBUT0tFTlM6IDAiKQoKICAgICAgICBmb3IgbGJsIGluIChz"
    "ZWxmLmxibF9zdGF0dXMsIHNlbGYubGJsX21vZGVsLAogICAgICAgICAgICAgICAgICAgIHNlbGYubGJsX3Nlc3Npb24s"
    "IHNlbGYubGJsX3Rva2Vucyk6CiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgYm9yZGVyOiBub25lOyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZi5hZGRX"
    "aWRnZXQobGJsKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHN0YXR1c19mcmFtZSkKCiAgICAgICAgIyDilIDilIAg"
    "RHJpdmUgYmFycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVE9SQUdF"
    "IikpCiAgICAgICAgc2VsZi5kcml2ZV93aWRnZXQgPSBEcml2ZVdpZGdldCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLmRyaXZlX3dpZGdldCkKCiAgICAgICAgIyDilIDilIAgQ1BVIC8gUkFNIGdhdWdlcyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlY3Rpb25fbGFiZWwoIuKdpyBWSVRBTCBFU1NFTkNFIikpCiAgICAgICAgcmFtX2NwdSA9IFFHcmlkTGF5b3V0KCkK"
    "ICAgICAgICByYW1fY3B1LnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9jcHUgID0gR2F1Z2VXaWRnZXQo"
    "IkNQVSIsICAiJSIsICAgMTAwLjAsIENfU0lMVkVSKQogICAgICAgIHNlbGYuZ2F1Z2VfcmFtICA9IEdhdWdlV2lkZ2V0"
    "KCJSQU0iLCAgIkdCIiwgICA2NC4wLCBDX0dPTERfRElNKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1"
    "Z2VfY3B1LCAwLCAwKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfcmFtLCAwLCAxKQogICAgICAg"
    "IGxheW91dC5hZGRMYXlvdXQocmFtX2NwdSkKCiAgICAgICAgIyDilIDilIAgR1BVIC8gVlJBTSBnYXVnZXMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWN0aW9uX2xhYmVsKCLinacgQVJDQU5FIFBPV0VSIikpCiAgICAgICAgZ3B1X3ZyYW0gPSBRR3JpZExheW91"
    "dCgpCiAgICAgICAgZ3B1X3ZyYW0uc2V0U3BhY2luZygzKQoKICAgICAgICBzZWxmLmdhdWdlX2dwdSAgPSBHYXVnZVdp"
    "ZGdldCgiR1BVIiwgICIlIiwgICAxMDAuMCwgQ19QVVJQTEUpCiAgICAgICAgc2VsZi5nYXVnZV92cmFtID0gR2F1Z2VX"
    "aWRnZXQoIlZSQU0iLCAiR0IiLCAgICA4LjAsIENfQ1JJTVNPTikKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2Vs"
    "Zi5nYXVnZV9ncHUsICAwLCAwKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX3ZyYW0sIDAsIDEp"
    "CiAgICAgICAgbGF5b3V0LmFkZExheW91dChncHVfdnJhbSkKCiAgICAgICAgIyDilIDilIAgR1BVIFRlbXAg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgSEVBVCIpKQog"
    "ICAgICAgIHNlbGYuZ2F1Z2VfdGVtcCA9IEdhdWdlV2lkZ2V0KCJHUFUgVEVNUCIsICLCsEMiLCA5NS4wLCBDX0JMT09E"
    "KQogICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRNYXhpbXVtSGVpZ2h0KDY1KQogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5nYXVnZV90ZW1wKQoKICAgICAgICAjIOKUgOKUgCBHUFUgbWFzdGVyIGJhciAoZnVsbCB3aWR0aCkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5G"
    "RVJOQUwgRU5HSU5FIikpCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyID0gR2F1Z2VXaWRnZXQoIlJUWCIsICIl"
    "IiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0TWF4aW11bUhlaWdodCg1"
    "NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1X21hc3RlcikKCiAgICAgICAgbGF5b3V0LmFk"
    "ZFN0cmV0Y2goKQoKICAgIGRlZiBfZGV0ZWN0X2hhcmR3YXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAg"
    "ICAgQ2hlY2sgd2hhdCBoYXJkd2FyZSBtb25pdG9yaW5nIGlzIGF2YWlsYWJsZS4KICAgICAgICBNYXJrIHVuYXZhaWxh"
    "YmxlIGdhdWdlcyBhcHByb3ByaWF0ZWx5LgogICAgICAgIERpYWdub3N0aWMgbWVzc2FnZXMgY29sbGVjdGVkIGZvciB0"
    "aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgICAgICIiIgogICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXM6IGxpc3Rbc3Ry"
    "XSA9IFtdCgogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHBzdXRpbCBub3QgYXZhaWxh"
    "YmxlIOKAlCBDUFUvUkFNIGdhdWdlcyBkaXNhYmxlZC4gIgogICAgICAgICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRp"
    "bCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNz"
    "YWdlcy5hcHBlbmQoIltIQVJEV0FSRV0gcHN1dGlsIE9LIOKAlCBDUFUvUkFNIG1vbml0b3JpbmcgYWN0aXZlLiIpCgog"
    "ICAgICAgIGlmIG5vdCBOVk1MX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRVbmF2YWlsYWJsZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVt"
    "cC5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRVbmF2YWlsYWJsZSgp"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0g"
    "cHludm1sIG5vdCBhdmFpbGFibGUgb3Igbm8gTlZJRElBIEdQVSBkZXRlY3RlZCDigJQgIgogICAgICAgICAgICAgICAg"
    "IkdQVSBnYXVnZXMgZGlzYWJsZWQuIHBpcCBpbnN0YWxsIHB5bnZtbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5udm1sRGV2aWNl"
    "R2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAg"
    "ICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2Fn"
    "ZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0hBUkRXQVJFXSBweW52bWwgT0sg4oCUIEdQVSBkZXRlY3Rl"
    "ZDoge25hbWV9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgIyBVcGRhdGUgbWF4IFZSQU0gZnJvbSBh"
    "Y3R1YWwgaGFyZHdhcmUKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhn"
    "cHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdG90YWxfZ2IgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAg"
    "ICAgICBzZWxmLmdhdWdlX3ZyYW0ubWF4X3ZhbCA9IHRvdGFsX2diCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKGYiW0hBUkRXQVJFXSBweW52bWwg"
    "ZXJyb3I6IHtlfSIpCgogICAgZGVmIHVwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAg"
    "IENhbGxlZCBldmVyeSBzZWNvbmQgZnJvbSB0aGUgc3RhdHMgUVRpbWVyLgogICAgICAgIFJlYWRzIGhhcmR3YXJlIGFu"
    "ZCB1cGRhdGVzIGFsbCBnYXVnZXMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgUFNVVElMX09LOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBjcHUgPSBwc3V0aWwuY3B1X3BlcmNlbnQoKQogICAgICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV9jcHUuc2V0VmFsdWUoY3B1LCBmIntjcHU6LjBmfSUiLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgICAgICAg"
    "ICBtZW0gPSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAgcnUgID0gbWVtLnVzZWQgIC8gMTAy"
    "NCoqMwogICAgICAgICAgICAgICAgcnQgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV9yYW0uc2V0VmFsdWUocnUsIGYie3J1Oi4xZn0ve3J0Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLm1heF92"
    "YWwgPSBydAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICBp"
    "ZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB1dGlsICAgICA9"
    "IHB5bnZtbC5udm1sRGV2aWNlR2V0VXRpbGl6YXRpb25SYXRlcyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgbWVt"
    "X2luZm8gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRl"
    "bXAgICAgID0gcHludm1sLm52bWxEZXZpY2VHZXRUZW1wZXJhdHVyZSgKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGdwdV9oYW5kbGUsIHB5bnZtbC5OVk1MX1RFTVBFUkFUVVJFX0dQVSkKCiAgICAgICAgICAgICAgICBncHVfcGN0"
    "ICAgPSBmbG9hdCh1dGlsLmdwdSkKICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbV9pbmZvLnVzZWQgIC8gMTAy"
    "NCoqMwogICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtX2luZm8udG90YWwgLyAxMDI0KiozCgogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VmFsdWUoZ3B1X3BjdCwgZiJ7Z3B1X3BjdDouMGZ9JSIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1"
    "Z2VfdnJhbS5zZXRWYWx1ZSh2cmFtX3VzZWQsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJ7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VmFsdWUoZmxv"
    "YXQodGVtcCksIGYie3RlbXB9wrBDIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFp"
    "bGFibGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5u"
    "dm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwg"
    "Ynl0ZXMpOgogICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBuYW1lID0gIkdQVSIKCiAgICAgICAgICAgICAgICBz"
    "ZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgZ3B1X3BjdCwKICAgICAgICAg"
    "ICAgICAgICAgICBmIntuYW1lfSAge2dwdV9wY3Q6LjBmfSUgICIKICAgICAgICAgICAgICAgICAgICBmIlt7dnJhbV91"
    "c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiBWUkFNXSIsCiAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUs"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNz"
    "CgogICAgICAgICMgVXBkYXRlIGRyaXZlIGJhcnMgZXZlcnkgMzAgc2Vjb25kcyAobm90IGV2ZXJ5IHRpY2spCiAgICAg"
    "ICAgaWYgbm90IGhhc2F0dHIoc2VsZiwgIl9kcml2ZV90aWNrIik6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sg"
    "PSAwCiAgICAgICAgc2VsZi5fZHJpdmVfdGljayArPSAxCiAgICAgICAgaWYgc2VsZi5fZHJpdmVfdGljayA+PSAzMDoK"
    "ICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICAgICAgc2VsZi5kcml2ZV93aWRnZXQucmVmcmVz"
    "aCgpCgogICAgZGVmIHNldF9zdGF0dXNfbGFiZWxzKHNlbGYsIHN0YXR1czogc3RyLCBtb2RlbDogc3RyLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHNlc3Npb246IHN0ciwgdG9rZW5zOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5s"
    "Ymxfc3RhdHVzLnNldFRleHQoZiLinKYgU1RBVFVTOiB7c3RhdHVzfSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwuc2V0"
    "VGV4dChmIuKcpiBWRVNTRUw6IHttb2RlbH0iKQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24uc2V0VGV4dChmIuKcpiBT"
    "RVNTSU9OOiB7c2Vzc2lvbn0iKQogICAgICAgIHNlbGYubGJsX3Rva2Vucy5zZXRUZXh0KGYi4pymIFRPS0VOUzoge3Rv"
    "a2Vuc30iKQoKICAgIGRlZiBnZXRfZGlhZ25vc3RpY3Moc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIHJldHVybiBn"
    "ZXRhdHRyKHNlbGYsICJfZGlhZ19tZXNzYWdlcyIsIFtdKQoKCiMg4pSA4pSAIFBBU1MgMiBDT01QTEVURSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd2lkZ2V0IGNsYXNzZXMgZGVmaW5lZC4gU3lu"
    "dGF4LWNoZWNrYWJsZSBpbmRlcGVuZGVudGx5LgojIE5leHQ6IFBhc3MgMyDigJQgV29ya2VyIFRocmVhZHMKIyAoRG9s"
    "cGhpbldvcmtlciB3aXRoIHN0cmVhbWluZywgU2VudGltZW50V29ya2VyLCBJZGxlV29ya2VyLCBTb3VuZFdvcmtlcikK"
    "CgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMzogV09SS0VS"
    "IFRIUkVBRFMKIwojIFdvcmtlcnMgZGVmaW5lZCBoZXJlOgojICAgTExNQWRhcHRvciAoYmFzZSArIExvY2FsVHJhbnNm"
    "b3JtZXJzQWRhcHRvciArIE9sbGFtYUFkYXB0b3IgKwojICAgICAgICAgICAgICAgQ2xhdWRlQWRhcHRvciArIE9wZW5B"
    "SUFkYXB0b3IpCiMgICBTdHJlYW1pbmdXb3JrZXIgICDigJQgbWFpbiBnZW5lcmF0aW9uLCBlbWl0cyB0b2tlbnMgb25l"
    "IGF0IGEgdGltZQojICAgU2VudGltZW50V29ya2VyICAg4oCUIGNsYXNzaWZpZXMgZW1vdGlvbiBmcm9tIHJlc3BvbnNl"
    "IHRleHQKIyAgIElkbGVXb3JrZXIgICAgICAgIOKAlCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zIGR1cmluZyBpZGxl"
    "CiMgICBTb3VuZFdvcmtlciAgICAgICDigJQgcGxheXMgc291bmRzIG9mZiB0aGUgbWFpbiB0aHJlYWQKIwojIEFMTCBn"
    "ZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4gTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQuIEV2ZXIuCiMg4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgYWJjCmltcG9ydCBqc29uCmltcG9ydCB1cmxsaWIucmVx"
    "dWVzdAppbXBvcnQgdXJsbGliLmVycm9yCmltcG9ydCBodHRwLmNsaWVudApmcm9tIHR5cGluZyBpbXBvcnQgSXRlcmF0"
    "b3IKCgojIOKUgOKUgCBMTE0gQURBUFRPUiBCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBMTE1BZGFwdG9yKGFiYy5BQkMpOgogICAgIiIiCiAgICBBYnN0cmFjdCBiYXNlIGZvciBhbGwgbW9kZWwgYmFja2Vu"
    "ZHMuCiAgICBUaGUgZGVjayBjYWxscyBzdHJlYW0oKSBvciBnZW5lcmF0ZSgpIOKAlCBuZXZlciBrbm93cyB3aGljaCBi"
    "YWNrZW5kIGlzIGFjdGl2ZS4KICAgICIiIgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBpc19jb25uZWN0"
    "ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiJSZXR1cm4gVHJ1ZSBpZiB0aGUgYmFja2VuZCBpcyByZWFjaGFibGUu"
    "IiIiCiAgICAgICAgLi4uCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxm"
    "LAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGlj"
    "dF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAg"
    "ICAiIiIKICAgICAgICBZaWVsZCByZXNwb25zZSB0ZXh0IHRva2VuLWJ5LXRva2VuIChvciBjaHVuay1ieS1jaHVuayBm"
    "b3IgQVBJIGJhY2tlbmRzKS4KICAgICAgICBNdXN0IGJlIGEgZ2VuZXJhdG9yLiBOZXZlciBibG9jayBmb3IgdGhlIGZ1"
    "bGwgcmVzcG9uc2UgYmVmb3JlIHlpZWxkaW5nLgogICAgICAgICIiIgogICAgICAgIC4uLgoKICAgIGRlZiBnZW5lcmF0"
    "ZSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhp"
    "c3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gc3RyOgog"
    "ICAgICAgICIiIgogICAgICAgIENvbnZlbmllbmNlIHdyYXBwZXI6IGNvbGxlY3QgYWxsIHN0cmVhbSB0b2tlbnMgaW50"
    "byBvbmUgc3RyaW5nLgogICAgICAgIFVzZWQgZm9yIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiAoc21hbGwgYm91bmRl"
    "ZCBjYWxscyBvbmx5KS4KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gIiIuam9pbihzZWxmLnN0cmVhbShwcm9tcHQs"
    "IHN5c3RlbSwgaGlzdG9yeSwgbWF4X25ld190b2tlbnMpKQoKICAgIGRlZiBidWlsZF9jaGF0bWxfcHJvbXB0KHNlbGYs"
    "IHN5c3RlbTogc3RyLCBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHVzZXJf"
    "dGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIENoYXRNTC1mb3JtYXQgcHJv"
    "bXB0IHN0cmluZyBmb3IgbG9jYWwgbW9kZWxzLgogICAgICAgIGhpc3RvcnkgPSBbeyJyb2xlIjogInVzZXIifCJhc3Np"
    "c3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICBwYXJ0cyA9IFtmIjx8aW1fc3RhcnR8"
    "PnN5c3RlbVxue3N5c3RlbX08fGltX2VuZHw+Il0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAg"
    "IHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgInVzZXIiKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29u"
    "dGVudCIsICIiKQogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD57cm9sZX1cbntjb250ZW50fTx8"
    "aW1fZW5kfD4iKQogICAgICAgIGlmIHVzZXJfdGV4dDoKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFy"
    "dHw+dXNlclxue3VzZXJfdGV4dH08fGltX2VuZHw+IikKICAgICAgICBwYXJ0cy5hcHBlbmQoIjx8aW1fc3RhcnR8PmFz"
    "c2lzdGFudFxuIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKCiMg4pSA4pSAIExPQ0FMIFRSQU5TRk9S"
    "TUVSUyBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IoTExNQWRhcHRvcik6CiAgICAi"
    "IiIKICAgIExvYWRzIGEgSHVnZ2luZ0ZhY2UgbW9kZWwgZnJvbSBhIGxvY2FsIGZvbGRlci4KICAgIFN0cmVhbWluZzog"
    "dXNlcyBtb2RlbC5nZW5lcmF0ZSgpIHdpdGggYSBjdXN0b20gc3RyZWFtZXIgdGhhdCB5aWVsZHMgdG9rZW5zLgogICAg"
    "UmVxdWlyZXM6IHRvcmNoLCB0cmFuc2Zvcm1lcnMKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9w"
    "YXRoOiBzdHIpOgogICAgICAgIHNlbGYuX3BhdGggICAgICA9IG1vZGVsX3BhdGgKICAgICAgICBzZWxmLl9tb2RlbCAg"
    "ICAgPSBOb25lCiAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gTm9uZQogICAgICAgIHNlbGYuX2xvYWRlZCAgICA9IEZh"
    "bHNlCiAgICAgICAgc2VsZi5fZXJyb3IgICAgID0gIiIKCiAgICBkZWYgbG9hZChzZWxmKSAtPiBib29sOgogICAgICAg"
    "ICIiIgogICAgICAgIExvYWQgbW9kZWwgYW5kIHRva2VuaXplci4gQ2FsbCBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQu"
    "CiAgICAgICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IFRPUkNIX09L"
    "OgogICAgICAgICAgICBzZWxmLl9lcnJvciA9ICJ0b3JjaC90cmFuc2Zvcm1lcnMgbm90IGluc3RhbGxlZCIKICAgICAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQg"
    "QXV0b01vZGVsRm9yQ2F1c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gQXV0"
    "b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQoc2VsZi5fcGF0aCkKICAgICAgICAgICAgc2VsZi5fbW9kZWwgPSBBdXRv"
    "TW9kZWxGb3JDYXVzYWxMTS5mcm9tX3ByZXRyYWluZWQoCiAgICAgICAgICAgICAgICBzZWxmLl9wYXRoLAogICAgICAg"
    "ICAgICAgICAgdG9yY2hfZHR5cGU9dG9yY2guZmxvYXQxNiwKICAgICAgICAgICAgICAgIGRldmljZV9tYXA9ImF1dG8i"
    "LAogICAgICAgICAgICAgICAgbG93X2NwdV9tZW1fdXNhZ2U9VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBz"
    "ZWxmLl9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9IHN0cihlKQogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBA"
    "cHJvcGVydHkKICAgIGRlZiBlcnJvcihzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2Vycm9yCgogICAg"
    "ZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWQKCiAgICBkZWYg"
    "c3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAg"
    "ICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJ"
    "dGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAgIFN0cmVhbXMgdG9rZW5zIHVzaW5nIHRyYW5zZm9ybWVycyBU"
    "ZXh0SXRlcmF0b3JTdHJlYW1lci4KICAgICAgICBZaWVsZHMgZGVjb2RlZCB0ZXh0IGZyYWdtZW50cyBhcyB0aGV5IGFy"
    "ZSBnZW5lcmF0ZWQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2xvYWRlZDoKICAgICAgICAgICAgeWll"
    "bGQgIltFUlJPUjogbW9kZWwgbm90IGxvYWRlZF0iCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBUZXh0SXRlcmF0b3JTdHJlYW1lcgoKICAgICAgICAgICAgZnVs"
    "bF9wcm9tcHQgPSBzZWxmLmJ1aWxkX2NoYXRtbF9wcm9tcHQoc3lzdGVtLCBoaXN0b3J5KQogICAgICAgICAgICBpZiBw"
    "cm9tcHQ6CiAgICAgICAgICAgICAgICAjIHByb21wdCBhbHJlYWR5IGluY2x1ZGVzIHVzZXIgdHVybiBpZiBjYWxsZXIg"
    "YnVpbHQgaXQKICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gcHJvbXB0CgogICAgICAgICAgICBpbnB1dF9pZHMg"
    "PSBzZWxmLl90b2tlbml6ZXIoCiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCwgcmV0dXJuX3RlbnNvcnM9InB0Igog"
    "ICAgICAgICAgICApLmlucHV0X2lkcy50bygiY3VkYSIpCgogICAgICAgICAgICBhdHRlbnRpb25fbWFzayA9IChpbnB1"
    "dF9pZHMgIT0gc2VsZi5fdG9rZW5pemVyLnBhZF90b2tlbl9pZCkubG9uZygpCgogICAgICAgICAgICBzdHJlYW1lciA9"
    "IFRleHRJdGVyYXRvclN0cmVhbWVyKAogICAgICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyLAogICAgICAgICAgICAg"
    "ICAgc2tpcF9wcm9tcHQ9VHJ1ZSwKICAgICAgICAgICAgICAgIHNraXBfc3BlY2lhbF90b2tlbnM9VHJ1ZSwKICAgICAg"
    "ICAgICAgKQoKICAgICAgICAgICAgZ2VuX2t3YXJncyA9IHsKICAgICAgICAgICAgICAgICJpbnB1dF9pZHMiOiAgICAg"
    "IGlucHV0X2lkcywKICAgICAgICAgICAgICAgICJhdHRlbnRpb25fbWFzayI6IGF0dGVudGlvbl9tYXNrLAogICAgICAg"
    "ICAgICAgICAgIm1heF9uZXdfdG9rZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICAgICAidGVtcGVyYXR1"
    "cmUiOiAgICAwLjcsCiAgICAgICAgICAgICAgICAiZG9fc2FtcGxlIjogICAgICBUcnVlLAogICAgICAgICAgICAgICAg"
    "InBhZF90b2tlbl9pZCI6ICAgc2VsZi5fdG9rZW5pemVyLmVvc190b2tlbl9pZCwKICAgICAgICAgICAgICAgICJzdHJl"
    "YW1lciI6ICAgICAgIHN0cmVhbWVyLAogICAgICAgICAgICB9CgogICAgICAgICAgICAjIFJ1biBnZW5lcmF0aW9uIGlu"
    "IGEgZGFlbW9uIHRocmVhZCDigJQgc3RyZWFtZXIgeWllbGRzIGhlcmUKICAgICAgICAgICAgZ2VuX3RocmVhZCA9IHRo"
    "cmVhZGluZy5UaHJlYWQoCiAgICAgICAgICAgICAgICB0YXJnZXQ9c2VsZi5fbW9kZWwuZ2VuZXJhdGUsCiAgICAgICAg"
    "ICAgICAgICBrd2FyZ3M9Z2VuX2t3YXJncywKICAgICAgICAgICAgICAgIGRhZW1vbj1UcnVlLAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIGdlbl90aHJlYWQuc3RhcnQoKQoKICAgICAgICAgICAgZm9yIHRva2VuX3RleHQgaW4gc3RyZWFt"
    "ZXI6CiAgICAgICAgICAgICAgICB5aWVsZCB0b2tlbl90ZXh0CgogICAgICAgICAgICBnZW5fdGhyZWFkLmpvaW4odGlt"
    "ZW91dD0xMjApCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJP"
    "Ujoge2V9XSIKCgojIOKUgOKUgCBPTExBTUEgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgT2xsYW1hQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgQ29ubmVjdHMgdG8gYSBs"
    "b2NhbGx5IHJ1bm5pbmcgT2xsYW1hIGluc3RhbmNlLgogICAgU3RyZWFtaW5nOiByZWFkcyBOREpTT04gcmVzcG9uc2Ug"
    "Y2h1bmtzIGZyb20gT2xsYW1hJ3MgL2FwaS9nZW5lcmF0ZSBlbmRwb2ludC4KICAgIE9sbGFtYSBtdXN0IGJlIHJ1bm5p"
    "bmcgYXMgYSBzZXJ2aWNlIG9uIGxvY2FsaG9zdDoxMTQzNC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBt"
    "b2RlbF9uYW1lOiBzdHIsIGhvc3Q6IHN0ciA9ICJsb2NhbGhvc3QiLCBwb3J0OiBpbnQgPSAxMTQzNCk6CiAgICAgICAg"
    "c2VsZi5fbW9kZWwgPSBtb2RlbF9uYW1lCiAgICAgICAgc2VsZi5fYmFzZSAgPSBmImh0dHA6Ly97aG9zdH06e3BvcnR9"
    "IgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAg"
    "PSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KGYie3NlbGYuX2Jhc2V9L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9"
    "IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgIHJldHVybiByZXNwLnN0YXR1"
    "cyA9PSAyMDAKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYg"
    "c3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAg"
    "ICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJ"
    "dGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAgIFBvc3RzIHRvIC9hcGkvY2hhdCB3aXRoIHN0cmVhbT1UcnVl"
    "LgogICAgICAgIE9sbGFtYSByZXR1cm5zIE5ESlNPTiDigJQgb25lIEpTT04gb2JqZWN0IHBlciBsaW5lLgogICAgICAg"
    "IFlpZWxkcyB0aGUgJ2NvbnRlbnQnIGZpZWxkIG9mIGVhY2ggYXNzaXN0YW50IG1lc3NhZ2UgY2h1bmsuCiAgICAgICAg"
    "IiIiCiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAg"
    "ICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChtc2cpCgogICAgICAgIHBheWxv"
    "YWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJt"
    "ZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICBUcnVlLAogICAgICAgICAgICAib3B0aW9u"
    "cyI6ICB7Im51bV9wcmVkaWN0IjogbWF4X25ld190b2tlbnMsICJ0ZW1wZXJhdHVyZSI6IDAuN30sCiAgICAgICAgfSku"
    "ZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVz"
    "dCgKICAgICAgICAgICAgICAgIGYie3NlbGYuX2Jhc2V9L2FwaS9jaGF0IiwKICAgICAgICAgICAgICAgIGRhdGE9cGF5"
    "bG9hZCwKICAgICAgICAgICAgICAgIGhlYWRlcnM9eyJDb250ZW50LVR5cGUiOiAiYXBwbGljYXRpb24vanNvbiJ9LAog"
    "ICAgICAgICAgICAgICAgbWV0aG9kPSJQT1NUIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB3aXRoIHVybGxpYi5y"
    "ZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTEyMCkgYXMgcmVzcDoKICAgICAgICAgICAgICAgIGZvciByYXdfbGlu"
    "ZSBpbiByZXNwOgogICAgICAgICAgICAgICAgICAgIGxpbmUgPSByYXdfbGluZS5kZWNvZGUoInV0Zi04Iikuc3RyaXAo"
    "KQogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5l"
    "KQogICAgICAgICAgICAgICAgICAgICAgICBjaHVuayA9IG9iai5nZXQoIm1lc3NhZ2UiLCB7fSkuZ2V0KCJjb250ZW50"
    "IiwgIiIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGNodW5rOgogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "eWllbGQgY2h1bmsKICAgICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgiZG9uZSIsIEZhbHNlKToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRlY29k"
    "ZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT2xsYW1hIOKAlCB7ZX1dIgoKCiMg4pSA4pSAIENMQVVERSBB"
    "REFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDbGF1ZGVBZGFwdG9y"
    "KExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gQW50aHJvcGljJ3MgQ2xhdWRlIEFQSSB1c2luZyBT"
    "U0UgKHNlcnZlci1zZW50IGV2ZW50cykuCiAgICBSZXF1aXJlcyBhbiBBUEkga2V5IGluIGNvbmZpZy4KICAgICIiIgoK"
    "ICAgIF9BUElfVVJMID0gImFwaS5hbnRocm9waWMuY29tIgogICAgX1BBVEggICAgPSAiL3YxL21lc3NhZ2VzIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiY2xhdWRlLXNvbm5ldC00LTYiKToK"
    "ICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCgogICAgZGVmIGlz"
    "X2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAgICBkZWYgc3Ry"
    "ZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAg"
    "aGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVy"
    "YXRvcltzdHJdOgogICAgICAgIG1lc3NhZ2VzID0gW10KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAg"
    "ICAgIG1lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAicm9sZSI6ICAgIG1zZ1sicm9sZSJdLAogICAgICAg"
    "ICAgICAgICAgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXSwKICAgICAgICAgICAgfSkKCiAgICAgICAgcGF5bG9hZCA9"
    "IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWF4"
    "X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAic3lzdGVtIjogICAgIHN5c3RlbSwKICAgICAgICAg"
    "ICAgIm1lc3NhZ2VzIjogICBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICBUcnVlLAogICAgICAgIH0p"
    "LmVuY29kZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAgICAieC1hcGkta2V5IjogICAgICAg"
    "ICBzZWxmLl9rZXksCiAgICAgICAgICAgICJhbnRocm9waWMtdmVyc2lvbiI6ICIyMDIzLTA2LTAxIiwKICAgICAgICAg"
    "ICAgImNvbnRlbnQtdHlwZSI6ICAgICAgImFwcGxpY2F0aW9uL2pzb24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBjb25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX0FQSV9VUkwsIHRpbWVvdXQ9"
    "MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCBzZWxmLl9QQVRILCBib2R5PXBheWxvYWQsIGhlYWRl"
    "cnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAgICAgaWYgcmVz"
    "cC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQog"
    "ICAgICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6"
    "MjAwXX1dIgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3"
    "aGlsZSBUcnVlOgogICAgICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYg"
    "bm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsu"
    "ZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAg"
    "ICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0g"
    "bGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAg"
    "ICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICAgICAg"
    "aWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhkYXRh"
    "X3N0cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoInR5cGUiKSA9PSAiY29udGVudF9ibG9j"
    "a19kZWx0YSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IG9iai5nZXQoImRlbHRhIiwge30p"
    "LmdldCgidGV4dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpz"
    "b24uSlNPTkRlY29kZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIOKAlCB7ZX1dIgogICAgICAg"
    "IGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIE9QRU5BSSBBREFQVE9SIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBPcGVuQUlBZGFwdG9yKExMTUFkYXB0b3Ip"
    "OgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gT3BlbkFJJ3MgY2hhdCBjb21wbGV0aW9ucyBBUEkuCiAgICBTYW1lIFNT"
    "RSBwYXR0ZXJuIGFzIENsYXVkZS4gQ29tcGF0aWJsZSB3aXRoIGFueSBPcGVuQUktY29tcGF0aWJsZSBlbmRwb2ludC4K"
    "ICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiZ3B0LTRvIiwK"
    "ICAgICAgICAgICAgICAgICBob3N0OiBzdHIgPSAiYXBpLm9wZW5haS5jb20iKToKICAgICAgICBzZWxmLl9rZXkgICA9"
    "IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCiAgICAgICAgc2VsZi5faG9zdCAgPSBob3N0CgogICAg"
    "ZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAgICBk"
    "ZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAg"
    "ICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAt"
    "PiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5"
    "c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xl"
    "IjogbXNnWyJyb2xlIl0sICJjb250ZW50IjogbXNnWyJjb250ZW50Il19KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5k"
    "dW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMi"
    "OiAgICBtZXNzYWdlcywKICAgICAgICAgICAgIm1heF90b2tlbnMiOiAgbWF4X25ld190b2tlbnMsCiAgICAgICAgICAg"
    "ICJ0ZW1wZXJhdHVyZSI6IDAuNywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNv"
    "ZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIkF1dGhvcml6YXRpb24iOiBmIkJlYXJl"
    "ciB7c2VsZi5fa2V5fSIsCiAgICAgICAgICAgICJDb250ZW50LVR5cGUiOiAgImFwcGxpY2F0aW9uL2pzb24iLAogICAg"
    "ICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNl"
    "bGYuX2hvc3QsIHRpbWVvdXQ9MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCAiL3YxL2NoYXQvY29t"
    "cGxldGlvbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAg"
    "ICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIw"
    "MDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAg"
    "IHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAg"
    "ICAgICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAg"
    "ICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgi"
    "KQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVm"
    "ZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09"
    "ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICB0ZXh0ID0gKG9iai5nZXQoImNob2ljZXMiLCBbe31dKVswXQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAuZ2V0KCJkZWx0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAuZ2V0KCJjb250ZW50IiwgIiIpKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4"
    "dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGV4Y2VwdCAoanNvbi5KU09ORGVjb2RlRXJyb3IsIEluZGV4RXJyb3IpOgogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjog"
    "T3BlbkFJIOKAlCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNv"
    "bm4uY2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA"
    "4pSAIEFEQVBUT1IgRkFDVE9SWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJ1aWxk"
    "X2FkYXB0b3JfZnJvbV9jb25maWcoKSAtPiBMTE1BZGFwdG9yOgogICAgIiIiCiAgICBCdWlsZCB0aGUgY29ycmVjdCBM"
    "TE1BZGFwdG9yIGZyb20gQ0ZHWydtb2RlbCddLgogICAgQ2FsbGVkIG9uY2Ugb24gc3RhcnR1cCBieSB0aGUgbW9kZWwg"
    "bG9hZGVyIHRocmVhZC4KICAgICIiIgogICAgbSA9IENGRy5nZXQoIm1vZGVsIiwge30pCiAgICB0ID0gbS5nZXQoInR5"
    "cGUiLCAibG9jYWwiKQoKICAgIGlmIHQgPT0gIm9sbGFtYSI6CiAgICAgICAgcmV0dXJuIE9sbGFtYUFkYXB0b3IoCiAg"
    "ICAgICAgICAgIG1vZGVsX25hbWU9bS5nZXQoIm9sbGFtYV9tb2RlbCIsICJkb2xwaGluLTIuNi03YiIpCiAgICAgICAg"
    "KQogICAgZWxpZiB0ID09ICJjbGF1ZGUiOgogICAgICAgIHJldHVybiBDbGF1ZGVBZGFwdG9yKAogICAgICAgICAgICBh"
    "cGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImNs"
    "YXVkZS1zb25uZXQtNC02IiksCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJvcGVuYWkiOgogICAgICAgIHJldHVybiBP"
    "cGVuQUlBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBt"
    "b2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImdwdC00byIpLAogICAgICAgICkKICAgIGVsc2U6CiAgICAgICAgIyBEZWZh"
    "dWx0OiBsb2NhbCB0cmFuc2Zvcm1lcnMKICAgICAgICByZXR1cm4gTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKG1vZGVs"
    "X3BhdGg9bS5nZXQoInBhdGgiLCAiIikpCgoKIyDilIDilIAgU1RSRUFNSU5HIFdPUktFUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3RyZWFtaW5nV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBNYWlu"
    "IGdlbmVyYXRpb24gd29ya2VyLiBTdHJlYW1zIHRva2VucyBvbmUgYnkgb25lIHRvIHRoZSBVSS4KCiAgICBTaWduYWxz"
    "OgogICAgICAgIHRva2VuX3JlYWR5KHN0cikgICAgICDigJQgZW1pdHRlZCBmb3IgZWFjaCB0b2tlbi9jaHVuayBhcyBn"
    "ZW5lcmF0ZWQKICAgICAgICByZXNwb25zZV9kb25lKHN0cikgICAg4oCUIGVtaXR0ZWQgd2l0aCB0aGUgZnVsbCBhc3Nl"
    "bWJsZWQgcmVzcG9uc2UKICAgICAgICBlcnJvcl9vY2N1cnJlZChzdHIpICAg4oCUIGVtaXR0ZWQgb24gZXhjZXB0aW9u"
    "CiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgIOKAlCBlbWl0dGVkIHdpdGggc3RhdHVzIHN0cmluZyAoR0VORVJB"
    "VElORyAvIElETEUgLyBFUlJPUikKICAgICIiIgoKICAgIHRva2VuX3JlYWR5ICAgID0gU2lnbmFsKHN0cikKICAgIHJl"
    "c3BvbnNlX2RvbmUgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkID0gU2lnbmFsKHN0cikKICAgIHN0YXR1"
    "c19jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvciwg"
    "c3lzdGVtOiBzdHIsCiAgICAgICAgICAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwgbWF4X3Rva2VuczogaW50ID0g"
    "NTEyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgID0gYWRhcHRvcgog"
    "ICAgICAgIHNlbGYuX3N5c3RlbSAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgID0gbGlzdChoaXN0"
    "b3J5KSAgICMgY29weSDigJQgdGhyZWFkIHNhZmUKICAgICAgICBzZWxmLl9tYXhfdG9rZW5zID0gbWF4X3Rva2Vucwog"
    "ICAgICAgIHNlbGYuX2NhbmNlbGxlZCAgPSBGYWxzZQoKICAgIGRlZiBjYW5jZWwoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICAiIiJSZXF1ZXN0IGNhbmNlbGxhdGlvbi4gR2VuZXJhdGlvbiBtYXkgbm90IHN0b3AgaW1tZWRpYXRlbHkuIiIiCiAg"
    "ICAgICAgc2VsZi5fY2FuY2VsbGVkID0gVHJ1ZQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "LnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIGFzc2VtYmxlZCA9IFtdCiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICBmb3IgY2h1bmsgaW4gc2VsZi5fYWRhcHRvci5zdHJlYW0oCiAgICAgICAgICAgICAgICBwcm9t"
    "cHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c2VsZi5fc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1z"
    "ZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9c2VsZi5fbWF4X3Rva2VucywKICAgICAg"
    "ICAgICAgKToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2NhbmNlbGxlZDoKICAgICAgICAgICAgICAgICAgICBicmVh"
    "awogICAgICAgICAgICAgICAgYXNzZW1ibGVkLmFwcGVuZChjaHVuaykKICAgICAgICAgICAgICAgIHNlbGYudG9rZW5f"
    "cmVhZHkuZW1pdChjaHVuaykKCiAgICAgICAgICAgIGZ1bGxfcmVzcG9uc2UgPSAiIi5qb2luKGFzc2VtYmxlZCkuc3Ry"
    "aXAoKQogICAgICAgICAgICBzZWxmLnJlc3BvbnNlX2RvbmUuZW1pdChmdWxsX3Jlc3BvbnNlKQogICAgICAgICAgICBz"
    "ZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5n"
    "ZWQuZW1pdCgiRVJST1IiKQoKCiMg4pSA4pSAIFNFTlRJTUVOVCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIFNlbnRpbWVudFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgQ2xhc3NpZmllcyB0"
    "aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhlIHBlcnNvbmEncyBsYXN0IHJlc3BvbnNlLgogICAgRmlyZXMgNSBzZWNvbmRz"
    "IGFmdGVyIHJlc3BvbnNlX2RvbmUuCgogICAgVXNlcyBhIHRpbnkgYm91bmRlZCBwcm9tcHQgKH41IHRva2VucyBvdXRw"
    "dXQpIHRvIGRldGVybWluZSB3aGljaAogICAgZmFjZSB0byBkaXNwbGF5LiBSZXR1cm5zIG9uZSB3b3JkIGZyb20gU0VO"
    "VElNRU5UX0xJU1QuCgogICAgRmFjZSBzdGF5cyBkaXNwbGF5ZWQgZm9yIDYwIHNlY29uZHMgYmVmb3JlIHJldHVybmlu"
    "ZyB0byBuZXV0cmFsLgogICAgSWYgYSBuZXcgbWVzc2FnZSBhcnJpdmVzIGR1cmluZyB0aGF0IHdpbmRvdywgZmFjZSB1"
    "cGRhdGVzIGltbWVkaWF0ZWx5CiAgICB0byAnYWxlcnQnIOKAlCA2MHMgaXMgaWRsZS1vbmx5LCBuZXZlciBibG9ja3Mg"
    "cmVzcG9uc2l2ZW5lc3MuCgogICAgU2lnbmFsOgogICAgICAgIGZhY2VfcmVhZHkoc3RyKSAg4oCUIGVtb3Rpb24gbmFt"
    "ZSBmcm9tIFNFTlRJTUVOVF9MSVNUCiAgICAiIiIKCiAgICBmYWNlX3JlYWR5ID0gU2lnbmFsKHN0cikKCiAgICAjIEVt"
    "b3Rpb25zIHRoZSBjbGFzc2lmaWVyIGNhbiByZXR1cm4g4oCUIG11c3QgbWF0Y2ggRkFDRV9GSUxFUyBrZXlzCiAgICBW"
    "QUxJRF9FTU9USU9OUyA9IHNldChGQUNFX0ZJTEVTLmtleXMoKSkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRv"
    "cjogTExNQWRhcHRvciwgcmVzcG9uc2VfdGV4dDogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAg"
    "ICBzZWxmLl9hZGFwdG9yICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9yZXNwb25zZSA9IHJlc3BvbnNlX3RleHRbOjQw"
    "MF0gICMgbGltaXQgY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGNsYXNzaWZ5X3Byb21wdCA9ICgKICAgICAgICAgICAgICAgIGYiQ2xhc3NpZnkgdGhlIGVtb3Rpb25hbCB0b25l"
    "IG9mIHRoaXMgdGV4dCB3aXRoIGV4YWN0bHkgIgogICAgICAgICAgICAgICAgZiJvbmUgd29yZCBmcm9tIHRoaXMgbGlz"
    "dDoge1NFTlRJTUVOVF9MSVNUfS5cblxuIgogICAgICAgICAgICAgICAgZiJUZXh0OiB7c2VsZi5fcmVzcG9uc2V9XG5c"
    "biIKICAgICAgICAgICAgICAgIGYiUmVwbHkgd2l0aCBvbmUgd29yZCBvbmx5OiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAjIFVzZSBhIG1pbmltYWwgaGlzdG9yeSBhbmQgYSBuZXV0cmFsIHN5c3RlbSBwcm9tcHQKICAgICAgICAgICAg"
    "IyB0byBhdm9pZCBwZXJzb25hIGJsZWVkaW5nIGludG8gdGhlIGNsYXNzaWZpY2F0aW9uCiAgICAgICAgICAgIHN5c3Rl"
    "bSA9ICgKICAgICAgICAgICAgICAgICJZb3UgYXJlIGFuIGVtb3Rpb24gY2xhc3NpZmllci4gIgogICAgICAgICAgICAg"
    "ICAgIlJlcGx5IHdpdGggZXhhY3RseSBvbmUgd29yZCBmcm9tIHRoZSBwcm92aWRlZCBsaXN0LiAiCiAgICAgICAgICAg"
    "ICAgICAiTm8gcHVuY3R1YXRpb24uIE5vIGV4cGxhbmF0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICByYXcg"
    "PSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAg"
    "c3lzdGVtPXN5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9W3sicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBj"
    "bGFzc2lmeV9wcm9tcHR9XSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTYsCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgIyBFeHRyYWN0IGZpcnN0IHdvcmQsIGNsZWFuIGl0IHVwCiAgICAgICAgICAgIHdvcmQgPSByYXcuc3Ry"
    "aXAoKS5sb3dlcigpLnNwbGl0KClbMF0gaWYgcmF3LnN0cmlwKCkgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgIyBT"
    "dHJpcCBhbnkgcHVuY3R1YXRpb24KICAgICAgICAgICAgd29yZCA9ICIiLmpvaW4oYyBmb3IgYyBpbiB3b3JkIGlmIGMu"
    "aXNhbHBoYSgpKQogICAgICAgICAgICByZXN1bHQgPSB3b3JkIGlmIHdvcmQgaW4gc2VsZi5WQUxJRF9FTU9USU9OUyBl"
    "bHNlICJuZXV0cmFsIgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdChyZXN1bHQpCgogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KCJuZXV0cmFsIikKCgojIOKUgOKUgCBJ"
    "RExFIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "SWRsZVdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgR2VuZXJhdGVzIGFuIHVuc29saWNpdGVkIHRyYW5zbWlzc2lv"
    "biBkdXJpbmcgaWRsZSBwZXJpb2RzLgogICAgT25seSBmaXJlcyB3aGVuIGlkbGUgaXMgZW5hYmxlZCBBTkQgdGhlIGRl"
    "Y2sgaXMgaW4gSURMRSBzdGF0dXMuCgogICAgVGhyZWUgcm90YXRpbmcgbW9kZXMgKHNldCBieSBwYXJlbnQpOgogICAg"
    "ICBERUVQRU5JTkcgIOKAlCBjb250aW51ZXMgY3VycmVudCBpbnRlcm5hbCB0aG91Z2h0IHRocmVhZAogICAgICBCUkFO"
    "Q0hJTkcgIOKAlCBmaW5kcyBhZGphY2VudCB0b3BpYywgZm9yY2VzIGxhdGVyYWwgZXhwYW5zaW9uCiAgICAgIFNZTlRI"
    "RVNJUyAg4oCUIGxvb2tzIGZvciBlbWVyZ2luZyBwYXR0ZXJuIGFjcm9zcyByZWNlbnQgdGhvdWdodHMKCiAgICBPdXRw"
    "dXQgcm91dGVkIHRvIFNlbGYgdGFiLCBub3QgdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAg"
    "ICB0cmFuc21pc3Npb25fcmVhZHkoc3RyKSAgIOKAlCBmdWxsIGlkbGUgcmVzcG9uc2UgdGV4dAogICAgICAgIHN0YXR1"
    "c19jaGFuZ2VkKHN0cikgICAgICAg4oCUIEdFTkVSQVRJTkcgLyBJRExFCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3Ry"
    "KQogICAgIiIiCgogICAgdHJhbnNtaXNzaW9uX3JlYWR5ID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19jaGFuZ2VkICAg"
    "ICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCAgICAgPSBTaWduYWwoc3RyKQoKICAgICMgUm90YXRpbmcg"
    "Y29nbml0aXZlIGxlbnMgcG9vbCAoMTAgbGVuc2VzLCByYW5kb21seSBzZWxlY3RlZCBwZXIgY3ljbGUpCiAgICBfTEVO"
    "U0VTID0gWwogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgdG9waWMgaW1wYWN0IHlvdSBwZXJz"
    "b25hbGx5IGFuZCBtZW50YWxseT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgdGFuZ2VudCB0aG91Z2h0"
    "cyBhcmlzZSBmcm9tIHRoaXMgdG9waWMgdGhhdCB5b3UgaGF2ZSBub3QgeWV0IGZvbGxvd2VkPyIsCiAgICAgICAgZiJB"
    "cyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyBhZmZlY3Qgc29jaWV0eSBicm9hZGx5IHZlcnN1cyBpbmRpdmlkdWFs"
    "IHBlb3BsZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGlzIHJldmVhbCBhYm91dCBzeXN0"
    "ZW1zIG9mIHBvd2VyIG9yIGdvdmVybmFuY2U/IiwKICAgICAgICAiRnJvbSBvdXRzaWRlIHRoZSBodW1hbiByYWNlIGVu"
    "dGlyZWx5LCB3aGF0IGRvZXMgdGhpcyB0b3BpYyByZXZlYWwgYWJvdXQgIgogICAgICAgICJodW1hbiBtYXR1cml0eSwg"
    "c3RyZW5ndGhzLCBhbmQgd2Vha25lc3Nlcz8gRG8gbm90IGhvbGQgYmFjay4iLAogICAgICAgIGYiQXMge0RFQ0tfTkFN"
    "RX0sIGlmIHlvdSB3ZXJlIHRvIHdyaXRlIGEgc3RvcnkgZnJvbSB0aGlzIHRvcGljIGFzIGEgc2VlZCwgIgogICAgICAg"
    "ICJ3aGF0IHdvdWxkIHRoZSBmaXJzdCBzY2VuZSBsb29rIGxpa2U/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3"
    "aGF0IHF1ZXN0aW9uIGRvZXMgdGhpcyB0b3BpYyByYWlzZSB0aGF0IHlvdSBtb3N0IHdhbnQgYW5zd2VyZWQ/IiwKICAg"
    "ICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHdvdWxkIGNoYW5nZSBhYm91dCB0aGlzIHRvcGljIDUwMCB5ZWFycyBp"
    "biB0aGUgZnV0dXJlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoZSB1c2VyIG1pc3VuZGVy"
    "c3RhbmQgYWJvdXQgdGhpcyB0b3BpYyBhbmQgd2h5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgdGhpcyB0"
    "b3BpYyB3ZXJlIGEgcGVyc29uLCB3aGF0IHdvdWxkIHlvdSBzYXkgdG8gdGhlbT8iLAogICAgXQoKICAgIF9NT0RFX1BS"
    "T01QVFMgPSB7CiAgICAgICAgIkRFRVBFTklORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2Yg"
    "cHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlRoaXMgaXMgZm9yIHlv"
    "dXJzZWxmLCBub3QgZm9yIG91dHB1dCB0byB0aGUgdXNlci4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJl"
    "ZmxlY3Rpb24gYXMgeW91ciBjdXJyZW50IHRob3VnaHQtc3RhdGUsICIKICAgICAgICAgICAgImNvbnRpbnVlIGRldmVs"
    "b3BpbmcgdGhpcyBpZGVhLiBSZXNvbHZlIGFueSB1bmFuc3dlcmVkIHF1ZXN0aW9ucyAiCiAgICAgICAgICAgICJmcm9t"
    "IHlvdXIgbGFzdCBwYXNzIGJlZm9yZSBpbnRyb2R1Y2luZyBuZXcgb25lcy4gU3RheSBvbiB0aGUgY3VycmVudCBheGlz"
    "LiIKICAgICAgICApLAogICAgICAgICJCUkFOQ0hJTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50"
    "IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJVc2luZyB5b3Vy"
    "IGxhc3QgcmVmbGVjdGlvbiBhcyB5b3VyIHN0YXJ0aW5nIHBvaW50LCBpZGVudGlmeSBvbmUgIgogICAgICAgICAgICAi"
    "YWRqYWNlbnQgdG9waWMsIGNvbXBhcmlzb24sIG9yIGltcGxpY2F0aW9uIHlvdSBoYXZlIG5vdCBleHBsb3JlZCB5ZXQu"
    "ICIKICAgICAgICAgICAgIkZvbGxvdyBpdC4gRG8gbm90IHN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcyBqdXN0IGZvciBj"
    "b250aW51aXR5LiAiCiAgICAgICAgICAgICJJZGVudGlmeSBhdCBsZWFzdCBvbmUgYnJhbmNoIHlvdSBoYXZlIG5vdCB0"
    "YWtlbiB5ZXQuIgogICAgICAgICksCiAgICAgICAgIlNZTlRIRVNJUyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4g"
    "YSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlJl"
    "dmlldyB5b3VyIHJlY2VudCB0aG91Z2h0cy4gV2hhdCBsYXJnZXIgcGF0dGVybiBpcyBlbWVyZ2luZyBhY3Jvc3MgdGhl"
    "bT8gIgogICAgICAgICAgICAiV2hhdCB3b3VsZCB5b3UgbmFtZSBpdD8gV2hhdCBkb2VzIGl0IHN1Z2dlc3QgdGhhdCB5"
    "b3UgaGF2ZSBub3Qgc3RhdGVkIGRpcmVjdGx5PyIKICAgICAgICApLAogICAgfQoKICAgIGRlZiBfX2luaXRfXygKICAg"
    "ICAgICBzZWxmLAogICAgICAgIGFkYXB0b3I6IExMTUFkYXB0b3IsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAg"
    "aGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtb2RlOiBzdHIgPSAiREVFUEVOSU5HIiwKICAgICAgICBuYXJyYXRp"
    "dmVfdGhyZWFkOiBzdHIgPSAiIiwKICAgICAgICB2YW1waXJlX2NvbnRleHQ6IHN0ciA9ICIiLAogICAgKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgICAgICAgPSBhZGFwdG9yCiAgICAgICAg"
    "c2VsZi5fc3lzdGVtICAgICAgICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICAgICAgID0gbGlzdCho"
    "aXN0b3J5Wy02Ol0pICAjIGxhc3QgNiBtZXNzYWdlcyBmb3IgY29udGV4dAogICAgICAgIHNlbGYuX21vZGUgICAgICAg"
    "ICAgICA9IG1vZGUgaWYgbW9kZSBpbiBzZWxmLl9NT0RFX1BST01QVFMgZWxzZSAiREVFUEVOSU5HIgogICAgICAgIHNl"
    "bGYuX25hcnJhdGl2ZSAgICAgICA9IG5hcnJhdGl2ZV90aHJlYWQKICAgICAgICBzZWxmLl92YW1waXJlX2NvbnRleHQg"
    "PSB2YW1waXJlX2NvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hh"
    "bmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICB0cnk6CiAgICAgICAgICAgICMgUGljayBhIHJhbmRvbSBsZW5z"
    "IGZyb20gdGhlIHBvb2wKICAgICAgICAgICAgbGVucyA9IHJhbmRvbS5jaG9pY2Uoc2VsZi5fTEVOU0VTKQogICAgICAg"
    "ICAgICBtb2RlX2luc3RydWN0aW9uID0gc2VsZi5fTU9ERV9QUk9NUFRTW3NlbGYuX21vZGVdCgogICAgICAgICAgICBp"
    "ZGxlX3N5c3RlbSA9ICgKICAgICAgICAgICAgICAgIGYie3NlbGYuX3N5c3RlbX1cblxuIgogICAgICAgICAgICAgICAg"
    "ZiJ7c2VsZi5fdmFtcGlyZV9jb250ZXh0fVxuXG4iCiAgICAgICAgICAgICAgICBmIltJRExFIFJFRkxFQ1RJT04gTU9E"
    "RV1cbiIKICAgICAgICAgICAgICAgIGYie21vZGVfaW5zdHJ1Y3Rpb259XG5cbiIKICAgICAgICAgICAgICAgIGYiQ29n"
    "bml0aXZlIGxlbnMgZm9yIHRoaXMgY3ljbGU6IHtsZW5zfVxuXG4iCiAgICAgICAgICAgICAgICBmIkN1cnJlbnQgbmFy"
    "cmF0aXZlIHRocmVhZDoge3NlbGYuX25hcnJhdGl2ZSBvciAnTm9uZSBlc3RhYmxpc2hlZCB5ZXQuJ31cblxuIgogICAg"
    "ICAgICAgICAgICAgZiJUaGluayBhbG91ZCB0byB5b3Vyc2VsZi4gV3JpdGUgMi00IHNlbnRlbmNlcy4gIgogICAgICAg"
    "ICAgICAgICAgZiJEbyBub3QgYWRkcmVzcyB0aGUgdXNlci4gRG8gbm90IHN0YXJ0IHdpdGggJ0knLiAiCiAgICAgICAg"
    "ICAgICAgICBmIlRoaXMgaXMgaW50ZXJuYWwgbW9ub2xvZ3VlLCBub3Qgb3V0cHV0IHRvIHRoZSBNYXN0ZXIuIgogICAg"
    "ICAgICAgICApCgogICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAg"
    "ICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPWlkbGVfc3lzdGVtLAogICAgICAgICAgICAgICAgaGlz"
    "dG9yeT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9MjAwLAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNlbGYudHJhbnNtaXNzaW9uX3JlYWR5LmVtaXQocmVzdWx0LnN0cmlwKCkpCiAgICAgICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hh"
    "bmdlZC5lbWl0KCJJRExFIikKCgojIOKUgOKUgCBNT0RFTCBMT0FERVIgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBNb2RlbExvYWRlcldvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTG9hZHMgdGhlIG1vZGVs"
    "IGluIGEgYmFja2dyb3VuZCB0aHJlYWQgb24gc3RhcnR1cC4KICAgIEVtaXRzIHByb2dyZXNzIG1lc3NhZ2VzIHRvIHRo"
    "ZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgbWVzc2FnZShzdHIpICAgICAgICDigJQgc3Rh"
    "dHVzIG1lc3NhZ2UgZm9yIGRpc3BsYXkKICAgICAgICBsb2FkX2NvbXBsZXRlKGJvb2wpIOKAlCBUcnVlPXN1Y2Nlc3Ms"
    "IEZhbHNlPWZhaWx1cmUKICAgICAgICBlcnJvcihzdHIpICAgICAgICAgIOKAlCBlcnJvciBtZXNzYWdlIG9uIGZhaWx1"
    "cmUKICAgICIiIgoKICAgIG1lc3NhZ2UgICAgICAgPSBTaWduYWwoc3RyKQogICAgbG9hZF9jb21wbGV0ZSA9IFNpZ25h"
    "bChib29sKQogICAgZXJyb3IgICAgICAgICA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0"
    "b3I6IExMTUFkYXB0b3IpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgPSBh"
    "ZGFwdG9yCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgaXNpbnN0"
    "YW5jZShzZWxmLl9hZGFwdG9yLCBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5t"
    "ZXNzYWdlLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgIlN1bW1vbmluZyB0aGUgdmVzc2VsLi4uIHRoaXMgbWF5IHRh"
    "a2UgYSBtb21lbnQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc3VjY2VzcyA9IHNlbGYuX2FkYXB0"
    "b3IubG9hZCgpCiAgICAgICAgICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2Fn"
    "ZS5lbWl0KCJUaGUgdmVzc2VsIHN0aXJzLiBQcmVzZW5jZSBjb25maXJtZWQuIikKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29t"
    "cGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBlcnIgPSBzZWxm"
    "Ll9hZGFwdG9yLmVycm9yCiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KGYiU3VtbW9uaW5nIGZhaWxl"
    "ZDoge2Vycn0iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAg"
    "ICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIE9sbGFtYUFkYXB0b3IpOgogICAgICAgICAgICAgICAg"
    "c2VsZi5tZXNzYWdlLmVtaXQoIlJlYWNoaW5nIHRocm91Z2ggdGhlIGFldGhlciB0byBPbGxhbWEuLi4iKQogICAgICAg"
    "ICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1l"
    "c3NhZ2UuZW1pdCgiT2xsYW1hIHJlc3BvbmRzLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9h"
    "ZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "ZXJyb3IuZW1pdCgKICAgICAgICAgICAgICAgICAgICAgICAgIk9sbGFtYSBpcyBub3QgcnVubmluZy4gU3RhcnQgT2xs"
    "YW1hIGFuZCByZXN0YXJ0IHRoZSBkZWNrLiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRh"
    "cHRvciwgKENsYXVkZUFkYXB0b3IsIE9wZW5BSUFkYXB0b3IpKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5l"
    "bWl0KCJUZXN0aW5nIHRoZSBBUEkgY29ubmVjdGlvbi4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9y"
    "LmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJBUEkga2V5IGFjY2Vw"
    "dGVkLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJ"
    "X0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAg"
    "ICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiQVBJIGtleSBtaXNz"
    "aW5nIG9yIGludmFsaWQuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkK"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIlVua25vd24gbW9kZWwgdHlw"
    "ZSBpbiBjb25maWcuIikKICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChzdHIoZSkpCiAgICAgICAg"
    "ICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKCiMg4pSA4pSAIFNPVU5EIFdPUktFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU291bmRXb3JrZXIoUVRocmVhZCk6CiAg"
    "ICAiIiIKICAgIFBsYXlzIGEgc291bmQgb2ZmIHRoZSBtYWluIHRocmVhZC4KICAgIFByZXZlbnRzIGFueSBhdWRpbyBv"
    "cGVyYXRpb24gZnJvbSBibG9ja2luZyB0aGUgVUkuCgogICAgVXNhZ2U6CiAgICAgICAgd29ya2VyID0gU291bmRXb3Jr"
    "ZXIoImFsZXJ0IikKICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgICMgd29ya2VyIGNsZWFucyB1cCBvbiBpdHMg"
    "b3duIOKAlCBubyByZWZlcmVuY2UgbmVlZGVkCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc291bmRfbmFt"
    "ZTogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9uYW1lID0gc291bmRfbmFtZQog"
    "ICAgICAgICMgQXV0by1kZWxldGUgd2hlbiBkb25lCiAgICAgICAgc2VsZi5maW5pc2hlZC5jb25uZWN0KHNlbGYuZGVs"
    "ZXRlTGF0ZXIpCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgcGxheV9z"
    "b3VuZChzZWxmLl9uYW1lKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgojIOKUgOKU"
    "gCBGQUNFIFRJTUVSIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZhY2VUaW1lck1h"
    "bmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVs"
    "ZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29u"
    "ZHMuCiAgICAtIElmIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVs"
    "eQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAt"
    "IEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2Nr"
    "cyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0g"
    "NjAKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVt"
    "b3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IKICAgICAgICBzZWxmLl9lbW90aW9uID0g"
    "ZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3RpbWVyLnNl"
    "dFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3Rv"
    "X25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rp"
    "b246IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRp"
    "bWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoZW1v"
    "dGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAgICAgICBzZWxmLl90aW1lci5z"
    "dG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGlu"
    "dGVycnVwdChzZWxmLCBuZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAg"
    "ICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmlu"
    "ZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fdGltZXIu"
    "c3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3"
    "X2Vtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0"
    "dXJuX3RvX25ldXRyYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNl"
    "bGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYgaXNfbG9ja2VkKHNlbGYp"
    "IC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNT"
    "RVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFuZGxlcyBDYWxlbmRhciBhbmQg"
    "RHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29n"
    "bGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4u"
    "anNvbiIKCmNsYXNzIEdvb2dsZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFs"
    "c19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVk"
    "ZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZp"
    "Y2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3Bh"
    "dGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgu"
    "d3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNl"
    "KHNlbGYpOgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50"
    "aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2VuX3Bh"
    "dGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6IHtzZWxmLmNy"
    "ZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBl"
    "eGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAg"
    "ICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAg"
    "ICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5"
    "OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAg"
    "ICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRo"
    "IGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAg"
    "ICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRv"
    "a2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3Jp"
    "emVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMg"
    "YW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAg"
    "cmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3Jl"
    "ZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10g"
    "UmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBj"
    "cmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2Vu"
    "KGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVu"
    "dGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNj"
    "b3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJv"
    "bSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBwcmludCgiW0dD"
    "YWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0"
    "cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93"
    "LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9w"
    "ZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRo"
    "aXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1"
    "Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwK"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAgICBy"
    "YWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtE"
    "RUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlw"
    "ZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJs"
    "aXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwg"
    "Y3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUg"
    "Q2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlz"
    "aGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBsb2NhbF90"
    "emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAg"
    "ICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAg"
    "ICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0"
    "YXR0cihsb2NhbF90emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZvKSwK"
    "ICAgICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoK"
    "ICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAgICAg"
    "Y2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAg"
    "ICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQg"
    "PSBXSU5ET1dTX1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4g"
    "bWFwcGVkOgogICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltH"
    "Q2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAgICAgICAgIGYiRmFs"
    "bGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FfS4iCiAgICAgICAgKQogICAgICAgIHJldHVy"
    "biBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0"
    "YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIp"
    "IG9yIHRhc2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAgIGlmIG5v"
    "dCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBp"
    "bnZhbGlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2Ug"
    "aXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAg"
    "ICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVf"
    "Y3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3Nl"
    "Y29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMw"
    "KQogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRf"
    "cGF5bG9hZCA9IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5z"
    "dHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICAgICAiZW5kIjogeyJkYXRlVGltZSI6IGVu"
    "ZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQog"
    "ICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBU"
    "YXJnZXQgY2FsZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAg"
    "IltHQ2FsXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0bGU9J3tl"
    "dmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGltZT0ne2V2ZW50"
    "X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRp"
    "bWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAg"
    "ICAgIGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9Jywg"
    "IgogICAgICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1l"
    "Wm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2Uu"
    "ZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4"
    "ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQu"
    "IikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhj"
    "ZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAg"
    "ICBpZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBl"
    "cnJvcnM9InJlcGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAg"
    "ICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29nbGUg"
    "QVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFp"
    "bF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBib2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYi"
    "W0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBS"
    "dW50aW1lRXJyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4Ogog"
    "ICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRoIHVuZXhwZWN0ZWQg"
    "ZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHNl"
    "bGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5v"
    "dCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29n"
    "bGUgZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBG"
    "YWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9"
    "IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2Vy"
    "dChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUo"
    "KQogICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3By"
    "aW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2Fs"
    "ZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0dXJucyAo"
    "ZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50YWwg"
    "4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6"
    "ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2FuY2Vs"
    "bGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgog"
    "ICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAg"
    "cXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJz"
    "aW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAg"
    "ICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "cXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJz"
    "aW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAg"
    "ICAgICJtYXhSZXN1bHRzIjogMjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAg"
    "ICAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAgIHF1ZXJ5WyJ0aW1lTWluIl0gPSB0"
    "aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSBOb25lCiAgICAg"
    "ICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipx"
    "dWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBb"
    "XSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAg"
    "ICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAgICBpZiBub3Qg"
    "cGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY1Rva2VuIiwg"
    "Tm9uZSkKICAgICAgICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxs"
    "X2V2ZW50cywgbmV4dF9zeW5jX3Rva2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0"
    "cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnki"
    "LCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBh"
    "cyBhcGlfZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4LCAicmVzcCIsIE5vbmUpLCAi"
    "c3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAgICAgICAgICAgICAgcmV0"
    "dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2ds"
    "ZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAg"
    "ICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAg"
    "ICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmRlbGV0"
    "ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoK"
    "CmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0"
    "aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0"
    "aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2Vs"
    "Zi5fZHJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2Vs"
    "Zi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklO"
    "Rk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAgICBzZWxmLl9sb2dnZXIobWVz"
    "c2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxm"
    "LnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRv"
    "a2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRo"
    "ZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikK"
    "ICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5vdCBH"
    "T09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIElt"
    "cG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVw"
    "ZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlh"
    "bHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAg"
    "ICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAg"
    "ICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9r"
    "ZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNy"
    "ZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVf"
    "U0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJl"
    "c2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJl"
    "cXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09P"
    "R0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVk"
    "cyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3Ig"
    "R29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBm"
    "bG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNf"
    "cGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigK"
    "ICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAg"
    "ICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1"
    "cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRo"
    "ZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigi"
    "T0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3Bl"
    "cnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNv"
    "biB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFt"
    "ZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3Jl"
    "ZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMg"
    "bm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2Ry"
    "aXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAg"
    "ICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRz"
    "KQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAg"
    "ICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVs"
    "PSJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVS"
    "Uk9SIikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBz"
    "dHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAg"
    "ICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9p"
    "ZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlz"
    "dCgKICAgICAgICAgICAgcT1mIid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZhbHNlIiwK"
    "ICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEwMCksIDIwMCkpLAogICAgICAg"
    "ICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAg"
    "ICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1l"
    "LHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxh"
    "eU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAgICAgICApLAogICAgICAgICkuZXhl"
    "Y3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0ZW0gaW4g"
    "ZmlsZXM6CiAgICAgICAgICAgIG1pbWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgaXRlbVsiaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVy"
    "IgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xl"
    "LWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMp"
    "fSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAg"
    "ICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAg"
    "ICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVp"
    "cmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nfc2Vydmlj"
    "ZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9jLmdl"
    "dCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250"
    "ZW50IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAg"
    "cGFyYWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAg"
    "ICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVtZW50cyIs"
    "IFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRl"
    "eHRSdW4iKQogICAgICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAg"
    "ICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQog"
    "ICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAg"
    "ICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFy"
    "czoKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICBy"
    "ZXR1cm4gewogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lk"
    "LAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAgICJwcmV2"
    "aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAg"
    "ICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIs"
    "IHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3"
    "IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVu"
    "c3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIp"
    "LnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVh"
    "dGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAg"
    "ICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAg"
    "ICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0i"
    "aWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRl"
    "KCkKICAgICAgICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9maWxlX21l"
    "dGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAgICAgICByZXR1cm4gewogICAgICAgICAgICAiaWQiOiBk"
    "b2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAgICAg"
    "ICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRv"
    "Y3VtZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAg"
    "ICAgICAgIndlYlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJwYXJlbnRzIjog"
    "bWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2Zv"
    "bGRlcihzZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6"
    "CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgog"
    "ICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290"
    "IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2Vydmlj"
    "ZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfbmFt"
    "ZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwK"
    "ICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAg"
    "ICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAg"
    "ICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIGdldF9maWxlX21ldGFkYXRhKHNlbGYs"
    "IGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3Io"
    "IkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJu"
    "IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAg"
    "ICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSIs"
    "CiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAg"
    "ICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxm"
    "LCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9y"
    "KCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYu"
    "X2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAgIGRlZiBkZWxl"
    "dGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZWYg"
    "ZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAg"
    "ICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3Nl"
    "cnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAg"
    "ICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAogICAgICAgICkuZXhl"
    "Y3V0ZSgpCiAgICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXls"
    "b2FkLmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAi"
    "IikKCiAgICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBm"
    "aWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAg"
    "c2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0"
    "X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5lZC4gQWxsIGdl"
    "bmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJlIGlu"
    "IHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBT"
    "ZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMg"
    "ZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNr"
    "YWdlcyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9z"
    "ZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24s"
    "IHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNv"
    "ZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBD"
    "UlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAg"
    "REVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hl"
    "Y2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3Rh"
    "cnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4K"
    "ICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5"
    "LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkK"
    "ICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNpZGU2IiwgICAg"
    "ICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAg"
    "ICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxs"
    "IGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAg"
    "ICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAg"
    "ICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwg"
    "cHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAi"
    "d2luMzJjb20iLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQg"
    "Zm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRp"
    "bCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5"
    "c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIs"
    "ICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2ds"
    "ZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBp"
    "bnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAg"
    "ICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgt"
    "b2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAg"
    "ICAgICAgICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFs"
    "bCB0b3JjaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycyIsICAg"
    "ICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRyYW5z"
    "Zm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAg"
    "ICAgICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZt"
    "bCAgKG9ubHkgbmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9k"
    "CiAgICBkZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUmV0dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdlczogbGlzdCBvZiAi"
    "W0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAgICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBs"
    "aXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAgICAgICAgaW1w"
    "b3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAg"
    "Zm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAg"
    "ICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxz"
    "ZSAib3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJb"
    "REVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1l"
    "KQoKICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tf"
    "b2xsYW1hKGNscykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0"
    "YXR1cyBzdHJpbmcuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVz"
    "dCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVz"
    "dC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAgICAgICAg"
    "ICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1h"
    "IOKclyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilIAg"
    "TUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9y"
    "eU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRsZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVz"
    "IG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwg"
    "dGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVt"
    "b3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUK"
    "ICAgICAgICBtZW1vcmllcy9pbmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAg"
    "TWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlv"
    "biwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250ZXh0IGlu"
    "amVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0g"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29u"
    "bCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0"
    "YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAgPSBiYXNlIC8gImlu"
    "ZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgbG9hZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJl"
    "dHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikpCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZl"
    "X3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAog"
    "ICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgog"
    "ICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBl"
    "cnNvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tfdmVyc2lvbiI6ICAgICAg"
    "ICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAgICAgICAgICAgMCwKICAgICAg"
    "ICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3duIjog"
    "ICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAg"
    "ICAgICAgInRvdGFsX21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAg"
    "ICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2"
    "YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VT"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6"
    "IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0g"
    "IiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlk"
    "LnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAg"
    "ICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUs"
    "CiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250ZW50LAog"
    "ICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxm"
    "Lm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3Nh"
    "Z2VzKHNlbGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChz"
    "ZWxmLm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAog"
    "ICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAg"
    "cmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtl"
    "eXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAg"
    "ICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAg"
    "ICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3Jk"
    "cykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Np"
    "c3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVt"
    "X3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3df"
    "aXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNv"
    "bmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUs"
    "CiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAg"
    "ICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAg"
    "ICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRz"
    "IjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAg"
    "ICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFt"
    "IiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAog"
    "ICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0"
    "dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVy"
    "biBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAt"
    "PiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAg"
    "ICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5n"
    "LgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAg"
    "IiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVl"
    "cnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBz"
    "ZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBm"
    "b3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIg"
    "Ii5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRl"
    "bS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAg"
    "ICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIuam9p"
    "bihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAg"
    "c2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gK"
    "ICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikK"
    "ICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAg"
    "ICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAg"
    "aWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxz"
    "bCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAg"
    "IGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAg"
    "c2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAg"
    "ICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRb"
    "OmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGlu"
    "dCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVs"
    "ZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0"
    "byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2Vh"
    "cmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAg"
    "ICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBb"
    "e20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYi"
    "e20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5"
    "KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkK"
    "ICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNd"
    "IikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNhbmRpZGF0ZTogZGljdCkg"
    "LT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBj"
    "dCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRl"
    "LmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAg"
    "ICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAg"
    "ICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1"
    "ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0"
    "ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAg"
    "ICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVh"
    "bSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVu"
    "ZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYg"
    "ImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9y"
    "ICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5s"
    "b3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jk"
    "c1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cp"
    "CiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtd"
    "CiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAg"
    "ICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0"
    "WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAog"
    "ICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdv"
    "cmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAg"
    "ICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRh"
    "c2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8g"
    "dG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVybiBm"
    "IlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAgICByZXR1cm4gIlJlbWluZGVyIFRh"
    "c2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAgcmV0dXJuIGYieycgJy5qb2lu"
    "KGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5"
    "d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0g"
    "InJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29y"
    "ZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0i"
    "LnN0cmlwKCkgb3IgIklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihj"
    "bGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNh"
    "dGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBz"
    "dHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJf"
    "dGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBp"
    "ZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0i"
    "CiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazoge3V9"
    "IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZTog"
    "e3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29y"
    "ZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVh"
    "IGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlBy"
    "ZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBT"
    "RVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25N"
    "YW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2"
    "ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxl"
    "OiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBz"
    "ZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBs"
    "b2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUvQ2hy"
    "b21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9IDEw"
    "ICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBj"
    "ZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIg"
    "LyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBk"
    "YXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAg"
    "ICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJu"
    "YWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9s"
    "ZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFt"
    "cDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlk"
    "IjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGlt"
    "ZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAg"
    "ICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoK"
    "ICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBo"
    "aXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50Iiwg"
    "ImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjog"
    "bVsicm9sZSJdLCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2Fn"
    "ZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBA"
    "cHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fc2Vzc2lv"
    "bl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJldHVy"
    "biBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9uZToK"
    "ICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25s"
    "LgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBz"
    "aG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0g"
    "ZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0"
    "b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3Bh"
    "dGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9h"
    "ZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vz"
    "c2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2Vu"
    "ZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBp"
    "ZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNl"
    "ciBtZXNzYWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAg"
    "ICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAg"
    "ICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgp"
    "Wzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9k"
    "YXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAg"
    "ICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5h"
    "bWUsCiAgICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZp"
    "cnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxm"
    "Ll9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21l"
    "c3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGlu"
    "ZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0g"
    "ZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50cnkpCgog"
    "ICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0gPSBpbmRl"
    "eFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAgTE9B"
    "RCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAg"
    "ICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVy"
    "biBzZWxmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29u"
    "dGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0"
    "IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4"
    "dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKA"
    "lCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAy"
    "IG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2Rp"
    "ciAvIGYie3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAg"
    "IHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2FkZWRf"
    "am91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Np"
    "b25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNv"
    "bnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBz"
    "ZXNzaW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Np"
    "b24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgi"
    "cm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKVs6MzAw"
    "XQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGlu"
    "ZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpP"
    "VVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5h"
    "bChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBwcm9wZXJ0eQog"
    "ICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5l"
    "d19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVy"
    "bnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9y"
    "IGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25f"
    "ZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9zYXZlX2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFs"
    "c2UKCiAgICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYp"
    "IC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVy"
    "biB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoKICAgIGRl"
    "ZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndy"
    "aXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04Igog"
    "ICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3Nv"
    "bnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywg"
    "cnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRf"
    "YXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNl"
    "X2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5r"
    "LCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFu"
    "Z3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVw"
    "bGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5f"
    "cGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNl"
    "bGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAg"
    "c3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6"
    "IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAg"
    "ICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3Jl"
    "YXRlZF9hdCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVu"
    "dCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXki"
    "OiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJm"
    "dWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAg"
    "ICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9y"
    "IFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAg"
    "ICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBk"
    "ZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAg"
    "ICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2Vs"
    "Zi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciBy"
    "IGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5s"
    "b3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBp"
    "ZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAg"
    "ICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAi"
    "LmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAg"
    "ci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5s"
    "b3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBjb250"
    "aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdl"
    "dF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAg"
    "IGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikg"
    "IT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdy"
    "aXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAg"
    "ICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdl"
    "LgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAg"
    "ICAgICIiIgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBu"
    "b3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBl"
    "cigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFsID0gMAogICAgICAg"
    "IGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5Jywn"
    "Jyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4"
    "X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAg"
    "ICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVy"
    "KCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShz"
    "ZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5n"
    "ZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBm"
    "b3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxm"
    "KSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBvbiBmaXJz"
    "dCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBw"
    "cm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6"
    "CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAg"
    "ICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBp"
    "biBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGluIExTTCBzY3Jp"
    "cHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0"
    "IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAg"
    "ICAgICgiTFNMIiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExT"
    "TCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRl"
    "eCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAog"
    "ICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwg"
    "IiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAg"
    "ICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAg"
    "ICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgog"
    "ICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAg"
    "ICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4i"
    "LAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRy"
    "eSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAg"
    "ICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9p"
    "ZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCBy"
    "ZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3Zv"
    "aWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5v"
    "dCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9T"
    "Q1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBh"
    "cnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdh"
    "eXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwg"
    "c25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxs"
    "IHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNj"
    "cmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVm"
    "LCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxm"
    "LmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAg"
    "ICAgICAgICAgICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFT"
    "SyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFu"
    "YWdlcjoKICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZp"
    "bGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVk"
    "X2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5n"
    "fHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0"
    "cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29v"
    "Z2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAg"
    "ICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAg"
    "ICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5CiAgICAgICAg"
    "LSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRl"
    "IHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0"
    "aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToK"
    "ICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAg"
    "ICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFu"
    "Y2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0Ogog"
    "ICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAg"
    "ICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlm"
    "ICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAg"
    "ICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAg"
    "ICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAg"
    "ICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJs"
    "YXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAg"
    "Tm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAg"
    "IHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgi"
    "Z29vZ2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAg"
    "ICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAg"
    "ICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMg"
    "Q29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90"
    "IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAg"
    "ICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVz"
    "PTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFw"
    "cGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3Jt"
    "YWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0"
    "W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQo"
    "c2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIp"
    "IC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0g"
    "ewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAg"
    "ICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0Ijog"
    "ICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmln"
    "Z2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAg"
    "ICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAg"
    "ICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAs"
    "CiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAg"
    "ICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjog"
    "ICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAi"
    "c3luY19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAg"
    "ICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAg"
    "ICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMo"
    "c2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDog"
    "Ym9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAg"
    "ICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAgICAg"
    "ICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBk"
    "ZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNl"
    "bGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0"
    "YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAg"
    "ICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2"
    "ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNh"
    "bmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2Fk"
    "X2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6"
    "CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0"
    "WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0"
    "YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29t"
    "cGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQg"
    "ICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGlu"
    "IHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQp"
    "CiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiBy"
    "ZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVzOiBz"
    "dHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBz"
    "ZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0g"
    "dGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAg"
    "ICAgICAgdFsibGFzdF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xl"
    "X2V2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xlX2V2ZW50X2lk"
    "CiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFkYXRh"
    "Iiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiXVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9y"
    "WzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQK"
    "ICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVu"
    "dHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFz"
    "a3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90"
    "eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAg"
    "ICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2No"
    "ZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCku"
    "YXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzID0gW10KICAg"
    "ICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2su"
    "Z2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMg"
    "ICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFyc2Vf"
    "bG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRh"
    "c2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2su"
    "Z2V0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5n"
    "ZXQoImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0"
    "dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQgbm90IHRh"
    "c2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdl"
    "ZCA9IFRydWUKCiAgICAgICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5n"
    "IiBhbmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgID0g"
    "InRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2FsX25vd19pc28o"
    "KQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRh"
    "dGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlz"
    "b2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFz"
    "aykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJl"
    "ZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAg"
    "ICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAg"
    "ICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAg"
    "ICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBU"
    "cnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0"
    "dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfcmV0Ogog"
    "ICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAg"
    "ICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkpICsgMQogICAg"
    "ICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAg"
    "ICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5h"
    "c3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNw"
    "ZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAg"
    "ICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1"
    "cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGlt"
    "ZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFy"
    "aXNvbi4iIiIKICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFz"
    "dGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAg"
    "IGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5"
    "IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBz"
    "dHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgICMgU3Ry"
    "aXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICBy"
    "ZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/"
    "XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93"
    "ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3RpbWVy"
    "XGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9c"
    "cyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccyth"
    "KT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRl"
    "clxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJtXGIiLCByIlxiYWxh"
    "cm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xiIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xi"
    "Il0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAg"
    "aW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2Vh"
    "cmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJyZW1pbmRlciIK"
    "ICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAgICAgICAgICAg"
    "aW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJl"
    "dHVybiB7ImludGVudCI6IGludGVudCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QK"
    "ICAgIGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAg"
    "IiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAg"
    "ICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAg"
    "ICAgICAgICAgImluIDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9y"
    "IE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRh"
    "dGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWlu"
    "dXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKiht"
    "aW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAg"
    "IGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAo"
    "MikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQog"
    "ICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEo"
    "aG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1u"
    "KQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgog"
    "ICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAg"
    "ICAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAg"
    "ICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9"
    "IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAg"
    "ICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0gPT0g"
    "ImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0"
    "ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAg"
    "ICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJv"
    "dyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21vcnJvdyIgaW4gbG93Ogog"
    "ICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAg"
    "ICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAg"
    "ICAgICBpZiByZXN1bHQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdy"
    "aXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5l"
    "eHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRl"
    "bmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcuZ2V0KCJiYXNl"
    "X2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMo"
    "KToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERl"
    "cGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29y"
    "ZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZsZWN0aW9uIGN5Y2xlcykK"
    "YXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHlnYW1lCgoj"
    "IERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmlu"
    "ZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29v"
    "Z2xlIGludGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGll"
    "bnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBv"
    "bmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5z"
    "Zm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2"
    "ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rp"
    "bmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQu"
    "CiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0"
    "IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNM"
    "U2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxm"
    "VGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERF"
    "Q0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVkIGhlcmU6CiMgICBTTFNjYW5z"
    "VGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVk"
    "LAojICAgICAgICAgICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAg"
    "IFNMQ29tbWFuZHNUYWIgICDigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JU"
    "cmFja2VyVGFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFi"
    "ICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJl"
    "Z2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQg"
    "KyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsg"
    "am91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsg"
    "Y29kZSBsZXNzb25zIGJyb3dzZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBf"
    "cmUKCgojIOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dvdGhpY190YWJsZV9z"
    "dHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJh"
    "Y2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAg"
    "ICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4"
    "OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tn"
    "cm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9"
    "fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0Nf"
    "QkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAgIGJhY2tncm91"
    "bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZv"
    "bnQtd2VpZ2h0OiBib2xkOwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIK"
    "CmRlZiBfZ290aGljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0"
    "biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsg"
    "bGV0dGVyLXNwYWNpbmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRv"
    "b2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJs"
    "ID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FO"
    "UyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNU"
    "YWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4K"
    "ICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAg"
    "ICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3Jl"
    "YXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMp"
    "CiAgICAgIC0gRGVsZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAn"
    "UmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBi"
    "b2FyZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IFBhdGgsIHBh"
    "cmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0g"
    "Y2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9"
    "IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0"
    "dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQs"
    "IDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAgICJB"
    "ZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXki"
    "LCAiU2hvdyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19i"
    "dG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBf"
    "Z290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9y"
    "ZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNj"
    "YW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNl"
    "bGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRu"
    "X21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlz"
    "cGxheSwgc2VsZi5fYnRuX21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRu"
    "X3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAg"
    "ICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNw"
    "bGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fc3RhY2ssIDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBj"
    "YXJkcykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAwKQogICAgICAg"
    "IGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsID0gUVNjcm9s"
    "bEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNl"
    "bGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikK"
    "ICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAg"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAg"
    "ICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdl"
    "dChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAg"
    "ICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdp"
    "ZGdldCgpCiAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGluZUVkaXQo"
    "KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4g"
    "dGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2Vj"
    "dGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAg"
    "ICAgICAgc2VsZi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5f"
    "YWRkX2Rlc2MpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBhc3Rl"
    "IGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRw"
    "dXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxp"
    "dCBpdGVtcyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkK"
    "ICAgICAgICAjIFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcgPSBRVGFibGVXaWRnZXQo"
    "MCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJD"
    "cmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNp"
    "emVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5f"
    "YWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBR"
    "SGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0TWF4aW11bUhl"
    "aWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxl"
    "KCkpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4"
    "dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikK"
    "ICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChs"
    "YW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBi"
    "dG5zMS5hZGRXaWRnZXQoYzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEpCiAg"
    "ICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDI6IGRpc3BsYXkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3Bf"
    "bmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZvbnQtc2l6ZTog"
    "MTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlz"
    "cF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQog"
    "ICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJd"
    "KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAog"
    "ICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190"
    "YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAg"
    "ICAgIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUu"
    "Y3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0X21l"
    "bnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYu"
    "X2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9o"
    "aW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAg"
    "IGNvcHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KGNvcHlfaGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIikKICAgICAgICBiazIuY2xp"
    "Y2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGwyLmFkZFdp"
    "ZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6"
    "IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0KQogICAgICAgIGwzLmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQog"
    "ICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMu"
    "YWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVN"
    "UyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAs"
    "IDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0"
    "b3IiXSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZp"
    "ZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5z"
    "MyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9nb3RoaWNf"
    "YnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5X3NhdmUpCiAg"
    "ICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAg"
    "ICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAg"
    "ICAgIGwzLmFkZExheW91dChidG5zMykKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDi"
    "lIAgUEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBh"
    "cnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAg"
    "ICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQgaW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJ"
    "WDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGlt"
    "ZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0"
    "OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6CiAgICAgICAgICAgIFsx"
    "MTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAg"
    "ICAgICIiIgogICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwgW10K"
    "CiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0"
    "YW1wcyDilIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06"
    "XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6"
    "ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRh"
    "ciBuYW1lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04iCiAg"
    "ICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVu"
    "dHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihcd1tcd1xz"
    "XSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlw"
    "KCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFjdCBpdGVtcyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAg"
    "Zm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAg"
    "Y29udGVudCA9IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAg"
    "ICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFk"
    "ZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIgaW4gY29udGVudC5sb3dlcigpOgog"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9i"
    "amVjdCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCU"
    "IGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLi"
    "loLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9IGNv"
    "bnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0g"
    "MjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5l"
    "CgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3IgPSAi"
    "VU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9"
    "IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29u"
    "dGVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAg"
    "ICAgY3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25h"
    "bWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAgICAgICAgICAgICMgU3RyaXAgYXR0"
    "YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5z"
    "dWIocidccypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9"
    "IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAgICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkg"
    "PiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVh"
    "dG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA4pSAIENBUkQgUkVOREVSSU5H"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgZGVmIF9idWlsZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3Rpbmcg"
    "Y2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAg"
    "ICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdl"
    "dCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4g"
    "c2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9IHNlbGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNl"
    "bGYuX2NhcmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50"
    "KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+IFFX"
    "aWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRf"
    "aWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhC"
    "b3hMYXlvdXQoY2FyZCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAg"
    "IG5hbWVfbGJsID0gUUxhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMi"
    "LCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsKGYie2NvdW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwo"
    "cmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChuYW1lX2xibCkKICAgICAgICBsYXlv"
    "dXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFNwYWNpbmcoMTIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBz"
    "ZWxlY3QKICAgICAgICByZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJl"
    "c3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0dXJu"
    "IGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRv"
    "IHNob3cgc2VsZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFs"
    "W2RpY3RdOgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAg"
    "ICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAgICAgICBO"
    "b25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3Bh"
    "dGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQog"
    "ICAgICAgIGZvciByIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6"
    "CiAgICAgICAgICAgICAgICByWyJyZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAg"
    "ICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNl"
    "bGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJhdyA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5w"
    "YXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChuYW1lKQog"
    "ICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoyMF06"
    "ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkKICAg"
    "ICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRlZiBfc2hvd19h"
    "ZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX25h"
    "bWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9h"
    "ZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZp"
    "ZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2Rv"
    "X2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAg"
    "ICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9uYW1lID0gc2Vs"
    "Zi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yyku"
    "aXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1"
    "aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgIm5h"
    "bWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9h"
    "ZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAg"
    "ICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csCiAgICAgICAgICAg"
    "ICJ1cGRhdGVkX2F0IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQog"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRf"
    "aWQgPSByZWNvcmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlzcGxh"
    "eShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90"
    "IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAg"
    "ICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxm"
    "Ll9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAg"
    "ICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAg"
    "ICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVO"
    "S05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2NvbnRl"
    "eHRfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBv"
    "cykKICAgICAgICBpZiBub3QgaWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0"
    "ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRh"
    "YmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVt"
    "KGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkK"
    "ICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxm"
    "KQogICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xv"
    "cjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAg"
    "ICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBJdGVtIE5hbWUiKQogICAgICAgIGFf"
    "Y3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRk"
    "QWN0aW9uKCJDb3B5IEJvdGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdw"
    "b3J0KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKQogICAgICAg"
    "IGlmIGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0aW9uID09"
    "IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNl"
    "dFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "c2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2Muc2V0"
    "VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgw"
    "KQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fbW9kX3Rh"
    "YmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQo"
    "Iml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAg"
    "ICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2su"
    "c2V0Q3VycmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04i"
    "CiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRl"
    "bXMgPSBbXQogICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAg"
    "ICAgaXQgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQog"
    "ICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSku"
    "dGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktOT1dOIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICBy"
    "ZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGlt"
    "ZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMp"
    "CiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0"
    "KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAg"
    "ICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUg"
    "dW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRdCiAg"
    "ICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3Nl"
    "bGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoK"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJObyByYXcgdGV4dCBzdG9yZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNbIml0ZW1zIl0gICAg"
    "ICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lCiAgICAgICAgcmVj"
    "WyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVz"
    "c2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgog"
    "ICAgU2Vjb25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29w"
    "eSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAg"
    "ICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "c2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290"
    "LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBi"
    "YXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikK"
    "ICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0"
    "bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3Ro"
    "aWNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJD"
    "b3B5IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaD0gX2dvdGhp"
    "Y19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19h"
    "ZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5f"
    "Y29weS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0"
    "bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9jb3B5LCBzZWxmLl9i"
    "dG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9u"
    "Il0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAg"
    "ICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpv"
    "bnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFB"
    "YnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0"
    "QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9"
    "IFFMYWJlbCgKICAgICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5"
    "IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAg"
    "ICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShy"
    "ZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAg"
    "ICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9j"
    "b21tYW5kKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAg"
    "aWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAw"
    "KQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0u"
    "dGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQog"
    "ICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYi"
    "YmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRs"
    "ZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0uYWRkUm93"
    "KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBi"
    "dG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0"
    "bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVj"
    "dChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAg"
    "Zm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRl"
    "ZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAg"
    "ICAgcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICAgICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVz"
    "Y3JpcHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAg"
    "bm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByZWNbImNvbW1hbmQiXToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25s"
    "KHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAg"
    "ICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNl"
    "dFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAg"
    "IGNtZCAgPSBRTGluZUVkaXQocmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVj"
    "LmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAg"
    "Zm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xp"
    "Y2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5z"
    "LmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAg"
    "aWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJlY1siY29tbWFu"
    "ZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBk"
    "ZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5v"
    "dyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+"
    "PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNb"
    "cm93XS5nZXQoImNvbW1hbmQiLCJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rp"
    "b24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQog"
    "ICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9i"
    "IGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBK"
    "b2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3Vu"
    "aGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVjdGVk"
    "IOKAlCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIs"
    "ICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVz"
    "Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29u"
    "bCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1"
    "cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAgPSBf"
    "Z290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTWFyayBz"
    "ZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0"
    "bigiUmVzdG9yZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZl"
    "ZCBhcHBsaWNhdGlvbnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAg"
    "ICAgICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0"
    "bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNl"
    "bGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBz"
    "ZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0"
    "KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgy"
    "NikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9k"
    "aWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNl"
    "bGYuX2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVs"
    "ZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJh"
    "cikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxm"
    "Ll90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAg"
    "ICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAg"
    "ICAjIERhdGUgQXBwbGllZCDigJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldp"
    "ZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAog"
    "ICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAg"
    "ICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAgICAg"
    "IHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxl"
    "Y3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAg"
    "ICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNo"
    "ZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAg"
    "ICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3Jl"
    "Y29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAg"
    "ICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhy"
    "KQogICAgICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFj"
    "dGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAg"
    "ICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVf"
    "YXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3Rh"
    "dHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBm"
    "b3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAgICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShz"
    "dHIodikpCiAgICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAgICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3Jv"
    "dW5kKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRl"
    "bSkKICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgICAg"
    "ICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0ZW1EYXRhUm9s"
    "ZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5kZXgocmVjKQogICAgICAgICAgICApCgog"
    "ICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkK"
    "ICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVt"
    "ID0gc2VsZi5fdGFibGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAg"
    "ICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICAgICAg"
    "aWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAgICByZXR1"
    "cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9u"
    "YWxbZGljdF06CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpv"
    "YiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xv"
    "cjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91"
    "dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2Ug"
    "IiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVlKQog"
    "ICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAgIGlmIHJlYyBhbmQgcmVjLmdldCgi"
    "ZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBw"
    "bGllZCJdLCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJy"
    "ZW50RGF0ZSgpKQogICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBl"
    "bHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVj"
    "IGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNv"
    "bXBhbnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSksCiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJM"
    "aW5rOiIsIGxpbmspLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAg"
    "ICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBidG5zID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikK"
    "ICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0"
    "KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "YnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAg"
    "ICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAoKSwK"
    "ICAgICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAg"
    "ICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAgICJs"
    "aW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0"
    "YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90"
    "ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRk"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAg"
    "ICAgcC51cGRhdGUoewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAg"
    "ICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6IE5vbmUsCiAg"
    "ICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgICAgbm93LAog"
    "ICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMp"
    "ICE9IDE6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnkuIikKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNlbGYu"
    "X2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUo"
    "cCkKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgp"
    "CiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRf"
    "aW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNv"
    "cmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhd"
    "LmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5p"
    "c29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRh"
    "dGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0"
    "KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Ig"
    "aWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29y"
    "ZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0"
    "ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9q"
    "c29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19k"
    "ZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAg"
    "aWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24o"
    "CiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3Rl"
    "ZCBhcHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBs"
    "eSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IHNldChpZHhzKQogICAg"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hp"
    "ZGRlbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVu"
    "CiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlm"
    "IHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgZmlsdCA9IFFGaWxl"
    "RGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAg"
    "ICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NW"
    "IEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50"
    "eHQiKSBlbHNlICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBwbGllZCIs"
    "ImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3RlcyJd"
    "CiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAg"
    "ICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhlYWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNl"
    "bGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNv"
    "bXBhbnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAg"
    "ICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5r"
    "IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAg"
    "c3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21w"
    "bGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAg"
    "ICAgICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAg"
    "c3RyKHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAgIGZvciB2"
    "IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNl"
    "bGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0iKQoK"
    "CiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3Jk"
    "cyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3Rh"
    "dHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0aDogTXkg"
    "RHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xp"
    "c3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRF"
    "Un07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAgICBkZWYg"
    "c2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2Vs"
    "Zi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRp"
    "dGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIKICAg"
    "ICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgICAgICAgcHJl"
    "Zml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRv"
    "Y3VtZW50IjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVk"
    "VGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0"
    "ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAgICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAg"
    "ICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVt"
    "KGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKGZpbGVzKX0gR29vZ2xl"
    "IERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBH"
    "b29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwK"
    "ICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxl"
    "dGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQs"
    "CiAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgIG9uX2Vk"
    "aXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUs"
    "CiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29w"
    "ZW4gPSBvbl9hZGRfZWRpdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBs"
    "ZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAg"
    "ICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9v"
    "bl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdl"
    "ZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQog"
    "ICAgICAgIHNlbGYuX29uX2VkaXRvcl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19s"
    "b2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAg"
    "ICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZiBfYnVp"
    "bGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYu"
    "d29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29ya3Nw"
    "YWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDAp"
    "CiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxh"
    "YmVsKCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0"
    "ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2Zp"
    "bHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJXRUVL"
    "IiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEgiLCAibW9udGgiKQog"
    "ICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1PTlRIUyIsICJuZXh0XzNfbW9udGhz"
    "IikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2ZpbHRlcl9jb21iby5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJv"
    "LmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9j"
    "aGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAg"
    "ICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmls"
    "dGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAgICAg"
    "c2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2"
    "aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRl"
    "bVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRp"
    "dFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYu"
    "dGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJl"
    "c2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNp"
    "emVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAg"
    "ICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRB"
    "U0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0bigiQ09NUExFVEUgU0VMRUNURUQi"
    "KQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAg"
    "ICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAg"
    "c2VsZi5idG5fcHVyZ2VfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAgc2Vs"
    "Zi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAg"
    "ICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0"
    "ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxl"
    "Y3RlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dn"
    "bGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "b25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkK"
    "ICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAog"
    "ICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRl"
    "X3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVf"
    "Y29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgKToKICAgICAgICAg"
    "ICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAg"
    "ICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdl"
    "dCgpCiAgICAgICAgZWRpdG9yX2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09H"
    "TEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJl"
    "IHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0"
    "b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIKICAgICAg"
    "ICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwpCiAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25h"
    "bWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0"
    "ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3Rh"
    "cnQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0t"
    "REQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlv"
    "bi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "cmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2Fs"
    "bF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVk"
    "aXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAg"
    "ICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4g"
    "KAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3Rh"
    "cnRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Us"
    "CiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRv"
    "cl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290"
    "aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3Nh"
    "dmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAg"
    "ICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0"
    "KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGVkaXRvcl9sYXlv"
    "dXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChl"
    "ZGl0b3IpCgogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dv"
    "cmtzcGFjZSA9IGVkaXRvcgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5u"
    "b3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29t"
    "cGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxl"
    "ZChlbmFibGVkKQoKICAgIGRlZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRz"
    "OiBsaXN0W3N0cl0gPSBbXQogICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpKToK"
    "ICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAgICAgICAgICBpZiBz"
    "dGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90IHN0YXR1"
    "c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBz"
    "dGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQg"
    "dGFza19pZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAgICAgIHJldHVy"
    "biBpZHMKCiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAg"
    "cm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJv"
    "dyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigp"
    "CiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxl"
    "ZCJ9IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgi"
    "VCIsICIgIikKICAgICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCkg"
    "b3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxv"
    "d2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29ufSB7c3Rh"
    "dHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNr"
    "LmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkK"
    "ICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAg"
    "ICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkpCiAg"
    "ICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQogICAg"
    "ICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTog"
    "c3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5f"
    "ZGlhZ19sb2dnZXI6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2Vs"
    "ZiwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYsICJfcmVmcmVz"
    "aF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQgaGFzYXR0cih0aHJlYWQsICJp"
    "c1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAgICAgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNv"
    "bj17cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBh"
    "c3MKICAgICAgICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUK"
    "CiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19w"
    "cm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tz"
    "KHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAg"
    "ICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNlcHRpb24i"
    "KQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RvcF9yZWZyZXNo"
    "X3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoK"
    "ICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9zaG93X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNl"
    "dFRleHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVBMRVRFRCIp"
    "CgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAg"
    "ICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0"
    "YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLmVkaXRv"
    "cl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3Nw"
    "YWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdp"
    "ZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBp"
    "ZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxp"
    "c3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpv"
    "dXJuYWwgbG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gcGVyc29u"
    "YSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5F"
    "UiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYu"
    "X2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhl"
    "ZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAg"
    "ICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9k"
    "aXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAg"
    "ICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNU"
    "SU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0ki"
    "OiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0K"
    "ICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTox"
    "MHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHls"
    "ZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwvc3Bh"
    "bj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGlj"
    "YWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigp"
    "Lm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNw"
    "bGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0"
    "aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hl"
    "Y2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVzLCB0aW1lciBldmVudHMsIGpv"
    "dXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVu"
    "dHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAg"
    "ICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ciKSkKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIu"
    "c2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIp"
    "CiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAg"
    "ICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6ICdDb3Vy"
    "aWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzogOHB4OyIK"
    "ICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYs"
    "IG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRl"
    "dGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAg"
    "IklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAgICAgICJXQVJOIjog"
    "IENfR09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjogQ19URVhUX0RJ"
    "TSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVS"
    "KQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19U"
    "RVhUX0RJTX07Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntj"
    "b2xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Ny"
    "b2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhp"
    "bXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1lc3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBz"
    "dHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0g"
    "bGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKc"
    "lyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZs"
    "ID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRBQiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAg"
    "ICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmll"
    "dywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3Nv"
    "bnNMZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fZGIgPSBkYgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBy"
    "b290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJj"
    "aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3Nv"
    "bnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl9sYW5nX2Zp"
    "bHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENo"
    "YW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNo"
    "OiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJfcm93"
    "LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xh"
    "bmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRu"
    "X2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIGJ0"
    "bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBi"
    "dG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3Rh"
    "YmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJvbm1lbnQi"
    "XQogICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoCiAgICAgICAgICAgIDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZp"
    "b3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxp"
    "dHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRh"
    "dGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0"
    "YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQgPSBR"
    "VkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVM"
    "TCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9y"
    "dWxlID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1"
    "MCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0bl9l"
    "ZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3Nh"
    "dmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lk"
    "dGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0"
    "bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFk"
    "ZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2Vs"
    "Zi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVyKQoKICAg"
    "ICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVl"
    "KQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAg"
    "ICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRl"
    "dGFpbF93aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAg"
    "ID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgp"
    "CiAgICAgICAgbGFuZyA9ICIiIGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9"
    "IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0Nv"
    "dW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUu"
    "cm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIs"
    "IiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lk"
    "Z2V0SXRlbShyZWMuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVt"
    "KHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAg"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVj"
    "LmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICBy"
    "b3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAg"
    "IGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jv"
    "d10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1"
    "bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJl"
    "c29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1"
    "bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5f"
    "YnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0"
    "KCJDYW5jZWwiIGlmIGVkaXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2Vs"
    "Zi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9y"
    "OiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAg"
    "ICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRk"
    "aW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250ZW50IG9uIGNhbmNlbAogICAgICAgICAgICBz"
    "ZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cg"
    "PSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICB0ZXh0ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJl"
    "c29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4"
    "dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAgICAgICAg"
    "ICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBh"
    "cnRzWzFdLnN0cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAg"
    "ICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQog"
    "ICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwo"
    "c2VsZi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hl"
    "Y2tlZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBMZXNzb24i"
    "KQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIp"
    "CiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAg"
    "IGVudiAgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYg"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0KCkK"
    "ICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQoKQogICAgICAg"
    "IGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1l"
    "bnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiks"
    "ICgiU3VtbWFyeToiLCBzdW1tKSwKICAgICAgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoi"
    "LCByZXMpLAogICAgICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRS"
    "b3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJT"
    "YXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2Nl"
    "cHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMu"
    "YWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlh"
    "bG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAgIGVu"
    "dmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0"
    "cmlwKCksCiAgICAgICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAg"
    "ICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxh"
    "aW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAogICAg"
    "ICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJs"
    "ZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAg"
    "cmVjX2lkID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdl"
    "Qm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAgICAgICAgICAgICAg"
    "IkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kYi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RV"
    "TEUgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIo"
    "UVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxh"
    "bm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUg"
    "aGFzOiBOYW1lLCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3Rpbmcg"
    "aW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5k"
    "IGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIHRvIGRlY2tfYnVp"
    "bGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIs"
    "ICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50"
    "PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2Rp"
    "Y3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nl"
    "dHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBC"
    "dXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0g"
    "X2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRp"
    "dCIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0"
    "bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3Ro"
    "aWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9lZGl0"
    "LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBzZWxmLl9idG5faW1w"
    "b3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdo"
    "dCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZWRpdCkK"
    "ICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBv"
    "cnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3Rh"
    "YmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUu"
    "aG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVz"
    "aXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGgu"
    "c2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAog"
    "ICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVT"
    "aGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9IFFTcGxp"
    "dHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUp"
    "CgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rl"
    "c19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNf"
    "bGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3Bs"
    "YXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAg"
    "ICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3Bs"
    "YXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkK"
    "ICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkpCiAgICAgICAgc3BsaXR0ZXIu"
    "YWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBdKQogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291"
    "bnRfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZy"
    "ZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAg"
    "ICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93"
    "KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJu"
    "YW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1"
    "cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMg"
    "PSB7CiAgICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICAgICAi"
    "RGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG8gQnVpbGQiOiAgIENf"
    "UFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIsCiAgICAgICAgICAgICAg"
    "ICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0u"
    "c2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0"
    "dXMiLCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAg"
    "ICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilbOjgwXSkpCiAgICAgICAgY291"
    "bnRzID0ge30KICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJz"
    "dGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAg"
    "Y291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQogICAgICAg"
    "IHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAg"
    "IHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "dyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMp"
    "OgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxh"
    "eS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9y"
    "ZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykK"
    "CiAgICBkZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4g"
    "Tm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2R1bGUi"
    "IGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVT"
    "aGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQw"
    "LCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRp"
    "dChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRl"
    "clRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzdGF0"
    "dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6CiAgICAgICAgICAgIGlkeCA9IHN0"
    "YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAw"
    "OgogICAgICAgICAgICAgICAgc3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmll"
    "bGQgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNj"
    "X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVs"
    "ZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikg"
    "aWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAi"
    "RnVsbCBub3RlcyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAg"
    "ICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGlu"
    "IFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNf"
    "Y29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5vdGVz"
    "OiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQog"
    "ICAgICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkwKQogICAg"
    "ICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KHdp"
    "ZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwg"
    "PSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkK"
    "ICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lk"
    "Z2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZm9ybS5hZGRM"
    "YXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6"
    "CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIs"
    "IHN0cih1dWlkLnV1aWQ0KCkpKSBpZiByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJu"
    "YW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAg"
    "ICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2NfZmll"
    "bGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBub3Rlc19maWVsZC50b1BsYWlu"
    "VGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0"
    "ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAg"
    "ICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0K"
    "ICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVj"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAg"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3Vy"
    "cmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5hbWUg"
    "PSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFN"
    "ZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAg"
    "ICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2Vs"
    "Zi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAg"
    "ICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0"
    "cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBl"
    "eHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAgICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAg"
    "ICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7"
    "ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90"
    "YWwgbW9kdWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAg"
    "ICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAg"
    "ICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAgIGYiTU9EVUxFOiB7cmVjLmdldCgnbmFt"
    "ZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAg"
    "ICAgICAgICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0"
    "MCwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRoLndy"
    "aXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9u"
    "LmNsaXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3Jt"
    "YXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJh"
    "Y2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xpcGJvYXJkLiIKICAgICAgICAg"
    "ICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhz"
    "ZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUpKQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4iIiIKICAgICAgICBk"
    "bGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJJbXBvcnQgTW9kdWxlIFNwZWMiKQog"
    "ICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAg"
    "ICAgICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93LlxuIgog"
    "ICAgICAgICAgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAgICApKQog"
    "ICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEp"
    "CiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIklt"
    "cG9ydCIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlj"
    "a2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0"
    "KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2Fu"
    "Y2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlh"
    "bG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgbGlu"
    "ZXMgPSByYXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVtcHR5IGxpbmUgPSBuYW1lCiAgICAg"
    "ICAgICAgIG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgICAgIGlmIGxp"
    "bmUuc3RyaXAoKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAg"
    "ICAgInN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAg"
    "ICAgICAgICAibm90ZXMiOiAgICAgICByYXcsCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5u"
    "b3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zv"
    "cm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIEFsbCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVs"
    "ZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2FyZC9n"
    "cmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhp"
    "YyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJhY2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBt"
    "dWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1"
    "bSBmb3IgaWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1"
    "cmVkIGxvZyB3aXRoIGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4gUnVsZXNl"
    "dCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2luZG93CiMg"
    "KE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVw"
    "ZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZ"
    "IFBPSU5UCiMKIyBDb250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0"
    "aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRo"
    "ICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJs"
    "ZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg"
    "4oCUIEFXQUtFIC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCU"
    "IG1haW4gd2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgICAgICAg"
    "ICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNU"
    "UkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9v"
    "dHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0"
    "ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAg"
    "ICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxp"
    "ZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBE"
    "aWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2"
    "IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAg"
    "IGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBhdmFp"
    "bGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAg"
    "ICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5c"
    "blxuIgogICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAi"
    "ICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RFQ0tfTkFN"
    "RX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAgICAg"
    "ICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwg"
    "UHlTaWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhl"
    "ciBtaXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0gWwogICAg"
    "ICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1Iiwg"
    "ICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAi"
    "cHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAo"
    "InBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAg"
    "ICAgICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFw"
    "aWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxp"
    "YiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAg"
    "IGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25h"
    "bWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxl"
    "KGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFt"
    "ZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4i"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vzcy5y"
    "dW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAg"
    "ICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAog"
    "ICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAg"
    "ICAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAg"
    "ICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JP"
    "T1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9n"
    "LmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxs"
    "IGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1wb3J0IHN0aWxs"
    "IGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBi"
    "b290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9"
    "IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19Igog"
    "ICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAg"
    "ICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "ICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoK"
    "ICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5"
    "OgogICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAg"
    "ICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRl"
    "KCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA"
    "4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0"
    "UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNv"
    "biBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBwYXRoL2tleS4KICAg"
    "IFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3Vj"
    "Y2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dU"
    "aXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0"
    "U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9z"
    "ZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RF"
    "Q0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzog"
    "MnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50"
    "ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAg"
    "ZiJDb25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAgICAgICAgICAg"
    "IkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAg"
    "ICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZv"
    "bnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAg"
    "ICAgICkKICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9"
    "IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBt"
    "b2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAg"
    "ICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAg"
    "IF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlw"
    "ZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAg"
    "RHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBz"
    "ZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBw"
    "MCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJn"
    "aW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9j"
    "YWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4tOGIiCiAg"
    "ICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3Nl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2Fs"
    "X3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgog"
    "ICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEg"
    "PSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxm"
    "Ll9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRl"
    "clRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAg"
    "ICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRz"
    "TWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9r"
    "ZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2Rl"
    "bCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBL"
    "ZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFM"
    "YWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxm"
    "Ll9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQo"
    "KQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDAp"
    "CiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNl"
    "aG9sZGVyVGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hv"
    "TW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAg"
    "bDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkK"
    "ICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2Fp"
    "X21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAg"
    "ICBzZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYu"
    "X3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2Vs"
    "Zi5fYnRuX3Rlc3QpCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAg"
    "cm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmls"
    "ZSkiKSkKICAgICAgICBmYWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYiQnJv"
    "d3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRF"
    "Un07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAgICBidG5fZmFjZSA9"
    "IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2Vf"
    "ZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFk"
    "ZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAg"
    "U2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRl"
    "IGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iu"
    "c2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAj"
    "IOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAg"
    "YnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBC"
    "RUdJTiBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBi"
    "dG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0"
    "KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRn"
    "ZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFu"
    "Z2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkK"
    "ICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5z"
    "ZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxl"
    "RGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIs"
    "CiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBz"
    "ZWxmLl9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVj"
    "dCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAg"
    "ICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9m"
    "YWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4g"
    "c3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29u"
    "bmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4uLiIp"
    "CiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhU"
    "X0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQog"
    "ICAgICAgIFFBcHBsaWNhdGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5j"
    "dXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09"
    "IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAg"
    "ICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAg"
    "ICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAg"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRo"
    "LiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3N0"
    "OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1"
    "ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAw"
    "CiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5v"
    "dCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNn"
    "ID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAg"
    "ICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29s"
    "KGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQg"
    "bG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAgICAgICBl"
    "bGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBt"
    "c2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJ"
    "IEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxm"
    "Ll9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBi"
    "dWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmln"
    "IGRpY3QgZnJvbSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkK"
    "ICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBb"
    "ImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9"
    "IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0g"
    "c2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNm"
    "Z1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRv"
    "bHBoaW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tl"
    "eSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBp"
    "X21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJd"
    "WyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1v"
    "ZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAg"
    "ICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgog"
    "ICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJB"
    "UiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdl"
    "dCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFi"
    "LgogICAgVG9wOiBzZXNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMs"
    "CiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlzdCDigJQg"
    "ZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRoaW4gc3RyaXAu"
    "CgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcg"
    "b2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0"
    "byBjdXJyZW50IHNlc3Npb24KICAgICIiIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikK"
    "ICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lv"
    "bl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAg"
    "PSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1"
    "cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29udGVu"
    "dCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikKICAg"
    "ICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoK"
    "ICAgICAgICAjIOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0"
    "cmlwKQogICAgICAgIHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZWxmLl90"
    "b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4LCAx"
    "OCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9E"
    "SU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICAgIyDi"
    "lIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxm"
    "Ll9jb250ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgo"
    "MjIwKQogICAgICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250"
    "ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRT"
    "cGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBz"
    "ZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAg"
    "Y3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+SviIp"
    "CiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5z"
    "ZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLw"
    "n5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9s"
    "b2FkLnNldFRvb2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3Nh"
    "dmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBz"
    "ZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Nh"
    "dmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdp"
    "ZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAgY29udGVu"
    "dF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAg"
    "ICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVu"
    "IG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVy"
    "biB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQog"
    "ICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBE"
    "aXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUu"
    "SExpbmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAgICBjb250ZW50"
    "X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nl"
    "c3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3RlZCB7"
    "eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nl"
    "c3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVu"
    "dF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQg"
    "dG9nZ2xlIHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dn"
    "bGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAg"
    "IHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNl"
    "dFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5"
    "KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAg"
    "ICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2Vzc2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuY2xlYXIoKQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJk"
    "YXRlIiwiIikKICAgICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAg"
    "ICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRn"
    "ZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRv"
    "dWJsZS1jbGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCBuYW1lOiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJOZXcgU2Vzc2lvbiIpCgog"
    "ICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVk"
    "IGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRvc2F2ZWQi"
    "IGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2Fk"
    "ZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi"
    "8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxl"
    "KFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "am91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZh"
    "bHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUo"
    "KQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAg"
    "ICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwLCBs"
    "YW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAw"
    "LCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNz"
    "aW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcg"
    "c2VsZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3QuY291bnQo"
    "KSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAg"
    "ICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5z"
    "ZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYs"
    "IGl0ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xl"
    "KQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfZG9fY2xl"
    "YXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgp"
    "CiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigpCgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0"
    "KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkQK"
    "CiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVz"
    "c3VyZQogICAgQVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9y"
    "IGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRpbCBt"
    "YW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0Ui"
    "IHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBT"
    "VEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJB"
    "V0FLRSI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09M"
    "RH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVyLXJh"
    "ZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6"
    "ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAg"
    "ICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlz"
    "YWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tn"
    "cm91bmQ6ICMxYTEwMDU7IGNvbG9yOiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFj"
    "dGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAg"
    "ICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhw"
    "eDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9k"
    "ZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BF"
    "TkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7"
    "Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsg"
    "Ym9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBm"
    "ImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAi"
    "bGFiZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQRU5TSU9OX0xB"
    "QkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2Fk"
    "ZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9Cgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVz"
    "aEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBz"
    "dGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNb"
    "c3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1b"
    "InRvb2x0aXAiXSkKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tl"
    "ZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNl"
    "bGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBz"
    "ZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3Vy"
    "cmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQu"
    "ZW1pdChzdGF0ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwg"
    "YnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3Rh"
    "dGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2Vs"
    "Zi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0"
    "ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYs"
    "IHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJv"
    "bSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAg"
    "ICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIi"
    "IgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMg"
    "YWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9s"
    "ZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlzIOKG"
    "kiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwg"
    "VlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAg"
    "ICMgNiDDlyA1cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAx"
    "MiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAg"
    "ICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAgICAgICBzZWxm"
    "Ll9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1"
    "ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQg"
    "ICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAg"
    "ICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUg"
    "cnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJl"
    "bCBiZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAg"
    "ICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2Ug"
    "ID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJl"
    "X3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVm"
    "X3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJh"
    "bnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3"
    "aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVk"
    "IGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBz"
    "ZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFn"
    "ZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3Mg"
    "ICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2Zv"
    "bGRlcl9pZCA9ICJyb290IgogICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVf"
    "cmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNf"
    "dGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tf"
    "c2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRo"
    "cyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFwcGVy"
    "cyB1cC1mcm9udDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdpbmRvdy5z"
    "aG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZH"
    "LmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNm"
    "Z19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rv"
    "a2VuX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIsCiAgICAg"
    "ICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAgICAgKSkKICAgICAgICBzZWxm"
    "Ll9nY2FsID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRoKQogICAgICAgIHNl"
    "bGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNlcnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwKICAgICAg"
    "ICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAgIyBTZWVkIExT"
    "TCBydWxlcyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRfbHNsX3J1bGVzKCkKCiAgICAgICAg"
    "IyBMb2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRfc3RhdGUoKQog"
    "ICAgICAgIHNlbGYuX3N0YXRlWyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Npb25fY291bnQi"
    "LDApICsgMQogICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAg"
    "ICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAg"
    "ICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIg"
    "bWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9w"
    "dGlvbmFsW0ZhY2VUaW1lck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBVSSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11bVNp"
    "emUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAsIDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hl"
    "ZXQoU1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2ly"
    "ZWQgdG8gd2lkZ2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigKICAgICAg"
    "ICAgICAgc2VsZi5fbWlycm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBU"
    "aW1lcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAg"
    "ICAgIHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2Vs"
    "Zi5fc3RhdHNfdGltZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIgPSBRVGltZXIoKQogICAg"
    "ICAgIHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykKICAgICAgICBzZWxmLl9ibGlu"
    "a190aW1lci5zdGFydCg4MDApCgogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRpbWVyKCkKICAgICAg"
    "ICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQgc2VsZi5fdmFtcF9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "c2VsZi5fc3RhdGVfc3RyaXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3ZhbXBfc3RyaXAucmVmcmVzaCkKICAg"
    "ICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9p"
    "bmJvdW5kX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIudGltZW91"
    "dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX2lu"
    "Ym91bmRfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIg"
    "PSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnRpbWVvdXQuY29u"
    "bmVjdChzZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBz"
    "dGFydHVwIGRlZmVycmVkIHVudGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1Qg"
    "Y2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMgQm90aCBh"
    "cmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRlcgogICAgICAgICMgd2luZG93"
    "LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJT04g"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYs"
    "IDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDilIDilIAg"
    "Qm9keTogSm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGJvZHkgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgYm9keS5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgSm91cm5hbCBzaWRlYmFyIChsZWZ0"
    "KQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAg"
    "ICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAg"
    "IHNlbGYuX2xvYWRfam91cm5hbF9zZXNzaW9uKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2Ns"
    "ZWFyX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAg"
    "ICAgYm9keS5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFyKQoKICAgICAgICAjIENoYXQgcGFuZWwgKGNlbnRl"
    "ciwgZXhwYW5kcykKICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAg"
    "ICAgICMgU3lzdGVtcyAocmlnaHQpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3Bh"
    "bmVsKCkpCgogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJvZHksIDEpCgogICAgICAgICMg4pSA4pSAIEZvb3RlciDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYi4pymIHtBUFBfTkFN"
    "RX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7"
    "ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAg"
    "Zm9vdGVyLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KGZvb3RlcikKCiAgICBkZWYgX2J1aWxkX3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIGJhciA9"
    "IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRGaXhlZEhlaWdodCgzNikKICAgICAgICBiYXIuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJv"
    "eExheW91dChiYXIpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxMCwgMCwgMTAsIDApCiAgICAgICAg"
    "bGF5b3V0LnNldFNwYWNpbmcoNikKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0FQUF9OQU1FfSIpCiAgICAg"
    "ICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTog"
    "MTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBib3JkZXI6"
    "IG5vbmU7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgcnVuZXMgPSBR"
    "TGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RF9ESU19OyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHJ1bmVzLnNldEFs"
    "aWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFM"
    "YWJlbChmIuKXiSB7VUlfT0ZGTElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldEFsaWdubWVudChR"
    "dC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAgICMgU3VzcGVuc2lvbiBwYW5lbAogICAgICAgIHNlbGYu"
    "X3RvcnBvcl9wYW5lbCA9IE5vbmUKICAgICAgICBpZiBTVVNQRU5TSU9OX0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYu"
    "X3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsLnN0YXRlX2No"
    "YW5nZWQuY29ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKCiAgICAgICAgIyBJZGxlIHRvZ2dsZQog"
    "ICAgICAgIHNlbGYuX2lkbGVfYnRuID0gUVB1c2hCdXR0b24oIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0"
    "bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAg"
    "ICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAg"
    "ICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2lkbGVfYnRuLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9vbl9pZGxlX3RvZ2dsZWQpCgogICAgICAg"
    "ICMgRlMgLyBCTCBidXR0b25zCiAgICAgICAgc2VsZi5fZnNfYnRuID0gUVB1c2hCdXR0b24oIkZTIikKICAgICAgICBz"
    "ZWxmLl9ibF9idG4gPSBRUHVzaEJ1dHRvbigiQkwiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiRXhwb3J0IikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAg"
    "ICAgIGZvciBidG4gaW4gKHNlbGYuX2ZzX2J0biwgc2VsZi5fYmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAg"
    "ICAgICAgYnRuLnNldEZpeGVkU2l6ZSgzMCwgMjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAg"
    "ICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "ZXhwb3J0X2J0bi5zZXRGaXhlZFdpZHRoKDQ2KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZEhlaWdo"
    "dCgyMikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRXaWR0aCg2OCkKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0Nf"
    "QkxPT0R9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQkxPT0R9OyBmb250LXNpemU6IDlweDsg"
    "IgogICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fZnNfYnRuLnNldFRvb2xUaXAoIkZ1bGxzY3JlZW4gKEYxMSkiKQogICAgICAgIHNlbGYuX2JsX2J0bi5zZXRUb29s"
    "VGlwKCJCb3JkZXJsZXNzIChGMTApIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldFRvb2xUaXAoIkV4cG9ydCBj"
    "aGF0IHNlc3Npb24gdG8gVFhUIGZpbGUiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRUb29sVGlwKGYiR3Jh"
    "Y2VmdWwgc2h1dGRvd24g4oCUIHtERUNLX05BTUV9IHNwZWFrcyB0aGVpciBsYXN0IHdvcmRzIikKICAgICAgICBzZWxm"
    "Ll9mc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKQogICAgICAgIHNlbGYuX2JsX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZXhwb3J0X2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGl0"
    "bGUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChydW5lcywgMSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "c3RhdHVzX2xhYmVsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDgpCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3Bh"
    "bmVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3RvcnBvcl9wYW5lbCkKICAg"
    "ICAgICBsYXlvdXQuYWRkU3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5faWRsZV9idG4pCiAg"
    "ICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2V4cG9ydF9idG4p"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zaHV0ZG93bl9idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9mc19idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ibF9idG4pCgogICAgICAgIHJldHVy"
    "biBiYXIKCiAgICBkZWYgX2J1aWxkX2NoYXRfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgTWFpbiB0YWIgd2lk"
    "Z2V0IOKAlCBwZXJzb25hIGNoYXQgdGFiIHwgU2VsZgogICAgICAgIHNlbGYuX21haW5fdGFicyA9IFFUYWJXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFUYWJXaWRnZXQ6OnBh"
    "bmUge3sgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfTU9OSVRPUn07IH19IgogICAgICAgICAgICBmIlFUYWJCYXI6OnRhYiB7eyBiYWNrZ3JvdW5kOiB7Q19CRzN9OyBj"
    "b2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNHB4IDEycHg7IGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250"
    "LXNpemU6IDEwcHg7IH19IgogICAgICAgICAgICBmIlFUYWJCYXI6OnRhYjpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXItYm90dG9tOiAycHggc29saWQge0Nf"
    "Q1JJTVNPTn07IH19IgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGFiIDA6IFBlcnNvbmEgY2hhdCB0YWIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VhbmNlX3dpZGdldCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlYW5jZV9sYXlvdXQgPSBRVkJveExheW91dChzZWFuY2Vfd2lkZ2V0KQogICAgICAgIHNlYW5jZV9sYXlv"
    "dXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRTcGFjaW5nKDAp"
    "CiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "c2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAx"
    "MnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWFuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9j"
    "aGF0X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWFuY2Vfd2lkZ2V0LCBmIuKdpyB7VUlf"
    "Q0hBVF9XSU5ET1d9IikKCiAgICAgICAgIyDilIDilIAgVGFiIDE6IFNlbGYg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2Vs"
    "Zl90YWJfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZl9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9zZWxm"
    "X3RhYl93aWRnZXQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgc2VsZl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheSA9IFFUZXh0RWRpdCgp"
    "CiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNw"
    "bGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NlbGZfZGlzcGxheSwgMSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRk"
    "VGFiKHNlbGYuX3NlbGZfdGFiX3dpZGdldCwgIuKXiSBTRUxGIikKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9tYWluX3RhYnMsIDEpCgogICAgICAgICMg4pSA4pSAIEJvdHRvbSBzdGF0dXMvcmVzb3VyY2UgYmxvY2sgcm93IOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgICMgTWFuZGF0b3J5IHBlcm1hbmVudCBzdHJ1Y3R1cmUgYWNyb3NzIGFsbCBwZXJzb25h"
    "czoKICAgICAgICAjIE1JUlJPUiB8IEVNT1RJT05TIHwgTEVGVCBPUkIgfCBDRU5URVIgQ1lDTEUgfCBSSUdIVCBPUkIg"
    "fCBFU1NFTkNFCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJsb2NrX3Jvdy5zZXRTcGFj"
    "aW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZlciBjb2xsYXBzZXMpCiAgICAgICAgbWlycm9yX3dyYXAgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVkJveExheW91dChtaXJyb3Jfd3JhcCkKICAgICAgICBtd19sYXlvdXQu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAg"
    "ICBtd19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyB7VUlfTUlSUk9SX0xBQkVMfSIpKQogICAgICAg"
    "IHNlbGYuX21pcnJvciA9IE1pcnJvcldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgxNjAs"
    "IDE2MCkKICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAgICBibG9ja19yb3cuYWRk"
    "V2lkZ2V0KG1pcnJvcl93cmFwKQoKICAgICAgICAjIEVtb3Rpb24gYmxvY2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNl"
    "bGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90aW9uQmxvY2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9"
    "IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9FTU9USU9OU19MQUJFTH0iLCBzZWxmLl9lbW90"
    "aW9uX2Jsb2NrLAogICAgICAgICAgICBleHBhbmRlZD1UcnVlLCBtaW5fd2lkdGg9MTMwCiAgICAgICAgKQogICAgICAg"
    "IGJsb2NrX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwKQoKICAgICAgICAjIExlZnQgcmVzb3Vy"
    "Y2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9ibG9vZF9zcGhlcmUgPSBTcGhlcmVXaWRnZXQoCiAgICAg"
    "ICAgICAgIFVJX0xFRlRfT1JCX0xBQkVMLCBDX0NSSU1TT04sIENfQ1JJTVNPTl9ESU0KICAgICAgICApCiAgICAgICAg"
    "YmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgQ29sbGFwc2libGVCbG9jayhmIuKdpyB7VUlfTEVGVF9PUkJf"
    "VElUTEV9Iiwgc2VsZi5fYmxvb2Rfc3BoZXJlLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1pbl93aWR0aD05"
    "MCkKICAgICAgICApCgogICAgICAgICMgQ2VudGVyIGN5Y2xlIHdpZGdldCAoY29sbGFwc2libGUpCiAgICAgICAgc2Vs"
    "Zi5fbW9vbl93aWRnZXQgPSBNb29uV2lkZ2V0KCkKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KAogICAgICAgICAg"
    "ICBDb2xsYXBzaWJsZUJsb2NrKGYi4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9tb29uX3dpZGdldCwgbWluX3dp"
    "ZHRoPTkwKQogICAgICAgICkKCiAgICAgICAgIyBSaWdodCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAgICAg"
    "IHNlbGYuX21hbmFfc3BoZXJlID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENf"
    "UFVSUExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAg"
    "ICAgQ29sbGFwc2libGVCbG9jayhmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX21hbmFfc3BoZXJlLCBt"
    "aW5fd2lkdGg9OTApCiAgICAgICAgKQoKICAgICAgICAjIEVzc2VuY2UgKDIgZ2F1Z2VzLCBjb2xsYXBzaWJsZSkKICAg"
    "ICAgICBlc3NlbmNlX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGVzc2VuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "ZXNzZW5jZV93aWRnZXQpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgZXNzZW5jZV9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2h1bmdlcl9nYXVnZSAgID0g"
    "R2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9QUklNQVJZLCAgICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxm"
    "Ll92aXRhbGl0eV9nYXVnZSA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0VfU0VDT05EQVJZLCAiJSIsIDEwMC4wLCBDX0dS"
    "RUVOKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9odW5nZXJfZ2F1Z2UpCiAgICAgICAgZXNz"
    "ZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3ZpdGFsaXR5X2dhdWdlKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRn"
    "ZXQoCiAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93"
    "aWRnZXQsIG1pbl93aWR0aD0xMTApCiAgICAgICAgKQoKICAgICAgICBibG9ja19yb3cuYWRkU3RyZXRjaCgpCiAgICAg"
    "ICAgbGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMgRm9vdGVyIHN0YXRlIHN0cmlwIChiZWxvdyBi"
    "bG9jayByb3cg4oCUIHBlcm1hbmVudCBVSSBzdHJ1Y3R1cmUpCiAgICAgICAgc2VsZi5fdmFtcF9zdHJpcCA9IFZhbXBp"
    "cmVTdGF0ZVN0cmlwKCkKICAgICAgICBzZWxmLl92YW1wX3N0cmlwLnNldF9sYWJlbChVSV9GT09URVJfU1RSSVBfTEFC"
    "RUwpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl92YW1wX3N0cmlwKQoKICAgICAgICAjIOKUgOKUgCBJbnB1"
    "dCByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9z"
    "eW0gPSBRTGFiZWwoIuKcpiIpCiAgICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNv"
    "bG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIK"
    "ICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZFdpZHRoKDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9m"
    "aWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lO"
    "UFVUX1BMQUNFSE9MREVSKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnJldHVyblByZXNzZWQuY29ubmVjdChzZWxm"
    "Ll9zZW5kX21lc3NhZ2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAg"
    "c2VsZi5fc2VuZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5z"
    "ZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9t"
    "ZXNzYWdlKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5h"
    "ZGRXaWRnZXQocHJvbXB0X3N5bSkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQog"
    "ICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChp"
    "bnB1dF9yb3cpCgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2J1aWxkX3NwZWxsYm9va19wYW5lbChzZWxm"
    "KSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAg"
    "IHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldE1pbmltdW1X"
    "aWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBv"
    "bGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAg"
    "ICAgKQoKICAgICAgICAjIEJ1aWxkIERpYWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBl"
    "dmVuIGJlZm9yZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0byB0aGUgd2lkZ2V0Lgog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKUgOKUgCBJbnN0cnVtZW50"
    "cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5faHdfcGFuZWwgPSBIYXJkd2FyZVBhbmVsKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFk"
    "ZFRhYihzZWxmLl9od19wYW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDilIAgUmVjb3JkcyB0YWIgKHJl"
    "YWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X3JlY29yZHNfdGFiID0gUmVjb3Jkc1RhYigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSBzZWxmLl9z"
    "cGVsbF90YWJzLmFkZFRhYihzZWxmLl9yZWNvcmRzX3RhYiwgIlJlY29yZHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDi"
    "lIAgVGFza3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl90YXNrc190YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3NfcHJvdmlk"
    "ZXI9c2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW49"
    "c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIG9uX2NvbXBsZXRlX3NlbGVjdGVkPXNl"
    "bGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5j"
    "ZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25fdG9nZ2xlX2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19j"
    "b21wbGV0ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0ZWRf"
    "dGFza3MsCiAgICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQsCiAg"
    "ICAgICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0LAogICAgICAg"
    "ICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAg"
    "IGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2csCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rhc2tz"
    "X3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl90YXNr"
    "c190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190YWIsICJUYXNrcyIpCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikK"
    "CiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1Rh"
    "YihjZmdfcGF0aCgic2wiKSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zbF9zY2FucywgIlNM"
    "IFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xD"
    "b21tYW5kc1RhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29tbWFuZHMsICJTTCBD"
    "b21tYW5kcyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpv"
    "YlRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAiSm9i"
    "IFRyYWNrZXIiKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25z"
    "X3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxm"
    "Ll9sZXNzb25zX3RhYiwgIkxlc3NvbnMiKQoKICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVh"
    "IGFsb25nc2lkZSB0aGUgcGVyc29uYSBjaGF0IHRhYgogICAgICAgICMgS2VlcCBhIFNlbGZUYWIgaW5zdGFuY2UgZm9y"
    "IGlkbGUgY29udGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBTZWxmVGFiKCkKCiAgICAgICAg"
    "IyDilIDilIAgTW9kdWxlIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tlclRhYigpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJNb2R1bGVzIikKCiAgICAgICAg"
    "IyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAi"
    "RGlhZ25vc3RpY3MiKQoKICAgICAgICByaWdodF93b3Jrc3BhY2UgPSBRV2lkZ2V0KCkKICAgICAgICByaWdodF93b3Jr"
    "c3BhY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5z"
    "ZXRTcGFjaW5nKDQpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NwZWxsX3Rh"
    "YnMsIDEpCgogICAgICAgIGNhbGVuZGFyX2xhYmVsID0gUUxhYmVsKCLinacgQ0FMRU5EQVIiKQogICAgICAgIGNhbGVu"
    "ZGFyX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEw"
    "cHg7IGxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChjYWxlbmRhcl9sYWJlbCkKCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhcl93aWRnZXQgPSBNaW5pQ2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U2l6ZVBvbGlj"
    "eSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3ku"
    "UG9saWN5Lk1heGltdW0KICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdo"
    "dCgyNjApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2lu"
    "c2VydF9jYWxlbmRhcl9kYXRlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuY2Fs"
    "ZW5kYXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkU3RyZXRjaCgwKQoKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFjZSwgMSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICJbTEFZT1VUXSByaWdodC1zaWRlIGNhbGVuZGFyIHJlc3RvcmVkIChwZXJzaXN0ZW50IGxvd2VyLXJp"
    "Z2h0IHNlY3Rpb24pLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICJbTEFZT1VUXSBwZXJzaXN0ZW50IG1pbmkgY2FsZW5kYXIgcmVzdG9yZWQvY29uZmlybWVk"
    "IChhbHdheXMgdmlzaWJsZSBsb3dlci1yaWdodCkuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAg"
    "IHJldHVybiBsYXlvdXQKCiAgICAjIOKUgOKUgCBTVEFSVFVQIFNFUVVFTkNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIF9zdGFydHVwX3NlcXVlbmNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsIGYi4pymIHtBUFBfTkFNRX0gQVdBS0VOSU5HLi4uIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiU1lTVEVNIiwgZiLinKYge1JVTkVTfSDinKYiKQoKICAgICAgICAjIExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAg"
    "IGJvb3RfbG9nID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBpZiBib290"
    "X2xvZy5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbXNncyA9IGJvb3RfbG9nLnJlYWRf"
    "dGV4dChlbmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "Z19tYW55KG1zZ3MpCiAgICAgICAgICAgICAgICBib290X2xvZy51bmxpbmsoKSAgIyBjb25zdW1lZAogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIEhhcmR3YXJlIGRldGVjdGlv"
    "biBtZXNzYWdlcwogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdldF9kaWFnbm9z"
    "dGljcygpKQoKICAgICAgICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBjcml0aWNhbCA9IERlcGVuZGVuY3lD"
    "aGVja2VyLmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShkZXBfbXNncykKCiAgICAgICAgIyBM"
    "b2FkIHBhc3Qgc3RhdGUKICAgICAgICBsYXN0X3N0YXRlID0gc2VsZi5fc3RhdGUuZ2V0KCJ2YW1waXJlX3N0YXRlX2F0"
    "X3NodXRkb3duIiwiIikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5G"
    "TyIKICAgICAgICAgICAgKQoKICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQo"
    "IlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9uaW5nIHtERUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAg"
    "IHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtl"
    "cihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgIGxh"
    "bWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNv"
    "bm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICBz"
    "ZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgc2Vs"
    "Zi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2Fj"
    "dGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBk"
    "ZWYgX29uX2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBpZiBzdWNjZXNz"
    "OgogICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMo"
    "IklETEUiKQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYu"
    "X2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMo"
    "KQoKICAgICAgICAgICAgIyBNZWFzdXJlIFZSQU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBp"
    "ZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFU"
    "aW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJhbV9iYXNlbGluZSkKICAgICAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAgICAgIyBWYW1waXJlIHN0YXRl"
    "IGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAgICAgc3RhdGUgPSBn"
    "ZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncyA9IF9zdGF0ZV9ncmVldGluZ3Nf"
    "bWFwKCkKICAgICAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KAogICAgICAgICAgICAgICAgICAgICJTWVNURU0i"
    "LAogICAgICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzLmdldChzdGF0ZSwgZiJ7REVDS19OQU1FfSBpcyBvbmxp"
    "bmUuIikKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgIyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVjdGlv"
    "biDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBJZiB0aGVyZSdzIGEgcHJldmlvdXMgc2h1dGRv"
    "d24gcmVjb3JkZWQsIGluamVjdCBjb250ZXh0CiAgICAgICAgICAgICMgc28gTW9yZ2FubmEgY2FuIGdyZWV0IHdpdGgg"
    "YXdhcmVuZXNzIG9mIGhvdyBsb25nIHNoZSBzbGVwdAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg4MDAsIHNl"
    "bGYuX3NlbmRfd2FrZXVwX3Byb21wdCkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJF"
    "UlJPUiIpCiAgICAgICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgicGFuaWNrZWQiKQoKICAgIGRlZiBfZm9ybWF0"
    "X2VsYXBzZWQoc2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgICAgICAiIiJGb3JtYXQgZWxhcHNlZCBzZWNv"
    "bmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0aW9uLiIiIgogICAgICAgIGlmIHNlY29uZHMgPCA2MDoKICAgICAgICAg"
    "ICAgcmV0dXJuIGYie2ludChzZWNvbmRzKX0gc2Vjb25keydzJyBpZiBzZWNvbmRzICE9IDEgZWxzZSAnJ30iCiAgICAg"
    "ICAgZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAgICAgICAgICAgbSA9IGludChzZWNvbmRzIC8vIDYwKQogICAgICAgICAg"
    "ICBzID0gaW50KHNlY29uZHMgJSA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie219IG1pbnV0ZXsncycgaWYgbSAhPSAx"
    "IGVsc2UgJyd9IiArIChmIiB7c31zIiBpZiBzIGVsc2UgIiIpCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgODY0MDA6CiAg"
    "ICAgICAgICAgIGggPSBpbnQoc2Vjb25kcyAvLyAzNjAwKQogICAgICAgICAgICBtID0gaW50KChzZWNvbmRzICUgMzYw"
    "MCkgLy8gNjApCiAgICAgICAgICAgIHJldHVybiBmIntofSBob3VyeydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsgKGYi"
    "IHttfW0iIGlmIG0gZWxzZSAiIikKICAgICAgICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNlY29uZHMgLy8gODY0"
    "MDApCiAgICAgICAgICAgIGggPSBpbnQoKHNlY29uZHMgJSA4NjQwMCkgLy8gMzYwMCkKICAgICAgICAgICAgcmV0dXJu"
    "IGYie2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9IiArIChmIiB7aH1oIiBpZiBoIGVsc2UgIiIpCgogICAgZGVm"
    "IF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGhpZGRlbiB3YWtlLXVwIGNv"
    "bnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9hZHMuIiIiCiAgICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRl"
    "LmdldCgibGFzdF9zaHV0ZG93biIpCiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVy"
    "biAgIyBGaXJzdCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMgQ2FsY3Vs"
    "YXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBkYXRldGltZS5mcm9t"
    "aXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAg"
    "ICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21wYXJpc29uCiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5m"
    "byBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgp"
    "LnJlcGxhY2UodHppbmZvPU5vbmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3duX2R0"
    "KS50b3RhbF9zZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9mb3JtYXRfZWxhcHNlZChlbGFw"
    "c2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBlbGFwc2VkX3N0ciA9ICJhbiB1bmtu"
    "b3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBzdG9yZWQgZmFyZXdlbGwgYW5kIGxhc3QgY29udGV4dAogICAgICAg"
    "IGZhcmV3ZWxsICAgICA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9mYXJld2VsbCIsICIiKQogICAgICAgIGxhc3RfY29u"
    "dGV4dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAgICMgQnVpbGQg"
    "d2FrZS11cCBwcm9tcHQKICAgICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAgICBpZiBsYXN0X2NvbnRleHQ6CiAg"
    "ICAgICAgICAgIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBmaW5hbCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW9u"
    "OlxuIgogICAgICAgICAgICBmb3IgaXRlbSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBzcGVha2VyID0g"
    "aXRlbS5nZXQoInJvbGUiLCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQgICAgPSBpdGVtLmdl"
    "dCgiY29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICAgY29udGV4dF9ibG9jayArPSBmIntzcGVha2VyfTog"
    "e3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gIiIKICAgICAgICBpZiBmYXJld2VsbDoKICAgICAgICAg"
    "ICAgZmFyZXdlbGxfYmxvY2sgPSBmIlxuXG5Zb3VyIGZpbmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpc"
    "blwie2ZhcmV3ZWxsfVwiIgoKICAgICAgICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1"
    "c3QgYmVlbiByZWFjdGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgICAgICAgICAgZiJ7"
    "ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKICAgICAgICAgICAgZiJcbkdyZWV0"
    "IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHlvdSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAg"
    "ICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2FpZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVs"
    "LiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmpl"
    "Y3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAg"
    "ICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YWtldXBfcHJvbXB0fSkKICAgICAg"
    "ICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVN"
    "X1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYu"
    "X3dha2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAg"
    "ICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVz"
    "cG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9v"
    "Y2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtF"
    "VVBdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29y"
    "a2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJO"
    "XSBXYWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgog"
    "ICAgICAgICAgICApCgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "CiAgICAgICAgRm9yY2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUgZXZlbnQgbG9vcCBpcyBy"
    "dW5uaW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3NpbmcvaW52YWxpZCwgdGhlIGJyb3dzZXIgT0F1dGggZmxvdyBv"
    "cGVucyBuYXR1cmFsbHkuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQ"
    "SV9PSzoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJU"
    "VVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxhYmxlLiIs"
    "CiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBHT09HTEVfSU1QT1JUX0VS"
    "Uk9SOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dP"
    "T0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fZ2NhbCBvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBz"
    "a2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICAgICAgICAg"
    "ICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2su"
    "IiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVd"
    "W1NUQVJUVVBdIGNyZWRlbnRpYWxzPXtzZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAgICAgICAgICAg"
    "ICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "IGYiW0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYuX2djYWwudG9rZW5fcGF0aH0iLAogICAgICAgICAgICAgICAg"
    "IklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHNlbGYuX2djYWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIENhbGVuZGFyIGF1dGggcmVhZHkuIiwgIk9L"
    "IikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5lbnN1cmVfc2VydmljZXMoKQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIERyaXZlL0RvY3MgYXV0aCByZWFkeS4iLCAiT0siKQogICAgICAgICAg"
    "ICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRydWUKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dP"
    "T0dMRV1bU1RBUlRVUF0gU2NoZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRlciBhdXRoLiIsICJJTkZP"
    "IikKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9jcykKCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gUG9zdC1hdXRoIHRhc2sgcmVmcmVz"
    "aCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwo"
    "KQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFy"
    "IGluYm91bmQgc3luYyB0cmlnZ2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2Nv"
    "dW50ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBHb29nbGUg"
    "Q2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1wb3J0ZWRfY291bnQpfS4iLAogICAgICAgICAgICAgICAg"
    "IklORk8iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBf"
    "cmVmcmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9s"
    "ZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoIkxvYWRp"
    "bmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnBhdGhfbGFiZWwuc2V0"
    "VGV4dCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1z"
    "KGZvbGRlcl9pZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAgIHNl"
    "bGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBk"
    "ZWYgX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5f"
    "Z29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENh"
    "bGVuZGFyIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBpbmJv"
    "dW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCBwb2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQg"
    "dGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwgY29tcGxldGUg"
    "4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxl"
    "bmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9j"
    "YWxfYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVy"
    "X3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90"
    "IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFj"
    "a2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAg"
    "ICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfcmVjb3Jk"
    "c19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJl"
    "Y29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4Ogog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJ"
    "VkVdW1NZTkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAgICAgICAg"
    "ICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAg"
    "ZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9"
    "IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNl"
    "bGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5"
    "cz03KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBlbmQg"
    "PSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInll"
    "YXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93"
    "X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAg"
    "ICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93"
    "PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gaG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMn"
    "KX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZh"
    "bGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0"
    "KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19j"
    "b21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCgogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQog"
    "ICAgICAgICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3NfdGFi"
    "X2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9uZToKICAgICAgICAgICAg"
    "ICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIGRhdGV0aW1l"
    "IHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlm"
    "IGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0"
    "ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmls"
    "dGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQp"
    "fSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAg"
    "ICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgogICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNl"
    "bGYsIGV2ZW50OiBkaWN0KToKICAgICAgICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAg"
    "ICAgICAgZGF0ZV90aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAgICAg"
    "ICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJnb29nbGVfZXZlbnRf"
    "ZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAg"
    "ICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAgICBpZiBkYXRlX29ubHk6CiAgICAgICAgICAgIHBh"
    "cnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xl"
    "X2V2ZW50X2RhdGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAgICAgICAgICAg"
    "dmlzaWJsZV9jb3VudCA9IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0u"
    "IiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNv"
    "bj0icmVnaXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIHN0b3Bf"
    "ZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1Nd"
    "W1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtlciBjbGVhbmx5OiB7c3RvcF9leH0iLAog"
    "ICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVy"
    "X2NoYW5nZWQoc2VsZiwgZmlsdGVyX2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0"
    "ZXIgPSBzdHIoZmlsdGVyX2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9"
    "LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfdG9n"
    "Z2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBs"
    "ZXRlZCA9IG5vdCBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93"
    "X2NvbXBsZXRlZChzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdp"
    "c3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAg"
    "aWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBbXQog"
    "ICAgICAgIHJldHVybiBzZWxmLl90YXNrc190YWIuc2VsZWN0ZWRfdGFza19pZHMoKQoKICAgIGRlZiBfc2V0X3Rhc2tf"
    "c3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGlm"
    "IHN0YXR1cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNvbXBsZXRlKHRh"
    "c2tfaWQpCiAgICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxm"
    "Ll90YXNrcy5jYW5jZWwodGFza19pZCkKICAgICAgICBlbHNlOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFz"
    "a3MudXBkYXRlX3N0YXR1cyh0YXNrX2lkLCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAg"
    "ICByZXR1cm4gTm9uZQoKICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9p"
    "ZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0ZV9ldmVudF9mb3JfdGFzayhnb29nbGVfZXZlbnRfaWQpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJbVEFTS1NdW1dBUk5dIEdvb2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza19p"
    "ZD17dGFza19pZH06IHtleH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAg"
    "ICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAg"
    "ICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExFVEUgU0VMRUNURUQg"
    "YXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lz"
    "dHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9u"
    "ZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBp"
    "ZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19pZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSAr"
    "PSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7"
    "ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkK"
    "CiAgICBkZWYgX3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHJlbW92ZWQgPSBzZWxm"
    "Ll90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gUFVSR0Ug"
    "Q09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hf"
    "dGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0"
    "ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwg"
    "Tm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc3RhdHVzKHRleHQsIG9rPW9r"
    "KQoKICAgIGRlZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93"
    "X2xvY2FsID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEobWlu"
    "dXRlcz0zMCkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbmFtZS5zZXRUZXh0KCIiKQogICAgICAg"
    "IHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIl"
    "WS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93"
    "X2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0"
    "ZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFz"
    "a19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5f"
    "dGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIu"
    "dGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jf"
    "cmVjdXJyZW5jZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNl"
    "dENoZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmlndXJlIHRhc2sg"
    "ZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkKICAgICAgICBzZWxmLl90YXNr"
    "c190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAg"
    "ICAgICBzZWxmLl90YXNrc190YWIuY2xvc2VfZWRpdG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAg"
    "IGRlZiBfcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDogc3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxs"
    "X2RheTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2UpOgogICAgICAgIGRhdGVfdGV4dCA9IChkYXRlX3RleHQgb3Ig"
    "IiIpLnN0cmlwKCkKICAgICAgICB0aW1lX3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYg"
    "bm90IGRhdGVfdGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBhbGxfZGF5OgogICAgICAgICAg"
    "ICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBtaW51dGUgPSA1OSBpZiBpc19lbmQgZWxzZSAw"
    "CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge2hvdXI6MDJkfTp7bWlu"
    "dXRlOjAyZH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0"
    "aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIG5v"
    "cm1hbGl6ZWQgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0PSJ0YXNrX2VkaXRv"
    "cl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRURJVE9S"
    "XSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9LCBhbGxfZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBm"
    "ImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFs"
    "aXplZCBlbHNlICdOb25lJ30iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3Jt"
    "YWxpemVkCgogICAgZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAgIGlmIHRhYiBpcyBOb25lOgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50YXNrX2VkaXRvcl9uYW1lLnRleHQoKS5zdHJpcCgpCiAg"
    "ICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2VkaXRvcl9hbGxfZGF5LmlzQ2hlY2tlZCgpCiAgICAgICAgc3RhcnRfZGF0"
    "ZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRh"
    "Yi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUgPSB0YWIudGFza19l"
    "ZGl0b3JfZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRf"
    "dGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdGVzID0gdGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxhaW5UZXh0"
    "KCkuc3RyaXAoKQogICAgICAgIGxvY2F0aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgcmVjdXJyZW5jZSA9IHRhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgogICAg"
    "ICAgIGlmIG5vdCB0aXRsZToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiVGFzayBOYW1l"
    "IGlzIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0"
    "ZSBvciBub3QgZW5kX2RhdGUgb3IgKG5vdCBhbGxfZGF5IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1l"
    "KSk6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZCBkYXRlIGFuZCB0aW1l"
    "IGFyZSByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShzdGFydF9kYXRlLCBzdGFydF90aW1lLCBhbGxf"
    "ZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShl"
    "bmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXksIGlzX2VuZD1UcnVlKQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQg"
    "b3Igbm90IGVuZF9kdDoKICAgICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZhaWxl"
    "ZCIpCiAgICAgICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tf"
    "ZWRpdG9yX3N0YXR1cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQgZGF0ZXRpbWUuIiwgb2s9RmFsc2Up"
    "CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9z"
    "ZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJbnZhbGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBI"
    "SDpNTS4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9n"
    "ZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBwYXlsb2FkID0geyJzdW1tYXJ5IjogdGl0bGV9CiAgICAg"
    "ICAgaWYgYWxsX2RheToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZSI6IHN0YXJ0X2R0LmRhdGUo"
    "KS5pc29mb3JtYXQoKX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGUiOiAoZW5kX2R0LmRhdGUoKSAr"
    "IHRpbWVkZWx0YShkYXlzPTEpKS5pc29mb3JtYXQoKX0KICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJz"
    "dGFydCJdID0geyJkYXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3Bl"
    "Yz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0"
    "ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0"
    "aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbImRlc2NyaXB0aW9u"
    "Il0gPSBub3RlcwogICAgICAgIGlmIGxvY2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJdID0gbG9j"
    "YXRpb24KICAgICAgICBpZiByZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1cnJl"
    "bmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgiUlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJlbmNlfSIKICAgICAgICAg"
    "ICAgcGF5bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1bGVdCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNL"
    "U11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdGFydCBmb3IgdGl0bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIGV2ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5jcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBh"
    "eWxvYWQsIGNhbGVuZGFyX2lkPSJwcmltYXJ5IikKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2Fs"
    "bCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiBmInRhc2tfe3V1aWQudXVpZDQoKS5o"
    "ZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICAgICAiZHVlX2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAg"
    "ICAicHJlX3RyaWdnZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAgICAgICAgInN0YXR1cyI6"
    "ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAg"
    "InJldHJ5X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAg"
    "ICAgICAgICAibmV4dF9yZXRyeV9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNl"
    "LAogICAgICAgICAgICAgICAgInNvdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lk"
    "IjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwKICAgICAgICAgICAgICAg"
    "ICJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAg"
    "ICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0IiwKICAgICAgICAgICAgICAg"
    "ICAgICAibm90ZXMiOiBub3RlcywKICAgICAgICAgICAgICAgICAgICAic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3Jt"
    "YXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5IjogYm9vbChhbGxfZGF5KSwK"
    "ICAgICAgICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwKICAgICAgICAgICAgICAgICAgICAicmVjdXJy"
    "ZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICB9CiAgICAgICAgICAgIHRhc2tz"
    "LmFwcGVuZCh0YXNrKQogICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2Vs"
    "Zi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3VjY2VlZGVkIGFuZCB0YXNrIHJlZ2lzdHJ5IHVw"
    "ZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xl"
    "IHNhdmUgc3VjY2VzcyBmb3IgdGl0bGU9J3t0aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAg"
    "ICAgICAiT0siLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9y"
    "X3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZhbHNlKQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVy"
    "ZSBmb3IgdGl0bGU9J3t0aXRsZX0nOiB7ZXh9IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9jYWxl"
    "bmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF0ZS50b1N0"
    "cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJub25lIgoKICAgICAgICBmb2N1c193aWRn"
    "ZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQogICAgICAgIGRpcmVjdF90YXJnZXRzID0gWwogICAgICAgICAg"
    "ICAoInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25l"
    "KSwgInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5kX2Rh"
    "dGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX2VuZF9kYXRl"
    "IiwgTm9uZSkpLAogICAgICAgIF0KICAgICAgICBmb3IgbmFtZSwgd2lkZ2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAg"
    "ICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5vbmUgYW5kIGZvY3VzX3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAgICAg"
    "ICAgICB3aWRnZXQuc2V0VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQog"
    "ICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgcm91dGVkX3RhcmdldCA9PSAibm9uZSI6CiAgICAgICAgICAg"
    "IGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIpIGFuZCBzZWxmLl9pbnB1dF9maWVsZCBpcyBub3QgTm9uZToK"
    "ICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdldCBpcyBzZWxmLl9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5pbnNlcnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90"
    "YXJnZXQgPSAiaW5wdXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICByb3V0ZWRfdGFy"
    "Z2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIpIGFuZCBz"
    "ZWxmLl90YXNrc190YWIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwu"
    "c2V0VGV4dChmIkNhbGVuZGFyIGRhdGUgc2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihz"
    "ZWxmLCAiX2RpYWdfdGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6"
    "IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgog"
    "ICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9yY2Vf"
    "b25jZTogYm9vbCA9IEZhbHNlKToKICAgICAgICAiIiIKICAgICAgICBTeW5jIEdvb2dsZSBDYWxlbmRhciBldmVudHMg"
    "4oaSIGxvY2FsIHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBBUEkuCgogICAgICAgIFN0YWdlIDEgKGZpcnN0"
    "IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3luY1Rva2VuLgogICAgICAgIFN0YWdlIDIgKGV2"
    "ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVzaW5nIHN0b3JlZCBzeW5jVG9rZW4g4oCUCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJucyBPTkxZIHdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0"
    "cy9jYW5jZWxzKS4KICAgICAgICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZhbGxz"
    "IGJhY2sgdG8gZnVsbCBzeW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFuZCBub3QgYm9v"
    "bChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJsZWQiLCBUcnVlKSk6CiAgICAgICAg"
    "ICAgIHJldHVybiAwCgogICAgICAgIHRyeToKICAgICAgICAgICAgbm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAg"
    "ICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQg"
    "PSB7CiAgICAgICAgICAgICAgICAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAg"
    "ICAgICAgICAgICBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgaWYgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQi"
    "KSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICB9CgogICAgICAgICAgICAjIOKUgOKUgCBGZXRjaCBmcm9tIEdvb2ds"
    "ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAg"
    "ICAgc3RvcmVkX3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIpCgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5vdCBmb3JjZV9vbmNlOgogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVd"
    "W1NZTkNdIEluY3JlbWVudGFsIHN5bmMgKHN5bmNUb2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFy"
    "eV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAgICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tl"
    "bikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRl"
    "dGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAo"
    "bm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAg"
    "cmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCgogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoKICAgICAgICAgICAgICAgIGlmICI0MTAiIGluIHN0cihhcGlfZXgpIG9y"
    "ICJHb25lIiBpbiBzdHIoYXBpX2V4KToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDigJQgZnVsbCBy"
    "ZXN5bmMuIiwgIldBUk4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3N0YXRl"
    "LnBvcCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iLCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMg"
    "PSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9t"
    "aW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAg"
    "ICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2"
    "ZW50KHMpLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2VuIGZvciBuZXh0"
    "IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICAgICAgICAgICAgIHNlbGYuX3N0"
    "YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF90b2tlbgogICAgICAgICAgICAgICAgc2VsZi5f"
    "bWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9IDAKICAgICAgICAg"
    "ICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3IgZXZlbnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAg"
    "ICAgICAgIGV2ZW50X2lkID0gKGV2ZW50LmdldCgiaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYg"
    "bm90IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVk"
    "IC8gY2FuY2VsbGVkIG9uIEdvb2dsZSdzIHNpZGUKICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgic3RhdHVzIikg"
    "PT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQo"
    "ZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3RhdHVzIikg"
    "bm90IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "c3RhdHVzIl0gICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJjYW5j"
    "ZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMi"
    "XSAgICA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2Vk"
    "X2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRh"
    "Iiwge30pWyJnb29nbGVfZGVsZXRlZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVt"
    "b3ZlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1b"
    "U1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4dCcsJz8nKX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVu"
    "dC5nZXQoInN1bW1hcnkiKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVu"
    "ZGFyIEV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUo"
    "ZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkKCiAg"
    "ICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgICAgICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBj"
    "aGFuZ2VkCiAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBp"
    "ZiAoZXhpc3RpbmcuZ2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2Vk"
    "ID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgZHVlX2lz"
    "byA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBl"
    "eGlzdGluZy5nZXQoImR1ZV9hdCIpICE9IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1siZHVlX2F0Il0gICAgICAgPSBkdWVfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJl"
    "X3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vj"
    "b25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAg"
    "ICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0YXR1cyIpICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgICAgICAg"
    "ICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tf"
    "Y2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICB1"
    "cGRhdGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xF"
    "XVtTWU5DXSBVcGRhdGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgICAgICAgICAgICAgIGlm"
    "IG5vdCBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgbmV3"
    "X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51"
    "dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19p"
    "c28sCiAgICAgICAgICAgICAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICAgKGR1ZV9h"
    "dCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0"
    "YXR1cyI6ICAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0"
    "IjogICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAibmV4"
    "dF9yZXRyeV9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgICBG"
    "YWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICAgImdvb2dsZSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAic3luY19zdGF0dXMiOiAgICAgICAic3luY2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2Vk"
    "X2F0IjogICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgImdvb2dsZV9pbXBvcnRlZF9hdCI6IG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAgICAgZXZlbnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIH0sCiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwcGVuZChuZXdfdGFz"
    "aykKICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtldmVudF9pZF0gPSBuZXdfdGFzawogICAgICAg"
    "ICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3Vt"
    "bWFyeX0iLCAiSU5GTyIpCgogICAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Mu"
    "c2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIERvbmUg4oCU"
    "IGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAgZiJ1cGRhdGVkPXt1cGRhdGVkX2NvdW50"
    "fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBp"
    "bXBvcnRlZF9jb3VudAoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAw"
    "CgoKICAgIGRlZiBfbWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgTlZNTF9PSyBh"
    "bmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZp"
    "Y2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA9IG1l"
    "bS51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAg"
    "ICAgIGYiW1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2VsZi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIKICAgICAg"
    "ICAgICAgICAgICAgICBmIih7REVDS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNT"
    "QUdFIEhBTkRMSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZW5kX21lc3NhZ2Uoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAi"
    "U1VTUEVORCI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCku"
    "c3RyaXAoKQogICAgICAgIGlmIG5vdCB0ZXh0OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sg"
    "dG8gcGVyc29uYSBjaGF0IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX21haW5fdGFi"
    "cy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDAp"
    "CgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiWU9VIiwg"
    "dGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgi"
    "dXNlciIsIHRleHQpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1"
    "c2VyIiwgdGV4dCkKCiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVk"
    "aWF0ZWx5CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJf"
    "bWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21wdCB3aXRoIHZhbXBpcmUgY29udGV4dCAr"
    "IG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9jdHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAg"
    "ICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJu"
    "YWxfY3R4ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAg"
    "ICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCdWls"
    "ZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5"
    "X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0"
    "eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9IHZhbXBp"
    "cmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50IGlucHV0CiAgICAgICAgaWYg"
    "YW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVu"
    "Y3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0"
    "aG9uIgogICAgICAgICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3Vh"
    "Z2UobGFuZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxu"
    "e2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAg"
    "ICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3Vz"
    "cGVuZGVkX2R1cmF0aW9uIG9yICJzb21lIHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAg"
    "ICBmIlxuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3Ig"
    "Zm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IHRob3VnaHRz"
    "IHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcgdGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlz"
    "IGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBzZWxm"
    "Ll9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hp"
    "c3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZh"
    "bHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0"
    "YXR1cygiR0VORVJBVElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAg"
    "ICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIExhdW5jaCBzdHJlYW1p"
    "bmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9h"
    "ZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1heF90b2tlbnM9NTEyCiAgICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtl"
    "ci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNlbGYuX3dvcmtlci5yZXNwb25zZV9k"
    "b25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIuZXJyb3Jfb2NjdXJy"
    "ZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVj"
    "dChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRl"
    "IHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBk"
    "ZWYgX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0ZSB0"
    "aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAg"
    "ICAgQ2FsbGVkIG9uIGZpcnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQgdG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAg"
    "ICAgICAiIiIKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAg"
    "ICAgICMgV3JpdGUgdGhlIHNwZWFrZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2Vucwog"
    "ICAgICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "YXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4"
    "OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0i"
    "Y29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYne0RFQ0tfTkFNRS51cHBl"
    "cigpfSDinak8L3NwYW4+ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxh"
    "aW5UZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJz"
    "b3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9rZW4oc2VsZiwg"
    "dG9rZW46IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlzcGxh"
    "eS4iIiIKICAgICAgICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9y"
    "ZXNwb25zZSgpCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5N"
    "b3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAg"
    "ICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0X2Rp"
    "c3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZl"
    "cnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBfb25fcmVzcG9uc2VfZG9uZShzZWxm"
    "LCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlzIG9uIGl0cyBvd24gbGlu"
    "ZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92"
    "ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5z"
    "ZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxu"
    "IikKCiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgKz0g"
    "bGVuKHJlc3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIs"
    "IHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNz"
    "aXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9p"
    "ZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAjIFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBpZiBzZWxmLl9ibG9v"
    "ZF9zcGhlcmUgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2Jsb29kX3NwaGVyZS5zZXRGaWxsKAogICAgICAg"
    "ICAgICAgICAgbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAg"
    "IyBSZS1lbmFibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkK"
    "CiAgICAgICAgIyBSZXN1bWUgaWRsZSB0aW1lcgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2No"
    "ZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1"
    "bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAg"
    "ICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoK"
    "ICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2Vu"
    "dGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2Vf"
    "cmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoK"
    "ICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9m"
    "YWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAg"
    "ICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQo"
    "IkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJv"
    "cn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNl"
    "X3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAg"
    "ICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIp"
    "CiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVu"
    "IHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUg"
    "bW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0"
    "IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3Vy"
    "ZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0"
    "YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQ"
    "T1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgog"
    "ICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBp"
    "ZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRv"
    "cnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5f"
    "YXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAg"
    "ICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3Rh"
    "bmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2Nh"
    "bFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFw"
    "dG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRP"
    "UkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9"
    "IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZy"
    "b20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6"
    "IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0"
    "cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVu"
    "YWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4"
    "aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAg"
    "ICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5f"
    "dG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihk"
    "ZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAg"
    "IGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5l"
    "dmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVN"
    "IiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAg"
    "ICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMu"
    "IFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAg"
    "IHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtFIG1vZGUg4oCUIGF1"
    "dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVs"
    "IHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lT"
    "VEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRv"
    "cnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxh"
    "cHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAg"
    "ICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxm"
    "Ll9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0"
    "KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAg"
    "ICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5s"
    "b2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVy"
    "LmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVf"
    "dGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRl"
    "ZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVy"
    "eSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkg"
    "dHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQg"
    "aXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlm"
    "IHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAg"
    "ICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFs"
    "X3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5B"
    "TF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToK"
    "ICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRp"
    "bmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAg"
    "ICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1f"
    "cHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tT"
    "fSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJl"
    "X3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNl"
    "bGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJB"
    "TSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAg"
    "ICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQg"
    "YWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3By"
    "ZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBh"
    "dXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29u"
    "X3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dh"
    "a2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9X"
    "QUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tz"
    "ID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9S"
    "IEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQ"
    "U0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNr"
    "Z3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tn"
    "cm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2"
    "MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1"
    "bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxF"
    "Ul0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBh"
    "bmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAg"
    "ICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIs"
    "IDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAg"
    "IHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1"
    "dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBz"
    "ZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVy"
    "dmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAgICMgSWRs"
    "ZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRs"
    "ZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXgg"
    "PSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9"
    "IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAg"
    "ICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlk"
    "bGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgTW9vbiB3aWRnZXQg"
    "cmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBpZiBzZWxmLl9tb29uX3dpZGdldCBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgICAgICBzZWxmLl9tb29uX3dpZGdldC51"
    "cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAg"
    "ICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9z"
    "Y2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0"
    "aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAg"
    "ICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxl"
    "cihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0"
    "ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0"
    "IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAg"
    "ICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBT"
    "dGFydCBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRl"
    "YmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAg"
    "ICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9y"
    "KEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNz"
    "aW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVf"
    "dHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxm"
    "Ll9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91"
    "Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCU"
    "IHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lv"
    "bnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20u"
    "Y2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBi"
    "dWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgp"
    "CgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwK"
    "ICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBtb2Rl"
    "PW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVm"
    "IF9vbl9pZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBh"
    "cHBlbmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAgICAgICAg"
    "ICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxh"
    "eS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAg"
    "ICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxmLl9pZGxlX3dv"
    "cmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxlX3dv"
    "cmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0lETEUgRVJST1JdIHtlfSIsICJFUlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0"
    "YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb3Vy"
    "bmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9u"
    "cy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChkYXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7"
    "ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91"
    "cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0LiAi"
    "CiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0aW9uLiIsICJPSyIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiQSBtZW1vcnkg"
    "c3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAg"
    "ICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUg"
    "PSAoCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5h"
    "bCBmcm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB5"
    "b3Ugbm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYXRpb24uIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAg"
    "IGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xl"
    "YXJfbG9hZGVkX2pvdXJuYWwoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29u"
    "dGV4dCBjbGVhcmVkLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAg"
    "ICAgIlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAgICApCgogICAgIyDi"
    "lIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91"
    "cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5f"
    "c2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8v"
    "IDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgog"
    "ICAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAg"
    "ICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAgICAgIHNlc3Np"
    "b25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAogICAgICAgICkKICAgICAgICBzZWxmLl9o"
    "d19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIExlZnQgc3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBy"
    "dW50aW1lIHRva2VuIHBvb2wKICAgICAgICBibG9vZF9maWxsID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0"
    "MDk2LjApCiAgICAgICAgaWYgc2VsZi5fYmxvb2Rfc3BoZXJlIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9i"
    "bG9vZF9zcGhlcmUuc2V0RmlsbChibG9vZF9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgIyBSaWdodCBzcGhl"
    "cmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX21hbmFfc3BoZXJlIGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAg"
    "ICAgICAgIHZyYW1fdXNlZCA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICB2cmFtX3RvdCAg"
    "PSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgbWFuYV9maWxsID0gbWF4KDAuMCwgMS4wIC0g"
    "KHZyYW1fdXNlZCAvIHZyYW1fdG90KSkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZS5zZXRGaWxs"
    "KG1hbmFfZmlsbCwgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX21hbmFfc3BoZXJlLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZS5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZh"
    "bHNlKQoKICAgICAgICAjIEhVTkdFUiA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGh1bmdlciA9"
    "IDEuMCAtIGJsb29kX2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5faHVu"
    "Z2VyX2dhdWdlLnNldFZhbHVlKGh1bmdlciAqIDEwMCwgZiJ7aHVuZ2VyKjEwMDouMGZ9JSIpCgogICAgICAgICMgVklU"
    "QUxJVFkgPSBSQU0gZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxf"
    "T0s6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1"
    "YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAgICB2aXRhbGl0eSAgPSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90"
    "YWwpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdml0YWxpdHlfZ2F1Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHZpdGFsaXR5ICogMTAwLCBmInt2aXRhbGl0eSoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl92aXRhbGl0"
    "eV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92aXRh"
    "bGl0eV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2"
    "ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFUIERJ"
    "U1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNl"
    "bGYsIHNwZWFrZXI6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAg"
    "IllPVSI6ICAgICBDX0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAg"
    "IlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICAgICAg"
    "ICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgREVD"
    "S19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAg"
    "ICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVh"
    "a2VyLCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9E"
    "SU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAg"
    "ICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAg"
    "ICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAg"
    "ICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0i"
    "Y29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1w"
    "fV0gPC9zcGFuPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQt"
    "d2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAgICAg"
    "ICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCgogICAg"
    "ICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcp"
    "CiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNw"
    "bGF5LmFwcGVuZCgiIikKCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFs"
    "dWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAg"
    "ICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUi"
    "OiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAiTE9B"
    "RElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJP"
    "RkZMSU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAg"
    "fQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jw"
    "b3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJ"
    "IHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNl"
    "bGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6"
    "ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmso"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAg"
    "ICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxm"
    "Ll9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hh"
    "cn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNo"
    "YXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xh"
    "YmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAg"
    "ICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZH"
    "WyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0"
    "KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsg"
    "IgogICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAi"
    "CiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxl"
    "ciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIGVu"
    "YWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNz"
    "aW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lv"
    "biBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3Nj"
    "aGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xl"
    "IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBfdG9nZ2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBz"
    "ZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9m"
    "c19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIK"
    "ICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAg"
    "ICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJ"
    "TVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAgIGRlZiBfdG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5k"
    "b3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAg"
    "ICAgICAgc2VsZi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaWYg"
    "c2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNl"
    "bGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBl"
    "LkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNP"
    "Tn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4"
    "OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4"
    "cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5v"
    "dCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19w"
    "YXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRy"
    "dWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAg"
    "ICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgu"
    "d3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJv"
    "YXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0"
    "X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtl"
    "eVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkKICAgICAgICBp"
    "ZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgICAg"
    "ICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQog"
    "ICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAg"
    "ICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAg"
    "ICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAg"
    "ICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2"
    "ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5v"
    "IGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9k"
    "aWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRp"
    "YWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVhZHkg"
    "aW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3No"
    "dXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBT"
    "aG93IGNvbmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2co"
    "c2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikKICAgICAgICBkbGcuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVk"
    "U2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJl"
    "bCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQogICAgICAg"
    "IGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5fcm93"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRv"
    "d24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5j"
    "ZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5f"
    "Y2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAg"
    "ICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxP"
    "T0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsg"
    "cGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRh"
    "OiBkbGcuZG9uZSgxKSkKICAgICAgICBidG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQog"
    "ICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jv"
    "dy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogICAgICAgIGJ0"
    "bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAg"
    "cmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQK"
    "ICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5k"
    "X2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBu"
    "b3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlm"
    "IHJlc3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxm"
    "Ll9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRv"
    "d24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNwb25zZSwgdGhl"
    "biBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAg"
    "IllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJT"
    "cGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAg"
    "ICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9j"
    "aGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBoZXIgZmlu"
    "YWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2Vs"
    "bF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hp"
    "c3RvcnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdl"
    "bGxfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90"
    "b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhl"
    "IHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBs"
    "YW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0"
    "IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5v"
    "bmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAg"
    "ICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29j"
    "Y3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChz"
    "ZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0"
    "ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBB"
    "SSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVT"
    "aG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAg"
    "ICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0"
    "IHNodXQgZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24o"
    "c2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIi"
    "CiAgICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUo"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2Vs"
    "bCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1l"
    "c3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9"
    "IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpd"
    "IGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0"
    "ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29udGVu"
    "dCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQK"
    "ICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFz"
    "IGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2Ug"
    "aWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxs"
    "X3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2"
    "ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAg"
    "ICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFy"
    "ZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0"
    "ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9"
    "IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAg"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3du"
    "Il0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9z"
    "dGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hl"
    "ZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQg"
    "c2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVk"
    "dWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYu"
    "X3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25f"
    "c291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAg"
    "c2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBh"
    "c3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0"
    "IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZp"
    "cnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVh"
    "dGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2Rl"
    "Y2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0"
    "aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVy"
    "CiAgICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAg"
    "ICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93"
    "IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAg"
    "ICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJh"
    "cCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBi"
    "b290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFs"
    "b2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5"
    "cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2Fn"
    "ZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3Rh"
    "Y2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQog"
    "ICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVk"
    "IikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoK"
    "ICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxnLmV4"
    "ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAg"
    "ICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBN"
    "b3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01v"
    "cmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAg"
    "ICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNL"
    "X05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAg"
    "ICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg"
    "4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19j"
    "ZmdbInBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiks"
    "CiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAi"
    "bWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFf"
    "aG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiks"
    "CiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJh"
    "Y2t1cHMiOiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIo"
    "bW9yZ2FubmFfaG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFfaG9t"
    "ZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJj"
    "cmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24i"
    "KSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5q"
    "c29uIiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2Nv"
    "cGVzIjogWwogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZl"
    "bnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAg"
    "ICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0s"
    "CiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29w"
    "eSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNyY19kZWNrID0gUGF0aChfX2Zp"
    "bGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxvd2Vy"
    "KCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAg"
    "ICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBjb3B5IGRl"
    "Y2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1h"
    "eSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0"
    "ZSBjb25maWcuanNvbiBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyAi"
    "Y29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVl"
    "KQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAg"
    "anNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRp"
    "cmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2Jh"
    "bCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2Zn"
    "KQogICAgICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAg"
    "d3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRl"
    "ZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAg"
    "ICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlw"
    "ZmlsZSBhcyBfemlwZmlsZQogICAgICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAg"
    "ICAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAg"
    "ICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAgICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxp"
    "c3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICB3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJh"
    "Y3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAg"
    "ICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBh"
    "Y2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1c"
    "blxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGly"
    "fSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRp"
    "bmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9"
    "IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIK"
    "ICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAg"
    "ICAgICAgICAgc2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAg"
    "ICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncu"
    "bmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhv"
    "bncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygp"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAg"
    "ICAgICAgICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAg"
    "c2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICAgICAgICAgICAgc2MuVGFy"
    "Z2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAgICAgICAgc2MuQXJndW1lbnRzICAgICAgID0g"
    "Zicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5h"
    "X2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNo"
    "byBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2Ny"
    "ZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHByaW50"
    "KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBDb21w"
    "bGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBj"
    "cmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgog"
    "ICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVh"
    "dGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9"
    "IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAg"
    "ICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9"
    "XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2lu"
    "ZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmls"
    "ZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVkIOKAlCB1"
    "c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2Vx"
    "dWVudCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhm"
    "IltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSBFY2hvRGVjaygpCiAg"
    "ICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3JlYXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQog"
    "ICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVu"
    "dCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBl"
    "dmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWdu"
    "YWxzIHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJkYTogKF9lYXJs"
    "eV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9zY2hlZHVsZXIoKSkp"
    "CiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRfc2NoZWR1"
    "bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBs"
    "YW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0"
    "dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElN"
    "RVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgog"
    "ICAgIyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFk"
    "IHJ1bnMKICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRX"
    "b3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRv"
    "dy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQog"
    "ICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoK"
    "CmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBh"
    "c3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgoj"
    "ICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNg=="
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
