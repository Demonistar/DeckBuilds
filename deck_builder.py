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
    "dGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJvbSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFs"
    "LCBJdGVyYXRvcgoKIyDilIDilIAgRUFSTFkgQ1JBU0ggTE9HR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEhvb2tzIGlu"
    "IGJlZm9yZSBRdCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFMTCBvdXRwdXQgaW5jbHVkaW5nCiMgQysrIGxldmVs"
    "IFF0IG1lc3NhZ2VzLiBXcml0dGVuIHRvIFtEZWNrTmFtZV0vbG9ncy9zdGFydHVwLmxvZwojIFRoaXMgc3RheXMgYWN0aXZl"
    "IGZvciB0aGUgbGlmZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJMWV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlfTE9HX1BB"
    "VEg6IE9wdGlvbmFsW1BhdGhdID0gTm9uZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+IE5vbmU6CiAgICB0cyA9IGRh"
    "dGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzotM10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNnfSIKICAg"
    "IF9FQVJMWV9MT0dfTElORVMuYXBwZW5kKGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQogICAgaWYgX0VBUkxZ"
    "X0xPR19QQVRIOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigiYSIsIGVuY29k"
    "aW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBmLndyaXRlKGxpbmUgKyAiXG4iKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCmRlZiBfaW5pdF9lYXJseV9sb2coYmFzZV9kaXI6IFBhdGgpIC0+IE5vbmU6"
    "CiAgICBnbG9iYWwgX0VBUkxZX0xPR19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIgLyAibG9ncyIKICAgIGxvZ19kaXIu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xPR19QQVRIID0gbG9nX2RpciAvIGYic3Rh"
    "cnR1cF97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0ubG9nIgogICAgIyBGbHVzaCBidWZmZXJl"
    "ZCBsaW5lcwogICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAg"
    "ICAgZm9yIGxpbmUgaW4gX0VBUkxZX0xPR19MSU5FUzoKICAgICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKCmRlZiBf"
    "aW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKSAtPiBOb25lOgogICAgIiIiCiAgICBJbnRlcmNlcHQgQUxMIFF0IG1lc3Nh"
    "Z2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2FybmluZ3MuCiAgICBUaGlzIGNhdGNoZXMgdGhlIFFUaHJlYWQgZGVzdHJveWVk"
    "IG1lc3NhZ2UgYXQgdGhlIHNvdXJjZSBhbmQgbG9ncyBpdAogICAgd2l0aCBhIGZ1bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cg"
    "ZXhhY3RseSB3aGljaCB0aHJlYWQgYW5kIHdoZXJlLgogICAgIiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0"
    "Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNzYWdlSGFuZGxlciwgUXRNc2dUeXBlCiAgICAgICAgaW1wb3J0IHRyYWNlYmFjawoK"
    "ICAgICAgICBkZWYgcXRfbWVzc2FnZV9oYW5kbGVyKG1zZ190eXBlLCBjb250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAg"
    "bGV2ZWwgPSB7CiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXREZWJ1Z01zZzogICAgIlFUX0RFQlVHIiwKICAgICAgICAg"
    "ICAgICAgIFF0TXNnVHlwZS5RdEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRX"
    "YXJuaW5nTXNnOiAgIlFUX1dBUk5JTkciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0Q3JpdGljYWxNc2c6ICJRVF9D"
    "UklUSUNBTCIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRGYXRhbE1zZzogICAgIlFUX0ZBVEFMIiwKICAgICAgICAg"
    "ICAgfS5nZXQobXNnX3R5cGUsICJRVF9VTktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0gIiIKICAgICAgICAgICAg"
    "aWYgY29udGV4dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmlsZX06e2NvbnRleHQu"
    "bGluZX1dIgoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2NhdGlvbn0ge21lc3NhZ2V9IikKCiAgICAg"
    "ICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxvZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAgICBpZiAi"
    "UVRocmVhZCIgaW4gbWVzc2FnZSBvciAidGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBzdGFj"
    "ayA9ICIiLmpvaW4odHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltTVEFD"
    "SyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3RhbGxNZXNzYWdlSGFuZGxlcihxdF9tZXNz"
    "YWdlX2hhbmRsZXIpCiAgICAgICAgX2Vhcmx5X2xvZygiW0lOSVRdIFF0IG1lc3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQog"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIF9lYXJseV9sb2coZiJbSU5JVF0gQ291bGQgbm90IGluc3RhbGwg"
    "UXQgbWVzc2FnZSBoYW5kbGVyOiB7ZX0iKQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7REVDS19OQU1FfSBkZWNrIHN0YXJ0aW5n"
    "IikKX2Vhcmx5X2xvZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNwbGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJs"
    "ZX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFdvcmtpbmcgZGlyZWN0b3J5OiB7b3MuZ2V0Y3dkKCl9IikKX2Vhcmx5X2xvZyhm"
    "IltJTklUXSBTY3JpcHQgbG9jYXRpb246IHtQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCl9IikKCiMg4pSA4pSAIE9QVElPTkFM"
    "IERFUEVOREVOQ1kgR1VBUkRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAoKUFNVVElMX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElM"
    "X09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6"
    "CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHN1dGlsIEZBSUxFRDoge2V9IikKCk5WTUxfT0sgPSBGYWxzZQpncHVfaGFu"
    "ZGxlID0gTm9uZQp0cnk6CiAgICBpbXBvcnQgd2FybmluZ3MKICAgIHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToK"
    "ICAgICAgICB3YXJuaW5ncy5zaW1wbGVmaWx0ZXIoImlnbm9yZSIpCiAgICAgICAgaW1wb3J0IHB5bnZtbAogICAgcHludm1s"
    "Lm52bWxJbml0KCkKICAgIGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VHZXRDb3VudCgpCiAgICBpZiBjb3VudCA+IDA6CiAg"
    "ICAgICAgZ3B1X2hhbmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxlQnlJbmRleCgwKQogICAgICAgIE5WTUxfT0sg"
    "PSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIE9LIOKAlCB7Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgRkFJTEVEOiB7ZX0iKQoKVE9SQ0hfT0sg"
    "PSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgdG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JD"
    "YXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9y"
    "Y2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJ"
    "TVBPUlRdIHRvcmNoIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQg"
    "d2luMzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHdpbjMyY29tIE9L"
    "IikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2luMzJjb20gRkFJTEVEOiB7"
    "ZX0iKQoKV0lOU09VTkRfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luc291bmQKICAgIFdJTlNPVU5EX09LID0gVHJ1"
    "ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9l"
    "YXJseV9sb2coZiJbSU1QT1JUXSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKClBZR0FNRV9PSyA9IEZhbHNl"
    "CnRyeToKICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5taXhlci5pbml0KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAg"
    "IF9lYXJseV9sb2coIltJTVBPUlRdIHB5Z2FtZSBPSyIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2co"
    "ZiJbSU1QT1JUXSBweWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xFX09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZhbHNl"
    "ICAjIGFsaWFzIHVzZWQgYnkgR29vZ2xlIHNlcnZpY2UgY2xhc3NlcwpHT09HTEVfSU1QT1JUX0VSUk9SID0gTm9uZQp0cnk6"
    "CiAgICBmcm9tIGdvb2dsZS5hdXRoLnRyYW5zcG9ydC5yZXF1ZXN0cyBpbXBvcnQgUmVxdWVzdCBhcyBHb29nbGVBdXRoUmVx"
    "dWVzdAogICAgZnJvbSBnb29nbGUub2F1dGgyLmNyZWRlbnRpYWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVk"
    "ZW50aWFscwogICAgZnJvbSBnb29nbGVfYXV0aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0YWxsZWRBcHBGbG93CiAgICBm"
    "cm9tIGdvb2dsZWFwaWNsaWVudC5kaXNjb3ZlcnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2dsZV9idWlsZAogICAgZnJvbSBnb29n"
    "bGVhcGljbGllbnQuZXJyb3JzIGltcG9ydCBIdHRwRXJyb3IgYXMgR29vZ2xlSHR0cEVycm9yCiAgICBHT09HTEVfT0sgPSBU"
    "cnVlCiAgICBHT09HTEVfQVBJX09LID0gVHJ1ZQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgX2U6CiAgICBHT09HTEVfSU1QT1JU"
    "X0VSUk9SID0gc3RyKF9lKQogICAgR29vZ2xlSHR0cEVycm9yID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVTID0gWwogICAg"
    "Imh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMu"
    "Y29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwK"
    "ICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCl0KR09PR0xFX1NDT1BFX1JFQVVUSF9N"
    "U0cgPSAoCiAgICAiR29vZ2xlIHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3IgaW5jb21wYXRpYmxlIHdpdGggcmVxdWVz"
    "dGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29uIGFuZCByZWF1dGhvcml6ZSB3aXRoIHRoZSB1cGRhdGVkIHNj"
    "b3BlIGxpc3QuIgopCkRFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUgPSAiQW1lcmljYS9DaGljYWdvIgpXSU5ET1dTX1Ra"
    "X1RPX0lBTkEgPSB7CiAgICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAiRWFzdGVy"
    "biBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRhcmQgVGltZSI6ICJBbWVy"
    "aWNhL0xvc19BbmdlbGVzIiwKICAgICJNb3VudGFpbiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvRGVudmVyIiwKfQoKCiMg"
    "4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZnJvbSBQeVNpZGU2LlF0"
    "V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFpbldpbmRvdywgUVdpZGdldCwgUVZCb3hMYXlvdXQsIFFI"
    "Qm94TGF5b3V0LAogICAgUUdyaWRMYXlvdXQsIFFUZXh0RWRpdCwgUUxpbmVFZGl0LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBR"
    "RnJhbWUsCiAgICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdpZGdldCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRlclZpZXcs"
    "CiAgICBRQWJzdHJhY3RJdGVtVmlldywgUVN0YWNrZWRXaWRnZXQsIFFUYWJXaWRnZXQsIFFMaXN0V2lkZ2V0LAogICAgUUxp"
    "c3RXaWRnZXRJdGVtLCBRU2l6ZVBvbGljeSwgUUNvbWJvQm94LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3Nh"
    "Z2VCb3gsIFFEYXRlRWRpdCwgUURpYWxvZywgUUZvcm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNwbGl0dGVyLCBRSW5w"
    "dXREaWFsb2csIFFUb29sQnV0dG9uCikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRo"
    "cmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNpemUsIFFQb2ludCwgUVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgK"
    "ICAgIFFGb250LCBRQ29sb3IsIFFQYWludGVyLCBRTGluZWFyR3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXht"
    "YXAsIFFQZW4sIFFQYWludGVyUGF0aCwgUVRleHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9u"
    "CikKCiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQ"
    "X05BTUUgICAgICA9IFVJX1dJTkRPV19USVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4wIgpBUFBfRklMRU5BTUUgID0gZiJ7"
    "REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0wNCIKCiMg4pSA4pSAIENPTkZJ"
    "RyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29uIGxpdmVzIG5l"
    "eHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcuIE5vdGhpbmcgaGFyZGNvZGVk"
    "IGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudApDT05GSUdf"
    "UEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5vdyB0aGF0IHdlIGtu"
    "b3cgd2hlcmUgd2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlfbG9nKGYiW0lOSVRdIFNDUklQVF9E"
    "SVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIENPTkZJR19QQVRIID0ge0NPTkZJR19QQVRIfSIpCl9l"
    "YXJseV9sb2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3RzOiB7Q09ORklHX1BBVEguZXhpc3RzKCl9IikKCmRlZiBfZGVm"
    "YXVsdF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBm"
    "aXJzdC1ydW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVybiB7CiAgICAgICAg"
    "ImRlY2tfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgImJh"
    "c2VfZGlyIjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7CiAgICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAg"
    "IyBsb2NhbCB8IG9sbGFtYSB8IGNsYXVkZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAg"
    "ICMgbG9jYWwgbW9kZWwgZm9sZGVyIHBhdGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4g"
    "ImRvbHBoaW4tMi42LTdiIgogICAgICAgICAgICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5B"
    "SSBrZXkKICAgICAgICAgICAgImFwaV90eXBlIjogIiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAg"
    "ICAgICAgImFwaV9tb2RlbCI6ICIiLCAgICAgICAgICAjIGUuZy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAg"
    "ICAgICAgImdvb2dsZSI6IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAv"
    "ICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIs"
    "CiAgICAgICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0"
    "aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJp"
    "dmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAg"
    "ICAgICAgXSwKICAgICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKFNDUklQ"
    "VF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIgLyAic291bmRzIiksCiAg"
    "ICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9u"
    "cyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihTQ1JJUFRfRElS"
    "IC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4cG9ydHMiKSwKICAgICAgICAg"
    "ICAgImxvZ3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIoU0NS"
    "SVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihTQ1JJUFRfRElSIC8gInBlcnNvbmFz"
    "IiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIpLAogICAgICAgIH0sCiAgICAg"
    "ICAgInNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9lbmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAg"
    "ICAgICAiaWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRsZV9tYXhfbWludXRlcyI6ICAg"
    "ICAgICAgIDMwLAogICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4"
    "X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAogICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRy"
    "dWUsCiAgICAgICAgICAgICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9p"
    "bmJvdW5kX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAgICAgICAiZ29vZ2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMw"
    "LAogICAgICAgICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0"
    "X3J1biI6IFRydWUsCiAgICB9CgpkZWYgbG9hZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4g"
    "UmV0dXJucyBkZWZhdWx0IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdfUEFUSC5leGlzdHMo"
    "KToKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAgICAgICB3aXRoIENPTkZJR19QQVRILm9w"
    "ZW4oInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNhdmVfY29uZmlnKGNmZzogZGlj"
    "dCkgLT4gTm9uZToKICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYt"
    "OCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywgZiwgaW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0IG1vZHVsZSBs"
    "ZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9tIENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJseV9sb2co"
    "ZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1vZGVsX3R5cGU9"
    "e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BBVEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7"
    "CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJzb3VuZHMiOiAgIFNDUklQVF9ESVIgLyAic291"
    "bmRzIiwKICAgICJtZW1vcmllcyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAogICAgInNlc3Npb25zIjogU0NSSVBUX0RJ"
    "UiAvICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJUFRfRElSIC8gInNsIiwKICAgICJleHBvcnRzIjogIFNDUklQ"
    "VF9ESVIgLyAiZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElSIC8gImxvZ3MiLAogICAgImJhY2t1cHMiOiAg"
    "U0NSSVBUX0RJUiAvICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVyc29uYXMiLAogICAgImdv"
    "b2dsZSI6ICAgU0NSSVBUX0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKSAtPiBOb25l"
    "OgogICAgIiIiCiAgICBTZWxmLWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMgbWlzc2luZyByZXF1aXJlZCBwYXRoIGtl"
    "eXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBub3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxv"
    "Y2F0aW9ucywKICAgIHRoZW4gcGVyc2lzdHMgY29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgogICAg"
    "Y2hhbmdlZCA9IEZhbHNlCiAgICBwYXRocyA9IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVm"
    "YXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdldChrZXkpOgogICAg"
    "ICAgICAgICBwYXRoc1trZXldID0gc3RyKGRlZmF1bHRfcGF0aCkKICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBn"
    "b29nbGVfY2ZnID0gQ0ZHLnNldGRlZmF1bHQoImdvb2dsZSIsIHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdl"
    "dCgiZ29vZ2xlIiwgc3RyKF9ERUZBVUxUX1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0cihnb29n"
    "bGVfcm9vdCAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290"
    "IC8gInRva2VuLmpzb24iKQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSku"
    "c3RyaXAoKQogICAgdG9rZW5fdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tlbiIsICIiKSkuc3RyaXAoKQogICAgaWYg"
    "KG5vdCBjcmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVkc192YWwgYW5kICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIg"
    "aW4gY3JlZHNfdmFsKToKICAgICAgICBnb29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVmYXVsdF9jcmVkcwogICAgICAg"
    "IGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3QgdG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBkZWZh"
    "dWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29uZmlnKENG"
    "RykKCmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQgYSBwYXRoIGZyb20g"
    "Q0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBw"
    "YXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAgICB2YWx1ZSA9IHBhdGhzLmdldChrZXkpCiAgICBpZiB2YWx1ZToKICAg"
    "ICAgICByZXR1cm4gUGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZh"
    "bGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAgcmV0dXJuIGZhbGxiYWNrCiAgICBy"
    "ZXR1cm4gU0NSSVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKQoKIyDilIDilIAgQ09MT1IgQ09OU1RB"
    "TlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1BUlksIENfU0VDT05EQVJZLCBD"
    "X0FDQ0VOVCwgQ19CRywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElNIGFyZSBpbmplY3RlZCBhdCB0"
    "aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIuCiMgRXZlcnl0aGluZyBiZWxvdyBpcyBkZXJpdmVkIGZyb20g"
    "dGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoKIyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xvcnMgdG8gbmFt"
    "ZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRoZSBVSQpDX0NSSU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAgICMgbWFp"
    "biBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMsIGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0gPSBDX1BSSU1BUlkgKyAiODgi"
    "ICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0bGUgYm9yZGVycwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMg"
    "bWFpbiBsYWJlbC90ZXh0L0FJIG91dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGlt"
    "IHNlY29uZGFyeQpDX0dPTERfQlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMgZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpD"
    "X1NJTFZFUiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMgc2Vjb25kYXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNf"
    "U0lMVkVSX0RJTSAgPSBDX1RFWFRfRElNICsgIjg4IiAgIyBkaW0gc2Vjb25kYXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENf"
    "QkcgICAgICAgICAgICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAg"
    "ICAgID0gQ19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAgICA9IENfUEFORUwg"
    "ICAgICAgICAgICAjIHRlcnRpYXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkxPT0QgICAgICAg"
    "PSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBzdGF0ZXMsIGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAgICAg"
    "PSAnIzg4NTVjYycgICAgICAgICAgIyBTWVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBMRV9ESU0gID0gJyMy"
    "YTA1MmEnICAgICAgICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0YWE2NicgICAg"
    "ICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4Y2MnICAgICAgICAg"
    "ICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNhbAoKIyBGb250IGhlbHBlciDigJQgZXh0cmFjdHMgcHJpbWFyeSBmb250IG5h"
    "bWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlfRk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgpLnN0"
    "cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24gcmVjb3JkIGNoaXBzKQpFTU9USU9O"
    "X0NPTE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAg"
    "Q19HT0xELAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6"
    "ICAgICAgQ19HT0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFuaWNrZWQiOiAgIENfQ1JJTVNPTiwKICAg"
    "ICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2NrZWQiOiAgICBDX0NSSU1TT04sCiAgICAiY2hlYXRtb2RlIjog"
    "IENfQ1JJTVNPTiwKICAgICJjb25jZXJuZWQiOiAgIiNjYzY2MjIiLAogICAgInNhZCI6ICAgICAgICAiI2NjNjYyMiIsCiAg"
    "ICAiaHVtaWxpYXRlZCI6ICIjY2M2NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjog"
    "ICBDX1BVUlBMRSwKICAgICJzdXNwaWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENfUFVSUExFLAogICAg"
    "ImZvY3VzZWQiOiAgICBDX1NJTFZFUiwKICAgICJhbGVydCI6ICAgICAgQ19TSUxWRVIsCiAgICAibmV1dHJhbCI6ICAgIENf"
    "VEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09SQVRJVkUgQ09OU1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlz"
    "IHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVT"
    "CgojIEZhY2UgaW1hZ2UgbWFwIOKAlCBwcmVmaXggZnJvbSBGQUNFX1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0"
    "aHMuZmFjZXMKRkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklY"
    "fV9OZXV0cmFsLnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVydC5wbmciLAogICAgImZvY3Vz"
    "ZWQiOiAgICBmIntGQUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1f"
    "U211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIsCiAgICAic2FkIjog"
    "ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQiOiAgIGYie0ZBQ0VfUFJFRklY"
    "fV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBmIntGQUNFX1BSRUZJWH1fSW1wcmVzc2VkLnBuZyIsCiAgICAi"
    "dmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJFRklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxpYXRlZCI6IGYie0ZBQ0VfUFJF"
    "RklYfV9IdW1pbGlhdGVkLnBuZyIsCiAgICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNpb3VzLnBuZyIs"
    "CiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0bW9kZSI6ICBmIntG"
    "QUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBmIntGQUNFX1BSRUZJWH1fQW5ncnkucG5n"
    "IiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYi"
    "e0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBuZyIsCiAgICAiaGFwcHkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmci"
    "LAogICAgImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZB"
    "Q0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAgZiJ7RkFDRV9QUkVGSVh9X0VudmlvdXMucG5n"
    "IiwKfQoKU0VOVElNRU5UX0xJU1QgPSAoCiAgICAibmV1dHJhbCwgYWxlcnQsIGZvY3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwg"
    "c2FkLCByZWxpZXZlZCwgaW1wcmVzc2VkLCAiCiAgICAidmljdG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNr"
    "ZWQsIGFuZ3J5LCBwbG90dGluZywgc2hvY2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZsdXN0ZXJlZCwgZW52aW91cyIK"
    "KQoKIyDilIDilIAgU1lTVEVNIFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBm"
    "aWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRfQkFTRSBpcyBhbHJl"
    "YWR5IGRlZmluZWQgYWJvdmUgZnJvbSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3QgcmVkZWZpbmUg"
    "aXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBTVFlMRVNIRUVUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9"
    "IGYiIiIKUU1haW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9yOiB7"
    "Q19HT0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRVGV4dEVkaXQge3sKICAgIGJhY2tncm91"
    "bmQtY29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAg"
    "ICBmb250LXNpemU6IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjoge0Nf"
    "Q1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAgICBjb2xvcjog"
    "e0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAg"
    "IGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxM3B4OwogICAgcGFkZGluZzogOHB4IDEy"
    "cHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07CiAgICBiYWNrZ3JvdW5k"
    "LWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1y"
    "YWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAg"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHggMjBweDsKICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQ"
    "dXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xE"
    "X0JSSUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNzZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAg"
    "IGJvcmRlci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7"
    "ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXItY29s"
    "b3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0aWNhbCB7ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAg"
    "d2lkdGg6IDZweDsKICAgIGJvcmRlcjogbm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2"
    "ZXJ0aWNhbDpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6OmFkZC1saW5lOnZl"
    "cnRpY2FsLCBRU2Nyb2xsQmFyOjpzdWItbGluZTp2ZXJ0aWNhbCB7ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6"
    "OnBhbmUge3sKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07"
    "Cn19ClFUYWJCYXI6OnRhYiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAg"
    "ICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFt"
    "aWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0K"
    "UVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0Nf"
    "R09MRH07CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRhYjpob3ZlciB7"
    "ewogICAgYmFja2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dPTERfRElNfTsKfX0KUVRhYmxlV2lkZ2V0IHt7"
    "CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OwogICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRf"
    "RkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9Owp9fQpRSGVhZGVyVmlldzo6c2Vj"
    "dGlvbiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9"
    "fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9G"
    "T05UX0ZBTUlMWX07Cn19ClFDb21ib0JveDo6ZHJvcC1kb3duIHt7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0JveCB7"
    "ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9fQpRU3BsaXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dy"
    "b3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgd2lkdGg6IDJweDsKfX0KIiIiCgojIOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNU"
    "UkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgQ3JlYXRlIGFsbCByZXF1aXJlZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAgQ2FsbGVkIG9uIHN0"
    "YXJ0dXAgYmVmb3JlIGFueXRoaW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFsc28gbWlncmF0"
    "ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRp"
    "cnMgPSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2VzIiksCiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAgIGNm"
    "Z19wYXRoKCJtZW1vcmllcyIpLAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIp"
    "LAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAgICAgICBjZmdfcGF0"
    "aCgiYmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSwK"
    "ICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0cyIsCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAg"
    "IGQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05MIGZpbGVzIGlm"
    "IHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZuYW1lIGlu"
    "ICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAgICAgICAgICAgICAi"
    "bGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVtb3J5X2Rp"
    "ciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNv"
    "ZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4gKCJzbF9zY2Fucy5q"
    "c29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3Qg"
    "ZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lv"
    "bnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpz"
    "b24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAgIGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9u"
    "cyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0"
    "YXRlLmpzb24iCiAgICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShz"
    "dGF0ZV9wYXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhf"
    "cGF0aC5leGlzdHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoeyJ2"
    "ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3Rh"
    "bF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAg"
    "IyBMZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxl"
    "cwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBO"
    "b25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJz"
    "aW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBO"
    "b25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAogICAgICAg"
    "ICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIsCiAgICB9CiAgICBw"
    "YXRoLndyaXRlX3RleHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKZGVmIF9taWdy"
    "YXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIKICAgIElmIG9sZCBEOlxcQUlcXE1vZGVsc1xcW0RlY2tOYW1l"
    "XV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdyYXRlIGZpbGVzIHRvIG5ldyBzdHJ1Y3R1cmUgc2lsZW50"
    "bHkuCiAgICAiIiIKICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2ZSB0byBtb2RlbCBwYXRoCiAgICBtb2Rl"
    "bF9wYXRoID0gUGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYgbm90IG1vZGVsX3BhdGguZXhpc3Rz"
    "KCk6CiAgICAgICAgcmV0dXJuCiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFyZW50IC8gZiJ7REVDS19OQU1FfV9NZW1v"
    "cmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwog"
    "ICAgICAgIChvbGRfcm9vdCAvICJtZW1vcmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJt"
    "ZW1vcmllcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAgICAgY2ZnX3Bh"
    "dGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFza3MuanNvbmwiLCAg"
    "ICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8g"
    "InN0YXRlLmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAg"
    "ICAgKG9sZF9yb290IC8gImluZGV4Lmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJpbmRl"
    "eC5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wi"
    "KSAvICJzbF9zY2Fucy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29ubCIsICAgICAgICAg"
    "Y2ZnX3BhdGgoInNsIikgLyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0"
    "b2tlbi5qc29uIiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsidG9rZW4iXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJjb25m"
    "aWciIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBQYXRoKENGR1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291"
    "bmRzIiAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIpLAogICAgXQoK"
    "ICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAgICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRzdC5leGlz"
    "dHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4"
    "aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIo"
    "c3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoK"
    "ICAgICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2ZhY2VzID0gb2xkX3Jvb3QgLyAiRmFjZXMiCiAgICBuZXdfZmFj"
    "ZXMgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2ZhY2VzLmV4aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xk"
    "X2ZhY2VzLmdsb2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19mYWNlcyAvIGltZy5uYW1lCiAgICAgICAgICAg"
    "IGlmIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHNo"
    "dXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoaW1nKSwgc3RyKGRzdCkpCiAgICAgICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRh"
    "dGV0aW1lLm5vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFsdWU6IHN0"
    "cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgaWYgbm90IHZhbHVlOgogICAgICAgIHJldHVybiBOb25lCiAgICB2YWx1"
    "ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBpZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICBy"
    "ZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAg"
    "ICAgICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "IHJldHVybiBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBsZV0gPSBzZXQoKQoKCmRlZiBf"
    "bG9jYWxfdHppbmZvKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbyBvciB0aW1lem9u"
    "ZS51dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkK"
    "CgpkZWYgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICBp"
    "ZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3QgaXNpbnN0YW5jZShkdF92YWx1ZSwg"
    "ZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9sb2NhbF90emluZm8oKQogICAgaWYgZHRf"
    "dmFsdWUudHppbmZvIGlzIE5vbmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLnJlcGxhY2UodHppbmZvPWxvY2Fs"
    "X3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0KQogICAgICAgIGlmIGtleSBub3QgaW4gX0RBVEVUSU1FX05P"
    "Uk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICAgICAgZiJbREFURVRJTUVd"
    "W0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5l"
    "cmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xP"
    "R0dFRC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3JtYWxpemVkID0gZHRfdmFsdWUuYXN0aW1l"
    "em9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIoZHRfdmFsdWUudHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIs"
    "IGNvbnRleHQsIGR0X3R6X25hbWUpCiAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBh"
    "bmQgZHRfdHpfbmFtZSBub3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAg"
    "ICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmcm9tIHtkdF90el9u"
    "YW1lfSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAg"
    "KQogICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQK"
    "CgpkZWYgcGFyc2VfaXNvX2Zvcl9jb21wYXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9ybWFs"
    "aXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tf"
    "ZHVlX3NvcnRfa2V5KHRhc2s6IGRpY3QpOgogICAgZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5n"
    "ZXQoImR1ZV9hdCIpIG9yICh0YXNrIG9yIHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVl"
    "IGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICgxLCBkYXRldGltZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkK"
    "ICAgIHJldHVybiAoMCwgZHVlLmFzdGltZXpvbmUodGltZXpvbmUudXRjKSwgKCh0YXNrIG9yIHt9KS5nZXQoInRleHQiKSBv"
    "ciAiIikubG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9uKHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9"
    "IG1heCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCByZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJl"
    "bSA9IGRpdm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9kKHJlbSwgNjApCiAgICBwYXJ0cyA9IFtd"
    "CiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5c31kIikKICAgIGlmIGhvdXJzOiAgIHBhcnRzLmFwcGVuZChm"
    "Intob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRzLmFwcGVuZChmInttaW51dGVzfW0iKQogICAgaWYgbm90IHBhcnRz"
    "OiBwYXJ0cy5hcHBlbmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10pCgojIOKUgOKUgCBNT09O"
    "IFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbiBtYXRoIOKA"
    "lCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01PT04gPSBkYXRlKDIwMDAsIDEs"
    "IDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAtPiB0dXBsZVtmbG9hdCwg"
    "c3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2ZyYWN0aW9uLCBwaGFzZV9uYW1lLCBpbGx1bWluYXRp"
    "b25fcGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9uOiAwLjAgPSBuZXcgbW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcg"
    "bW9vbiBhZ2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDigJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwgcGhh"
    "c2UuCiAgICAiIiIKICAgIGRheXMgID0gKGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9PTikuZGF5cwogICAgY3ljbGUg"
    "PSBkYXlzICUgX0xVTkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8"
    "IDEuODU6ICAgbmFtZSA9ICJORVcgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVND"
    "RU5UIgogICAgZWxpZiBjeWNsZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNsZSA8IDE0"
    "Ljc3OiAgbmFtZSA9ICJXQVhJTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09O"
    "IgogICAgZWxpZiBjeWNsZSA8IDIyLjE1OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45"
    "OTogIG5hbWUgPSAiTEFTVCBRVUFSVEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NF"
    "TlQiCgogICAgIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9vbgogICAgaWxs"
    "dW1pbmF0aW9uID0gKDEgLSBtYXRoLmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkgLyAyICogMTAwCiAgICByZXR1cm4gcGhh"
    "c2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkKCl9TVU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25l"
    "Cl9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTjogT3B0aW9uYWxbaW50XSA9IE5vbmUKX1NVTl9DQUNIRV9USU1FUzogdHVwbGVb"
    "c3RyLCBzdHJdID0gKCIwNjowMCIsICIxODozMCIpCgpkZWYgX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0dXBs"
    "ZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNvbHZlIGxhdGl0dWRlL2xvbmdpdHVkZSBmcm9tIHJ1bnRpbWUgY29u"
    "ZmlnIHdoZW4gYXZhaWxhYmxlLgogICAgRmFsbHMgYmFjayB0byB0aW1lem9uZS1kZXJpdmVkIGNvYXJzZSBkZWZhdWx0cy4K"
    "ICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9uZQogICAgdHJ5OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdl"
    "dCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgICAgICBmb3Iga2V5IGluICgi"
    "bGF0aXR1ZGUiLCAibGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxhdCA9"
    "IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgICAgIGZvciBrZXkgaW4gKCJsb25naXR1"
    "ZGUiLCAibG9uIiwgImxuZyIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAgICAgICBsb24g"
    "PSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgbGF0ID0gTm9uZQogICAgICAgIGxvbiA9IE5vbmUKCiAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6"
    "b25lKCkKICAgIHR6X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkKICAgIHR6X29mZnNl"
    "dF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKCiAgICBpZiBsb24gaXMgTm9uZToKICAgICAg"
    "ICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIHR6X29mZnNldF9ob3VycyAqIDE1LjApKQoKICAgIGlmIGxhdCBpcyBO"
    "b25lOgogICAgICAgIHR6X25hbWUgPSBzdHIobm93X2xvY2FsLnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50ID0g"
    "YW55KHRva2VuIGluIHR6X25hbWUgZm9yIHRva2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lmaWMvQXVja2xhbmQiLCAiQW1l"
    "cmljYS9TYW50aWFnbyIpKQogICAgICAgIGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0g"
    "bWF4KC02Ni4wLCBtaW4oNjYuMCwgbGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgbG9uKSkKICAgIHJl"
    "dHVybiBsYXQsIGxvbgoKZGVmIF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9jYWxfZGF5OiBkYXRlLCBsYXRpdHVkZTog"
    "ZmxvYXQsIGxvbmdpdHVkZTogZmxvYXQsIHN1bnJpc2U6IGJvb2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEt"
    "c3R5bGUgc3VucmlzZS9zdW5zZXQgc29sdmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJvbSBtaWRuaWdodC4iIiIKICAg"
    "IG4gPSBsb2NhbF9kYXkudGltZXR1cGxlKCkudG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0"
    "ID0gbiArICgoNiAtIGxuZ19ob3VyKSAvIDI0LjApIGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxuZ19ob3VyKSAvIDI0"
    "LjApCgogICAgTSA9ICgwLjk4NTYgKiB0KSAtIDMuMjg5CiAgICBMID0gTSArICgxLjkxNiAqIG1hdGguc2luKG1hdGgucmFk"
    "aWFucyhNKSkpICsgKDAuMDIwICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9IEwg"
    "JSAzNjAuMAoKICAgIFJBID0gbWF0aC5kZWdyZWVzKG1hdGguYXRhbigwLjkxNzY0ICogbWF0aC50YW4obWF0aC5yYWRpYW5z"
    "KEwpKSkpCiAgICBSQSA9IFJBICUgMzYwLjAKICAgIExfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihMIC8gOTAuMCkpICogOTAu"
    "MAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihSQSAvIDkwLjApKSAqIDkwLjAKICAgIFJBID0gKFJBICsgKExfcXVh"
    "ZHJhbnQgLSBSQV9xdWFkcmFudCkpIC8gMTUuMAoKICAgIHNpbl9kZWMgPSAwLjM5NzgyICogbWF0aC5zaW4obWF0aC5yYWRp"
    "YW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGguYXNpbihzaW5fZGVjKSkKCiAgICB6ZW5pdGggPSA5MC44MzMK"
    "ICAgIGNvc19oID0gKG1hdGguY29zKG1hdGgucmFkaWFucyh6ZW5pdGgpKSAtIChzaW5fZGVjICogbWF0aC5zaW4obWF0aC5y"
    "YWRpYW5zKGxhdGl0dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpCiAgICBp"
    "ZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBpZiBzdW5yaXNlOgogICAg"
    "ICAgIEggPSAzNjAuMCAtIG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAgZWxzZToKICAgICAgICBIID0gbWF0"
    "aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89IDE1LjAKCiAgICBUID0gSCArIFJBIC0gKDAuMDY1NzEgKiB0"
    "KSAtIDYuNjIyCiAgICBVVCA9IChUIC0gbG5nX2hvdXIpICUgMjQuMAoKICAgIGxvY2FsX29mZnNldF9ob3VycyA9IChkYXRl"
    "dGltZS5ub3coKS5hc3RpbWV6b25lKCkudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLyAz"
    "NjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBsb2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAgcmV0dXJuIGxvY2Fs"
    "X2hvdXIgKiA2MC4wCgpkZWYgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKG1pbnV0ZXNfZnJvbV9taWRuaWdodDogT3B0aW9u"
    "YWxbZmxvYXRdKSAtPiBzdHI6CiAgICBpZiBtaW51dGVzX2Zyb21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1cm4g"
    "Ii0tOi0tIgogICAgbWlucyA9IGludChyb3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAlICgyNCAqIDYwKQogICAgaGgs"
    "IG1tID0gZGl2bW9kKG1pbnMsIDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRl"
    "PW1tLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4g"
    "dHVwbGVbc3RyLCBzdHJdOgogICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJpc2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBk"
    "YXRlICsgdGltZXpvbmUgYW5kIG9wdGlvbmFsCiAgICBydW50aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2"
    "YWlsYWJsZS4KICAgIENhY2hlZCBwZXIgbG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0LgogICAgIiIiCiAgICBnbG9i"
    "YWwgX1NVTl9DQUNIRV9EQVRFLCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3df"
    "bG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRhdGUoKQogICAgdHpf"
    "b2Zmc2V0X21pbiA9IGludCgobm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygp"
    "IC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FDSEVfREFURSA9PSB0b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID09"
    "IHR6X29mZnNldF9taW46CiAgICAgICAgcmV0dXJuIF9TVU5fQ0FDSEVfVElNRVMKCiAgICB0cnk6CiAgICAgICAgbGF0LCBs"
    "b24gPSBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpCiAgICAgICAgc3VucmlzZV9taW4gPSBfY2FsY19zb2xhcl9ldmVu"
    "dF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1UcnVlKQogICAgICAgIHN1bnNldF9taW4gPSBfY2FsY19zb2xh"
    "cl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1GYWxzZSkKICAgICAgICBpZiBzdW5yaXNlX21pbiBp"
    "cyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiU29sYXIgZXZlbnQg"
    "dW5hdmFpbGFibGUgZm9yIHJlc29sdmVkIGNvb3JkaW5hdGVzIikKICAgICAgICB0aW1lcyA9IChfZm9ybWF0X2xvY2FsX3Nv"
    "bGFyX3RpbWUoc3VucmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3Vuc2V0X21pbikpCiAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIxODozMCIpCgogICAgX1NVTl9DQUNIRV9EQVRFID0gdG9k"
    "YXkKICAgIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9IHR6X29mZnNldF9taW4KICAgIF9TVU5fQ0FDSEVfVElNRVMgPSB0"
    "aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNZU1RFTSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBUaW1lLW9mLWRheSBiZWhhdmlvcmFsIHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19FTkFCTEVEPVRydWUu"
    "CiMgSW5qZWN0ZWQgaW50byBzeXN0ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRpb24gY2FsbC4KClZBTVBJUkVfU1RBVEVT"
    "OiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAiV0lUQ0hJTkcgSE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAgImNv"
    "bG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjogICAgIHsiaG91cnMiOiB7MSwy"
    "LDN9LCAgICAgICAgImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5H"
    "Ijp7ImhvdXJzIjogezQsNX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6IDAuN30sCiAgICAi"
    "RE9STUFOVCI6ICAgICAgICB7ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dl"
    "ciI6IDAuMn0sCiAgICAiUkVTVExFU1MgU0xFRVAiOiB7ImhvdXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVY"
    "VF9ESU0sICAgICJwb3dlciI6IDAuM30sCiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJzIjogezE2LDE3fSwgICAgICAg"
    "ICJjb2xvciI6IENfR09MRF9ESU0sICAgICJwb3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7ImhvdXJzIjog"
    "ezE4LDE5LDIwLDIxfSwgICJjb2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAiSFVOVElORyI6ICAg"
    "ICAgICB7ImhvdXJzIjogezIyLDIzfSwgICAgICAgICJjb2xvciI6IENfQ1JJTVNPTiwgICAgICJwb3dlciI6IDEuMH0sCn0K"
    "CmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgpIC0+IHN0cjoKICAgICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRl"
    "IG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5ob3VyCiAgICBmb3Igc3RhdGVf"
    "bmFtZSwgZGF0YSBpbiBWQU1QSVJFX1NUQVRFUy5pdGVtcygpOgogICAgICAgIGlmIGggaW4gZGF0YVsiaG91cnMiXToKICAg"
    "ICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJldHVybiAiRE9STUFOVCIKCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZV9j"
    "b2xvcihzdGF0ZTogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gVkFNUElSRV9TVEFURVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJj"
    "b2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJl"
    "dHVybiB7CiAgICAgICAgIldJVENISU5HIEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBh"
    "c3Npc3QgcmlnaHQgbm93LiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1"
    "c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJTkciOiBmIntERUNL"
    "X05BTUV9IGlzIGF0dGVudGl2ZSBhbmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAgICJET1JNQU5U"
    "IjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUu"
    "IiwKICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiByZS1l"
    "bmdhZ2UgaW1tZWRpYXRlbHkuIiwKICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWlu"
    "ZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFN"
    "RX0gaXMgZnVsbHkgYWN0aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYi"
    "e0RFQ0tfTkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Npbmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoK"
    "CmRlZiBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCku"
    "Z2V0KCJBSV9TVEFURV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92"
    "aWRlZC5rZXlzKCkpID09IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBkaWN0W3N0ciwgc3Ry"
    "XSA9IHt9CiAgICAgICAgZm9yIGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6CiAgICAgICAgICAgIHZhbCA9IHByb3Zp"
    "ZGVkLmdldChrZXkpCiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0cmlwKCk6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAgICAgICAgICAgY2xlYW5ba2V5"
    "XSA9ICIgIi5qb2luKHZhbC5zdHJpcCgpLnNwbGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICByZXR1cm4gX25ldXRy"
    "YWxfc3RhdGVfZ3JlZXRpbmdzKCkKCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBC"
    "dWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5q"
    "ZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5lcmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVz"
    "aC4KICAgICIiIgogICAgaWYgbm90IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0g"
    "Z2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgcGhhc2UsIG1vb25fbmFtZSwgaWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBu"
    "b3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQoKICAgIHN0YXRlX2ZsYXZvcnMgPSBfc3RhdGVfZ3JlZXRp"
    "bmdzX21hcCgpCiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3JzLmdldChzdGF0ZSwgIiIpCgogICAgcmV0dXJuICgKICAgICAg"
    "ICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4iCiAgICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7"
    "Zmxhdm9yfVxuIgogICAgICAgIGYiTW9vbjoge21vb25fbmFtZX0gKHtpbGx1bX0lIGlsbHVtaW5hdGVkKS5cbiIKICAgICAg"
    "ICBmIlJlc3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5jZSB0aGVzZSBicmFja2V0"
    "cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiMgUHJvY2VkdXJhbCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5kIHByb2ZpbGVzLgojIE5v"
    "IGV4dGVybmFsIGF1ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBi"
    "dWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sgKHN1cHBvcnRz"
    "IFdBViBhbmQgTVAzKS4KCl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAt"
    "PiBmbG9hdDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJlcTog"
    "ZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0x"
    "LjAKCmRlZiBfc2F3dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVx"
    "ICogdCkgJSAxLjApIC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19yOiBmbG9h"
    "dCwKICAgICAgICAgZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAoc2luZV9yICogX3NpbmUo"
    "ZnJlcSwgdCkgKwogICAgICAgICAgICBzcXVhcmVfciAqIF9zcXVhcmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAq"
    "IF9zYXd0b290aChmcmVxLCB0KSkKCmRlZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAogICAgICAgICAgICAgIGF0"
    "dGFja19mcmFjOiBmbG9hdCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykgLT4gZmxv"
    "YXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBvcyA9IGkgLyBtYXgoMSwgdG90YWwp"
    "CiAgICBpZiBwb3MgPCBhdHRhY2tfZnJhYzoKICAgICAgICByZXR1cm4gcG9zIC8gYXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9z"
    "ID4gKDEgLSByZWxlYXNlX2ZyYWMpOgogICAgICAgIHJldHVybiAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVy"
    "biAxLjAKCmRlZiBfd3JpdGVfd2F2KHBhdGg6IFBhdGgsIGF1ZGlvOiBsaXN0W2ludF0pIC0+IE5vbmU6CiAgICBwYXRoLnBh"
    "cmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3"
    "IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwgMiwgX1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJl"
    "c3NlZCIpKQogICAgICAgIGZvciBzIGluIGF1ZGlvOgogICAgICAgICAgICBmLndyaXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8"
    "aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50OgogICAgcmV0dXJuIG1heCgtMzI3NjcsIG1pbigzMjc2Nywg"
    "aW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBNT1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVzCiMgVHdvIG5vdGVz"
    "OiByb290IOKGkiBtaW5vciB0aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhlZHJhbCByZXNvbmFuY2UuCiMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0"
    "ZV9tb3JnYW5uYV9hbGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJlbGwg"
    "4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAgIFNvdW5kcyBsaWtl"
    "IGEgc2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBub3RlcyA9"
    "IFsKICAgICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQgZmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45KSwg"
    "ICMgRiM0IOKAlCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAgYXVkaW8g"
    "PSBbXQogICAgZm9yIGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBs"
    "ZW5ndGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQog"
    "ICAgICAgICAgICAjIFB1cmUgc2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3CiAgICAgICAgICAgIHZh"
    "bCA9IF9zaW5lKGZyZXEsIHQpICogMC43CiAgICAgICAgICAgICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZvciByaWNobmVz"
    "cwogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIHZhbCArPSBfc2lu"
    "ZShmcmVxICogMy4wLCB0KSAqIDAuMDUKICAgICAgICAgICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGll"
    "cyBzbG93bHkKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNl"
    "X2ZyYWM9MC43KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICAgICAgIyBC"
    "cmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4x"
    "KSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU1RBUlRV"
    "UCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3JkIHJlc29sdXRpb24KIyBUaHJlZSBub3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNo"
    "b3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8OpYW5jZSBiZWdpbm5pbmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwKHBhdGg6"
    "IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2aW5nIHVwd2FyZCDigJQgbGlrZSBhIHPD"
    "qWFuY2UgYmVnaW5uaW5nLgogICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFsIG5vdGUgaGVsZCBhbmQgZmFkZWQp"
    "LgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoMjIwLjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYxLjYzLCAw"
    "LjI1KSwgICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBFNCAoZmlmdGgpCiAgICAgICAg"
    "KDQ0MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChm"
    "cmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVu"
    "Z3RoKQogICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90"
    "YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAq"
    "IDAuNgogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAgICAgaWYgaXNfZmlu"
    "YWw6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2Vf"
    "ZnJhYz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0"
    "dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICog"
    "ZW52ICogMC40NSkpCiAgICAgICAgaWYgbm90IGlzX2ZpbmFsOgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NB"
    "TVBMRV9SQVRFICogMC4wNSkpOgogICAgICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgs"
    "IGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBNT1JHQU5OQSBJRExFIENISU1FIOKAlCBzaW5nbGUgbG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50"
    "IGNodXJjaCBiZWxsLiBTaWduYWxzIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0"
    "aDogUGF0aCkgLT4gTm9uZToKICAgICIiIlNpbmdsZSBzb2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2Vu"
    "Y2UgaW4gdGhlIGRhcmsuIiIiCiAgICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBsZW5ndGggPSAxLjIKICAgIHRvdGFsID0g"
    "aW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAg"
    "ICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41CiAgICAgICAgdmFs"
    "ICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tf"
    "ZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAu"
    "MykpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAodGhlIGRldmlsJ3MgaW50"
    "ZXJ2YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVhbC4KIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21v"
    "cmdhbm5hX2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIzICsg"
    "RjQgcGxheWVkIHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2EnLiBCcmllZiBhbmQgaGFyc2gg"
    "Y29tcGFyZWQgdG8gaGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVx"
    "X2IgPSAzNDkuMjMgICMgRjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBsZW5ndGggPSAwLjQK"
    "ICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdl"
    "KHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRh"
    "bmVvdXNseSDigJQgY3JlYXRlcyBkaXNzb25hbmNlCiAgICAgICAgdmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwog"
    "ICAgICAgICAgICAgICBfc3F1YXJlKGZyZXFfYiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAy"
    "LjAsIHQpICogMC4xKQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFz"
    "ZV9mcmFjPTAuNCkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICBfd3JpdGVfd2F2"
    "KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKIyBNT1JHQU5OQSBTSFVURE9XTiDigJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ug"
    "b2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRyYXdzLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRv"
    "d24ocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKGkiBDNCDihpIgQTMuIFByZXNl"
    "bmNlIHdpdGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAj"
    "IEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAjIEM0CiAgICAgICAg"
    "KDIyMC4wLCAgMC44KSwgICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3Ig"
    "aSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUg"
    "KiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDMs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0gbGVuKG5vdGVzKS0xIGVsc2Ug"
    "MC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8gaW4g"
    "cmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVf"
    "d2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGdldF9zb3VuZF9wYXRoKG5hbWU6IHN0cikgLT4gUGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikg"
    "LyBmIntTT1VORF9QUkVGSVh9X3tuYW1lfS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6CiAgICAiIiJH"
    "ZW5lcmF0ZSBhbnkgbWlzc2luZyBzb3VuZCBXQVYgZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAg"
    "ICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdl"
    "ZAogICAgICAgICJzdGFydHVwIjogIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2Vu"
    "ZXJhdGVfbW9yZ2FubmFfaWRsZSwKICAgICAgICAiZXJyb3IiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAg"
    "ICAic2h1dGRvd24iOiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93biwKICAgIH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4g"
    "Z2VuZXJhdG9ycy5pdGVtcygpOgogICAgICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBw"
    "YXRoLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU09VTkRdW1dBUk5dIEZhaWxlZCB0byBn"
    "ZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3VuZChuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBs"
    "YXkgYSBuYW1lZCBzb3VuZCBub24tYmxvY2tpbmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIgZmlyc3QgKGNyb3NzLXBsYXRm"
    "b3JtLCBXQVYgKyBNUDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgogICAgRmFsbHMgYmFjayB0"
    "byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBub3QgQ0ZHWyJzZXR0aW5ncyJd"
    "LmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5h"
    "bWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBpZiBQWUdBTUVfT0s6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAgICAgICAgICAgIHNvdW5k"
    "LnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5QbGF5U291bmQoc3RyKHBhdGgp"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJTEVOQU1FIHwgd2luc291bmQuU05EX0FT"
    "WU5DKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAg"
    "dHJ5OgogICAgICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKIyDi"
    "lIDilIAgREVTS1RPUCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBi"
    "b29sOgogICAgIiIiCiAgICBDcmVhdGUgYSBkZXNrdG9wIHNob3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5"
    "dGhvbncuZXhlLgogICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90"
    "IFdJTjMyX09LOgogICAgICAgIHJldHVybiBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAv"
    "ICJEZXNrdG9wIgogICAgICAgIHNob3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCgogICAgICAg"
    "ICMgcHl0aG9udyA9IHNhbWUgYXMgcHl0aG9uIGJ1dCBubyBjb25zb2xlIHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRo"
    "KHN5cy5leGVjdXRhYmxlKQogICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAg"
    "ICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253LmV4"
    "aXN0cygpOgogICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0g"
    "UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxsID0gd2luMzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2Ny"
    "aXB0LlNoZWxsIikKICAgICAgICBzYyA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzaG9ydGN1dF9wYXRoKSkKICAgICAg"
    "ICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQogICAgICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZicie2RlY2tf"
    "cGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRoLnBhcmVudCkKICAgICAgICBzYy5E"
    "ZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKCiAgICAgICAgIyBVc2UgbmV1dHJhbCBmYWNl"
    "IGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikgLyBmIntGQUNFX1BS"
    "RUZJWH1fTmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICAjIFdpbmRvd3Mg"
    "c2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCUIHNraXAgaWNvbiBpZiBubyAuaWNvCiAgICAgICAgICAgIHBh"
    "c3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICBwcmludChmIltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKICAgICAgICBy"
    "ZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ZGVmIHJlYWRfanNvbmwocGF0aDogUGF0aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1"
    "cm5zIGxpc3Qgb2YgZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAg"
    "ICBpZiBub3QgcmF3OgogICAgICAgIHJldHVybiBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGRhdGEgPSBqc29uLmxvYWRzKHJhdykKICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEg"
    "aWYgaXNpbnN0YW5jZSh4LCBkaWN0KV0KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICBp"
    "dGVtcyA9IFtdCiAgICBmb3IgbGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkK"
    "ICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9"
    "IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAgICAgICAg"
    "aXRlbXMuYXBwZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0"
    "dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pzb25sKHBhdGg6IFBhdGgsIG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVu"
    "ZCBvbmUgcmVjb3JkIHRvIGEgSlNPTkwgZmlsZS4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhp"
    "c3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmLndy"
    "aXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikKCmRlZiB3cml0ZV9qc29ubChwYXRoOiBQ"
    "YXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgIiIiT3ZlcndyaXRlIGEgSlNPTkwgZmlsZSB3aXRoIGEg"
    "bGlzdCBvZiByZWNvcmRzLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQog"
    "ICAgd2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZvciByIGluIHJlY29yZHM6"
    "CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikKCiMg4pSA4pSA"
    "IEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0aGUiLCJhbmQiLCJ0aGF0Iiwi"
    "d2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwid2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndv"
    "dWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQiLCJsaWtlIiwiYmVj"
    "YXVzZSIsIndoaWxlIiwiY291bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIsImRvZXMi"
    "LCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIsIm9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4iLCJh"
    "bHNvIiwic29tZSIsIm1vcmUiLCJsZXNzIiwib25seSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2Fp"
    "biIsInZlcnkiLCJtdWNoIiwicmVhbGx5IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxs"
    "IiwidG9sZCIsImlkZWEiLCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwKfQoKZGVm"
    "IGV4dHJhY3Rfa2V5d29yZHModGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxpc3Rbc3RyXToKICAgIHRva2VucyA9"
    "IFt0Lmxvd2VyKCkuc3RyaXAoIiAuLCE/OzonXCIoKVtde30iKSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCBy"
    "ZXN1bHQgPSBzZXQoKSwgW10KICAgIGZvciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NU"
    "T1BXT1JEUyBvciB0LmlzZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgog"
    "ICAgICAgICAgICBzZWVuLmFkZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAgaWYgbGVuKHJlc3Vs"
    "dCkgPj0gbGltaXQ6CiAgICAgICAgICAgIGJyZWFrCiAgICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUo"
    "dXNlcl90ZXh0OiBzdHIsIGFzc2lzdGFudF90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAi"
    "ICIgKyBhc3Npc3RhbnRfdGV4dCkubG93ZXIoKQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIs"
    "ImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4ZWQiLCJyZXNvbHZl"
    "ZCIsInNvbHV0aW9uIiwid29ya2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJyZXNvbHV0aW9uIgogICAgICAgIHJldHVy"
    "biAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicmVtaW5kIiwidGltZXIiLCJhbGFybSIsInRhc2siKSk6"
    "CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImlkZWEiLCJjb25jZXB0Iiwid2hh"
    "dCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRlYSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHgg"
    "aW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIpKToKICAgICAgICByZXR1cm4gInByZWZl"
    "cmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1MgMSBDT01QTEVURSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lkZ2V0LCBN"
    "b29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1waXJlU3RhdGVTdHJp"
    "cCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1Mg"
    "MjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2su"
    "CiMKIyBXaWRnZXRzIGRlZmluZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwg"
    "YmFyIHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1"
    "c2VkL3RvdGFsIEdCKQojICAgU3BoZXJlV2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBN"
    "QU5BCiMgICBNb29uV2lkZ2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVt"
    "b3Rpb25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdl"
    "dCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMgICBWYW1waXJlU3RhdGVTdHJpcCAgICDi"
    "gJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVzIGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdy"
    "YXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRvZ2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDi"
    "gJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJ"
    "REdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgR2F1Z2VXaWRnZXQoUVdpZGdl"
    "dCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4KICAgIFNob3dz"
    "OiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3AtcmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9y"
    "IHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMgdmFsdWUgYXBwcm9hY2hlcyBtYXguCiAgICBT"
    "aG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAg"
    "c2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0"
    "ID0gMTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVu"
    "aXQgICAgID0gdW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNv"
    "bG9yCiAgICAgICAgc2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNl"
    "bGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYu"
    "c2V0TWF4aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIg"
    "PSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxv"
    "YXQodmFsdWUpLCBzZWxmLm1heF92YWwpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYg"
    "bm90IGF2YWlsYWJsZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5Ogog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWls"
    "YWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxh"
    "eSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhp"
    "bnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBC"
    "YWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQogICAgICAgIHAuc2V0UGVu"
    "KFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCgwLCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFi"
    "ZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9O"
    "VCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAg"
    "ICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSBDX1RF"
    "WFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAg"
    "ICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5"
    "KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIK"
    "ICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAg"
    "IHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAg"
    "IGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVl"
    "IC8gc2VsZi5tYXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAg"
    "ICAgICAgICAgIyBDb2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZy"
    "YWMgPiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcs"
    "IGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9y"
    "KGJhcl9jb2xvcikuZGFya2VyKDE2MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9y"
    "KSkKICAgICAgICAgICAgcC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAg"
    "ICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3Mg"
    "ZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2"
    "ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZHJpdmVzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxm"
    "LnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZh"
    "bHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRpbC5kaXNrX3VzYWdl"
    "KHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJzdHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInRv"
    "dGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBl"
    "cmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MK"
    "ICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwogICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykp"
    "CiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRl"
    "ZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAu"
    "c2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0"
    "aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKA"
    "lCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBy"
    "b3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0"
    "dGVyID0gZHJ2WyJsZXR0ZXIiXQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAg"
    "PSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0gZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAg"
    "ICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4xZn0ve3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQ"
    "ZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdo"
    "dC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAgICAgIyBCYXIKICAg"
    "ICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95ID0geSArIDE1CiAgICAgICAgICAgIGJhcl93ID0gdyAtIDEy"
    "CiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9o"
    "LCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJh"
    "d1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBp"
    "bnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBwY3QgPiAwLjkgZWxz"
    "ZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95"
    "LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9y"
    "KS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAg"
    "ICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAg"
    "ICAgIHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "IiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoK"
    "CiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNw"
    "aGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxPT0Qg"
    "KHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZpbGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZm"
    "ZWN0LiBMYWJlbCBiZWxvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVs"
    "OiBzdHIsCiAgICAgICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50"
    "PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9"
    "IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0g"
    "Y29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAgID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYu"
    "X2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxs"
    "KHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9m"
    "aWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxh"
    "YmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAg"
    "ICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlh"
    "bGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcs"
    "IGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAg"
    "ICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuc2V0QnJ1"
    "c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciArIDMsIGN5IC0gciArIDMsIHIg"
    "KiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29s"
    "b3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdF"
    "bGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAg"
    "IGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9wYXRoID0gUVBh"
    "aW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAt"
    "IHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAg"
    "ICAgICAgICAgZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20gUHlT"
    "aWRlNi5RdENvcmUgaW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3Rv"
    "cF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkK"
    "ICAgICAgICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3Bh"
    "dGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAg"
    "ICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBl"
    "ZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAg"
    "ZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAg"
    "ICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9y"
    "QXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAgICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQ"
    "ZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAy"
    "KQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBw"
    "LnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwg"
    "Y3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9BIG92ZXJsYXkKICAgICAgICBpZiBub3Qgc2VsZi5fYXZhaWxh"
    "YmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9u"
    "dCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0g"
    "Ik4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0"
    "LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFiZWxfdGV4dCA9IChzZWxmLmxhYmVsIGlm"
    "IHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0"
    "X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAg"
    "cC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwg"
    "UUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpv"
    "bnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBsYWJlbF90"
    "ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAg"
    "ICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygp"
    "CiAgICAgICAgICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0"
    "KGN4IC0gcHcgLy8gMiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6"
    "CiAgICAiIiIKICAgIERyYXduIG1vb24gb3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZF"
    "TlRJT04gKG5vcnRoZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1"
    "bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5h"
    "dGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0CgogICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQg"
    "aWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAgICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19G"
    "TElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAgICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFw"
    "cGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5nCiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX3BoYXNlICAgICAgID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGwsIDEuMD1uZXcKICAgICAgICBzZWxmLl9u"
    "YW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAg"
    "ICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAg"
    "ICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAg"
    "ICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1tZWRpYXRlbHkKICAg"
    "ICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2Vs"
    "Zi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9zdW5fZGF0"
    "ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9u"
    "IG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0ZSgpIGRpcmVj"
    "dGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0"
    "ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVm"
    "IHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVt"
    "aW5hdGlvbiA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5k"
    "YXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2Fz"
    "eW5jKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAg"
    "ICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50"
    "aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4o"
    "dywgaCAtIDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoK"
    "ICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4"
    "KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFS"
    "X0NZQ0xFCiAgICAgICAgaXNfd2F4aW5nID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVs"
    "bCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAg"
    "ICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAy"
    "MTAsIDE4NSkpCiAgICAgICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAg"
    "ICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGlsbHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDi"
    "hpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9scyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBz"
    "aGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24g"
    "b2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNlbGYu"
    "X2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4wIC0gaWxsdW1fZnJhYwoKICAgICAg"
    "ICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFkb3cgTEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxs"
    "dW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxsaXBz"
    "ZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAgICAgICAg"
    "ICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193YXhpbmcgPSBub3QgaXNfd2F4"
    "aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAg"
    "ICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAg"
    "ICAjIFNoYWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAg"
    "ICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAg"
    "ICAgICAgICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxv"
    "YXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAy"
    "KSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNo"
    "YWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQoc2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cg"
    "PSBtb29uX3BhdGguaW50ZXJzZWN0ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFk"
    "b3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWlsIChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUg"
    "Z3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kg"
    "LSByICogMC4yKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGlu"
    "ZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBR"
    "Q29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5Q"
    "ZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVu"
    "KFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIs"
    "IHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1NJTFZF"
    "UikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZt"
    "ID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1lKQogICAgICAg"
    "IHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAgICAgICAgIyBJbGx1bWluYXRp"
    "b24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAg"
    "ICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UoaWxsdW1fc3RyKQog"
    "ICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0"
    "aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5f"
    "c3Vuc2V0fSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFk"
    "dmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAg"
    "IHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBw"
    "YW5lbC4KICAgIFNob3dzIGNvbG9yLWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0"
    "IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUgYm90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBq"
    "dXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJd"
    "XSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2Vs"
    "Zi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhl"
    "YWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAg"
    "ICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJv"
    "dHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoaGVh"
    "ZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFMIFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAg"
    "ICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYu"
    "X3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBm"
    "b250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQo"
    "bGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAg"
    "ICAgICAjIFNjcm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEo"
    "KQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0"
    "SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5"
    "c09mZikKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkK"
    "ICAgICAgICBzZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNl"
    "bGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0"
    "LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3Jv"
    "bGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoK"
    "ICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5k"
    "ZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21l"
    "dHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3Ry"
    "ZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAoZW1vdGlvbiwgdGltZXN0YW1wKSkKICAg"
    "ICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5fbWF4X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVi"
    "dWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlz"
    "dGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291"
    "bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYg"
    "aXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3Ig"
    "ZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAgICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1v"
    "dGlvbiwgQ19URVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3Rz"
    "fSIpCiAgICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZv"
    "bnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGlu"
    "ZzogMXB4IDRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xh"
    "eW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAog"
    "ICAgICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigp"
    "CiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1h"
    "Z2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5w"
    "bmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6"
    "CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9T"
    "YWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFDRV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRt"
    "b2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMg"
    "Zm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBs"
    "aXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1hcHBpbmdzIChsb3dl"
    "cmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9UT19FTU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAg"
    "ICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAiY2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIs"
    "IFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5l"
    "ZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYu"
    "c2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgz"
    "MDAsIHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAg"
    "U2NhbiBGYWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBl"
    "bW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5LgogICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZl"
    "ciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNf"
    "ZGlyLmV4aXN0cygpOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAg"
    "ICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAg"
    "cmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNFX1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9Dcnlpbmci"
    "CiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJz"
    "YWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAg"
    "ZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQoc3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAg"
    "IHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAgICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAgICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxm"
    "Ll9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoK"
    "ICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0"
    "cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2Vs"
    "Zi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAgIHByaW50KGYiW01JUlJPUl1bV0FSTl0g"
    "RmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcgbmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJu"
    "ZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9j"
    "YWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxlZCA9IHB4LnNj"
    "YWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAg"
    "ICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9u"
    "TW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAg"
    "ICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRp"
    "dXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAg"
    "UVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5f"
    "Y2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1"
    "cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJF"
    "IFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDeWNsZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIi"
    "IkdlbmVyaWMgY3ljbGUgdmlzdWFsaXphdGlvbiB3aWRnZXQgKGN1cnJlbnRseSBsdW5hci1waGFzZSBkcml2ZW4pLiIiIgoK"
    "CmNsYXNzIFZhbXBpcmVTdGF0ZVN0cmlwKFFXaWRnZXQpOgogICAgIiIiCiAgICBGdWxsLXdpZHRoIHN0YXR1cyBiYXIgc2hv"
    "d2luZzoKICAgICAgWyDinKYgVkFNUElSRV9TVEFURSAg4oCiICBISDpNTSAg4oCiICDimIAgU1VOUklTRSAg4pi9IFNVTlNF"
    "VCAg4oCiICBNT09OIFBIQVNFICBJTExVTSUgXQogICAgQWx3YXlzIHZpc2libGUsIG5ldmVyIGNvbGxhcHNlcy4KICAgIFVw"
    "ZGF0ZXMgZXZlcnkgbWludXRlIHZpYSBleHRlcm5hbCBRVGltZXIgY2FsbCB0byByZWZyZXNoKCkuCiAgICBDb2xvci1jb2Rl"
    "ZCBieSBjdXJyZW50IHZhbXBpcmUgc3RhdGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9ICJTVEFURSIK"
    "ICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0g"
    "IiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgog"
    "ICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAg"
    "ICAgc2VsZi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAgICBzZWxmLnNl"
    "dFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19"
    "OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBzZXRf"
    "bGFiZWwoc2VsZiwgbGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwgb3Ig"
    "IlNUQVRFIikuc3RyaXAoKS51cHBlcigpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5j"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQog"
    "ICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAg"
    "IHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVk"
    "dWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEg"
    "YmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFkIGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVy"
    "LnNpbmdsZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1U"
    "cnVlKS5zdGFydCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBn"
    "ZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgp"
    "LnN0cmZ0aW1lKCIlWCIpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAg"
    "ICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAg"
    "ICAgXywgc2VsZi5fbW9vbl9uYW1lLCBzZWxmLl9pbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICBzZWxmLnVwZGF0"
    "ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYp"
    "CiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGgg"
    "PSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19C"
    "RzIpKQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHNlbGYuX3N0YXRlKQogICAgICAg"
    "IHRleHQgPSAoCiAgICAgICAgICAgIGYi4pymICB7c2VsZi5fbGFiZWxfcHJlZml4fToge3NlbGYuX3N0YXRlfSAg4oCiICB7"
    "c2VsZi5fdGltZV9zdHJ9ICDigKIgICIKICAgICAgICAgICAgZiLimIAge3NlbGYuX3N1bnJpc2V9ICAgIOKYvSB7c2VsZi5f"
    "c3Vuc2V0fSAg4oCiICAiCiAgICAgICAgICAgIGYie3NlbGYuX21vb25fbmFtZX0gIHtzZWxmLl9pbGx1bTouMGZ9JSIKICAg"
    "ICAgICApCgogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDksIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAg"
    "ICBwLnNldFBlbihRQ29sb3Ioc3RhdGVfY29sb3IpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdHcg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZSh0ZXh0KQogICAgICAgIHAuZHJhd1RleHQoKHcgLSB0dykgLy8gMiwgaCAtIDcsIHRl"
    "eHQpCgogICAgICAgIHAuZW5kKCkKCgpjbGFzcyBNaW5pQ2FsZW5kYXJXaWRnZXQoUVdpZGdldCk6CiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZWFkZXIuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5wcmV2X2J0biA9IFFQdXNoQnV0dG9uKCI8PCIpCiAg"
    "ICAgICAgc2VsZi5uZXh0X2J0biA9IFFQdXNoQnV0dG9uKCI+PiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwgPSBRTGFiZWwo"
    "IiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAg"
    "ICAgICAgZm9yIGJ0biBpbiAoc2VsZi5wcmV2X2J0biwgc2VsZi5uZXh0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhl"
    "ZFdpZHRoKDM0KQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAg"
    "ICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMnB4OyIKICAgICAgICAgICAg"
    "KQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBi"
    "b3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBoZWFk"
    "ZXIuYWRkV2lkZ2V0KHNlbGYucHJldl9idG4pCiAgICAgICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLm1vbnRoX2xibCwgMSkK"
    "ICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubmV4dF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChoZWFkZXIp"
    "CgogICAgICAgIHNlbGYuY2FsZW5kYXIgPSBRQ2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0R3Jp"
    "ZFZpc2libGUoVHJ1ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFZlcnRpY2FsSGVhZGVyRm9ybWF0KFFDYWxlbmRhcldp"
    "ZGdldC5WZXJ0aWNhbEhlYWRlckZvcm1hdC5Ob1ZlcnRpY2FsSGVhZGVyKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0TmF2"
    "aWdhdGlvbkJhclZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmIlFDYWxlbmRhcldpZGdldCBRV2lkZ2V0e3thbHRlcm5hdGUtYmFja2dyb3VuZC1jb2xvcjp7Q19CRzJ9O319ICIKICAg"
    "ICAgICAgICAgZiJRVG9vbEJ1dHRvbnt7Y29sb3I6e0NfR09MRH07fX0gIgogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdl"
    "dCBRQWJzdHJhY3RJdGVtVmlldzplbmFibGVke3tiYWNrZ3JvdW5kOntDX0JHMn07IGNvbG9yOiNmZmZmZmY7ICIKICAgICAg"
    "ICAgICAgZiJzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjp7Q19DUklNU09OX0RJTX07IHNlbGVjdGlvbi1jb2xvcjp7Q19U"
    "RVhUfTsgZ3JpZGxpbmUtY29sb3I6e0NfQk9SREVSfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0"
    "cmFjdEl0ZW1WaWV3OmRpc2FibGVke3tjb2xvcjojOGI5NWExO319IgogICAgICAgICkKICAgICAgICBsYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuY2FsZW5kYXIpCgogICAgICAgIHNlbGYucHJldl9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5j"
    "YWxlbmRhci5zaG93UHJldmlvdXNNb250aCgpKQogICAgICAgIHNlbGYubmV4dF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJk"
    "YTogc2VsZi5jYWxlbmRhci5zaG93TmV4dE1vbnRoKCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5jdXJyZW50UGFnZUNoYW5n"
    "ZWQuY29ubmVjdChzZWxmLl91cGRhdGVfbGFiZWwpCiAgICAgICAgc2VsZi5fdXBkYXRlX2xhYmVsKCkKICAgICAgICBzZWxm"
    "Ll9hcHBseV9mb3JtYXRzKCkKCiAgICBkZWYgX3VwZGF0ZV9sYWJlbChzZWxmLCAqYXJncyk6CiAgICAgICAgeWVhciA9IHNl"
    "bGYuY2FsZW5kYXIueWVhclNob3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAg"
    "ICAgc2VsZi5tb250aF9sYmwuc2V0VGV4dChmIntkYXRlKHllYXIsIG1vbnRoLCAxKS5zdHJmdGltZSgnJUIgJVknKX0iKQog"
    "ICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfYXBwbHlfZm9ybWF0cyhzZWxmKToKICAgICAgICBiYXNl"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBiYXNlLnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAg"
    "ICAgc2F0dXJkYXkgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIHNhdHVyZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENf"
    "R09MRF9ESU0pKQogICAgICAgIHN1bmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc3VuZGF5LnNldEZvcmVncm91"
    "bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZX"
    "ZWVrLk1vbmRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vl"
    "ay5UdWVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVr"
    "LldlZG5lc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vl"
    "ay5UaHVyc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vl"
    "ay5GcmlkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsu"
    "U2F0dXJkYXksIHNhdHVyZGF5KQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZX"
    "ZWVrLlN1bmRheSwgc3VuZGF5KQoKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1v"
    "bnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBmaXJzdF9kYXkgPSBRRGF0ZSh5ZWFyLCBtb250aCwg"
    "MSkKICAgICAgICBmb3IgZGF5IGluIHJhbmdlKDEsIGZpcnN0X2RheS5kYXlzSW5Nb250aCgpICsgMSk6CiAgICAgICAgICAg"
    "IGQgPSBRRGF0ZSh5ZWFyLCBtb250aCwgZGF5KQogICAgICAgICAgICBmbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAg"
    "ICAgICB3ZWVrZGF5ID0gZC5kYXlPZldlZWsoKQogICAgICAgICAgICBpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TYXR1"
    "cmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAg"
    "ICAgICAgZWxpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TdW5kYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9y"
    "ZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICAgICAgc2VsZi5jYWxlbmRhci5zZXREYXRlVGV4dEZvcm1hdChk"
    "LCBmbXQpCgogICAgICAgIHRvZGF5X2ZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgdG9kYXlfZm10LnNldEZvcmVn"
    "cm91bmQoUUNvbG9yKCIjNjhkMzlhIikpCiAgICAgICAgdG9kYXlfZm10LnNldEJhY2tncm91bmQoUUNvbG9yKCIjMTYzODI1"
    "IikpCiAgICAgICAgdG9kYXlfZm10LnNldEZvbnRXZWlnaHQoUUZvbnQuV2VpZ2h0LkJvbGQpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXREYXRlVGV4dEZvcm1hdChRRGF0ZS5jdXJyZW50RGF0ZSgpLCB0b2RheV9mbXQpCgoKIyDilIDilIAgQ09MTEFQ"
    "U0lCTEUgQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIENvbGxhcHNpYmxlQmxvY2soUVdpZGdldCk6"
    "CiAgICAiIiIKICAgIFdyYXBwZXIgdGhhdCBhZGRzIGEgY29sbGFwc2UvZXhwYW5kIHRvZ2dsZSB0byBhbnkgd2lkZ2V0Lgog"
    "ICAgQ29sbGFwc2VzIGhvcml6b250YWxseSAocmlnaHR3YXJkKSDigJQgaGlkZXMgY29udGVudCwga2VlcHMgaGVhZGVyIHN0"
    "cmlwLgogICAgSGVhZGVyIHNob3dzIGxhYmVsLiBUb2dnbGUgYnV0dG9uIG9uIHJpZ2h0IGVkZ2Ugb2YgaGVhZGVyLgoKICAg"
    "IFVzYWdlOgogICAgICAgIGJsb2NrID0gQ29sbGFwc2libGVCbG9jaygi4p2nIEJMT09EIiwgU3BoZXJlV2lkZ2V0KC4uLikp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChibG9jaykKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDog"
    "c3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRo"
    "OiBpbnQgPSA5MCwKICAgICAgICAgICAgICAgICBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJl"
    "bnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggPSBtaW5fd2lk"
    "dGgKICAgICAgICBzZWxmLl9jb250ZW50ICAgPSBjb250ZW50CgogICAgICAgIG1haW4gPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIG1haW4uc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbWFpbi5zZXRTcGFjaW5nKDApCgog"
    "ICAgICAgICMgSGVhZGVyCiAgICAgICAgc2VsZi5faGVhZGVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5faGVhZGVyLnNl"
    "dEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExh"
    "eW91dChzZWxmLl9oZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwu"
    "c2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLl9sYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgc2VsZi5fbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4"
    "OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNl"
    "bGYuX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6"
    "ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBzZWxmLl9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2xibCkKICAgICAgICBobC5h"
    "ZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fYnRuKQoKICAgICAgICBtYWluLmFkZFdpZGdldChzZWxm"
    "Ll9oZWFkZXIpCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICAgICAgc2VsZi5fYXBwbHlfc3Rh"
    "dGUoKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5f"
    "ZXhwYW5kZWQKICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIF9hcHBseV9zdGF0ZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl9idG4uc2V0"
    "VGV4dCgiPCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAiPiIpCiAgICAgICAgaWYgc2VsZi5fZXhwYW5kZWQ6CiAgICAgICAg"
    "ICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lk"
    "dGgoMTY3NzcyMTUpICAjIHVuY29uc3RyYWluZWQKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIENvbGxhcHNlZDoganVz"
    "dCB0aGUgaGVhZGVyIHN0cmlwIChsYWJlbCArIGJ1dHRvbikKICAgICAgICAgICAgY29sbGFwc2VkX3cgPSBzZWxmLl9oZWFk"
    "ZXIuc2l6ZUhpbnQoKS53aWR0aCgpCiAgICAgICAgICAgIHNlbGYuc2V0Rml4ZWRXaWR0aChtYXgoNjAsIGNvbGxhcHNlZF93"
    "KSkKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwYXJlbnQgPSBzZWxmLnBhcmVudFdpZGdldCgpCiAg"
    "ICAgICAgaWYgcGFyZW50IGFuZCBwYXJlbnQubGF5b3V0KCk6CiAgICAgICAgICAgIHBhcmVudC5sYXlvdXQoKS5hY3RpdmF0"
    "ZSgpCgoKIyDilIDilIAgSEFSRFdBUkUgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IEhhcmR3YXJlUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRoZSBzeXN0ZW1zIHJpZ2h0IHBhbmVsIGNvbnRlbnRzLgog"
    "ICAgR3JvdXBzOiBzdGF0dXMgaW5mbywgZHJpdmUgYmFycywgQ1BVL1JBTSBnYXVnZXMsIEdQVS9WUkFNIGdhdWdlcywgR1BV"
    "IHRlbXAuCiAgICBSZXBvcnRzIGhhcmR3YXJlIGF2YWlsYWJpbGl0eSBpbiBEaWFnbm9zdGljcyBvbiBzdGFydHVwLgogICAg"
    "U2hvd3MgTi9BIGdyYWNlZnVsbHkgd2hlbiBkYXRhIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXR1cF91"
    "aSgpCiAgICAgICAgc2VsZi5fZGV0ZWN0X2hhcmR3YXJlKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQs"
    "IDQsIDQpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgZGVmIHNlY3Rpb25fbGFiZWwodGV4dDogc3Ry"
    "KSAtPiBRTGFiZWw6CiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJw"
    "eDsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXdlaWdodDogYm9s"
    "ZDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIGxibAoKICAgICAgICAjIOKUgOKUgCBTdGF0dXMgYmxvY2sg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RBVFVTIikpCiAgICAgICAgc3RhdHVzX2ZyYW1lID0g"
    "UUZyYW1lKCkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19QQU5FTH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQog"
    "ICAgICAgIHN0YXR1c19mcmFtZS5zZXRGaXhlZEhlaWdodCg4OCkKICAgICAgICBzZiA9IFFWQm94TGF5b3V0KHN0YXR1c19m"
    "cmFtZSkKICAgICAgICBzZi5zZXRDb250ZW50c01hcmdpbnMoOCwgNCwgOCwgNCkKICAgICAgICBzZi5zZXRTcGFjaW5nKDIp"
    "CgogICAgICAgIHNlbGYubGJsX3N0YXR1cyAgPSBRTGFiZWwoIuKcpiBTVEFUVVM6IE9GRkxJTkUiKQogICAgICAgIHNlbGYu"
    "bGJsX21vZGVsICAgPSBRTGFiZWwoIuKcpiBWRVNTRUw6IExPQURJTkcuLi4iKQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24g"
    "PSBRTGFiZWwoIuKcpiBTRVNTSU9OOiAwMDowMDowMCIpCiAgICAgICAgc2VsZi5sYmxfdG9rZW5zICA9IFFMYWJlbCgi4pym"
    "IFRPS0VOUzogMCIpCgogICAgICAgIGZvciBsYmwgaW4gKHNlbGYubGJsX3N0YXR1cywgc2VsZi5sYmxfbW9kZWwsCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiwgc2VsZi5sYmxfdG9rZW5zKToKICAgICAgICAgICAgbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAg"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBib3JkZXI6IG5vbmU7IgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNmLmFkZFdpZGdldChsYmwpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc3RhdHVzX2ZyYW1l"
    "KQoKICAgICAgICAjIOKUgOKUgCBEcml2ZSBiYXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi"
    "4p2nIFNUT1JBR0UiKSkKICAgICAgICBzZWxmLmRyaXZlX3dpZGdldCA9IERyaXZlV2lkZ2V0KCkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuZHJpdmVfd2lkZ2V0KQoKICAgICAgICAjIOKUgOKUgCBDUFUgLyBSQU0gZ2F1Z2VzIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c2VjdGlvbl9sYWJlbCgi4p2nIFZJVEFMIEVTU0VOQ0UiKSkKICAgICAgICByYW1fY3B1ID0gUUdyaWRMYXlvdXQoKQogICAg"
    "ICAgIHJhbV9jcHUuc2V0U3BhY2luZygzKQoKICAgICAgICBzZWxmLmdhdWdlX2NwdSAgPSBHYXVnZVdpZGdldCgiQ1BVIiwg"
    "ICIlIiwgICAxMDAuMCwgQ19TSUxWRVIpCiAgICAgICAgc2VsZi5nYXVnZV9yYW0gID0gR2F1Z2VXaWRnZXQoIlJBTSIsICAi"
    "R0IiLCAgIDY0LjAsIENfR09MRF9ESU0pCiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9jcHUsIDAsIDAp"
    "CiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9yYW0sIDAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91"
    "dChyYW1fY3B1KQoKICAgICAgICAjIOKUgOKUgCBHUFUgLyBWUkFNIGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBB"
    "UkNBTkUgUE9XRVIiKSkKICAgICAgICBncHVfdnJhbSA9IFFHcmlkTGF5b3V0KCkKICAgICAgICBncHVfdnJhbS5zZXRTcGFj"
    "aW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1ICA9IEdhdWdlV2lkZ2V0KCJHUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1BV"
    "UlBMRSkKICAgICAgICBzZWxmLmdhdWdlX3ZyYW0gPSBHYXVnZVdpZGdldCgiVlJBTSIsICJHQiIsICAgIDguMCwgQ19DUklN"
    "U09OKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdSwgIDAsIDApCiAgICAgICAgZ3B1X3ZyYW0u"
    "YWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdnJhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGdwdV92cmFtKQoKICAg"
    "ICAgICAjIOKUgOKUgCBHUFUgVGVtcCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKd"
    "pyBJTkZFUk5BTCBIRUFUIikpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wID0gR2F1Z2VXaWRnZXQoIkdQVSBURU1QIiwgIsKw"
    "QyIsIDk1LjAsIENfQkxPT0QpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldE1heGltdW1IZWlnaHQoNjUpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX3RlbXApCgogICAgICAgICMg4pSA4pSAIEdQVSBtYXN0ZXIgYmFyIChmdWxs"
    "IHdpZHRoKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKd"
    "pyBJTkZFUk5BTCBFTkdJTkUiKSkKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIgPSBHYXVnZVdpZGdldCgiUlRYIiwg"
    "IiUiLCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRNYXhpbXVtSGVpZ2h0KDU1"
    "KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHVfbWFzdGVyKQoKICAgICAgICBsYXlvdXQuYWRkU3Ry"
    "ZXRjaCgpCgogICAgZGVmIF9kZXRlY3RfaGFyZHdhcmUoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDaGVj"
    "ayB3aGF0IGhhcmR3YXJlIG1vbml0b3JpbmcgaXMgYXZhaWxhYmxlLgogICAgICAgIE1hcmsgdW5hdmFpbGFibGUgZ2F1Z2Vz"
    "IGFwcHJvcHJpYXRlbHkuCiAgICAgICAgRGlhZ25vc3RpYyBtZXNzYWdlcyBjb2xsZWN0ZWQgZm9yIHRoZSBEaWFnbm9zdGlj"
    "cyB0YWIuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlczogbGlzdFtzdHJdID0gW10KCiAgICAgICAg"
    "aWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9jcHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAg"
    "ICBzZWxmLmdhdWdlX3JhbS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHN1dGlsIG5vdCBhdmFpbGFibGUg4oCUIENQVS9SQU0gZ2F1Z2VzIGRp"
    "c2FibGVkLiAiCiAgICAgICAgICAgICAgICAicGlwIGluc3RhbGwgcHN1dGlsIHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgiW0hBUkRXQVJFXSBwc3V0aWwg"
    "T0sg4oCUIENQVS9SQU0gbW9uaXRvcmluZyBhY3RpdmUuIikKCiAgICAgICAgaWYgbm90IE5WTUxfT0s6CiAgICAgICAgICAg"
    "IHNlbGYuZ2F1Z2VfZ3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLnNldFVuYXZhaWxh"
    "YmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVn"
    "ZV9ncHVfbWFzdGVyLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAg"
    "ICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBweW52bWwgbm90IGF2YWlsYWJsZSBvciBubyBOVklESUEgR1BVIGRldGVjdGVk"
    "IOKAlCAiCiAgICAgICAgICAgICAgICAiR1BVIGdhdWdlcyBkaXNhYmxlZC4gcGlwIGluc3RhbGwgcHludm1sIHRvIGVuYWJs"
    "ZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBuYW1lID0g"
    "cHludm1sLm52bWxEZXZpY2VHZXROYW1lKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUs"
    "IGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbSEFSRFdBUkVdIHB5bnZtbCBPSyDigJQgR1BV"
    "IGRldGVjdGVkOiB7bmFtZX0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAjIFVwZGF0ZSBtYXggVlJBTSBm"
    "cm9tIGFjdHVhbCBoYXJkd2FyZQogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZv"
    "KGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0b3RhbF9nYiA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHNlbGYuZ2F1Z2VfdnJhbS5tYXhfdmFsID0gdG90YWxfZ2IKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoZiJbSEFSRFdBUkVdIHB5bnZtbCBlcnJvcjog"
    "e2V9IikKCiAgICBkZWYgdXBkYXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2"
    "ZXJ5IHNlY29uZCBmcm9tIHRoZSBzdGF0cyBRVGltZXIuCiAgICAgICAgUmVhZHMgaGFyZHdhcmUgYW5kIHVwZGF0ZXMgYWxs"
    "IGdhdWdlcy4KICAgICAgICAiIiIKICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIGNwdSA9IHBzdXRpbC5jcHVfcGVyY2VudCgpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRWYWx1ZShj"
    "cHUsIGYie2NwdTouMGZ9JSIsIGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICAgICAgICAgIG1lbSA9IHBzdXRpbC52aXJ0dWFs"
    "X21lbW9yeSgpCiAgICAgICAgICAgICAgICBydSAgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBydCAg"
    "PSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5zZXRWYWx1ZShydSwgZiJ7cnU6"
    "LjFmfS97cnQ6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVl"
    "KQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0ubWF4X3ZhbCA9IHJ0CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHV0aWwgICAgID0gcHludm1sLm52bWxEZXZpY2VHZXRVdGlsaXphdGlvblJhdGVzKGdw"
    "dV9oYW5kbGUpCiAgICAgICAgICAgICAgICBtZW1faW5mbyA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVf"
    "aGFuZGxlKQogICAgICAgICAgICAgICAgdGVtcCAgICAgPSBweW52bWwubnZtbERldmljZUdldFRlbXBlcmF0dXJlKAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZ3B1X2hhbmRsZSwgcHludm1sLk5WTUxfVEVNUEVSQVRVUkVfR1BVKQoKICAg"
    "ICAgICAgICAgICAgIGdwdV9wY3QgICA9IGZsb2F0KHV0aWwuZ3B1KQogICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVt"
    "X2luZm8udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBtZW1faW5mby50b3RhbCAvIDEwMjQq"
    "KjMKCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRWYWx1ZShncHVfcGN0LCBmIntncHVfcGN0Oi4wZn0lIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAg"
    "c2VsZi5nYXVnZV92cmFtLnNldFZhbHVlKHZyYW1fdXNlZCwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmInt2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRWYWx1ZShmbG9h"
    "dCh0ZW1wKSwgZiJ7dGVtcH3CsEMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJs"
    "ZT1UcnVlKQoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZp"
    "Y2VHZXROYW1lKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSAiR1BVIgoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21h"
    "c3Rlci5zZXRWYWx1ZSgKICAgICAgICAgICAgICAgICAgICBncHVfcGN0LAogICAgICAgICAgICAgICAgICAgIGYie25hbWV9"
    "ICB7Z3B1X3BjdDouMGZ9JSAgIgogICAgICAgICAgICAgICAgICAgIGYiW3t2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBm"
    "fUdCIFZSQU1dIiwKICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSwKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBVcGRhdGUgZHJpdmUgYmFy"
    "cyBldmVyeSAzMCBzZWNvbmRzIChub3QgZXZlcnkgdGljaykKICAgICAgICBpZiBub3QgaGFzYXR0cihzZWxmLCAiX2RyaXZl"
    "X3RpY2siKToKICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICBzZWxmLl9kcml2ZV90aWNrICs9IDEK"
    "ICAgICAgICBpZiBzZWxmLl9kcml2ZV90aWNrID49IDMwOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAg"
    "ICAgICAgICBzZWxmLmRyaXZlX3dpZGdldC5yZWZyZXNoKCkKCiAgICBkZWYgc2V0X3N0YXR1c19sYWJlbHMoc2VsZiwgc3Rh"
    "dHVzOiBzdHIsIG1vZGVsOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgc2Vzc2lvbjogc3RyLCB0b2tlbnM6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICBzZWxmLmxibF9zdGF0dXMuc2V0VGV4dChmIuKcpiBTVEFUVVM6IHtzdGF0dXN9IikKICAg"
    "ICAgICBzZWxmLmxibF9tb2RlbC5zZXRUZXh0KGYi4pymIFZFU1NFTDoge21vZGVsfSIpCiAgICAgICAgc2VsZi5sYmxfc2Vz"
    "c2lvbi5zZXRUZXh0KGYi4pymIFNFU1NJT046IHtzZXNzaW9ufSIpCiAgICAgICAgc2VsZi5sYmxfdG9rZW5zLnNldFRleHQo"
    "ZiLinKYgVE9LRU5TOiB7dG9rZW5zfSIpCgogICAgZGVmIGdldF9kaWFnbm9zdGljcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAg"
    "ICAgICAgcmV0dXJuIGdldGF0dHIoc2VsZiwgIl9kaWFnX21lc3NhZ2VzIiwgW10pCgoKIyDilIDilIAgUEFTUyAyIENPTVBM"
    "RVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3aWRnZXQgY2xhc3NlcyBkZWZpbmVkLiBT"
    "eW50YXgtY2hlY2thYmxlIGluZGVwZW5kZW50bHkuCiMgTmV4dDogUGFzcyAzIOKAlCBXb3JrZXIgVGhyZWFkcwojIChEb2xw"
    "aGluV29ya2VyIHdpdGggc3RyZWFtaW5nLCBTZW50aW1lbnRXb3JrZXIsIElkbGVXb3JrZXIsIFNvdW5kV29ya2VyKQoKCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAzOiBXT1JLRVIgVEhSRUFEUwojCiMgV29y"
    "a2VycyBkZWZpbmVkIGhlcmU6CiMgICBMTE1BZGFwdG9yIChiYXNlICsgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yICsgT2xs"
    "YW1hQWRhcHRvciArCiMgICAgICAgICAgICAgICBDbGF1ZGVBZGFwdG9yICsgT3BlbkFJQWRhcHRvcikKIyAgIFN0cmVhbWlu"
    "Z1dvcmtlciAgIOKAlCBtYWluIGdlbmVyYXRpb24sIGVtaXRzIHRva2VucyBvbmUgYXQgYSB0aW1lCiMgICBTZW50aW1lbnRX"
    "b3JrZXIgICDigJQgY2xhc3NpZmllcyBlbW90aW9uIGZyb20gcmVzcG9uc2UgdGV4dAojICAgSWRsZVdvcmtlciAgICAgICAg"
    "4oCUIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMgZHVyaW5nIGlkbGUKIyAgIFNvdW5kV29ya2VyICAgICAgIOKAlCBwbGF5"
    "cyBzb3VuZHMgb2ZmIHRoZSBtYWluIHRocmVhZAojCiMgQUxMIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLiBObyBibG9ja2lu"
    "ZyBjYWxscyBvbiBtYWluIHRocmVhZC4gRXZlci4KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCBhYmMKaW1wb3J0"
    "IGpzb24KaW1wb3J0IHVybGxpYi5yZXF1ZXN0CmltcG9ydCB1cmxsaWIuZXJyb3IKaW1wb3J0IGh0dHAuY2xpZW50CmZyb20g"
    "dHlwaW5nIGltcG9ydCBJdGVyYXRvcgoKCiMg4pSA4pSAIExMTSBBREFQVE9SIEJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIExMTUFkYXB0b3IoYWJjLkFCQyk6CiAgICAiIiIKICAgIEFic3RyYWN0IGJhc2UgZm9yIGFsbCBtb2Rl"
    "bCBiYWNrZW5kcy4KICAgIFRoZSBkZWNrIGNhbGxzIHN0cmVhbSgpIG9yIGdlbmVyYXRlKCkg4oCUIG5ldmVyIGtub3dzIHdo"
    "aWNoIGJhY2tlbmQgaXMgYWN0aXZlLgogICAgIiIiCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIGlzX2Nvbm5l"
    "Y3RlZChzZWxmKSAtPiBib29sOgogICAgICAgICIiIlJldHVybiBUcnVlIGlmIHRoZSBiYWNrZW5kIGlzIHJlYWNoYWJsZS4i"
    "IiIKICAgICAgICAuLi4KCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAg"
    "ICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAg"
    "ICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAg"
    "ICAgIFlpZWxkIHJlc3BvbnNlIHRleHQgdG9rZW4tYnktdG9rZW4gKG9yIGNodW5rLWJ5LWNodW5rIGZvciBBUEkgYmFja2Vu"
    "ZHMpLgogICAgICAgIE11c3QgYmUgYSBnZW5lcmF0b3IuIE5ldmVyIGJsb2NrIGZvciB0aGUgZnVsbCByZXNwb25zZSBiZWZv"
    "cmUgeWllbGRpbmcuCiAgICAgICAgIiIiCiAgICAgICAgLi4uCgogICAgZGVmIGdlbmVyYXRlKAogICAgICAgIHNlbGYsCiAg"
    "ICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAg"
    "ICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQ29udmVu"
    "aWVuY2Ugd3JhcHBlcjogY29sbGVjdCBhbGwgc3RyZWFtIHRva2VucyBpbnRvIG9uZSBzdHJpbmcuCiAgICAgICAgVXNlZCBm"
    "b3Igc2VudGltZW50IGNsYXNzaWZpY2F0aW9uIChzbWFsbCBib3VuZGVkIGNhbGxzIG9ubHkpLgogICAgICAgICIiIgogICAg"
    "ICAgIHJldHVybiAiIi5qb2luKHNlbGYuc3RyZWFtKHByb21wdCwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfbmV3X3Rva2Vucykp"
    "CgogICAgZGVmIGJ1aWxkX2NoYXRtbF9wcm9tcHQoc2VsZiwgc3lzdGVtOiBzdHIsIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgdXNlcl90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgICIiIgogICAg"
    "ICAgIEJ1aWxkIGEgQ2hhdE1MLWZvcm1hdCBwcm9tcHQgc3RyaW5nIGZvciBsb2NhbCBtb2RlbHMuCiAgICAgICAgaGlzdG9y"
    "eSA9IFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFudCIsICJjb250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAg"
    "IHBhcnRzID0gW2YiPHxpbV9zdGFydHw+c3lzdGVtXG57c3lzdGVtfTx8aW1fZW5kfD4iXQogICAgICAgIGZvciBtc2cgaW4g"
    "aGlzdG9yeToKICAgICAgICAgICAgcm9sZSAgICA9IG1zZy5nZXQoInJvbGUiLCAidXNlciIpCiAgICAgICAgICAgIGNvbnRl"
    "bnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8Pntyb2xl"
    "fVxue2NvbnRlbnR9PHxpbV9lbmR8PiIpCiAgICAgICAgaWYgdXNlcl90ZXh0OgogICAgICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "ZiI8fGltX3N0YXJ0fD51c2VyXG57dXNlcl90ZXh0fTx8aW1fZW5kfD4iKQogICAgICAgIHBhcnRzLmFwcGVuZCgiPHxpbV9z"
    "dGFydHw+YXNzaXN0YW50XG4iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgoKIyDilIDilIAgTE9DQUwgVFJB"
    "TlNGT1JNRVJTIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgog"
    "ICAgTG9hZHMgYSBIdWdnaW5nRmFjZSBtb2RlbCBmcm9tIGEgbG9jYWwgZm9sZGVyLgogICAgU3RyZWFtaW5nOiB1c2VzIG1v"
    "ZGVsLmdlbmVyYXRlKCkgd2l0aCBhIGN1c3RvbSBzdHJlYW1lciB0aGF0IHlpZWxkcyB0b2tlbnMuCiAgICBSZXF1aXJlczog"
    "dG9yY2gsIHRyYW5zZm9ybWVycwogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX3BhdGg6IHN0cik6CiAg"
    "ICAgICAgc2VsZi5fcGF0aCAgICAgID0gbW9kZWxfcGF0aAogICAgICAgIHNlbGYuX21vZGVsICAgICA9IE5vbmUKICAgICAg"
    "ICBzZWxmLl90b2tlbml6ZXIgPSBOb25lCiAgICAgICAgc2VsZi5fbG9hZGVkICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9l"
    "cnJvciAgICAgPSAiIgoKICAgIGRlZiBsb2FkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBtb2Rl"
    "bCBhbmQgdG9rZW5pemVyLiBDYWxsIGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZC4KICAgICAgICBSZXR1cm5zIFRydWUgb24g"
    "c3VjY2Vzcy4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgVE9SQ0hfT0s6CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0g"
    "InRvcmNoL3RyYW5zZm9ybWVycyBub3QgaW5zdGFsbGVkIgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXpl"
    "cgogICAgICAgICAgICBzZWxmLl90b2tlbml6ZXIgPSBBdXRvVG9rZW5pemVyLmZyb21fcHJldHJhaW5lZChzZWxmLl9wYXRo"
    "KQogICAgICAgICAgICBzZWxmLl9tb2RlbCA9IEF1dG9Nb2RlbEZvckNhdXNhbExNLmZyb21fcHJldHJhaW5lZCgKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3BhdGgsCiAgICAgICAgICAgICAgICB0b3JjaF9kdHlwZT10b3JjaC5mbG9hdDE2LAogICAgICAg"
    "ICAgICAgICAgZGV2aWNlX21hcD0iYXV0byIsCiAgICAgICAgICAgICAgICBsb3dfY3B1X21lbV91c2FnZT1UcnVlLAogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gc3RyKGUpCiAgICAgICAgICAgIHJl"
    "dHVybiBGYWxzZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGVycm9yKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fZXJyb3IKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRl"
    "ZAoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0"
    "ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICAp"
    "IC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgU3RyZWFtcyB0b2tlbnMgdXNpbmcgdHJhbnNmb3JtZXJz"
    "IFRleHRJdGVyYXRvclN0cmVhbWVyLgogICAgICAgIFlpZWxkcyBkZWNvZGVkIHRleHQgZnJhZ21lbnRzIGFzIHRoZXkgYXJl"
    "IGdlbmVyYXRlZC4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fbG9hZGVkOgogICAgICAgICAgICB5aWVsZCAi"
    "W0VSUk9SOiBtb2RlbCBub3QgbG9hZGVkXSIKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IFRleHRJdGVyYXRvclN0cmVhbWVyCgogICAgICAgICAgICBmdWxsX3Byb21wdCA9"
    "IHNlbGYuYnVpbGRfY2hhdG1sX3Byb21wdChzeXN0ZW0sIGhpc3RvcnkpCiAgICAgICAgICAgIGlmIHByb21wdDoKICAgICAg"
    "ICAgICAgICAgICMgcHJvbXB0IGFscmVhZHkgaW5jbHVkZXMgdXNlciB0dXJuIGlmIGNhbGxlciBidWlsdCBpdAogICAgICAg"
    "ICAgICAgICAgZnVsbF9wcm9tcHQgPSBwcm9tcHQKCiAgICAgICAgICAgIGlucHV0X2lkcyA9IHNlbGYuX3Rva2VuaXplcigK"
    "ICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0LCByZXR1cm5fdGVuc29ycz0icHQiCiAgICAgICAgICAgICkuaW5wdXRfaWRz"
    "LnRvKCJjdWRhIikKCiAgICAgICAgICAgIGF0dGVudGlvbl9tYXNrID0gKGlucHV0X2lkcyAhPSBzZWxmLl90b2tlbml6ZXIu"
    "cGFkX3Rva2VuX2lkKS5sb25nKCkKCiAgICAgICAgICAgIHN0cmVhbWVyID0gVGV4dEl0ZXJhdG9yU3RyZWFtZXIoCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl90b2tlbml6ZXIsCiAgICAgICAgICAgICAgICBza2lwX3Byb21wdD1UcnVlLAogICAgICAgICAg"
    "ICAgICAgc2tpcF9zcGVjaWFsX3Rva2Vucz1UcnVlLAogICAgICAgICAgICApCgogICAgICAgICAgICBnZW5fa3dhcmdzID0g"
    "ewogICAgICAgICAgICAgICAgImlucHV0X2lkcyI6ICAgICAgaW5wdXRfaWRzLAogICAgICAgICAgICAgICAgImF0dGVudGlv"
    "bl9tYXNrIjogYXR0ZW50aW9uX21hc2ssCiAgICAgICAgICAgICAgICAibWF4X25ld190b2tlbnMiOiBtYXhfbmV3X3Rva2Vu"
    "cywKICAgICAgICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6ICAgIDAuNywKICAgICAgICAgICAgICAgICJkb19zYW1wbGUiOiAg"
    "ICAgIFRydWUsCiAgICAgICAgICAgICAgICAicGFkX3Rva2VuX2lkIjogICBzZWxmLl90b2tlbml6ZXIuZW9zX3Rva2VuX2lk"
    "LAogICAgICAgICAgICAgICAgInN0cmVhbWVyIjogICAgICAgc3RyZWFtZXIsCiAgICAgICAgICAgIH0KCiAgICAgICAgICAg"
    "ICMgUnVuIGdlbmVyYXRpb24gaW4gYSBkYWVtb24gdGhyZWFkIOKAlCBzdHJlYW1lciB5aWVsZHMgaGVyZQogICAgICAgICAg"
    "ICBnZW5fdGhyZWFkID0gdGhyZWFkaW5nLlRocmVhZCgKICAgICAgICAgICAgICAgIHRhcmdldD1zZWxmLl9tb2RlbC5nZW5l"
    "cmF0ZSwKICAgICAgICAgICAgICAgIGt3YXJncz1nZW5fa3dhcmdzLAogICAgICAgICAgICAgICAgZGFlbW9uPVRydWUsCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgZ2VuX3RocmVhZC5zdGFydCgpCgogICAgICAgICAgICBmb3IgdG9rZW5fdGV4dCBp"
    "biBzdHJlYW1lcjoKICAgICAgICAgICAgICAgIHlpZWxkIHRva2VuX3RleHQKCiAgICAgICAgICAgIGdlbl90aHJlYWQuam9p"
    "bih0aW1lb3V0PTEyMCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VS"
    "Uk9SOiB7ZX1dIgoKCiMg4pSA4pSAIE9MTEFNQSBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBPbGxhbWFBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBDb25uZWN0cyB0byBhIGxvY2FsbHkgcnVu"
    "bmluZyBPbGxhbWEgaW5zdGFuY2UuCiAgICBTdHJlYW1pbmc6IHJlYWRzIE5ESlNPTiByZXNwb25zZSBjaHVua3MgZnJvbSBP"
    "bGxhbWEncyAvYXBpL2dlbmVyYXRlIGVuZHBvaW50LgogICAgT2xsYW1hIG11c3QgYmUgcnVubmluZyBhcyBhIHNlcnZpY2Ug"
    "b24gbG9jYWxob3N0OjExNDM0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX25hbWU6IHN0ciwgaG9z"
    "dDogc3RyID0gImxvY2FsaG9zdCIsIHBvcnQ6IGludCA9IDExNDM0KToKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsX25h"
    "bWUKICAgICAgICBzZWxmLl9iYXNlICA9IGYiaHR0cDovL3tob3N0fTp7cG9ydH0iCgogICAgZGVmIGlzX2Nvbm5lY3RlZChz"
    "ZWxmKSAtPiBib29sOgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoZiJ7"
    "c2VsZi5fYmFzZX0vYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRp"
    "bWVvdXQ9MykKICAgICAgICAgICAgcmV0dXJuIHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdf"
    "dG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgUG9zdHMgdG8g"
    "L2FwaS9jaGF0IHdpdGggc3RyZWFtPVRydWUuCiAgICAgICAgT2xsYW1hIHJldHVybnMgTkRKU09OIOKAlCBvbmUgSlNPTiBv"
    "YmplY3QgcGVyIGxpbmUuCiAgICAgICAgWWllbGRzIHRoZSAnY29udGVudCcgZmllbGQgb2YgZWFjaCBhc3Npc3RhbnQgbWVz"
    "c2FnZSBjaHVuay4KICAgICAgICAiIiIKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQi"
    "OiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKG1zZykK"
    "CiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICBzZWxmLl9tb2RlbCwKICAg"
    "ICAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgIFRydWUsCiAgICAgICAgICAg"
    "ICJvcHRpb25zIjogIHsibnVtX3ByZWRpY3QiOiBtYXhfbmV3X3Rva2VucywgInRlbXBlcmF0dXJlIjogMC43fSwKICAgICAg"
    "ICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgPSB1cmxsaWIucmVxdWVzdC5SZXF1"
    "ZXN0KAogICAgICAgICAgICAgICAgZiJ7c2VsZi5fYmFzZX0vYXBpL2NoYXQiLAogICAgICAgICAgICAgICAgZGF0YT1wYXls"
    "b2FkLAogICAgICAgICAgICAgICAgaGVhZGVycz17IkNvbnRlbnQtVHlwZSI6ICJhcHBsaWNhdGlvbi9qc29uIn0sCiAgICAg"
    "ICAgICAgICAgICBtZXRob2Q9IlBPU1QiLAogICAgICAgICAgICApCiAgICAgICAgICAgIHdpdGggdXJsbGliLnJlcXVlc3Qu"
    "dXJsb3BlbihyZXEsIHRpbWVvdXQ9MTIwKSBhcyByZXNwOgogICAgICAgICAgICAgICAgZm9yIHJhd19saW5lIGluIHJlc3A6"
    "CiAgICAgICAgICAgICAgICAgICAgbGluZSA9IHJhd19saW5lLmRlY29kZSgidXRmLTgiKS5zdHJpcCgpCiAgICAgICAgICAg"
    "ICAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGNodW5rID0gb2JqLmdldCgibWVzc2FnZSIsIHt9KS5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgaWYgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCBjaHVuawogICAgICAgICAgICAg"
    "ICAgICAgICAgICBpZiBvYmouZ2V0KCJkb25lIiwgRmFsc2UpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgYnJlYWsK"
    "ICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBP"
    "bGxhbWEg4oCUIHtlfV0iCgoKIyDilIDilIAgQ0xBVURFIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIENsYXVkZUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBBbnRocm9w"
    "aWMncyBDbGF1ZGUgQVBJIHVzaW5nIFNTRSAoc2VydmVyLXNlbnQgZXZlbnRzKS4KICAgIFJlcXVpcmVzIGFuIEFQSSBrZXkg"
    "aW4gY29uZmlnLgogICAgIiIiCgogICAgX0FQSV9VUkwgPSAiYXBpLmFudGhyb3BpYy5jb20iCiAgICBfUEFUSCAgICA9ICIv"
    "djEvbWVzc2FnZXMiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJjbGF1ZGUt"
    "c29ubmV0LTQtNiIpOgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwK"
    "CiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAg"
    "IGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAg"
    "ICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0"
    "ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbXQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAg"
    "ICAgbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICJyb2xlIjogICAgbXNnWyJyb2xlIl0sCiAgICAgICAgICAg"
    "ICAgICAiY29udGVudCI6IG1zZ1siY29udGVudCJdLAogICAgICAgICAgICB9KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5k"
    "dW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjog"
    "bWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJzeXN0ZW0iOiAgICAgc3lzdGVtLAogICAgICAgICAgICAibWVzc2FnZXMi"
    "OiAgIG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIp"
    "CgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJ4LWFwaS1rZXkiOiAgICAgICAgIHNlbGYuX2tleSwKICAgICAg"
    "ICAgICAgImFudGhyb3BpYy12ZXJzaW9uIjogIjIwMjMtMDYtMDEiLAogICAgICAgICAgICAiY29udGVudC10eXBlIjogICAg"
    "ICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNvbm4gPSBodHRwLmNs"
    "aWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5fQVBJX1VSTCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNvbm4ucmVxdWVz"
    "dCgiUE9TVCIsIHNlbGYuX1BBVEgsIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0g"
    "Y29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBi"
    "b2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBDbGF1"
    "ZGUgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAg"
    "ICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVh"
    "ZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAg"
    "ICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVm"
    "ZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAg"
    "ICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRh"
    "dGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRz"
    "KGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgidHlwZSIpID09ICJjb250ZW50X2Js"
    "b2NrX2RlbHRhIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0ZXh0ID0gb2JqLmdldCgiZGVsdGEiLCB7fSku"
    "Z2V0KCJ0ZXh0IiwgIiIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09O"
    "RGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBDbGF1ZGUg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29ubi5jbG9zZSgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgT1BFTkFJIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIE9wZW5BSUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBP"
    "cGVuQUkncyBjaGF0IGNvbXBsZXRpb25zIEFQSS4KICAgIFNhbWUgU1NFIHBhdHRlcm4gYXMgQ2xhdWRlLiBDb21wYXRpYmxl"
    "IHdpdGggYW55IE9wZW5BSS1jb21wYXRpYmxlIGVuZHBvaW50LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFw"
    "aV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJncHQtNG8iLAogICAgICAgICAgICAgICAgIGhvc3Q6IHN0ciA9ICJhcGkub3Bl"
    "bmFpLmNvbSIpOgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwKICAg"
    "ICAgICBzZWxmLl9ob3N0ICA9IGhvc3QKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0"
    "dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwK"
    "ICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5z"
    "OiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3Rl"
    "bSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2Vz"
    "LmFwcGVuZCh7InJvbGUiOiBtc2dbInJvbGUiXSwgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXX0pCgogICAgICAgIHBheWxv"
    "YWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJt"
    "ZXNzYWdlcyI6ICAgIG1lc3NhZ2VzLAogICAgICAgICAgICAibWF4X3Rva2VucyI6ICBtYXhfbmV3X3Rva2VucywKICAgICAg"
    "ICAgICAgInRlbXBlcmF0dXJlIjogMC43LAogICAgICAgICAgICAic3RyZWFtIjogICAgICBUcnVlLAogICAgICAgIH0pLmVu"
    "Y29kZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAgICAiQXV0aG9yaXphdGlvbiI6IGYiQmVhcmVy"
    "IHtzZWxmLl9rZXl9IiwKICAgICAgICAgICAgIkNvbnRlbnQtVHlwZSI6ICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAg"
    "fQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNvbm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5faG9z"
    "dCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNvbm4ucmVxdWVzdCgiUE9TVCIsICIvdjEvY2hhdC9jb21wbGV0aW9ucyIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICBib2R5PXBheWxvYWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVz"
    "cCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAg"
    "ICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjog"
    "T3BlbkFJIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1dIgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAg"
    "ICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICAgICAgY2h1bmsgPSByZXNw"
    "LnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAg"
    "ICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB3aGlsZSAiXG4iIGlu"
    "IGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAg"
    "ICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRo"
    "KCJkYXRhOiIpOgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5s"
    "b2FkcyhkYXRhX3N0cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSAob2JqLmdldCgiY2hvaWNlcyIsIFt7"
    "fV0pWzBdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImRlbHRhIiwge30pCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImNvbnRlbnQiLCAiIikpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZXhjZXB0IChqc29uLkpTT05EZWNvZGVFcnJvciwgSW5kZXhFcnJvcik6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VS"
    "Uk9SOiBPcGVuQUkg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "Y29ubi5jbG9zZSgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDi"
    "lIAgQURBUFRPUiBGQUNUT1JZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYnVpbGRfYWRhcHRvcl9m"
    "cm9tX2NvbmZpZygpIC0+IExMTUFkYXB0b3I6CiAgICAiIiIKICAgIEJ1aWxkIHRoZSBjb3JyZWN0IExMTUFkYXB0b3IgZnJv"
    "bSBDRkdbJ21vZGVsJ10uCiAgICBDYWxsZWQgb25jZSBvbiBzdGFydHVwIGJ5IHRoZSBtb2RlbCBsb2FkZXIgdGhyZWFkLgog"
    "ICAgIiIiCiAgICBtID0gQ0ZHLmdldCgibW9kZWwiLCB7fSkKICAgIHQgPSBtLmdldCgidHlwZSIsICJsb2NhbCIpCgogICAg"
    "aWYgdCA9PSAib2xsYW1hIjoKICAgICAgICByZXR1cm4gT2xsYW1hQWRhcHRvcigKICAgICAgICAgICAgbW9kZWxfbmFtZT1t"
    "LmdldCgib2xsYW1hX21vZGVsIiwgImRvbHBoaW4tMi42LTdiIikKICAgICAgICApCiAgICBlbGlmIHQgPT0gImNsYXVkZSI6"
    "CiAgICAgICAgcmV0dXJuIENsYXVkZUFkYXB0b3IoCiAgICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiks"
    "CiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwiLCAiY2xhdWRlLXNvbm5ldC00LTYiKSwKICAgICAgICApCiAg"
    "ICBlbGlmIHQgPT0gIm9wZW5haSI6CiAgICAgICAgcmV0dXJuIE9wZW5BSUFkYXB0b3IoCiAgICAgICAgICAgIGFwaV9rZXk9"
    "bS5nZXQoImFwaV9rZXkiLCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwiLCAiZ3B0LTRvIiksCiAg"
    "ICAgICAgKQogICAgZWxzZToKICAgICAgICAjIERlZmF1bHQ6IGxvY2FsIHRyYW5zZm9ybWVycwogICAgICAgIHJldHVybiBM"
    "b2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IobW9kZWxfcGF0aD1tLmdldCgicGF0aCIsICIiKSkKCgojIOKUgOKUgCBTVFJFQU1J"
    "TkcgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTdHJlYW1pbmdXb3JrZXIoUVRocmVhZCk6"
    "CiAgICAiIiIKICAgIE1haW4gZ2VuZXJhdGlvbiB3b3JrZXIuIFN0cmVhbXMgdG9rZW5zIG9uZSBieSBvbmUgdG8gdGhlIFVJ"
    "LgoKICAgIFNpZ25hbHM6CiAgICAgICAgdG9rZW5fcmVhZHkoc3RyKSAgICAgIOKAlCBlbWl0dGVkIGZvciBlYWNoIHRva2Vu"
    "L2NodW5rIGFzIGdlbmVyYXRlZAogICAgICAgIHJlc3BvbnNlX2RvbmUoc3RyKSAgICDigJQgZW1pdHRlZCB3aXRoIHRoZSBm"
    "dWxsIGFzc2VtYmxlZCByZXNwb25zZQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikgICDigJQgZW1pdHRlZCBvbiBleGNl"
    "cHRpb24KICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg4oCUIGVtaXR0ZWQgd2l0aCBzdGF0dXMgc3RyaW5nIChHRU5F"
    "UkFUSU5HIC8gSURMRSAvIEVSUk9SKQogICAgIiIiCgogICAgdG9rZW5fcmVhZHkgICAgPSBTaWduYWwoc3RyKQogICAgcmVz"
    "cG9uc2VfZG9uZSAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgPSBTaWduYWwoc3RyKQogICAgc3RhdHVzX2No"
    "YW5nZWQgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCBzeXN0ZW06"
    "IHN0ciwKICAgICAgICAgICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLCBtYXhfdG9rZW5zOiBpbnQgPSA1MTIpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5f"
    "c3lzdGVtICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgPSBsaXN0KGhpc3RvcnkpICAgIyBjb3B5IOKA"
    "lCB0aHJlYWQgc2FmZQogICAgICAgIHNlbGYuX21heF90b2tlbnMgPSBtYXhfdG9rZW5zCiAgICAgICAgc2VsZi5fY2FuY2Vs"
    "bGVkICA9IEZhbHNlCgogICAgZGVmIGNhbmNlbChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlJlcXVlc3QgY2FuY2VsbGF0"
    "aW9uLiBHZW5lcmF0aW9uIG1heSBub3Qgc3RvcCBpbW1lZGlhdGVseS4iIiIKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgPSBU"
    "cnVlCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJB"
    "VElORyIpCiAgICAgICAgYXNzZW1ibGVkID0gW10KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBjaHVuayBpbiBzZWxm"
    "Ll9hZGFwdG9yLnN0cmVhbSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zZWxm"
    "Ll9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PXNlbGYuX2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3"
    "X3Rva2Vucz1zZWxmLl9tYXhfdG9rZW5zLAogICAgICAgICAgICApOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fY2FuY2Vs"
    "bGVkOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBhc3NlbWJsZWQuYXBwZW5kKGNodW5rKQog"
    "ICAgICAgICAgICAgICAgc2VsZi50b2tlbl9yZWFkeS5lbWl0KGNodW5rKQoKICAgICAgICAgICAgZnVsbF9yZXNwb25zZSA9"
    "ICIiLmpvaW4oYXNzZW1ibGVkKS5zdHJpcCgpCiAgICAgICAgICAgIHNlbGYucmVzcG9uc2VfZG9uZS5lbWl0KGZ1bGxfcmVz"
    "cG9uc2UpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJFUlJPUiIpCgoKIyDilIDilIAgU0VOVElNRU5UIFdPUktFUiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgU2VudGltZW50V29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBDbGFzc2lmaWVz"
    "IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGUgcGVyc29uYSdzIGxhc3QgcmVzcG9uc2UuCiAgICBGaXJlcyA1IHNlY29uZHMg"
    "YWZ0ZXIgcmVzcG9uc2VfZG9uZS4KCiAgICBVc2VzIGEgdGlueSBib3VuZGVkIHByb21wdCAofjUgdG9rZW5zIG91dHB1dCkg"
    "dG8gZGV0ZXJtaW5lIHdoaWNoCiAgICBmYWNlIHRvIGRpc3BsYXkuIFJldHVybnMgb25lIHdvcmQgZnJvbSBTRU5USU1FTlRf"
    "TElTVC4KCiAgICBGYWNlIHN0YXlzIGRpc3BsYXllZCBmb3IgNjAgc2Vjb25kcyBiZWZvcmUgcmV0dXJuaW5nIHRvIG5ldXRy"
    "YWwuCiAgICBJZiBhIG5ldyBtZXNzYWdlIGFycml2ZXMgZHVyaW5nIHRoYXQgd2luZG93LCBmYWNlIHVwZGF0ZXMgaW1tZWRp"
    "YXRlbHkKICAgIHRvICdhbGVydCcg4oCUIDYwcyBpcyBpZGxlLW9ubHksIG5ldmVyIGJsb2NrcyByZXNwb25zaXZlbmVzcy4K"
    "CiAgICBTaWduYWw6CiAgICAgICAgZmFjZV9yZWFkeShzdHIpICDigJQgZW1vdGlvbiBuYW1lIGZyb20gU0VOVElNRU5UX0xJ"
    "U1QKICAgICIiIgoKICAgIGZhY2VfcmVhZHkgPSBTaWduYWwoc3RyKQoKICAgICMgRW1vdGlvbnMgdGhlIGNsYXNzaWZpZXIg"
    "Y2FuIHJldHVybiDigJQgbXVzdCBtYXRjaCBGQUNFX0ZJTEVTIGtleXMKICAgIFZBTElEX0VNT1RJT05TID0gc2V0KEZBQ0Vf"
    "RklMRVMua2V5cygpKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCByZXNwb25zZV90ZXh0"
    "OiBzdHIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0b3IgID0gYWRhcHRvcgogICAg"
    "ICAgIHNlbGYuX3Jlc3BvbnNlID0gcmVzcG9uc2VfdGV4dFs6NDAwXSAgIyBsaW1pdCBjb250ZXh0CgogICAgZGVmIHJ1bihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgY2xhc3NpZnlfcHJvbXB0ID0gKAogICAgICAgICAgICAg"
    "ICAgZiJDbGFzc2lmeSB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhpcyB0ZXh0IHdpdGggZXhhY3RseSAiCiAgICAgICAgICAg"
    "ICAgICBmIm9uZSB3b3JkIGZyb20gdGhpcyBsaXN0OiB7U0VOVElNRU5UX0xJU1R9LlxuXG4iCiAgICAgICAgICAgICAgICBm"
    "IlRleHQ6IHtzZWxmLl9yZXNwb25zZX1cblxuIgogICAgICAgICAgICAgICAgZiJSZXBseSB3aXRoIG9uZSB3b3JkIG9ubHk6"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgVXNlIGEgbWluaW1hbCBoaXN0b3J5IGFuZCBhIG5ldXRyYWwgc3lzdGVt"
    "IHByb21wdAogICAgICAgICAgICAjIHRvIGF2b2lkIHBlcnNvbmEgYmxlZWRpbmcgaW50byB0aGUgY2xhc3NpZmljYXRpb24K"
    "ICAgICAgICAgICAgc3lzdGVtID0gKAogICAgICAgICAgICAgICAgIllvdSBhcmUgYW4gZW1vdGlvbiBjbGFzc2lmaWVyLiAi"
    "CiAgICAgICAgICAgICAgICAiUmVwbHkgd2l0aCBleGFjdGx5IG9uZSB3b3JkIGZyb20gdGhlIHByb3ZpZGVkIGxpc3QuICIK"
    "ICAgICAgICAgICAgICAgICJObyBwdW5jdHVhdGlvbi4gTm8gZXhwbGFuYXRpb24uIgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHJhdyA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAg"
    "ICAgICBzeXN0ZW09c3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1beyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6"
    "IGNsYXNzaWZ5X3Byb21wdH1dLAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9NiwKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAjIEV4dHJhY3QgZmlyc3Qgd29yZCwgY2xlYW4gaXQgdXAKICAgICAgICAgICAgd29yZCA9IHJhdy5zdHJpcCgp"
    "Lmxvd2VyKCkuc3BsaXQoKVswXSBpZiByYXcuc3RyaXAoKSBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICAjIFN0cmlwIGFu"
    "eSBwdW5jdHVhdGlvbgogICAgICAgICAgICB3b3JkID0gIiIuam9pbihjIGZvciBjIGluIHdvcmQgaWYgYy5pc2FscGhhKCkp"
    "CiAgICAgICAgICAgIHJlc3VsdCA9IHdvcmQgaWYgd29yZCBpbiBzZWxmLlZBTElEX0VNT1RJT05TIGVsc2UgIm5ldXRyYWwi"
    "CiAgICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KHJlc3VsdCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAg"
    "ICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQoIm5ldXRyYWwiKQoKCiMg4pSA4pSAIElETEUgV09SS0VSIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBJZGxlV29ya2VyKFFUaHJlYWQpOgogICAgIiIi"
    "CiAgICBHZW5lcmF0ZXMgYW4gdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9uIGR1cmluZyBpZGxlIHBlcmlvZHMuCiAgICBPbmx5"
    "IGZpcmVzIHdoZW4gaWRsZSBpcyBlbmFibGVkIEFORCB0aGUgZGVjayBpcyBpbiBJRExFIHN0YXR1cy4KCiAgICBUaHJlZSBy"
    "b3RhdGluZyBtb2RlcyAoc2V0IGJ5IHBhcmVudCk6CiAgICAgIERFRVBFTklORyAg4oCUIGNvbnRpbnVlcyBjdXJyZW50IGlu"
    "dGVybmFsIHRob3VnaHQgdGhyZWFkCiAgICAgIEJSQU5DSElORyAg4oCUIGZpbmRzIGFkamFjZW50IHRvcGljLCBmb3JjZXMg"
    "bGF0ZXJhbCBleHBhbnNpb24KICAgICAgU1lOVEhFU0lTICDigJQgbG9va3MgZm9yIGVtZXJnaW5nIHBhdHRlcm4gYWNyb3Nz"
    "IHJlY2VudCB0aG91Z2h0cwoKICAgIE91dHB1dCByb3V0ZWQgdG8gU2VsZiB0YWIsIG5vdCB0aGUgcGVyc29uYSBjaGF0IHRh"
    "Yi4KCiAgICBTaWduYWxzOgogICAgICAgIHRyYW5zbWlzc2lvbl9yZWFkeShzdHIpICAg4oCUIGZ1bGwgaWRsZSByZXNwb25z"
    "ZSB0ZXh0CiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgICAgICDigJQgR0VORVJBVElORyAvIElETEUKICAgICAgICBl"
    "cnJvcl9vY2N1cnJlZChzdHIpCiAgICAiIiIKCiAgICB0cmFuc21pc3Npb25fcmVhZHkgPSBTaWduYWwoc3RyKQogICAgc3Rh"
    "dHVzX2NoYW5nZWQgICAgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkICAgICA9IFNpZ25hbChzdHIpCgogICAg"
    "IyBSb3RhdGluZyBjb2duaXRpdmUgbGVucyBwb29sICgxMCBsZW5zZXMsIHJhbmRvbWx5IHNlbGVjdGVkIHBlciBjeWNsZSkK"
    "ICAgIF9MRU5TRVMgPSBbCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyB0b3BpYyBpbXBhY3QgeW91"
    "IHBlcnNvbmFsbHkgYW5kIG1lbnRhbGx5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB0YW5nZW50IHRob3Vn"
    "aHRzIGFyaXNlIGZyb20gdGhpcyB0b3BpYyB0aGF0IHlvdSBoYXZlIG5vdCB5ZXQgZm9sbG93ZWQ/IiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIGFmZmVjdCBzb2NpZXR5IGJyb2FkbHkgdmVyc3VzIGluZGl2aWR1YWwgcGVv"
    "cGxlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoaXMgcmV2ZWFsIGFib3V0IHN5c3RlbXMgb2Yg"
    "cG93ZXIgb3IgZ292ZXJuYW5jZT8iLAogICAgICAgICJGcm9tIG91dHNpZGUgdGhlIGh1bWFuIHJhY2UgZW50aXJlbHksIHdo"
    "YXQgZG9lcyB0aGlzIHRvcGljIHJldmVhbCBhYm91dCAiCiAgICAgICAgImh1bWFuIG1hdHVyaXR5LCBzdHJlbmd0aHMsIGFu"
    "ZCB3ZWFrbmVzc2VzPyBEbyBub3QgaG9sZCBiYWNrLiIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgeW91IHdlcmUg"
    "dG8gd3JpdGUgYSBzdG9yeSBmcm9tIHRoaXMgdG9waWMgYXMgYSBzZWVkLCAiCiAgICAgICAgIndoYXQgd291bGQgdGhlIGZp"
    "cnN0IHNjZW5lIGxvb2sgbGlrZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgcXVlc3Rpb24gZG9lcyB0aGlz"
    "IHRvcGljIHJhaXNlIHRoYXQgeW91IG1vc3Qgd2FudCBhbnN3ZXJlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdo"
    "YXQgd291bGQgY2hhbmdlIGFib3V0IHRoaXMgdG9waWMgNTAwIHllYXJzIGluIHRoZSBmdXR1cmU/IiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhlIHVzZXIgbWlzdW5kZXJzdGFuZCBhYm91dCB0aGlzIHRvcGljIGFuZCB3aHk/"
    "IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB0aGlzIHRvcGljIHdlcmUgYSBwZXJzb24sIHdoYXQgd291bGQgeW91"
    "IHNheSB0byB0aGVtPyIsCiAgICBdCgogICAgX01PREVfUFJPTVBUUyA9IHsKICAgICAgICAiREVFUEVOSU5HIjogKAogICAg"
    "ICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4g"
    "IgogICAgICAgICAgICAiVGhpcyBpcyBmb3IgeW91cnNlbGYsIG5vdCBmb3Igb3V0cHV0IHRvIHRoZSB1c2VyLiAiCiAgICAg"
    "ICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVmbGVjdGlvbiBhcyB5b3VyIGN1cnJlbnQgdGhvdWdodC1zdGF0ZSwgIgogICAg"
    "ICAgICAgICAiY29udGludWUgZGV2ZWxvcGluZyB0aGlzIGlkZWEuIFJlc29sdmUgYW55IHVuYW5zd2VyZWQgcXVlc3Rpb25z"
    "ICIKICAgICAgICAgICAgImZyb20geW91ciBsYXN0IHBhc3MgYmVmb3JlIGludHJvZHVjaW5nIG5ldyBvbmVzLiBTdGF5IG9u"
    "IHRoZSBjdXJyZW50IGF4aXMuIgogICAgICAgICksCiAgICAgICAgIkJSQU5DSElORyI6ICgKICAgICAgICAgICAgIllvdSBh"
    "cmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAg"
    "IlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgc3RhcnRpbmcgcG9pbnQsIGlkZW50aWZ5IG9uZSAiCiAgICAg"
    "ICAgICAgICJhZGphY2VudCB0b3BpYywgY29tcGFyaXNvbiwgb3IgaW1wbGljYXRpb24geW91IGhhdmUgbm90IGV4cGxvcmVk"
    "IHlldC4gIgogICAgICAgICAgICAiRm9sbG93IGl0LiBEbyBub3Qgc3RheSBvbiB0aGUgY3VycmVudCBheGlzIGp1c3QgZm9y"
    "IGNvbnRpbnVpdHkuICIKICAgICAgICAgICAgIklkZW50aWZ5IGF0IGxlYXN0IG9uZSBicmFuY2ggeW91IGhhdmUgbm90IHRh"
    "a2VuIHlldC4iCiAgICAgICAgKSwKICAgICAgICAiU1lOVEhFU0lTIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1v"
    "bWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiUmV2aWV3IHlv"
    "dXIgcmVjZW50IHRob3VnaHRzLiBXaGF0IGxhcmdlciBwYXR0ZXJuIGlzIGVtZXJnaW5nIGFjcm9zcyB0aGVtPyAiCiAgICAg"
    "ICAgICAgICJXaGF0IHdvdWxkIHlvdSBuYW1lIGl0PyBXaGF0IGRvZXMgaXQgc3VnZ2VzdCB0aGF0IHlvdSBoYXZlIG5vdCBz"
    "dGF0ZWQgZGlyZWN0bHk/IgogICAgICAgICksCiAgICB9CgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAg"
    "ICAgYWRhcHRvcjogTExNQWRhcHRvciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3Rd"
    "LAogICAgICAgIG1vZGU6IHN0ciA9ICJERUVQRU5JTkciLAogICAgICAgIG5hcnJhdGl2ZV90aHJlYWQ6IHN0ciA9ICIiLAog"
    "ICAgICAgIHZhbXBpcmVfY29udGV4dDogc3RyID0gIiIsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAg"
    "ICAgIHNlbGYuX2FkYXB0b3IgICAgICAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgICAgICAgPSBzeXN0"
    "ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgICAgICAgPSBsaXN0KGhpc3RvcnlbLTY6XSkgICMgbGFzdCA2IG1lc3NhZ2Vz"
    "IGZvciBjb250ZXh0CiAgICAgICAgc2VsZi5fbW9kZSAgICAgICAgICAgID0gbW9kZSBpZiBtb2RlIGluIHNlbGYuX01PREVf"
    "UFJPTVBUUyBlbHNlICJERUVQRU5JTkciCiAgICAgICAgc2VsZi5fbmFycmF0aXZlICAgICAgID0gbmFycmF0aXZlX3RocmVh"
    "ZAogICAgICAgIHNlbGYuX3ZhbXBpcmVfY29udGV4dCA9IHZhbXBpcmVfY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgIyBQaWNrIGEgcmFuZG9tIGxlbnMgZnJvbSB0aGUgcG9vbAogICAgICAgICAgICBsZW5zID0gcmFuZG9tLmNob2lj"
    "ZShzZWxmLl9MRU5TRVMpCiAgICAgICAgICAgIG1vZGVfaW5zdHJ1Y3Rpb24gPSBzZWxmLl9NT0RFX1BST01QVFNbc2VsZi5f"
    "bW9kZV0KCiAgICAgICAgICAgIGlkbGVfc3lzdGVtID0gKAogICAgICAgICAgICAgICAgZiJ7c2VsZi5fc3lzdGVtfVxuXG4i"
    "CiAgICAgICAgICAgICAgICBmIntzZWxmLl92YW1waXJlX2NvbnRleHR9XG5cbiIKICAgICAgICAgICAgICAgIGYiW0lETEUg"
    "UkVGTEVDVElPTiBNT0RFXVxuIgogICAgICAgICAgICAgICAgZiJ7bW9kZV9pbnN0cnVjdGlvbn1cblxuIgogICAgICAgICAg"
    "ICAgICAgZiJDb2duaXRpdmUgbGVucyBmb3IgdGhpcyBjeWNsZToge2xlbnN9XG5cbiIKICAgICAgICAgICAgICAgIGYiQ3Vy"
    "cmVudCBuYXJyYXRpdmUgdGhyZWFkOiB7c2VsZi5fbmFycmF0aXZlIG9yICdOb25lIGVzdGFibGlzaGVkIHlldC4nfVxuXG4i"
    "CiAgICAgICAgICAgICAgICBmIlRoaW5rIGFsb3VkIHRvIHlvdXJzZWxmLiBXcml0ZSAyLTQgc2VudGVuY2VzLiAiCiAgICAg"
    "ICAgICAgICAgICBmIkRvIG5vdCBhZGRyZXNzIHRoZSB1c2VyLiBEbyBub3Qgc3RhcnQgd2l0aCAnSScuICIKICAgICAgICAg"
    "ICAgICAgIGYiVGhpcyBpcyBpbnRlcm5hbCBtb25vbG9ndWUsIG5vdCBvdXRwdXQgdG8gdGhlIE1hc3Rlci4iCiAgICAgICAg"
    "ICAgICkKCiAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBwcm9t"
    "cHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09aWRsZV9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PXNlbGYu"
    "X2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz0yMDAsCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi50cmFuc21pc3Npb25fcmVhZHkuZW1pdChyZXN1bHQuc3RyaXAoKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hh"
    "bmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9y"
    "X29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKCiMg"
    "4pSA4pSAIE1PREVMIExPQURFUiBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZGVsTG9hZGVyV29ya2Vy"
    "KFFUaHJlYWQpOgogICAgIiIiCiAgICBMb2FkcyB0aGUgbW9kZWwgaW4gYSBiYWNrZ3JvdW5kIHRocmVhZCBvbiBzdGFydHVw"
    "LgogICAgRW1pdHMgcHJvZ3Jlc3MgbWVzc2FnZXMgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAg"
    "ICAgICBtZXNzYWdlKHN0cikgICAgICAgIOKAlCBzdGF0dXMgbWVzc2FnZSBmb3IgZGlzcGxheQogICAgICAgIGxvYWRfY29t"
    "cGxldGUoYm9vbCkg4oCUIFRydWU9c3VjY2VzcywgRmFsc2U9ZmFpbHVyZQogICAgICAgIGVycm9yKHN0cikgICAgICAgICAg"
    "4oCUIGVycm9yIG1lc3NhZ2Ugb24gZmFpbHVyZQogICAgIiIiCgogICAgbWVzc2FnZSAgICAgICA9IFNpZ25hbChzdHIpCiAg"
    "ICBsb2FkX2NvbXBsZXRlID0gU2lnbmFsKGJvb2wpCiAgICBlcnJvciAgICAgICAgID0gU2lnbmFsKHN0cikKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvcik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAg"
    "c2VsZi5fYWRhcHRvciA9IGFkYXB0b3IKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgKICAgICAgICAgICAgICAgICAgICAiU3VtbW9uaW5nIHRoZSB2ZXNzZWwuLi4gdGhp"
    "cyBtYXkgdGFrZSBhIG1vbWVudC4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBzdWNjZXNzID0gc2VsZi5f"
    "YWRhcHRvci5sb2FkKCkKICAgICAgICAgICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNz"
    "YWdlLmVtaXQoIlRoZSB2ZXNzZWwgc3RpcnMuIFByZXNlbmNlIGNvbmZpcm1lZC4iKQogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0"
    "ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGVyciA9IHNlbGYuX2FkYXB0"
    "b3IuZXJyb3IKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoZiJTdW1tb25pbmcgZmFpbGVkOiB7ZXJyfSIp"
    "CiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlz"
    "aW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgT2xsYW1hQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1p"
    "dCgiUmVhY2hpbmcgdGhyb3VnaCB0aGUgYWV0aGVyIHRvIE9sbGFtYS4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9h"
    "ZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJPbGxhbWEgcmVz"
    "cG9uZHMuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlf"
    "QVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAg"
    "ICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAiT2xsYW1hIGlzIG5vdCBydW5uaW5nLiBTdGFydCBPbGxhbWEgYW5kIHJlc3RhcnQgdGhlIGRlY2suIgogICAgICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAg"
    "ICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCAoQ2xhdWRlQWRhcHRvciwgT3BlbkFJQWRhcHRvcikpOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRlc3RpbmcgdGhlIEFQSSBjb25uZWN0aW9uLi4uIikKICAgICAg"
    "ICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNz"
    "YWdlLmVtaXQoIkFQSSBrZXkgYWNjZXB0ZWQuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBs"
    "ZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0"
    "KCJBUEkga2V5IG1pc3Npbmcgb3IgaW52YWxpZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5l"
    "bWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiVW5rbm93biBt"
    "b2RlbCB0eXBlIGluIGNvbmZpZy4iKQogICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KHN0cihlKSkKICAgICAg"
    "ICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgoKIyDilIDilIAgU09VTkQgV09SS0VSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTb3VuZFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAg"
    "UGxheXMgYSBzb3VuZCBvZmYgdGhlIG1haW4gdGhyZWFkLgogICAgUHJldmVudHMgYW55IGF1ZGlvIG9wZXJhdGlvbiBmcm9t"
    "IGJsb2NraW5nIHRoZSBVSS4KCiAgICBVc2FnZToKICAgICAgICB3b3JrZXIgPSBTb3VuZFdvcmtlcigiYWxlcnQiKQogICAg"
    "ICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgIyB3b3JrZXIgY2xlYW5zIHVwIG9uIGl0cyBvd24g4oCUIG5vIHJlZmVyZW5j"
    "ZSBuZWVkZWQKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzb3VuZF9uYW1lOiBzdHIpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX25hbWUgPSBzb3VuZF9uYW1lCiAgICAgICAgIyBBdXRvLWRlbGV0ZSB3aGVu"
    "IGRvbmUKICAgICAgICBzZWxmLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5kZWxldGVMYXRlcikKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBwbGF5X3NvdW5kKHNlbGYuX25hbWUpCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZBQ0UgVElNRVIgTUFOQUdFUiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgRm9vdGVyU3RyaXBXaWRnZXQoVmFtcGlyZVN0YXRlU3RyaXApOgogICAgIiIiR2VuZXJpYyBm"
    "b290ZXIgc3RyaXAgd2lkZ2V0IHVzZWQgYnkgdGhlIHBlcm1hbmVudCBsb3dlciBibG9jay4iIiIKCgpjbGFzcyBGYWNlVGlt"
    "ZXJNYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIHRoZSA2MC1zZWNvbmQgZmFjZSBkaXNwbGF5IHRpbWVyLgoKICAgIFJ1"
    "bGVzOgogICAgLSBBZnRlciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24sIGZhY2UgaXMgbG9ja2VkIGZvciA2MCBzZWNvbmRz"
    "LgogICAgLSBJZiB1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UgZHVyaW5nIHRoZSA2MHMsIGZhY2UgaW1tZWRpYXRlbHkKICAg"
    "ICAgc3dpdGNoZXMgdG8gJ2FsZXJ0JyAobG9ja2VkID0gRmFsc2UsIG5ldyBjeWNsZSBiZWdpbnMpLgogICAgLSBBZnRlciA2"
    "MHMgd2l0aCBubyBuZXcgaW5wdXQsIHJldHVybnMgdG8gJ25ldXRyYWwnLgogICAgLSBOZXZlciBibG9ja3MgYW55dGhpbmcu"
    "IFB1cmUgdGltZXIgKyBjYWxsYmFjayBsb2dpYy4KICAgICIiIgoKICAgIEhPTERfU0VDT05EUyA9IDYwCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIG1pcnJvcjogIk1pcnJvcldpZGdldCIsIGVtb3Rpb25fYmxvY2s6ICJFbW90aW9uQmxvY2siKToKICAg"
    "ICAgICBzZWxmLl9taXJyb3IgID0gbWlycm9yCiAgICAgICAgc2VsZi5fZW1vdGlvbiA9IGVtb3Rpb25fYmxvY2sKICAgICAg"
    "ICBzZWxmLl90aW1lciAgID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl90aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAg"
    "ICAgc2VsZi5fdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3JldHVybl90b19uZXV0cmFsKQogICAgICAgIHNlbGYuX2xv"
    "Y2tlZCAgPSBGYWxzZQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBlbW90aW9uOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "U2V0IGZhY2UgYW5kIHN0YXJ0IHRoZSA2MC1zZWNvbmQgaG9sZCB0aW1lci4iIiIKICAgICAgICBzZWxmLl9sb2NrZWQgPSBU"
    "cnVlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKGVtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90"
    "aW9uKGVtb3Rpb24pCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fdGltZXIuc3RhcnQoc2VsZi5I"
    "T0xEX1NFQ09ORFMgKiAxMDAwKQoKICAgIGRlZiBpbnRlcnJ1cHQoc2VsZiwgbmV3X2Vtb3Rpb246IHN0ciA9ICJhbGVydCIp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHdoZW4gdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdlLgogICAg"
    "ICAgIEludGVycnVwdHMgYW55IHJ1bm5pbmcgaG9sZCwgc2V0cyBhbGVydCBmYWNlIGltbWVkaWF0ZWx5LgogICAgICAgICIi"
    "IgogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5f"
    "bWlycm9yLnNldF9mYWNlKG5ld19lbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihuZXdfZW1vdGlv"
    "bikKCiAgICBkZWYgX3JldHVybl90b19uZXV0cmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFs"
    "c2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGlzX2xv"
    "Y2tlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2NrZWQKCgojIOKUgOKUgCBHT09HTEUgU0VSVklD"
    "RSBDTEFTU0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAojIFBvcnRlZCBmcm9tIEdyaW1WZWlsIGRlY2suIEhhbmRsZXMgQ2FsZW5kYXIgYW5kIERy"
    "aXZlL0RvY3MgYXV0aCArIEFQSS4KIyBDcmVkZW50aWFscyBwYXRoOiBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2Ny"
    "ZWRlbnRpYWxzLmpzb24iCiMgVG9rZW4gcGF0aDogICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iCgpj"
    "bGFzcyBHb29nbGVDYWxlbmRhclNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0"
    "aCwgdG9rZW5fcGF0aDogUGF0aCk6CiAgICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAog"
    "ICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gTm9uZQoKICAgIGRl"
    "ZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAgICAgICAgc2VsZi50b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJl"
    "bnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2VsZi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNv"
    "bigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYnVpbGRfc2VydmljZShzZWxmKToKICAgICAgICBwcmludChmIltH"
    "Q2FsXVtERUJVR10gQ3JlZGVudGlhbHMgcGF0aDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iKQogICAgICAgIHByaW50KGYi"
    "W0dDYWxdW0RFQlVHXSBUb2tlbiBwYXRoOiB7c2VsZi50b2tlbl9wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVC"
    "VUddIENyZWRlbnRpYWxzIGZpbGUgZXhpc3RzOiB7c2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpfSIpCiAgICAgICAg"
    "cHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIGZpbGUgZXhpc3RzOiB7c2VsZi50b2tlbl9wYXRoLmV4aXN0cygpfSIpCgog"
    "ICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9y"
    "ICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBD"
    "YWxlbmRhciBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29n"
    "bGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAg"
    "ICAgICAgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAg"
    "ICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZy"
    "b21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlm"
    "IGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAg"
    "ICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNy"
    "ZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFJl"
    "ZnJlc2hpbmcgZXhwaXJlZCBHb29nbGUgdG9rZW4uIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMu"
    "cmVmcmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigK"
    "ICAgICAgICAgICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246"
    "IHtleH0uIHtHT09HTEVfU0NPUEVfUkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYg"
    "bm90IGNyZWRzIG9yIG5vdCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gU3RhcnRpbmcg"
    "T0F1dGggZmxvdyBmb3IgR29vZ2xlIENhbGVuZGFyLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cg"
    "PSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwg"
    "R09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAg"
    "ICAgICAgICAgIHBvcnQ9MCwKICAgICAgICAgICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAg"
    "ICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9tZXNzYWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBV"
    "UkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAgICAgICAgICAgICAg"
    "ICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZ"
    "b3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3Jl"
    "ZHM6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRl"
    "bnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAg"
    "ICAgIHByaW50KCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIikKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBPQXV0aCBmbG93"
    "IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIpCiAgICAgICAgICAgICAgICByYWlzZQogICAgICAgICAgICBs"
    "aW5rX2VzdGFibGlzaGVkID0gVHJ1ZQoKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJjYWxlbmRhciIs"
    "ICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEF1dGhlbnRpY2F0ZWQgR29v"
    "Z2xlIENhbGVuZGFyIHNlcnZpY2UgY3JlYXRlZCBzdWNjZXNzZnVsbHkuIikKICAgICAgICByZXR1cm4gbGlua19lc3RhYmxp"
    "c2hlZAoKICAgIGRlZiBfZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZShzZWxmKSAtPiBzdHI6CiAgICAgICAgbG9jYWxfdHpp"
    "bmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbwogICAgICAgIGNhbmRpZGF0ZXMgPSBbXQogICAgICAg"
    "IGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAgY2FuZGlkYXRlcy5leHRlbmQoWwogICAgICAgICAg"
    "ICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJrZXkiLCBOb25lKSwKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxf"
    "dHppbmZvLCAiem9uZSIsIE5vbmUpLAogICAgICAgICAgICAgICAgc3RyKGxvY2FsX3R6aW5mbyksCiAgICAgICAgICAgICAg"
    "ICBsb2NhbF90emluZm8udHpuYW1lKGRhdGV0aW1lLm5vdygpKSwKICAgICAgICAgICAgXSkKCiAgICAgICAgZW52X3R6ID0g"
    "b3MuZW52aXJvbi5nZXQoIlRaIikKICAgICAgICBpZiBlbnZfdHo6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuYXBwZW5kKGVu"
    "dl90eikKCiAgICAgICAgZm9yIGNhbmRpZGF0ZSBpbiBjYW5kaWRhdGVzOgogICAgICAgICAgICBpZiBub3QgY2FuZGlkYXRl"
    "OgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgbWFwcGVkID0gV0lORE9XU19UWl9UT19JQU5BLmdldChj"
    "YW5kaWRhdGUsIGNhbmRpZGF0ZSkKICAgICAgICAgICAgaWYgIi8iIGluIG1hcHBlZDoKICAgICAgICAgICAgICAgIHJldHVy"
    "biBtYXBwZWQKCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bV0FSTl0gVW5hYmxlIHRvIHJlc29sdmUgbG9j"
    "YWwgSUFOQSB0aW1lem9uZS4gIgogICAgICAgICAgICBmIkZhbGxpbmcgYmFjayB0byB7REVGQVVMVF9HT09HTEVfSUFOQV9U"
    "SU1FWk9ORX0uIgogICAgICAgICkKICAgICAgICByZXR1cm4gREVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORQoKICAgIGRl"
    "ZiBjcmVhdGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgdGFzazogZGljdCk6CiAgICAgICAgZHVlX2F0ID0gcGFyc2VfaXNvX2Zv"
    "cl9jb21wYXJlKHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0YXNrLmdldCgiZHVlIiksIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVf"
    "ZXZlbnRfZHVlIikKICAgICAgICBpZiBub3QgZHVlX2F0OgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJUYXNrIGR1"
    "ZSB0aW1lIGlzIG1pc3Npbmcgb3IgaW52YWxpZC4iKQoKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAg"
    "ICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9z"
    "ZXJ2aWNlKCkKCiAgICAgICAgZHVlX2xvY2FsID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR1ZV9hdCwgY29u"
    "dGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWVfbG9jYWwiKQogICAgICAgIHN0YXJ0X2R0ID0gZHVlX2xvY2FsLnJlcGxh"
    "Y2UobWljcm9zZWNvbmQ9MCwgdHppbmZvPU5vbmUpCiAgICAgICAgZW5kX2R0ID0gc3RhcnRfZHQgKyB0aW1lZGVsdGEobWlu"
    "dXRlcz0zMCkKICAgICAgICB0el9uYW1lID0gc2VsZi5fZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCgogICAgICAgIGV2"
    "ZW50X3BheWxvYWQgPSB7CiAgICAgICAgICAgICJzdW1tYXJ5IjogKHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVyIiku"
    "c3RyaXAoKSwKICAgICAgICAgICAgInN0YXJ0IjogeyJkYXRlVGltZSI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0i"
    "c2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICAgICAgImVuZCI6IHsiZGF0ZVRpbWUiOiBlbmRfZHQu"
    "aXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgIH0KICAgICAgICB0"
    "YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVGFyZ2V0IGNhbGVu"
    "ZGFyIElEOiB7dGFyZ2V0X2NhbGVuZGFyX2lkfSIpCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bREVCVUdd"
    "IEV2ZW50IHBheWxvYWQgYmVmb3JlIGluc2VydDogIgogICAgICAgICAgICBmInRpdGxlPSd7ZXZlbnRfcGF5bG9hZC5nZXQo"
    "J3N1bW1hcnknKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQn"
    "LCB7fSkuZ2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJzdGFydC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQu"
    "Z2V0KCdzdGFydCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JywgIgogICAgICAgICAgICBmImVuZC5kYXRlVGltZT0ne2V2ZW50"
    "X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJlbmQudGltZVpvbmU9"
    "J3tldmVudF9wYXlsb2FkLmdldCgnZW5kJywge30pLmdldCgndGltZVpvbmUnKX0nIgogICAgICAgICkKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPXRhcmdldF9j"
    "YWxlbmRhcl9pZCwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJV"
    "R10gRXZlbnQgaW5zZXJ0IGNhbGwgc3VjY2VlZGVkLiIpCiAgICAgICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwg"
    "bGlua19lc3RhYmxpc2hlZAogICAgICAgIGV4Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBh"
    "cGlfZGV0YWlsID0gIiIKICAgICAgICAgICAgaWYgaGFzYXR0cihhcGlfZXgsICJjb250ZW50IikgYW5kIGFwaV9leC5jb250"
    "ZW50OgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBhcGlfZXguY29udGVu"
    "dC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IHN0cihhcGlfZXguY29udGVudCkKICAgICAgICAgICAgZGV0YWlsX21z"
    "ZyA9IGYiR29vZ2xlIEFQSSBlcnJvcjoge2FwaV9leH0iCiAgICAgICAgICAgIGlmIGFwaV9kZXRhaWw6CiAgICAgICAgICAg"
    "ICAgICBkZXRhaWxfbXNnID0gZiJ7ZGV0YWlsX21zZ30gfCBBUEkgYm9keToge2FwaV9kZXRhaWx9IgogICAgICAgICAgICBw"
    "cmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZDoge2RldGFpbF9tc2d9IikKICAgICAgICAgICAgcmFp"
    "c2UgUnVudGltZUVycm9yKGRldGFpbF9tc2cpIGZyb20gYXBpX2V4CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoK"
    "ICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBmYWlsZWQgd2l0aCB1bmV4cGVjdGVkIGVy"
    "cm9yOiB7ZXh9IikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9hZChzZWxmLCBl"
    "dmVudF9wYXlsb2FkOiBkaWN0LCBjYWxlbmRhcl9pZDogc3RyID0gInByaW1hcnkiKToKICAgICAgICBpZiBub3QgaXNpbnN0"
    "YW5jZShldmVudF9wYXlsb2FkLCBkaWN0KToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29vZ2xlIGV2ZW50IHBh"
    "eWxvYWQgbXVzdCBiZSBhIGRpY3Rpb25hcnkuIikKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9zZXJ2"
    "aWNlKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD0oY2FsZW5k"
    "YXJfaWQgb3IgInByaW1hcnkiKSwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRl"
    "ZC5nZXQoImlkIiksIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgbGlzdF9wcmltYXJ5X2V2ZW50cyhzZWxmLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHRpbWVfbWluOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHN5bmNfdG9rZW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbWF4X3Jlc3VsdHM6IGludCA9"
    "IDI1MDApOgogICAgICAgICIiIgogICAgICAgIEZldGNoIGNhbGVuZGFyIGV2ZW50cyB3aXRoIHBhZ2luYXRpb24gYW5kIHN5"
    "bmNUb2tlbiBzdXBwb3J0LgogICAgICAgIFJldHVybnMgKGV2ZW50c19saXN0LCBuZXh0X3N5bmNfdG9rZW4pLgoKICAgICAg"
    "ICBzeW5jX3Rva2VuIG1vZGU6IGluY3JlbWVudGFsIOKAlCByZXR1cm5zIE9OTFkgY2hhbmdlcyAoYWRkcy9lZGl0cy9jYW5j"
    "ZWxzKS4KICAgICAgICB0aW1lX21pbiBtb2RlOiAgIGZ1bGwgc3luYyBmcm9tIGEgZGF0ZS4KICAgICAgICBCb3RoIHVzZSBz"
    "aG93RGVsZXRlZD1UcnVlIHNvIGNhbmNlbGxhdGlvbnMgY29tZSB0aHJvdWdoLgogICAgICAgICIiIgogICAgICAgIGlmIHNl"
    "bGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGlmIHN5bmNf"
    "dG9rZW46CiAgICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAgImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAg"
    "ICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzaG93RGVsZXRlZCI6IFRydWUs"
    "CiAgICAgICAgICAgICAgICAic3luY1Rva2VuIjogc3luY190b2tlbiwKICAgICAgICAgICAgfQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAgImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAgICAgICAgICAg"
    "ICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzaG93RGVsZXRlZCI6IFRydWUsCiAgICAgICAg"
    "ICAgICAgICAibWF4UmVzdWx0cyI6IDI1MCwKICAgICAgICAgICAgICAgICJvcmRlckJ5IjogInN0YXJ0VGltZSIsCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgaWYgdGltZV9taW46CiAgICAgICAgICAgICAgICBxdWVyeVsidGltZU1pbiJdID0gdGlt"
    "ZV9taW4KCiAgICAgICAgYWxsX2V2ZW50cyA9IFtdCiAgICAgICAgbmV4dF9zeW5jX3Rva2VuID0gTm9uZQogICAgICAgIHdo"
    "aWxlIFRydWU6CiAgICAgICAgICAgIHJlc3BvbnNlID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5saXN0KCoqcXVlcnkpLmV4"
    "ZWN1dGUoKQogICAgICAgICAgICBhbGxfZXZlbnRzLmV4dGVuZChyZXNwb25zZS5nZXQoIml0ZW1zIiwgW10pKQogICAgICAg"
    "ICAgICBuZXh0X3N5bmNfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRTeW5jVG9rZW4iKQogICAgICAgICAgICBwYWdlX3Rv"
    "a2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0UGFnZVRva2VuIikKICAgICAgICAgICAgaWYgbm90IHBhZ2VfdG9rZW46CiAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgICAgICAgICBxdWVyeS5wb3AoInN5bmNUb2tlbiIsIE5vbmUpCiAgICAgICAgICAgIHF1"
    "ZXJ5WyJwYWdlVG9rZW4iXSA9IHBhZ2VfdG9rZW4KCiAgICAgICAgcmV0dXJuIGFsbF9ldmVudHMsIG5leHRfc3luY190b2tl"
    "bgoKICAgIGRlZiBnZXRfZXZlbnQoc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVf"
    "ZXZlbnRfaWQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9zZXJ2"
    "aWNlLmV2ZW50cygpLmdldChjYWxlbmRhcklkPSJwcmltYXJ5IiwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUo"
    "KQogICAgICAgIGV4Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBjb2RlID0gZ2V0YXR0cihn"
    "ZXRhdHRyKGFwaV9leCwgInJlc3AiLCBOb25lKSwgInN0YXR1cyIsIE5vbmUpCiAgICAgICAgICAgIGlmIGNvZGUgaW4gKDQw"
    "NCwgNDEwKToKICAgICAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGRlbGV0ZV9l"
    "dmVudF9mb3JfdGFzayhzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9p"
    "ZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29vZ2xlIGV2ZW50IGlkIGlzIG1pc3Npbmc7IGNhbm5vdCBkZWxl"
    "dGUgZXZlbnQuIikKCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9z"
    "ZXJ2aWNlKCkKCiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgc2VsZi5fc2VydmljZS5l"
    "dmVudHMoKS5kZWxldGUoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJfaWQsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5l"
    "eGVjdXRlKCkKCgpjbGFzcyBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRp"
    "YWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgsIGxvZ2dlcj1Ob25lKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxz"
    "X3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNl"
    "bGYuX2RyaXZlX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gTm9uZQogICAgICAgIHNlbGYu"
    "X2xvZ2dlciA9IGxvZ2dlcgoKICAgIGRlZiBfbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIik6"
    "CiAgICAgICAgaWYgY2FsbGFibGUoc2VsZi5fbG9nZ2VyKToKICAgICAgICAgICAgc2VsZi5fbG9nZ2VyKG1lc3NhZ2UsIGxl"
    "dmVsPWxldmVsKQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAgICAgICAgc2VsZi50b2tlbl9wYXRo"
    "LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2VsZi50b2tlbl9wYXRoLndyaXRl"
    "X3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYXV0aGVudGljYXRlKHNlbGYpOgog"
    "ICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgc2VsZi5fbG9nKCJE"
    "b2NzIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAg"
    "ICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRFcnJvciIKICAgICAgICAgICAgcmFp"
    "c2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAgICAgICBp"
    "ZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJv"
    "cigKICAgICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtz"
    "ZWxmLmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGlmIHNl"
    "bGYudG9rZW5fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhv"
    "cml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRva2VuX3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBh"
    "bmQgY3JlZHMudmFsaWQgYW5kIG5vdCBjcmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlz"
    "ZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBp"
    "cmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZy"
    "ZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAg"
    "ICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4"
    "fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3Qg"
    "Y3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBzZWxmLl9sb2coIlN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9y"
    "IEdvb2dsZSBEcml2ZS9Eb2NzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxv"
    "dyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgp"
    "LCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAg"
    "ICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAg"
    "ICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlz"
    "IFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAg"
    "ICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUu"
    "IFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBj"
    "cmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3Jl"
    "ZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fbG9nKCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIiwgbGV2ZWw9"
    "IklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9nKGYi"
    "T0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAg"
    "ICAgICAgcmFpc2UKCiAgICAgICAgcmV0dXJuIGNyZWRzCgogICAgZGVmIGVuc3VyZV9zZXJ2aWNlcyhzZWxmKToKICAgICAg"
    "ICBpZiBzZWxmLl9kcml2ZV9zZXJ2aWNlIGlzIG5vdCBOb25lIGFuZCBzZWxmLl9kb2NzX3NlcnZpY2UgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlZHMgPSBzZWxmLl9hdXRoZW50aWNhdGUo"
    "KQogICAgICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkcml2ZSIsICJ2MyIsIGNyZWRlbnRp"
    "YWxzPWNyZWRzKQogICAgICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRvY3MiLCAidjEiLCBj"
    "cmVkZW50aWFscz1jcmVkcykKICAgICAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklO"
    "Rk8iKQogICAgICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBhdXRoIGZhaWx1cmU6IHtleH0i"
    "LCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICBzZWxmLl9sb2coZiJEb2NzIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVs"
    "PSJFUlJPUiIpCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGxpc3RfZm9sZGVyX2l0ZW1zKHNlbGYsIGZvbGRlcl9pZDog"
    "c3RyID0gInJvb3QiLCBwYWdlX3NpemU6IGludCA9IDEwMCk6CiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAg"
    "ICAgIHNhZmVfZm9sZGVyX2lkID0gKGZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2Vs"
    "Zi5fbG9nKGYiRHJpdmUgZmlsZSBsaXN0IGZldGNoIHN0YXJ0ZWQuIGZvbGRlcl9pZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2"
    "ZWw9IklORk8iKQogICAgICAgIHJlc3BvbnNlID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmxpc3QoCiAgICAgICAg"
    "ICAgIHE9ZiIne3NhZmVfZm9sZGVyX2lkfScgaW4gcGFyZW50cyBhbmQgdHJhc2hlZD1mYWxzZSIsCiAgICAgICAgICAgIHBh"
    "Z2VTaXplPW1heCgxLCBtaW4oaW50KHBhZ2Vfc2l6ZSBvciAxMDApLCAyMDApKSwKICAgICAgICAgICAgb3JkZXJCeT0iZm9s"
    "ZGVyLG5hbWUsbW9kaWZpZWRUaW1lIGRlc2MiLAogICAgICAgICAgICBmaWVsZHM9KAogICAgICAgICAgICAgICAgImZpbGVz"
    "KCIKICAgICAgICAgICAgICAgICJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzLHNp"
    "emUsIgogICAgICAgICAgICAgICAgImxhc3RNb2RpZnlpbmdVc2VyKGRpc3BsYXlOYW1lLGVtYWlsQWRkcmVzcykiCiAgICAg"
    "ICAgICAgICAgICAiKSIKICAgICAgICAgICAgKSwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGZpbGVzID0gcmVzcG9u"
    "c2UuZ2V0KCJmaWxlcyIsIFtdKQogICAgICAgIGZvciBpdGVtIGluIGZpbGVzOgogICAgICAgICAgICBtaW1lID0gKGl0ZW0u"
    "Z2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1bImlzX2ZvbGRlciJdID0gbWltZSA9PSAi"
    "YXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciIKICAgICAgICAgICAgaXRlbVsiaXNfZ29vZ2xlX2RvYyJdID0g"
    "bWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZl"
    "IGl0ZW1zIHJldHVybmVkOiB7bGVuKGZpbGVzKX0gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIp"
    "CiAgICAgICAgcmV0dXJuIGZpbGVzCgogICAgZGVmIGdldF9kb2NfcHJldmlldyhzZWxmLCBkb2NfaWQ6IHN0ciwgbWF4X2No"
    "YXJzOiBpbnQgPSAxODAwKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJE"
    "b2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBkb2MgPSBz"
    "ZWxmLl9kb2NzX3NlcnZpY2UuZG9jdW1lbnRzKCkuZ2V0KGRvY3VtZW50SWQ9ZG9jX2lkKS5leGVjdXRlKCkKICAgICAgICB0"
    "aXRsZSA9IGRvYy5nZXQoInRpdGxlIikgb3IgIlVudGl0bGVkIgogICAgICAgIGJvZHkgPSBkb2MuZ2V0KCJib2R5Iiwge30p"
    "LmdldCgiY29udGVudCIsIFtdKQogICAgICAgIGNodW5rcyA9IFtdCiAgICAgICAgZm9yIGJsb2NrIGluIGJvZHk6CiAgICAg"
    "ICAgICAgIHBhcmFncmFwaCA9IGJsb2NrLmdldCgicGFyYWdyYXBoIikKICAgICAgICAgICAgaWYgbm90IHBhcmFncmFwaDoK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGVsZW1lbnRzID0gcGFyYWdyYXBoLmdldCgiZWxlbWVudHMi"
    "LCBbXSkKICAgICAgICAgICAgZm9yIGVsIGluIGVsZW1lbnRzOgogICAgICAgICAgICAgICAgcnVuID0gZWwuZ2V0KCJ0ZXh0"
    "UnVuIikKICAgICAgICAgICAgICAgIGlmIG5vdCBydW46CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAg"
    "ICAgICAgIHRleHQgPSAocnVuLmdldCgiY29udGVudCIpIG9yICIiKS5yZXBsYWNlKCJceDBiIiwgIlxuIikKICAgICAgICAg"
    "ICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgY2h1bmtzLmFwcGVuZCh0ZXh0KQogICAgICAgIHBhcnNlZCA9"
    "ICIiLmpvaW4oY2h1bmtzKS5zdHJpcCgpCiAgICAgICAgaWYgbGVuKHBhcnNlZCkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAg"
    "IHBhcnNlZCA9IHBhcnNlZFs6bWF4X2NoYXJzXS5yc3RyaXAoKSArICLigKYiCiAgICAgICAgcmV0dXJuIHsKICAgICAgICAg"
    "ICAgInRpdGxlIjogdGl0bGUsCiAgICAgICAgICAgICJkb2N1bWVudF9pZCI6IGRvY19pZCwKICAgICAgICAgICAgInJldmlz"
    "aW9uX2lkIjogZG9jLmdldCgicmV2aXNpb25JZCIpLAogICAgICAgICAgICAicHJldmlld190ZXh0IjogcGFyc2VkIG9yICJb"
    "Tm8gdGV4dCBjb250ZW50IHJldHVybmVkIGZyb20gRG9jcyBBUEkuXSIsCiAgICAgICAgfQoKICAgIGRlZiBjcmVhdGVfZG9j"
    "KHNlbGYsIHRpdGxlOiBzdHIgPSAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiLCBwYXJlbnRfZm9sZGVyX2lkOiBzdHIgPSAicm9v"
    "dCIpOgogICAgICAgIHNhZmVfdGl0bGUgPSAodGl0bGUgb3IgIk5ldyBHcmltVmVpbGUgUmVjb3JkIikuc3RyaXAoKSBvciAi"
    "TmV3IEdyaW1WZWlsZSBSZWNvcmQiCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNhZmVfcGFyZW50"
    "X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIGNyZWF0ZWQgPSBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAgICAgICAgICAgICJu"
    "YW1lIjogc2FmZV90aXRsZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFw"
    "cHMuZG9jdW1lbnQiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAgICB9"
    "LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMi"
    "LAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZG9jX2lkID0gY3JlYXRlZC5nZXQoImlkIikKICAgICAgICBtZXRhID0g"
    "c2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpIGlmIGRvY19pZCBlbHNlIHt9CiAgICAgICAgcmV0dXJuIHsKICAgICAg"
    "ICAgICAgImlkIjogZG9jX2lkLAogICAgICAgICAgICAibmFtZSI6IG1ldGEuZ2V0KCJuYW1lIikgb3Igc2FmZV90aXRsZSwK"
    "ICAgICAgICAgICAgIm1pbWVUeXBlIjogbWV0YS5nZXQoIm1pbWVUeXBlIikgb3IgImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUt"
    "YXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICJtb2RpZmllZFRpbWUiOiBtZXRhLmdldCgibW9kaWZpZWRUaW1lIiksCiAg"
    "ICAgICAgICAgICJ3ZWJWaWV3TGluayI6IG1ldGEuZ2V0KCJ3ZWJWaWV3TGluayIpLAogICAgICAgICAgICAicGFyZW50cyI6"
    "IG1ldGEuZ2V0KCJwYXJlbnRzIikgb3IgW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9mb2xk"
    "ZXIoc2VsZiwgbmFtZTogc3RyID0gIk5ldyBGb2xkZXIiLCBwYXJlbnRfZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIpOgogICAg"
    "ICAgIHNhZmVfbmFtZSA9IChuYW1lIG9yICJOZXcgRm9sZGVyIikuc3RyaXAoKSBvciAiTmV3IEZvbGRlciIKICAgICAgICBz"
    "YWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBz"
    "ZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVh"
    "dGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX25hbWUsCiAgICAgICAgICAgICAg"
    "ICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciIsCiAgICAgICAgICAgICAgICAicGFy"
    "ZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1l"
    "VHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICByZXR1"
    "cm4gY3JlYXRlZAoKICAgIGRlZiBnZXRfZmlsZV9tZXRhZGF0YShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5v"
    "dCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAg"
    "c2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0KAog"
    "ICAgICAgICAgICBmaWxlSWQ9ZmlsZV9pZCwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVk"
    "VGltZSx3ZWJWaWV3TGluayxwYXJlbnRzLHNpemUiLAogICAgICAgICkuZXhlY3V0ZSgpCgogICAgZGVmIGdldF9kb2NfbWV0"
    "YWRhdGEoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHJldHVybiBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkK"
    "CiAgICBkZWYgZGVsZXRlX2l0ZW0oc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAg"
    "ICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZp"
    "Y2VzKCkKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZGVsZXRlKGZpbGVJZD1maWxlX2lkKS5leGVjdXRl"
    "KCkKCiAgICBkZWYgZGVsZXRlX2RvYyhzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgc2VsZi5kZWxldGVfaXRlbShkb2Nf"
    "aWQpCgogICAgZGVmIGV4cG9ydF9kb2NfdGV4dChzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGRvY19pZDoK"
    "ICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVu"
    "c3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcGF5bG9hZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5leHBvcnQoCiAg"
    "ICAgICAgICAgIGZpbGVJZD1kb2NfaWQsCiAgICAgICAgICAgIG1pbWVUeXBlPSJ0ZXh0L3BsYWluIiwKICAgICAgICApLmV4"
    "ZWN1dGUoKQogICAgICAgIGlmIGlzaW5zdGFuY2UocGF5bG9hZCwgYnl0ZXMpOgogICAgICAgICAgICByZXR1cm4gcGF5bG9h"
    "ZC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICByZXR1cm4gc3RyKHBheWxvYWQgb3IgIiIpCgog"
    "ICAgZGVmIGRvd25sb2FkX2ZpbGVfYnl0ZXMoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoK"
    "ICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJl"
    "X3NlcnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmdldF9tZWRpYShmaWxlSWQ9"
    "ZmlsZV9pZCkuZXhlY3V0ZSgpCgoKCgojIOKUgOKUgCBQQVNTIDMgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgQWxsIHdvcmtlciB0aHJlYWRzIGRlZmluZWQuIEFsbCBnZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4KIyBO"
    "byBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZCBhbnl3aGVyZSBpbiB0aGlzIGZpbGUuCiMKIyBOZXh0OiBQYXNzIDQg"
    "4oCUIE1lbW9yeSAmIFN0b3JhZ2UKIyAoTWVtb3J5TWFuYWdlciwgU2Vzc2lvbk1hbmFnZXIsIExlc3NvbnNMZWFybmVkREIs"
    "IFRhc2tNYW5hZ2VyKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA0OiBNRU1P"
    "UlkgJiBTVE9SQUdFCiMKIyBTeXN0ZW1zIGRlZmluZWQgaGVyZToKIyAgIERlcGVuZGVuY3lDaGVja2VyICAg4oCUIHZhbGlk"
    "YXRlcyBhbGwgcmVxdWlyZWQgcGFja2FnZXMgb24gc3RhcnR1cAojICAgTWVtb3J5TWFuYWdlciAgICAgICDigJQgSlNPTkwg"
    "bWVtb3J5IHJlYWQvd3JpdGUvc2VhcmNoCiMgICBTZXNzaW9uTWFuYWdlciAgICAgIOKAlCBhdXRvLXNhdmUsIGxvYWQsIGNv"
    "bnRleHQgaW5qZWN0aW9uLCBzZXNzaW9uIGluZGV4CiMgICBMZXNzb25zTGVhcm5lZERCICAgIOKAlCBMU0wgRm9yYmlkZGVu"
    "IFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMga25vd2xlZGdlIGJhc2UKIyAgIFRhc2tNYW5hZ2VyICAgICAgICAg4oCUIHRhc2sv"
    "cmVtaW5kZXIgQ1JVRCwgZHVlLWV2ZW50IGRldGVjdGlvbgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIERF"
    "UEVOREVOQ1kgQ0hFQ0tFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRGVwZW5kZW5jeUNoZWNrZXI6CiAgICAi"
    "IiIKICAgIFZhbGlkYXRlcyBhbGwgcmVxdWlyZWQgYW5kIG9wdGlvbmFsIHBhY2thZ2VzIG9uIHN0YXJ0dXAuCiAgICBSZXR1"
    "cm5zIGEgbGlzdCBvZiBzdGF0dXMgbWVzc2FnZXMgZm9yIHRoZSBEaWFnbm9zdGljcyB0YWIuCiAgICBTaG93cyBhIGJsb2Nr"
    "aW5nIGVycm9yIGRpYWxvZyBmb3IgYW55IGNyaXRpY2FsIG1pc3NpbmcgZGVwZW5kZW5jeS4KICAgICIiIgoKICAgICMgKHBh"
    "Y2thZ2VfbmFtZSwgaW1wb3J0X25hbWUsIGNyaXRpY2FsLCBpbnN0YWxsX2hpbnQpCiAgICBQQUNLQUdFUyA9IFsKICAgICAg"
    "ICAoIlB5U2lkZTYiLCAgICAgICAgICAgICAgICAgICAiUHlTaWRlNiIsICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgUHlTaWRlNiIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiLCAg"
    "ICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBsb2d1cnUiKSwKICAgICAgICAoImFwc2NoZWR1bGVy"
    "IiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiLCAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgYXBz"
    "Y2hlZHVsZXIiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiwgICAgICAgICAgICAg"
    "ICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5Z2FtZSAgKG5lZWRlZCBmb3Igc291bmQpIiksCiAgICAgICAgKCJw"
    "eXdpbjMyIiwgICAgICAgICAgICAgICAgICAgIndpbjMyY29tIiwgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAg"
    "aW5zdGFsbCBweXdpbjMyICAobmVlZGVkIGZvciBkZXNrdG9wIHNob3J0Y3V0KSIpLAogICAgICAgICgicHN1dGlsIiwgICAg"
    "ICAgICAgICAgICAgICAgICJwc3V0aWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHN1"
    "dGlsICAobmVlZGVkIGZvciBzeXN0ZW0gbW9uaXRvcmluZykiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAgICAgICAg"
    "ICAgICAicmVxdWVzdHMiLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHJlcXVlc3RzIiksCiAg"
    "ICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIsICAgICAgRmFsc2UsCiAgICAg"
    "ICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiKSwKICAgICAgICAoImdvb2dsZS1hdXRoLW9hdXRo"
    "bGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiLCBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1h"
    "dXRoLW9hdXRobGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5hdXRoIiwgICAg"
    "ICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aCIpLAogICAgICAgICgidG9yY2giLCAgICAg"
    "ICAgICAgICAgICAgICAgICJ0b3JjaCIsICAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdG9y"
    "Y2ggIChvbmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgICAg"
    "ICAgInRyYW5zZm9ybWVycyIsICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0cmFuc2Zvcm1lcnMgIChv"
    "bmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJweW52bWwiLCAgICAgICAgICAgICAgICAgICAgInB5"
    "bnZtbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweW52bWwgIChvbmx5IG5lZWRlZCBm"
    "b3IgTlZJRElBIEdQVSBtb25pdG9yaW5nKSIpLAogICAgXQoKICAgIEBjbGFzc21ldGhvZAogICAgZGVmIGNoZWNrKGNscykg"
    "LT4gdHVwbGVbbGlzdFtzdHJdLCBsaXN0W3N0cl1dOgogICAgICAgICIiIgogICAgICAgIFJldHVybnMgKG1lc3NhZ2VzLCBj"
    "cml0aWNhbF9mYWlsdXJlcykuCiAgICAgICAgbWVzc2FnZXM6IGxpc3Qgb2YgIltERVBTXSBwYWNrYWdlIOKcky/inJcg4oCU"
    "IG5vdGUiIHN0cmluZ3MKICAgICAgICBjcml0aWNhbF9mYWlsdXJlczogbGlzdCBvZiBwYWNrYWdlcyB0aGF0IGFyZSBjcml0"
    "aWNhbCBhbmQgbWlzc2luZwogICAgICAgICIiIgogICAgICAgIGltcG9ydCBpbXBvcnRsaWIKICAgICAgICBtZXNzYWdlcyAg"
    "PSBbXQogICAgICAgIGNyaXRpY2FsICA9IFtdCgogICAgICAgIGZvciBwa2dfbmFtZSwgaW1wb3J0X25hbWUsIGlzX2NyaXRp"
    "Y2FsLCBoaW50IGluIGNscy5QQUNLQUdFUzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaW1wb3J0bGliLmlt"
    "cG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoZiJbREVQU10ge3BrZ19u"
    "YW1lfSDinJMiKQogICAgICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgICAgICBzdGF0dXMgPSAiQ1JJ"
    "VElDQUwiIGlmIGlzX2NyaXRpY2FsIGVsc2UgIm9wdGlvbmFsIgogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgICAgIGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyXICh7c3RhdHVzfSkg4oCUIHtoaW50fSIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIGlzX2NyaXRpY2FsOgogICAgICAgICAgICAgICAgICAgIGNyaXRpY2Fs"
    "LmFwcGVuZChwa2dfbmFtZSkKCiAgICAgICAgcmV0dXJuIG1lc3NhZ2VzLCBjcml0aWNhbAoKICAgIEBjbGFzc21ldGhvZAog"
    "ICAgZGVmIGNoZWNrX29sbGFtYShjbHMpIC0+IHN0cjoKICAgICAgICAiIiJDaGVjayBpZiBPbGxhbWEgaXMgcnVubmluZy4g"
    "UmV0dXJucyBzdGF0dXMgc3RyaW5nLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0"
    "LlJlcXVlc3QoImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJl"
    "cXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MikKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgPT0gMjAwOgogICAgICAg"
    "ICAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKckyDigJQgcnVubmluZyBvbiBsb2NhbGhvc3Q6MTE0MzQiCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJcg"
    "4oCUIG5vdCBydW5uaW5nIChvbmx5IG5lZWRlZCBmb3IgT2xsYW1hIG1vZGVsIHR5cGUpIgoKCiMg4pSA4pSAIE1FTU9SWSBN"
    "QU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNZW1vcnlNYW5hZ2VyOgogICAgIiIi"
    "CiAgICBIYW5kbGVzIGFsbCBKU09OTCBtZW1vcnkgb3BlcmF0aW9ucy4KCiAgICBGaWxlcyBtYW5hZ2VkOgogICAgICAgIG1l"
    "bW9yaWVzL21lc3NhZ2VzLmpzb25sICAgICAgICAg4oCUIGV2ZXJ5IG1lc3NhZ2UsIHRpbWVzdGFtcGVkCiAgICAgICAgbWVt"
    "b3JpZXMvbWVtb3JpZXMuanNvbmwgICAgICAgICDigJQgZXh0cmFjdGVkIG1lbW9yeSByZWNvcmRzCiAgICAgICAgbWVtb3Jp"
    "ZXMvc3RhdGUuanNvbiAgICAgICAgICAgICDigJQgZW50aXR5IHN0YXRlCiAgICAgICAgbWVtb3JpZXMvaW5kZXguanNvbiAg"
    "ICAgICAgICAgICDigJQgY291bnRzIGFuZCBtZXRhZGF0YQoKICAgIE1lbW9yeSByZWNvcmRzIGhhdmUgdHlwZSBpbmZlcmVu"
    "Y2UsIGtleXdvcmQgZXh0cmFjdGlvbiwgdGFnIGdlbmVyYXRpb24sCiAgICBuZWFyLWR1cGxpY2F0ZSBkZXRlY3Rpb24sIGFu"
    "ZCByZWxldmFuY2Ugc2NvcmluZyBmb3IgY29udGV4dCBpbmplY3Rpb24uCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "Zik6CiAgICAgICAgYmFzZSAgICAgICAgICAgICA9IGNmZ19wYXRoKCJtZW1vcmllcyIpCiAgICAgICAgc2VsZi5tZXNzYWdl"
    "c19wICA9IGJhc2UgLyAibWVzc2FnZXMuanNvbmwiCiAgICAgICAgc2VsZi5tZW1vcmllc19wICA9IGJhc2UgLyAibWVtb3Jp"
    "ZXMuanNvbmwiCiAgICAgICAgc2VsZi5zdGF0ZV9wICAgICA9IGJhc2UgLyAic3RhdGUuanNvbiIKICAgICAgICBzZWxmLmlu"
    "ZGV4X3AgICAgID0gYmFzZSAvICJpbmRleC5qc29uIgoKICAgICMg4pSA4pSAIFNUQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgZGVmIGxvYWRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAgICBpZiBub3Qgc2VsZi5zdGF0ZV9w"
    "LmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICByZXR1cm4ganNvbi5sb2FkcyhzZWxmLnN0YXRlX3AucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKCiAgICBkZWYgc2F2"
    "ZV9zdGF0ZShzZWxmLCBzdGF0ZTogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXRlX3Aud3JpdGVfdGV4dCgKICAg"
    "ICAgICAgICAganNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoKICAgIGRl"
    "ZiBfZGVmYXVsdF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJwZXJzb25hX25h"
    "bWUiOiAgICAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJkZWNrX3ZlcnNpb24iOiAgICAgICAgICAgICBBUFBf"
    "VkVSU0lPTiwKICAgICAgICAgICAgInNlc3Npb25fY291bnQiOiAgICAgICAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3N0"
    "YXJ0dXAiOiAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9zaHV0ZG93biI6ICAgICAgICAgICAgTm9uZSwK"
    "ICAgICAgICAgICAgImxhc3RfYWN0aXZlIjogICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJ0b3RhbF9tZXNzYWdl"
    "cyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAg"
    "ImludGVybmFsX25hcnJhdGl2ZSI6ICAgICAgIHt9LAogICAgICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6"
    "IkRPUk1BTlQiLAogICAgICAgIH0KCiAgICAjIOKUgOKUgCBNRVNTQUdFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBhcHBlbmRfbWVzc2FnZShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHJvbGU6IHN0ciwKICAgICAgICAgICAgICAgICAgICAg"
    "ICBjb250ZW50OiBzdHIsIGVtb3Rpb246IHN0ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAg"
    "ICAgImlkIjogICAgICAgICBmIm1zZ197dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAi"
    "OiAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6IHNlc3Npb25faWQsCiAgICAgICAgICAgICJw"
    "ZXJzb25hIjogICAgREVDS19OQU1FLAogICAgICAgICAgICAicm9sZSI6ICAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250"
    "ZW50IjogICAgY29udGVudCwKICAgICAgICAgICAgImVtb3Rpb24iOiAgICBlbW90aW9uLAogICAgICAgIH0KICAgICAgICBh"
    "cHBlbmRfanNvbmwoc2VsZi5tZXNzYWdlc19wLCByZWNvcmQpCiAgICAgICAgcmV0dXJuIHJlY29yZAoKICAgIGRlZiBsb2Fk"
    "X3JlY2VudF9tZXNzYWdlcyhzZWxmLCBsaW1pdDogaW50ID0gMjApIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJl"
    "YWRfanNvbmwoc2VsZi5tZXNzYWdlc19wKVstbGltaXQ6XQoKICAgICMg4pSA4pSAIE1FTU9SSUVTIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZW1vcnkoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAg"
    "ICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJlY29y"
    "ZF90eXBlID0gaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKICAgICAgICBrZXl3b3JkcyAg"
    "ICA9IGV4dHJhY3Rfa2V5d29yZHModXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpCiAgICAgICAgdGFncyAgICAg"
    "ICAgPSBzZWxmLl9pbmZlcl90YWdzKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHRpdGxlICAg"
    "ICAgID0gc2VsZi5faW5mZXJfdGl0bGUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgc3VtbWFy"
    "eSAgICAgPSBzZWxmLl9zdW1tYXJpemUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQpCgogICAgICAg"
    "IG1lbW9yeSA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmIm1lbV97dXVpZC51dWlkNCgpLmhleFs6MTJd"
    "fSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiAgICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lv"
    "bl9pZCI6ICAgICAgIHNlc3Npb25faWQsCiAgICAgICAgICAgICJwZXJzb25hIjogICAgICAgICAgREVDS19OQU1FLAogICAg"
    "ICAgICAgICAidHlwZSI6ICAgICAgICAgICAgIHJlY29yZF90eXBlLAogICAgICAgICAgICAidGl0bGUiOiAgICAgICAgICAg"
    "IHRpdGxlLAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJjb250ZW50Ijog"
    "ICAgICAgICAgdXNlcl90ZXh0Wzo0MDAwXSwKICAgICAgICAgICAgImFzc2lzdGFudF9jb250ZXh0Ijphc3Npc3RhbnRfdGV4"
    "dFs6MTIwMF0sCiAgICAgICAgICAgICJrZXl3b3JkcyI6ICAgICAgICAga2V5d29yZHMsCiAgICAgICAgICAgICJ0YWdzIjog"
    "ICAgICAgICAgICAgdGFncywKICAgICAgICAgICAgImNvbmZpZGVuY2UiOiAgICAgICAwLjcwIGlmIHJlY29yZF90eXBlIGlu"
    "IHsKICAgICAgICAgICAgICAgICJkcmVhbSIsImlzc3VlIiwiaWRlYSIsInByZWZlcmVuY2UiLCJyZXNvbHV0aW9uIgogICAg"
    "ICAgICAgICB9IGVsc2UgMC41NSwKICAgICAgICB9CgogICAgICAgIGlmIHNlbGYuX2lzX25lYXJfZHVwbGljYXRlKG1lbW9y"
    "eSk6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lbW9yaWVzX3AsIG1lbW9y"
    "eSkKICAgICAgICByZXR1cm4gbWVtb3J5CgogICAgZGVmIHNlYXJjaF9tZW1vcmllcyhzZWxmLCBxdWVyeTogc3RyLCBsaW1p"
    "dDogaW50ID0gNikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiIKICAgICAgICBLZXl3b3JkLXNjb3JlZCBtZW1vcnkgc2Vh"
    "cmNoLgogICAgICAgIFJldHVybnMgdXAgdG8gYGxpbWl0YCByZWNvcmRzIHNvcnRlZCBieSByZWxldmFuY2Ugc2NvcmUgZGVz"
    "Y2VuZGluZy4KICAgICAgICBGYWxscyBiYWNrIHRvIG1vc3QgcmVjZW50IGlmIG5vIHF1ZXJ5IHRlcm1zIG1hdGNoLgogICAg"
    "ICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApCiAgICAgICAgaWYgbm90IHF1"
    "ZXJ5LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiBtZW1vcmllc1stbGltaXQ6XQoKICAgICAgICBxX3Rlcm1zID0gc2V0"
    "KGV4dHJhY3Rfa2V5d29yZHMocXVlcnksIGxpbWl0PTE2KSkKICAgICAgICBzY29yZWQgID0gW10KCiAgICAgICAgZm9yIGl0"
    "ZW0gaW4gbWVtb3JpZXM6CiAgICAgICAgICAgIGl0ZW1fdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcygiICIuam9pbihb"
    "CiAgICAgICAgICAgICAgICBpdGVtLmdldCgidGl0bGUiLCAgICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJzdW1t"
    "YXJ5IiwgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoImNvbnRlbnQiLCAiIiksCiAgICAgICAgICAgICAgICAiICIu"
    "am9pbihpdGVtLmdldCgia2V5d29yZHMiLCBbXSkpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoInRhZ3Mi"
    "LCAgICAgW10pKSwKICAgICAgICAgICAgXSksIGxpbWl0PTQwKSkKCiAgICAgICAgICAgIHNjb3JlID0gbGVuKHFfdGVybXMg"
    "JiBpdGVtX3Rlcm1zKQoKICAgICAgICAgICAgIyBCb29zdCBieSB0eXBlIG1hdGNoCiAgICAgICAgICAgIHFsID0gcXVlcnku"
    "bG93ZXIoKQogICAgICAgICAgICBydCA9IGl0ZW0uZ2V0KCJ0eXBlIiwgIiIpCiAgICAgICAgICAgIGlmICJkcmVhbSIgIGlu"
    "IHFsIGFuZCBydCA9PSAiZHJlYW0iOiAgICBzY29yZSArPSA0CiAgICAgICAgICAgIGlmICJ0YXNrIiAgIGluIHFsIGFuZCBy"
    "dCA9PSAidGFzayI6ICAgICBzY29yZSArPSAzCiAgICAgICAgICAgIGlmICJpZGVhIiAgIGluIHFsIGFuZCBydCA9PSAiaWRl"
    "YSI6ICAgICBzY29yZSArPSAyCiAgICAgICAgICAgIGlmICJsc2wiICAgIGluIHFsIGFuZCBydCBpbiB7Imlzc3VlIiwicmVz"
    "b2x1dGlvbiJ9OiBzY29yZSArPSAyCgogICAgICAgICAgICBpZiBzY29yZSA+IDA6CiAgICAgICAgICAgICAgICBzY29yZWQu"
    "YXBwZW5kKChzY29yZSwgaXRlbSkpCgogICAgICAgIHNjb3JlZC5zb3J0KGtleT1sYW1iZGEgeDogKHhbMF0sIHhbMV0uZ2V0"
    "KCJ0aW1lc3RhbXAiLCAiIikpLAogICAgICAgICAgICAgICAgICAgIHJldmVyc2U9VHJ1ZSkKICAgICAgICByZXR1cm4gW2l0"
    "ZW0gZm9yIF8sIGl0ZW0gaW4gc2NvcmVkWzpsaW1pdF1dCgogICAgZGVmIGJ1aWxkX2NvbnRleHRfYmxvY2soc2VsZiwgcXVl"
    "cnk6IHN0ciwgbWF4X2NoYXJzOiBpbnQgPSAyMDAwKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250"
    "ZXh0IHN0cmluZyBmcm9tIHJlbGV2YW50IG1lbW9yaWVzIGZvciBwcm9tcHQgaW5qZWN0aW9uLgogICAgICAgIFRydW5jYXRl"
    "cyB0byBtYXhfY2hhcnMgdG8gcHJvdGVjdCB0aGUgY29udGV4dCB3aW5kb3cuCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3Jp"
    "ZXMgPSBzZWxmLnNlYXJjaF9tZW1vcmllcyhxdWVyeSwgbGltaXQ9NCkKICAgICAgICBpZiBub3QgbWVtb3JpZXM6CiAgICAg"
    "ICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFsiW1JFTEVWQU5UIE1FTU9SSUVTXSJdCiAgICAgICAgdG90YWwg"
    "PSAwCiAgICAgICAgZm9yIG0gaW4gbWVtb3JpZXM6CiAgICAgICAgICAgIGVudHJ5ID0gKAogICAgICAgICAgICAgICAgZiLi"
    "gKIgW3ttLmdldCgndHlwZScsJycpLnVwcGVyKCl9XSB7bS5nZXQoJ3RpdGxlJywnJyl9OiAiCiAgICAgICAgICAgICAgICBm"
    "InttLmdldCgnc3VtbWFyeScsJycpfSIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiB0b3RhbCArIGxlbihlbnRyeSkg"
    "PiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZW50cnkpCiAgICAg"
    "ICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5kKCJbRU5EIE1FTU9SSUVTXSIpCiAgICAg"
    "ICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICAjIOKUgOKUgCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9pc19uZWFyX2R1cGxpY2F0ZShzZWxmLCBjYW5kaWRhdGU6IGRpY3QpIC0+IGJvb2w6CiAgICAgICAgcmVj"
    "ZW50ID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApWy0yNTpdCiAgICAgICAgY3QgPSBjYW5kaWRhdGUuZ2V0KCJ0aXRs"
    "ZSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBjcyA9IGNhbmRpZGF0ZS5nZXQoInN1bW1hcnkiLCAiIikubG93ZXIo"
    "KS5zdHJpcCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gcmVjZW50OgogICAgICAgICAgICBpZiBpdGVtLmdldCgidGl0bGUiLCIi"
    "KS5sb3dlcigpLnN0cmlwKCkgPT0gY3Q6ICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiBpdGVtLmdldCgic3VtbWFyeSIs"
    "IiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjczogcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgX2lu"
    "ZmVyX3RhZ3Moc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgIGtleXdvcmRz"
    "OiBsaXN0W3N0cl0pIC0+IGxpc3Rbc3RyXToKICAgICAgICB0ICAgID0gdGV4dC5sb3dlcigpCiAgICAgICAgdGFncyA9IFty"
    "ZWNvcmRfdHlwZV0KICAgICAgICBpZiAiZHJlYW0iICAgaW4gdDogdGFncy5hcHBlbmQoImRyZWFtIikKICAgICAgICBpZiAi"
    "bHNsIiAgICAgaW4gdDogdGFncy5hcHBlbmQoImxzbCIpCiAgICAgICAgaWYgInB5dGhvbiIgIGluIHQ6IHRhZ3MuYXBwZW5k"
    "KCJweXRob24iKQogICAgICAgIGlmICJnYW1lIiAgICBpbiB0OiB0YWdzLmFwcGVuZCgiZ2FtZV9pZGVhIikKICAgICAgICBp"
    "ZiAic2wiICAgICAgaW4gdCBvciAic2Vjb25kIGxpZmUiIGluIHQ6IHRhZ3MuYXBwZW5kKCJzZWNvbmRsaWZlIikKICAgICAg"
    "ICBpZiBERUNLX05BTUUubG93ZXIoKSBpbiB0OiB0YWdzLmFwcGVuZChERUNLX05BTUUubG93ZXIoKSkKICAgICAgICBmb3Ig"
    "a3cgaW4ga2V5d29yZHNbOjRdOgogICAgICAgICAgICBpZiBrdyBub3QgaW4gdGFnczoKICAgICAgICAgICAgICAgIHRhZ3Mu"
    "YXBwZW5kKGt3KQogICAgICAgICMgRGVkdXBsaWNhdGUgcHJlc2VydmluZyBvcmRlcgogICAgICAgIHNlZW4sIG91dCA9IHNl"
    "dCgpLCBbXQogICAgICAgIGZvciB0YWcgaW4gdGFnczoKICAgICAgICAgICAgaWYgdGFnIG5vdCBpbiBzZWVuOgogICAgICAg"
    "ICAgICAgICAgc2Vlbi5hZGQodGFnKQogICAgICAgICAgICAgICAgb3V0LmFwcGVuZCh0YWcpCiAgICAgICAgcmV0dXJuIG91"
    "dFs6MTJdCgogICAgZGVmIF9pbmZlcl90aXRsZShzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAg"
    "ICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gc3RyOgogICAgICAgIGRlZiBjbGVhbih3b3Jkcyk6"
    "CiAgICAgICAgICAgIHJldHVybiBbdy5zdHJpcCgiIC1fLiwhPyIpLmNhcGl0YWxpemUoKQogICAgICAgICAgICAgICAgICAg"
    "IGZvciB3IGluIHdvcmRzIGlmIGxlbih3KSA+IDJdCgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ0YXNrIjoKICAgICAg"
    "ICAgICAgaW1wb3J0IHJlCiAgICAgICAgICAgIG0gPSByZS5zZWFyY2gociJyZW1pbmQgbWUgLio/IHRvICguKykiLCB1c2Vy"
    "X3RleHQsIHJlLkkpCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAgICAgICByZXR1cm4gZiJSZW1pbmRlcjoge20uZ3Jv"
    "dXAoMSkuc3RyaXAoKVs6NjBdfSIKICAgICAgICAgICAgcmV0dXJuICJSZW1pbmRlciBUYXNrIgogICAgICAgIGlmIHJlY29y"
    "ZF90eXBlID09ICJkcmVhbSI6CiAgICAgICAgICAgIHJldHVybiBmInsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6M10pKX0g"
    "RHJlYW0iLnN0cmlwKCkgb3IgIkRyZWFtIE1lbW9yeSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaXNzdWUiOgogICAg"
    "ICAgICAgICByZXR1cm4gZiJJc3N1ZTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVj"
    "aG5pY2FsIElzc3VlIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjoKICAgICAgICAgICAgcmV0dXJu"
    "IGYiUmVzb2x1dGlvbjogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2FsIFJl"
    "c29sdXRpb24iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOgogICAgICAgICAgICByZXR1cm4gZiJJZGVhOiB7"
    "JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJJZGVhIgogICAgICAgIGlmIGtleXdvcmRzOgog"
    "ICAgICAgICAgICByZXR1cm4gIiAiLmpvaW4oY2xlYW4oa2V5d29yZHNbOjVdKSkgb3IgIkNvbnZlcnNhdGlvbiBNZW1vcnki"
    "CiAgICAgICAgcmV0dXJuICJDb252ZXJzYXRpb24gTWVtb3J5IgoKICAgIGRlZiBfc3VtbWFyaXplKHNlbGYsIHJlY29yZF90"
    "eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gc3Ry"
    "OgogICAgICAgIHUgPSB1c2VyX3RleHQuc3RyaXAoKVs6MjIwXQogICAgICAgIGEgPSBhc3Npc3RhbnRfdGV4dC5zdHJpcCgp"
    "WzoyMjBdCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjogICAgICAgcmV0dXJuIGYiVXNlciBkZXNjcmliZWQg"
    "YSBkcmVhbToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ0YXNrIjogICAgICAgIHJldHVybiBmIlJlbWluZGVy"
    "L3Rhc2s6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaXNzdWUiOiAgICAgICByZXR1cm4gZiJUZWNobmljYWwg"
    "aXNzdWU6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6ICByZXR1cm4gZiJTb2x1dGlvbiBy"
    "ZWNvcmRlZDoge2Egb3IgdX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOiAgICAgICAgcmV0dXJuIGYiSWRl"
    "YSBkaXNjdXNzZWQ6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicHJlZmVyZW5jZSI6ICByZXR1cm4gZiJQcmVm"
    "ZXJlbmNlIG5vdGVkOiB7dX0iCiAgICAgICAgcmV0dXJuIGYiQ29udmVyc2F0aW9uOiB7dX0iCgoKIyDilIDilIAgU0VTU0lP"
    "TiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZXNzaW9uTWFuYWdlcjoKICAgICIi"
    "IgogICAgTWFuYWdlcyBjb252ZXJzYXRpb24gc2Vzc2lvbnMuCgogICAgQXV0by1zYXZlOiBldmVyeSAxMCBtaW51dGVzIChB"
    "UFNjaGVkdWxlciksIG1pZG5pZ2h0LXRvLW1pZG5pZ2h0IGJvdW5kYXJ5LgogICAgRmlsZTogc2Vzc2lvbnMvWVlZWS1NTS1E"
    "RC5qc29ubCDigJQgb3ZlcndyaXRlcyBvbiBlYWNoIHNhdmUuCiAgICBJbmRleDogc2Vzc2lvbnMvc2Vzc2lvbl9pbmRleC5q"
    "c29uIOKAlCBvbmUgZW50cnkgcGVyIGRheS4KCiAgICBTZXNzaW9ucyBhcmUgbG9hZGVkIGFzIGNvbnRleHQgaW5qZWN0aW9u"
    "IChub3QgcmVhbCBtZW1vcnkpIHVudGlsCiAgICB0aGUgU1FMaXRlL0Nocm9tYURCIHN5c3RlbSBpcyBidWlsdCBpbiBQaGFz"
    "ZSAyLgogICAgIiIiCgogICAgQVVUT1NBVkVfSU5URVJWQUwgPSAxMCAgICMgbWludXRlcwoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmKToKICAgICAgICBzZWxmLl9zZXNzaW9uc19kaXIgID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgICAgICBzZWxmLl9p"
    "bmRleF9wYXRoICAgID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9uX2lkICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfSIKICAg"
    "ICAgICBzZWxmLl9jdXJyZW50X2RhdGUgID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgc2VsZi5fbWVzc2Fn"
    "ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsOiBPcHRpb25hbFtzdHJdID0gTm9uZSAg"
    "IyBkYXRlIG9mIGxvYWRlZCBqb3VybmFsCgogICAgIyDilIDilIAgQ1VSUkVOVCBTRVNTSU9OIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFkZF9tZXNz"
    "YWdlKHNlbGYsIHJvbGU6IHN0ciwgY29udGVudDogc3RyLAogICAgICAgICAgICAgICAgICAgIGVtb3Rpb246IHN0ciA9ICIi"
    "LCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgIHNlbGYuX21lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAg"
    "ICAgICJpZCI6ICAgICAgICBmIm1zZ197dXVpZC51dWlkNCgpLmhleFs6OF19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6"
    "IHRpbWVzdGFtcCBvciBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJyb2xlIjogICAgICByb2xlLAogICAgICAgICAg"
    "ICAiY29udGVudCI6ICAgY29udGVudCwKICAgICAgICAgICAgImVtb3Rpb24iOiAgIGVtb3Rpb24sCiAgICAgICAgfSkKCiAg"
    "ICBkZWYgZ2V0X2hpc3Rvcnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm4gaGlzdG9y"
    "eSBpbiBMTE0tZnJpZW5kbHkgZm9ybWF0LgogICAgICAgIFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFudCIsICJjb250ZW50"
    "IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHJldHVybiBbCiAgICAgICAgICAgIHsicm9sZSI6IG1bInJvbGUiXSwg"
    "ImNvbnRlbnQiOiBtWyJjb250ZW50Il19CiAgICAgICAgICAgIGZvciBtIGluIHNlbGYuX21lc3NhZ2VzCiAgICAgICAgICAg"
    "IGlmIG1bInJvbGUiXSBpbiAoInVzZXIiLCAiYXNzaXN0YW50IikKICAgICAgICBdCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "c2Vzc2lvbl9pZChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nlc3Npb25faWQKCiAgICBAcHJvcGVydHkK"
    "ICAgIGRlZiBtZXNzYWdlX2NvdW50KHNlbGYpIC0+IGludDoKICAgICAgICByZXR1cm4gbGVuKHNlbGYuX21lc3NhZ2VzKQoK"
    "ICAgICMg4pSA4pSAIFNBVkUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgc2F2ZShzZWxmLCBh"
    "aV9nZW5lcmF0ZWRfbmFtZTogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2F2ZSBjdXJyZW50IHNl"
    "c3Npb24gdG8gc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubC4KICAgICAgICBPdmVyd3JpdGVzIHRoZSBmaWxlIGZvciB0b2Rh"
    "eSDigJQgZWFjaCBzYXZlIGlzIGEgZnVsbCBzbmFwc2hvdC4KICAgICAgICBVcGRhdGVzIHNlc3Npb25faW5kZXguanNvbi4K"
    "ICAgICAgICAiIiIKICAgICAgICB0b2RheSA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIG91dF9wYXRoID0g"
    "c2VsZi5fc2Vzc2lvbnNfZGlyIC8gZiJ7dG9kYXl9Lmpzb25sIgoKICAgICAgICAjIFdyaXRlIGFsbCBtZXNzYWdlcwogICAg"
    "ICAgIHdyaXRlX2pzb25sKG91dF9wYXRoLCBzZWxmLl9tZXNzYWdlcykKCiAgICAgICAgIyBVcGRhdGUgaW5kZXgKICAgICAg"
    "ICBpbmRleCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGV4aXN0aW5nID0gbmV4dCgKICAgICAgICAgICAgKHMgZm9y"
    "IHMgaW4gaW5kZXhbInNlc3Npb25zIl0gaWYgc1siZGF0ZSJdID09IHRvZGF5KSwgTm9uZQogICAgICAgICkKCiAgICAgICAg"
    "bmFtZSA9IGFpX2dlbmVyYXRlZF9uYW1lIG9yIGV4aXN0aW5nLmdldCgibmFtZSIsICIiKSBpZiBleGlzdGluZyBlbHNlICIi"
    "CiAgICAgICAgaWYgbm90IG5hbWUgYW5kIHNlbGYuX21lc3NhZ2VzOgogICAgICAgICAgICAjIEF1dG8tbmFtZSBmcm9tIGZp"
    "cnN0IHVzZXIgbWVzc2FnZSAoZmlyc3QgNSB3b3JkcykKICAgICAgICAgICAgZmlyc3RfdXNlciA9IG5leHQoCiAgICAgICAg"
    "ICAgICAgICAobVsiY29udGVudCJdIGZvciBtIGluIHNlbGYuX21lc3NhZ2VzIGlmIG1bInJvbGUiXSA9PSAidXNlciIpLAog"
    "ICAgICAgICAgICAgICAgIiIKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3JkcyA9IGZpcnN0X3VzZXIuc3BsaXQoKVs6"
    "NV0KICAgICAgICAgICAgbmFtZSAgPSAiICIuam9pbih3b3JkcykgaWYgd29yZHMgZWxzZSBmIlNlc3Npb24ge3RvZGF5fSIK"
    "CiAgICAgICAgZW50cnkgPSB7CiAgICAgICAgICAgICJkYXRlIjogICAgICAgICAgdG9kYXksCiAgICAgICAgICAgICJzZXNz"
    "aW9uX2lkIjogICAgc2VsZi5fc2Vzc2lvbl9pZCwKICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgICBuYW1lLAogICAgICAg"
    "ICAgICAibWVzc2FnZV9jb3VudCI6IGxlbihzZWxmLl9tZXNzYWdlcyksCiAgICAgICAgICAgICJmaXJzdF9tZXNzYWdlIjog"
    "KHNlbGYuX21lc3NhZ2VzWzBdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBzZWxmLl9t"
    "ZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICAgICAgImxhc3RfbWVzc2FnZSI6ICAoc2VsZi5fbWVzc2FnZXNbLTFdWyJ0aW1l"
    "c3RhbXAiXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAg"
    "ICB9CgogICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAgICBpZHggPSBpbmRleFsic2Vzc2lvbnMiXS5pbmRleChleGlz"
    "dGluZykKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl1baWR4XSA9IGVudHJ5CiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgaW5kZXhbInNlc3Npb25zIl0uaW5zZXJ0KDAsIGVudHJ5KQoKICAgICAgICAjIEtlZXAgbGFzdCAzNjUgZGF5cyBpbiBp"
    "bmRleAogICAgICAgIGluZGV4WyJzZXNzaW9ucyJdID0gaW5kZXhbInNlc3Npb25zIl1bOjM2NV0KICAgICAgICBzZWxmLl9z"
    "YXZlX2luZGV4KGluZGV4KQoKICAgICMg4pSA4pSAIExPQUQgLyBKT1VSTkFMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxpc3Rfc2Vzc2lvbnMo"
    "c2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiJSZXR1cm4gYWxsIHNlc3Npb25zIGZyb20gaW5kZXgsIG5ld2VzdCBm"
    "aXJzdC4iIiIKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZF9pbmRleCgpLmdldCgic2Vzc2lvbnMiLCBbXSkKCiAgICBkZWYg"
    "bG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIpIC0+IHN0cjoKICAgICAgICAiIiIKICAg"
    "ICAgICBMb2FkIGEgcGFzdCBzZXNzaW9uIGFzIGEgY29udGV4dCBpbmplY3Rpb24gc3RyaW5nLgogICAgICAgIFJldHVybnMg"
    "Zm9ybWF0dGVkIHRleHQgdG8gcHJlcGVuZCB0byB0aGUgc3lzdGVtIHByb21wdC4KICAgICAgICBUaGlzIGlzIE5PVCByZWFs"
    "IG1lbW9yeSDigJQgaXQncyBhIHRlbXBvcmFyeSBjb250ZXh0IHdpbmRvdyBpbmplY3Rpb24KICAgICAgICB1bnRpbCB0aGUg"
    "UGhhc2UgMiBtZW1vcnkgc3lzdGVtIGlzIGJ1aWx0LgogICAgICAgICIiIgogICAgICAgIHBhdGggPSBzZWxmLl9zZXNzaW9u"
    "c19kaXIgLyBmIntzZXNzaW9uX2RhdGV9Lmpzb25sIgogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAg"
    "ICByZXR1cm4gIiIKCiAgICAgICAgbWVzc2FnZXMgPSByZWFkX2pzb25sKHBhdGgpCiAgICAgICAgc2VsZi5fbG9hZGVkX2pv"
    "dXJuYWwgPSBzZXNzaW9uX2RhdGUKCiAgICAgICAgbGluZXMgPSBbZiJbSk9VUk5BTCBMT0FERUQg4oCUIHtzZXNzaW9uX2Rh"
    "dGV9XSIsCiAgICAgICAgICAgICAgICAgIlRoZSBmb2xsb3dpbmcgaXMgYSByZWNvcmQgb2YgYSBwcmlvciBjb252ZXJzYXRp"
    "b24uIiwKICAgICAgICAgICAgICAgICAiVXNlIHRoaXMgYXMgY29udGV4dCBmb3IgdGhlIGN1cnJlbnQgc2Vzc2lvbjpcbiJd"
    "CgogICAgICAgICMgSW5jbHVkZSB1cCB0byBsYXN0IDMwIG1lc3NhZ2VzIGZyb20gdGhhdCBzZXNzaW9uCiAgICAgICAgZm9y"
    "IG1zZyBpbiBtZXNzYWdlc1stMzA6XToKICAgICAgICAgICAgcm9sZSAgICA9IG1zZy5nZXQoInJvbGUiLCAiPyIpLnVwcGVy"
    "KCkKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIilbOjMwMF0KICAgICAgICAgICAgdHMgICAg"
    "ICA9IG1zZy5nZXQoInRpbWVzdGFtcCIsICIiKVs6MTZdCiAgICAgICAgICAgIGxpbmVzLmFwcGVuZChmIlt7dHN9XSB7cm9s"
    "ZX06IHtjb250ZW50fSIpCgogICAgICAgIGxpbmVzLmFwcGVuZCgiW0VORCBKT1VSTkFMXSIpCiAgICAgICAgcmV0dXJuICJc"
    "biIuam9pbihsaW5lcykKCiAgICBkZWYgY2xlYXJfbG9hZGVkX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9sb2FkZWRfam91cm5hbCA9IE5vbmUKCiAgICBAcHJvcGVydHkKICAgIGRlZiBsb2FkZWRfam91cm5hbF9kYXRlKHNlbGYp"
    "IC0+IE9wdGlvbmFsW3N0cl06CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZF9qb3VybmFsCgogICAgZGVmIHJlbmFtZV9z"
    "ZXNzaW9uKHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyLCBuZXdfbmFtZTogc3RyKSAtPiBib29sOgogICAgICAgICIiIlJlbmFt"
    "ZSBhIHNlc3Npb24gaW4gdGhlIGluZGV4LiBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4iIiIKICAgICAgICBpbmRleCA9IHNl"
    "bGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGZvciBlbnRyeSBpbiBpbmRleFsic2Vzc2lvbnMiXToKICAgICAgICAgICAgaWYg"
    "ZW50cnlbImRhdGUiXSA9PSBzZXNzaW9uX2RhdGU6CiAgICAgICAgICAgICAgICBlbnRyeVsibmFtZSJdID0gbmV3X25hbWVb"
    "OjgwXQogICAgICAgICAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKICAgICAgICAgICAgICAgIHJldHVybiBUcnVl"
    "CiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgIyDilIDilIAgSU5ERVggSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9p"
    "bmRleChzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLl9pbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgICAg"
    "ICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9pbmRleF9wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICAp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KCiAgICBkZWYg"
    "X3NhdmVfaW5kZXgoc2VsZiwgaW5kZXg6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faW5kZXhfcGF0aC53cml0ZV90"
    "ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKGluZGV4LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICAp"
    "CgoKIyDilIDilIAgTEVTU09OUyBMRUFSTkVEIERBVEFCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zTGVhcm5lZERCOgogICAg"
    "IiIiCiAgICBQZXJzaXN0ZW50IGtub3dsZWRnZSBiYXNlIGZvciBjb2RlIGxlc3NvbnMsIHJ1bGVzLCBhbmQgcmVzb2x1dGlv"
    "bnMuCgogICAgQ29sdW1ucyBwZXIgcmVjb3JkOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBlbnZpcm9ubWVudCAoTFNMfFB5"
    "dGhvbnxQeVNpZGU2fC4uLiksIGxhbmd1YWdlLAogICAgICAgIHJlZmVyZW5jZV9rZXkgKHNob3J0IHVuaXF1ZSB0YWcpLCBz"
    "dW1tYXJ5LCBmdWxsX3J1bGUsCiAgICAgICAgcmVzb2x1dGlvbiwgbGluaywgdGFncwoKICAgIFF1ZXJpZWQgRklSU1QgYmVm"
    "b3JlIGFueSBjb2RlIHNlc3Npb24gaW4gdGhlIHJlbGV2YW50IGxhbmd1YWdlLgogICAgVGhlIExTTCBGb3JiaWRkZW4gUnVs"
    "ZXNldCBsaXZlcyBoZXJlLgogICAgR3Jvd2luZywgbm9uLWR1cGxpY2F0aW5nLCBzZWFyY2hhYmxlLgogICAgIiIiCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJsZXNzb25z"
    "X2xlYXJuZWQuanNvbmwiCgogICAgZGVmIGFkZChzZWxmLCBlbnZpcm9ubWVudDogc3RyLCBsYW5ndWFnZTogc3RyLCByZWZl"
    "cmVuY2Vfa2V5OiBzdHIsCiAgICAgICAgICAgIHN1bW1hcnk6IHN0ciwgZnVsbF9ydWxlOiBzdHIsIHJlc29sdXRpb246IHN0"
    "ciA9ICIiLAogICAgICAgICAgICBsaW5rOiBzdHIgPSAiIiwgdGFnczogbGlzdCA9IE5vbmUpIC0+IGRpY3Q6CiAgICAgICAg"
    "cmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgIGYibGVzc29uX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19"
    "IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJlbnZpcm9ubWVu"
    "dCI6ICAgZW52aXJvbm1lbnQsCiAgICAgICAgICAgICJsYW5ndWFnZSI6ICAgICAgbGFuZ3VhZ2UsCiAgICAgICAgICAgICJy"
    "ZWZlcmVuY2Vfa2V5IjogcmVmZXJlbmNlX2tleSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICBzdW1tYXJ5LAogICAg"
    "ICAgICAgICAiZnVsbF9ydWxlIjogICAgIGZ1bGxfcnVsZSwKICAgICAgICAgICAgInJlc29sdXRpb24iOiAgICByZXNvbHV0"
    "aW9uLAogICAgICAgICAgICAibGluayI6ICAgICAgICAgIGxpbmssCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgdGFn"
    "cyBvciBbXSwKICAgICAgICB9CiAgICAgICAgaWYgbm90IHNlbGYuX2lzX2R1cGxpY2F0ZShyZWZlcmVuY2Vfa2V5KToKICAg"
    "ICAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYuX3BhdGgsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVm"
    "IHNlYXJjaChzZWxmLCBxdWVyeTogc3RyID0gIiIsIGVudmlyb25tZW50OiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgbGFu"
    "Z3VhZ2U6IHN0ciA9ICIiKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgp"
    "CiAgICAgICAgcmVzdWx0cyA9IFtdCiAgICAgICAgcSA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICBmb3IgciBpbiByZWNvcmRz"
    "OgogICAgICAgICAgICBpZiBlbnZpcm9ubWVudCBhbmQgci5nZXQoImVudmlyb25tZW50IiwiIikubG93ZXIoKSAhPSBlbnZp"
    "cm9ubWVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbGFuZ3VhZ2UgYW5kIHIu"
    "Z2V0KCJsYW5ndWFnZSIsIiIpLmxvd2VyKCkgIT0gbGFuZ3VhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIGlmIHE6CiAgICAgICAgICAgICAgICBoYXlzdGFjayA9ICIgIi5qb2luKFsKICAgICAgICAgICAgICAg"
    "ICAgICByLmdldCgic3VtbWFyeSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJmdWxsX3J1bGUiLCIiKSwKICAg"
    "ICAgICAgICAgICAgICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIpLAogICAgICAgICAgICAgICAgICAgICIgIi5qb2lu"
    "KHIuZ2V0KCJ0YWdzIixbXSkpLAogICAgICAgICAgICAgICAgXSkubG93ZXIoKQogICAgICAgICAgICAgICAgaWYgcSBub3Qg"
    "aW4gaGF5c3RhY2s6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgcmVzdWx0cy5hcHBlbmQocikK"
    "ICAgICAgICByZXR1cm4gcmVzdWx0cwoKICAgIGRlZiBnZXRfYWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0"
    "dXJuIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKCiAgICBkZWYgZGVsZXRlKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBib29s"
    "OgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgZmlsdGVyZWQgPSBbciBmb3IgciBp"
    "biByZWNvcmRzIGlmIHIuZ2V0KCJpZCIpICE9IHJlY29yZF9pZF0KICAgICAgICBpZiBsZW4oZmlsdGVyZWQpIDwgbGVuKHJl"
    "Y29yZHMpOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBmaWx0ZXJlZCkKICAgICAgICAgICAgcmV0dXJu"
    "IFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2Uoc2VsZiwgbGFu"
    "Z3VhZ2U6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfY2hhcnM6IGludCA9IDE1MDApIC0+"
    "IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIG9mIGFsbCBydWxlcyBmb3IgYSBnaXZl"
    "biBsYW5ndWFnZS4KICAgICAgICBGb3IgaW5qZWN0aW9uIGludG8gc3lzdGVtIHByb21wdCBiZWZvcmUgY29kZSBzZXNzaW9u"
    "cy4KICAgICAgICAiIiIKICAgICAgICByZWNvcmRzID0gc2VsZi5zZWFyY2gobGFuZ3VhZ2U9bGFuZ3VhZ2UpCiAgICAgICAg"
    "aWYgbm90IHJlY29yZHM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFtmIlt7bGFuZ3VhZ2UudXBw"
    "ZXIoKX0gUlVMRVMg4oCUIEFQUExZIEJFRk9SRSBXUklUSU5HIENPREVdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBm"
    "b3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBlbnRyeSA9IGYi4oCiIHtyLmdldCgncmVmZXJlbmNlX2tleScsJycpfTog"
    "e3IuZ2V0KCdmdWxsX3J1bGUnLCcnKX0iCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoK"
    "ICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwg"
    "Kz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoZiJbRU5EIHtsYW5ndWFnZS51cHBlcigpfSBSVUxFU10iKQog"
    "ICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAgZGVmIF9pc19kdXBsaWNhdGUoc2VsZiwgcmVmZXJlbmNlX2tl"
    "eTogc3RyKSAtPiBib29sOgogICAgICAgIHJldHVybiBhbnkoCiAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5Iiwi"
    "IikubG93ZXIoKSA9PSByZWZlcmVuY2Vfa2V5Lmxvd2VyKCkKICAgICAgICAgICAgZm9yIHIgaW4gcmVhZF9qc29ubChzZWxm"
    "Ll9wYXRoKQogICAgICAgICkKCiAgICBkZWYgc2VlZF9sc2xfcnVsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAg"
    "ICAgICBTZWVkIHRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgb24gZmlyc3QgcnVuIGlmIHRoZSBEQiBpcyBlbXB0eS4KICAg"
    "ICAgICBUaGVzZSBhcmUgdGhlIGhhcmQgcnVsZXMgZnJvbSB0aGUgcHJvamVjdCBzdGFuZGluZyBydWxlcy4KICAgICAgICAi"
    "IiIKICAgICAgICBpZiByZWFkX2pzb25sKHNlbGYuX3BhdGgpOgogICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBzZWVk"
    "ZWQKCiAgICAgICAgbHNsX3J1bGVzID0gWwogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVEVSTkFSWSIsCiAgICAg"
    "ICAgICAgICAiTm8gdGVybmFyeSBvcGVyYXRvcnMgaW4gTFNMIiwKICAgICAgICAgICAgICJOZXZlciB1c2UgdGhlIHRlcm5h"
    "cnkgb3BlcmF0b3IgKD86KSBpbiBMU0wgc2NyaXB0cy4gIgogICAgICAgICAgICAgIlVzZSBpZi9lbHNlIGJsb2NrcyBpbnN0"
    "ZWFkLiBMU0wgZG9lcyBub3Qgc3VwcG9ydCB0ZXJuYXJ5LiIsCiAgICAgICAgICAgICAiUmVwbGFjZSB3aXRoIGlmL2Vsc2Ug"
    "YmxvY2suIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fRk9SRUFDSCIsCiAgICAgICAgICAgICAiTm8g"
    "Zm9yZWFjaCBsb29wcyBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBoYXMgbm8gZm9yZWFjaCBsb29wIGNvbnN0cnVjdC4g"
    "VXNlIGludGVnZXIgaW5kZXggd2l0aCAiCiAgICAgICAgICAgICAibGxHZXRMaXN0TGVuZ3RoKCkgYW5kIGEgZm9yIG9yIHdo"
    "aWxlIGxvb3AuIiwKICAgICAgICAgICAgICJVc2U6IGZvcihpbnRlZ2VyIGk9MDsgaTxsbEdldExpc3RMZW5ndGgobXlMaXN0"
    "KTsgaSsrKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0dMT0JBTF9BU1NJR05fRlJPTV9GVU5DIiwK"
    "ICAgICAgICAgICAgICJObyBnbG9iYWwgdmFyaWFibGUgYXNzaWdubWVudHMgZnJvbSBmdW5jdGlvbiBjYWxscyIsCiAgICAg"
    "ICAgICAgICAiR2xvYmFsIHZhcmlhYmxlIGluaXRpYWxpemF0aW9uIGluIExTTCBjYW5ub3QgY2FsbCBmdW5jdGlvbnMuICIK"
    "ICAgICAgICAgICAgICJJbml0aWFsaXplIGdsb2JhbHMgd2l0aCBsaXRlcmFsIHZhbHVlcyBvbmx5LiAiCiAgICAgICAgICAg"
    "ICAiQXNzaWduIGZyb20gZnVuY3Rpb25zIGluc2lkZSBldmVudCBoYW5kbGVycyBvciBvdGhlciBmdW5jdGlvbnMuIiwKICAg"
    "ICAgICAgICAgICJNb3ZlIHRoZSBhc3NpZ25tZW50IGludG8gYW4gZXZlbnQgaGFuZGxlciAoc3RhdGVfZW50cnksIGV0Yy4p"
    "IiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVk9JRF9LRVlXT1JEIiwKICAgICAgICAgICAgICJObyB2"
    "b2lkIGtleXdvcmQgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgZG9lcyBub3QgaGF2ZSBhIHZvaWQga2V5d29yZCBmb3Ig"
    "ZnVuY3Rpb24gcmV0dXJuIHR5cGVzLiAiCiAgICAgICAgICAgICAiRnVuY3Rpb25zIHRoYXQgcmV0dXJuIG5vdGhpbmcgc2lt"
    "cGx5IG9taXQgdGhlIHJldHVybiB0eXBlLiIsCiAgICAgICAgICAgICAiUmVtb3ZlICd2b2lkJyBmcm9tIGZ1bmN0aW9uIHNp"
    "Z25hdHVyZS4gIgogICAgICAgICAgICAgImUuZy4gbXlGdW5jKCkgeyAuLi4gfSBub3Qgdm9pZCBteUZ1bmMoKSB7IC4uLiB9"
    "IiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiQ09NUExFVEVfU0NSSVBUU19PTkxZIiwKICAgICAgICAgICAg"
    "ICJBbHdheXMgcHJvdmlkZSBjb21wbGV0ZSBzY3JpcHRzLCBuZXZlciBwYXJ0aWFsIGVkaXRzIiwKICAgICAgICAgICAgICJX"
    "aGVuIHdyaXRpbmcgb3IgZWRpdGluZyBMU0wgc2NyaXB0cywgYWx3YXlzIG91dHB1dCB0aGUgY29tcGxldGUgIgogICAgICAg"
    "ICAgICAgInNjcmlwdC4gTmV2ZXIgcHJvdmlkZSBwYXJ0aWFsIHNuaXBwZXRzIG9yICdhZGQgdGhpcyBzZWN0aW9uJyAiCiAg"
    "ICAgICAgICAgICAiaW5zdHJ1Y3Rpb25zLiBUaGUgZnVsbCBzY3JpcHQgbXVzdCBiZSBjb3B5LXBhc3RlIHJlYWR5LiIsCiAg"
    "ICAgICAgICAgICAiV3JpdGUgdGhlIGVudGlyZSBzY3JpcHQgZnJvbSB0b3AgdG8gYm90dG9tLiIsICIiKSwKICAgICAgICBd"
    "CgogICAgICAgIGZvciBlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rIGluIGxz"
    "bF9ydWxlczoKICAgICAgICAgICAgc2VsZi5hZGQoZW52LCBsYW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1"
    "dGlvbiwgbGluaywKICAgICAgICAgICAgICAgICAgICAgdGFncz1bImxzbCIsICJmb3JiaWRkZW4iLCAic3RhbmRpbmdfcnVs"
    "ZSJdKQoKCiMg4pSA4pSAIFRBU0sgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgVGFza01hbmFnZXI6CiAgICAiIiIKICAgIFRhc2svcmVtaW5kZXIgQ1JVRCBhbmQgZHVlLWV2ZW50IGRldGVjdGlvbi4K"
    "CiAgICBGaWxlOiBtZW1vcmllcy90YXNrcy5qc29ubAoKICAgIFRhc2sgcmVjb3JkIGZpZWxkczoKICAgICAgICBpZCwgY3Jl"
    "YXRlZF9hdCwgZHVlX2F0LCBwcmVfdHJpZ2dlciAoMW1pbiBiZWZvcmUpLAogICAgICAgIHRleHQsIHN0YXR1cyAocGVuZGlu"
    "Z3x0cmlnZ2VyZWR8c25vb3plZHxjb21wbGV0ZWR8Y2FuY2VsbGVkKSwKICAgICAgICBhY2tub3dsZWRnZWRfYXQsIHJldHJ5"
    "X2NvdW50LCBsYXN0X3RyaWdnZXJlZF9hdCwgbmV4dF9yZXRyeV9hdCwKICAgICAgICBzb3VyY2UgKGxvY2FsfGdvb2dsZSks"
    "IGdvb2dsZV9ldmVudF9pZCwgc3luY19zdGF0dXMsIG1ldGFkYXRhCgogICAgRHVlLWV2ZW50IGN5Y2xlOgogICAgICAgIC0g"
    "UHJlLXRyaWdnZXI6IDEgbWludXRlIGJlZm9yZSBkdWUg4oaSIGFubm91bmNlIHVwY29taW5nCiAgICAgICAgLSBEdWUgdHJp"
    "Z2dlcjogYXQgZHVlIHRpbWUg4oaSIGFsZXJ0IHNvdW5kICsgQUkgY29tbWVudGFyeQogICAgICAgIC0gMy1taW51dGUgd2lu"
    "ZG93OiBpZiBub3QgYWNrbm93bGVkZ2VkIOKGkiBzbm9vemUKICAgICAgICAtIDEyLW1pbnV0ZSByZXRyeTogcmUtdHJpZ2dl"
    "cgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3Jp"
    "ZXMiKSAvICJ0YXNrcy5qc29ubCIKCiAgICAjIOKUgOKUgCBDUlVEIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIGxvYWRfYWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgbm9ybWFsaXplZCA9IFtdCiAgICAgICAgZm9yIHQgaW4g"
    "dGFza3M6CiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHQsIGRpY3QpOgogICAgICAgICAgICAgICAgY29udGludWUK"
    "ICAgICAgICAgICAgaWYgImlkIiBub3QgaW4gdDoKICAgICAgICAgICAgICAgIHRbImlkIl0gPSBmInRhc2tfe3V1aWQudXVp"
    "ZDQoKS5oZXhbOjEwXX0iCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAjIE5vcm1hbGl6ZSBm"
    "aWVsZCBuYW1lcwogICAgICAgICAgICBpZiAiZHVlX2F0IiBub3QgaW4gdDoKICAgICAgICAgICAgICAgIHRbImR1ZV9hdCJd"
    "ID0gdC5nZXQoImR1ZSIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICB0LnNldGRlZmF1bHQo"
    "InN0YXR1cyIsICAgICAgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicmV0cnlfY291bnQiLCAg"
    "ICAgIDApCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiYWNrbm93bGVkZ2VkX2F0IiwgIE5vbmUpCiAgICAgICAgICAgIHQu"
    "c2V0ZGVmYXVsdCgibGFzdF90cmlnZ2VyZWRfYXQiLE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibmV4dF9yZXRy"
    "eV9hdCIsICAgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicHJlX2Fubm91bmNlZCIsICAgIEZhbHNlKQogICAg"
    "ICAgICAgICB0LnNldGRlZmF1bHQoInNvdXJjZSIsICAgICAgICAgICAibG9jYWwiKQogICAgICAgICAgICB0LnNldGRlZmF1"
    "bHQoImdvb2dsZV9ldmVudF9pZCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN5bmNfc3RhdHVzIiwgICAg"
    "ICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCAgICAgICAgIHt9KQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoImNyZWF0ZWRfYXQiLCAgICAgICBsb2NhbF9ub3dfaXNvKCkpCgogICAgICAgICAgICAjIENvbXB1"
    "dGUgcHJlX3RyaWdnZXIgaWYgbWlzc2luZwogICAgICAgICAgICBpZiB0LmdldCgiZHVlX2F0IikgYW5kIG5vdCB0LmdldCgi"
    "cHJlX3RyaWdnZXIiKToKICAgICAgICAgICAgICAgIGR0ID0gcGFyc2VfaXNvKHRbImR1ZV9hdCJdKQogICAgICAgICAgICAg"
    "ICAgaWYgZHQ6CiAgICAgICAgICAgICAgICAgICAgcHJlID0gZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAgICAg"
    "ICAgICAgICAgIHRbInByZV90cmlnZ2VyIl0gPSBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAg"
    "ICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgbm9ybWFsaXplZC5hcHBlbmQodCkKCiAgICAgICAgaWYg"
    "Y2hhbmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgbm9ybWFsaXplZCkKICAgICAgICByZXR1cm4g"
    "bm9ybWFsaXplZAoKICAgIGRlZiBzYXZlX2FsbChzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICB3"
    "cml0ZV9qc29ubChzZWxmLl9wYXRoLCB0YXNrcykKCiAgICBkZWYgYWRkKHNlbGYsIHRleHQ6IHN0ciwgZHVlX2R0OiBkYXRl"
    "dGltZSwKICAgICAgICAgICAgc291cmNlOiBzdHIgPSAibG9jYWwiKSAtPiBkaWN0OgogICAgICAgIHByZSA9IGR1ZV9kdCAt"
    "IHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBm"
    "InRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgIGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICBkdWVfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNv"
    "bmRzIiksCiAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6ICAgICAgcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "LAogICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgIHRleHQuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXR1cyI6ICAg"
    "ICAgICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgTm9uZSwKICAgICAgICAgICAgInJl"
    "dHJ5X2NvdW50IjogICAgICAwLAogICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOk5vbmUsCiAgICAgICAgICAgICJu"
    "ZXh0X3JldHJ5X2F0IjogICAgTm9uZSwKICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiAgICBGYWxzZSwKICAgICAgICAg"
    "ICAgInNvdXJjZSI6ICAgICAgICAgICBzb3VyY2UsCiAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgTm9uZSwKICAg"
    "ICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICJtZXRhZGF0YSI6ICAgICAgICAg"
    "e30sCiAgICAgICAgfQogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgdGFza3MuYXBwZW5kKHRhc2sp"
    "CiAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gdGFzawoKICAgIGRlZiB1cGRhdGVfc3RhdHVz"
    "KHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhY2tub3dsZWRnZWQ6IGJv"
    "b2wgPSBGYWxzZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBm"
    "b3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRb"
    "InN0YXR1cyJdID0gc3RhdHVzCiAgICAgICAgICAgICAgICBpZiBhY2tub3dsZWRnZWQ6CiAgICAgICAgICAgICAgICAgICAg"
    "dFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNvbXBsZXRlKHNlbGYs"
    "IHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAg"
    "ICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAg"
    "IHRbInN0YXR1cyJdICAgICAgICAgID0gImNvbXBsZXRlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJd"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAg"
    "cmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjYW5jZWwoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRp"
    "b25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAg"
    "ICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAg"
    "PSAiY2FuY2VsbGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVy"
    "biBOb25lCgogICAgZGVmIGNsZWFyX2NvbXBsZXRlZChzZWxmKSAtPiBpbnQ6CiAgICAgICAgdGFza3MgICAgPSBzZWxmLmxv"
    "YWRfYWxsKCkKICAgICAgICBrZXB0ICAgICA9IFt0IGZvciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICAgICAgaWYgdC5n"
    "ZXQoInN0YXR1cyIpIG5vdCBpbiB7ImNvbXBsZXRlZCIsImNhbmNlbGxlZCJ9XQogICAgICAgIHJlbW92ZWQgID0gbGVuKHRh"
    "c2tzKSAtIGxlbihrZXB0KQogICAgICAgIGlmIHJlbW92ZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwoa2VwdCkKICAg"
    "ICAgICByZXR1cm4gcmVtb3ZlZAoKICAgIGRlZiB1cGRhdGVfZ29vZ2xlX3N5bmMoc2VsZiwgdGFza19pZDogc3RyLCBzeW5j"
    "X3N0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICBnb29nbGVfZXZlbnRfaWQ6IHN0ciA9ICIiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBlcnJvcjogc3RyID0gIiIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tz"
    "ID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09"
    "IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzeW5jX3N0YXR1cyJdICAgID0gc3luY19zdGF0dXMKICAgICAgICAgICAg"
    "ICAgIHRbImxhc3Rfc3luY2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIGlmIGdvb2dsZV9ldmVu"
    "dF9pZDoKICAgICAgICAgICAgICAgICAgICB0WyJnb29nbGVfZXZlbnRfaWQiXSA9IGdvb2dsZV9ldmVudF9pZAogICAgICAg"
    "ICAgICAgICAgaWYgZXJyb3I6CiAgICAgICAgICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsIHt9KQogICAg"
    "ICAgICAgICAgICAgICAgIHRbIm1ldGFkYXRhIl1bImdvb2dsZV9zeW5jX2Vycm9yIl0gPSBlcnJvcls6MjQwXQogICAgICAg"
    "ICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5v"
    "bmUKCiAgICAjIOKUgOKUgCBEVUUgRVZFTlQgREVURUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGdldF9kdWVfZXZlbnRzKHNlbGYpIC0+IGxpc3RbdHVwbGVbc3Ry"
    "LCBkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sgYWxsIHRhc2tzIGZvciBkdWUvcHJlLXRyaWdnZXIvcmV0cnkg"
    "ZXZlbnRzLgogICAgICAgIFJldHVybnMgbGlzdCBvZiAoZXZlbnRfdHlwZSwgdGFzaykgdHVwbGVzLgogICAgICAgIGV2ZW50"
    "X3R5cGU6ICJwcmUiIHwgImR1ZSIgfCAicmV0cnkiCgogICAgICAgIE1vZGlmaWVzIHRhc2sgc3RhdHVzZXMgaW4gcGxhY2Ug"
    "YW5kIHNhdmVzLgogICAgICAgIENhbGwgZnJvbSBBUFNjaGVkdWxlciBldmVyeSAzMCBzZWNvbmRzLgogICAgICAgICIiIgog"
    "ICAgICAgIG5vdyAgICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgICAgIHRhc2tzICA9IHNlbGYubG9hZF9h"
    "bGwoKQogICAgICAgIGV2ZW50cyA9IFtdCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgIGZvciB0YXNrIGluIHRh"
    "c2tzOgogICAgICAgICAgICBpZiB0YXNrLmdldCgiYWNrbm93bGVkZ2VkX2F0Iik6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQoKICAgICAgICAgICAgc3RhdHVzICAgPSB0YXNrLmdldCgic3RhdHVzIiwgInBlbmRpbmciKQogICAgICAgICAgICBkdWUg"
    "ICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJkdWVfYXQiKSkKICAgICAgICAgICAgcHJlICAgICAgPSBzZWxm"
    "Ll9wYXJzZV9sb2NhbCh0YXNrLmdldCgicHJlX3RyaWdnZXIiKSkKICAgICAgICAgICAgbmV4dF9yZXQgPSBzZWxmLl9wYXJz"
    "ZV9sb2NhbCh0YXNrLmdldCgibmV4dF9yZXRyeV9hdCIpKQogICAgICAgICAgICBkZWFkbGluZSA9IHNlbGYuX3BhcnNlX2xv"
    "Y2FsKHRhc2suZ2V0KCJhbGVydF9kZWFkbGluZSIpKQoKICAgICAgICAgICAgIyBQcmUtdHJpZ2dlcgogICAgICAgICAgICBp"
    "ZiAoc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgcHJlIGFuZCBub3cgPj0gcHJlCiAgICAgICAgICAgICAgICAgICAgYW5kIG5v"
    "dCB0YXNrLmdldCgicHJlX2Fubm91bmNlZCIpKToKICAgICAgICAgICAgICAgIHRhc2tbInByZV9hbm5vdW5jZWQiXSA9IFRy"
    "dWUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJwcmUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQg"
    "PSBUcnVlCgogICAgICAgICAgICAjIER1ZSB0cmlnZ2VyCiAgICAgICAgICAgIGlmIHN0YXR1cyA9PSAicGVuZGluZyIgYW5k"
    "IGR1ZSBhbmQgbm93ID49IGR1ZToKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICA9ICJ0cmlnZ2Vy"
    "ZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAg"
    "ICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5h"
    "c3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoImR1ZSIsIHRhc2spKQogICAgICAgICAgICAgICAg"
    "Y2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFNub296ZSBhZnRlciAzLW1p"
    "bnV0ZSB3aW5kb3cKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJ0cmlnZ2VyZWQiIGFuZCBkZWFkbGluZSBhbmQgbm93ID49"
    "IGRlYWRsaW5lOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgID0gInNub296ZWQiCiAgICAgICAgICAg"
    "ICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1l"
    "em9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MTIpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vj"
    "b25kcyIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICMgUmV0cnkKICAgICAgICAgICAgaWYgc3RhdHVzIGluIHsicmV0cnlfcGVuZGluZyIsInNub296ZWQifSBhbmQgbmV4"
    "dF9yZXQgYW5kIG5vdyA+PSBuZXh0X3JldDoKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICAgPSAi"
    "dHJpZ2dlcmVkIgogICAgICAgICAgICAgICAgdGFza1sicmV0cnlfY291bnQiXSAgICAgICA9IGludCh0YXNrLmdldCgicmV0"
    "cnlfY291bnQiLDApKSArIDEKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il0gPSBsb2NhbF9ub3df"
    "aXNvKCkKICAgICAgICAgICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICAgPSAoCiAgICAgICAgICAgICAgICAgICAg"
    "ZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSAgICAgPSBO"
    "b25lCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgicmV0cnkiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5n"
    "ZWQgPSBUcnVlCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAg"
    "cmV0dXJuIGV2ZW50cwoKICAgIGRlZiBfcGFyc2VfbG9jYWwoc2VsZiwgdmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRp"
    "bWVdOgogICAgICAgICIiIlBhcnNlIElTTyBzdHJpbmcgdG8gdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZm9yIGNvbXBhcmlz"
    "b24uIiIiCiAgICAgICAgZHQgPSBwYXJzZV9pc28odmFsdWUpCiAgICAgICAgaWYgZHQgaXMgTm9uZToKICAgICAgICAgICAg"
    "cmV0dXJuIE5vbmUKICAgICAgICBpZiBkdC50emluZm8gaXMgTm9uZToKICAgICAgICAgICAgZHQgPSBkdC5hc3RpbWV6b25l"
    "KCkKICAgICAgICByZXR1cm4gZHQKCiAgICAjIOKUgOKUgCBOQVRVUkFMIExBTkdVQUdFIFBBUlNJTkcg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgY2xhc3NpZnlfaW50"
    "ZW50KHRleHQ6IHN0cikgLT4gZGljdDoKICAgICAgICAiIiIKICAgICAgICBDbGFzc2lmeSB1c2VyIGlucHV0IGFzIHRhc2sv"
    "cmVtaW5kZXIvdGltZXIvY2hhdC4KICAgICAgICBSZXR1cm5zIHsiaW50ZW50Ijogc3RyLCAiY2xlYW5lZF9pbnB1dCI6IHN0"
    "cn0KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICAjIFN0cmlwIGNvbW1vbiBpbnZvY2F0aW9uIHByZWZp"
    "eGVzCiAgICAgICAgY2xlYW5lZCA9IHJlLnN1YigKICAgICAgICAgICAgcmYiXlxzKig/OntERUNLX05BTUUubG93ZXIoKX18"
    "aGV5XHMre0RFQ0tfTkFNRS5sb3dlcigpfSlccyosP1xzKls6XC1dP1xzKiIsCiAgICAgICAgICAgICIiLCB0ZXh0LCBmbGFn"
    "cz1yZS5JCiAgICAgICAgKS5zdHJpcCgpCgogICAgICAgIGxvdyA9IGNsZWFuZWQubG93ZXIoKQoKICAgICAgICB0aW1lcl9w"
    "YXRzICAgID0gW3IiXGJzZXQoPzpccythKT9ccyt0aW1lclxiIiwgciJcYnRpbWVyXHMrZm9yXGIiLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgciJcYnN0YXJ0KD86XHMrYSk/XHMrdGltZXJcYiJdCiAgICAgICAgcmVtaW5kZXJfcGF0cyA9IFtyIlxi"
    "cmVtaW5kIG1lXGIiLCByIlxic2V0KD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICBy"
    "IlxiYWRkKD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic2V0KD86XHMrYW4/"
    "KT9ccythbGFybVxiIiwgciJcYmFsYXJtXHMrZm9yXGIiXQogICAgICAgIHRhc2tfcGF0cyAgICAgPSBbciJcYmFkZCg/Olxz"
    "K2EpP1xzK3Rhc2tcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxiY3JlYXRlKD86XHMrYSk/XHMrdGFza1xiIiwg"
    "ciJcYm5ld1xzK3Rhc2tcYiJdCgogICAgICAgIGltcG9ydCByZSBhcyBfcmUKICAgICAgICBpZiBhbnkoX3JlLnNlYXJjaChw"
    "LCBsb3cpIGZvciBwIGluIHRpbWVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGltZXIiCiAgICAgICAgZWxpZiBh"
    "bnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHJlbWluZGVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAicmVt"
    "aW5kZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRhc2tfcGF0cyk6CiAgICAgICAg"
    "ICAgIGludGVudCA9ICJ0YXNrIgogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGludGVudCA9ICJjaGF0IgoKICAgICAgICBy"
    "ZXR1cm4geyJpbnRlbnQiOiBpbnRlbnQsICJjbGVhbmVkX2lucHV0IjogY2xlYW5lZH0KCiAgICBAc3RhdGljbWV0aG9kCiAg"
    "ICBkZWYgcGFyc2VfZHVlX2RhdGV0aW1lKHRleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIgog"
    "ICAgICAgIFBhcnNlIG5hdHVyYWwgbGFuZ3VhZ2UgdGltZSBleHByZXNzaW9uIGZyb20gdGFzayB0ZXh0LgogICAgICAgIEhh"
    "bmRsZXM6ICJpbiAzMCBtaW51dGVzIiwgImF0IDNwbSIsICJ0b21vcnJvdyBhdCA5YW0iLAogICAgICAgICAgICAgICAgICJp"
    "biAyIGhvdXJzIiwgImF0IDE1OjMwIiwgZXRjLgogICAgICAgIFJldHVybnMgYSBkYXRldGltZSBvciBOb25lIGlmIHVucGFy"
    "c2VhYmxlLgogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3coKQogICAg"
    "ICAgIGxvdyAgPSB0ZXh0Lmxvd2VyKCkuc3RyaXAoKQoKICAgICAgICAjICJpbiBYIG1pbnV0ZXMvaG91cnMvZGF5cyIKICAg"
    "ICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImluXHMrKFxkKylccyoobWludXRlfG1pbnxob3VyfGhyfGRheXxz"
    "ZWNvbmR8c2VjKSIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAgICAgICBuICAgID0g"
    "aW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIHVuaXQgPSBtLmdyb3VwKDIpCiAgICAgICAgICAgIGlmICJtaW4iIGluIHVu"
    "aXQ6ICByZXR1cm4gbm93ICsgdGltZWRlbHRhKG1pbnV0ZXM9bikKICAgICAgICAgICAgaWYgImhvdXIiIGluIHVuaXQgb3Ig"
    "ImhyIiBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGhvdXJzPW4pCiAgICAgICAgICAgIGlmICJkYXkiICBpbiB1"
    "bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGRheXM9bikKICAgICAgICAgICAgaWYgInNlYyIgIGluIHVuaXQ6IHJldHVy"
    "biBub3cgKyB0aW1lZGVsdGEoc2Vjb25kcz1uKQoKICAgICAgICAjICJhdCBISDpNTSIgb3IgImF0IEg6TU1hbS9wbSIKICAg"
    "ICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImF0XHMrKFxkezEsMn0pKD86OihcZHsyfSkpP1xzKihhbXxwbSk/"
    "IiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIGhyICA9IGludChtLmdyb3Vw"
    "KDEpKQogICAgICAgICAgICBtbiAgPSBpbnQobS5ncm91cCgyKSkgaWYgbS5ncm91cCgyKSBlbHNlIDAKICAgICAgICAgICAg"
    "YXBtID0gbS5ncm91cCgzKQogICAgICAgICAgICBpZiBhcG0gPT0gInBtIiBhbmQgaHIgPCAxMjogaHIgKz0gMTIKICAgICAg"
    "ICAgICAgaWYgYXBtID09ICJhbSIgYW5kIGhyID09IDEyOiBociA9IDAKICAgICAgICAgICAgZHQgPSBub3cucmVwbGFjZSho"
    "b3VyPWhyLCBtaW51dGU9bW4sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKQogICAgICAgICAgICBpZiBkdCA8PSBub3c6CiAg"
    "ICAgICAgICAgICAgICBkdCArPSB0aW1lZGVsdGEoZGF5cz0xKQogICAgICAgICAgICByZXR1cm4gZHQKCiAgICAgICAgIyAi"
    "dG9tb3Jyb3cgYXQgLi4uIiAgKHJlY3Vyc2Ugb24gdGhlICJhdCIgcGFydCkKICAgICAgICBpZiAidG9tb3Jyb3ciIGluIGxv"
    "dzoKICAgICAgICAgICAgdG9tb3Jyb3dfdGV4dCA9IHJlLnN1YihyInRvbW9ycm93IiwgIiIsIGxvdykuc3RyaXAoKQogICAg"
    "ICAgICAgICByZXN1bHQgPSBUYXNrTWFuYWdlci5wYXJzZV9kdWVfZGF0ZXRpbWUodG9tb3Jyb3dfdGV4dCkKICAgICAgICAg"
    "ICAgaWYgcmVzdWx0OgogICAgICAgICAgICAgICAgcmV0dXJuIHJlc3VsdCArIHRpbWVkZWx0YShkYXlzPTEpCgogICAgICAg"
    "IHJldHVybiBOb25lCgoKIyDilIDilIAgUkVRVUlSRU1FTlRTLlRYVCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiB3cml0ZV9yZXF1aXJlbWVu"
    "dHNfdHh0KCkgLT4gTm9uZToKICAgICIiIgogICAgV3JpdGUgcmVxdWlyZW1lbnRzLnR4dCBuZXh0IHRvIHRoZSBkZWNrIGZp"
    "bGUgb24gZmlyc3QgcnVuLgogICAgSGVscHMgdXNlcnMgaW5zdGFsbCBhbGwgZGVwZW5kZW5jaWVzIHdpdGggb25lIHBpcCBj"
    "b21tYW5kLgogICAgIiIiCiAgICByZXFfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiYmFzZV9kaXIiLCBzdHIoU0NSSVBUX0RJUikp"
    "KSAvICJyZXF1aXJlbWVudHMudHh0IgogICAgaWYgcmVxX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgY29u"
    "dGVudCA9ICIiIlwKIyBNb3JnYW5uYSBEZWNrIOKAlCBSZXF1aXJlZCBEZXBlbmRlbmNpZXMKIyBJbnN0YWxsIGFsbCB3aXRo"
    "OiBwaXAgaW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0CgojIENvcmUgVUkKUHlTaWRlNgoKIyBTY2hlZHVsaW5nIChpZGxl"
    "IHRpbWVyLCBhdXRvc2F2ZSwgcmVmbGVjdGlvbiBjeWNsZXMpCmFwc2NoZWR1bGVyCgojIExvZ2dpbmcKbG9ndXJ1CgojIFNv"
    "dW5kIHBsYXliYWNrIChXQVYgKyBNUDMpCnB5Z2FtZQoKIyBEZXNrdG9wIHNob3J0Y3V0IGNyZWF0aW9uIChXaW5kb3dzIG9u"
    "bHkpCnB5d2luMzIKCiMgU3lzdGVtIG1vbml0b3JpbmcgKENQVSwgUkFNLCBkcml2ZXMsIG5ldHdvcmspCnBzdXRpbAoKIyBI"
    "VFRQIHJlcXVlc3RzCnJlcXVlc3RzCgojIEdvb2dsZSBpbnRlZ3JhdGlvbiAoQ2FsZW5kYXIsIERyaXZlLCBEb2NzLCBHbWFp"
    "bCkKZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Cmdvb2dsZS1hdXRoLW9hdXRobGliCmdvb2dsZS1hdXRoCgojIOKUgOKUgCBP"
    "cHRpb25hbCAobG9jYWwgbW9kZWwgb25seSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHVzaW5nIGEgbG9jYWwgSHVnZ2luZ0ZhY2UgbW9kZWw6CiMg"
    "dG9yY2gKIyB0cmFuc2Zvcm1lcnMKIyBhY2NlbGVyYXRlCgojIOKUgOKUgCBPcHRpb25hbCAoTlZJRElBIEdQVSBtb25pdG9y"
    "aW5nKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgeW91"
    "IGhhdmUgYW4gTlZJRElBIEdQVToKIyBweW52bWwKIiIiCiAgICByZXFfcGF0aC53cml0ZV90ZXh0KGNvbnRlbnQsIGVuY29k"
    "aW5nPSJ1dGYtOCIpCgoKIyDilIDilIAgUEFTUyA0IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIE1lbW9yeSwgU2Vzc2lvbiwgTGVzc29uc0xlYXJuZWQsIFRhc2tNYW5hZ2VyIGFsbCBkZWZpbmVkLgojIExTTCBGb3Ji"
    "aWRkZW4gUnVsZXNldCBhdXRvLXNlZWRlZCBvbiBmaXJzdCBydW4uCiMgcmVxdWlyZW1lbnRzLnR4dCB3cml0dGVuIG9uIGZp"
    "cnN0IHJ1bi4KIwojIE5leHQ6IFBhc3MgNSDigJQgVGFiIENvbnRlbnQgQ2xhc3NlcwojIChTTFNjYW5zVGFiLCBTTENvbW1h"
    "bmRzVGFiLCBKb2JUcmFja2VyVGFiLCBSZWNvcmRzVGFiLAojICBUYXNrc1RhYiwgU2VsZlRhYiwgRGlhZ25vc3RpY3NUYWIp"
    "CgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDU6IFRBQiBDT05URU5UIENMQVNT"
    "RVMKIwojIFRhYnMgZGVmaW5lZCBoZXJlOgojICAgU0xTY2Fuc1RhYiAgICAgIOKAlCBncmltb2lyZS1jYXJkIHN0eWxlLCBy"
    "ZWJ1aWx0IChEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwKIyAgICAgICAgICAgICAgICAgICAgIHBhcnNlciBmaXhlZCwg"
    "Y29weS10by1jbGlwYm9hcmQgcGVyIGl0ZW0pCiMgICBTTENvbW1hbmRzVGFiICAg4oCUIGdvdGhpYyB0YWJsZSwgY29weSBj"
    "b21tYW5kIHRvIGNsaXBib2FyZAojICAgSm9iVHJhY2tlclRhYiAgIOKAlCBmdWxsIHJlYnVpbGQgZnJvbSBzcGVjLCBDU1Yv"
    "VFNWIGV4cG9ydAojICAgUmVjb3Jkc1RhYiAgICAgIOKAlCBHb29nbGUgRHJpdmUvRG9jcyB3b3Jrc3BhY2UKIyAgIFRhc2tz"
    "VGFiICAgICAgICDigJQgdGFzayByZWdpc3RyeSArIG1pbmkgY2FsZW5kYXIKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRs"
    "ZSBuYXJyYXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1IG91dHB1dCArIGhh"
    "cmR3YXJlIHJlcG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMgICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBGb3JiaWRk"
    "ZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMg"
    "X3JlCgoKIyDilIDilIAgU0hBUkVEIEdPVEhJQyBUQUJMRSBTVFlMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAt"
    "PiBzdHI6CiAgICByZXR1cm4gZiIiIgogICAgICAgIFFUYWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsKICAgICAgICAgICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQtc2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAg"
    "IFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07"
    "CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAgICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0"
    "ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgfX0KICAgICAgICBRSGVh"
    "ZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgICAgICAgICBjb2xvcjog"
    "e0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgcGFk"
    "ZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAg"
    "Zm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9sZDsKICAgICAgICAgICAgbGV0dGVyLXNwYWNp"
    "bmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4dDogc3RyLCB0b29sdGlwOiBzdHIgPSAi"
    "IikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQogICAgYnRuLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYiZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogNHB4IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAgICAgICBidG4uc2V0"
    "VG9vbFRpcCh0b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoK"
    "ICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07"
    "IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMg"
    "VEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQp"
    "OgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBhdmF0YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZy"
    "b20gc3BlYzoKICAgICAgLSBDYXJkL2dyaW1vaXJlLWVudHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGlt"
    "ZXN0YW1wLWF3YXJlIHBhcnNlcikKICAgICAgLSBEaXNwbGF5IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0g"
    "TW9kaWZ5IChlZGl0IG5hbWUsIGRlc2NyaXB0aW9uLCBpbmRpdmlkdWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1p"
    "c3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBhcnNlICh3YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNl"
    "ciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAgIC0gQ29weS10by1jbGlwYm9hcmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIgog"
    "ICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkOiBPcHRpb25h"
    "bFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "c2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRv"
    "biBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICAgPSBfZ290aGljX2J0"
    "bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5ID0gX2dvdGhpY19i"
    "dG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBkZXRhaWxzIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5"
    "ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9k"
    "ZWxldGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxm"
    "Ll9idG5fcmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4dCBvZiBzZWxlY3Rl"
    "ZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAgICAgICBz"
    "ZWxmLl9idG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9t"
    "b2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fcmVwYXJzZSkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYu"
    "X2J0bl9tb2RpZnksCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAg"
    "ICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91"
    "dChiYXIpCgogICAgICAgICMgU3RhY2s6IGxpc3QgdmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAg"
    "IHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoK"
    "ICAgICAgICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4gbGlzdCAoZ3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdl"
    "dCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwg"
    "MCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5z"
    "ZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAgc2VsZi5fY2FyZF9jb250YWluZXIgPSBRV2lkZ2V0KCkK"
    "ICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94TGF5b3V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQogICAgICAg"
    "IHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5"
    "b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9j"
    "YXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2Nh"
    "cmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyDilIDilIAgUEFHRSAxOiBh"
    "ZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBw"
    "MSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5z"
    "KDQsIDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBTQ0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQi"
    "KQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYu"
    "X2FkZF9kZXNjLnNldE1heGltdW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAg"
    "ICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAg"
    "IHNlbGYuX2FkZF9yYXcgICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQo"
    "CiAgICAgICAgICAgICJQYXN0ZSB0aGUgcmF3IFNlY29uZCBMaWZlIHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAg"
    "ICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3XSB3aWxsIGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAg"
    "ICApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBp"
    "dGVtcwogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAg"
    "ICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhv"
    "cml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXpl"
    "TW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Fk"
    "ZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQo"
    "X2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfcHJldmlldykKICAgICAgICBz"
    "ZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fcHJldmlld19wYXJzZSkKCiAgICAgICAgYnRuczEgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzEgPSBfZ290aGljX2J0bigi4pyX"
    "IENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBjMS5jbGlja2VkLmNv"
    "bm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczEuYWRkV2lkZ2V0KHMx"
    "KTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRjaCgpCiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0bnMxKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAyOiBkaXNwbGF5IOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAyID0gUVdpZGdl"
    "dCgpCiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX2Rpc3BfZGVzYyAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVl"
    "KQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6"
    "b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250"
    "YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5T"
    "dHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRl"
    "eHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAg"
    "ICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYu"
    "X2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF9uYW1lKQogICAgICAgIGwyLmFk"
    "ZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfdGFibGUsIDEpCgogICAg"
    "ICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55IGl0ZW0gdG8gY29weSBpdCB0byBjbGlwYm9hcmQuIikK"
    "ICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGwyLmFkZFdp"
    "ZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNfYnRuKCLil4AgQmFjayIpCiAgICAgICAgYmsyLmNsaWNr"
    "ZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBsMi5hZGRXaWRnZXQo"
    "YmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAgUEFHRSAzOiBtb2RpZnkg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDMg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLi"
    "nacgTkFNRSIpKQogICAgICAgIHNlbGYuX21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2Vs"
    "Zi5fbW9kX25hbWUpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAg"
    "ICAgc2VsZi5fbW9kX2Rlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAg"
    "ICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSVRFTVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAg"
    "ICAgIHNlbGYuX21vZF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jp"
    "em9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250"
    "YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5T"
    "dHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "CiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUu"
    "c2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJs"
    "ZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJveExheW91dCgpCiAgICAgICAgczMgPSBfZ290aGljX2J0bigi4pymIFNhdmUi"
    "KTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21v"
    "ZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRl"
    "eCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBidG5zMy5hZGRXaWRnZXQoYzMpOyBidG5zMy5hZGRTdHJldGNo"
    "KCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICMg"
    "4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9z"
    "Y2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2Ug"
    "cmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBpdGVtcykuCgogICAgICAgIEtFWSBGSVg6IEJlZm9yZSBz"
    "cGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRpbWVzdGFtcCBzbyBzaW5n"
    "bGUtbGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzEx"
    "OjQ3XSBBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46IEl0ZW0gTmFtZSBb"
    "QXR0YWNobWVudF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3XSAuLi4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qg"
    "cmF3LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9XTiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTog"
    "bm9ybWFsaXplIOKAlCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbm9ybWFsaXplZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAg"
    "IGxpbmVzID0gW2wuc3RyaXAoKSBmb3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAg"
    "ICAgICMg4pSA4pSAIFN0ZXAgMjogZXh0cmFjdCBhdmF0YXIgbmFtZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBhdmF0YXJfbmFtZSA9ICJVTktOT1dOIgogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0"
    "YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBvciBzaW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAg"
    "ICAgICAgICAgICAgciIoXHdbXHdcc10rPyknc1xzK3B1YmxpY1xzK2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxp"
    "bmUsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0g"
    "bS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBicmVhawoKICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJh"
    "Y3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQog"
    "ICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjIFN0cmlwIGxlYWRpbmcgdGltZXN0YW1wCiAgICAgICAg"
    "ICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpcZHsyfVxdXHMqJywgJycsIGxpbmUpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAjIFNraXAgaGVhZGVy"
    "IGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNobWVudHMiIGluIGNvbnRlbnQubG93ZXIoKToKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93ZXIoKS5zdGFydHN3aXRoKCJvYmplY3QiKToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZpZGVyIGxpbmVzIOKAlCBsaW5lcyB0aGF0"
    "IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAgICAgICAgICAjIGUuZy4g4paC4paC4paC4paC4paC4paC"
    "4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkCBvciDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50LnN0cmlwKCIuOiAiKQog"
    "ICAgICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250"
    "aW51ZSAgIyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAgIyBUcnkgdG8gZXh0"
    "cmFjdCBDUkVBVE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9yID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0ZW1fbmFt"
    "ZSA9IGNvbnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2ggPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidD"
    "UkVBVE9SOlxzKihbXHdcc10rPykoPzpccypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgaWYgY3JlYXRvcl9tYXRjaDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSku"
    "c3RyaXAoKQogICAgICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJp"
    "cCgpCgogICAgICAgICAgICAjIFN0cmlwIGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAg"
    "ICAgICAgICBpdGVtX25hbWUgPSBfcmUuc3ViKHInXHMqXFtbXHdcc19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQog"
    "ICAgICAgICAgICBpdGVtX25hbWUgPSBpdGVtX25hbWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUg"
    "YW5kIGxlbihpdGVtX25hbWUpID4gMToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUs"
    "ICJjcmVhdG9yIjogY3JlYXRvcn0pCgogICAgICAgIHJldHVybiBhdmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBD"
    "QVJEIFJFTkRFUklORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfY2FyZHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0"
    "aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAg"
    "ICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQo"
    "KToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgcmVjIGluIHNlbGYu"
    "X3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtlX2NhcmQocmVjKQogICAgICAgICAgICBzZWxmLl9jYXJk"
    "X2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpIC0gMSwgY2Fy"
    "ZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVjOiBkaWN0KSAtPiBRV2lkZ2V0OgogICAgICAg"
    "IGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2Vs"
    "ZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEwYTEw"
    "JyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IHBh"
    "ZGRpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJuYW1l"
    "IiwgIlVOS05PV04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19H"
    "T0xEX0JSSUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAg"
    "IGNvdW50ID0gbGVuKHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0g"
    "aXRlbXMiKQogICAgICAgIGNvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09O"
    "fTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAg"
    "IGRhdGVfbGJsID0gUUxhYmVsKHJlYy5nZXQoImNyZWF0ZWRfYXQiLCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxh"
    "eW91dC5hZGRTcGFjaW5nKDEyKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sg"
    "dG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgicmVjb3JkX2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVBy"
    "ZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJlY19pZDogc2VsZi5fc2VsZWN0X2NhcmQocmlkKQogICAgICAgIHJldHVybiBj"
    "YXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9z"
    "ZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkgICMgUmVidWlsZCB0byBzaG93IHNl"
    "bGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVkX3JlY29yZChzZWxmKSAtPiBPcHRpb25hbFtkaWN0XToKICAg"
    "ICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIgaW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgaWYg"
    "ci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkKSwKICAgICAgICAgICAgTm9uZQogICAgICAgICkKCiAg"
    "ICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICMgRW5zdXJlIHJlY29yZF9p"
    "ZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBzZWxmLl9yZWNvcmRzOgog"
    "ICAgICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSBy"
    "LmdldCgiaWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICBp"
    "ZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNl"
    "bGYuX2J1aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZp"
    "ZXdfcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAg"
    "ICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFj"
    "ZWhvbGRlclRleHQobmFtZSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBp"
    "dCBpbiBpdGVtc1s6MjBdOiAgIyBwcmV2aWV3IGZpcnN0IDIwCiAgICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5y"
    "b3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9h"
    "ZGRfcHJldmlldy5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYu"
    "X2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMSwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3No"
    "b3dfYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYWRkX25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9u"
    "YW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRk"
    "X2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNl"
    "dFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRl"
    "bXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgb3ZlcnJpZGVfbmFtZSA9IHNlbGYuX2FkZF9uYW1lLnRl"
    "eHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAg"
    "ICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAg"
    "InJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJuYW1lIjogICAgICAgIG92ZXJyaWRlX25h"
    "bWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5fYWRkX2Rlc2MudG9QbGFpblRleHQoKVs6MjQ0"
    "XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAgICJyYXdfdGV4dCI6ICAgIHJhdywKICAg"
    "ICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9hdCI6ICBub3csCiAgICAgICAgfQog"
    "ICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxm"
    "Ll9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQiXQogICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxl"
    "Y3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNl"
    "bGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRp"
    "c3BsYXkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5n"
    "ZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwi"
    "IikpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJp"
    "dGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X2Rpc3BfdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAg"
    "ICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3Bf"
    "dGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJV"
    "TktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0"
    "X21lbnUoc2VsZiwgcG9zKSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAg"
    "ICAgICAgaWYgbm90IGlkeC5pc1ZhbGlkKCk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2Vs"
    "Zi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0"
    "ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVhdG9yICAgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDEp"
    "IG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNp"
    "ZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1lbnUoc2VsZikKICAgICAgICBtZW51LnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgYV9pdGVtICAgID0g"
    "bWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAgICBhX2NyZWF0b3IgPSBtZW51LmFkZEFjdGlvbigiQ29w"
    "eSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBCb3RoIikKICAgICAgICBhY3Rp"
    "b24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgY2Ig"
    "PSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBhY3Rpb24gPT0gYV9pdGVtOiAgICBjYi5zZXRUZXh0KGl0"
    "ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0b3I6IGNiLnNldFRleHQoY3JlYXRvcikKICAgICAgICBl"
    "bGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVhdG9yfSIpCgogICAgZGVm"
    "IF9zaG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAg"
    "ICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQocmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYu"
    "X21vZF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYu"
    "X21vZF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAg"
    "ICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0"
    "KCJpdGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAg"
    "UVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleCgzKQoKICAgIGRlZiBfZG9fbW9kaWZ5X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxm"
    "Ll9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1si"
    "bmFtZSJdICAgICAgICA9IHNlbGYuX21vZF9uYW1lLnRleHQoKS5zdHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1si"
    "ZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQoKVs6MjQ0XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBm"
    "b3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2Rf"
    "dGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYu"
    "X21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBpdGVtcy5h"
    "cHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9XTiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0"
    "b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAgcmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAg"
    "IHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19k"
    "ZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5v"
    "dCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRlbGV0ZS4iKQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5x"
    "dWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/"
    "IFRoaXMgY2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBR"
    "TWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5T"
    "dGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRz"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lk"
    "XQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9z"
    "ZWxlY3RlZF9pZCA9IE5vbmUKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAg"
    "ICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJh"
    "dyA9IHJlYy5nZXQoInJhd190ZXh0IiwiIikKICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5p"
    "bmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2UiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3"
    "IHRleHQgc3RvcmVkIGZvciB0aGlzIHNjYW4uIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBz"
    "ZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1si"
    "bmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0gb3IgbmFtZQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUu"
    "bm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBh"
    "cnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJGb3VuZCB7bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgoj"
    "IOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMQ29tbWFu"
    "ZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQgcmVmZXJlbmNlIHRhYmxlLgogICAgR290"
    "aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQgYnV0dG9uIHBlciByb3cuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAg"
    "ICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAg"
    "ICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIp"
    "CiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5f"
    "ZGVsZXRlID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0"
    "bigi4qeJIENvcHkgQ29tbWFuZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxl"
    "Y3RlZCBjb21tYW5kIHRvIGNsaXBib2FyZCIpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsg"
    "UmVmcmVzaCIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNl"
    "bGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2NvcHlfY29tbWFuZCkKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZy"
    "ZXNoKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRl"
    "LAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwgc2VsZi5fYnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIu"
    "YWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAg"
    "ICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVh"
    "ZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAg"
    "ICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJl"
    "aGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5"
    "bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgog"
    "ICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxlY3QgYSByb3cgYW5kIGNsaWNrIOKniSBDb3B5IENvbW1h"
    "bmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50LnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRlZiByZWZyZXNoKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9"
    "IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAg"
    "IHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29t"
    "bWFuZCIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKSkKCiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIGl0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAg"
    "ICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFk"
    "ZCBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19H"
    "T0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAgICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNj"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3co"
    "IkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNf"
    "YnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5h"
    "Y2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMu"
    "YWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9n"
    "LkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zv"
    "cm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0"
    "KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAg"
    "ICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAgICJjcmVhdGVk"
    "X2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcmVjWyJjb21tYW5k"
    "Il06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlm"
    "IHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0g"
    "c2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRs"
    "ZSgiTW9kaWZ5IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29s"
    "b3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0"
    "KHJlYy5nZXQoImNvbW1hbmQiLCIiKSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwi"
    "IikpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlv"
    "bjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIp"
    "OyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3gu"
    "Y2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChj"
    "eCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2Rl"
    "LkFjY2VwdGVkOgogICAgICAgICAgICByZWNbImNvbW1hbmQiXSAgICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAg"
    "ICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNb"
    "InVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAg"
    "aWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjbWQg"
    "PSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhpcyBjb21tYW5kIikKICAgICAgICByZXBseSA9IFFNZXNz"
    "YWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwgZiJEZWxldGUgJ3tjbWR9Jz8iLAogICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAg"
    "ICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNl"
    "bGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBKT0IgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpvYiBhcHBsaWNhdGlv"
    "biB0cmFja2luZy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAgIEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxlLCBEYXRl"
    "IEFwcGxpZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1Yg"
    "YW5kIFRTViBleHBvcnQuCiAgICBIaWRkZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBq"
    "dXN0IG5vdCBzaG93bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBw"
    "bGllZCIsCiAgICAgICAgICAgICAgICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYs"
    "IHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0g"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiam9iX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtk"
    "aWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Qu"
    "c2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9n"
    "b3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgPSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAg"
    "ICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhpY19idG4oIkFyY2hpdmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVkL3JlamVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5o"
    "aWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlJl"
    "c3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRl"
    "bGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3RoaWNfYnRuKCJTaG93IEFyY2hpdmVkIikKICAgICAgICBz"
    "ZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIpCgogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRk"
    "LCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSwg"
    "c2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSwgc2VsZi5fYnRuX2V4cG9ydCk6"
    "CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAg"
    "ICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAg"
    "ICBzZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2ds"
    "ZV9oaWRkZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAg"
    "ICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0g"
    "UVRhYmxlV2lkZ2V0KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFk"
    "ZXJMYWJlbHMoc2VsZi5DT0xVTU5TKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAg"
    "ICAgIyBDb21wYW55IGFuZCBKb2IgVGl0bGUgc3RyZXRjaAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFI"
    "ZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRo"
    "CiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgyLCAxMDApCiAgICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGho"
    "LnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1"
    "cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDQsIDgwKQogICAgICAgICMgTm90ZXMgc3Ry"
    "ZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZp"
    "ZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAog"
    "ICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVl"
    "dChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAg"
    "ICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIsIEZhbHNlKSkKICAgICAgICAgICAgaWYgaGlkZGVuIGFu"
    "ZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByID0gc2VsZi5f"
    "dGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVz"
    "ID0gIkFyY2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAgICAgICAgICB2YWxz"
    "ID0gWwogICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiam9i"
    "X3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAg"
    "IHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5v"
    "dGVzIiwiIiksCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAg"
    "ICAgICAgICAgaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAg"
    "ICAgICAgICAgICAgICAgIGl0ZW0uc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRJdGVtKHIsIGMsIGl0ZW0pCiAgICAgICAgICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0"
    "IGNvbHVtbidzIHVzZXIgZGF0YQogICAgICAgICAgICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAg"
    "ICAgICAgICBRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJl"
    "YykKICAgICAgICAgICAgKQoKICAgIGRlZiBfc2VsZWN0ZWRfaW5kaWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAg"
    "aW5kaWNlcyA9IHNldCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2VsZi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAg"
    "ICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRlbS5yb3coKSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06"
    "CiAgICAgICAgICAgICAgICBpZHggPSByb3dfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAg"
    "ICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAg"
    "cmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUpIC0+IE9wdGlv"
    "bmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJKb2Ig"
    "QXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtD"
    "X0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQoK"
    "ICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnkiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAg"
    "ICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRl"
    "ICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVuZGFyUG9wdXAoVHJ1ZSkKICAgICAgICBkZS5zZXREaXNw"
    "bGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMgYW5kIHJlYy5nZXQoImRhdGVfYXBwbGllZCIpOgogICAg"
    "ICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwieXl5eS1NTS1kZCIpKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAg"
    "ID0gUUxpbmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0dXMgID0gUUxpbmVF"
    "ZGl0KHJlYy5nZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMgZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90ZXMgICA9"
    "IFFMaW5lRWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdl"
    "dCBpbiBbCiAgICAgICAgICAgICgiQ29tcGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAg"
    "ICAgICAoIkRhdGUgQXBwbGllZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3Rh"
    "dHVzKSwgKCJOb3RlczoiLCBub3RlcyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdl"
    "dCkKCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0g"
    "X2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2Vk"
    "LmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAg"
    "ICAgIGZvcm0uYWRkUm93KGJ0bnMpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2Vw"
    "dGVkOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICAgICAiam9iX3RpdGxlIjogICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAg"
    "ICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAg"
    "ICAibGluayI6ICAgICAgICAgbGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICBz"
    "dGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVz"
    "LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX2RvX2FkZChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2coKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHAudXBkYXRl"
    "KHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJoaWRkZW4i"
    "OiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUiOiBOb25lLAogICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5vdywKICAgICAgICB9KQogICAgICAgIHNl"
    "bGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNl"
    "bGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC5pbmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVj"
    "dCBleGFjdGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3Jl"
    "Y29yZHNbaWR4c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFsb2cocmVjKQogICAgICAgIGlmIG5vdCBwOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5u"
    "b3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Ig"
    "aWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMp"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJjb21wbGV0ZWRfZGF0ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHNbaWR4XS5nZXQoImNvbXBsZXRlZF9kYXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3co"
    "KS5kYXRlKCkuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4"
    "XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zv"
    "cm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fdW5oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlk"
    "eCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0"
    "aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0"
    "aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIG5vdCBpZHhzOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVs"
    "ZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQgYXBwbGljYXRpb24ocyk/IENhbm5vdCBi"
    "ZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3Rh"
    "bmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "WWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciBpLCBy"
    "IGluIGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJh"
    "ZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2hpZGRl"
    "biA9IG5vdCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAg"
    "IuKYgCBIaWRlIEFyY2hpdmVkIiBpZiBzZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBh"
    "dGgsIGZpbHQgPSBRRmlsZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRy"
    "YWNrZXIiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImV4cG9ydHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAg"
    "ICAgICAgIkNTViBGaWxlcyAoKi5jc3YpOztUYWIgRGVsaW1pdGVkICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5v"
    "dCBwYXRoOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRo"
    "KCIudHh0IikgZWxzZSAiLCIKICAgICAgICBoZWFkZXIgPSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQi"
    "LCJsaW5rIiwKICAgICAgICAgICAgICAgICAgInN0YXR1cyIsImhpZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQog"
    "ICAgICAgIHdpdGggb3BlbihwYXRoLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAg"
    "ICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxuIikKICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNv"
    "cmRzOgogICAgICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAg"
    "ICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAgICAgICAgICAgICAgICAgIHN0cihib29sKHJlYy5nZXQoImhp"
    "ZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGxldGVkX2RhdGUiLCIiKSBvciAiIiwK"
    "ICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgXQogICAgICAgICAgICAg"
    "ICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0cih2KS5yZXBsYWNlKCJcbiIsIiAiKS5yZXBs"
    "YWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxzCiAgICAgICAgICAgICAgICApICsgIlxu"
    "IikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKUgOKUgCBTRUxGIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgUmVjb3Jkc1RhYihRV2lkZ2V0KToKICAgICIiIkdv"
    "b2dsZSBEcml2ZS9Eb2NzIHJlY29yZHMgYnJvd3NlciB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiUmVjb3JkcyBhcmUgbm90IGxvYWRlZCB5ZXQuIikKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBzZWxmLnBhdGhfbGFiZWwgPSBRTGFiZWwoIlBhdGg6IE15"
    "IERyaXZlIikKICAgICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "R09MRF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnBhdGhfbGFiZWwpCgogICAgICAgIHNlbGYucmVjb3Jkc19saXN0ID0gUUxp"
    "c3RXaWRnZXQoKQogICAgICAgIHNlbGYucmVjb3Jkc19saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIKICAgICAgICAp"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5yZWNvcmRzX2xpc3QsIDEpCgogICAgZGVmIHNldF9pdGVtcyhzZWxmLCBm"
    "aWxlczogbGlzdFtkaWN0XSwgcGF0aF90ZXh0OiBzdHIgPSAiTXkgRHJpdmUiKSAtPiBOb25lOgogICAgICAgIHNlbGYucGF0"
    "aF9sYWJlbC5zZXRUZXh0KGYiUGF0aDoge3BhdGhfdGV4dH0iKQogICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmNsZWFyKCkK"
    "ICAgICAgICBmb3IgZmlsZV9pbmZvIGluIGZpbGVzOgogICAgICAgICAgICB0aXRsZSA9IChmaWxlX2luZm8uZ2V0KCJuYW1l"
    "Iikgb3IgIlVudGl0bGVkIikuc3RyaXAoKSBvciAiVW50aXRsZWQiCiAgICAgICAgICAgIG1pbWUgPSAoZmlsZV9pbmZvLmdl"
    "dCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBpZiBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29v"
    "Z2xlLWFwcHMuZm9sZGVyIjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OBIgogICAgICAgICAgICBlbGlmIG1pbWUg"
    "PT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCI6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+T"
    "nSIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OEIgogICAgICAgICAgICBtb2RpZmll"
    "ZCA9IChmaWxlX2luZm8uZ2V0KCJtb2RpZmllZFRpbWUiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikucmVwbGFjZSgiWiIs"
    "ICIgVVRDIikKICAgICAgICAgICAgdGV4dCA9IGYie3ByZWZpeH0ge3RpdGxlfSIgKyAoZiIgICAgW3ttb2RpZmllZH1dIiBp"
    "ZiBtb2RpZmllZCBlbHNlICIiKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKHRleHQpCiAgICAgICAgICAg"
    "IGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGZpbGVfaW5mbykKICAgICAgICAgICAgc2VsZi5yZWNv"
    "cmRzX2xpc3QuYWRkSXRlbShpdGVtKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJMb2FkZWQge2xlbihm"
    "aWxlcyl9IEdvb2dsZSBEcml2ZSBpdGVtKHMpLiIpCgoKY2xhc3MgVGFza3NUYWIoUVdpZGdldCk6CiAgICAiIiJUYXNrIHJl"
    "Z2lzdHJ5ICsgR29vZ2xlLWZpcnN0IGVkaXRvciB3b3JrZmxvdyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAg"
    "IHNlbGYsCiAgICAgICAgdGFza3NfcHJvdmlkZXIsCiAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuLAogICAgICAgIG9uX2Nv"
    "bXBsZXRlX3NlbGVjdGVkLAogICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZCwKICAgICAgICBvbl90b2dnbGVfY29tcGxldGVk"
    "LAogICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZCwKICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZCwKICAgICAgICBvbl9lZGl0"
    "b3Jfc2F2ZSwKICAgICAgICBvbl9lZGl0b3JfY2FuY2VsLAogICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lLAogICAg"
    "ICAgIHBhcmVudD1Ob25lLAogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl90"
    "YXNrc19wcm92aWRlciA9IHRhc2tzX3Byb3ZpZGVyCiAgICAgICAgc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuID0gb25fYWRk"
    "X2VkaXRvcl9vcGVuCiAgICAgICAgc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQgPSBvbl9jb21wbGV0ZV9zZWxlY3RlZAog"
    "ICAgICAgIHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCA9IG9uX2NhbmNlbF9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX3Rv"
    "Z2dsZV9jb21wbGV0ZWQgPSBvbl90b2dnbGVfY29tcGxldGVkCiAgICAgICAgc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkID0g"
    "b25fcHVyZ2VfY29tcGxldGVkCiAgICAgICAgc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQgPSBvbl9maWx0ZXJfY2hhbmdlZAog"
    "ICAgICAgIHNlbGYuX29uX2VkaXRvcl9zYXZlID0gb25fZWRpdG9yX3NhdmUKICAgICAgICBzZWxmLl9vbl9lZGl0b3JfY2Fu"
    "Y2VsID0gb25fZWRpdG9yX2NhbmNlbAogICAgICAgIHNlbGYuX2RpYWdfbG9nZ2VyID0gZGlhZ25vc3RpY3NfbG9nZ2VyCiAg"
    "ICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQog"
    "ICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBy"
    "b290LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAg"
    "ICByb290LmFkZFdpZGdldChzZWxmLndvcmtzcGFjZV9zdGFjaywgMSkKCiAgICAgICAgbm9ybWFsID0gUVdpZGdldCgpCiAg"
    "ICAgICAgbm9ybWFsX2xheW91dCA9IFFWQm94TGF5b3V0KG5vcm1hbCkKICAgICAgICBub3JtYWxfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxm"
    "LnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiVGFzayByZWdpc3RyeSBpcyBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgbm9ybWFsX2xheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREFURSBSQU5HRSIpKQogICAgICAgIHNlbGYudGFz"
    "a19maWx0ZXJfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiV0VF"
    "SyIsICJ3ZWVrIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk1PTlRIIiwgIm1vbnRoIikKICAg"
    "ICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk5FWFQgMyBNT05USFMiLCAibmV4dF8zX21vbnRocyIpCiAg"
    "ICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJZRUFSIiwgInllYXIiKQogICAgICAgIHNlbGYudGFza19m"
    "aWx0ZXJfY29tYm8uc2V0Q3VycmVudEluZGV4KDIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50SW5k"
    "ZXhDaGFuZ2VkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBfOiBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZChzZWxmLnRh"
    "c2tfZmlsdGVyX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgICkKICAgICAgICBmaWx0"
    "ZXJfcm93LmFkZFdpZGdldChzZWxmLnRhc2tfZmlsdGVyX2NvbWJvKQogICAgICAgIGZpbHRlcl9yb3cuYWRkU3RyZXRjaCgx"
    "KQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIHNlbGYudGFza190YWJsZSA9"
    "IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsi"
    "U3RhdHVzIiwgIkR1ZSIsICJUYXNrIiwgIlNvdXJjZSJdKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25C"
    "ZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rp"
    "b24pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEVkaXRUcmlnZ2VycyhRQWJzdHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dl"
    "ci5Ob0VkaXRUcmlnZ2VycykKICAgICAgICBzZWxmLnRhc2tfdGFibGUudmVydGljYWxIZWFkZXIoKS5zZXRWaXNpYmxlKEZh"
    "bHNlKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwg"
    "UUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9u"
    "dGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRl"
    "bnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwg"
    "UUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVy"
    "KCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZSkK"
    "ICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfdGFibGUsIDEpCgogICAgICAgIGFjdGlvbnMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlID0gX2dvdGhpY19idG4oIkFERCBUQVNL"
    "IikKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrID0gX2dvdGhpY19idG4oIkNPTVBMRVRFIFNFTEVDVEVEIikKICAg"
    "ICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzayA9IF9nb3RoaWNfYnRuKCJDQU5DRUwgU0VMRUNURUQiKQogICAgICAgIHNlbGYu"
    "YnRuX3RvZ2dsZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiU0hPVyBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX3B1"
    "cmdlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJQVVJHRSBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNr"
    "X3dvcmtzcGFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuKQogICAgICAgIHNlbGYuYnRuX2Nv"
    "bXBsZXRlX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRu"
    "X2NhbmNlbF90YXNrLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5f"
    "dG9nZ2xlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCkKICAgICAgICBzZWxm"
    "LmJ0bl9wdXJnZV9jb21wbGV0ZWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCkKICAgICAgICBz"
    "ZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0"
    "RW5hYmxlZChGYWxzZSkKICAgICAgICBmb3IgYnRuIGluICgKICAgICAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3Nw"
    "YWNlLAogICAgICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFz"
    "aywKICAgICAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29t"
    "cGxldGVkLAogICAgICAgICk6CiAgICAgICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KGJ0bikKICAgICAgICBub3JtYWxfbGF5"
    "b3V0LmFkZExheW91dChhY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChub3JtYWwpCgog"
    "ICAgICAgIGVkaXRvciA9IFFXaWRnZXQoKQogICAgICAgIGVkaXRvcl9sYXlvdXQgPSBRVkJveExheW91dChlZGl0b3IpCiAg"
    "ICAgICAgZWRpdG9yX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBlZGl0b3JfbGF5b3V0"
    "LnNldFNwYWNpbmcoNCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBUQVNLIEVE"
    "SVRPUiDigJQgR09PR0xFLUZJUlNUIikpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwgPSBRTGFiZWwo"
    "IkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307"
    "IGNvbG9yOiB7Q19URVhUX0RJTX07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAg"
    "ICAgKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lLnNl"
    "dFBsYWNlaG9sZGVyVGV4dCgiVGFzayBOYW1lIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUgPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IERh"
    "dGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUgPSBRTGluZUVkaXQoKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IFRpbWUgKEhIOk1NKSIp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9lbmRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9lbmRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRQbGFj"
    "ZWhvbGRlclRleHQoIkVuZCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24gPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24uc2V0UGxhY2Vob2xkZXJUZXh0KCJMb2NhdGlvbiAo"
    "b3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UgPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRQbGFjZWhvbGRlclRleHQoIlJlY3VycmVuY2UgUlJVTEUgKG9wdGlvbmFs"
    "KSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9hbGxfZGF5ID0gUUNoZWNrQm94KCJBbGwtZGF5IikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX25vdGVzID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiTm90ZXMiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0TWF4aW11bUhlaWdodCg5MCkK"
    "ICAgICAgICBmb3Igd2lkZ2V0IGluICgKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lLAogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSwKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGlt"
    "ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9y"
    "ZWN1cnJlbmNlLAogICAgICAgICk6CiAgICAgICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAg"
    "ICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkpCiAgICAgICAgZWRpdG9yX2xheW91"
    "dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9ub3RlcywgMSkKICAgICAgICBlZGl0b3JfYWN0aW9ucyA9IFFIQm94TGF5"
    "b3V0KCkKICAgICAgICBidG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCJTQVZFIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhp"
    "Y19idG4oIkNBTkNFTCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9zYXZlKQog"
    "ICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9jYW5jZWwpCiAgICAgICAgZWRpdG9y"
    "X2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5fY2FuY2Vs"
    "KQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFN0cmV0Y2goMSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZExheW91dChl"
    "ZGl0b3JfYWN0aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQoZWRpdG9yKQoKICAgICAgICBz"
    "ZWxmLm5vcm1hbF93b3Jrc3BhY2UgPSBub3JtYWwKICAgICAgICBzZWxmLmVkaXRvcl93b3Jrc3BhY2UgPSBlZGl0b3IKICAg"
    "ICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCiAgICBk"
    "ZWYgX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZW5hYmxlZCA9IGJvb2woc2Vs"
    "Zi5zZWxlY3RlZF90YXNrX2lkcygpKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChlbmFibGVk"
    "KQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKCiAgICBkZWYgc2VsZWN0ZWRfdGFz"
    "a19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlkczogbGlzdFtzdHJdID0gW10KICAgICAgICBmb3IgciBpbiBy"
    "YW5nZShzZWxmLnRhc2tfdGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gc2VsZi50YXNrX3Rh"
    "YmxlLml0ZW0ociwgMCkKICAgICAgICAgICAgaWYgc3RhdHVzX2l0ZW0gaXMgTm9uZToKICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCiAgICAgICAgICAgIGlmIG5vdCBzdGF0dXNfaXRlbS5pc1NlbGVjdGVkKCk6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICB0YXNrX2lkID0gc3RhdHVzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAg"
    "ICAgICAgIGlmIHRhc2tfaWQgYW5kIHRhc2tfaWQgbm90IGluIGlkczoKICAgICAgICAgICAgICAgIGlkcy5hcHBlbmQodGFz"
    "a19pZCkKICAgICAgICByZXR1cm4gaWRzCgogICAgZGVmIGxvYWRfdGFza3Moc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6"
    "CiAgICAgICAgICAgIHJvdyA9IHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5pbnNlcnRSb3cocm93KQogICAgICAgICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIiku"
    "bG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaWNvbiA9ICLimJEiIGlmIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5j"
    "ZWxsZWQifSBlbHNlICLigKIiCiAgICAgICAgICAgIGR1ZSA9ICh0YXNrLmdldCgiZHVlX2F0Iikgb3IgIiIpLnJlcGxhY2Uo"
    "IlQiLCAiICIpCiAgICAgICAgICAgIHRleHQgPSAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpIG9y"
    "ICJSZW1pbmRlciIKICAgICAgICAgICAgc291cmNlID0gKHRhc2suZ2V0KCJzb3VyY2UiKSBvciAibG9jYWwiKS5sb3dlcigp"
    "CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShmIntzdGF0dXNfaWNvbn0ge3N0YXR1c30iKQog"
    "ICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgdGFzay5nZXQoImlkIikp"
    "CiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMCwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNl"
    "bGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRhYmxlV2lkZ2V0SXRlbShkdWUpKQogICAgICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0ZW0odGV4dCkpCiAgICAgICAgICAgIHNlbGYudGFza190"
    "YWJsZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzb3VyY2UpKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVs"
    "LnNldFRleHQoZiJMb2FkZWQge2xlbih0YXNrcyl9IHRhc2socykuIikKICAgICAgICBzZWxmLl91cGRhdGVfYWN0aW9uX2J1"
    "dHRvbl9zdGF0ZSgpCgogICAgZGVmIF9kaWFnKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4g"
    "Tm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIHNlbGYuX2RpYWdfbG9nZ2VyOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ19sb2dnZXIobWVzc2FnZSwgbGV2ZWwpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFz"
    "cwoKICAgIGRlZiBzdG9wX3JlZnJlc2hfd29ya2VyKHNlbGYsIHJlYXNvbjogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAg"
    "dGhyZWFkID0gZ2V0YXR0cihzZWxmLCAiX3JlZnJlc2hfdGhyZWFkIiwgTm9uZSkKICAgICAgICBpZiB0aHJlYWQgaXMgbm90"
    "IE5vbmUgYW5kIGhhc2F0dHIodGhyZWFkLCAiaXNSdW5uaW5nIikgYW5kIHRocmVhZC5pc1J1bm5pbmcoKToKICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtUSFJFQURdW1dBUk5dIHN0b3AgcmVxdWVzdGVkIGZv"
    "ciByZWZyZXNoIHdvcmtlciByZWFzb249e3JlYXNvbiBvciAndW5zcGVjaWZpZWQnfSIsCiAgICAgICAgICAgICAgICAiV0FS"
    "TiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdGhyZWFkLnJlcXVlc3RJbnRlcnJ1"
    "cHRpb24oKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucXVpdCgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgICAgICBwYXNzCiAgICAgICAgICAgIHRocmVhZC53YWl0KDIwMDApCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQg"
    "PSBOb25lCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3QgY2FsbGFibGUoc2VsZi5fdGFz"
    "a3NfcHJvdmlkZXIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYubG9hZF90YXNr"
    "cyhzZWxmLl90YXNrc19wcm92aWRlcigpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWcoZiJbVEFTS1NdW1RBQl1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAg"
    "ICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX3JlZnJlc2hfZXhjZXB0aW9uIikKCiAgICBk"
    "ZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVh"
    "c29uPSJ0YXNrc190YWJfY2xvc2UiKQogICAgICAgIHN1cGVyKCkuY2xvc2VFdmVudChldmVudCkKCiAgICBkZWYgc2V0X3No"
    "b3dfY29tcGxldGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQg"
    "PSBib29sKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5zZXRUZXh0KCJISURFIENPTVBMRVRF"
    "RCIgaWYgc2VsZi5fc2hvd19jb21wbGV0ZWQgZWxzZSAiU0hPVyBDT01QTEVURUQiKQoKICAgIGRlZiBzZXRfc3RhdHVzKHNl"
    "bGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sg"
    "ZWxzZSBDX1RFWFRfRElNCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge2NvbG9yfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgcGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0"
    "VGV4dCh0ZXh0KQoKICAgIGRlZiBvcGVuX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0"
    "YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5lZGl0b3Jfd29ya3NwYWNlKQoKICAgIGRlZiBjbG9zZV9lZGl0b3Ioc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtz"
    "cGFjZSkKCgpjbGFzcyBTZWxmVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hJ3MgaW50ZXJuYWwgZGlhbG9ndWUg"
    "c3BhY2UuCiAgICBSZWNlaXZlczogaWRsZSBuYXJyYXRpdmUgb3V0cHV0LCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zLAog"
    "ICAgICAgICAgICAgIFBvSSBsaXN0IGZyb20gZGFpbHkgcmVmbGVjdGlvbiwgdW5hbnN3ZXJlZCBxdWVzdGlvbiBmbGFncywK"
    "ICAgICAgICAgICAgICBqb3VybmFsIGxvYWQgbm90aWZpY2F0aW9ucy4KICAgIFJlYWQtb25seSBkaXNwbGF5LiBTZXBhcmF0"
    "ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIgYWx3YXlzLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacgSU5O"
    "RVIgU0FOQ1RVTSDigJQge0RFQ0tfTkFNRS51cHBlcigpfSdTIFBSSVZBVEUgVEhPVUdIVFMiKSkKICAgICAgICBzZWxmLl9i"
    "dG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0"
    "aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0"
    "KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFk"
    "T25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVS"
    "UExFX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEx"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgog"
    "ICAgZGVmIGFwcGVuZChzZWxmLCBsYWJlbDogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0g"
    "ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJOQVJS"
    "QVRJVkUiOiAgQ19HT0xELAogICAgICAgICAgICAiUkVGTEVDVElPTiI6IENfUFVSUExFLAogICAgICAgICAgICAiSk9VUk5B"
    "TCI6ICAgIENfU0lMVkVSLAogICAgICAgICAgICAiUE9JIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICJTWVNU"
    "RU0iOiAgICAgQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBjb2xvcnMuZ2V0KGxhYmVsLnVwcGVyKCks"
    "IENfR09MRCkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAg"
    "ICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAg"
    "IGYn4p2nIHtsYWJlbH08L3NwYW4+PGJyPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57"
    "dGV4dH08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgiIikKICAgICAgICBzZWxmLl9k"
    "aXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxT"
    "Y3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgRElBR05PU1RJQ1MgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBEaWFnbm9zdGljc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgQmFja2VuZCBkaWFnbm9zdGljcyBk"
    "aXNwbGF5LgogICAgUmVjZWl2ZXM6IGhhcmR3YXJlIGRldGVjdGlvbiByZXN1bHRzLCBkZXBlbmRlbmN5IGNoZWNrIHJlc3Vs"
    "dHMsCiAgICAgICAgICAgICAgQVBJIGVycm9ycywgc3luYyBmYWlsdXJlcywgdGltZXIgZXZlbnRzLCBqb3VybmFsIGxvYWQg"
    "bm90aWNlcywKICAgICAgICAgICAgICBtb2RlbCBsb2FkIHN0YXR1cywgR29vZ2xlIGF1dGggZXZlbnRzLgogICAgQWx3YXlz"
    "IHNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9"
    "Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYp"
    "CiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRElB"
    "R05PU1RJQ1Mg4oCUIFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19i"
    "dG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5f"
    "YnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAgICAgICBo"
    "ZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYu"
    "X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9y"
    "OiB7Q19TSUxWRVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiAnQ291cmllciBOZXcnLCBtb25vc3BhY2U7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDEw"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgog"
    "ICAgZGVmIGxvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdGlt"
    "ZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAg"
    "ICAgICAgICAgICJJTkZPIjogIENfU0lMVkVSLAogICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAogICAgICAgICAgICAi"
    "V0FSTiI6ICBDX0dPTEQsCiAgICAgICAgICAgICJFUlJPUiI6IENfQkxPT0QsCiAgICAgICAgICAgICJERUJVRyI6IENfVEVY"
    "VF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gbGV2ZWxfY29sb3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZF"
    "UikKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVY"
    "VF9ESU19OyI+W3t0aW1lc3RhbXB9XTwvc3Bhbj4gJwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9"
    "OyI+e21lc3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigp"
    "LnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAg"
    "ICAgKQoKICAgIGRlZiBsb2dfbWFueShzZWxmLCBtZXNzYWdlczogbGlzdFtzdHJdLCBsZXZlbDogc3RyID0gIklORk8iKSAt"
    "PiBOb25lOgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXM6CiAgICAgICAgICAgIGx2bCA9IGxldmVsCiAgICAgICAgICAg"
    "IGlmICLinJMiIGluIG1zZzogICAgbHZsID0gIk9LIgogICAgICAgICAgICBlbGlmICLinJciIGluIG1zZzogIGx2bCA9ICJX"
    "QVJOIgogICAgICAgICAgICBlbGlmICJFUlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2bCA9ICJFUlJPUiIKICAgICAgICAgICAg"
    "c2VsZi5sb2cobXNnLCBsdmwpCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5j"
    "bGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhbmQgY29k"
    "ZSBsZXNzb25zIGJyb3dzZXIuCiAgICBBZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRlIGxlc3NvbnMuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVhcm5lZERCIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNw"
    "YWNpbmcoNCkKCiAgICAgICAgIyBGaWx0ZXIgYmFyCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9zZWFyY2ggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNl"
    "YXJjaCBsZXNzb25zLi4uIikKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5f"
    "bGFuZ19maWx0ZXIuYWRkSXRlbXMoWyJBbGwiLCAiTFNMIiwgIlB5dGhvbiIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJKYXZhU2NyaXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5fc2VhcmNoLnRleHRD"
    "aGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0Q2hhbmdl"
    "ZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIlNlYXJjaDoiKSkK"
    "ICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9zZWFyY2gsIDEpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJMYW5ndWFnZToiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikK"
    "ICAgICAgICByb290LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0bigi4pymIEFkZCBMZXNzb24iKQogICAgICAgIGJ0bl9kZWwgPSBfZ290aGljX2J0"
    "bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGJ0"
    "bl9kZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBidG5fYmFyLmFkZFdpZGdldChidG5fYWRk"
    "KQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAg"
    "ICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoCiAgICAgICAgICAgIFsiTGFuZ3VhZ2UiLCAiUmVm"
    "ZXJlbmNlIEtleSIsICJTdW1tYXJ5IiwgIkVudmlyb25tZW50Il0KICAgICAgICApCiAgICAgICAgc2VsZi5fdGFibGUuaG9y"
    "aXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0"
    "cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJu"
    "YXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkK"
    "CiAgICAgICAgIyBVc2Ugc3BsaXR0ZXIgYmV0d2VlbiB0YWJsZSBhbmQgZGV0YWlsCiAgICAgICAgc3BsaXR0ZXIgPSBRU3Bs"
    "aXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoK"
    "ICAgICAgICAjIERldGFpbCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBkZXRhaWxf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldENvbnRlbnRzTWFy"
    "Z2lucygwLCA0LCAwLCAwKQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVh"
    "ZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZV"
    "TEwgUlVMRSIpKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVs"
    "ZSA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAg"
    "ICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxl"
    "LnRvZ2dsZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZWRpdF9tb2RlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBf"
    "Z290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAg"
    "IHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9i"
    "dG5fZWRpdF9ydWxlKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlX3J1bGUpCiAgICAg"
    "ICAgZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hlYWRlcikKCiAgICAgICAgc2VsZi5fZGV0YWlsID0gUVRleHRF"
    "ZGl0KCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0TWlu"
    "aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsg"
    "cGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZGV0YWlsKQog"
    "ICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChkZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFszMDAs"
    "IDE4MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcSAgICA9IHNlbGYuX3NlYXJjaC50ZXh0KCkKICAgICAgICBsYW5nID0gc2VsZi5fbGFuZ19maWx0"
    "ZXIuY3VycmVudFRleHQoKQogICAgICAgIGxhbmcgPSAiIiBpZiBsYW5nID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAgIHNl"
    "bGYuX3JlY29yZHMgPSBzZWxmLl9kYi5zZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYu"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2Ui"
    "LCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdl"
    "dEl0ZW0ocmVjLmdldCgicmVmZXJlbmNlX2tleSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAy"
    "LAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRJdGVtKHIsIDMsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImVudmly"
    "b25tZW50IiwiIikpKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFi"
    "bGUuY3VycmVudFJvdygpCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3cgPSByb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxl"
    "bihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYu"
    "X2RldGFpbC5zZXRQbGFpblRleHQoCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiAr"
    "CiAgICAgICAgICAgICAgICAoIlJlc29sdXRpb246ICIgKyByZWMuZ2V0KCJyZXNvbHV0aW9uIiwiIikgaWYgcmVjLmdldCgi"
    "cmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBSZXNldCBlZGl0IG1vZGUgb24gbmV3"
    "IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCgogICAgZGVmIF90"
    "b2dnbGVfZWRpdF9tb2RlKHNlbGYsIGVkaXRpbmc6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFJl"
    "YWRPbmx5KG5vdCBlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShlZGl0aW5nKQogICAg"
    "ICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2VsIiBpZiBlZGl0aW5nIGVsc2UgIkVkaXQiKQogICAgICAg"
    "IGlmIGVkaXRpbmc6CiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNl"
    "bGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsi"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBSZWxvYWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5jZWwKICAgICAgICAg"
    "ICAgc2VsZi5fb25fc2VsZWN0KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93"
    "ID0gc2VsZi5fZWRpdGluZ19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgdGV4dCA9IHNlbGYuX2RldGFpbC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgIyBTcGxpdCByZXNvbHV0"
    "aW9uIGJhY2sgb3V0IGlmIHByZXNlbnQKICAgICAgICAgICAgaWYgIlxuXG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAg"
    "ICAgICAgICAgICBwYXJ0cyA9IHRleHQuc3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAgICAgICAgICAgZnVs"
    "bF9ydWxlICA9IHBhcnRzWzBdLnN0cmlwKCkKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBwYXJ0c1sxXS5zdHJpcCgp"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gdGV4dAogICAgICAgICAgICAgICAgcmVz"
    "b2x1dGlvbiA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoInJlc29sdXRpb24iLCAiIikKICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkc1tyb3ddWyJmdWxsX3J1bGUiXSAgPSBmdWxsX3J1bGUKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJyZXNv"
    "bHV0aW9uIl0gPSByZXNvbHV0aW9uCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX2RiLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAg"
    "ICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgTGVzc29uIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tn"
    "cm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTAwLCA0MDApCiAgICAgICAg"
    "Zm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBlbnYgID0gUUxpbmVFZGl0KCJMU0wiKQogICAgICAgIGxhbmcgPSBR"
    "TGluZUVkaXQoIkxTTCIpCiAgICAgICAgcmVmICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc3VtbSA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgcnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVtSGVpZ2h0KDEwMCkKICAgICAgICByZXMg"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBsaW5rID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3IgbGFiZWwsIHcgaW4gWwogICAg"
    "ICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgiTGFuZ3VhZ2U6IiwgbGFuZyksCiAgICAgICAgICAgICgiUmVmZXJl"
    "bmNlIEtleToiLCByZWYpLCAoIlN1bW1hcnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBSdWxlOiIsIHJ1bGUpLCAo"
    "IlJlc29sdXRpb246IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06CiAgICAgICAgICAg"
    "IGZvcm0uYWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGlj"
    "X2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcu"
    "YWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5z"
    "LmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxv"
    "Zy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9kYi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9u"
    "bWVudD1lbnYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQoKS5zdHJpcCgpLAog"
    "ICAgICAgICAgICAgICAgcmVmZXJlbmNlX2tleT1yZWYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBzdW1tYXJ5"
    "PXN1bW0udGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBmdWxsX3J1bGU9cnVsZS50b1BsYWluVGV4dCgpLnN0cmlw"
    "KCksCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uPXJlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxpbms9"
    "bGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAg"
    "aWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlY19pZCA9IHNlbGYuX3JlY29yZHNbcm93"
    "XS5nZXQoImlkIiwiIikKICAgICAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAg"
    "IHNlbGYsICJEZWxldGUgTGVzc29uIiwKICAgICAgICAgICAgICAgICJEZWxldGUgdGhpcyBsZXNzb24/IENhbm5vdCBiZSB1"
    "bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRh"
    "cmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fZGIuZGVsZXRlKHJlY19pZCkKICAgICAgICAgICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgoKIyDilIDilIAgTU9EVUxFIFRSQUNLRVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBNb2R1bGVUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hbCBtb2R1bGUgcGlwZWxpbmUgdHJhY2tl"
    "ci4KICAgIFRyYWNrIHBsYW5uZWQvaW4tcHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBhcyB0aGV5IGFyZSBkZXNpZ25lZC4KICAg"
    "IEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNjcmlwdGlvbiwgTm90ZXMuCiAgICBFeHBvcnQgdG8gVFhUIGZv"
    "ciBwYXN0aW5nIGludG8gc2Vzc2lvbnMuCiAgICBJbXBvcnQ6IHBhc3RlIGEgZmluYWxpemVkIHNwZWMsIGl0IHBhcnNlcyBu"
    "YW1lIGFuZCBkZXRhaWxzLgogICAgVGhpcyBpcyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5lY3RlZCB0byBkZWNr"
    "X2J1aWxkZXIncyBNT0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIsICJEZXNpZ25pbmci"
    "LCAiUmVhZHkgdG8gQnVpbGQiLCAiUGFydGlhbCIsICJCdWlsdCJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1l"
    "bW9yaWVzIikgLyAibW9kdWxlX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtd"
    "CiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJn"
    "aW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAg"
    "IGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9k"
    "dWxlIikKICAgICAgICBzZWxmLl9idG5fZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9k"
    "ZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4"
    "cG9ydCBUWFQiKQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNwZWMiKQogICAgICAg"
    "IGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZWRpdCwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fYnRuX2V4cG9ydCwgc2VsZi5fYnRuX2ltcG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRo"
    "KDgwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGIp"
    "CiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBz"
    "ZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAg"
    "ICAgICBzZWxmLl9idG5faW1wb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19pbXBvcnQpCgogICAgICAgICMgVGFibGUK"
    "ICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250"
    "YWxIZWFkZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3JpcHRpb24iXSkKICAgICAgICBoaCA9IHNl"
    "bGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMCwgMTYwKQogICAgICAg"
    "IGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0Q29sdW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAg"
    "ICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhp"
    "Y190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5f"
    "b25fc2VsZWN0KQoKICAgICAgICAjIFNwbGl0dGVyCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRp"
    "b24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIE5vdGVzIHBh"
    "bmVsCiAgICAgICAgbm90ZXNfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgbm90ZXNfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "bm90ZXNfd2lkZ2V0KQogICAgICAgIG5vdGVzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAg"
    "ICBub3Rlc19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgTk9URVMiKSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9u"
    "b3Rlc19kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRNaW5pbXVtSGVp"
    "Z2h0KDEyMCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsg"
    "cGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ub3Rlc19kaXNw"
    "bGF5KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChub3Rlc193aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMo"
    "WzI1MCwgMTUwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgIyBDb3VudCBsYWJlbAog"
    "ICAgICAgIHNlbGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvdW50X2xibCkKCiAgICBk"
    "ZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAg"
    "ICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhy"
    "KQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibmFtZSIs"
    "ICIiKSkpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdGF0dXMiLCAiSWRl"
    "YSIpKQogICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAg"
    "ICAgICAgICAgIklkZWEiOiAgICAgICAgICAgICBDX1RFWFRfRElNLAogICAgICAgICAgICAgICAgIkRlc2lnbmluZyI6ICAg"
    "ICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAgICAgIlJlYWR5IHRvIEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAgICAg"
    "ICAgICAgICJQYXJ0aWFsIjogICAgICAgICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0IjogICAgICAgICAg"
    "ICBDX0dSRUVOLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVncm91bmQoCiAgICAgICAg"
    "ICAgICAgICBRQ29sb3Ioc3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpLCBDX1RFWFRfRElNKSkK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsIHN0YXR1c19pdGVtKQogICAgICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQo"
    "ImRlc2NyaXB0aW9uIiwgIiIpWzo4MF0pKQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9y"
    "ZWNvcmRzOgogICAgICAgICAgICBzID0gcmVjLmdldCgic3RhdHVzIiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10g"
    "PSBjb3VudHMuZ2V0KHMsIDApICsgMQogICAgICAgIGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfToge259IiBmb3Igcywg"
    "biBpbiBjb3VudHMuaXRlbXMoKSkKICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0VGV4dCgKICAgICAgICAgICAgZiJUb3Rh"
    "bDoge2xlbihzZWxmLl9yZWNvcmRzKX0gICB7Y291bnRfc3RyfSIKICAgICAgICApCgogICAgZGVmIF9vbl9zZWxlY3Qoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8"
    "IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNl"
    "bGYuX25vdGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwgIiIpKQoKICAgIGRlZiBfZG9fYWRkKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZygpCgogICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4o"
    "c2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coc2VsZi5fcmVjb3Jkc1tyb3ddLCBy"
    "b3cpCgogICAgZGVmIF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUsIHJvdzogaW50ID0gLTEpIC0+"
    "IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kdWxlIiBp"
    "ZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQo"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDU0MCwgNDQwKQog"
    "ICAgICAgIGZvcm0gPSBRVkJveExheW91dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGluZUVkaXQocmVjLmdldCgi"
    "bmFtZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJNb2R1bGUg"
    "bmFtZSIpCgogICAgICAgIHN0YXR1c19jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2NvbWJvLmFkZEl0ZW1z"
    "KHNlbGYuU1RBVFVTRVMpCiAgICAgICAgaWYgcmVjOgogICAgICAgICAgICBpZHggPSBzdGF0dXNfY29tYm8uZmluZFRleHQo"
    "cmVjLmdldCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgICAgIHN0YXR1"
    "c19jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQoKICAgICAgICBkZXNjX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoImRl"
    "c2NyaXB0aW9uIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9u"
    "ZS1saW5lIGRlc2NyaXB0aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIG5vdGVzX2Zp"
    "ZWxkLnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5vdGVzX2ZpZWxk"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIkZ1bGwgbm90ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVu"
    "dHMsIGVkZ2UgY2FzZXMuLi4iCiAgICAgICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1IZWlnaHQoMjAwKQoK"
    "ICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxkKSwKICAgICAg"
    "ICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzX2NvbWJvKSwKICAgICAgICAgICAgKCJEZXNjcmlwdGlvbjoiLCBkZXNjX2ZpZWxk"
    "KSwKICAgICAgICAgICAgKCJOb3RlczoiLCBub3Rlc19maWVsZCksCiAgICAgICAgXToKICAgICAgICAgICAgcm93X2xheW91"
    "dCA9IFFIQm94TGF5b3V0KCkKICAgICAgICAgICAgbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4"
    "ZWRXaWR0aCg5MCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICByb3dfbGF5b3V0"
    "LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgICAgIGZvcm0uYWRkTGF5b3V0KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9y"
    "b3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgICA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBidG5f"
    "Y2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KGRsZy5hY2Nl"
    "cHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdp"
    "ZGdldChidG5fc2F2ZSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGZvcm0uYWRkTGF5"
    "b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAg"
    "ICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgcmVjLmdldCgiaWQiLCBzdHIodXVp"
    "ZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ugc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAibmFtZSI6ICAgICAg"
    "ICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgc3RhdHVzX2NvbWJv"
    "LmN1cnJlbnRUZXh0KCksCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxkLnRleHQoKS5zdHJpcCgp"
    "LAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAg"
    "ICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgp"
    "KSBpZiByZWMgZWxzZSBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAg"
    "IGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2Vs"
    "Zi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYu"
    "X3JlY29yZHMpOgogICAgICAgICAgICBuYW1lID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgibmFtZSIsInRoaXMgbW9kdWxl"
    "IikKICAgICAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxl"
    "dGUgTW9kdWxlIiwKICAgICAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAg"
    "ICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5O"
    "bwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYu"
    "X3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMi"
    "KQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAg"
    "dHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhw"
    "b3J0X2RpciAvIGYibW9kdWxlc197dHN9LnR4dCIKICAgICAgICAgICAgbGluZXMgPSBbCiAgICAgICAgICAgICAgICAiRUNI"
    "TyBERUNLIOKAlCBNT0RVTEUgVFJBQ0tFUiBFWFBPUlQiLAogICAgICAgICAgICAgICAgZiJFeHBvcnRlZDoge2RhdGV0aW1l"
    "Lm5vdygpLnN0cmZ0aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAgICAgICAgICAgICBmIlRvdGFsIG1vZHVsZXM6"
    "IHtsZW4oc2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAgICAgICI9IiAqIDYwLAogICAgICAgICAgICAgICAgIiIsCiAg"
    "ICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgbGluZXMu"
    "ZXh0ZW5kKFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVMRToge3JlYy5nZXQoJ25hbWUnLCcnKX0iLAogICAgICAgICAg"
    "ICAgICAgICAgIGYiU3RhdHVzOiB7cmVjLmdldCgnc3RhdHVzJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIkRlc2Ny"
    "aXB0aW9uOiB7cmVjLmdldCgnZGVzY3JpcHRpb24nLCcnKX0iLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAg"
    "ICAgICAgICAgICJOb3RlczoiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIi0iICogNDAsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAg"
    "ICAgICAgICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KCJcbiIuam9pbihsaW5lcyksIGVuY29kaW5n"
    "PSJ1dGYtOCIpCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykp"
    "CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwK"
    "ICAgICAgICAgICAgICAgIGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9XG5cbkFsc28gY29waWVk"
    "IHRvIGNsaXBib2FyZC4iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94Lndhcm5pbmcoc2VsZiwgIkV4cG9ydCBFcnJvciIsIHN0cihlKSkKCiAgICBkZWYgX2RvX2ltcG9ydChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIkltcG9ydCBhIG1vZHVsZSBzcGVjIGZyb20gY2xpcGJvYXJkIG9yIHR5cGVkIHRl"
    "eHQuIiIiCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1v"
    "ZHVsZSBTcGVjIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19H"
    "T0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTAwLCAzNDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKAogICAgICAgICAgICAiUGFzdGUgYSBtb2R1bGUgc3BlYyBiZWxvdy5c"
    "biIKICAgICAgICAgICAgIkZpcnN0IGxpbmUgd2lsbCBiZSB1c2VkIGFzIHRoZSBtb2R1bGUgbmFtZS4iCiAgICAgICAgKSkK"
    "ICAgICAgICB0ZXh0X2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "UGFzdGUgbW9kdWxlIHNwZWMgaGVyZS4uLiIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQogICAg"
    "ICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX29rICAgICA9IF9nb3RoaWNfYnRuKCJJbXBvcnQiKQog"
    "ICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBidG5fb2suY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5f"
    "cm93LmFkZFdpZGdldChidG5fb2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2Vw"
    "dGVkOgogICAgICAgICAgICByYXcgPSB0ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBpZiBu"
    "b3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIGxpbmVzID0gcmF3LnNwbGl0bGluZXMoKQogICAg"
    "ICAgICAgICAjIEZpcnN0IG5vbi1lbXB0eSBsaW5lID0gbmFtZQogICAgICAgICAgICBuYW1lID0gIiIKICAgICAgICAgICAg"
    "Zm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICAgICBpZiBsaW5lLnN0cmlwKCk6CiAgICAgICAgICAgICAgICAgICAg"
    "bmFtZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAg"
    "ICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjog"
    "ICAgICAgIG5hbWVbOjYwXSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICJJZGVhIiwKICAgICAgICAgICAgICAg"
    "ICJkZXNjcmlwdGlvbiI6ICIiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgcmF3LAogICAgICAgICAgICAgICAg"
    "ImNyZWF0ZWQiOiAgICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAg"
    "ICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFw"
    "cGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIFBBU1MgNSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBBbGwgdGFiIGNvbnRlbnQgY2xhc3NlcyBkZWZpbmVkLgojIFNMU2NhbnNUYWI6IHJlYnVpbHQg4oCU"
    "IERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLCB0aW1lc3RhbXAgcGFyc2VyIGZpeGVkLAojICAgICAgICAgICAgIGNhcmQv"
    "Z3JpbW9pcmUgc3R5bGUsIGNvcHktdG8tY2xpcGJvYXJkIGNvbnRleHQgbWVudS4KIyBTTENvbW1hbmRzVGFiOiBnb3RoaWMg"
    "dGFibGUsIOKniSBDb3B5IENvbW1hbmQgYnV0dG9uLgojIEpvYlRyYWNrZXJUYWI6IGZ1bGwgcmVidWlsZCDigJQgbXVsdGkt"
    "c2VsZWN0LCBhcmNoaXZlL3Jlc3RvcmUsIENTVi9UU1YgZXhwb3J0LgojIFNlbGZUYWI6IGlubmVyIHNhbmN0dW0gZm9yIGlk"
    "bGUgbmFycmF0aXZlIGFuZCByZWZsZWN0aW9uIG91dHB1dC4KIyBEaWFnbm9zdGljc1RhYjogc3RydWN0dXJlZCBsb2cgd2l0"
    "aCBsZXZlbC1jb2xvcmVkIG91dHB1dC4KIyBMZXNzb25zVGFiOiBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYnJvd3NlciB3aXRo"
    "IGFkZC9kZWxldGUvc2VhcmNoLgojCiMgTmV4dDogUGFzcyA2IOKAlCBNYWluIFdpbmRvdwojIChNb3JnYW5uYURlY2sgY2xh"
    "c3MsIGZ1bGwgbGF5b3V0LCBBUFNjaGVkdWxlciwgZmlyc3QtcnVuIGZsb3csCiMgIGRlcGVuZGVuY3kgYm9vdHN0cmFwLCBz"
    "aG9ydGN1dCBjcmVhdGlvbiwgc3RhcnR1cCBzZXF1ZW5jZSkKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5B"
    "IERFQ0sg4oCUIFBBU1MgNjogTUFJTiBXSU5ET1cgJiBFTlRSWSBQT0lOVAojCiMgQ29udGFpbnM6CiMgICBib290c3RyYXBf"
    "Y2hlY2soKSAgICAg4oCUIGRlcGVuZGVuY3kgdmFsaWRhdGlvbiArIGF1dG8taW5zdGFsbCBiZWZvcmUgVUkKIyAgIEZpcnN0"
    "UnVuRGlhbG9nICAgICAgICDigJQgbW9kZWwgcGF0aCArIGNvbm5lY3Rpb24gdHlwZSBzZWxlY3Rpb24KIyAgIEpvdXJuYWxT"
    "aWRlYmFyICAgICAgICDigJQgY29sbGFwc2libGUgbGVmdCBzaWRlYmFyIChzZXNzaW9uIGJyb3dzZXIgKyBqb3VybmFsKQoj"
    "ICAgVG9ycG9yUGFuZWwgICAgICAgICAgIOKAlCBBV0FLRSAvIEFVVE8gLyBTVVNQRU5EIHN0YXRlIHRvZ2dsZQojICAgTW9y"
    "Z2FubmFEZWNrICAgICAgICAgIOKAlCBtYWluIHdpbmRvdywgZnVsbCBsYXlvdXQsIGFsbCBzaWduYWwgY29ubmVjdGlvbnMK"
    "IyAgIG1haW4oKSAgICAgICAgICAgICAgICDigJQgZW50cnkgcG9pbnQgd2l0aCBib290c3RyYXAgc2VxdWVuY2UKIyDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZAKCmltcG9ydCBzdWJwcm9jZXNzCgoKIyDilIDilIAgUFJFLUxBVU5DSCBERVBFTkRFTkNZIEJP"
    "T1RTVFJBUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJvb3Rz"
    "dHJhcF9jaGVjaygpIC0+IE5vbmU6CiAgICAiIiIKICAgIFJ1bnMgQkVGT1JFIFFBcHBsaWNhdGlvbiBpcyBjcmVhdGVkLgog"
    "ICAgQ2hlY2tzIGZvciBQeVNpZGU2IHNlcGFyYXRlbHkgKGNhbid0IHNob3cgR1VJIHdpdGhvdXQgaXQpLgogICAgQXV0by1p"
    "bnN0YWxscyBhbGwgb3RoZXIgbWlzc2luZyBub24tY3JpdGljYWwgZGVwcyB2aWEgcGlwLgogICAgVmFsaWRhdGVzIGluc3Rh"
    "bGxzIHN1Y2NlZWRlZC4KICAgIFdyaXRlcyByZXN1bHRzIHRvIGEgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFi"
    "IHRvIHBpY2sgdXAuCiAgICAiIiIKICAgICMg4pSA4pSAIFN0ZXAgMTogQ2hlY2sgUHlTaWRlNiAoY2FuJ3QgYXV0by1pbnN0"
    "YWxsIHdpdGhvdXQgaXQgYWxyZWFkeSBwcmVzZW50KSDilIAKICAgIHRyeToKICAgICAgICBpbXBvcnQgUHlTaWRlNiAgIyBu"
    "b3FhCiAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgIyBObyBHVUkgYXZhaWxhYmxlIOKAlCB1c2UgV2luZG93cyBu"
    "YXRpdmUgZGlhbG9nIHZpYSBjdHlwZXMKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydCBjdHlwZXMKICAgICAgICAg"
    "ICAgY3R5cGVzLndpbmRsbC51c2VyMzIuTWVzc2FnZUJveFcoCiAgICAgICAgICAgICAgICAwLAogICAgICAgICAgICAgICAg"
    "IlB5U2lkZTYgaXMgcmVxdWlyZWQgYnV0IG5vdCBpbnN0YWxsZWQuXG5cbiIKICAgICAgICAgICAgICAgICJPcGVuIGEgdGVy"
    "bWluYWwgYW5kIHJ1bjpcblxuIgogICAgICAgICAgICAgICAgIiAgICBwaXAgaW5zdGFsbCBQeVNpZGU2XG5cbiIKICAgICAg"
    "ICAgICAgICAgIGYiVGhlbiByZXN0YXJ0IHtERUNLX05BTUV9LiIsCiAgICAgICAgICAgICAgICBmIntERUNLX05BTUV9IOKA"
    "lCBNaXNzaW5nIERlcGVuZGVuY3kiLAogICAgICAgICAgICAgICAgMHgxMCAgIyBNQl9JQ09ORVJST1IKICAgICAgICAgICAg"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHByaW50KCJDUklUSUNBTDogUHlTaWRlNiBub3QgaW5z"
    "dGFsbGVkLiBSdW46IHBpcCBpbnN0YWxsIFB5U2lkZTYiKQogICAgICAgIHN5cy5leGl0KDEpCgogICAgIyDilIDilIAgU3Rl"
    "cCAyOiBBdXRvLWluc3RhbGwgb3RoZXIgbWlzc2luZyBkZXBzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0FVVE9f"
    "SU5TVEFMTCA9IFsKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiKSwKICAgICAg"
    "ICAoImxvZ3VydSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAg"
    "ICAgICAgICAgInB5Z2FtZSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJweXdpbjMyIiksCiAg"
    "ICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAg"
    "ICAgICAgICAgICAgICJyZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJnb29nbGVh"
    "cGljbGllbnQiKSwKICAgICAgICAoImdvb2dsZS1hdXRoLW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIi"
    "KSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiKSwKICAgIF0KCiAgICBpbXBv"
    "cnQgaW1wb3J0bGliCiAgICBib290c3RyYXBfbG9nID0gW10KCiAgICBmb3IgcGlwX25hbWUsIGltcG9ydF9uYW1lIGluIF9B"
    "VVRPX0lOU1RBTEw6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFt"
    "ZSkKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAg"
    "ICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "IGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBtaXNzaW5nIOKAlCBpbnN0YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHN1YnByb2Nlc3MucnVuKAogICAgICAgICAgICAgICAgICAg"
    "IFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwgInBpcCIsICJpbnN0YWxsIiwKICAgICAgICAgICAgICAgICAgICAgcGlwX25hbWUs"
    "ICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRpb24iXSwKICAgICAgICAgICAgICAgICAgICBjYXB0dXJlX291"
    "dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRpbWVvdXQ9MTIwCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBy"
    "ZXN1bHQucmV0dXJuY29kZSA9PSAwOgogICAgICAgICAgICAgICAgICAgICMgVmFsaWRhdGUgaXQgYWN0dWFsbHkgaW1wb3J0"
    "ZWQgbm93CiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0"
    "X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbGVkIOKckyIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbCBhcHBlYXJlZCB0byAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInN1Y2NlZWQg"
    "YnV0IGltcG9ydCBzdGlsbCBmYWlscyDigJQgcmVzdGFydCBtYXkgIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJi"
    "ZSByZXF1aXJlZC4iCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3Bp"
    "cF9uYW1lfSBpbnN0YWxsIGZhaWxlZDogIgogICAgICAgICAgICAgICAgICAgICAgICBmIntyZXN1bHQuc3RkZXJyWzoyMDBd"
    "fSIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBzdWJwcm9jZXNzLlRpbWVvdXRFeHBpcmVkOgog"
    "ICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7"
    "cGlwX25hbWV9IGluc3RhbGwgdGltZWQgb3V0LiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJb"
    "Qk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZXJyb3I6IHtlfSIKICAgICAgICAgICAgICAgICkKCiAgICAjIOKUgOKU"
    "gCBTdGVwIDM6IFdyaXRlIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIHRyeToKICAgICAgICBsb2dfcGF0"
    "aCA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAgICAgICAgd2l0aCBsb2dfcGF0aC5vcGVu"
    "KCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZSgiXG4iLmpvaW4oYm9vdHN0cmFwX2xv"
    "ZykpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCgojIOKUgOKUgCBGSVJTVCBSVU4gRElBTE9HIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGaXJzdFJ1bkRpYWxvZyhRRGlhbG9nKToKICAgICIiIgogICAgU2hv"
    "d24gb24gZmlyc3QgbGF1bmNoIHdoZW4gY29uZmlnLmpzb24gZG9lc24ndCBleGlzdC4KICAgIENvbGxlY3RzIG1vZGVsIGNv"
    "bm5lY3Rpb24gdHlwZSBhbmQgcGF0aC9rZXkuCiAgICBWYWxpZGF0ZXMgY29ubmVjdGlvbiBiZWZvcmUgYWNjZXB0aW5nLgog"
    "ICAgV3JpdGVzIGNvbmZpZy5qc29uIG9uIHN1Y2Nlc3MuCiAgICBDcmVhdGVzIGRlc2t0b3Agc2hvcnRjdXQuCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5H"
    "IikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCiAgICAgICAgc2VsZi5zZXRGaXhlZFNpemUoNTIwLCA0MDAp"
    "CiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldFNwYWNpbmcoMTApCgogICAgICAgIHRpdGxlID0gUUxhYmVs"
    "KGYi4pymIHtERUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyDinKYiKQogICAgICAgIHRpdGxlLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE0cHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6"
    "IDJweDsiCiAgICAgICAgKQogICAgICAgIHRpdGxlLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVy"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHRpdGxlKQoKICAgICAgICBzdWIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiQ29u"
    "ZmlndXJlIHRoZSB2ZXNzZWwgYmVmb3JlIHtERUNLX05BTUV9IG1heSBhd2FrZW4uXG4iCiAgICAgICAgICAgICJBbGwgc2V0"
    "dGluZ3MgYXJlIHN0b3JlZCBsb2NhbGx5LiBOb3RoaW5nIGxlYXZlcyB0aGlzIG1hY2hpbmUuIgogICAgICAgICkKICAgICAg"
    "ICBzdWIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7"
    "ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc3Vi"
    "LnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHN1YikK"
    "CiAgICAgICAgIyDilIDilIAgQ29ubmVjdGlvbiB0eXBlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEFJIENPTk5F"
    "Q1RJT04gVFlQRSIpKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX3R5cGVf"
    "Y29tYm8uYWRkSXRlbXMoWwogICAgICAgICAgICAiTG9jYWwgbW9kZWwgZm9sZGVyICh0cmFuc2Zvcm1lcnMpIiwKICAgICAg"
    "ICAgICAgIk9sbGFtYSAobG9jYWwgc2VydmljZSkiLAogICAgICAgICAgICAiQ2xhdWRlIEFQSSAoQW50aHJvcGljKSIsCiAg"
    "ICAgICAgICAgICJPcGVuQUkgQVBJIiwKICAgICAgICBdKQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4"
    "Q2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3R5cGVfY2hhbmdlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3R5cGVf"
    "Y29tYm8pCgogICAgICAgICMg4pSA4pSAIER5bmFtaWMgY29ubmVjdGlvbiBmaWVsZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCgogICAgICAgICMgUGFnZSAwOiBMb2Nh"
    "bCBwYXRoCiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFIQm94TGF5b3V0KHAwKQogICAgICAgIGwwLnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2xvY2FsX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAg"
    "IHNlbGYuX2xvY2FsX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICByIkQ6XEFJXE1vZGVsc1xkb2xwaGlu"
    "LThiIgogICAgICAgICkKICAgICAgICBidG5fYnJvd3NlID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2Jy"
    "b3dzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX21vZGVsKQogICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9sb2Nh"
    "bF9wYXRoKTsgbDAuYWRkV2lkZ2V0KGJ0bl9icm93c2UpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAg"
    "ICAgICAjIFBhZ2UgMTogT2xsYW1hIG1vZGVsIG5hbWUKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUUhC"
    "b3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2xsYW1h"
    "X21vZGVsID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwuc2V0UGxhY2Vob2xkZXJUZXh0KCJkb2xw"
    "aGluLTIuNi03YiIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX29sbGFtYV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFj"
    "ay5hZGRXaWRnZXQocDEpCgogICAgICAgICMgUGFnZSAyOiBDbGF1ZGUgQVBJIGtleQogICAgICAgIHAyID0gUVdpZGdldCgp"
    "CiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAg"
    "ICAgICBzZWxmLl9jbGF1ZGVfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KCJzay1hbnQtLi4uIikKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5F"
    "Y2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9jbGF1ZGVfbW9kZWwgPSBRTGluZUVkaXQoImNsYXVkZS1zb25uZXQt"
    "NC02IikKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJBUEkgS2V5OiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxm"
    "Ll9jbGF1ZGVfa2V5KQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAgIGwyLmFkZFdpZGdl"
    "dChzZWxmLl9jbGF1ZGVfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIFBhZ2Ug"
    "MzogT3BlbkFJCiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwz"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29haV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fb2FpX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLS4uLiIpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRF"
    "Y2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fb2FpX21vZGVsID0gUUxpbmVFZGl0"
    "KCJncHQtNG8iKQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDMuYWRkV2lkZ2V0"
    "KHNlbGYuX29haV9rZXkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDMuYWRkV2lk"
    "Z2V0KHNlbGYuX29haV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX3N0YWNrKQoKICAgICAgICAjIOKUgOKUgCBUZXN0ICsgc3RhdHVzIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHRlc3Rfcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl90ZXN0ID0gX2dvdGhpY19idG4oIlRlc3QgQ29ubmVjdGlvbiIpCiAgICAgICAg"
    "c2VsZi5fYnRuX3Rlc3QuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Rlc3RfY29ubmVjdGlvbikKICAgICAgICBzZWxmLl9zdGF0"
    "dXNfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl90ZXN0KQog"
    "ICAgICAgIHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9zdGF0dXNfbGJsLCAxKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KHRl"
    "c3Rfcm93KQoKICAgICAgICAjIOKUgOKUgCBGYWNlIFBhY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgRkFDRSBQQUNLIChvcHRpb25hbCDigJQgWklQIGZpbGUpIikpCiAgICAgICAgZmFjZV9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGgu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICBmIkJyb3dzZSB0byB7REVDS19OQU1FfSBmYWNlIHBhY2sgWklQIChv"
    "cHRpb25hbCwgY2FuIGFkZCBsYXRlcikiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDZweCAxMHB4OyIKICAgICAg"
    "ICApCiAgICAgICAgYnRuX2ZhY2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fZmFjZS5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fYnJvd3NlX2ZhY2UpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lkZ2V0KHNlbGYuX2ZhY2VfcGF0aCkKICAg"
    "ICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoYnRuX2ZhY2UpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmFjZV9yb3cpCgogICAg"
    "ICAgICMg4pSA4pSAIFNob3J0Y3V0IG9wdGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYiA9IFFDaGVja0JveCgKICAgICAgICAgICAgIkNy"
    "ZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IChyZWNvbW1lbmRlZCkiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2Ni"
    "LnNldENoZWNrZWQoVHJ1ZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zaG9ydGN1dF9jYikKCiAgICAgICAgIyDi"
    "lIDilIAgQnV0dG9ucyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFN0cmV0Y2goKQogICAgICAgIGJ0bl9yb3cgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbiA9IF9nb3RoaWNfYnRuKCLinKYgQkVHSU4gQVdBS0VOSU5H"
    "IikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3Ro"
    "aWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLmNsaWNrZWQuY29ubmVjdChzZWxmLmFjY2Vw"
    "dCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdp"
    "ZGdldChzZWxmLl9idG5fYXdha2VuKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICBkZWYgX29uX3R5cGVfY2hhbmdlKHNlbGYsIGlkeDogaW50KSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFi"
    "bGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiIikKCiAgICBkZWYgX2Jyb3dzZV9tb2RlbChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGggPSBRRmlsZURpYWxvZy5nZXRFeGlzdGluZ0RpcmVjdG9yeSgKICAgICAgICAg"
    "ICAgc2VsZiwgIlNlbGVjdCBNb2RlbCBGb2xkZXIiLAogICAgICAgICAgICByIkQ6XEFJXE1vZGVscyIKICAgICAgICApCiAg"
    "ICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAgZGVmIF9icm93"
    "c2VfZmFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIF8gPSBRRmlsZURpYWxvZy5nZXRPcGVuRmlsZU5hbWUoCiAg"
    "ICAgICAgICAgIHNlbGYsICJTZWxlY3QgRmFjZSBQYWNrIFpJUCIsCiAgICAgICAgICAgIHN0cihQYXRoLmhvbWUoKSAvICJE"
    "ZXNrdG9wIiksCiAgICAgICAgICAgICJaSVAgRmlsZXMgKCouemlwKSIKICAgICAgICApCiAgICAgICAgaWYgcGF0aDoKICAg"
    "ICAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFRleHQocGF0aCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBmYWNlX3ppcF9w"
    "YXRoKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fZmFjZV9wYXRoLnRleHQoKS5zdHJpcCgpCgogICAgZGVm"
    "IF90ZXN0X2Nvbm5lY3Rpb24oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQoIlRlc3Rp"
    "bmcuLi4iKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "VEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBRQXBwbGljYXRpb24ucHJvY2Vzc0V2ZW50cygpCgogICAgICAgIGlkeCA9IHNlbGYuX3R5cGVfY29tYm8uY3Vy"
    "cmVudEluZGV4KCkKICAgICAgICBvayAgPSBGYWxzZQogICAgICAgIG1zZyA9ICIiCgogICAgICAgIGlmIGlkeCA9PSAwOiAg"
    "IyBMb2NhbAogICAgICAgICAgICBwYXRoID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBp"
    "ZiBwYXRoIGFuZCBQYXRoKHBhdGgpLmV4aXN0cygpOgogICAgICAgICAgICAgICAgb2sgID0gVHJ1ZQogICAgICAgICAgICAg"
    "ICAgbXNnID0gZiJGb2xkZXIgZm91bmQuIE1vZGVsIHdpbGwgbG9hZCBvbiBzdGFydHVwLiIKICAgICAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgICAgIG1zZyA9ICJGb2xkZXIgbm90IGZvdW5kLiBDaGVjayB0aGUgcGF0aC4iCgogICAgICAgIGVsaWYg"
    "aWR4ID09IDE6ICAjIE9sbGFtYQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVl"
    "c3QuUmVxdWVzdCgKICAgICAgICAgICAgICAgICAgICAiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0z"
    "KQogICAgICAgICAgICAgICAgb2sgICA9IHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgICAgICAgICAgbXNnICA9ICJPbGxh"
    "bWEgaXMgcnVubmluZyDinJMiIGlmIG9rIGVsc2UgIk9sbGFtYSBub3QgcmVzcG9uZGluZy4iCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIG1zZyA9IGYiT2xsYW1hIG5vdCByZWFjaGFibGU6IHtlfSIKCiAg"
    "ICAgICAgZWxpZiBpZHggPT0gMjogICMgQ2xhdWRlCiAgICAgICAgICAgIGtleSA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgp"
    "LnN0cmlwKCkKICAgICAgICAgICAgb2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay1hbnQiKSkKICAgICAg"
    "ICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRlciBhIHZhbGlkIENs"
    "YXVkZSBBUEkga2V5LiIKCiAgICAgICAgZWxpZiBpZHggPT0gMzogICMgT3BlbkFJCiAgICAgICAgICAgIGtleSA9IHNlbGYu"
    "X29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgb2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJz"
    "ay0iKSkKICAgICAgICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRl"
    "ciBhIHZhbGlkIE9wZW5BSSBBUEkga2V5LiIKCiAgICAgICAgY29sb3IgPSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19DUklNU09O"
    "CiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KG1zZykKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChvaykKCiAgICBk"
    "ZWYgYnVpbGRfY29uZmlnKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgIiIiQnVpbGQgYW5kIHJldHVybiB1cGRhdGVkIGNvbmZp"
    "ZyBkaWN0IGZyb20gZGlhbG9nIHNlbGVjdGlvbnMuIiIiCiAgICAgICAgY2ZnICAgICA9IF9kZWZhdWx0X2NvbmZpZygpCiAg"
    "ICAgICAgaWR4ICAgICA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICB0eXBlcyAgID0gWyJsb2Nh"
    "bCIsICJvbGxhbWEiLCAiY2xhdWRlIiwgIm9wZW5haSJdCiAgICAgICAgY2ZnWyJtb2RlbCJdWyJ0eXBlIl0gPSB0eXBlc1tp"
    "ZHhdCgogICAgICAgIGlmIGlkeCA9PSAwOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bInBhdGgiXSA9IHNlbGYuX2xvY2Fs"
    "X3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbGlmIGlkeCA9PSAxOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bIm9s"
    "bGFtYV9tb2RlbCJdID0gc2VsZi5fb2xsYW1hX21vZGVsLnRleHQoKS5zdHJpcCgpIG9yICJkb2xwaGluLTIuNi03YiIKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAyOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5fY2xhdWRl"
    "X2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5fY2xhdWRl"
    "X21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAiY2xhdWRlIgog"
    "ICAgICAgIGVsaWYgaWR4ID09IDM6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9vYWlf"
    "a2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9vYWlfbW9k"
    "ZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJvcGVuYWkiCgogICAg"
    "ICAgIGNmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQogICAgICAgIHJldHVybiBjZmcKCiAgICBAcHJvcGVydHkKICAgIGRlZiBj"
    "cmVhdGVfc2hvcnRjdXQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fc2hvcnRjdXRfY2IuaXNDaGVja2Vk"
    "KCkKCgojIOKUgOKUgCBKT1VSTkFMIFNJREVCQVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpv"
    "dXJuYWxTaWRlYmFyKFFXaWRnZXQpOgogICAgIiIiCiAgICBDb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgbmV4dCB0byB0aGUg"
    "cGVyc29uYSBjaGF0IHRhYi4KICAgIFRvcDogc2Vzc2lvbiBjb250cm9scyAoY3VycmVudCBzZXNzaW9uIG5hbWUsIHNhdmUv"
    "bG9hZCBidXR0b25zLAogICAgICAgICBhdXRvc2F2ZSBpbmRpY2F0b3IpLgogICAgQm9keTogc2Nyb2xsYWJsZSBzZXNzaW9u"
    "IGxpc3Qg4oCUIGRhdGUsIEFJIG5hbWUsIG1lc3NhZ2UgY291bnQuCiAgICBDb2xsYXBzZXMgbGVmdHdhcmQgdG8gYSB0aGlu"
    "IHN0cmlwLgoKICAgIFNpZ25hbHM6CiAgICAgICAgc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZChzdHIpICAg4oCUIGRhdGUgc3Ry"
    "aW5nIG9mIHNlc3Npb24gdG8gbG9hZAogICAgICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkKCkgICAgIOKAlCByZXR1cm4g"
    "dG8gY3VycmVudCBzZXNzaW9uCiAgICAiIiIKCiAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkICA9IFNpZ25hbChzdHIpCiAg"
    "ICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCA9IFNpZ25hbCgpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNlc3Npb25fbWdy"
    "OiAiU2Vzc2lvbk1hbmFnZXIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9tZ3IgPSBzZXNzaW9uX21ncgogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgID0gVHJ1ZQogICAg"
    "ICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAjIFVzZSBhIGhvcml6b250YWwgcm9vdCBsYXlvdXQg4oCUIGNvbnRlbnQgb24gbGVmdCwgdG9nZ2xl"
    "IHN0cmlwIG9uIHJpZ2h0CiAgICAgICAgcm9vdCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50"
    "c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyDilIDilIAgQ29sbGFw"
    "c2UgdG9nZ2xlIHN0cmlwIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X3RvZ2dsZV9zdHJpcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcC5zZXRGaXhlZFdpZHRoKDIwKQog"
    "ICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGJvcmRlci1yaWdodDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHRzX2xheW91"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKICAgICAgICB0c19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDgsIDAsIDgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dn"
    "bGVfYnRuLnNldEZpeGVkU2l6ZSgxOCwgMTgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiKQogICAg"
    "ICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVu"
    "dDsgY29sb3I6IHtDX0dPTERfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQogICAgICAg"
    "IHRzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX2J0bikKICAgICAgICB0c19sYXlvdXQuYWRkU3RyZXRjaCgpCgog"
    "ICAgICAgICMg4pSA4pSAIE1haW4gY29udGVudCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9jb250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fY29udGVudC5zZXRNaW5pbXVtV2lkdGgoMTgwKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWF4aW11bVdpZHRoKDIy"
    "MCkKICAgICAgICBjb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgY29udGVudF9s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg0"
    "KQoKICAgICAgICAjIFNlY3Rpb24gbGFiZWwKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgSk9VUk5BTCIpKQoKICAgICAgICAjIEN1cnJlbnQgc2Vzc2lvbiBpbmZvCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9u"
    "YW1lID0gUUxhYmVsKCJOZXcgU2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX25hbWUuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vzc2lv"
    "bl9uYW1lKQoKICAgICAgICAjIFNhdmUgLyBMb2FkIHJvdwogICAgICAgIGN0cmxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuX2J0bl9zYXZlID0gX2dvdGhpY19idG4oIvCfkr4iKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldEZpeGVk"
    "U2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VG9vbFRpcCgiU2F2ZSBzZXNzaW9uIG5vdyIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2xvYWQgPSBfZ290aGljX2J0bigi8J+TgiIpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0Rml4ZWRT"
    "aXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRUb29sVGlwKCJCcm93c2UgYW5kIGxvYWQgYSBwYXN0IHNl"
    "c3Npb24iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdCA9IFFMYWJlbCgi4pePIikKICAgICAgICBzZWxmLl9hdXRvc2F2"
    "ZV9kb3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDhweDsg"
    "Ym9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoIkF1dG9zYXZl"
    "IHN0YXR1cyIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3NhdmUpCiAgICAgICAg"
    "c2VsZi5fYnRuX2xvYWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYuX2J0bl9zYXZlKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fbG9hZCkKICAgICAgICBjdHJs"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYXV0b3NhdmVfZG90KQogICAgICAgIGN0cmxfcm93LmFkZFN0cmV0Y2goKQogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0LmFkZExheW91dChjdHJsX3JvdykKCiAgICAgICAgIyBKb3VybmFsIGxvYWRlZCBpbmRpY2F0b3IK"
    "ICAgICAgICBzZWxmLl9qb3VybmFsX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19QVVJQTEV9OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2pvdXJuYWxfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2pvdXJuYWxfbGJsKQoKICAgICAgICAjIENsZWFyIGpvdXJuYWwgYnV0dG9uIChoaWRkZW4gd2hlbiBub3QgbG9hZGVk"
    "KQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsID0gX2dvdGhpY19idG4oIuKclyBSZXR1cm4gdG8gUHJlc2VudCIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fY2xl"
    "YXJfam91cm5hbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fY2xlYXJfam91cm5hbCkKICAgICAgICBjb250ZW50X2xheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwpCgogICAgICAgICMgRGl2aWRlcgogICAgICAgIGRpdiA9IFFG"
    "cmFtZSgpCiAgICAgICAgZGl2LnNldEZyYW1lU2hhcGUoUUZyYW1lLlNoYXBlLkhMaW5lKQogICAgICAgIGRpdi5zZXRTdHls"
    "ZVNoZWV0KGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChkaXYp"
    "CgogICAgICAgICMgU2Vzc2lvbiBsaXN0CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIFBBU1QgU0VTU0lPTlMiKSkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbl9saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29s"
    "b3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgICAgIGYiUUxp"
    "c3RXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyB9fSIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGlj"
    "aykKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNr"
    "KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX2xpc3QsIDEpCgogICAgICAgICMgQWRk"
    "IGNvbnRlbnQgYW5kIHRvZ2dsZSBzdHJpcCB0byB0aGUgcm9vdCBob3Jpem9udGFsIGxheW91dAogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQoKICAgIGRl"
    "ZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAg"
    "ICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5z"
    "ZXRUZXh0KCLil4AiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIuKWtiIpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgp"
    "CiAgICAgICAgcCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwIGFuZCBwLmxheW91dCgpOgogICAgICAgICAg"
    "ICBwLmxheW91dCgpLmFjdGl2YXRlKCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlc3Npb25z"
    "ID0gc2VsZi5fc2Vzc2lvbl9tZ3IubGlzdF9zZXNzaW9ucygpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmNsZWFyKCkK"
    "ICAgICAgICBmb3IgcyBpbiBzZXNzaW9uczoKICAgICAgICAgICAgZGF0ZV9zdHIgPSBzLmdldCgiZGF0ZSIsIiIpCiAgICAg"
    "ICAgICAgIG5hbWUgICAgID0gcy5nZXQoIm5hbWUiLCBkYXRlX3N0cilbOjMwXQogICAgICAgICAgICBjb3VudCAgICA9IHMu"
    "Z2V0KCJtZXNzYWdlX2NvdW50IiwgMCkKICAgICAgICAgICAgaXRlbSA9IFFMaXN0V2lkZ2V0SXRlbShmIntkYXRlX3N0cn1c"
    "bntuYW1lfSAoe2NvdW50fSBtc2dzKSIpCiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJv"
    "bGUsIGRhdGVfc3RyKQogICAgICAgICAgICBpdGVtLnNldFRvb2xUaXAoZiJEb3VibGUtY2xpY2sgdG8gbG9hZCBzZXNzaW9u"
    "IGZyb20ge2RhdGVfc3RyfSIpCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5hZGRJdGVtKGl0ZW0pCgogICAgZGVm"
    "IHNldF9zZXNzaW9uX25hbWUoc2VsZiwgbmFtZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5z"
    "ZXRUZXh0KG5hbWVbOjUwXSBvciAiTmV3IFNlc3Npb24iKQoKICAgIGRlZiBzZXRfYXV0b3NhdmVfaW5kaWNhdG9yKHNlbGYs"
    "IHNhdmVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19HUkVFTiBpZiBzYXZlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlw"
    "KAogICAgICAgICAgICAiQXV0b3NhdmVkIiBpZiBzYXZlZCBlbHNlICJQZW5kaW5nIGF1dG9zYXZlIgogICAgICAgICkKCiAg"
    "ICBkZWYgc2V0X2pvdXJuYWxfbG9hZGVkKHNlbGYsIGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91"
    "cm5hbF9sYmwuc2V0VGV4dChmIvCfk5YgSm91cm5hbDoge2RhdGVfc3RyfSIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pv"
    "dXJuYWwuc2V0VmlzaWJsZShUcnVlKQoKICAgIGRlZiBjbGVhcl9qb3VybmFsX2luZGljYXRvcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0"
    "VmlzaWJsZShGYWxzZSkKCiAgICBkZWYgX2RvX3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX21n"
    "ci5zYXZlKCkKICAgICAgICBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIuKckyIpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMCwg"
    "bGFtYmRhOiBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLwn5K+IikpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwMCwg"
    "bGFtYmRhOiBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpKQoKICAgIGRlZiBfZG9fbG9hZChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICMgVHJ5IHNlbGVjdGVkIGl0ZW0gZmlyc3QKICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0"
    "LmN1cnJlbnRJdGVtKCkKICAgICAgICBpZiBub3QgaXRlbToKICAgICAgICAgICAgIyBJZiBub3RoaW5nIHNlbGVjdGVkLCB0"
    "cnkgdGhlIGZpcnN0IGl0ZW0KICAgICAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbl9saXN0LmNvdW50KCkgPiAwOgogICAgICAg"
    "ICAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtKDApCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9u"
    "X2xpc3Quc2V0Q3VycmVudEl0ZW0oaXRlbSkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBkYXRlX3N0ciA9IGl0ZW0u"
    "ZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5l"
    "bWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfb25fc2Vzc2lvbl9jbGljayhzZWxmLCBpdGVtKSAtPiBOb25lOgogICAgICAgIGRh"
    "dGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9y"
    "ZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYgX2RvX2NsZWFyX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmVtaXQoKQogICAgICAgIHNlbGYuY2xlYXJfam91cm5hbF9pbmRpY2F0"
    "b3IoKQoKCiMg4pSA4pSAIFRPUlBPUiBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgVG9ycG9yUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRocmVlLXN0YXRlIHN1c3BlbnNpb24gdG9nZ2xlOiBB"
    "V0FLRSB8IEFVVE8gfCBTVVNQRU5ECgogICAgQVdBS0UgIOKAlCBtb2RlbCBsb2FkZWQsIGF1dG8tdG9ycG9yIGRpc2FibGVk"
    "LCBpZ25vcmVzIFZSQU0gcHJlc3N1cmUKICAgIEFVVE8gICDigJQgbW9kZWwgbG9hZGVkLCBtb25pdG9ycyBWUkFNIHByZXNz"
    "dXJlLCBhdXRvLXRvcnBvciBpZiBzdXN0YWluZWQKICAgIFNVU1BFTkQg4oCUIG1vZGVsIHVubG9hZGVkLCBzdGF5cyBzdXNw"
    "ZW5kZWQgdW50aWwgbWFudWFsbHkgY2hhbmdlZAoKICAgIFNpZ25hbHM6CiAgICAgICAgc3RhdGVfY2hhbmdlZChzdHIpICDi"
    "gJQgIkFXQUtFIiB8ICJBVVRPIiB8ICJTVVNQRU5EIgogICAgIiIiCgogICAgc3RhdGVfY2hhbmdlZCA9IFNpZ25hbChzdHIp"
    "CgogICAgU1RBVEVTID0gWyJBV0FLRSIsICJBVVRPIiwgIlNVU1BFTkQiXQoKICAgIFNUQVRFX1NUWUxFUyA9IHsKICAgICAg"
    "ICAiQVdBS0UiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzJhMWEwNTsgY29sb3I6IHtDX0dP"
    "TER9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07IGJvcmRlci1yYWRp"
    "dXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsg"
    "cGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9y"
    "OiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9"
    "OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjogICAgIuKYgCBBV0FLRSIsCiAg"
    "ICAgICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3RpdmUuIEF1dG8tdG9ycG9yIGRpc2FibGVkLiIsCiAgICAgICAgfSwK"
    "ICAgICAgICAiQVVUTyI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMWExMDA1OyBjb2xvcjog"
    "I2NjODgyMjsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkICNjYzg4MjI7IGJvcmRlci1y"
    "YWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9s"
    "ZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNv"
    "bG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjogICAgIuKXiSBBVVRPIiwK"
    "ICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by1zdXNwZW5kIG9uIFZSQU0gcHJlc3N1cmUuIiwK"
    "ICAgICAgICB9LAogICAgICAgICJTVVNQRU5EIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6IHtD"
    "X1BVUlBMRV9ESU19OyBjb2xvcjoge0NfUFVSUExFfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX1BVUlBMRX07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUi"
    "OiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAg"
    "ICAgImxhYmVsIjogICAgZiLimrAge1VJX1NVU1BFTlNJT05fTEFCRUwuc3RyaXAoKSBpZiBzdHIoVUlfU1VTUEVOU0lPTl9M"
    "QUJFTCkuc3RyaXAoKSBlbHNlICdTdXNwZW5kJ30iLAogICAgICAgICAgICAidG9vbHRpcCI6ICBmIk1vZGVsIHVubG9hZGVk"
    "LiB7REVDS19OQU1FfSBzbGVlcHMgdW50aWwgbWFudWFsbHkgYXdha2VuZWQuIiwKICAgICAgICB9LAogICAgfQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fY3VycmVudCA9ICJBV0FLRSIKICAgICAgICBzZWxmLl9idXR0b25zOiBkaWN0W3N0ciwgUVB1c2hCdXR0b25dID0g"
    "e30KICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBmb3Igc3RhdGUgaW4gc2VsZi5TVEFU"
    "RVM6CiAgICAgICAgICAgIGJ0biA9IFFQdXNoQnV0dG9uKHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsibGFiZWwiXSkKICAg"
    "ICAgICAgICAgYnRuLnNldFRvb2xUaXAoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJ0b29sdGlwIl0pCiAgICAgICAgICAg"
    "IGJ0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICAgICAgYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgY2hlY2tlZCwg"
    "cz1zdGF0ZTogc2VsZi5fc2V0X3N0YXRlKHMpKQogICAgICAgICAgICBzZWxmLl9idXR0b25zW3N0YXRlXSA9IGJ0bgogICAg"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJ0bikKCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKCiAgICBkZWYgX3Nl"
    "dF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQ6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJlbnQgPSBzdGF0ZQogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxl"
    "cygpCiAgICAgICAgc2VsZi5zdGF0ZV9jaGFuZ2VkLmVtaXQoc3RhdGUpCgogICAgZGVmIF9hcHBseV9zdHlsZXMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBmb3Igc3RhdGUsIGJ0biBpbiBzZWxmLl9idXR0b25zLml0ZW1zKCk6CiAgICAgICAgICAgIHN0"
    "eWxlX2tleSA9ICJhY3RpdmUiIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQgZWxzZSAiaW5hY3RpdmUiCiAgICAgICAgICAg"
    "IGJ0bi5zZXRTdHlsZVNoZWV0KHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVtzdHlsZV9rZXldKQoKICAgIEBwcm9wZXJ0eQog"
    "ICAgZGVmIGN1cnJlbnRfc3RhdGUoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9jdXJyZW50CgogICAgZGVm"
    "IHNldF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBzdGF0ZSBwcm9ncmFtbWF0aWNh"
    "bGx5IChlLmcuIGZyb20gYXV0by10b3Jwb3IgZGV0ZWN0aW9uKS4iIiIKICAgICAgICBpZiBzdGF0ZSBpbiBzZWxmLlNUQVRF"
    "UzoKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXRlKHN0YXRlKQoKCiMg4pSA4pSAIE1BSU4gV0lORE9XIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFY2hvRGVjayhRTWFpbldpbmRvdyk6CiAgICAiIiIK"
    "ICAgIFRoZSBtYWluIEVjaG8gRGVjayB3aW5kb3cuCiAgICBBc3NlbWJsZXMgYWxsIHdpZGdldHMsIGNvbm5lY3RzIGFsbCBz"
    "aWduYWxzLCBtYW5hZ2VzIGFsbCBzdGF0ZS4KICAgICIiIgoKICAgICMg4pSA4pSAIFRvcnBvciB0aHJlc2hvbGRzIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0VYVEVS"
    "TkFMX1ZSQU1fVE9SUE9SX0dCICAgID0gMS41ICAgIyBleHRlcm5hbCBWUkFNID4gdGhpcyDihpIgY29uc2lkZXIgdG9ycG9y"
    "CiAgICBfRVhURVJOQUxfVlJBTV9XQUtFX0dCICAgICAgPSAwLjggICAjIGV4dGVybmFsIFZSQU0gPCB0aGlzIOKGkiBjb25z"
    "aWRlciB3YWtlCiAgICBfVE9SUE9SX1NVU1RBSU5FRF9USUNLUyAgICAgPSA2ICAgICAjIDYgw5cgNXMgPSAzMCBzZWNvbmRz"
    "IHN1c3RhaW5lZAogICAgX1dBS0VfU1VTVEFJTkVEX1RJQ0tTICAgICAgID0gMTIgICAgIyA2MCBzZWNvbmRzIHN1c3RhaW5l"
    "ZCBsb3cgcHJlc3N1cmUKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCgogICAg"
    "ICAgICMg4pSA4pSAIENvcmUgc3RhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHVzICAgICAgICAgICAgICA9ICJPRkZMSU5F"
    "IgogICAgICAgIHNlbGYuX3Nlc3Npb25fc3RhcnQgICAgICAgPSB0aW1lLnRpbWUoKQogICAgICAgIHNlbGYuX3Rva2VuX2Nv"
    "dW50ICAgICAgICAgPSAwCiAgICAgICAgc2VsZi5fZmFjZV9sb2NrZWQgICAgICAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5f"
    "Ymxpbmtfc3RhdGUgICAgICAgICA9IFRydWUKICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgICAgICAgID0gRmFsc2UKICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX2lkICAgICAgICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVkl"
    "bSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkczogbGlzdCA9IFtdICAjIGtlZXAgcmVmcyB0byBw"
    "cmV2ZW50IEdDIHdoaWxlIHJ1bm5pbmcKICAgICAgICBzZWxmLl9maXJzdF90b2tlbjogYm9vbCA9IFRydWUgICAjIHdyaXRl"
    "IHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHN0cmVhbWluZyB0b2tlbgoKICAgICAgICAjIFRvcnBvciAvIFZSQU0gdHJh"
    "Y2tpbmcKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgICAgICAgID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2RlY2tfdnJh"
    "bV9iYXNlICA9IDAuMCAgICMgYmFzZWxpbmUgVlJBTSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA9IDAgICAgICMgc3VzdGFpbmVkIHByZXNzdXJlIGNvdW50ZXIKICAgICAgICBzZWxmLl92cmFtX3JlbGll"
    "Zl90aWNrcyAgID0gMCAgICAgIyBzdXN0YWluZWQgcmVsaWVmIGNvdW50ZXIKICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5z"
    "bWlzc2lvbnMgPSAwCiAgICAgICAgc2VsZi5fdG9ycG9yX3NpbmNlICAgICAgICA9IE5vbmUgICMgZGF0ZXRpbWUgd2hlbiB0"
    "b3Jwb3IgYmVnYW4KICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gID0gIiIgICAjIGZvcm1hdHRlZCBkdXJhdGlv"
    "biBzdHJpbmcKCiAgICAgICAgIyDilIDilIAgTWFuYWdlcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbWVtb3J5ICAgPSBN"
    "ZW1vcnlNYW5hZ2VyKCkKICAgICAgICBzZWxmLl9zZXNzaW9ucyA9IFNlc3Npb25NYW5hZ2VyKCkKICAgICAgICBzZWxmLl9s"
    "ZXNzb25zICA9IExlc3NvbnNMZWFybmVkREIoKQogICAgICAgIHNlbGYuX3Rhc2tzICAgID0gVGFza01hbmFnZXIoKQogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfY2FjaGU6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6"
    "ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxm"
    "Ll9nb29nbGVfYXV0aF9yZWFkeSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXI6IE9wdGlvbmFs"
    "W1FUaW1lcl0gPSBOb25lCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcjogT3B0aW9uYWxbUVRp"
    "bWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgc2VsZi5fdGFza3NfdGFi"
    "X2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBzZWxmLl90YXNr"
    "X2RhdGVfZmlsdGVyID0gIm5leHRfM19tb250aHMiCgogICAgICAgICMg4pSA4pSAIEdvb2dsZSBTZXJ2aWNlcyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIEluc3RhbnRp"
    "YXRlIHNlcnZpY2Ugd3JhcHBlcnMgdXAtZnJvbnQ7IGF1dGggaXMgZm9yY2VkIGxhdGVyCiAgICAgICAgIyBmcm9tIG1haW4o"
    "KSBhZnRlciB3aW5kb3cuc2hvdygpIHdoZW4gdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBnX2NyZWRzX3Bh"
    "dGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJjcmVkZW50aWFscyIsCiAgICAgICAg"
    "ICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKQogICAgICAgICkpCiAgICAg"
    "ICAgZ190b2tlbl9wYXRoID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAidG9rZW4iLAog"
    "ICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iKQogICAgICAgICkpCiAgICAgICAgc2Vs"
    "Zi5fZ2NhbCA9IEdvb2dsZUNhbGVuZGFyU2VydmljZShnX2NyZWRzX3BhdGgsIGdfdG9rZW5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll9nZHJpdmUgPSBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlKAogICAgICAgICAgICBnX2NyZWRzX3BhdGgsCiAgICAgICAgICAg"
    "IGdfdG9rZW5fcGF0aCwKICAgICAgICAgICAgbG9nZ2VyPWxhbWJkYSBtc2csIGxldmVsPSJJTkZPIjogc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW0dEUklWRV0ge21zZ30iLCBsZXZlbCkKICAgICAgICApCgogICAgICAgICMgU2VlZCBMU0wgcnVsZXMgb24g"
    "Zmlyc3QgcnVuCiAgICAgICAgc2VsZi5fbGVzc29ucy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAgICMgTG9hZCBlbnRpdHkg"
    "c3RhdGUKICAgICAgICBzZWxmLl9zdGF0ZSA9IHNlbGYuX21lbW9yeS5sb2FkX3N0YXRlKCkKICAgICAgICBzZWxmLl9zdGF0"
    "ZVsic2Vzc2lvbl9jb3VudCJdID0gc2VsZi5fc3RhdGUuZ2V0KCJzZXNzaW9uX2NvdW50IiwwKSArIDEKICAgICAgICBzZWxm"
    "Ll9zdGF0ZVsibGFzdF9zdGFydHVwIl0gID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3Rh"
    "dGUoc2VsZi5fc3RhdGUpCgogICAgICAgICMgQnVpbGQgYWRhcHRvcgogICAgICAgIHNlbGYuX2FkYXB0b3IgPSBidWlsZF9h"
    "ZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgKHNldCB1cCBhZnRlciB3aWRnZXRz"
    "IGJ1aWx0KQogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyOiBPcHRpb25hbFtGYWNlVGltZXJNYW5hZ2VyXSA9IE5vbmUK"
    "CiAgICAgICAgIyDilIDilIAgQnVpbGQgVUkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShBUFBfTkFN"
    "RSkKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEyMDAsIDc1MCkKICAgICAgICBzZWxmLnJlc2l6ZSgxMzUwLCA4NTAp"
    "CiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgogICAgICAgICMg"
    "RmFjZSB0aW1lciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nciA9IEZhY2VU"
    "aW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNlbGYuX21pcnJvciwgc2VsZi5fZW1vdGlvbl9ibG9jawogICAgICAgICkKCiAg"
    "ICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyID0gUVRpbWVy"
    "KCkKICAgICAgICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRlX3N0YXRzKQogICAgICAg"
    "IHNlbGYuX3N0YXRzX3RpbWVyLnN0YXJ0KDEwMDApCgogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyID0gUVRpbWVyKCkKICAg"
    "ICAgICBzZWxmLl9ibGlua190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fYmxpbmspCiAgICAgICAgc2VsZi5fYmxpbmtf"
    "dGltZXIuc3RhcnQoODAwKQoKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1lcigpCiAgICAgICAgaWYg"
    "QUlfU1RBVEVTX0VOQUJMRUQgYW5kIHNlbGYuX2Zvb3Rlcl9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5f"
    "c3RhdGVfc3RyaXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2Zvb3Rlcl9zdHJpcC5yZWZyZXNoKQogICAgICAgICAg"
    "ICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGlt"
    "ZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2Vs"
    "Zi5fb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljaykKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci5zdGFy"
    "dCg2MDAwMCkKCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lciA9IFFUaW1lcihzZWxmKQogICAg"
    "ICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9y"
    "ZWNvcmRzX3JlZnJlc2hfdGltZXJfdGljaykKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnN0"
    "YXJ0KDYwMDAwKQoKICAgICAgICAjIOKUgOKUgCBTY2hlZHVsZXIgYW5kIHN0YXJ0dXAgZGVmZXJyZWQgdW50aWwgYWZ0ZXIg"
    "d2luZG93LnNob3coKSDilIDilIDilIAKICAgICAgICAjIERvIE5PVCBjYWxsIF9zZXR1cF9zY2hlZHVsZXIoKSBvciBfc3Rh"
    "cnR1cF9zZXF1ZW5jZSgpIGhlcmUuCiAgICAgICAgIyBCb3RoIGFyZSB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90"
    "IGZyb20gbWFpbigpIGFmdGVyCiAgICAgICAgIyB3aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucyBydW5uaW5n"
    "LgoKICAgICMg4pSA4pSAIFVJIENPTlNUUlVDVElPTiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRf"
    "dWkoc2VsZikgLT4gTm9uZToKICAgICAgICBjZW50cmFsID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5zZXRDZW50cmFsV2lk"
    "Z2V0KGNlbnRyYWwpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KGNlbnRyYWwpCiAgICAgICAgcm9vdC5zZXRDb250ZW50"
    "c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyDilIDilIAgVGl0bGUg"
    "YmFyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2J1aWxkX3RpdGxlX2JhcigpKQoKICAgICAgICAjIOKU"
    "gOKUgCBCb2R5OiBKb3VybmFsIHwgQ2hhdCB8IFN5c3RlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgYm9keSA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBib2R5LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBKb3VybmFsIHNpZGViYXIgKGxlZnQpCiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyID0gSm91cm5hbFNpZGViYXIoc2VsZi5fc2Vzc2lvbnMpCiAgICAgICAgc2Vs"
    "Zi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fbG9h"
    "ZF9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVk"
    "LmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBib2R5LmFkZFdpZGdl"
    "dChzZWxmLl9qb3VybmFsX3NpZGViYXIpCgogICAgICAgICMgQ2hhdCBwYW5lbCAoY2VudGVyLCBleHBhbmRzKQogICAgICAg"
    "IGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX2NoYXRfcGFuZWwoKSwgMSkKCiAgICAgICAgIyBTeXN0ZW1zIChyaWdodCkK"
    "ICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9zcGVsbGJvb2tfcGFuZWwoKSkKCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoYm9keSwgMSkKCiAgICAgICAgIyDilIDilIAgRm9vdGVyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZvb3RlciA9"
    "IFFMYWJlbCgKICAgICAgICAgICAgZiLinKYge0FQUF9OQU1FfSDigJQgdntBUFBfVkVSU0lPTn0g4pymIgogICAgICAgICkK"
    "ICAgICAgICBmb290ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNp"
    "emU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKICAgICAgICBmb290ZXIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50"
    "ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoZm9vdGVyKQoKICAgIGRlZiBfYnVpbGRfdGl0bGVfYmFyKHNlbGYpIC0+IFFX"
    "aWRnZXQ6CiAgICAgICAgYmFyID0gUVdpZGdldCgpCiAgICAgICAgYmFyLnNldEZpeGVkSGVpZ2h0KDM2KQogICAgICAgIGJh"
    "ci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxh"
    "eW91dCA9IFFIQm94TGF5b3V0KGJhcikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDEwLCAwLCAxMCwgMCkK"
    "ICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg2KQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7QVBQX05BTUV9IikK"
    "ICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXpl"
    "OiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImxldHRlci1zcGFjaW5nOiAycHg7IGJvcmRlcjog"
    "bm9uZTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBydW5lcyA9IFFMYWJl"
    "bChSVU5FUykKICAgICAgICBydW5lcy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07"
    "IGZvbnQtc2l6ZTogMTBweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcnVuZXMuc2V0QWxpZ25tZW50KFF0"
    "LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKGYi4peJIHtV"
    "SV9PRkZMSU5FX1NUQVRVU30iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0JMT09EfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25S"
    "aWdodCkKCiAgICAgICAgIyBTdXNwZW5zaW9uIHBhbmVsCiAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gTm9uZQogICAg"
    "ICAgIGlmIFNVU1BFTlNJT05fRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gVG9ycG9yUGFuZWwo"
    "KQogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwuc3RhdGVfY2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3RvcnBvcl9z"
    "dGF0ZV9jaGFuZ2VkKQoKICAgICAgICAjIElkbGUgdG9nZ2xlCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRv"
    "bigiSURMRSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2lk"
    "bGVfYnRuLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrZWQoRmFsc2UpCiAgICAg"
    "ICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xv"
    "cjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJh"
    "ZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAz"
    "cHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVf"
    "dG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJMIGJ1dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigi"
    "RlMiKQogICAgICAgIHNlbGYuX2JsX2J0biA9IFFQdXNoQnV0dG9uKCJCTCIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0biA9"
    "IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0biA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93"
    "biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgog"
    "ICAgICAgICAgICBidG4uc2V0Rml4ZWRTaXplKDMwLCAyMikKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAg"
    "ICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBzZWxmLl9leHBvcnRf"
    "YnRuLnNldEZpeGVkV2lkdGgoNDYpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAg"
    "ICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZFdpZHRoKDY4KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19CTE9PRH07ICIKICAgICAg"
    "ICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CTE9PRH07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICkKICAgICAgICBzZWxmLl9mc19idG4uc2V0VG9vbFRpcCgi"
    "RnVsbHNjcmVlbiAoRjExKSIpCiAgICAgICAgc2VsZi5fYmxfYnRuLnNldFRvb2xUaXAoIkJvcmRlcmxlc3MgKEYxMCkiKQog"
    "ICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0VG9vbFRpcCgiRXhwb3J0IGNoYXQgc2Vzc2lvbiB0byBUWFQgZmlsZSIpCiAg"
    "ICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFRvb2xUaXAoZiJHcmFjZWZ1bCBzaHV0ZG93biDigJQge0RFQ0tfTkFNRX0g"
    "c3BlYWtzIHRoZWlyIGxhc3Qgd29yZHMiKQogICAgICAgIHNlbGYuX2ZzX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9n"
    "Z2xlX2Z1bGxzY3JlZW4pCiAgICAgICAgc2VsZi5fYmxfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfYm9yZGVy"
    "bGVzcykKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9leHBvcnRfY2hhdCkKICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZykKCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldCh0aXRsZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJ1bmVzLCAxKQogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoOCkKICAgICAg"
    "ICBpZiBzZWxmLl90b3Jwb3JfcGFuZWwgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "dG9ycG9yX3BhbmVsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9pZGxlX2J0bikKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "ZXhwb3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2ZzX2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2JsX2J0bikKCiAgICAgICAg"
    "cmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlv"
    "dXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRhYiB3aWRn"
    "ZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9S"
    "fTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhU"
    "X0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "IgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAg"
    "ICAgICAgICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xE"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoK"
    "ICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94TGF5b3V0"
    "KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAg"
    "ICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4dEVkaXQo"
    "KQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9sYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5jZV93aWRn"
    "ZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMTogU2VsZiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9zZWxmX3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3Nl"
    "bGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAg"
    "ICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAg"
    "ICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJf"
    "d2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkKCiAgICAg"
    "ICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRv"
    "cnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgRU1PVElPTlMg"
    "fCBMRUZUIE9SQiB8IENFTlRFUiBDWUNMRSB8IFJJR0hUIE9SQiB8IEVTU0VOQ0UKICAgICAgICBibG9ja19yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgYmxvY2tfcm93LnNldFNwYWNpbmcoMikKCiAgICAgICAgIyBNaXJyb3IgKG5ldmVyIGNvbGxh"
    "cHNlcykKICAgICAgICBtaXJyb3Jfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIG13X2xheW91dCA9IFFWQm94TGF5b3V0KG1p"
    "cnJvcl93cmFwKQogICAgICAgIG13X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtd19s"
    "YXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIG13X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIHtVSV9N"
    "SVJST1JfTEFCRUx9IikpCiAgICAgICAgc2VsZi5fbWlycm9yID0gTWlycm9yV2lkZ2V0KCkKICAgICAgICBzZWxmLl9taXJy"
    "b3Iuc2V0Rml4ZWRTaXplKDE2MCwgMTYwKQogICAgICAgIG13X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbWlycm9yKQogICAg"
    "ICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlycm9yX3dyYXApCgogICAgICAgICMgRW1vdGlvbiBibG9jayAoY29sbGFwc2li"
    "bGUpCiAgICAgICAgc2VsZi5fZW1vdGlvbl9ibG9jayA9IEVtb3Rpb25CbG9jaygpCiAgICAgICAgc2VsZi5fZW1vdGlvbl9i"
    "bG9ja193cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VNT1RJT05TX0xBQkVMfSIsIHNl"
    "bGYuX2Vtb3Rpb25fYmxvY2ssCiAgICAgICAgICAgIGV4cGFuZGVkPVRydWUsIG1pbl93aWR0aD0xMzAKICAgICAgICApCiAg"
    "ICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXApCgogICAgICAgICMgTGVmdCByZXNv"
    "dXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAg"
    "ICBVSV9MRUZUX09SQl9MQUJFTCwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAgICAgIGJsb2NrX3Jv"
    "dy5hZGRXaWRnZXQoCiAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soZiLinacge1VJX0xFRlRfT1JCX1RJVExFfSIsIHNl"
    "bGYuX2xlZnRfb3JiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1pbl93aWR0aD05MCkKICAgICAgICApCgogICAg"
    "ICAgICMgQ2VudGVyIGN5Y2xlIHdpZGdldCAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fY3ljbGVfd2lkZ2V0ID0gQ3lj"
    "bGVXaWRnZXQoKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soZiLi"
    "nacge1VJX0NZQ0xFX1RJVExFfSIsIHNlbGYuX2N5Y2xlX3dpZGdldCwgbWluX3dpZHRoPTkwKQogICAgICAgICkKCiAgICAg"
    "ICAgIyBSaWdodCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX3JpZ2h0X29yYiA9IFNwaGVyZVdp"
    "ZGdldCgKICAgICAgICAgICAgVUlfUklHSFRfT1JCX0xBQkVMLCBDX1BVUlBMRSwgQ19QVVJQTEVfRElNCiAgICAgICAgKQog"
    "ICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soZiLinacge1VJX1JJR0hU"
    "X09SQl9USVRMRX0iLCBzZWxmLl9yaWdodF9vcmIsIG1pbl93aWR0aD05MCkKICAgICAgICApCgogICAgICAgICMgRXNzZW5j"
    "ZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNz"
    "ZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2Vs"
    "Zi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAu"
    "MCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNT"
    "RU5DRV9TRUNPTkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5j"
    "ZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgQ29sbGFwc2libGVC"
    "bG9jayhmIuKdpyB7VUlfRVNTRU5DRV9USVRMRX0iLCBlc3NlbmNlX3dpZGdldCwgbWluX3dpZHRoPTExMCkKICAgICAgICAp"
    "CgogICAgICAgIGJsb2NrX3Jvdy5hZGRTdHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJsb2NrX3JvdykKCiAg"
    "ICAgICAgIyBGb290ZXIgc3RhdGUgc3RyaXAgKGJlbG93IGJsb2NrIHJvdyDigJQgcGVybWFuZW50IFVJIHN0cnVjdHVyZSkK"
    "ICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAgPSBGb290ZXJTdHJpcFdpZGdldCgpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0"
    "cmlwLnNldF9sYWJlbChVSV9GT09URVJfU1RSSVBfTEFCRUwpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9mb290"
    "ZXJfc3RyaXApCgogICAgICAgICMg4pSA4pSAIElucHV0IHJvdyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpbnB1dF9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgcHJvbXB0X3N5bSA9IFFMYWJlbCgi4pymIikKICAgICAgICBwcm9tcHRfc3ltLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE2cHg7IGZvbnQtd2VpZ2h0OiBib2xk"
    "OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBwcm9tcHRfc3ltLnNldEZpeGVkV2lkdGgoMjApCgogICAgICAg"
    "IHNlbGYuX2lucHV0X2ZpZWxkID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRQbGFjZWhvbGRl"
    "clRleHQoVUlfSU5QVVRfUExBQ0VIT0xERVIpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQucmV0dXJuUHJlc3NlZC5jb25u"
    "ZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0biA9IFFQdXNoQnV0dG9uKFVJX1NFTkRfQlVUVE9OKQogICAgICAgIHNlbGYuX3NlbmRfYnRu"
    "LnNldEZpeGVkV2lkdGgoMTEwKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZW5kX21l"
    "c3NhZ2UpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgaW5wdXRfcm93LmFkZFdp"
    "ZGdldChwcm9tcHRfc3ltKQogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5faW5wdXRfZmllbGQpCiAgICAgICAg"
    "aW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9zZW5kX2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGlucHV0X3JvdykK"
    "CiAgICAgICAgcmV0dXJuIGxheW91dAoKICAgIGRlZiBfYnVpbGRfc3BlbGxib29rX3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5"
    "b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIFNZU1RFTVMiKSkKCiAgICAgICAgIyBUYWIgd2lkZ2V0CiAgICAgICAgc2VsZi5fc3BlbGxfdGFicyA9IFFU"
    "YWJXaWRnZXQoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0TWluaW11bVdpZHRoKDI4MCkKICAgICAgICBzZWxmLl9z"
    "cGVsbF90YWJzLnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAg"
    "ICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcKICAgICAgICApCgogICAgICAgICMgQnVpbGQgRGlhZ25vc3Rp"
    "Y3NUYWIgZWFybHkgc28gc3RhcnR1cCBsb2dzIGFyZSBzYWZlIGV2ZW4gYmVmb3JlCiAgICAgICAgIyB0aGUgRGlhZ25vc3Rp"
    "Y3MgdGFiIGlzIGF0dGFjaGVkIHRvIHRoZSB3aWRnZXQuCiAgICAgICAgc2VsZi5fZGlhZ190YWIgPSBEaWFnbm9zdGljc1Rh"
    "YigpCgogICAgICAgICMg4pSA4pSAIEluc3RydW1lbnRzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9od19wYW5lbCA9IEhhcmR3YXJlUGFuZWwoKQogICAg"
    "ICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2h3X3BhbmVsLCAiSW5zdHJ1bWVudHMiKQoKICAgICAgICAjIOKU"
    "gOKUgCBSZWNvcmRzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIgPSBSZWNvcmRzVGFiKCkKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYl9pbmRl"
    "eCA9IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3JlY29yZHNfdGFiLCAiUmVjb3JkcyIpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFJlY29yZHNUYWIgYXR0YWNoZWQuIiwgIklORk8iKQoKICAgICAgICAj"
    "IOKUgOKUgCBUYXNrcyB0YWIgKHJlYWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX3Rhc2tzX3RhYiA9IFRhc2tzVGFiKAogICAgICAgICAgICB0YXNrc19wcm92aWRlcj1z"
    "ZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnksCiAgICAgICAgICAgIG9uX2FkZF9lZGl0b3Jfb3Blbj1zZWxmLl9v"
    "cGVuX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSwKICAgICAgICAgICAgb25fY29tcGxldGVfc2VsZWN0ZWQ9c2VsZi5fY29tcGxl"
    "dGVfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkPXNlbGYuX2NhbmNlbF9zZWxlY3RlZF90"
    "YXNrLAogICAgICAgICAgICBvbl90b2dnbGVfY29tcGxldGVkPXNlbGYuX3RvZ2dsZV9zaG93X2NvbXBsZXRlZF90YXNrcywK"
    "ICAgICAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkPXNlbGYuX3B1cmdlX2NvbXBsZXRlZF90YXNrcywKICAgICAgICAgICAg"
    "b25fZmlsdGVyX2NoYW5nZWQ9c2VsZi5fb25fdGFza19maWx0ZXJfY2hhbmdlZCwKICAgICAgICAgICAgb25fZWRpdG9yX3Nh"
    "dmU9c2VsZi5fc2F2ZV90YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QsCiAgICAgICAgICAgIG9uX2VkaXRvcl9jYW5jZWw9c2Vs"
    "Zi5fY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSwKICAgICAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPXNlbGYuX2Rp"
    "YWdfdGFiLmxvZywKICAgICAgICApCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl90"
    "YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IHNlbGYuX3NwZWxsX3RhYnMuYWRk"
    "VGFiKHNlbGYuX3Rhc2tzX3RhYiwgIlRhc2tzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJl"
    "YWwgVGFza3NUYWIgYXR0YWNoZWQuIiwgIklORk8iKQoKICAgICAgICAjIOKUgOKUgCBTTCBTY2FucyB0YWIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2Vs"
    "Zi5fc2xfc2NhbnMgPSBTTFNjYW5zVGFiKGNmZ19wYXRoKCJzbCIpKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFi"
    "KHNlbGYuX3NsX3NjYW5zLCAiU0wgU2NhbnMiKQoKICAgICAgICAjIOKUgOKUgCBTTCBDb21tYW5kcyB0YWIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2xfY29t"
    "bWFuZHMgPSBTTENvbW1hbmRzVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zbF9jb21tYW5k"
    "cywgIlNMIENvbW1hbmRzIikKCiAgICAgICAgIyDilIDilIAgSm9iIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2pvYl90cmFja2VyID0gSm9i"
    "VHJhY2tlclRhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fam9iX3RyYWNrZXIsICJKb2IgVHJh"
    "Y2tlciIpCgogICAgICAgICMg4pSA4pSAIExlc3NvbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2xlc3NvbnNfdGFiID0gTGVzc29u"
    "c1RhYihzZWxmLl9sZXNzb25zKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2xlc3NvbnNfdGFiLCAi"
    "TGVzc29ucyIpCgogICAgICAgICMgU2VsZiB0YWIgaXMgbm93IGluIHRoZSBtYWluIGFyZWEgYWxvbmdzaWRlIHRoZSBwZXJz"
    "b25hIGNoYXQgdGFiCiAgICAgICAgIyBLZWVwIGEgU2VsZlRhYiBpbnN0YW5jZSBmb3IgaWRsZSBjb250ZW50IGdlbmVyYXRp"
    "b24KICAgICAgICBzZWxmLl9zZWxmX3RhYiA9IFNlbGZUYWIoKQoKICAgICAgICAjIOKUgOKUgCBNb2R1bGUgVHJhY2tlciB0"
    "YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbW9k"
    "dWxlX3RyYWNrZXIgPSBNb2R1bGVUcmFja2VyVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9t"
    "b2R1bGVfdHJhY2tlciwgIk1vZHVsZXMiKQoKICAgICAgICAjIOKUgOKUgCBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy5hZGRUYWIoc2VsZi5fZGlhZ190YWIsICJEaWFnbm9zdGljcyIpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRn"
    "ZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW91dChyaWdodF93b3Jrc3BhY2UpCiAgICAg"
    "ICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByaWdodF93"
    "b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fc3BlbGxfdGFicywgMSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKdpyBDQUxFTkRBUiIpCiAg"
    "ICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQt"
    "c2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAg"
    "ICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVsKQoKICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTaXplUG9saWN5KAogICAg"
    "ICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4"
    "aW11bQogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAg"
    "ICBzZWxmLmNhbGVuZGFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2Rh"
    "dGUpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl93aWRnZXQsIDApCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRTdHJldGNoKDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmln"
    "aHRfd29ya3NwYWNlLCAxKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0"
    "LXNpZGUgY2FsZW5kYXIgcmVzdG9yZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAg"
    "IklORk8iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHBlcnNp"
    "c3RlbnQgbWluaSBjYWxlbmRhciByZXN0b3JlZC9jb25maXJtZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAog"
    "ICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgcmV0dXJuIGxheW91dAoKICAgICMg4pSA4pSAIFNUQVJUVVAg"
    "U0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAg"
    "ICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290"
    "c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0Igog"
    "ICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtc2dzID0gYm9v"
    "dF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAjIGNvbnN1bWVkCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0ZWN0"
    "aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2V0X2RpYWdub3N0"
    "aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5jeUNoZWNr"
    "ZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQgcGFz"
    "dCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24i"
    "LCIiKQogICAgICAgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgIGYiW1NUQVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZPIgogICAgICAgICAgICAp"
    "CgogICAgICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAg"
    "ICAgICBVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAg"
    "ZiJTdW1tb25pbmcge0RFQ0tfTkFNRX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElO"
    "RyIpCgogICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgc2Vs"
    "Zi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNU"
    "RU0iLCBtKSkKICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJFUlJPUiIsIGUpKQogICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIu"
    "ZGVsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBz"
    "ZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fbG9hZF9jb21wbGV0ZShzZWxmLCBzdWNjZXNzOiBib29sKSAtPiBO"
    "b25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAg"
    "ICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkK"
    "ICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9m"
    "aWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1cmUgVlJBTSBiYXNlbGluZSBhZnRlciBtb2RlbCBsb2FkCiAg"
    "ICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92cmFtX2Jhc2VsaW5lKQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICAgICAjIFZhbXBpcmUgc3Rh"
    "dGUgZ3JlZXRpbmcKICAgICAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgICAgICBzdGF0ZSA9IGdl"
    "dF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAo"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAgICAgICAgIlNZU1RFTSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4iKQogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyBzaHV0ZG93biByZWNvcmRlZCwgaW5qZWN0"
    "IGNvbnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5uYSBjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcg"
    "c2hlIHNsZXB0CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbWly"
    "cm9yLnNldF9mYWNlKCJwYW5pY2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkg"
    "LT4gc3RyOgogICAgICAgICIiIkZvcm1hdCBlbGFwc2VkIHNlY29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIi"
    "CiAgICAgICAgaWYgc2Vjb25kcyA8IDYwOgogICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3Mn"
    "IGlmIHNlY29uZHMgIT0gMSBlbHNlICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0g"
    "aW50KHNlY29uZHMgLy8gNjApCiAgICAgICAgICAgIHMgPSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4g"
    "ZiJ7bX0gbWludXRleydzJyBpZiBtICE9IDEgZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBl"
    "bGlmIHNlY29uZHMgPCA4NjQwMDoKICAgICAgICAgICAgaCA9IGludChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0g"
    "PSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie2h9IGhvdXJ7J3MnIGlmIGggIT0g"
    "MSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBlbHNlICIiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQo"
    "c2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9IGludCgoc2Vjb25kcyAlIDg2NDAwKSAvLyAzNjAwKQogICAgICAg"
    "ICAgICByZXR1cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEgZWxzZSAnJ30iICsgKGYiIHtofWgiIGlmIGggZWxzZSAiIikK"
    "CiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2Ut"
    "dXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3NodXRkb3duID0gc2VsZi5fc3Rh"
    "dGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAgICAgICAgcmV0dXJu"
    "ICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAgIyBDYWxjdWxhdGUg"
    "ZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1lLmZyb21pc29mb3Jt"
    "YXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0ID0gZGF0ZXRpbWUubm93KCkKICAgICAgICAgICAgIyBNYWtl"
    "IGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQudHppbmZvIGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVwbGFjZSh0emluZm89"
    "Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFsX3NlY29uZHMoKQog"
    "ICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24gZHVyYXRpb24iCgogICAgICAgICMg"
    "R2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwgICAgID0gc2VsZi5fc3RhdGUu"
    "Z2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3No"
    "dXRkb3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAgIGNvbnRleHRfYmxv"
    "Y2sgPSAiIgogICAgICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJcblxuVGhlIGZp"
    "bmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3RfY29udGV4"
    "dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQogICAgICAg"
    "ICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0"
    "X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlm"
    "IGZhcmV3ZWxsOgogICAgICAgICAgICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRl"
    "YWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAg"
    "IGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAg"
    "ICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBm"
    "IlxuR3JlZXQgeW91ciBNYXN0ZXIgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgog"
    "ICAgICAgICAgICBmImFuZCB3aGF0ZXZlciB5b3UgbGFzdCBzYWlkIHRvIHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJm"
    "dWwuIgogICAgICAgICkKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltXQUtFVVBdIEluamVj"
    "dGluZyB3YWtlLXVwIGNvbnRleHQgKHtlbGFwc2VkX3N0cn0gZWxhcHNlZCkiLCAiSU5GTyIKICAgICAgICApCgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlz"
    "dG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IHdha2V1cF9wcm9tcHR9KQogICAgICAgICAgICB3b3Jr"
    "ZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0Us"
    "IGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fd2FrZXVwX3dvcmtlciA9"
    "IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX3Jl"
    "YWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAg"
    "ICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VVUF1bRVJST1JdIHtlfSIsICJXQVJOIikKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQog"
    "ICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtl"
    "ci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQgZHVlIHRvIGVycm9yOiB7"
    "ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBfZ29vZ2xlX2F1dGgo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBGb3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBzdGFydHVwIGFm"
    "dGVyIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlzc2luZy9pbnZhbGlkLCB0aGUg"
    "YnJvd3NlciBPQXV0aCBmbG93IG9wZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xFX09L"
    "IG9yIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAi"
    "W0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5h"
    "dmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9J"
    "TVBPUlRfRVJST1I6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtXQVJO"
    "XSB7R09PR0xFX0lNUE9SVF9FUlJPUn0iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGlmIG5vdCBzZWxmLl9nY2FsIG9yIG5vdCBzZWxmLl9nZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBw"
    "ZWQgYmVjYXVzZSBzZXJ2aWNlIG9iamVjdHMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4i"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVnaW5uaW5nIHByb2FjdGl2ZSBHb29nbGUgYXV0aCBjaGVjay4iLCAiSU5GTyIpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gY3JlZGVu"
    "dGlhbHM9e3NlbGYuX2djYWwuY3JlZGVudGlhbHNfcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSB0"
    "b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQoKICAg"
    "ICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dP"
    "T0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0siKQoKICAgICAgICAgICAgc2VsZi5fZ2RyaXZlLmVu"
    "c3VyZV9zZXJ2aWNlcygpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gRHJpdmUv"
    "RG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gVHJ1ZQoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hlZHVsaW5nIGluaXRpYWwgUmVjb3Jk"
    "cyByZWZyZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYu"
    "X3JlZnJlc2hfcmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQ"
    "XSBQb3N0LWF1dGggdGFzayByZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hf"
    "dGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBd"
    "IEluaXRpYWwgY2FsZW5kYXIgaW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAgICAg"
    "ICAgaW1wb3J0ZWRfY291bnQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1U"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBd"
    "IEdvb2dsZSBDYWxlbmRhciB0YXNrIGltcG9ydCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAg"
    "ICAgICAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKCgogICAgZGVmIF9y"
    "ZWZyZXNoX3JlY29yZHNfZG9jcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJf"
    "aWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9hZGluZyBHb29n"
    "bGUgRHJpdmUgcmVjb3Jkcy4uLiIpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRo"
    "OiBNeSBEcml2ZSIpCiAgICAgICAgZmlsZXMgPSBzZWxmLl9nZHJpdmUubGlzdF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNl"
    "bGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQsIHBhZ2Vfc2l6ZT0yMDApCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNo"
    "ZSA9IGZpbGVzCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IFRydWUKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "X3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhfdGV4dD0iTXkgRHJpdmUiKQoKICAgIGRlZiBfb25fZ29vZ2xlX2luYm91bmRf"
    "dGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgdGljayBmaXJlZCDigJQgYXV0aCBu"
    "b3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91bmQgc3luYyB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3Jv"
    "dW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRlZiBf"
    "Y2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2Nh"
    "bGVuZGFyX2luYm91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtUSU1F"
    "Ul0gQ2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDigJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vzc2VkLiIsICJPSyIpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xF"
    "XVtUSU1FUl1bRVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICBfdGhyZWFkaW5n"
    "LlRocmVhZCh0YXJnZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dvb2dsZV9yZWNvcmRz"
    "X3JlZnJlc2hfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFk"
    "eToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJlZCDigJQg"
    "YXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBzdGFydGluZyBi"
    "YWNrZ3JvdW5kIHJlZnJlc2guIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAg"
    "ICAgIGRlZiBfYmcoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2Rv"
    "Y3MoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyBy"
    "ZWZyZXNoIGNvbXBsZXRlLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtEUklWRV1bU1lOQ11bRVJS"
    "T1JdIHJlY29yZHMgcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3Ro"
    "cmVhZGluZy5UaHJlYWQodGFyZ2V0PV9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tz"
    "X2Zvcl9yZWdpc3RyeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwo"
    "KQogICAgICAgIG5vdyA9IG5vd19mb3JfY29tcGFyZSgpCiAgICAgICAgaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAi"
    "d2VlayI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTcpCiAgICAgICAgZWxpZiBzZWxmLl90YXNr"
    "X2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTMxKQogICAg"
    "ICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAieWVhciI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVk"
    "ZWx0YShkYXlzPTM2NikKICAgICAgICBlbHNlOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz05MikK"
    "CiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBzdGFydCBmaWx0ZXI9"
    "e3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkfSB0b3Rh"
    "bD17bGVuKHRhc2tzKX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltUQVNLU11bRklMVEVSXSBub3c9e25vdy5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBob3Jpem9uX2VuZD17ZW5kLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0W2RpY3RdID0gW10KICAgICAg"
    "ICBza2lwcGVkX2ludmFsaWRfZHVlID0gMAogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBzdGF0dXMg"
    "PSAodGFzay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBpZiBub3Qgc2VsZi5fdGFz"
    "a19zaG93X2NvbXBsZXRlZCBhbmQgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKCiAgICAgICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIp"
    "CiAgICAgICAgICAgIGR1ZV9kdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190YWJf"
    "ZHVlX2ZpbHRlciIpCiAgICAgICAgICAgIGlmIGR1ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAg"
    "c2tpcHBlZF9pbnZhbGlkX2R1ZSArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl1bV0FSTl0gc2tpcHBpbmcgaW52YWxpZCBkdWUgZGF0ZXRpbWUgdGFza19pZD17"
    "dGFzay5nZXQoJ2lkJywnPycpfSBkdWVfcmF3PXtkdWVfcmF3IXJ9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAg"
    "ICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmU6"
    "CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAg"
    "ICAgIGlmIG5vdyA8PSBkdWVfZHQgPD0gZW5kIG9yIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAg"
    "ICAgICAgICAgICAgIGZpbHRlcmVkLmFwcGVuZCh0YXNrKQoKICAgICAgICBmaWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVf"
    "c29ydF9rZXkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBkb25l"
    "IGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0ZXI9e2xlbihmaWx0ZXJlZCl9IHNraXBwZWRfaW52YWxpZF9kdWU9e3NraXBwZWRf"
    "aW52YWxpZF9kdWV9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4gZmlsdGVyZWQKCiAg"
    "ICBkZWYgX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUoc2VsZiwgZXZlbnQ6IGRpY3QpOgogICAgICAgIHN0YXJ0ID0gKGV2"
    "ZW50IG9yIHt9KS5nZXQoInN0YXJ0Iikgb3Ige30KICAgICAgICBkYXRlX3RpbWUgPSBzdGFydC5nZXQoImRhdGVUaW1lIikK"
    "ICAgICAgICBpZiBkYXRlX3RpbWU6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkYXRlX3Rp"
    "bWUsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlVGltZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAg"
    "ICAgIHJldHVybiBwYXJzZWQKICAgICAgICBkYXRlX29ubHkgPSBzdGFydC5nZXQoImRhdGUiKQogICAgICAgIGlmIGRhdGVf"
    "b25seToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKGYie2RhdGVfb25seX1UMDk6MDA6MDAi"
    "LCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAgICAgIHJl"
    "dHVybiBwYXJzZWQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnJlZnJlc2goKQogICAgICAg"
    "ICAgICB2aXNpYmxlX2NvdW50ID0gbGVuKHNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSgpKQogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXSByZWZyZXNoIGNvdW50PXt2aXNpYmxlX2NvdW50fS4i"
    "LCAiSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW1RBU0tTXVtSRUdJU1RSWV1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJyZWdpc3Ry"
    "eV9yZWZyZXNoX2V4Y2VwdGlvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgc3RvcF9leDoKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bUkVHSVNUUlldW1dBUk5d"
    "IGZhaWxlZCB0byBzdG9wIHJlZnJlc2ggd29ya2VyIGNsZWFubHk6IHtzdG9wX2V4fSIsCiAgICAgICAgICAgICAgICAgICAg"
    "IldBUk4iLAogICAgICAgICAgICAgICAgKQoKICAgIGRlZiBfb25fdGFza19maWx0ZXJfY2hhbmdlZChzZWxmLCBmaWx0ZXJf"
    "a2V5OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9IHN0cihmaWx0ZXJfa2V5IG9yICJu"
    "ZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFRhc2sgcmVnaXN0cnkgZGF0ZSBm"
    "aWx0ZXIgY2hhbmdlZCB0byB7c2VsZi5fdGFza19kYXRlX2ZpbHRlcn0uIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJl"
    "c2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQK"
    "ICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NlbGVjdGVkX3Rhc2tfaWRzKHNl"
    "bGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToK"
    "ICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJuIHNlbGYuX3Rhc2tzX3RhYi5zZWxlY3RlZF90YXNrX2lkcygp"
    "CgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0cikgLT4gT3B0aW9uYWxb"
    "ZGljdF06CiAgICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFz"
    "a3MuY29tcGxldGUodGFza19pZCkKICAgICAgICBlbGlmIHN0YXR1cyA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAgdXBk"
    "YXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBz"
    "ZWxmLl90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAgaWYgbm90IHVwZGF0ZWQ6CiAgICAg"
    "ICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVkLmdldCgiZ29vZ2xlX2V2ZW50"
    "X2lkIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2djYWwuZGVsZXRlX2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgICAgICBmIltUQVNLU11bV0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lkPXt0YXNrX2lk"
    "fToge2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVybiB1"
    "cGRhdGVkCgogICAgZGVmIF9jb21wbGV0ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAK"
    "ICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9z"
    "ZXRfdGFza19zdGF0dXModGFza19pZCwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDT01QTEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMp"
    "LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2Vs"
    "X3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNl"
    "bGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAi"
    "Y2FuY2VsbGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFT"
    "S1NdIENBTkNFTCBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9y"
    "ZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfcHVyZ2VfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmVtb3ZlZCA9IHNlbGYuX3Rhc2tzLmNsZWFyX2NvbXBsZXRlZCgpCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01QTEVURUQgcmVtb3ZlZCB7cmVtb3ZlZH0gdGFzayhzKS4iLCAiSU5GTyIpCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NldF90YXNrX2VkaXRvcl9zdGF0"
    "dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwg"
    "Il90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zdGF0dXMo"
    "dGV4dCwgb2s9b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2NhbCA9IG5vd19sb2NhbCArIHRpbWVkZWx0YSht"
    "aW51dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1lLnNldFRleHQoIiIpCiAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVZLSVt"
    "LSVkIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0VGV4dChub3dfbG9jYWwu"
    "c3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFRleHQo"
    "ZW5kX2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRf"
    "dGltZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19l"
    "ZGl0b3Jfbm90ZXMuc2V0UGxhaW5UZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2NhdGlv"
    "bi5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIp"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBz"
    "ZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xl"
    "IENhbGVuZGFyLiIsIG9rPUZhbHNlKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgogICAgZGVmIF9j"
    "bG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFz"
    "a3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoK"
    "ICAgIGRlZiBfY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3Nl"
    "X3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0"
    "OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBhbGxfZGF5OiBib29sLCBpc19lbmQ6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0"
    "ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIHRpbWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIp"
    "LnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0ZV90ZXh0OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFs"
    "bF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlm"
    "IGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91"
    "cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgcGFyc2Vk"
    "ID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAg"
    "ICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRp"
    "dG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1Jd"
    "IHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2FsbF9kYXl9OiAiCiAgICAgICAgICAgIGYiaW5w"
    "dXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3JtYXQoKSBpZiBub3JtYWxpemVkIGVs"
    "c2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAg"
    "ICBkZWYgX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdGFiID0gZ2V0YXR0"
    "cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpCiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIHRpdGxlID0gdGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBhbGxfZGF5ID0gdGFi"
    "LnRhc2tfZWRpdG9yX2FsbF9kYXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX3N0"
    "YXJ0X2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUu"
    "dGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgIGVuZF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90"
    "ZXMgPSB0YWIudGFza19lZGl0b3Jfbm90ZXMudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIu"
    "dGFza19lZGl0b3JfbG9jYXRpb24udGV4dCgpLnN0cmlwKCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRhc2tfZWRpdG9y"
    "X3JlY3VycmVuY2UudGV4dCgpLnN0cmlwKCkKCiAgICAgICAgaWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRf"
    "dGFza19lZGl0b3Jfc3RhdHVzKCJUYXNrIE5hbWUgaXMgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIGlmIG5vdCBzdGFydF9kYXRlIG9yIG5vdCBlbmRfZGF0ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3Rh"
    "cnRfdGltZSBvciBub3QgZW5kX3RpbWUpKToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3Rh"
    "cnQvRW5kIGRhdGUgYW5kIHRpbWUgYXJlIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHN0YXJ0X2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHN0YXJ0X2RhdGUsIHN0"
    "YXJ0X3RpbWUsIGFsbF9kYXksIGlzX2VuZD1GYWxzZSkKICAgICAgICAgICAgZW5kX2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9y"
    "X2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGltZSwgYWxsX2RheSwgaXNfZW5kPVRydWUpCiAgICAgICAgICAgIGlmIG5vdCBz"
    "dGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiZGF0ZXRpbWUgcGFyc2Ug"
    "ZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3RhcnRfZHQ6CiAgICAgICAgICAgICAgICBzZWxmLl9zZXRfdGFz"
    "a19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBhZnRlciBzdGFydCBkYXRldGltZS4iLCBvaz1GYWxzZSkK"
    "ICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuX3NldF90"
    "YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQgZGF0ZS90aW1lIGZvcm1hdC4gVXNlIFlZWVktTU0tREQgYW5kIEhIOk1NLiIs"
    "IG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2djYWwuX2dldF9nb29nbGVf"
    "ZXZlbnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRsZX0KICAgICAgICBpZiBhbGxfZGF5"
    "OgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0ZSgpLmlzb2Zvcm1hdCgpfQog"
    "ICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGltZWRlbHRhKGRheXM9MSkp"
    "Lmlzb2Zvcm1hdCgpfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGVUaW1lIjog"
    "c3RhcnRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6"
    "IHR6X25hbWV9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBsYWNlKHR6aW5m"
    "bz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBpZiBu"
    "b3RlczoKICAgICAgICAgICAgcGF5bG9hZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAg"
    "ICAgICAgICAgIHBheWxvYWRbImxvY2F0aW9uIl0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAg"
    "ICAgIHJ1bGUgPSByZWN1cnJlbmNlIGlmIHJlY3VycmVuY2UudXBwZXIoKS5zdGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYi"
    "UlJVTEU6e3JlY3VycmVuY2V9IgogICAgICAgICAgICBwYXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0KCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxl"
    "fScuIiwgIklORk8iKQogICAgICAgIHRyeToKICAgICAgICAgICAgZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9l"
    "dmVudF93aXRoX3BheWxvYWQocGF5bG9hZCwgY2FsZW5kYXJfaWQ9InByaW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNl"
    "bGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgICAgICJpZCI6IGYidGFza197"
    "dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6IGxvY2FsX25vd19pc28oKSwK"
    "ICAgICAgICAgICAgICAgICJkdWVfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAg"
    "ICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChzdGFydF9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJ0ZXh0IjogdGl0bGUsCiAgICAgICAgICAgICAgICAic3RhdHVz"
    "IjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAi"
    "cmV0cnlfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjogTm9uZSwKICAgICAgICAgICAg"
    "ICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogRmFsc2UsCiAgICAg"
    "ICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiBldmVudF9p"
    "ZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAgICAgICAgICAgICAgImxhc3Rfc3luY2Vk"
    "X2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAg"
    "ICJpbnB1dCI6ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAgICAgICAgICJub3RlcyI6IG5vdGVz"
    "LAogICAgICAgICAgICAgICAgICAgICJzdGFydF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "LAogICAgICAgICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAgICAgICJsb2NhdGlv"
    "biI6IGxvY2F0aW9uLAogICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAgICAgICAgICAg"
    "ICAgIH0sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNlbGYuX3Rh"
    "c2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUgc3lu"
    "YyBzdWNjZWVkZWQgYW5kIHRhc2sgcmVnaXN0cnkgdXBkYXRlZC4iLCBvaz1UcnVlKQogICAgICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtl"
    "dmVudF9pZH0uIiwKICAgICAgICAgICAgICAgICJPSyIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2Vf"
    "dGFza19lZGl0b3Jfd29ya3NwYWNlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxm"
    "Ll9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKGYiR29vZ2xlIHNhdmUgZmFpbGVkOiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdW0VSUk9SXSBHb29nbGUg"
    "c2F2ZSBmYWlsdXJlIGZvciB0aXRsZT0ne3RpdGxlfSc6IHtleH0iLAogICAgICAgICAgICAgICAgIkVSUk9SIiwKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0"
    "X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRhdGU6IFFEYXRlKSAtPiBOb25lOgogICAgICAgIGRhdGVfdGV4dCA9IHFkYXRlLnRv"
    "U3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gIm5vbmUiCgogICAgICAgIGZvY3VzX3dpZGdl"
    "dCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgpCiAgICAgICAgZGlyZWN0X3RhcmdldHMgPSBbCiAgICAgICAgICAgICgi"
    "dGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFz"
    "a19lZGl0b3Jfc3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIGdldGF0"
    "dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3JfZW5kX2RhdGUiLCBOb25lKSksCiAg"
    "ICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0X3RhcmdldHM6CiAgICAgICAgICAgIGlmIHdpZGdl"
    "dCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRUZXh0"
    "KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1lCiAgICAgICAgICAgICAgICBicmVhawoK"
    "ICAgICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0"
    "X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lk"
    "Z2V0IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChk"
    "YXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNlcnQiCiAgICAg"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0"
    "KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBpZiBoYXNh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIikgYW5kIHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2Vs"
    "Zi5fdGFza3NfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiQ2FsZW5kYXIgZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0i"
    "KQoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVu"
    "ZGFyIGNsaWNrIHJvdXRlZDogZGF0ZT17ZGF0ZV90ZXh0fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAg"
    "ICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhz"
    "ZWxmLCBmb3JjZV9vbmNlOiBib29sID0gRmFsc2UpOgogICAgICAgICIiIgogICAgICAgIFN5bmMgR29vZ2xlIENhbGVuZGFy"
    "IGV2ZW50cyDihpIgbG9jYWwgdGFza3MgdXNpbmcgR29vZ2xlJ3Mgc3luY1Rva2VuIEFQSS4KCiAgICAgICAgU3RhZ2UgMSAo"
    "Zmlyc3QgcnVuIC8gZm9yY2VkKTogRnVsbCBmZXRjaCwgc3RvcmVzIG5leHRTeW5jVG9rZW4uCiAgICAgICAgU3RhZ2UgMiAo"
    "ZXZlcnkgcG9sbCk6ICAgICAgICAgSW5jcmVtZW50YWwgZmV0Y2ggdXNpbmcgc3RvcmVkIHN5bmNUb2tlbiDigJQKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm5zIE9OTFkgd2hhdCBjaGFuZ2VkIChhZGRzL2VkaXRzL2Nh"
    "bmNlbHMpLgogICAgICAgIElmIHNlcnZlciByZXR1cm5zIDQxMCBHb25lICh0b2tlbiBleHBpcmVkKSwgZmFsbHMgYmFjayB0"
    "byBmdWxsIHN5bmMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IGZvcmNlX29uY2UgYW5kIG5vdCBib29sKENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNfZW5hYmxlZCIsIFRydWUpKToKICAgICAgICAgICAgcmV0dXJuIDAK"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBub3dfaXNvID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHRhc2tzID0g"
    "c2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZCA9IHsKICAgICAgICAgICAgICAg"
    "ICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6IHQKICAgICAgICAgICAgICAgIGZvciB0IGluIHRh"
    "c2tzCiAgICAgICAgICAgICAgICBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAg"
    "ICAgIH0KCiAgICAgICAgICAgICMg4pSA4pSAIEZldGNoIGZyb20gR29vZ2xlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdG9yZWRfdG9rZW4gPSBzZWxmLl9zdGF0ZS5nZXQo"
    "Imdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIikKCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHN0b3Jl"
    "ZF90b2tlbiBhbmQgbm90IGZvcmNlX29uY2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gSW5jcmVtZW50YWwgc3luYyAoc3luY1Rva2VuKS4iLCAiSU5G"
    "TyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9"
    "IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbj1zdG9y"
    "ZWRfdG9rZW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEZ1bGwgc3luYyAo"
    "bm8gc3RvcmVkIHRva2VuKS4iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgbm93"
    "X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1l"
    "X21pbiA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAg"
    "ICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAg"
    "ICAgICAgICAgICAgICAgICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgYXBpX2V4OgogICAgICAgICAgICAgICAgaWYgIjQxMCIgaW4gc3RyKGFwaV9leCkgb3IgIkdv"
    "bmUiIGluIHN0cihhcGlfZXgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIHN5bmNUb2tlbiBleHBpcmVkICg0MTApIOKAlCBmdWxsIHJlc3luYy4iLCAi"
    "V0FSTiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc3RhdGUucG9wKCJnb29nbGVf"
    "Y2FsZW5kYXJfc3luY190b2tlbiIsIE5vbmUpCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9IGRhdGV0aW1lLnV0Y25v"
    "dygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChub3dfdXRjIC0gdGlt"
    "ZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBu"
    "ZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICB0aW1l"
    "X21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAg"
    "ICAgICAgcmFpc2UKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1b"
    "U1lOQ10gUmVjZWl2ZWQge2xlbihyZW1vdGVfZXZlbnRzKX0gZXZlbnQocykuIiwgIklORk8iCiAgICAgICAgICAgICkKCiAg"
    "ICAgICAgICAgICMgU2F2ZSBuZXcgdG9rZW4gZm9yIG5leHQgaW5jcmVtZW50YWwgY2FsbAogICAgICAgICAgICBpZiBuZXh0"
    "X3Rva2VuOgogICAgICAgICAgICAgICAgc2VsZi5fc3RhdGVbImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIl0gPSBuZXh0"
    "X3Rva2VuCiAgICAgICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgICAg"
    "ICMg4pSA4pSAIFByb2Nlc3MgZXZlbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHVwZGF0ZWRfY291bnQgPSByZW1vdmVkX2Nv"
    "dW50ID0gMAogICAgICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVfZXZl"
    "bnRzOgogICAgICAgICAgICAgICAgZXZlbnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAg"
    "ICAgICAgICBpZiBub3QgZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICAj"
    "IERlbGV0ZWQgLyBjYW5jZWxsZWQgb24gR29vZ2xlJ3Mgc2lkZQogICAgICAgICAgICAgICAgaWYgZXZlbnQuZ2V0KCJzdGF0"
    "dXMiKSA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdl"
    "dChldmVudF9pZCkKICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZyBhbmQgZXhpc3RpbmcuZ2V0KCJzdGF0dXMiKSBu"
    "b3QgaW4gKCJjYW5jZWxsZWQiLCAiY29tcGxldGVkIik6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzdGF0"
    "dXMiXSAgICAgICAgID0gImNhbmNlbGxlZCIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9h"
    "dCJdICAgPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdICAgID0gImRl"
    "bGV0ZWRfcmVtb3RlIgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9zeW5jZWRfYXQiXSA9IG5vd19p"
    "c28KICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rpbmcuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSlbImdvb2dsZV9k"
    "ZWxldGVkX3JlbW90ZSJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICByZW1vdmVkX2NvdW50ICs9IDEKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBSZW1vdmVkOiB7ZXhpc3Rpbmcu"
    "Z2V0KCd0ZXh0JywnPycpfSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAg"
    "Y29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2ZW50LmdldCgic3VtbWFyeSIpIG9yICJHb29nbGUgQ2Fs"
    "ZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiCiAgICAgICAgICAgICAgICBkdWVfYXQg"
    "ID0gc2VsZi5fZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFz"
    "a3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQoKICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAgICAg"
    "ICAgICAgICMgVXBkYXRlIGlmIGFueXRoaW5nIGNoYW5nZWQKICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBG"
    "YWxzZQogICAgICAgICAgICAgICAgICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAiIikuc3RyaXAoKSAhPSBzdW1t"
    "YXJ5OgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sidGV4dCJdID0gc3VtbWFyeQogICAgICAgICAgICAgICAg"
    "ICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0OgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBkdWVfaXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGlmIGV4aXN0aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGV4aXN0aW5nWyJkdWVfYXQiXSAgICAgICA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0"
    "aW5nWyJwcmVfdHJpZ2dlciJdICA9IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAg"
    "ICAgICAgICBpZiBleGlzdGluZy5nZXQoInN5bmNfc3RhdHVzIikgIT0gInN5bmNlZCI6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdID0gInN5bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFu"
    "Z2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIHRhc2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291"
    "bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFVwZGF0ZWQ6"
    "IHtzdW1tYXJ5fSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgICAgICMgTmV3IGV2ZW50CiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICBuZXdfdGFzayA9IHsKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgImlkIjogICAgICAgICAgICAgICAgZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgImR1"
    "ZV9hdCI6ICAgICAgICAgICAgZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgICAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgICBzdW1tYXJ5"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJyZXRyeV9jb3Vu"
    "dCI6ICAgICAgIDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVf"
    "YW5ub3VuY2VkIjogICAgIEZhbHNlLAogICAgICAgICAgICAgICAgICAgICAgICAic291cmNlIjogICAgICAgICAgICAiZ29v"
    "Z2xlIiwKICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICAgZXZlbnRfaWQsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICAgICAgICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAibGFz"
    "dF9zeW5jZWRfYXQiOiAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2ltcG9ydGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJnb29nbGVfdXBkYXRlZCI6ICAgICBldmVudC5nZXQoInVwZGF0ZWQiKSwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgfSwKICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQog"
    "ICAgICAgICAgICAgICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAg"
    "ICAgICAgaW1wb3J0ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ10gSW1wb3J0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZP"
    "IikKCiAgICAgICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykK"
    "ICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gRG9uZSDigJQgaW1wb3J0ZWQ9e2ltcG9ydGVkX2Nv"
    "dW50fSAiCiAgICAgICAgICAgICAgICBmInVwZGF0ZWQ9e3VwZGF0ZWRfY291bnR9IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9"
    "IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIGltcG9ydGVkX2NvdW50CgogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdW0VSUk9S"
    "XSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgcmV0dXJuIDAKCgogICAgZGVmIF9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3Zy"
    "YW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05BTUV9J3MgZm9vdHByaW50KSIsICJJTkZP"
    "IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoK"
    "ICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2Fn"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRl"
    "ID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxkLnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgaWYgbm90IHRleHQ6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFjayB0"
    "byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1"
    "cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAg"
    "ICAgICAjIFNlc3Npb24gbG9nZ2luZwogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkK"
    "ICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAg"
    "ICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBz"
    "ZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIp"
    "CgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGggdmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2"
    "YW1waXJlX2N0eCAgPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9y"
    "eS5idWlsZF9jb250ZXh0X2Jsb2NrKHRleHQpCiAgICAgICAgam91cm5hbF9jdHggID0gIiIKCiAgICAgICAgaWYgc2VsZi5f"
    "c2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZToKICAgICAgICAgICAgam91cm5hbF9jdHggPSBzZWxmLl9zZXNzaW9ucy5s"
    "b2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2Rh"
    "dGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIHN5c3RlbSBwcm9tcHQKICAgICAgICBzeXN0ZW0gPSBTWVNURU1f"
    "UFJPTVBUX0JBU0UKICAgICAgICBpZiBtZW1vcnlfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue21lbW9yeV9j"
    "dHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2pvdXJuYWxfY3R4fSIK"
    "ICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAgIyBMZXNzb25zIGNvbnRleHQgZm9yIGNvZGUtYWRqYWNl"
    "bnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigpIGZvciBrdyBpbiAoImxzbCIsInB5dGhvbiIsInNj"
    "cmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9ICJMU0wiIGlmICJsc2wiIGluIHRleHQubG93"
    "ZXIoKSBlbHNlICJQeXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2VsZi5fbGVzc29ucy5idWlsZF9jb250ZXh0"
    "X2Zvcl9sYW5ndWFnZShsYW5nKQogICAgICAgICAgICBpZiBsZXNzb25zX2N0eDoKICAgICAgICAgICAgICAgIHN5c3RlbSAr"
    "PSBmIlxuXG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRyYW5zbWlzc2lvbnMgY29udGV4dCBpZiBh"
    "bnkKICAgICAgICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAgICBkdXIgPSBzZWxmLl9z"
    "dXNwZW5kZWRfZHVyYXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAgICAgICAgICAgICAg"
    "IGYiXG5cbltSRVRVUk4gRlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRvcnBvciBmb3Ig"
    "e2R1cn0uICIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMgd2VudCB1"
    "bnNwb2tlbiAiCiAgICAgICAgICAgICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFja25vd2xlZGdlIHRoaXMgYnJpZWZseSBp"
    "biBjaGFyYWN0ZXIgIgogICAgICAgICAgICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJh"
    "dGlvbiAgICA9ICIiCgogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMg"
    "RGlzYWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5w"
    "dXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJHRU5FUkFUSU5HIikKCiAgICAg"
    "ICAgIyBTdG9wIGlkbGUgdGltZXIgZHVyaW5nIGdlbmVyYXRpb24KICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5kIHNl"
    "bGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIu"
    "cGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgTGF1bmNoIHN0cmVhbWluZyB3b3JrZXIKICAgICAgICBzZWxmLl93b3JrZXIgPSBTdHJl"
    "YW1pbmdXb3JrZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIHN5c3RlbSwgaGlzdG9yeSwgbWF4X3Rva2Vucz01MTIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAg"
    "ICAgc2VsZi5fd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgIHNl"
    "bGYuX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KHNlbGYuX29uX2Vycm9yKQogICAgICAgIHNlbGYuX3dvcmtlci5z"
    "dGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVl"
    "ICAjIGZsYWcgdG8gd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3QgdG9rZW4KICAgICAgICBzZWxmLl93b3JrZXIu"
    "c3RhcnQoKQoKICAgIGRlZiBfYmVnaW5fcGVyc29uYV9yZXNwb25zZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAg"
    "ICAgIFdyaXRlIHRoZSBwZXJzb25hIHNwZWFrZXIgbGFiZWwgYW5kIHRpbWVzdGFtcCBiZWZvcmUgc3RyZWFtaW5nIGJlZ2lu"
    "cy4KICAgICAgICBDYWxsZWQgb24gZmlyc3QgdG9rZW4gb25seS4gU3Vic2VxdWVudCB0b2tlbnMgYXBwZW5kIGRpcmVjdGx5"
    "LgogICAgICAgICIiIgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAg"
    "ICAgICAgIyBXcml0ZSB0aGUgc3BlYWtlciBsYWJlbCBhcyBIVE1MLCB0aGVuIGFkZCBhIG5ld2xpbmUgc28gdG9rZW5zCiAg"
    "ICAgICAgIyBmbG93IGJlbG93IGl0IHJhdGhlciB0aGFuIGlubGluZQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBl"
    "bmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAg"
    "ICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19D"
    "UklNU09OfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZid7REVDS19OQU1FLnVwcGVyKCl9IOKdqTwvc3Bh"
    "bj4gJwogICAgICAgICkKICAgICAgICAjIE1vdmUgY3Vyc29yIHRvIGVuZCBzbyBpbnNlcnRQbGFpblRleHQgYXBwZW5kcyBj"
    "b3JyZWN0bHkKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29y"
    "Lm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "c2V0VGV4dEN1cnNvcihjdXJzb3IpCgogICAgZGVmIF9vbl90b2tlbihzZWxmLCB0b2tlbjogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgICIiIkFwcGVuZCBzdHJlYW1pbmcgdG9rZW4gdG8gY2hhdCBkaXNwbGF5LiIiIgogICAgICAgIGlmIHNlbGYuX2ZpcnN0"
    "X3Rva2VuOgogICAgICAgICAgICBzZWxmLl9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKCkKICAgICAgICAgICAgc2VsZi5fZmly"
    "c3RfdG9rZW4gPSBGYWxzZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAg"
    "ICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRf"
    "ZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0"
    "KHRva2VuKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVm"
    "IF9vbl9yZXNwb25zZV9kb25lKHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIyBFbnN1cmUgcmVzcG9u"
    "c2UgaXMgb24gaXRzIG93biBsaW5lCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQog"
    "ICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5f"
    "Y2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFp"
    "blRleHQoIlxuXG4iKQoKICAgICAgICAjIExvZyB0byBtZW1vcnkgYW5kIHNlc3Npb24KICAgICAgICBzZWxmLl90b2tlbl9j"
    "b3VudCArPSBsZW4ocmVzcG9uc2Uuc3BsaXQoKSkKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgiYXNzaXN0"
    "YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJh"
    "c3Npc3RhbnQiLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lbW9yeShzZWxmLl9zZXNzaW9uX2lk"
    "LCAiIiwgcmVzcG9uc2UpCgogICAgICAgICMgVXBkYXRlIGJsb29kIHNwaGVyZQogICAgICAgIGlmIHNlbGYuX2xlZnRfb3Ji"
    "IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKAogICAgICAgICAgICAgICAgbWluKDEu"
    "MCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAgIyBSZS1lbmFibGUgaW5wdXQK"
    "ICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgIyBSZXN1bWUgaWRsZSB0"
    "aW1lcgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1bGUgc2Vu"
    "dGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6"
    "IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTog"
    "c3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAg"
    "IHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5f"
    "c2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2Zh"
    "Y2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "YXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJS"
    "T1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxm"
    "Ll9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikK"
    "ICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "dG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9l"
    "bnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0"
    "ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDi"
    "gJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAg"
    "ICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4"
    "aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHBy"
    "ZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIg"
    "PSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5u"
    "b3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAi"
    "V0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkg"
    "d2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9h"
    "ZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBz"
    "ZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5f"
    "bW9kZWwKICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlm"
    "IFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZh"
    "bHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJB"
    "TS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJP"
    "UiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBz"
    "ZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNl"
    "OgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNl"
    "bGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAg"
    "ICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtp"
    "bmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAg"
    "IyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAg"
    "ICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7"
    "REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmll"
    "Zmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAi"
    "VGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygi"
    "SURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5w"
    "dXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtF"
    "IG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExv"
    "Y2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9t"
    "IHRvcnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxh"
    "cHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAgICAg"
    "ICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2Fk"
    "ZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0i"
    "LCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTog"
    "c2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNv"
    "bm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qo"
    "c2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5f"
    "bG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxl"
    "ciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZS"
    "QU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBv"
    "biB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRl"
    "ICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJl"
    "dHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5m"
    "byhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAgICAgICAg"
    "ICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJu"
    "YWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5j"
    "ZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0"
    "IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAg"
    "ICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1f"
    "cHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSki"
    "LCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tz"
    "ID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBv"
    "cl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9y"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAg"
    "ICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3Zy"
    "YW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0"
    "KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3Rv"
    "cnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAg"
    "ICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9z"
    "Y2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1"
    "bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9"
    "IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUi"
    "OiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1"
    "bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0g"
    "YXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVm"
    "bGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50"
    "ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAg"
    "ICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZl"
    "LCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkK"
    "CiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pv"
    "YigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25k"
    "cz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVz"
    "ZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJp"
    "ZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9t"
    "aW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50"
    "ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAg"
    "ICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAgICAgaWYgc2VsZi5fY3lj"
    "bGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYs"
    "IGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBj"
    "YWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2lu"
    "Z2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVu"
    "bmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0YXJ0"
    "X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNo"
    "b3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJl"
    "IFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9"
    "IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBz"
    "ZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRp"
    "Y2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6"
    "IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6"
    "IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9y"
    "IOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5k"
    "aW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tzZWxmLl9w"
    "ZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFt"
    "cGlyZV9jdHggPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRf"
    "aGlzdG9yeSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRh"
    "cHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBt"
    "b2RlPW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVm"
    "IF9vbl9pZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBhcHBl"
    "bmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAgICAgICAgICB0cyA9"
    "IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQo"
    "CiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+Jwog"
    "ICAgICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5"
    "bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vs"
    "Zl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVh"
    "ZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25u"
    "ZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJST1JdIHtlfSIsICJFUlJP"
    "UiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNF"
    "U1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChkYXRlX3N0cikKICAgICAg"
    "ICBpZiBub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltKT1VSTkFM"
    "XSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3Ry"
    "fSBhcyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0"
    "aW9uLiIsICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYi"
    "QSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVyLiIKICAgICAgICAp"
    "CiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5v"
    "dGUgPSAoCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5h"
    "bCBmcm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB5b3Ug"
    "bm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYXRpb24uIgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xl"
    "YXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pv"
    "dXJuYWwoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVkLiIs"
    "ICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIlRoZSBqb3VybmFsIGNs"
    "b3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0g"
    "ZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0"
    "ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogICAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxz"
    "KAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAgICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIp"
    "LnVwcGVyKCksCiAgICAgICAgICAgIHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIExlZnQgc3BoZXJlID0g"
    "YWN0aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAgICAgICBsZWZ0X29yYl9maWxsID0gbWluKDEuMCwg"
    "c2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwobGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICMg"
    "UmlnaHQgc3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9yaWdodF9vcmIgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAg"
    "ICAgICAgdnJhbV91c2VkID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1l"
    "bS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9vcmJfZmlsbCA9IG1heCgwLjAsIDEuMCAtICh2"
    "cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwocmlnaHRf"
    "b3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKICAgICAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAj"
    "IFByaW1hcnkgZXNzZW5jZSA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGVzc2VuY2VfcHJpbWFyeV9y"
    "YXRpbyA9IDEuMCAtIGxlZnRfb3JiX2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2Vs"
    "Zi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5j"
    "ZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCgogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAg"
    "ICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAg"
    "ICAgICBlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyAgPSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAg"
    "ICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBk"
    "YXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNo"
    "KCkKCiAgICAjIOKUgOKUgCBDSEFUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsK"
    "ICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAg"
    "ICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0K"
    "ICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAg"
    "REVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAg"
    "ICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2Vy"
    "LCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAg"
    "ICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzcGVh"
    "a2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAg"
    "Zic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYn"
    "W3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9y"
    "fTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hh"
    "dF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAg"
    "ICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07"
    "Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEn"
    "cyByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBwZXIo"
    "KToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNj"
    "cm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAg"
    "ICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAg"
    "ICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAg"
    "ICJPRkZMSU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAg"
    "fQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jwb3Jf"
    "bGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0"
    "dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVz"
    "X2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAgICAgIGlmIHNlbGYuX3N0YXR1"
    "cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLi"
    "l44iCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAg"
    "ZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19z"
    "dGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBm"
    "IntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6"
    "IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAg"
    "ICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBz"
    "ZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5h"
    "YmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RF"
    "WFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENf"
    "Qk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIGlmIHNlbGYuX3Nj"
    "aGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlm"
    "IGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNz"
    "aW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBl"
    "bmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0iLCAi"
    "RVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBf"
    "dG9nZ2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAg"
    "ICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAgIGRlZiBfdG9nZ2xlX2JvcmRlcmxl"
    "c3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93VHlw"
    "ZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdz"
    "KAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGlu"
    "dAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaWYgc2Vs"
    "Zi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuc2V0"
    "V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVz"
    "c1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAg"
    "ICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuc2hvdygpCgog"
    "ICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hh"
    "dCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2No"
    "YXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0"
    "X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCku"
    "c3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97"
    "dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAg"
    "ICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRU"
    "ZXh0KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vz"
    "c2lvbiBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIp"
    "CgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkK"
    "ICAgICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkK"
    "ICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3Mo"
    "KQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAg"
    "ICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25l"
    "OgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3No"
    "dXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAi"
    "IiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQg"
    "bGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBx"
    "dWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAgICAgICAg"
    "ICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9w"
    "cm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBB"
    "SQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikK"
    "ICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0Nf"
    "VEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAg"
    "ICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAg"
    "IGxibCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYi"
    "e0RFQ0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQog"
    "ICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5f"
    "cm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRv"
    "d24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwg"
    "PSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2Vs"
    "KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAgICBi"
    "dG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVY"
    "VH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7Igog"
    "ICAgICAgICkKICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBi"
    "dG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5j"
    "b25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAg"
    "ICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAg"
    "IGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1"
    "bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3Mg"
    "PSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lu"
    "cHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoK"
    "ICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRv"
    "d24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93"
    "bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dv"
    "cmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyBy"
    "ZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAg"
    "ICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAg"
    "ICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAg"
    "ICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9j"
    "aGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBoZXIgZmluYWwg"
    "d29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0g"
    "IiIKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAg"
    "ICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0fSkKICAg"
    "ICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVN"
    "X1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3No"
    "dXRkb3duX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAg"
    "IGRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFy"
    "ZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQog"
    "ICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAg"
    "ICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAg"
    "ICAgICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChz"
    "ZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAg"
    "ICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVz"
    "X2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3"
    "b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1l"
    "b3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFUaW1l"
    "ci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAg"
    "ICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0IHNodXQg"
    "ZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZl"
    "bnQpIC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAgICAgIyBT"
    "YXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBm"
    "b3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBo"
    "aXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0"
    "b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2Ug"
    "aGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAg"
    "ICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAg"
    "ICAgICAgICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3Qg"
    "TW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0"
    "dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0"
    "cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAg"
    "ICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJv"
    "bGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIs"
    "ICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9m"
    "YXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAg"
    "ICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAg"
    "ICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAg"
    "ICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRk"
    "b3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9z"
    "dGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3RvcCBzY2hlZHVs"
    "ZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5f"
    "c2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0"
    "ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5k"
    "ID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNoZWQuY29u"
    "bmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQu"
    "c3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9u"
    "LnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVy"
    "IG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlz"
    "c2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24g"
    "Zmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9k"
    "aXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3Jp"
    "dGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVz"
    "IHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBs"
    "b2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0"
    "Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawog"
    "ICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJv"
    "b3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFs"
    "b2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9l"
    "YXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2"
    "KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVy"
    "IE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZy"
    "b20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygi"
    "W01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQ"
    "aGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAg"
    "ICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNj"
    "ZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxv"
    "ZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygp"
    "CgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlz"
    "IGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIg"
    "ICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21l"
    "ID0gc2VlZF9kaXIgLyBERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rf"
    "b2s9VHJ1ZSkKCiAgICAgICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1v"
    "cmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAg"
    "ICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZh"
    "Y2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAg"
    "ICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9t"
    "ZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAg"
    "ICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAg"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFfaG9t"
    "ZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiKSwK"
    "ICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0ciht"
    "b3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2Vu"
    "IjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAgICJ0aW1l"
    "em9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAgICAgImh0"
    "dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczov"
    "L3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlz"
    "LmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1"
    "biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9o"
    "b21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNr"
    "KSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2Fybmlu"
    "ZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxk"
    "IG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAg"
    "IGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKU"
    "gCBXcml0ZSBjb25maWcuanNvbiBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyAi"
    "Y29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQog"
    "ICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5k"
    "dW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVz"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gYm9vdHN0"
    "cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJh"
    "cF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4"
    "dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFj"
    "ZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAgICAgICAgICBmYWNl"
    "c19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVl"
    "LCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUo"
    "ZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAg"
    "ICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2Vy"
    "KCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIp"
    "Lm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICB3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRz"
    "dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0"
    "ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIp"
    "CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBh"
    "Y2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxu"
    "IgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAg"
    "ICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3"
    "IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZhbHNlCiAgICAg"
    "ICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6"
    "CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAg"
    "ICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAgICAgc2NfcGF0aCAgICAg"
    "PSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5"
    "cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhl"
    "IjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAg"
    "ICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253"
    "ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1Nj"
    "cmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0"
    "aCkpCiAgICAgICAgICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAg"
    "ICAgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29ya2lu"
    "Z0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0g"
    "ZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAg"
    "ICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAj"
    "IOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVl"
    "biBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgog"
    "ICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVk"
    "LlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAg"
    "ICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi"
    "4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVt"
    "IGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAg"
    "ICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3Nl"
    "LlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFN"
    "RX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRj"
    "dXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAg"
    "UGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9v"
    "dHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRv"
    "dyIpCiAgICB3aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3Jl"
    "YXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIHdpbmRv"
    "dy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBhbmQgc3Rh"
    "cnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhy"
    "ZWFkcyBvciBlbWl0cyBzaWduYWxzIHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAs"
    "IGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9z"
    "Y2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3Rh"
    "cnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "NjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0"
    "YXJ0dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElN"
    "RVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAg"
    "IyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMK"
    "ICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0"
    "YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9z"
    "b3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmds"
    "ZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09ICJf"
    "X21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBw"
    "YXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBhc3MgMyDi"
    "hpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNg=="
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
