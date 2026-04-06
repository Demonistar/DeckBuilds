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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCiMg4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNI"
    "TyBERUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJT04KIyBHZW5lcmF0ZWQgYnkgZGVja19idWls"
    "ZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGluamVjdGVkIGZyb20gREVDS19URU1QTEFURSBoZWFk"
    "ZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAoKCmltcG9ydCBzeXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCBtYXRoCmltcG9ydCB0"
    "aW1lCmltcG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5n"
    "CmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRl"
    "dGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJv"
    "bSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsLCBJdGVyYXRvcgoKIyDilIDilIAgRUFSTFkgQ1JBU0ggTE9H"
    "R0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEhvb2tzIGlu"
    "IGJlZm9yZSBRdCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFMTCBvdXRwdXQgaW5jbHVkaW5n"
    "CiMgQysrIGxldmVsIFF0IG1lc3NhZ2VzLiBXcml0dGVuIHRvIFtEZWNrTmFtZV0vbG9ncy9zdGFydHVw"
    "LmxvZwojIFRoaXMgc3RheXMgYWN0aXZlIGZvciB0aGUgbGlmZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJM"
    "WV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlfTE9HX1BBVEg6IE9wdGlvbmFsW1BhdGhdID0gTm9u"
    "ZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+IE5vbmU6CiAgICB0cyA9IGRhdGV0aW1lLm5vdygp"
    "LnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzotM10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNnfSIKICAg"
    "IF9FQVJMWV9MT0dfTElORVMuYXBwZW5kKGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQog"
    "ICAgaWYgX0VBUkxZX0xPR19QQVRIOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlf"
    "TE9HX1BBVEgub3BlbigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBm"
    "LndyaXRlKGxpbmUgKyAiXG4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBh"
    "c3MKCmRlZiBfaW5pdF9lYXJseV9sb2coYmFzZV9kaXI6IFBhdGgpIC0+IE5vbmU6CiAgICBnbG9iYWwg"
    "X0VBUkxZX0xPR19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIgLyAibG9ncyIKICAgIGxvZ19kaXIu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xPR19QQVRIID0gbG9n"
    "X2RpciAvIGYic3RhcnR1cF97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0u"
    "bG9nIgogICAgIyBGbHVzaCBidWZmZXJlZCBsaW5lcwogICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3Bl"
    "bigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIGxpbmUgaW4gX0VBUkxZX0xP"
    "R19MSU5FUzoKICAgICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKCmRlZiBfaW5zdGFsbF9xdF9t"
    "ZXNzYWdlX2hhbmRsZXIoKSAtPiBOb25lOgogICAgIiIiCiAgICBJbnRlcmNlcHQgQUxMIFF0IG1lc3Nh"
    "Z2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2FybmluZ3MuCiAgICBUaGlzIGNhdGNoZXMgdGhlIFFUaHJl"
    "YWQgZGVzdHJveWVkIG1lc3NhZ2UgYXQgdGhlIHNvdXJjZSBhbmQgbG9ncyBpdAogICAgd2l0aCBhIGZ1"
    "bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cgZXhhY3RseSB3aGljaCB0aHJlYWQgYW5kIHdoZXJlLgogICAg"
    "IiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNz"
    "YWdlSGFuZGxlciwgUXRNc2dUeXBlCiAgICAgICAgaW1wb3J0IHRyYWNlYmFjawoKICAgICAgICBkZWYg"
    "cXRfbWVzc2FnZV9oYW5kbGVyKG1zZ190eXBlLCBjb250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAg"
    "bGV2ZWwgPSB7CiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXREZWJ1Z01zZzogICAgIlFUX0RFQlVH"
    "IiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAg"
    "ICAgICAgICAgICBRdE1zZ1R5cGUuUXRXYXJuaW5nTXNnOiAgIlFUX1dBUk5JTkciLAogICAgICAgICAg"
    "ICAgICAgUXRNc2dUeXBlLlF0Q3JpdGljYWxNc2c6ICJRVF9DUklUSUNBTCIsCiAgICAgICAgICAgICAg"
    "ICBRdE1zZ1R5cGUuUXRGYXRhbE1zZzogICAgIlFUX0ZBVEFMIiwKICAgICAgICAgICAgfS5nZXQobXNn"
    "X3R5cGUsICJRVF9VTktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0gIiIKICAgICAgICAgICAg"
    "aWYgY29udGV4dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmls"
    "ZX06e2NvbnRleHQubGluZX1dIgoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2Nh"
    "dGlvbn0ge21lc3NhZ2V9IikKCiAgICAgICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxv"
    "ZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAgICBpZiAiUVRocmVhZCIgaW4gbWVzc2FnZSBvciAi"
    "dGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBzdGFjayA9ICIiLmpvaW4o"
    "dHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltTVEFD"
    "SyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3RhbGxNZXNzYWdlSGFu"
    "ZGxlcihxdF9tZXNzYWdlX2hhbmRsZXIpCiAgICAgICAgX2Vhcmx5X2xvZygiW0lOSVRdIFF0IG1lc3Nh"
    "Z2UgaGFuZGxlciBpbnN0YWxsZWQiKQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIF9l"
    "YXJseV9sb2coZiJbSU5JVF0gQ291bGQgbm90IGluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyOiB7ZX0i"
    "KQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7REVDS19OQU1FfSBkZWNrIHN0YXJ0aW5nIikKX2Vhcmx5X2xv"
    "ZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNwbGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJs"
    "ZX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFdvcmtpbmcgZGlyZWN0b3J5OiB7b3MuZ2V0Y3dkKCl9IikK"
    "X2Vhcmx5X2xvZyhmIltJTklUXSBTY3JpcHQgbG9jYXRpb246IHtQYXRoKF9fZmlsZV9fKS5yZXNvbHZl"
    "KCl9IikKCiMg4pSA4pSAIE9QVElPTkFMIERFUEVOREVOQ1kgR1VBUkRTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAoKUFNVVElMX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElM"
    "X09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9y"
    "dEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHN1dGlsIEZBSUxFRDoge2V9IikK"
    "Ck5WTUxfT0sgPSBGYWxzZQpncHVfaGFuZGxlID0gTm9uZQp0cnk6CiAgICBpbXBvcnQgd2FybmluZ3MK"
    "ICAgIHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToKICAgICAgICB3YXJuaW5ncy5zaW1wbGVm"
    "aWx0ZXIoImlnbm9yZSIpCiAgICAgICAgaW1wb3J0IHB5bnZtbAogICAgcHludm1sLm52bWxJbml0KCkK"
    "ICAgIGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VHZXRDb3VudCgpCiAgICBpZiBjb3VudCA+IDA6CiAg"
    "ICAgICAgZ3B1X2hhbmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxlQnlJbmRleCgwKQogICAg"
    "ICAgIE5WTUxfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIE9LIOKAlCB7"
    "Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1Q"
    "T1JUXSBweW52bWwgRkFJTEVEOiB7ZX0iKQoKVE9SQ0hfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQg"
    "dG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0"
    "b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9y"
    "Y2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vh"
    "cmx5X2xvZyhmIltJTVBPUlRdIHRvcmNoIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sg"
    "PSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luMzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUK"
    "ICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHdpbjMyY29tIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFz"
    "IGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2luMzJjb20gRkFJTEVEOiB7ZX0iKQoKV0lOU09V"
    "TkRfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luc291bmQKICAgIFdJTlNPVU5EX09LID0gVHJ1"
    "ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1wb3J0RXJyb3Ig"
    "YXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKTog"
    "e2V9IikKClBZR0FNRV9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5t"
    "aXhlci5pbml0KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHB5"
    "Z2FtZSBPSyIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBw"
    "eWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xFX09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZhbHNl"
    "ICAjIGFsaWFzIHVzZWQgYnkgR29vZ2xlIHNlcnZpY2UgY2xhc3NlcwpHT09HTEVfSU1QT1JUX0VSUk9S"
    "ID0gTm9uZQp0cnk6CiAgICBmcm9tIGdvb2dsZS5hdXRoLnRyYW5zcG9ydC5yZXF1ZXN0cyBpbXBvcnQg"
    "UmVxdWVzdCBhcyBHb29nbGVBdXRoUmVxdWVzdAogICAgZnJvbSBnb29nbGUub2F1dGgyLmNyZWRlbnRp"
    "YWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVkZW50aWFscwogICAgZnJvbSBnb29nbGVf"
    "YXV0aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0YWxsZWRBcHBGbG93CiAgICBmcm9tIGdvb2dsZWFw"
    "aWNsaWVudC5kaXNjb3ZlcnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2dsZV9idWlsZAogICAgZnJvbSBnb29n"
    "bGVhcGljbGllbnQuZXJyb3JzIGltcG9ydCBIdHRwRXJyb3IgYXMgR29vZ2xlSHR0cEVycm9yCiAgICBH"
    "T09HTEVfT0sgPSBUcnVlCiAgICBHT09HTEVfQVBJX09LID0gVHJ1ZQpleGNlcHQgSW1wb3J0RXJyb3Ig"
    "YXMgX2U6CiAgICBHT09HTEVfSU1QT1JUX0VSUk9SID0gc3RyKF9lKQogICAgR29vZ2xlSHR0cEVycm9y"
    "ID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVTID0gWwogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMu"
    "Y29tL2F1dGgvY2FsZW5kYXIiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2Fs"
    "ZW5kYXIuZXZlbnRzIiwKICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwK"
    "ICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCl0KR09PR0xFX1ND"
    "T1BFX1JFQVVUSF9NU0cgPSAoCiAgICAiR29vZ2xlIHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3Ig"
    "aW5jb21wYXRpYmxlIHdpdGggcmVxdWVzdGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29u"
    "IGFuZCByZWF1dGhvcml6ZSB3aXRoIHRoZSB1cGRhdGVkIHNjb3BlIGxpc3QuIgopCkRFRkFVTFRfR09P"
    "R0xFX0lBTkFfVElNRVpPTkUgPSAiQW1lcmljYS9DaGljYWdvIgpXSU5ET1dTX1RaX1RPX0lBTkEgPSB7"
    "CiAgICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAiRWFzdGVy"
    "biBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRhcmQg"
    "VGltZSI6ICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAgICJNb3VudGFpbiBTdGFuZGFyZCBUaW1lIjog"
    "IkFtZXJpY2EvRGVudmVyIiwKfQoKCiMg4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZnJvbSBQeVNpZGU2LlF0"
    "V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFpbldpbmRvdywgUVdpZGdldCwgUVZC"
    "b3hMYXlvdXQsIFFIQm94TGF5b3V0LAogICAgUUdyaWRMYXlvdXQsIFFUZXh0RWRpdCwgUUxpbmVFZGl0"
    "LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBRRnJhbWUsCiAgICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdp"
    "ZGdldCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRlclZpZXcsCiAgICBRQWJzdHJhY3RJdGVtVmlldywg"
    "UVN0YWNrZWRXaWRnZXQsIFFUYWJXaWRnZXQsIFFMaXN0V2lkZ2V0LAogICAgUUxpc3RXaWRnZXRJdGVt"
    "LCBRU2l6ZVBvbGljeSwgUUNvbWJvQm94LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3Nh"
    "Z2VCb3gsIFFEYXRlRWRpdCwgUURpYWxvZywgUUZvcm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNw"
    "bGl0dGVyLCBRSW5wdXREaWFsb2csIFFUb29sQnV0dG9uCikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBv"
    "cnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNpemUsIFFQb2ludCwg"
    "UVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQYWlu"
    "dGVyLCBRTGluZWFyR3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQ"
    "YWludGVyUGF0aCwgUVRleHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9u"
    "CikKCiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUgICAgICA9IFVJX1dJTkRPV19U"
    "SVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4wIgpBUFBfRklMRU5BTUUgID0gZiJ7REVDS19OQU1FLmxv"
    "d2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0wNCIKCiMg4pSA4pSAIENPTkZJ"
    "RyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29uIGxpdmVzIG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUu"
    "CiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcuIE5vdGhpbmcgaGFyZGNvZGVkIGJlbG93IHRoaXMg"
    "cG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudApDT05GSUdf"
    "UEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5v"
    "dyB0aGF0IHdlIGtub3cgd2hlcmUgd2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFy"
    "bHlfbG9nKGYiW0lOSVRdIFNDUklQVF9ESVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lO"
    "SVRdIENPTkZJR19QQVRIID0ge0NPTkZJR19QQVRIfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gY29uZmln"
    "Lmpzb24gZXhpc3RzOiB7Q09ORklHX1BBVEguZXhpc3RzKCl9IikKCmRlZiBfZGVmYXVsdF9jb25maWco"
    "KSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBm"
    "aXJzdC1ydW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVy"
    "biB7CiAgICAgICAgImRlY2tfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjog"
    "QVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGlyIjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7CiAg"
    "ICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8IG9sbGFtYSB8IGNsYXVk"
    "ZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAgICMgbG9jYWwgbW9k"
    "ZWwgZm9sZGVyIHBhdGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4g"
    "ImRvbHBoaW4tMi42LTdiIgogICAgICAgICAgICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xh"
    "dWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAgImFwaV90eXBlIjogIiIsICAgICAgICAgICAjICJj"
    "bGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2RlbCI6ICIiLCAgICAgICAgICAjIGUu"
    "Zy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAgICAgICAgImdvb2dsZSI6IHsKICAgICAg"
    "ICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3Jl"
    "ZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJp"
    "Y2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6"
    "Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAg"
    "Imh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0"
    "dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAg"
    "ICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKFNDUklQ"
    "VF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIgLyAi"
    "c291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVz"
    "IiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAg"
    "ICAgICAgICAgICJzbCI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAgICJl"
    "eHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAg"
    "ICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIoU0NS"
    "SVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihTQ1JJUFRfRElS"
    "IC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8gImdv"
    "b2dsZSIpLAogICAgICAgIH0sCiAgICAgICAgInNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9l"
    "bmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiaWRsZV9taW5fbWludXRlcyI6"
    "ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRsZV9tYXhfbWludXRlcyI6ICAgICAgICAgIDMwLAog"
    "ICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4"
    "X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAogICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxl"
    "ZCI6ICAgICAgIFRydWUsCiAgICAgICAgICAgICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1"
    "ZSwKICAgICAgICAgICAgImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAg"
    "ICAgICAiZ29vZ2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxh"
    "eV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUs"
    "CiAgICB9CgpkZWYgbG9hZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4g"
    "UmV0dXJucyBkZWZhdWx0IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdf"
    "UEFUSC5leGlzdHMoKToKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAg"
    "ICAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAg"
    "ICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJl"
    "dHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNhdmVfY29uZmlnKGNmZzogZGljdCkgLT4gTm9uZToK"
    "ICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVu"
    "Y29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywgZiwgaW5kZW50PTIpCgoj"
    "IExvYWQgY29uZmlnIGF0IG1vZHVsZSBsZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9t"
    "IENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJseV9sb2coZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDi"
    "gJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1vZGVsX3R5cGU9e0NGRy5nZXQoJ21v"
    "ZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BBVEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7"
    "CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJzb3VuZHMiOiAgIFNDUklQ"
    "VF9ESVIgLyAic291bmRzIiwKICAgICJtZW1vcmllcyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAog"
    "ICAgInNlc3Npb25zIjogU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJ"
    "UFRfRElSIC8gInNsIiwKICAgICJleHBvcnRzIjogIFNDUklQVF9ESVIgLyAiZXhwb3J0cyIsCiAgICAi"
    "bG9ncyI6ICAgICBTQ1JJUFRfRElSIC8gImxvZ3MiLAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAv"
    "ICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVyc29uYXMiLAogICAgImdv"
    "b2dsZSI6ICAgU0NSSVBUX0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0"
    "aHMoKSAtPiBOb25lOgogICAgIiIiCiAgICBTZWxmLWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMg"
    "bWlzc2luZyByZXF1aXJlZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBu"
    "b3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lz"
    "dHMgY29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgogICAgY2hhbmdlZCA9IEZh"
    "bHNlCiAgICBwYXRocyA9IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVm"
    "YXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdl"
    "dChrZXkpOgogICAgICAgICAgICBwYXRoc1trZXldID0gc3RyKGRlZmF1bHRfcGF0aCkKICAgICAgICAg"
    "ICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVfY2ZnID0gQ0ZHLnNldGRlZmF1bHQoImdvb2dsZSIs"
    "IHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xlIiwgc3RyKF9ERUZBVUxU"
    "X1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0cihnb29nbGVfcm9vdCAvICJn"
    "b29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290"
    "IC8gInRva2VuLmpzb24iKQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50"
    "aWFscyIsICIiKSkuc3RyaXAoKQogICAgdG9rZW5fdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tl"
    "biIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBjcmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVk"
    "c192YWwgYW5kICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIgaW4gY3JlZHNfdmFsKToKICAgICAgICBn"
    "b29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVmYXVsdF9jcmVkcwogICAgICAgIGNoYW5nZWQgPSBU"
    "cnVlCiAgICBpZiBub3QgdG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBkZWZh"
    "dWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNh"
    "dmVfY29uZmlnKENGRykKCmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZl"
    "bmllbmNlOiBnZXQgYSBwYXRoIGZyb20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3"
    "aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBwYXRocyA9IENGRy5nZXQoInBhdGhzIiwg"
    "e30pCiAgICB2YWx1ZSA9IHBhdGhzLmdldChrZXkpCiAgICBpZiB2YWx1ZToKICAgICAgICByZXR1cm4g"
    "UGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZh"
    "bGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAgcmV0dXJuIGZh"
    "bGxiYWNrCiAgICByZXR1cm4gU0NSSVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMo"
    "KQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0"
    "ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1BUlksIENfU0VDT05EQVJZLCBDX0FDQ0VOVCwgQ19C"
    "RywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElNIGFyZSBpbmplY3RlZCBhdCB0"
    "aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIuCiMgRXZlcnl0aGluZyBiZWxvdyBpcyBk"
    "ZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoKIyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBt"
    "YXAgcGVyc29uYSBjb2xvcnMgdG8gbmFtZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRoZSBVSQpDX0NS"
    "SU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAgICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRl"
    "cnMsIGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0gPSBDX1BSSU1BUlkgKyAiODgiICAgIyBkaW0gYWNj"
    "ZW50IGZvciBzdWJ0bGUgYm9yZGVycwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMg"
    "bWFpbiBsYWJlbC90ZXh0L0FJIG91dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkg"
    "KyAiODgiICMgZGltIHNlY29uZGFyeQpDX0dPTERfQlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMg"
    "ZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpDX1NJTFZFUiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMg"
    "c2Vjb25kYXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJTSAgPSBDX1RFWFRfRElN"
    "ICsgIjg4IiAgIyBkaW0gc2Vjb25kYXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENfQkcgICAgICAgICAg"
    "ICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAg"
    "ICAgID0gQ19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAg"
    "ICA9IENfUEFORUwgICAgICAgICAgICAjIHRlcnRpYXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkg"
    "aW5qZWN0ZWQpCkNfQkxPT0QgICAgICAgPSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBzdGF0ZXMs"
    "IGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAgICAgPSAnIzg4NTVjYycgICAgICAgICAgIyBT"
    "WVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBMRV9ESU0gID0gJyMyYTA1MmEnICAgICAg"
    "ICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0YWE2NicgICAg"
    "ICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4"
    "Y2MnICAgICAgICAgICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNhbAoKIyBGb250IGhlbHBlciDigJQg"
    "ZXh0cmFjdHMgcHJpbWFyeSBmb250IG5hbWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlf"
    "Rk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgpLnN0cmlwKCInIikKCiMgRW1vdGlvbiDihpIg"
    "Y29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24gcmVjb3JkIGNoaXBzKQpFTU9USU9OX0NPTE9SUzogZGlj"
    "dFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAg"
    "Q19HT0xELAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2ZWQiOiAgIENfR09MRCwK"
    "ICAgICJoYXBweSI6ICAgICAgQ19HT0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFu"
    "aWNrZWQiOiAgIENfQ1JJTVNPTiwKICAgICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2Nr"
    "ZWQiOiAgICBDX0NSSU1TT04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAgICJjb25jZXJu"
    "ZWQiOiAgIiNjYzY2MjIiLAogICAgInNhZCI6ICAgICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRl"
    "ZCI6ICIjY2M2NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjog"
    "ICBDX1BVUlBMRSwKICAgICJzdXNwaWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENf"
    "UFVSUExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJTFZFUiwKICAgICJhbGVydCI6ICAgICAgQ19TSUxW"
    "RVIsCiAgICAibmV1dHJhbCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09SQVRJVkUgQ09O"
    "U1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlz"
    "IHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5F"
    "UyA9IFVJX1JVTkVTCgojIEZhY2UgaW1hZ2UgbWFwIOKAlCBwcmVmaXggZnJvbSBGQUNFX1BSRUZJWCwg"
    "ZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFjZXMKRkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0g"
    "PSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIsCiAgICAiYWxl"
    "cnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVydC5wbmciLAogICAgImZvY3VzZWQiOiAgICBmIntG"
    "QUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1f"
    "U211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIs"
    "CiAgICAic2FkIjogICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVs"
    "aWV2ZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBm"
    "IntGQUNFX1BSRUZJWH1fSW1wcmVzc2VkLnBuZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJF"
    "RklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxpYXRlZCI6IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlh"
    "dGVkLnBuZyIsCiAgICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNpb3VzLnBuZyIs"
    "CiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0"
    "bW9kZSI6ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBm"
    "IntGQUNFX1BSRUZJWH1fQW5ncnkucG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9"
    "X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBu"
    "ZyIsCiAgICAiaGFwcHkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmciLAogICAgImZsaXJ0"
    "eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZB"
    "Q0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAgZiJ7RkFDRV9QUkVGSVh9"
    "X0VudmlvdXMucG5nIiwKfQoKU0VOVElNRU5UX0xJU1QgPSAoCiAgICAibmV1dHJhbCwgYWxlcnQsIGZv"
    "Y3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZlZCwgaW1wcmVzc2VkLCAiCiAgICAidmlj"
    "dG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNrZWQsIGFuZ3J5LCBwbG90dGluZywgc2hv"
    "Y2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZsdXN0ZXJlZCwgZW52aW91cyIKKQoKIyDilIDilIAg"
    "U1lTVEVNIFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBm"
    "aWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRf"
    "QkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJvdmUgZnJvbSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVj"
    "dGlvbi4KIyBEbyBub3QgcmVkZWZpbmUgaXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBTVFlMRVNIRUVU"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9"
    "IGYiIiIKUU1haW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsK"
    "ICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpR"
    "VGV4dEVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtD"
    "X0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJh"
    "ZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6"
    "IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjoge0Nf"
    "Q1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307"
    "CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAg"
    "IGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAg"
    "Zm9udC1zaXplOiAxM3B4OwogICAgcGFkZGluZzogOHB4IDEycHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7"
    "ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19Q"
    "QU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsK"
    "ICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owog"
    "ICAgZm9udC1zaXplOiAxMnB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHgg"
    "MjBweDsKICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQdXNoQnV0dG9uOmhvdmVyIHt7CiAgICBi"
    "YWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19"
    "ClFQdXNoQnV0dG9uOnByZXNzZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAg"
    "IGJvcmRlci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRv"
    "bjpkaXNhYmxlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19U"
    "RVhUX0RJTX07CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0"
    "aWNhbCB7ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAgIGJvcmRlcjog"
    "bm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2"
    "ZXJ0aWNhbDpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6"
    "OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xsQmFyOjpzdWItbGluZTp2ZXJ0aWNhbCB7ewogICAgaGVp"
    "Z2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6OnBhbmUge3sKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07Cn19ClFUYWJCYXI6OnRhYiB7ewogICAg"
    "YmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07CiAgICBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFt"
    "aWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgbGV0dGVyLXNwYWNp"
    "bmc6IDFweDsKfX0KUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklN"
    "U09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQg"
    "e0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRhYjpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfUEFO"
    "RUx9OwogICAgY29sb3I6IHtDX0dPTERfRElNfTsKfX0KUVRhYmxlV2lkZ2V0IHt7CiAgICBiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OwogICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZhbWls"
    "eToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0Ojpp"
    "dGVtOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjog"
    "e0NfR09MRF9CUklHSFR9Owp9fQpRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDog"
    "e0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T05fRElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXItc3Bh"
    "Y2luZzogMXB4Owp9fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xv"
    "cjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRk"
    "aW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFDb21ib0Jv"
    "eDo6ZHJvcC1kb3duIHt7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0JveCB7ewogICAgY29sb3I6"
    "IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9fQpRU3BsaXR0ZXI6OmhhbmRsZSB7"
    "ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgd2lkdGg6IDJweDsKfX0KIiIiCgoj"
    "IOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgQ3JlYXRlIGFsbCByZXF1aXJlZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAg"
    "Q2FsbGVkIG9uIHN0YXJ0dXAgYmVmb3JlIGFueXRoaW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBs"
    "ZSB0aW1lcy4KICAgIEFsc28gbWlncmF0ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmll"
    "cyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRpcnMgPSBbCiAgICAgICAgY2ZnX3BhdGgo"
    "ImZhY2VzIiksCiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAgIGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpLAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIp"
    "LAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAg"
    "ICAgICBjZmdfcGF0aCgiYmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAogICAg"
    "ICAgIGNmZ19wYXRoKCJnb29nbGUiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0"
    "cyIsCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAgIGQubWtkaXIocGFyZW50cz1UcnVlLCBl"
    "eGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05MIGZpbGVzIGlmIHRoZXkgZG9uJ3Qg"
    "ZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZuYW1lIGlu"
    "ICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAg"
    "ICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIp"
    "OgogICAgICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygp"
    "OgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2Rp"
    "ciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4gKCJzbF9zY2Fucy5qc29ubCIsICJzbF9j"
    "b21tYW5kcy5qc29ubCIpOgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3Qg"
    "ZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIp"
    "CgogICAgc2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25z"
    "X2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAg"
    "IGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNv"
    "ZGluZz0idXRmLTgiKQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAg"
    "ICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShz"
    "dGF0ZV9wYXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBp"
    "ZiBub3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAg"
    "ICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdl"
    "cyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9"
    "MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgIyBMZWdhY3kgbWln"
    "cmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywgbWlncmF0ZSBmaWxl"
    "cwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRo"
    "OiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tf"
    "TkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25f"
    "Y291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRk"
    "b3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAogICAgICAgICJ0b3RhbF9tZXNz"
    "YWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIs"
    "CiAgICB9CiAgICBwYXRoLndyaXRlX3RleHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNv"
    "ZGluZz0idXRmLTgiKQoKZGVmIF9taWdyYXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIK"
    "ICAgIElmIG9sZCBEOlxcQUlcXE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0"
    "ZWN0ZWQsCiAgICBtaWdyYXRlIGZpbGVzIHRvIG5ldyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIK"
    "ICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2ZSB0byBtb2RlbCBwYXRoCiAgICBtb2Rl"
    "bF9wYXRoID0gUGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYgbm90IG1vZGVs"
    "X3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFy"
    "ZW50IC8gZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToK"
    "ICAgICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJtZW1v"
    "cmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZW1vcmllcy5qc29u"
    "bCIpLAogICAgICAgIChvbGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAgICAgY2ZnX3Bh"
    "dGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFz"
    "a3MuanNvbmwiLCAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25s"
    "IiksCiAgICAgICAgKG9sZF9yb290IC8gInN0YXRlLmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gImluZGV4Lmpz"
    "b24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJpbmRleC5qc29uIiksCiAg"
    "ICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wi"
    "KSAvICJzbF9zY2Fucy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29u"
    "bCIsICAgICAgICAgY2ZnX3BhdGgoInNsIikgLyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAo"
    "b2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsi"
    "dG9rZW4iXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJjb25maWciIC8gImdvb2dsZV9jcmVkZW50aWFs"
    "cy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBQ"
    "YXRoKENGR1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291"
    "bmRzIiAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVG"
    "SVh9X2FsZXJ0LndhdiIpLAogICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAg"
    "ICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUp"
    "CiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIo"
    "c3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2ZhY2VzID0gb2xkX3Jv"
    "b3QgLyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBjZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2Zh"
    "Y2VzLmV4aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2VzLmdsb2IoIioucG5nIik6CiAg"
    "ICAgICAgICAgIGRzdCA9IG5ld19mYWNlcyAvIGltZy5uYW1lCiAgICAgICAgICAgIGlmIG5vdCBkc3Qu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHNo"
    "dXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoaW1nKSwgc3RyKGRzdCkpCiAg"
    "ICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg"
    "4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRh"
    "dGV0aW1lLm5vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9p"
    "c28odmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgaWYgbm90IHZhbHVlOgogICAg"
    "ICAgIHJldHVybiBOb25lCiAgICB2YWx1ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBp"
    "ZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zv"
    "cm1hdCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAgICAgICAgcmV0dXJu"
    "IGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "IHJldHVybiBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBsZV0gPSBz"
    "ZXQoKQoKCmRlZiBfbG9jYWxfdHppbmZvKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkuYXN0aW1l"
    "em9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICBy"
    "ZXR1cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkKCgpkZWYgbm9ybWFsaXplX2RhdGV0aW1l"
    "X2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICBpZiBkdF92YWx1ZSBp"
    "cyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3QgaXNpbnN0YW5jZShkdF92YWx1ZSwg"
    "ZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9sb2NhbF90emluZm8o"
    "KQogICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5vbmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3Zh"
    "bHVlLnJlcGxhY2UodHppbmZvPWxvY2FsX3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0"
    "KQogICAgICAgIGlmIGtleSBub3QgaW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAg"
    "ICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1h"
    "bGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5l"
    "cmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JN"
    "QUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3Jt"
    "YWxpemVkID0gZHRfdmFsdWUuYXN0aW1lem9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIo"
    "ZHRfdmFsdWUudHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIsIGNvbnRleHQsIGR0X3R6X25hbWUpCiAg"
    "ICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBhbmQgZHRfdHpfbmFt"
    "ZSBub3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAg"
    "ICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBm"
    "cm9tIHtkdF90el9uYW1lfSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwn"
    "fSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xP"
    "R0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2VfaXNvX2Zvcl9jb21w"
    "YXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1l"
    "X2Zvcl9jb21wYXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tf"
    "ZHVlX3NvcnRfa2V5KHRhc2s6IGRpY3QpOgogICAgZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0"
    "YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9yICh0YXNrIG9yIHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0"
    "PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICgxLCBkYXRldGlt"
    "ZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkKICAgIHJldHVybiAoMCwgZHVlLmFzdGlt"
    "ZXpvbmUodGltZXpvbmUudXRjKSwgKCh0YXNrIG9yIHt9KS5nZXQoInRleHQiKSBvciAiIikubG93ZXIo"
    "KSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9uKHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9"
    "IG1heCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCByZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQog"
    "ICAgaG91cnMsIHJlbSA9IGRpdm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9k"
    "KHJlbSwgNjApCiAgICBwYXJ0cyA9IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5"
    "c31kIikKICAgIGlmIGhvdXJzOiAgIHBhcnRzLmFwcGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0"
    "ZXM6IHBhcnRzLmFwcGVuZChmInttaW51dGVzfW0iKQogICAgaWYgbm90IHBhcnRzOiBwYXJ0cy5hcHBl"
    "bmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10pCgojIOKUgOKUgCBNT09O"
    "IFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbiBtYXRoIOKAlCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVz"
    "IGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01PT04gPSBkYXRlKDIwMDAsIDEsIDYpCl9MVU5BUl9D"
    "WUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAtPiB0dXBsZVtmbG9hdCwg"
    "c3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2ZyYWN0aW9uLCBwaGFzZV9uYW1l"
    "LCBpbGx1bWluYXRpb25fcGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9uOiAwLjAgPSBuZXcgbW9vbiwgMC41"
    "ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcgbW9vbiBhZ2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDi"
    "gJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwgcGhhc2UuCiAgICAiIiIKICAgIGRheXMgID0g"
    "KGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9PTikuZGF5cwogICAgY3ljbGUgPSBkYXlzICUgX0xV"
    "TkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8"
    "IDEuODU6ICAgbmFtZSA9ICJORVcgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAi"
    "V0FYSU5HIENSRVNDRU5UIgogICAgZWxpZiBjeWNsZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFS"
    "VEVSIgogICAgZWxpZiBjeWNsZSA8IDE0Ljc3OiAgbmFtZSA9ICJXQVhJTkcgR0lCQk9VUyIKICAgIGVs"
    "aWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBjeWNsZSA8IDIyLjE1"
    "OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAi"
    "TEFTVCBRVUFSVEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NF"
    "TlQiCgogICAgIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwg"
    "bW9vbgogICAgaWxsdW1pbmF0aW9uID0gKDEgLSBtYXRoLmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkg"
    "LyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkKCl9T"
    "VU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25lCl9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01J"
    "TjogT3B0aW9uYWxbaW50XSA9IE5vbmUKX1NVTl9DQUNIRV9USU1FUzogdHVwbGVbc3RyLCBzdHJdID0g"
    "KCIwNjowMCIsICIxODozMCIpCgpkZWYgX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0dXBs"
    "ZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNvbHZlIGxhdGl0dWRlL2xvbmdpdHVkZSBmcm9t"
    "IHJ1bnRpbWUgY29uZmlnIHdoZW4gYXZhaWxhYmxlLgogICAgRmFsbHMgYmFjayB0byB0aW1lem9uZS1k"
    "ZXJpdmVkIGNvYXJzZSBkZWZhdWx0cy4KICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9u"
    "ZQogICAgdHJ5OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNp"
    "bnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgICAgICBmb3Iga2V5IGluICgibGF0aXR1ZGUiLCAi"
    "bGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxhdCA9"
    "IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgICAgIGZvciBrZXkg"
    "aW4gKCJsb25naXR1ZGUiLCAibG9uIiwgImxuZyIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGlu"
    "Z3M6CiAgICAgICAgICAgICAgICBsb24gPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgbGF0ID0gTm9uZQogICAgICAgIGxv"
    "biA9IE5vbmUKCiAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHR6"
    "X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkKICAgIHR6X29mZnNl"
    "dF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKCiAgICBpZiBsb24gaXMg"
    "Tm9uZToKICAgICAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIHR6X29mZnNldF9ob3VycyAq"
    "IDE1LjApKQoKICAgIGlmIGxhdCBpcyBOb25lOgogICAgICAgIHR6X25hbWUgPSBzdHIobm93X2xvY2Fs"
    "LnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50ID0gYW55KHRva2VuIGluIHR6X25hbWUgZm9y"
    "IHRva2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lmaWMvQXVja2xhbmQiLCAiQW1lcmljYS9TYW50aWFn"
    "byIpKQogICAgICAgIGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0g"
    "bWF4KC02Ni4wLCBtaW4oNjYuMCwgbGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwg"
    "bG9uKSkKICAgIHJldHVybiBsYXQsIGxvbgoKZGVmIF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9j"
    "YWxfZGF5OiBkYXRlLCBsYXRpdHVkZTogZmxvYXQsIGxvbmdpdHVkZTogZmxvYXQsIHN1bnJpc2U6IGJv"
    "b2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEtc3R5bGUgc3VucmlzZS9zdW5zZXQgc29s"
    "dmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJvbSBtaWRuaWdodC4iIiIKICAgIG4gPSBsb2NhbF9k"
    "YXkudGltZXR1cGxlKCkudG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0"
    "ID0gbiArICgoNiAtIGxuZ19ob3VyKSAvIDI0LjApIGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxu"
    "Z19ob3VyKSAvIDI0LjApCgogICAgTSA9ICgwLjk4NTYgKiB0KSAtIDMuMjg5CiAgICBMID0gTSArICgx"
    "LjkxNiAqIG1hdGguc2luKG1hdGgucmFkaWFucyhNKSkpICsgKDAuMDIwICogbWF0aC5zaW4obWF0aC5y"
    "YWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9IEwgJSAzNjAuMAoKICAgIFJBID0gbWF0aC5k"
    "ZWdyZWVzKG1hdGguYXRhbigwLjkxNzY0ICogbWF0aC50YW4obWF0aC5yYWRpYW5zKEwpKSkpCiAgICBS"
    "QSA9IFJBICUgMzYwLjAKICAgIExfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihMIC8gOTAuMCkpICogOTAu"
    "MAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihSQSAvIDkwLjApKSAqIDkwLjAKICAgIFJBID0g"
    "KFJBICsgKExfcXVhZHJhbnQgLSBSQV9xdWFkcmFudCkpIC8gMTUuMAoKICAgIHNpbl9kZWMgPSAwLjM5"
    "NzgyICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGgu"
    "YXNpbihzaW5fZGVjKSkKCiAgICB6ZW5pdGggPSA5MC44MzMKICAgIGNvc19oID0gKG1hdGguY29zKG1h"
    "dGgucmFkaWFucyh6ZW5pdGgpKSAtIChzaW5fZGVjICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKGxhdGl0"
    "dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpCiAgICBp"
    "ZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBpZiBz"
    "dW5yaXNlOgogICAgICAgIEggPSAzNjAuMCAtIG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQog"
    "ICAgZWxzZToKICAgICAgICBIID0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89"
    "IDE1LjAKCiAgICBUID0gSCArIFJBIC0gKDAuMDY1NzEgKiB0KSAtIDYuNjIyCiAgICBVVCA9IChUIC0g"
    "bG5nX2hvdXIpICUgMjQuMAoKICAgIGxvY2FsX29mZnNldF9ob3VycyA9IChkYXRldGltZS5ub3coKS5h"
    "c3RpbWV6b25lKCkudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLyAz"
    "NjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBsb2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAg"
    "cmV0dXJuIGxvY2FsX2hvdXIgKiA2MC4wCgpkZWYgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKG1pbnV0"
    "ZXNfZnJvbV9taWRuaWdodDogT3B0aW9uYWxbZmxvYXRdKSAtPiBzdHI6CiAgICBpZiBtaW51dGVzX2Zy"
    "b21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1cm4gIi0tOi0tIgogICAgbWlucyA9IGludChy"
    "b3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAlICgyNCAqIDYwKQogICAgaGgsIG1tID0gZGl2bW9k"
    "KG1pbnMsIDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRl"
    "PW1tLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3Vu"
    "X3RpbWVzKCkgLT4gdHVwbGVbc3RyLCBzdHJdOgogICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJp"
    "c2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBkYXRlICsgdGltZXpvbmUgYW5kIG9wdGlvbmFsCiAgICBydW50"
    "aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2YWlsYWJsZS4KICAgIENhY2hlZCBwZXIg"
    "bG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0LgogICAgIiIiCiAgICBnbG9iYWwgX1NVTl9DQUNI"
    "RV9EQVRFLCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3df"
    "bG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRh"
    "dGUoKQogICAgdHpfb2Zmc2V0X21pbiA9IGludCgobm93X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVk"
    "ZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FDSEVfREFURSA9PSB0"
    "b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID09IHR6X29mZnNldF9taW46CiAgICAgICAg"
    "cmV0dXJuIF9TVU5fQ0FDSEVfVElNRVMKCiAgICB0cnk6CiAgICAgICAgbGF0LCBsb24gPSBfcmVzb2x2"
    "ZV9zb2xhcl9jb29yZGluYXRlcygpCiAgICAgICAgc3VucmlzZV9taW4gPSBfY2FsY19zb2xhcl9ldmVu"
    "dF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1UcnVlKQogICAgICAgIHN1bnNldF9taW4g"
    "PSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1GYWxzZSkK"
    "ICAgICAgICBpZiBzdW5yaXNlX21pbiBpcyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAg"
    "ICAgICAgcmFpc2UgVmFsdWVFcnJvcigiU29sYXIgZXZlbnQgdW5hdmFpbGFibGUgZm9yIHJlc29sdmVk"
    "IGNvb3JkaW5hdGVzIikKICAgICAgICB0aW1lcyA9IChfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3Vu"
    "cmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3Vuc2V0X21pbikpCiAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIxODozMCIpCgogICAgX1NVTl9DQUNI"
    "RV9EQVRFID0gdG9kYXkKICAgIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9IHR6X29mZnNldF9taW4K"
    "ICAgIF9TVU5fQ0FDSEVfVElNRVMgPSB0aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBWQU1Q"
    "SVJFIFNUQVRFIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBUaW1lLW9mLWRheSBiZWhhdmlvcmFsIHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19F"
    "TkFCTEVEPVRydWUuCiMgSW5qZWN0ZWQgaW50byBzeXN0ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRp"
    "b24gY2FsbC4KClZBTVBJUkVfU1RBVEVTOiBkaWN0W3N0ciwgZGljdF0gPSB7CiAgICAiV0lUQ0hJTkcg"
    "SE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBv"
    "d2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjogICAgIHsiaG91cnMiOiB7MSwyLDN9LCAgICAgICAg"
    "ImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5H"
    "Ijp7ImhvdXJzIjogezQsNX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6"
    "IDAuN30sCiAgICAiRE9STUFOVCI6ICAgICAgICB7ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xv"
    "ciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuMn0sCiAgICAiUkVTVExFU1MgU0xFRVAiOiB7Imhv"
    "dXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuM30s"
    "CiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJzIjogezE2LDE3fSwgICAgICAgICJjb2xvciI6IENf"
    "R09MRF9ESU0sICAgICJwb3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7ImhvdXJzIjog"
    "ezE4LDE5LDIwLDIxfSwgICJjb2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAi"
    "SFVOVElORyI6ICAgICAgICB7ImhvdXJzIjogezIyLDIzfSwgICAgICAgICJjb2xvciI6IENfQ1JJTVNP"
    "TiwgICAgICJwb3dlciI6IDEuMH0sCn0KCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgpIC0+IHN0cjoKICAg"
    "ICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91"
    "ci4iIiIKICAgIGggPSBkYXRldGltZS5ub3coKS5ob3VyCiAgICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBp"
    "biBWQU1QSVJFX1NUQVRFUy5pdGVtcygpOgogICAgICAgIGlmIGggaW4gZGF0YVsiaG91cnMiXToKICAg"
    "ICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJldHVybiAiRE9STUFOVCIKCmRlZiBnZXRfdmFt"
    "cGlyZV9zdGF0ZV9jb2xvcihzdGF0ZTogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gVkFNUElSRV9TVEFU"
    "RVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9n"
    "cmVldGluZ3MoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENISU5H"
    "IEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQg"
    "bm93LiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFNRX0gcmVtYWlucyBmb2N1"
    "c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJ"
    "TkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBhbmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHBy"
    "b21wdC4iLAogICAgICAgICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGEgbG93"
    "LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3BvbnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xF"
    "RVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiByZS1lbmdhZ2UgaW1tZWRp"
    "YXRlbHkuIiwKICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWlu"
    "ZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAg"
    "IGYie0RFQ0tfTkFNRX0gaXMgZnVsbHkgYWN0aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAg"
    "ICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Np"
    "bmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3RhdGVfZ3JlZXRpbmdzX21h"
    "cCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJBSV9TVEFU"
    "RV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92"
    "aWRlZC5rZXlzKCkpID09IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBk"
    "aWN0W3N0ciwgc3RyXSA9IHt9CiAgICAgICAgZm9yIGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6"
    "CiAgICAgICAgICAgIHZhbCA9IHByb3ZpZGVkLmdldChrZXkpCiAgICAgICAgICAgIGlmIG5vdCBpc2lu"
    "c3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4g"
    "X25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAgICAgICAgICAgY2xlYW5ba2V5XSA9ICIgIi5qb2lu"
    "KHZhbC5zdHJpcCgpLnNwbGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICByZXR1cm4gX25ldXRy"
    "YWxfc3RhdGVfZ3JlZXRpbmdzKCkKCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3RyOgog"
    "ICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24gcGhhc2UgY29udGV4dCBzdHJp"
    "bmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5l"
    "cmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJ"
    "X1NUQVRFU19FTkFCTEVEOgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVf"
    "c3RhdGUoKQogICAgcGhhc2UsIG1vb25fbmFtZSwgaWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBu"
    "b3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQoKICAgIHN0YXRlX2ZsYXZvcnMgPSBf"
    "c3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3JzLmdldChzdGF0ZSwg"
    "IiIpCgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4i"
    "CiAgICAgICAgZiJWYW1waXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYiTW9v"
    "bjoge21vb25fbmFtZX0gKHtpbGx1bX0lIGlsbHVtaW5hdGVkKS5cbiIKICAgICAgICBmIlJlc3BvbmQg"
    "YXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5jZSB0aGVzZSBicmFja2V0"
    "cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUHJvY2VkdXJhbCBXQVYg"
    "Z2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5kIHByb2ZpbGVzLgojIE5vIGV4dGVybmFsIGF1"
    "ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBi"
    "dWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJh"
    "Y2sgKHN1cHBvcnRzIFdBViBhbmQgTVAzKS4KCl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUo"
    "ZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0"
    "aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9h"
    "dDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0xLjAKCmRlZiBfc2F3"
    "dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVx"
    "ICogdCkgJSAxLjApIC0gMS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQs"
    "IHNhd19yOiBmbG9hdCwKICAgICAgICAgZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAg"
    "IHJldHVybiAoc2luZV9yICogX3NpbmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzcXVhcmVfciAqIF9z"
    "cXVhcmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAqIF9zYXd0b290aChmcmVxLCB0KSkKCmRl"
    "ZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAogICAgICAgICAgICAgIGF0dGFja19mcmFjOiBm"
    "bG9hdCA9IDAuMDUsCiAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykgLT4gZmxv"
    "YXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVkZSBlbnZlbG9wZS4iIiIKICAgIHBvcyA9IGkgLyBt"
    "YXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRhY2tfZnJhYzoKICAgICAgICByZXR1cm4gcG9zIC8g"
    "YXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMpOgogICAgICAgIHJldHVy"
    "biAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAKCmRlZiBfd3JpdGVfd2F2KHBh"
    "dGg6IFBhdGgsIGF1ZGlvOiBsaXN0W2ludF0pIC0+IE5vbmU6CiAgICBwYXRoLnBhcmVudC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3"
    "IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwgMiwgX1NBTVBMRV9SQVRFLCAwLCAiTk9ORSIs"
    "ICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZvciBzIGluIGF1ZGlvOgogICAgICAgICAgICBmLndy"
    "aXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50"
    "OgogICAgcmV0dXJuIG1heCgtMzI3NjcsIG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBNT1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVz"
    "CiMgVHdvIG5vdGVzOiByb290IOKGkiBtaW5vciB0aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNh"
    "dGhlZHJhbCByZXNvbmFuY2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9h"
    "bGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJlbGwg"
    "4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAg"
    "IFNvdW5kcyBsaWtlIGEgc2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVk"
    "cmFsLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQg"
    "Zmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45KSwgICMgRiM0IOKAlCBkZXNjZW5kcyAobWlu"
    "b3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9y"
    "IGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBs"
    "ZW5ndGgpCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9T"
    "QU1QTEVfUkFURQogICAgICAgICAgICAjIFB1cmUgc2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBz"
    "cXVhcmUvc2F3CiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC43CiAgICAgICAgICAg"
    "ICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZvciByaWNobmVzcwogICAgICAgICAgICB2YWwgKz0gX3Np"
    "bmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4w"
    "LCB0KSAqIDAuMDUKICAgICAgICAgICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGll"
    "cyBzbG93bHkKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0w"
    "LjAxLCByZWxlYXNlX2ZyYWM9MC43KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAq"
    "IGVudiAqIDAuNSkpCiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBm"
    "b3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFw"
    "cGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9S"
    "R0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3JkIHJlc29sdXRpb24KIyBUaHJlZSBu"
    "b3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8OpYW5jZSBiZWdp"
    "bm5pbmcuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwKHBhdGg6"
    "IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2aW5nIHVwd2FyZCDi"
    "gJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5uaW5nLgogICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZp"
    "bmFsIG5vdGUgaGVsZCBhbmQgZmFkZWQpLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoMjIw"
    "LjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYxLjYzLCAwLjI1KSwgICMgQzQgKG1pbm9yIHRoaXJk"
    "KQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBFNCAoZmlmdGgpCiAgICAgICAgKDQ0MC4wLCAwLjgp"
    "LCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChm"
    "cmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBM"
    "RV9SQVRFICogbGVuZ3RoKQogICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAg"
    "ICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNgogICAgICAgICAgICB2YWwgKz0g"
    "X3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAgICAgaWYgaXNfZmluYWw6CiAgICAgICAg"
    "ICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2Vf"
    "ZnJhYz0wLjYpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUo"
    "aiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1"
    "ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40NSkpCiAgICAgICAgaWYgbm90IGlzX2ZpbmFs"
    "OgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNSkpOgogICAg"
    "ICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExFIENISU1FIOKAlCBzaW5nbGUgbG93IGJlbGwKIyBW"
    "ZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxsLiBTaWduYWxzIHVuc29saWNpdGVkIHRy"
    "YW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0"
    "aDogUGF0aCkgLT4gTm9uZToKICAgICIiIlNpbmdsZSBzb2Z0IGxvdyBiZWxsIOKAlCBEMy4gVmVyeSBx"
    "dWlldC4gUHJlc2VuY2UgaW4gdGhlIGRhcmsuIiIiCiAgICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBs"
    "ZW5ndGggPSAxLjIKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlv"
    "ID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZy"
    "ZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tf"
    "ZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZh"
    "bCAqIGVudiAqIDAuMykpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAodGhlIGRldmlsJ3MgaW50ZXJ2YWwpCiMgRGlz"
    "c29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVhbC4KIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAg"
    "ICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIzICsgRjQgcGxheWVkIHNpbXVsdGFuZW91c2x5"
    "LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2EnLiBCcmllZiBhbmQgaGFyc2ggY29tcGFyZWQgdG8g"
    "aGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVx"
    "X2IgPSAzNDkuMjMgICMgRjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBs"
    "ZW5ndGggPSAwLjQKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlv"
    "ID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFU"
    "RQogICAgICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQgY3JlYXRlcyBkaXNz"
    "b25hbmNlCiAgICAgICAgdmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAg"
    "ICBfc3F1YXJlKGZyZXFfYiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAy"
    "LjAsIHQpICogMC4xKQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9"
    "MC4wMiwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVu"
    "diAqIDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBN"
    "T1JHQU5OQSBTSFVURE9XTiDigJQgZGVzY2VuZGluZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ug"
    "b2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRyYXdzLgojIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24ocGF0aDogUGF0aCkgLT4gTm9uZToK"
    "ICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKGkiBDNCDihpIgQTMuIFByZXNlbmNlIHdpdGhkcmF3"
    "aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAgMC4zKSwgICAj"
    "IEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAj"
    "IEM0CiAgICAgICAgKDIyMC4wLCAgMC44KSwgICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBd"
    "CiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVz"
    "KToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGog"
    "aW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAg"
    "ICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFj"
    "a19mcmFjPTAuMDMsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlm"
    "IGkgPT0gbGVuKG5vdGVzKS0xIGVsc2UgMC4zKQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1w"
    "KHZhbCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAq"
    "IDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1"
    "ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdldF9zb3VuZF9wYXRoKG5hbWU6IHN0cikgLT4g"
    "UGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X3tuYW1l"
    "fS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6CiAgICAiIiJHZW5lcmF0ZSBhbnkg"
    "bWlzc2luZyBzb3VuZCBXQVYgZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAg"
    "ICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBu"
    "YW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVwIjogIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAs"
    "CiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZSwKICAgICAgICAiZXJyb3Ii"
    "OiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5lcmF0ZV9t"
    "b3JnYW5uYV9zaHV0ZG93biwKICAgIH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5p"
    "dGVtcygpOgogICAgICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBw"
    "YXRoLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBnZW5fZm4ocGF0aCkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJb"
    "U09VTkRdW1dBUk5dIEZhaWxlZCB0byBnZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3Vu"
    "ZChuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAiIiIKICAgIFBsYXkgYSBuYW1lZCBzb3VuZCBub24tYmxv"
    "Y2tpbmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIgZmlyc3QgKGNyb3NzLXBsYXRmb3JtLCBXQVYgKyBN"
    "UDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgogICAgRmFsbHMgYmFjayB0"
    "byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBub3QgQ0ZH"
    "WyJzZXR0aW5ncyJdLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAg"
    "cGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICByZXR1cm4KCiAgICBpZiBQWUdBTUVfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzb3VuZCA9"
    "IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAgICAgICAgICAgIHNvdW5kLnBsYXkoKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5QbGF5U291"
    "bmQoc3RyKHBhdGgpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJ"
    "TEVOQU1FIHwgd2luc291bmQuU05EX0FTWU5DKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgdHJ5OgogICAgICAgIFFBcHBsaWNhdGlv"
    "bi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKIyDilIDilIAgREVTS1RP"
    "UCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRl"
    "X2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBib29sOgogICAgIiIiCiAgICBDcmVhdGUgYSBkZXNrdG9wIHNo"
    "b3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgogICAgUmV0dXJucyBU"
    "cnVlIG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgog"
    "ICAgICAgIHJldHVybiBGYWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAv"
    "ICJEZXNrdG9wIgogICAgICAgIHNob3J0Y3V0X3BhdGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5s"
    "bmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUgYXMgcHl0aG9uIGJ1dCBubyBjb25zb2xlIHdpbmRv"
    "dwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgIGlmIHB5dGhvbncu"
    "bmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncu"
    "cGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAg"
    "ICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0g"
    "UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxsID0gd2luMzJjb20uY2xpZW50LkRp"
    "c3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICBzYyA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0"
    "cihzaG9ydGN1dF9wYXRoKSkKICAgICAgICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQog"
    "ICAgICAgIHNjLkFyZ3VtZW50cyAgICAgID0gZicie2RlY2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtp"
    "bmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRoLnBhcmVudCkKICAgICAgICBzYy5EZXNjcmlwdGlvbiAg"
    "ICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKCiAgICAgICAgIyBVc2UgbmV1dHJhbCBmYWNl"
    "IGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikg"
    "LyBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygp"
    "OgogICAgICAgICAgICAjIFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCU"
    "IHNraXAgaWNvbiBpZiBubyAuaWNvCiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAg"
    "ICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICBwcmludChm"
    "IltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKICAgICAgICBy"
    "ZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHJlYWRfanNvbmwocGF0aDogUGF0"
    "aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1cm5zIGxpc3Qgb2Yg"
    "ZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgcmV0dXJuIFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgi"
    "KS5zdHJpcCgpCiAgICBpZiBub3QgcmF3OgogICAgICAgIHJldHVybiBbXQogICAgaWYgcmF3LnN0YXJ0"
    "c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRhdGEgPSBqc29uLmxvYWRzKHJhdykK"
    "ICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEgaWYgaXNpbnN0YW5jZSh4LCBkaWN0KV0K"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAg"
    "ICBmb3IgbGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkK"
    "ICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShvYmos"
    "IGRpY3QpOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pz"
    "b25sKHBhdGg6IFBhdGgsIG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVuZCBvbmUgcmVjb3Jk"
    "IHRvIGEgSlNPTkwgZmlsZS4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhp"
    "c3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoK"
    "ICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikK"
    "CmRlZiB3cml0ZV9qc29ubChwYXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgog"
    "ICAgIiIiT3ZlcndyaXRlIGEgSlNPTkwgZmlsZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIiIgogICAg"
    "cGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRo"
    "Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZvciByIGluIHJlY29yZHM6"
    "CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxu"
    "IikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0aGUiLCJhbmQiLCJ0aGF0Iiwid2l0aCIsImhhdmUi"
    "LCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwid2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndv"
    "dWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQi"
    "LCJsaWtlIiwiYmVjYXVzZSIsIndoaWxlIiwiY291bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJi"
    "ZWVuIiwKICAgICJiZWluZyIsImRvZXMiLCJkaWQiLCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIs"
    "Im9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4iLCJhbHNvIiwic29tZSIsIm1vcmUiLCJsZXNz"
    "Iiwib25seSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2FpbiIsInZlcnkiLCJt"
    "dWNoIiwicmVhbGx5IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxs"
    "IiwidG9sZCIsImlkZWEiLCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0"
    "YW50IiwKfQoKZGVmIGV4dHJhY3Rfa2V5d29yZHModGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+"
    "IGxpc3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2VyKCkuc3RyaXAoIiAuLCE/OzonXCIoKVtde30i"
    "KSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQoKSwgW10KICAgIGZv"
    "ciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JEUyBvciB0"
    "LmlzZGlnaXQoKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgog"
    "ICAgICAgICAgICBzZWVuLmFkZCh0KQogICAgICAgICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAg"
    "aWYgbGVuKHJlc3VsdCkgPj0gbGltaXQ6CiAgICAgICAgICAgIGJyZWFrCiAgICByZXR1cm4gcmVzdWx0"
    "CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0OiBzdHIsIGFzc2lzdGFudF90ZXh0OiBzdHIg"
    "PSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkubG93"
    "ZXIoKQogICAgaWYgImRyZWFtIiBpbiB0OiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4g"
    "ImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIs"
    "ImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiZml4"
    "ZWQiLCJyZXNvbHZlZCIsInNvbHV0aW9uIiwid29ya2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJy"
    "ZXNvbHV0aW9uIgogICAgICAgIHJldHVybiAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGlu"
    "ICgicmVtaW5kIiwidGltZXIiLCJhbGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgog"
    "ICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImlkZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUi"
    "LCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRlYSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHgg"
    "aW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIpKToKICAgICAgICBy"
    "ZXR1cm4gInByZWZlcmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1Mg"
    "MSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lkZ2V0LCBN"
    "b29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1w"
    "aXJlU3RhdGVTdHJpcCwgQ29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1Mg"
    "MjogV0lER0VUIENMQVNTRVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRo"
    "ZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRlZmluZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAg"
    "ICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGggbGFiZWwgYW5kIHZhbHVlCiMgICBEcml2ZVdp"
    "ZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdCKQojICAgU3BoZXJl"
    "V2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29u"
    "V2lkZ2V0ICAgICAgICAgICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVt"
    "b3Rpb25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAg"
    "IE1pcnJvcldpZGdldCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkgKHRoZSBNaXJyb3IpCiMg"
    "ICBWYW1waXJlU3RhdGVTdHJpcCAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVz"
    "IGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNl"
    "IHRvZ2dsZSB0byBhbnkgd2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFs"
    "bCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgR2F1Z2VX"
    "aWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBn"
    "b3RoaWMgc3R5bGluZy4KICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3At"
    "cmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAgIENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NS"
    "SU1TT04g4oaSIENfQkxPT0QgYXMgdmFsdWUgYXBwcm9hY2hlcyBtYXguCiAgICBTaG93cyAnTi9BJyB3"
    "aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAg"
    "c2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1h"
    "eF92YWw6IGZsb2F0ID0gMTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBw"
    "YXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBz"
    "ZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0gdW5pdAogICAgICAgIHNl"
    "bGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAg"
    "c2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNl"
    "bGYuX2F2YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQog"
    "ICAgICAgIHNlbGYuc2V0TWF4aW11bUhlaWdodCg3MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFs"
    "dWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBzZWxmLm1heF92YWwp"
    "CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYgbm90IGF2YWlsYWJs"
    "ZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5Ogog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlzcGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAgICAgICAgc2VsZi51cGRh"
    "dGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2"
    "YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxm"
    "LnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "cCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhp"
    "bnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkK"
    "CiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3Io"
    "Q19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVj"
    "dCgwLCAwLCB3IC0gMSwgaCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29s"
    "b3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQu"
    "V2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQoNiwgMTQsIHNlbGYubGFiZWwpCgogICAgICAg"
    "ICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBzZWxmLl9hdmFpbGFi"
    "bGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMCwg"
    "UUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncg"
    "PSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9kaXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAt"
    "IHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBiYXIKICAgICAgICBiYXJf"
    "eSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAg"
    "IHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAu"
    "c2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cg"
    "LSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNlbGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFs"
    "ID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5tYXhfdmFsCiAgICAgICAg"
    "ICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAgIyBD"
    "b2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZy"
    "YWMgPiAwLjg1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4g"
    "MC42NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBn"
    "cmFkID0gUUxpbmVhckdyYWRpZW50KDcsIGJhcl95ICsgMSwgNyArIGZpbGxfdywgYmFyX3kgKyAxKQog"
    "ICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkp"
    "CiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAg"
    "ICAgcC5maWxsUmVjdCg3LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAg"
    "ICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChR"
    "V2lkZ2V0KToKICAgICIiIgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVy"
    "LCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAgIEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2"
    "ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZHJpdmVzOiBsaXN0"
    "W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5f"
    "cmVmcmVzaCgpCgogICAgZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJp"
    "dmVzID0gW10KICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGluIHBzdXRpbC5kaXNrX3BhcnRpdGlvbnMoYWxsPUZh"
    "bHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRp"
    "bC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2"
    "ZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJz"
    "dHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAgICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVz"
    "YWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsIjogIHVzYWdl"
    "LnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBl"
    "cmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwog"
    "ICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVt"
    "SGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50"
    "KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAu"
    "c2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBo"
    "ID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBo"
    "LCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qgc2VsZi5fZHJpdmVzOgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNL"
    "X0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5h"
    "dmFpbGFibGUiKQogICAgICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBy"
    "b3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAgICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAg"
    "ICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIiXQogICAgICAgICAgICB1c2VkICAgPSBkcnZbInVz"
    "ZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0g"
    "ZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRl"
    "cn0gIHt1c2VkOi4xZn0ve3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENf"
    "R09MRCkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdo"
    "dC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxhYmVsKQoKICAgICAgICAg"
    "ICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95ID0geSArIDE1CiAg"
    "ICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBw"
    "LmZpbGxSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gs"
    "IGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBp"
    "bnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBw"
    "Y3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAu"
    "NzUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3Jh"
    "ZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEsIGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kp"
    "CiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTUw"
    "KSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAg"
    "ICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3Jh"
    "ZCkKCiAgICAgICAgICAgIHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNo"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiQ2FsbCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZl"
    "IHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKCiMg4pSA4pSAIFNQSEVSRSBXSURHRVQg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBn"
    "YXVnZSDigJQgdXNlZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5BIChWUkFNKS4KICAgIEZp"
    "bGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAg"
    "ICAgY29sb3JfZnVsbDogc3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50"
    "PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5s"
    "YWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9IGNvbG9yX2Z1bGwKICAg"
    "ICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAg"
    "ID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAg"
    "ICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0"
    "aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBib29sID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9m"
    "aWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlvbikpCiAgICAgICAgc2VsZi5fYXZhaWxh"
    "YmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0"
    "UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0g"
    "c2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8g"
    "MiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAyMCkgLy8gMiArIDQKCiAg"
    "ICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4"
    "IC0gciArIDMsIGN5IC0gciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAo"
    "ZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAg"
    "ICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0g"
    "ciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAg"
    "IGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNs"
    "ZV9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShm"
    "bG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAgICAgICAgICAgZmlsbF90b3BfeSA9IGN5"
    "ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20gUHlTaWRlNi5RdENvcmUg"
    "aW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3Rv"
    "cF95LCByICogMiwgY3kgKyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBh"
    "aW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9wYXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAg"
    "ICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9wYXRoKQoKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9y"
    "KHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAg"
    "IyBHbGFzc3kgc2hpbmUKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAg"
    "ZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kgLSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAg"
    "ICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgNTUp"
    "KQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAg"
    "ICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAj"
    "IE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBw"
    "LnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAgICAgICBwLmRyYXdFbGxp"
    "cHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9BIG92ZXJsYXkKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19U"
    "RVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAg"
    "ICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAg"
    "ICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4dCkgLy8gMiwgY3kgKyA0"
    "LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFiZWxfdGV4dCA9IChz"
    "ZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntz"
    "ZWxmLmxhYmVsfSIpCiAgICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIg"
    "aWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29s"
    "b3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0"
    "LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpv"
    "bnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAt"
    "IDEwLCBsYWJlbF90ZXh0KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4o"
    "UUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3"
    "KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHB3ID0gZm0yLmhv"
    "cml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8g"
    "MiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXduIG1vb24g"
    "b3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRo"
    "ZXJuIGhlbWlzcGhlcmUsIHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1"
    "bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24gbGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5l"
    "dyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0CgogICAgVGhlIHNoYWRvd19z"
    "aWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAg"
    "ICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2Uu"
    "CiAgICAiIiIKCiAgICAjIOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dh"
    "cmRzIGR1cmluZyB0ZXN0aW5nCiAgICBNT09OX1NIQURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAgID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGws"
    "IDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxm"
    "Ll9pbGx1bWluYXRpb24gPSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0g"
    "IjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9z"
    "dW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg4MCwgMTEwKQogICAg"
    "ICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1t"
    "ZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3Vu"
    "X2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwg"
    "c3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAg"
    "ICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1l"
    "Lm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9u"
    "IG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVw"
    "ZGF0ZSgpIGRpcmVjdGx5IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIu"
    "c2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1f"
    "ZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdl"
    "dF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5k"
    "YXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5f"
    "ZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQo"
    "c2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGgg"
    "PSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAv"
    "LyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoK"
    "ICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xv"
    "cigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUl9ESU0pLCAx"
    "KSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4aW5n"
    "ID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2Ug"
    "KG1vb24gc3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAg"
    "ICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChR"
    "Q29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAt"
    "IHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGls"
    "bHVtaW5hdGlvbiBnb2VzIDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hh"
    "ZG93X29mZnNldCBjb250cm9scyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJz"
    "CiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24g"
    "b2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9m"
    "cmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0g"
    "MS4wIC0gaWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBz"
    "aGFkb3cgTEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJ"
    "R0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9udGFs"
    "bHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAgICAgICAg"
    "ICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193YXhpbmcg"
    "PSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAj"
    "IFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zm"
    "c2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiByaWdodCBzaWRl"
    "CiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAgICAgICAgICAgcC5z"
    "ZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9v"
    "biBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAg"
    "bW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAg"
    "ICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFk"
    "ZEVsbGlwc2UoZmxvYXQoc2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xp"
    "cHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJzZWN0ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAg"
    "IHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWls"
    "IChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUg"
    "PSBRUmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGlu"
    "ZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hpbmUuc2V0"
    "Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5zZXRCcnVzaChzaGlu"
    "ZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNl"
    "KGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAu"
    "c2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9y"
    "KENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIs"
    "IHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAgIHAuc2V0UGVuKFFD"
    "b2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQu"
    "V2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5o"
    "b3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1lKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAy"
    "LCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAgICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFn"
    "ZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9O"
    "VCwgNykpCiAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpv"
    "bnRhbEFkdmFuY2UoaWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSAr"
    "IHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAg"
    "ICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAg"
    "ICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMu"
    "aG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwg"
    "aCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9OIEJMT0NLIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rp"
    "b24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNvbG9yLWNvZGVkIGNoaXBzOiDinKYgRU1PVElPTl9O"
    "QU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUg"
    "Ym90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAg"
    "ICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJd"
    "XSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVl"
    "CiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBsYXlvdXQuc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVy"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJv"
    "dHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhC"
    "b3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQog"
    "ICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFM"
    "IFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtD"
    "X0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQog"
    "ICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90"
    "b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJl"
    "bnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQo"
    "bGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dn"
    "bGVfYnRuKQoKICAgICAgICAjIFNjcm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2Vs"
    "Zi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNp"
    "emFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGlj"
    "eSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAg"
    "ICBzZWxmLl9zY3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2No"
    "aXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBz"
    "ZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0"
    "KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVt"
    "V2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhw"
    "YW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2Vs"
    "Zi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBk"
    "ZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAo"
    "ZW1vdGlvbiwgdGltZXN0YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6"
    "c2VsZi5fbWF4X2VudHJpZXNdCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9y"
    "ZWJ1aWxkX2NoaXBzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAo"
    "a2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291"
    "bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAg"
    "ICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVs"
    "ZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAg"
    "ICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAgICAg"
    "ICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3RzfSIpCiAgICAgICAg"
    "ICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZv"
    "bnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIK"
    "ICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAgICAgICAgICAp"
    "CgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigp"
    "CiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgTWlycm9yV2lkZ2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDi"
    "gJQgJ1RoZSBNaXJyb3InLgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5w"
    "bmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8g"
    "ZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQi"
    "CiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFD"
    "RV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBu"
    "ZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBN"
    "aXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRjb2RlZCBs"
    "aXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1h"
    "cHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9UT19FTU9USU9O"
    "OiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAi"
    "Y2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2Zh"
    "Y2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIs"
    "IFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAg"
    "IHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXpl"
    "KDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25D"
    "ZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgz"
    "MDAsIHNlbGYuX3ByZWxvYWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "IiIiCiAgICAgICAgU2NhbiBGYWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBu"
    "ZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5Lgog"
    "ICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2"
    "YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygp"
    "OgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1f"
    "Ki5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAiTW9yZ2FubmFfIiB3"
    "aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNF"
    "X1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIg"
    "PSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoK"
    "ICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAg"
    "ZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQoc3RlbV9sb3dlciwgc3RlbV9sb3dlcikK"
    "CiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAgICAgICBpZiBub3Qg"
    "cHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAg"
    "ICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVu"
    "ZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0"
    "cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgaWYgZmFj"
    "ZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAg"
    "IHByaW50KGYiW01JUlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcg"
    "bmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAg"
    "IGZhY2UgPSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAg"
    "ICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNj"
    "YWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAg"
    "c2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0"
    "UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhUcmFuc2Zvcm1hdGlv"
    "biwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAgICAgIHNlbGYuc2V0"
    "VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNl"
    "bGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNP"
    "Tl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAg"
    "IGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmds"
    "ZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAg"
    "ICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoK"
    "ICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBWYW1waXJlU3RhdGVTdHJpcChR"
    "V2lkZ2V0KToKICAgICIiIgogICAgRnVsbC13aWR0aCBzdGF0dXMgYmFyIHNob3dpbmc6CiAgICAgIFsg"
    "4pymIFZBTVBJUkVfU1RBVEUgIOKAoiAgSEg6TU0gIOKAoiAg4piAIFNVTlJJU0UgIOKYvSBTVU5TRVQg"
    "IOKAoiAgTU9PTiBQSEFTRSAgSUxMVU0lIF0KICAgIEFsd2F5cyB2aXNpYmxlLCBuZXZlciBjb2xsYXBz"
    "ZXMuCiAgICBVcGRhdGVzIGV2ZXJ5IG1pbnV0ZSB2aWEgZXh0ZXJuYWwgUVRpbWVyIGNhbGwgdG8gcmVm"
    "cmVzaCgpLgogICAgQ29sb3ItY29kZWQgYnkgY3VycmVudCB2YW1waXJlIHN0YXRlLgogICAgIiIiCgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAg"
    "ICAgc2VsZi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAg"
    "ICAgICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5v"
    "bmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAgICAgc2VsZi5faWxsdW0g"
    "ICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAgICBzZWxmLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGVm"
    "IF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxm"
    "Ll9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNl"
    "bGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAg"
    "ICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkg"
    "ZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBRVGhyZWFkIGNy"
    "YXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi51cGRhdGUp"
    "CiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgog"
    "ICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRf"
    "dmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gZGF0ZXRpbWUubm93KCkuYXN0"
    "aW1lem9uZSgpLnN0cmZ0aW1lKCIlWCIpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5ub3coKS5hc3Rp"
    "bWV6b25lKCkuZGF0ZSgpCiAgICAgICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAg"
    "ICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgXywgc2VsZi5fbW9vbl9uYW1lLCBzZWxm"
    "Ll9pbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBh"
    "aW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAg"
    "ICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAg"
    "ICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxsUmVjdCgw"
    "LCAwLCB3LCBoLCBRQ29sb3IoQ19CRzIpKQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJl"
    "X3N0YXRlX2NvbG9yKHNlbGYuX3N0YXRlKQogICAgICAgIHRleHQgPSAoCiAgICAgICAgICAgIGYi4pym"
    "ICB7c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBm"
    "IuKYgCB7c2VsZi5fc3VucmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAg"
    "ICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAg"
    "ICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAg"
    "IHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgo"
    "dyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxl"
    "bmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAg"
    "ICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "bGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "IGhlYWRlci5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRu"
    "ID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+"
    "IikKICAgICAgICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xi"
    "bC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRu"
    "IGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVk"
    "V2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsg"
    "Zm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRl"
    "ci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9u"
    "dGhfbGJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBs"
    "YXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldp"
    "ZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNl"
    "bGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2Fs"
    "SGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZp"
    "Z2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5k"
    "LWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT0xE"
    "fTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJs"
    "ZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVj"
    "dGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNvbG9yOntDX1RF"
    "WFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJX"
    "aWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAg"
    "KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2"
    "X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRo"
    "KCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVu"
    "ZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdl"
    "ZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVfbGFiZWwoKQog"
    "ICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICph"
    "cmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRo"
    "ID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0"
    "KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5f"
    "YXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgogICAgICAgIGJhc2Ug"
    "PSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2Vk"
    "ZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXku"
    "c2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0gUVRleHRDaGFy"
    "Rm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAg"
    "ICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBi"
    "YXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVr"
    "LlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChR"
    "dC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2Rh"
    "eVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0"
    "dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldl"
    "ZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigp"
    "CiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2Rh"
    "eSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3Rf"
    "ZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBk"
    "YXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkg"
    "PSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNhdHVy"
    "ZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9E"
    "SU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToK"
    "ICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIp"
    "KQogICAgICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAg"
    "ICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdy"
    "b3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29s"
    "b3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQu"
    "Qm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnRE"
    "YXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9j"
    "ayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQg"
    "dG9nZ2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQp"
    "IOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFi"
    "ZWwuIFRvZ2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAg"
    "ICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGxhYmVsOiBzdHIsIGNvbnRlbnQ6IFFXaWRnZXQsCiAgICAgICAgICAgICAgICAgZXhwYW5kZWQ6"
    "IGJvb2wgPSBUcnVlLCBtaW5fd2lkdGg6IGludCA9IDkwLAogICAgICAgICAgICAgICAgIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRl"
    "ZCAgPSBleHBhbmRlZAogICAgICAgIHNlbGYuX21pbl93aWR0aCA9IG1pbl93aWR0aAogICAgICAgIHNl"
    "bGYuX2NvbnRlbnQgICA9IGNvbnRlbnQKCiAgICAgICAgbWFpbiA9IFFWQm94TGF5b3V0KHNlbGYpCiAg"
    "ICAgICAgbWFpbi5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtYWluLnNldFNw"
    "YWNpbmcoMCkKCiAgICAgICAgIyBIZWFkZXIKICAgICAgICBzZWxmLl9oZWFkZXIgPSBRV2lkZ2V0KCkK"
    "ICAgICAgICBzZWxmLl9oZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faGVhZGVy"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJv"
    "dHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci10b3A6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBobCA9IFFIQm94TGF5"
    "b3V0KHNlbGYuX2hlYWRlcikKICAgICAgICBobC5zZXRDb250ZW50c01hcmdpbnMoNiwgMCwgNCwgMCkK"
    "ICAgICAgICBobC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuX2xibCA9IFFMYWJlbChsYWJlbCkK"
    "ICAgICAgICBzZWxmLl9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9u"
    "ZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2Vs"
    "Zi5fYnRuLnNldEZpeGVkU2l6ZSgxNiwgMTYpCiAgICAgICAgc2VsZi5fYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJTX07"
    "IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRu"
    "LnNldFRleHQoIjwiKQogICAgICAgIHNlbGYuX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xl"
    "KQoKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fbGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9idG4pCgogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYu"
    "X2hlYWRlcikKICAgICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9jb250ZW50KQoKICAgICAgICBzZWxm"
    "Ll9hcHBseV9zdGF0ZSgpCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkK"
    "CiAgICBkZWYgX2FwcGx5X3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY29udGVudC5z"
    "ZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IiBpZiBz"
    "ZWxmLl9leHBhbmRlZCBlbHNlICI+IikKICAgICAgICBpZiBzZWxmLl9leHBhbmRlZDoKICAgICAgICAg"
    "ICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNl"
    "dE1heGltdW1XaWR0aCgxNjc3NzIxNSkgICMgdW5jb25zdHJhaW5lZAogICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICMgQ29sbGFwc2VkOiBqdXN0IHRoZSBoZWFkZXIgc3RyaXAgKGxhYmVsICsgYnV0dG9uKQog"
    "ICAgICAgICAgICBjb2xsYXBzZWRfdyA9IHNlbGYuX2hlYWRlci5zaXplSGludCgpLndpZHRoKCkKICAg"
    "ICAgICAgICAgc2VsZi5zZXRGaXhlZFdpZHRoKG1heCg2MCwgY29sbGFwc2VkX3cpKQogICAgICAgIHNl"
    "bGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAg"
    "ICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFyZW50LmxheW91"
    "dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5l"
    "bChRV2lkZ2V0KToKICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAg"
    "ICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0g"
    "Z2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdu"
    "b3N0aWNzIG9uIHN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFp"
    "bGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBz"
    "ZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYg"
    "c2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVs"
    "KHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAg"
    "ICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xk"
    "OyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0"
    "YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rp"
    "b25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAg"
    "ICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIK"
    "ICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICAgIHNm"
    "ID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4"
    "LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVz"
    "ICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9"
    "IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9"
    "IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90b2tlbnMgID0g"
    "UUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVz"
    "LCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxm"
    "LmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChz"
    "dGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RPUkFHRSIp"
    "KQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVn"
    "ZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgVklUQUwg"
    "RVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5z"
    "ZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAg"
    "IiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdl"
    "dCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdl"
    "dChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdl"
    "X3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA"
    "4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9s"
    "YWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQog"
    "ICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1"
    "Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2Vf"
    "dnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAg"
    "Z3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5h"
    "ZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1"
    "X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhF"
    "QVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBD"
    "IiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2"
    "NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDi"
    "lIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVO"
    "R0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAi"
    "JSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGlt"
    "dW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIp"
    "CgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmlu"
    "ZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVs"
    "eS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNz"
    "IHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBb"
    "XQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRV"
    "bmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRX"
    "QVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAg"
    "ICAgICAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdB"
    "UkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBu"
    "b3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAg"
    "ICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdh"
    "dWdlX3RlbXAuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIu"
    "c2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBH"
    "UFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAg"
    "aW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUo"
    "Z3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAg"
    "ICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1s"
    "IE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "ICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBt"
    "ZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "ICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVn"
    "ZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHlu"
    "dm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAg"
    "ICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAg"
    "ICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1"
    "dGlsLmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNw"
    "dSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1"
    "dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQq"
    "KjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAg"
    "IHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAg"
    "ICAgICBzZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwubnZtbERldmlj"
    "ZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0g"
    "cHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0"
    "ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAg"
    "ICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAgICAgICAgICAgICB2cmFt"
    "X3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9"
    "IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNl"
    "dFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3Zy"
    "YW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1"
    "X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGdw"
    "dV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0lICAiCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAog"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0"
    "ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5v"
    "dCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNr"
    "ID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3Rp"
    "Y2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYu"
    "ZHJpdmVfd2lkZ2V0LnJlZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0"
    "dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIs"
    "IHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pym"
    "IFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVT"
    "U0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lP"
    "Tjoge3Nlc3Npb259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6"
    "IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAg"
    "ICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQ"
    "QVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2Fi"
    "bGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBo"
    "aW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRX"
    "b3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3Jr"
    "ZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0Fk"
    "YXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVu"
    "QUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMg"
    "dG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVt"
    "b3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0"
    "ZWQgdHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlz"
    "IHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcu"
    "IE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQg"
    "anNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5j"
    "bGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFT"
    "RSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "TExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVs"
    "IGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2"
    "ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0"
    "bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJu"
    "IFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMu"
    "YWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAg"
    "ICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmst"
    "YnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2"
    "ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIK"
    "ICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAgICAiIiIKICAg"
    "ICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25l"
    "IHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJv"
    "dW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIiLmpvaW4oc2VsZi5z"
    "dHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVp"
    "bGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAg"
    "ICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2Fs"
    "IG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNv"
    "bnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5z"
    "eXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAg"
    "ICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVu"
    "dCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9z"
    "dGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3RleHQ6CiAg"
    "ICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9l"
    "bmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAg"
    "ICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURB"
    "UFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9y"
    "KExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBs"
    "b2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3Vz"
    "dG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNm"
    "b3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAg"
    "ICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAg"
    "PSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4g"
    "Ym9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJv"
    "bSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAg"
    "ICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAi"
    "dG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZv"
    "ckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9U"
    "b2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVs"
    "ID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fcGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAg"
    "ICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdl"
    "PVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAg"
    "ICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5"
    "CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAg"
    "IGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVk"
    "CgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAg"
    "IHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190"
    "b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAg"
    "ICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAg"
    "ICAgICAgWWllbGRzIGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgog"
    "ICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJb"
    "RVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAg"
    "ICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlz"
    "dG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFk"
    "eSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxs"
    "X3Byb21wdCA9IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAog"
    "ICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAg"
    "KS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRf"
    "aWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3Ry"
    "ZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXpl"
    "ciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3Nw"
    "ZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7"
    "CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAg"
    "ICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3"
    "X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAg"
    "MC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAg"
    "ICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAg"
    "ICAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAg"
    "IyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJl"
    "CiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAg"
    "dGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2Fy"
    "Z3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBn"
    "ZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgog"
    "ICAgICAgICAgICAgICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2lu"
    "KHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlp"
    "ZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFt"
    "YUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5u"
    "aW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09OIHJlc3BvbnNlIGNo"
    "dW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBi"
    "ZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9y"
    "dDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNl"
    "bGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNl"
    "bGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3Qu"
    "UmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIu"
    "cmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0"
    "dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNl"
    "CgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAg"
    "IHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190"
    "b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAg"
    "ICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJu"
    "cyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdj"
    "b250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAgICAgICIiIgog"
    "ICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAg"
    "ICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoK"
    "ICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYu"
    "X21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVh"
    "bSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9uZXdf"
    "dG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAg"
    "ICAgICAgICBmIntzZWxmLl9iYXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxv"
    "YWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pz"
    "b24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAg"
    "ICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5l"
    "ID0gcmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBu"
    "b3QgbGluZToKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVu"
    "dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRv"
    "bmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAg"
    "ICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYi"
    "XG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "Q2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3Bp"
    "YydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMg"
    "YW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGlj"
    "LmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "YXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2Vs"
    "Zi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19j"
    "b25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAg"
    "ZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3Rl"
    "bTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6"
    "IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAg"
    "ICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAg"
    "ICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50"
    "IjogbXNnWyJjb250ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1"
    "bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1h"
    "eF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBzeXN0ZW0s"
    "CiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAg"
    "ICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAg"
    "ICAgICAgICAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJv"
    "cGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAg"
    "ICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29u"
    "biA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkK"
    "ICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBo"
    "ZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAg"
    "ICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJl"
    "YWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVk"
    "ZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAg"
    "ICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoK"
    "ICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRl"
    "Y29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAg"
    "ICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAg"
    "ICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3Rh"
    "cnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6"
    "XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxv"
    "Y2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJk"
    "ZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBp"
    "ZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "ICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9w"
    "ZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVybiBhcyBDbGF1ZGUu"
    "IENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIsCiAg"
    "ICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5f"
    "a2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hv"
    "c3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1"
    "cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHBy"
    "b21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0s"
    "CiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToK"
    "ICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQog"
    "ICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9s"
    "ZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9h"
    "ZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAg"
    "ICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjog"
    "IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAg"
    "ICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhl"
    "YWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0i"
    "LAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9"
    "CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlv"
    "bihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwg"
    "Ii92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9h"
    "ZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgog"
    "ICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVz"
    "cC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBP"
    "cGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICBy"
    "ZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAg"
    "ICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1"
    "bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVu"
    "ay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAg"
    "ICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAg"
    "ICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5l"
    "LnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGlu"
    "ZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVd"
    "IjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3Ry"
    "KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9"
    "XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7"
    "fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIi"
    "KSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24u"
    "SlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBh"
    "c3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zy"
    "b21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExN"
    "QWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhl"
    "IG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQog"
    "ICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAg"
    "IHJldHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFf"
    "bW9kZWwiLCAiZG9scGhpbi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoK"
    "ICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBp"
    "X2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29u"
    "bmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4g"
    "T3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAg"
    "ICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBl"
    "bHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExv"
    "Y2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIpKQoKCiMg4pSA"
    "4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAg"
    "TWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUku"
    "CgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9y"
    "IGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAg"
    "IOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jf"
    "b2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFu"
    "Z2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExF"
    "IC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNw"
    "b25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAg"
    "ICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0"
    "b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3Rb"
    "ZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAg"
    "ICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0g"
    "c3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCU"
    "IHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAgICBz"
    "ZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9wIGltbWVkaWF0"
    "ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAg"
    "ICBhc3NlbWJsZWQgPSBbXQogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYu"
    "X2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAg"
    "c3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwK"
    "ICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAg"
    "ICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAg"
    "YnJlYWsKICAgICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAg"
    "ICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0g"
    "IiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVt"
    "aXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExF"
    "IikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29j"
    "Y3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVS"
    "Uk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6"
    "CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3Mg"
    "bGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAg"
    "IFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUg"
    "d2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9M"
    "SVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5p"
    "bmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5k"
    "b3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUt"
    "b25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNl"
    "X3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgog"
    "ICAgZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBj"
    "YW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMg"
    "PSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExM"
    "TUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAg"
    "ICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNw"
    "b25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAg"
    "ICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIK"
    "ICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0u"
    "XG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAg"
    "ICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAg"
    "ICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgog"
    "ICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNs"
    "YXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJv"
    "bSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBl"
    "eHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5n"
    "ZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1z"
    "eXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijog"
    "Y2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAg"
    "ICAgICB3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVs"
    "c2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAg"
    "IHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAg"
    "cmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIK"
    "ICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDi"
    "lIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIK"
    "ICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9k"
    "cy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElE"
    "TEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAgICAg"
    "REVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAg"
    "ICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFu"
    "c2lvbgogICAgICBTWU5USEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3Mg"
    "cmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJz"
    "b25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikg"
    "ICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg"
    "ICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIi"
    "IgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAg"
    "ICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAj"
    "IFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkgc2VsZWN0ZWQg"
    "cGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9l"
    "cyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBm"
    "IkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGlj"
    "IHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0s"
    "IGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9w"
    "bGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQg"
    "c3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUg"
    "aHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAg"
    "ICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xk"
    "IGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0"
    "b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmly"
    "c3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlv"
    "biBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAg"
    "ICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAg"
    "eWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0"
    "aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYi"
    "QXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ug"
    "c2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5J"
    "TkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlv"
    "bi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwg"
    "bm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCBy"
    "ZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250"
    "aW51ZSBkZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMg"
    "IgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9u"
    "ZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNISU5H"
    "IjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24u"
    "IE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rp"
    "b24gYXMgeW91ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFj"
    "ZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQg"
    "eWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4"
    "aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25l"
    "IGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVT"
    "SVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlv"
    "bi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhv"
    "dWdodHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAg"
    "ICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91"
    "IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0"
    "X18oCiAgICAgICAgc2VsZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3Rl"
    "bTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRF"
    "RVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGly"
    "ZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAg"
    "ICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAg"
    "ICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVst"
    "NjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAg"
    "ICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIK"
    "ICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2Vs"
    "Zi5fdmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAg"
    "ICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0"
    "cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9z"
    "eXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAg"
    "ICAgIGYie3NlbGYuX3ZhbXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBS"
    "RUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4i"
    "CiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxu"
    "IgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRp"
    "dmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsg"
    "YWxvdWQgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYi"
    "RG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAg"
    "ICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVy"
    "LiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0"
    "ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5"
    "c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAg"
    "IG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlz"
    "c2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFu"
    "Z2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "IHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2No"
    "YW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIo"
    "UVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFk"
    "IG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0"
    "IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBt"
    "ZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQgVHJ1ZT1zdWNj"
    "ZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVz"
    "c2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAg"
    "IGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwoc3Ry"
    "KQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAgIGRlZiBydW4o"
    "c2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5f"
    "YWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVz"
    "c2FnZS5lbWl0KAogICAgICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlz"
    "IG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nl"
    "c3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYgc3VjY2VzczoKICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2Ug"
    "Y29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VO"
    "SU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkK"
    "ICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRv"
    "ci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1bW1vbmluZyBmYWls"
    "ZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxz"
    "ZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9y"
    "KToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBh"
    "ZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29u"
    "bmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNw"
    "b25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3Nh"
    "Z2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29t"
    "cGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5p"
    "bmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAg"
    "ICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlB"
    "ZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJ"
    "IGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0"
    "ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRl"
    "ZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2Uu"
    "ZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxl"
    "dGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "LmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAg"
    "ICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5k"
    "IG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20g"
    "YmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJh"
    "bGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24g"
    "aXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIHNvdW5kX25hbWU6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2Vs"
    "Zi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAg"
    "IHNlbGYuZmluaXNoZWQuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikg"
    "LT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1F"
    "UiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBGYWNlVGltZXJNYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIHRoZSA2MC1zZWNvbmQgZmFj"
    "ZSBkaXNwbGF5IHRpbWVyLgoKICAgIFJ1bGVzOgogICAgLSBBZnRlciBzZW50aW1lbnQgY2xhc3NpZmlj"
    "YXRpb24sIGZhY2UgaXMgbG9ja2VkIGZvciA2MCBzZWNvbmRzLgogICAgLSBJZiB1c2VyIHNlbmRzIGEg"
    "bmV3IG1lc3NhZ2UgZHVyaW5nIHRoZSA2MHMsIGZhY2UgaW1tZWRpYXRlbHkKICAgICAgc3dpdGNoZXMg"
    "dG8gJ2FsZXJ0JyAobG9ja2VkID0gRmFsc2UsIG5ldyBjeWNsZSBiZWdpbnMpLgogICAgLSBBZnRlciA2"
    "MHMgd2l0aCBubyBuZXcgaW5wdXQsIHJldHVybnMgdG8gJ25ldXRyYWwnLgogICAgLSBOZXZlciBibG9j"
    "a3MgYW55dGhpbmcuIFB1cmUgdGltZXIgKyBjYWxsYmFjayBsb2dpYy4KICAgICIiIgoKICAgIEhPTERf"
    "U0VDT05EUyA9IDYwCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1pcnJvcjogIk1pcnJvcldpZGdldCIs"
    "IGVtb3Rpb25fYmxvY2s6ICJFbW90aW9uQmxvY2siKToKICAgICAgICBzZWxmLl9taXJyb3IgID0gbWly"
    "cm9yCiAgICAgICAgc2VsZi5fZW1vdGlvbiA9IGVtb3Rpb25fYmxvY2sKICAgICAgICBzZWxmLl90aW1l"
    "ciAgID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl90aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAg"
    "ICAgc2VsZi5fdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3JldHVybl90b19uZXV0cmFsKQogICAg"
    "ICAgIHNlbGYuX2xvY2tlZCAgPSBGYWxzZQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBlbW90aW9uOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IGZhY2UgYW5kIHN0YXJ0IHRoZSA2MC1zZWNvbmQgaG9s"
    "ZCB0aW1lci4iIiIKICAgICAgICBzZWxmLl9sb2NrZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWlycm9y"
    "LnNldF9mYWNlKGVtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKGVtb3Rpb24p"
    "CiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fdGltZXIuc3RhcnQoc2VsZi5I"
    "T0xEX1NFQ09ORFMgKiAxMDAwKQoKICAgIGRlZiBpbnRlcnJ1cHQoc2VsZiwgbmV3X2Vtb3Rpb246IHN0"
    "ciA9ICJhbGVydCIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHdoZW4gdXNlciBz"
    "ZW5kcyBhIG5ldyBtZXNzYWdlLgogICAgICAgIEludGVycnVwdHMgYW55IHJ1bm5pbmcgaG9sZCwgc2V0"
    "cyBhbGVydCBmYWNlIGltbWVkaWF0ZWx5LgogICAgICAgICIiIgogICAgICAgIHNlbGYuX3RpbWVyLnN0"
    "b3AoKQogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9m"
    "YWNlKG5ld19lbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihuZXdfZW1vdGlv"
    "bikKCiAgICBkZWYgX3JldHVybl90b19uZXV0cmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "bG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQoKICAg"
    "IEBwcm9wZXJ0eQogICAgZGVmIGlzX2xvY2tlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBz"
    "ZWxmLl9sb2NrZWQKCgojIOKUgOKUgCBHT09HTEUgU0VSVklDRSBDTEFTU0VTIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAojIFBvcnRlZCBmcm9tIEdyaW1WZWlsIGRlY2suIEhhbmRsZXMgQ2Fs"
    "ZW5kYXIgYW5kIERyaXZlL0RvY3MgYXV0aCArIEFQSS4KIyBDcmVkZW50aWFscyBwYXRoOiBjZmdfcGF0"
    "aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iCiMgVG9rZW4gcGF0aDogICAgICAg"
    "Y2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iCgpjbGFzcyBHb29nbGVDYWxlbmRhclNlcnZp"
    "Y2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0"
    "aDogUGF0aCk6CiAgICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAog"
    "ICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9zZXJ2aWNlID0g"
    "Tm9uZQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAgICAgICAgc2VsZi50b2tl"
    "bl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2Vs"
    "Zi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoK"
    "ICAgIGRlZiBfYnVpbGRfc2VydmljZShzZWxmKToKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10g"
    "Q3JlZGVudGlhbHMgcGF0aDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iKQogICAgICAgIHByaW50KGYi"
    "W0dDYWxdW0RFQlVHXSBUb2tlbiBwYXRoOiB7c2VsZi50b2tlbl9wYXRofSIpCiAgICAgICAgcHJpbnQo"
    "ZiJbR0NhbF1bREVCVUddIENyZWRlbnRpYWxzIGZpbGUgZXhpc3RzOiB7c2VsZi5jcmVkZW50aWFsc19w"
    "YXRoLmV4aXN0cygpfSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIGZpbGUgZXhp"
    "c3RzOiB7c2VsZi50b2tlbl9wYXRoLmV4aXN0cygpfSIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJ"
    "X09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIElt"
    "cG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBD"
    "YWxlbmRhciBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNy"
    "ZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9y"
    "KAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5v"
    "dCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3Jl"
    "ZHMgPSBOb25lCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi50"
    "b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZy"
    "b21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMp"
    "CgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMo"
    "R09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVf"
    "UkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJl"
    "ZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFJlZnJlc2hpbmcgZXhw"
    "aXJlZCBHb29nbGUgdG9rZW4uIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMu"
    "cmVmcmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90"
    "b2tlbihjcmVkcykKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAg"
    "ICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAgICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiBy"
    "ZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09HTEVfU0NPUEVfUkVB"
    "VVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9y"
    "IG5vdCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gU3RhcnRpbmcg"
    "T0F1dGggZmxvdyBmb3IgR29vZ2xlIENhbGVuZGFyLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIo"
    "c2VsZi5jcmVkZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRz"
    "ID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAgICAg"
    "ICAgICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3Jp"
    "emF0aW9uX3Byb21wdF9tZXNzYWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBV"
    "UkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAg"
    "ICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1"
    "dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAg"
    "ICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAg"
    "cmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVj"
    "dC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAg"
    "ICAgIHByaW50KCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIikK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHByaW50KGYi"
    "W0dDYWxdW0VSUk9SXSBPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIp"
    "CiAgICAgICAgICAgICAgICByYWlzZQogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gVHJ1ZQoK"
    "ICAgICAgICBzZWxmLl9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJjYWxlbmRhciIsICJ2MyIsIGNyZWRl"
    "bnRpYWxzPWNyZWRzKQogICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEF1dGhlbnRpY2F0ZWQgR29v"
    "Z2xlIENhbGVuZGFyIHNlcnZpY2UgY3JlYXRlZCBzdWNjZXNzZnVsbHkuIikKICAgICAgICByZXR1cm4g"
    "bGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBfZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZShzZWxmKSAt"
    "PiBzdHI6CiAgICAgICAgbG9jYWxfdHppbmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6"
    "aW5mbwogICAgICAgIGNhbmRpZGF0ZXMgPSBbXQogICAgICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3Qg"
    "Tm9uZToKICAgICAgICAgICAgY2FuZGlkYXRlcy5leHRlbmQoWwogICAgICAgICAgICAgICAgZ2V0YXR0"
    "cihsb2NhbF90emluZm8sICJrZXkiLCBOb25lKSwKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxf"
    "dHppbmZvLCAiem9uZSIsIE5vbmUpLAogICAgICAgICAgICAgICAgc3RyKGxvY2FsX3R6aW5mbyksCiAg"
    "ICAgICAgICAgICAgICBsb2NhbF90emluZm8udHpuYW1lKGRhdGV0aW1lLm5vdygpKSwKICAgICAgICAg"
    "ICAgXSkKCiAgICAgICAgZW52X3R6ID0gb3MuZW52aXJvbi5nZXQoIlRaIikKICAgICAgICBpZiBlbnZf"
    "dHo6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuYXBwZW5kKGVudl90eikKCiAgICAgICAgZm9yIGNhbmRp"
    "ZGF0ZSBpbiBjYW5kaWRhdGVzOgogICAgICAgICAgICBpZiBub3QgY2FuZGlkYXRlOgogICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICAgICAgbWFwcGVkID0gV0lORE9XU19UWl9UT19JQU5BLmdldChj"
    "YW5kaWRhdGUsIGNhbmRpZGF0ZSkKICAgICAgICAgICAgaWYgIi8iIGluIG1hcHBlZDoKICAgICAgICAg"
    "ICAgICAgIHJldHVybiBtYXBwZWQKCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bV0FS"
    "Tl0gVW5hYmxlIHRvIHJlc29sdmUgbG9jYWwgSUFOQSB0aW1lem9uZS4gIgogICAgICAgICAgICBmIkZh"
    "bGxpbmcgYmFjayB0byB7REVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORX0uIgogICAgICAgICkKICAg"
    "ICAgICByZXR1cm4gREVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORQoKICAgIGRlZiBjcmVhdGVfZXZl"
    "bnRfZm9yX3Rhc2soc2VsZiwgdGFzazogZGljdCk6CiAgICAgICAgZHVlX2F0ID0gcGFyc2VfaXNvX2Zv"
    "cl9jb21wYXJlKHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0YXNrLmdldCgiZHVlIiksIGNvbnRleHQ9Imdv"
    "b2dsZV9jcmVhdGVfZXZlbnRfZHVlIikKICAgICAgICBpZiBub3QgZHVlX2F0OgogICAgICAgICAgICBy"
    "YWlzZSBWYWx1ZUVycm9yKCJUYXNrIGR1ZSB0aW1lIGlzIG1pc3Npbmcgb3IgaW52YWxpZC4iKQoKICAg"
    "ICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5v"
    "bmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAg"
    "ICAgICAgZHVlX2xvY2FsID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR1ZV9hdCwgY29u"
    "dGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWVfbG9jYWwiKQogICAgICAgIHN0YXJ0X2R0ID0gZHVl"
    "X2xvY2FsLnJlcGxhY2UobWljcm9zZWNvbmQ9MCwgdHppbmZvPU5vbmUpCiAgICAgICAgZW5kX2R0ID0g"
    "c3RhcnRfZHQgKyB0aW1lZGVsdGEobWludXRlcz0zMCkKICAgICAgICB0el9uYW1lID0gc2VsZi5fZ2V0"
    "X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCgogICAgICAgIGV2ZW50X3BheWxvYWQgPSB7CiAgICAgICAg"
    "ICAgICJzdW1tYXJ5IjogKHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVyIikuc3RyaXAoKSwKICAg"
    "ICAgICAgICAgInN0YXJ0IjogeyJkYXRlVGltZSI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0i"
    "c2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICAgICAgImVuZCI6IHsiZGF0ZVRp"
    "bWUiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25h"
    "bWV9LAogICAgICAgIH0KICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAg"
    "ICBwcmludChmIltHQ2FsXVtERUJVR10gVGFyZ2V0IGNhbGVuZGFyIElEOiB7dGFyZ2V0X2NhbGVuZGFy"
    "X2lkfSIpCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bREVCVUddIEV2ZW50IHBheWxv"
    "YWQgYmVmb3JlIGluc2VydDogIgogICAgICAgICAgICBmInRpdGxlPSd7ZXZlbnRfcGF5bG9hZC5nZXQo"
    "J3N1bW1hcnknKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2Fk"
    "LmdldCgnc3RhcnQnLCB7fSkuZ2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJzdGFydC50"
    "aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9Jywg"
    "IgogICAgICAgICAgICBmImVuZC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSku"
    "Z2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJlbmQudGltZVpvbmU9J3tldmVudF9wYXls"
    "b2FkLmdldCgnZW5kJywge30pLmdldCgndGltZVpvbmUnKX0nIgogICAgICAgICkKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRh"
    "cklkPXRhcmdldF9jYWxlbmRhcl9pZCwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAg"
    "ICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gRXZlbnQgaW5zZXJ0IGNhbGwgc3VjY2VlZGVkLiIpCiAg"
    "ICAgICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAogICAgICAg"
    "IGV4Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBhcGlfZGV0YWlsID0g"
    "IiIKICAgICAgICAgICAgaWYgaGFzYXR0cihhcGlfZXgsICJjb250ZW50IikgYW5kIGFwaV9leC5jb250"
    "ZW50OgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBh"
    "cGlfZXguY29udGVudC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IHN0cihh"
    "cGlfZXguY29udGVudCkKICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYiR29vZ2xlIEFQSSBlcnJvcjog"
    "e2FwaV9leH0iCiAgICAgICAgICAgIGlmIGFwaV9kZXRhaWw6CiAgICAgICAgICAgICAgICBkZXRhaWxf"
    "bXNnID0gZiJ7ZGV0YWlsX21zZ30gfCBBUEkgYm9keToge2FwaV9kZXRhaWx9IgogICAgICAgICAgICBw"
    "cmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZDoge2RldGFpbF9tc2d9IikKICAg"
    "ICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGRldGFpbF9tc2cpIGZyb20gYXBpX2V4CiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2"
    "ZW50IGluc2VydCBmYWlsZWQgd2l0aCB1bmV4cGVjdGVkIGVycm9yOiB7ZXh9IikKICAgICAgICAgICAg"
    "cmFpc2UKCiAgICBkZWYgY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9hZChzZWxmLCBldmVudF9wYXlsb2Fk"
    "OiBkaWN0LCBjYWxlbmRhcl9pZDogc3RyID0gInByaW1hcnkiKToKICAgICAgICBpZiBub3QgaXNpbnN0"
    "YW5jZShldmVudF9wYXlsb2FkLCBkaWN0KToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29v"
    "Z2xlIGV2ZW50IHBheWxvYWQgbXVzdCBiZSBhIGRpY3Rpb25hcnkuIikKICAgICAgICBsaW5rX2VzdGFi"
    "bGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAg"
    "IGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICBjcmVhdGVkID0g"
    "c2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD0oY2FsZW5kYXJfaWQgb3IgInBy"
    "aW1hcnkiKSwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRl"
    "ZC5nZXQoImlkIiksIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgbGlzdF9wcmltYXJ5X2V2ZW50cyhz"
    "ZWxmLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRpbWVfbWluOiBzdHIgPSBOb25lLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgbWF4X3Jlc3VsdHM6IGludCA9IDI1MDApOgogICAgICAgICIiIgogICAg"
    "ICAgIEZldGNoIGNhbGVuZGFyIGV2ZW50cyB3aXRoIHBhZ2luYXRpb24gYW5kIHN5bmNUb2tlbiBzdXBw"
    "b3J0LgogICAgICAgIFJldHVybnMgKGV2ZW50c19saXN0LCBuZXh0X3N5bmNfdG9rZW4pLgoKICAgICAg"
    "ICBzeW5jX3Rva2VuIG1vZGU6IGluY3JlbWVudGFsIOKAlCByZXR1cm5zIE9OTFkgY2hhbmdlcyAoYWRk"
    "cy9lZGl0cy9jYW5jZWxzKS4KICAgICAgICB0aW1lX21pbiBtb2RlOiAgIGZ1bGwgc3luYyBmcm9tIGEg"
    "ZGF0ZS4KICAgICAgICBCb3RoIHVzZSBzaG93RGVsZXRlZD1UcnVlIHNvIGNhbmNlbGxhdGlvbnMgY29t"
    "ZSB0aHJvdWdoLgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAg"
    "ICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGlmIHN5bmNfdG9rZW46CiAgICAg"
    "ICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAgImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAg"
    "ICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzaG93RGVs"
    "ZXRlZCI6IFRydWUsCiAgICAgICAgICAgICAgICAic3luY1Rva2VuIjogc3luY190b2tlbiwKICAgICAg"
    "ICAgICAgfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAg"
    "ImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAgICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1"
    "ZSwKICAgICAgICAgICAgICAgICJzaG93RGVsZXRlZCI6IFRydWUsCiAgICAgICAgICAgICAgICAibWF4"
    "UmVzdWx0cyI6IDI1MCwKICAgICAgICAgICAgICAgICJvcmRlckJ5IjogInN0YXJ0VGltZSIsCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgaWYgdGltZV9taW46CiAgICAgICAgICAgICAgICBxdWVyeVsidGlt"
    "ZU1pbiJdID0gdGltZV9taW4KCiAgICAgICAgYWxsX2V2ZW50cyA9IFtdCiAgICAgICAgbmV4dF9zeW5j"
    "X3Rva2VuID0gTm9uZQogICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgIHJlc3BvbnNlID0gc2Vs"
    "Zi5fc2VydmljZS5ldmVudHMoKS5saXN0KCoqcXVlcnkpLmV4ZWN1dGUoKQogICAgICAgICAgICBhbGxf"
    "ZXZlbnRzLmV4dGVuZChyZXNwb25zZS5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgICAgICBuZXh0X3N5"
    "bmNfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRTeW5jVG9rZW4iKQogICAgICAgICAgICBwYWdlX3Rv"
    "a2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0UGFnZVRva2VuIikKICAgICAgICAgICAgaWYgbm90IHBhZ2Vf"
    "dG9rZW46CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBxdWVyeS5wb3AoInN5bmNUb2tl"
    "biIsIE5vbmUpCiAgICAgICAgICAgIHF1ZXJ5WyJwYWdlVG9rZW4iXSA9IHBhZ2VfdG9rZW4KCiAgICAg"
    "ICAgcmV0dXJuIGFsbF9ldmVudHMsIG5leHRfc3luY190b2tlbgoKICAgIGRlZiBnZXRfZXZlbnQoc2Vs"
    "ZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRfaWQ6CiAg"
    "ICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVy"
    "biBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmdldChjYWxlbmRhcklkPSJwcmltYXJ5IiwgZXZlbnRJZD1n"
    "b29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQogICAgICAgIGV4Y2VwdCBHb29nbGVIdHRwRXJyb3IgYXMg"
    "YXBpX2V4OgogICAgICAgICAgICBjb2RlID0gZ2V0YXR0cihnZXRhdHRyKGFwaV9leCwgInJlc3AiLCBO"
    "b25lKSwgInN0YXR1cyIsIE5vbmUpCiAgICAgICAgICAgIGlmIGNvZGUgaW4gKDQwNCwgNDEwKToKICAg"
    "ICAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGRlbGV0ZV9l"
    "dmVudF9mb3JfdGFzayhzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdv"
    "b2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29vZ2xlIGV2ZW50IGlk"
    "IGlzIG1pc3Npbmc7IGNhbm5vdCBkZWxldGUgZXZlbnQuIikKCiAgICAgICAgaWYgc2VsZi5fc2Vydmlj"
    "ZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgdGFyZ2V0"
    "X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgc2VsZi5fc2VydmljZS5ldmVudHMoKS5kZWxl"
    "dGUoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJfaWQsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5l"
    "eGVjdXRlKCkKCgpjbGFzcyBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgsIGxvZ2dlcj1Ob25lKToK"
    "ICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2Vs"
    "Zi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBOb25l"
    "CiAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gTm9uZQogICAgICAgIHNlbGYuX2xvZ2dlciA9IGxv"
    "Z2dlcgoKICAgIGRlZiBfbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIik6"
    "CiAgICAgICAgaWYgY2FsbGFibGUoc2VsZi5fbG9nZ2VyKToKICAgICAgICAgICAgc2VsZi5fbG9nZ2Vy"
    "KG1lc3NhZ2UsIGxldmVsPWxldmVsKQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6"
    "CiAgICAgICAgc2VsZi50b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29r"
    "PVRydWUpCiAgICAgICAgc2VsZi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBl"
    "bmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYXV0aGVudGljYXRlKHNlbGYpOgogICAgICAgIHNlbGYu"
    "X2xvZygiRHJpdmUgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgc2VsZi5fbG9nKCJE"
    "b2NzIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9P"
    "SzoKICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBv"
    "cnRFcnJvciIKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgUHl0"
    "aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAgICAgICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19w"
    "YXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJvcigKICAgICAgICAg"
    "ICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtz"
    "ZWxmLmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQog"
    "ICAgICAgIGlmIHNlbGYudG9rZW5fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29n"
    "bGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRva2VuX3BhdGgp"
    "LCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQgYW5kIG5vdCBj"
    "cmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJy"
    "b3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBp"
    "cmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9w"
    "ZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAg"
    "ICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xl"
    "IHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9T"
    "Q09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3Qg"
    "Y3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBzZWxmLl9sb2coIlN0YXJ0aW5nIE9B"
    "dXRoIGZsb3cgZm9yIEdvb2dsZSBEcml2ZS9Eb2NzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2Vj"
    "cmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAg"
    "ICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAg"
    "cG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAg"
    "ICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRp"
    "b246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nl"
    "c3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5k"
    "b3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAg"
    "ICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3Jl"
    "ZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRz"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fbG9nKCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRl"
    "biBzdWNjZXNzZnVsbHkuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9nKGYiT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBl"
    "KGV4KS5fX25hbWVfX306IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICAgICAgcmFpc2UK"
    "CiAgICAgICAgcmV0dXJuIGNyZWRzCgogICAgZGVmIGVuc3VyZV9zZXJ2aWNlcyhzZWxmKToKICAgICAg"
    "ICBpZiBzZWxmLl9kcml2ZV9zZXJ2aWNlIGlzIG5vdCBOb25lIGFuZCBzZWxmLl9kb2NzX3NlcnZpY2Ug"
    "aXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgY3Jl"
    "ZHMgPSBzZWxmLl9hdXRoZW50aWNhdGUoKQogICAgICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0g"
    "Z29vZ2xlX2J1aWxkKCJkcml2ZSIsICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAgICBz"
    "ZWxmLl9kb2NzX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRvY3MiLCAidjEiLCBjcmVkZW50aWFscz1j"
    "cmVkcykKICAgICAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklO"
    "Rk8iKQogICAgICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZP"
    "IikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9sb2coZiJE"
    "cml2ZSBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICBzZWxmLl9s"
    "b2coZiJEb2NzIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHJh"
    "aXNlCgogICAgZGVmIGxpc3RfZm9sZGVyX2l0ZW1zKHNlbGYsIGZvbGRlcl9pZDogc3RyID0gInJvb3Qi"
    "LCBwYWdlX3NpemU6IGludCA9IDEwMCk6CiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAg"
    "ICAgIHNhZmVfZm9sZGVyX2lkID0gKGZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3Qi"
    "CiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgZmlsZSBsaXN0IGZldGNoIHN0YXJ0ZWQuIGZvbGRlcl9p"
    "ZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJlc3BvbnNlID0gc2VsZi5f"
    "ZHJpdmVfc2VydmljZS5maWxlcygpLmxpc3QoCiAgICAgICAgICAgIHE9ZiIne3NhZmVfZm9sZGVyX2lk"
    "fScgaW4gcGFyZW50cyBhbmQgdHJhc2hlZD1mYWxzZSIsCiAgICAgICAgICAgIHBhZ2VTaXplPW1heCgx"
    "LCBtaW4oaW50KHBhZ2Vfc2l6ZSBvciAxMDApLCAyMDApKSwKICAgICAgICAgICAgb3JkZXJCeT0iZm9s"
    "ZGVyLG5hbWUsbW9kaWZpZWRUaW1lIGRlc2MiLAogICAgICAgICAgICBmaWVsZHM9KAogICAgICAgICAg"
    "ICAgICAgImZpbGVzKCIKICAgICAgICAgICAgICAgICJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGlt"
    "ZSx3ZWJWaWV3TGluayxwYXJlbnRzLHNpemUsIgogICAgICAgICAgICAgICAgImxhc3RNb2RpZnlpbmdV"
    "c2VyKGRpc3BsYXlOYW1lLGVtYWlsQWRkcmVzcykiCiAgICAgICAgICAgICAgICAiKSIKICAgICAgICAg"
    "ICAgKSwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGZpbGVzID0gcmVzcG9uc2UuZ2V0KCJmaWxl"
    "cyIsIFtdKQogICAgICAgIGZvciBpdGVtIGluIGZpbGVzOgogICAgICAgICAgICBtaW1lID0gKGl0ZW0u"
    "Z2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1bImlzX2ZvbGRlciJd"
    "ID0gbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciIKICAgICAgICAgICAg"
    "aXRlbVsiaXNfZ29vZ2xlX2RvYyJdID0gbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBz"
    "LmRvY3VtZW50IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGl0ZW1zIHJldHVybmVkOiB7bGVuKGZp"
    "bGVzKX0gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmV0"
    "dXJuIGZpbGVzCgogICAgZGVmIGdldF9kb2NfcHJldmlldyhzZWxmLCBkb2NfaWQ6IHN0ciwgbWF4X2No"
    "YXJzOiBpbnQgPSAxODAwKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3Nl"
    "cnZpY2VzKCkKICAgICAgICBkb2MgPSBzZWxmLl9kb2NzX3NlcnZpY2UuZG9jdW1lbnRzKCkuZ2V0KGRv"
    "Y3VtZW50SWQ9ZG9jX2lkKS5leGVjdXRlKCkKICAgICAgICB0aXRsZSA9IGRvYy5nZXQoInRpdGxlIikg"
    "b3IgIlVudGl0bGVkIgogICAgICAgIGJvZHkgPSBkb2MuZ2V0KCJib2R5Iiwge30pLmdldCgiY29udGVu"
    "dCIsIFtdKQogICAgICAgIGNodW5rcyA9IFtdCiAgICAgICAgZm9yIGJsb2NrIGluIGJvZHk6CiAgICAg"
    "ICAgICAgIHBhcmFncmFwaCA9IGJsb2NrLmdldCgicGFyYWdyYXBoIikKICAgICAgICAgICAgaWYgbm90"
    "IHBhcmFncmFwaDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGVsZW1lbnRzID0g"
    "cGFyYWdyYXBoLmdldCgiZWxlbWVudHMiLCBbXSkKICAgICAgICAgICAgZm9yIGVsIGluIGVsZW1lbnRz"
    "OgogICAgICAgICAgICAgICAgcnVuID0gZWwuZ2V0KCJ0ZXh0UnVuIikKICAgICAgICAgICAgICAgIGlm"
    "IG5vdCBydW46CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgIHRleHQg"
    "PSAocnVuLmdldCgiY29udGVudCIpIG9yICIiKS5yZXBsYWNlKCJceDBiIiwgIlxuIikKICAgICAgICAg"
    "ICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgY2h1bmtzLmFwcGVuZCh0ZXh0KQogICAg"
    "ICAgIHBhcnNlZCA9ICIiLmpvaW4oY2h1bmtzKS5zdHJpcCgpCiAgICAgICAgaWYgbGVuKHBhcnNlZCkg"
    "PiBtYXhfY2hhcnM6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlZFs6bWF4X2NoYXJzXS5yc3RyaXAo"
    "KSArICLigKYiCiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInRpdGxlIjogdGl0bGUsCiAgICAg"
    "ICAgICAgICJkb2N1bWVudF9pZCI6IGRvY19pZCwKICAgICAgICAgICAgInJldmlzaW9uX2lkIjogZG9j"
    "LmdldCgicmV2aXNpb25JZCIpLAogICAgICAgICAgICAicHJldmlld190ZXh0IjogcGFyc2VkIG9yICJb"
    "Tm8gdGV4dCBjb250ZW50IHJldHVybmVkIGZyb20gRG9jcyBBUEkuXSIsCiAgICAgICAgfQoKICAgIGRl"
    "ZiBjcmVhdGVfZG9jKHNlbGYsIHRpdGxlOiBzdHIgPSAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiLCBwYXJl"
    "bnRfZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfdGl0bGUgPSAodGl0bGUgb3Ig"
    "Ik5ldyBHcmltVmVpbGUgUmVjb3JkIikuc3RyaXAoKSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiCiAg"
    "ICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVu"
    "dF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIGNyZWF0ZWQgPSBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAg"
    "ICAgICAgICAgICJuYW1lIjogc2FmZV90aXRsZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJh"
    "cHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAgICAgInBhcmVu"
    "dHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAgICAgICBmaWVsZHM9Imlk"
    "LG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICku"
    "ZXhlY3V0ZSgpCiAgICAgICAgZG9jX2lkID0gY3JlYXRlZC5nZXQoImlkIikKICAgICAgICBtZXRhID0g"
    "c2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpIGlmIGRvY19pZCBlbHNlIHt9CiAgICAgICAgcmV0"
    "dXJuIHsKICAgICAgICAgICAgImlkIjogZG9jX2lkLAogICAgICAgICAgICAibmFtZSI6IG1ldGEuZ2V0"
    "KCJuYW1lIikgb3Igc2FmZV90aXRsZSwKICAgICAgICAgICAgIm1pbWVUeXBlIjogbWV0YS5nZXQoIm1p"
    "bWVUeXBlIikgb3IgImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAg"
    "ICAgICJtb2RpZmllZFRpbWUiOiBtZXRhLmdldCgibW9kaWZpZWRUaW1lIiksCiAgICAgICAgICAgICJ3"
    "ZWJWaWV3TGluayI6IG1ldGEuZ2V0KCJ3ZWJWaWV3TGluayIpLAogICAgICAgICAgICAicGFyZW50cyI6"
    "IG1ldGEuZ2V0KCJwYXJlbnRzIikgb3IgW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICB9CgogICAgZGVm"
    "IGNyZWF0ZV9mb2xkZXIoc2VsZiwgbmFtZTogc3RyID0gIk5ldyBGb2xkZXIiLCBwYXJlbnRfZm9sZGVy"
    "X2lkOiBzdHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfbmFtZSA9IChuYW1lIG9yICJOZXcgRm9sZGVy"
    "Iikuc3RyaXAoKSBvciAiTmV3IEZvbGRlciIKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRf"
    "Zm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVh"
    "dGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX25hbWUsCiAg"
    "ICAgICAgICAgICAgICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRl"
    "ciIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAg"
    "IH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmll"
    "d0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRlZAoK"
    "ICAgIGRlZiBnZXRfZmlsZV9tZXRhZGF0YShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5v"
    "dCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVk"
    "LiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2"
    "ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0KAogICAgICAgICAgICBmaWxlSWQ9ZmlsZV9pZCwKICAgICAgICAg"
    "ICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRz"
    "LHNpemUiLAogICAgICAgICkuZXhlY3V0ZSgpCgogICAgZGVmIGdldF9kb2NfbWV0YWRhdGEoc2VsZiwg"
    "ZG9jX2lkOiBzdHIpOgogICAgICAgIHJldHVybiBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkK"
    "CiAgICBkZWYgZGVsZXRlX2l0ZW0oc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmls"
    "ZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQog"
    "ICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZp"
    "bGVzKCkuZGVsZXRlKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCiAgICBkZWYgZGVsZXRlX2RvYyhz"
    "ZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgc2VsZi5kZWxldGVfaXRlbShkb2NfaWQpCgogICAgZGVm"
    "IGV4cG9ydF9kb2NfdGV4dChzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGRvY19pZDoK"
    "ICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAg"
    "ICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcGF5bG9hZCA9IHNlbGYuX2RyaXZlX3Nl"
    "cnZpY2UuZmlsZXMoKS5leHBvcnQoCiAgICAgICAgICAgIGZpbGVJZD1kb2NfaWQsCiAgICAgICAgICAg"
    "IG1pbWVUeXBlPSJ0ZXh0L3BsYWluIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGlmIGlzaW5z"
    "dGFuY2UocGF5bG9hZCwgYnl0ZXMpOgogICAgICAgICAgICByZXR1cm4gcGF5bG9hZC5kZWNvZGUoInV0"
    "Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICByZXR1cm4gc3RyKHBheWxvYWQgb3IgIiIpCgog"
    "ICAgZGVmIGRvd25sb2FkX2ZpbGVfYnl0ZXMoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBu"
    "b3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJl"
    "ZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJp"
    "dmVfc2VydmljZS5maWxlcygpLmdldF9tZWRpYShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgoKCgoj"
    "IOKUgOKUgCBQQVNTIDMgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdvcmtlciB0aHJlYWRzIGRlZmluZWQuIEFsbCBnZW5l"
    "cmF0aW9uIGlzIHN0cmVhbWluZy4KIyBObyBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZCBhbnl3"
    "aGVyZSBpbiB0aGlzIGZpbGUuCiMKIyBOZXh0OiBQYXNzIDQg4oCUIE1lbW9yeSAmIFN0b3JhZ2UKIyAo"
    "TWVtb3J5TWFuYWdlciwgU2Vzc2lvbk1hbmFnZXIsIExlc3NvbnNMZWFybmVkREIsIFRhc2tNYW5hZ2Vy"
    "KQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA0OiBNRU1PUlkgJiBTVE9SQUdFCiMKIyBTeXN0ZW1z"
    "IGRlZmluZWQgaGVyZToKIyAgIERlcGVuZGVuY3lDaGVja2VyICAg4oCUIHZhbGlkYXRlcyBhbGwgcmVx"
    "dWlyZWQgcGFja2FnZXMgb24gc3RhcnR1cAojICAgTWVtb3J5TWFuYWdlciAgICAgICDigJQgSlNPTkwg"
    "bWVtb3J5IHJlYWQvd3JpdGUvc2VhcmNoCiMgICBTZXNzaW9uTWFuYWdlciAgICAgIOKAlCBhdXRvLXNh"
    "dmUsIGxvYWQsIGNvbnRleHQgaW5qZWN0aW9uLCBzZXNzaW9uIGluZGV4CiMgICBMZXNzb25zTGVhcm5l"
    "ZERCICAgIOKAlCBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMga25vd2xlZGdlIGJh"
    "c2UKIyAgIFRhc2tNYW5hZ2VyICAgICAgICAg4oCUIHRhc2svcmVtaW5kZXIgQ1JVRCwgZHVlLWV2ZW50"
    "IGRldGVjdGlvbgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkAoKCiMg4pSA4pSAIERFUEVOREVOQ1kgQ0hFQ0tFUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRGVwZW5kZW5jeUNoZWNrZXI6CiAgICAi"
    "IiIKICAgIFZhbGlkYXRlcyBhbGwgcmVxdWlyZWQgYW5kIG9wdGlvbmFsIHBhY2thZ2VzIG9uIHN0YXJ0"
    "dXAuCiAgICBSZXR1cm5zIGEgbGlzdCBvZiBzdGF0dXMgbWVzc2FnZXMgZm9yIHRoZSBEaWFnbm9zdGlj"
    "cyB0YWIuCiAgICBTaG93cyBhIGJsb2NraW5nIGVycm9yIGRpYWxvZyBmb3IgYW55IGNyaXRpY2FsIG1p"
    "c3NpbmcgZGVwZW5kZW5jeS4KICAgICIiIgoKICAgICMgKHBhY2thZ2VfbmFtZSwgaW1wb3J0X25hbWUs"
    "IGNyaXRpY2FsLCBpbnN0YWxsX2hpbnQpCiAgICBQQUNLQUdFUyA9IFsKICAgICAgICAoIlB5U2lkZTYi"
    "LCAgICAgICAgICAgICAgICAgICAiUHlTaWRlNiIsICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgUHlTaWRlNiIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAg"
    "ICJsb2d1cnUiLCAgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBsb2d1cnUi"
    "KSwKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiLCAgICAg"
    "ICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgYXBzY2hlZHVsZXIiKSwKICAgICAgICAoInB5"
    "Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiwgICAgICAgICAgICAgICBGYWxzZSwKICAg"
    "ICAgICAgInBpcCBpbnN0YWxsIHB5Z2FtZSAgKG5lZWRlZCBmb3Igc291bmQpIiksCiAgICAgICAgKCJw"
    "eXdpbjMyIiwgICAgICAgICAgICAgICAgICAgIndpbjMyY29tIiwgICAgICAgICAgICAgRmFsc2UsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCBweXdpbjMyICAobmVlZGVkIGZvciBkZXNrdG9wIHNob3J0Y3V0KSIp"
    "LAogICAgICAgICgicHN1dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiLCAgICAgICAgICAg"
    "ICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHN1dGlsICAobmVlZGVkIGZvciBzeXN0ZW0g"
    "bW9uaXRvcmluZykiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAgICAgICAgICAgICAicmVxdWVz"
    "dHMiLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHJlcXVlc3RzIiksCiAg"
    "ICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIsICAgICAg"
    "RmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiKSwKICAg"
    "ICAgICAoImdvb2dsZS1hdXRoLW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiLCBG"
    "YWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoLW9hdXRobGliIiksCiAgICAgICAg"
    "KCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5hdXRoIiwgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aCIpLAogICAgICAgICgidG9yY2giLCAgICAg"
    "ICAgICAgICAgICAgICAgICJ0b3JjaCIsICAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlw"
    "IGluc3RhbGwgdG9yY2ggIChvbmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJ0"
    "cmFuc2Zvcm1lcnMiLCAgICAgICAgICAgICAgInRyYW5zZm9ybWVycyIsICAgICAgICAgRmFsc2UsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCB0cmFuc2Zvcm1lcnMgIChvbmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9k"
    "ZWwpIiksCiAgICAgICAgKCJweW52bWwiLCAgICAgICAgICAgICAgICAgICAgInB5bnZtbCIsICAgICAg"
    "ICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweW52bWwgIChvbmx5IG5lZWRlZCBm"
    "b3IgTlZJRElBIEdQVSBtb25pdG9yaW5nKSIpLAogICAgXQoKICAgIEBjbGFzc21ldGhvZAogICAgZGVm"
    "IGNoZWNrKGNscykgLT4gdHVwbGVbbGlzdFtzdHJdLCBsaXN0W3N0cl1dOgogICAgICAgICIiIgogICAg"
    "ICAgIFJldHVybnMgKG1lc3NhZ2VzLCBjcml0aWNhbF9mYWlsdXJlcykuCiAgICAgICAgbWVzc2FnZXM6"
    "IGxpc3Qgb2YgIltERVBTXSBwYWNrYWdlIOKcky/inJcg4oCUIG5vdGUiIHN0cmluZ3MKICAgICAgICBj"
    "cml0aWNhbF9mYWlsdXJlczogbGlzdCBvZiBwYWNrYWdlcyB0aGF0IGFyZSBjcml0aWNhbCBhbmQgbWlz"
    "c2luZwogICAgICAgICIiIgogICAgICAgIGltcG9ydCBpbXBvcnRsaWIKICAgICAgICBtZXNzYWdlcyAg"
    "PSBbXQogICAgICAgIGNyaXRpY2FsICA9IFtdCgogICAgICAgIGZvciBwa2dfbmFtZSwgaW1wb3J0X25h"
    "bWUsIGlzX2NyaXRpY2FsLCBoaW50IGluIGNscy5QQUNLQUdFUzoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAg"
    "ICAgICBtZXNzYWdlcy5hcHBlbmQoZiJbREVQU10ge3BrZ19uYW1lfSDinJMiKQogICAgICAgICAgICBl"
    "eGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgICAgICBzdGF0dXMgPSAiQ1JJVElDQUwiIGlmIGlz"
    "X2NyaXRpY2FsIGVsc2UgIm9wdGlvbmFsIgogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgICAgIGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyXICh7c3RhdHVzfSkg4oCUIHto"
    "aW50fSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIGlzX2NyaXRpY2FsOgogICAg"
    "ICAgICAgICAgICAgICAgIGNyaXRpY2FsLmFwcGVuZChwa2dfbmFtZSkKCiAgICAgICAgcmV0dXJuIG1l"
    "c3NhZ2VzLCBjcml0aWNhbAoKICAgIEBjbGFzc21ldGhvZAogICAgZGVmIGNoZWNrX29sbGFtYShjbHMp"
    "IC0+IHN0cjoKICAgICAgICAiIiJDaGVjayBpZiBPbGxhbWEgaXMgcnVubmluZy4gUmV0dXJucyBzdGF0"
    "dXMgc3RyaW5nLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0"
    "LlJlcXVlc3QoImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNw"
    "ID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MikKICAgICAgICAgICAgaWYgcmVz"
    "cC5zdGF0dXMgPT0gMjAwOgogICAgICAgICAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKckyDi"
    "gJQgcnVubmluZyBvbiBsb2NhbGhvc3Q6MTE0MzQiCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAg"
    "ICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJcg4oCUIG5vdCBydW5u"
    "aW5nIChvbmx5IG5lZWRlZCBmb3IgT2xsYW1hIG1vZGVsIHR5cGUpIgoKCiMg4pSA4pSAIE1FTU9SWSBN"
    "QU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBNZW1vcnlNYW5hZ2VyOgogICAgIiIiCiAgICBIYW5kbGVzIGFsbCBKU09OTCBt"
    "ZW1vcnkgb3BlcmF0aW9ucy4KCiAgICBGaWxlcyBtYW5hZ2VkOgogICAgICAgIG1lbW9yaWVzL21lc3Nh"
    "Z2VzLmpzb25sICAgICAgICAg4oCUIGV2ZXJ5IG1lc3NhZ2UsIHRpbWVzdGFtcGVkCiAgICAgICAgbWVt"
    "b3JpZXMvbWVtb3JpZXMuanNvbmwgICAgICAgICDigJQgZXh0cmFjdGVkIG1lbW9yeSByZWNvcmRzCiAg"
    "ICAgICAgbWVtb3JpZXMvc3RhdGUuanNvbiAgICAgICAgICAgICDigJQgZW50aXR5IHN0YXRlCiAgICAg"
    "ICAgbWVtb3JpZXMvaW5kZXguanNvbiAgICAgICAgICAgICDigJQgY291bnRzIGFuZCBtZXRhZGF0YQoK"
    "ICAgIE1lbW9yeSByZWNvcmRzIGhhdmUgdHlwZSBpbmZlcmVuY2UsIGtleXdvcmQgZXh0cmFjdGlvbiwg"
    "dGFnIGdlbmVyYXRpb24sCiAgICBuZWFyLWR1cGxpY2F0ZSBkZXRlY3Rpb24sIGFuZCByZWxldmFuY2Ug"
    "c2NvcmluZyBmb3IgY29udGV4dCBpbmplY3Rpb24uCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "Zik6CiAgICAgICAgYmFzZSAgICAgICAgICAgICA9IGNmZ19wYXRoKCJtZW1vcmllcyIpCiAgICAgICAg"
    "c2VsZi5tZXNzYWdlc19wICA9IGJhc2UgLyAibWVzc2FnZXMuanNvbmwiCiAgICAgICAgc2VsZi5tZW1v"
    "cmllc19wICA9IGJhc2UgLyAibWVtb3JpZXMuanNvbmwiCiAgICAgICAgc2VsZi5zdGF0ZV9wICAgICA9"
    "IGJhc2UgLyAic3RhdGUuanNvbiIKICAgICAgICBzZWxmLmluZGV4X3AgICAgID0gYmFzZSAvICJpbmRl"
    "eC5qc29uIgoKICAgICMg4pSA4pSAIFNUQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5zdGF0ZV9wLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gc2VsZi5f"
    "ZGVmYXVsdF9zdGF0ZSgpCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2Fkcyhz"
    "ZWxmLnN0YXRlX3AucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKCiAgICBkZWYgc2F2"
    "ZV9zdGF0ZShzZWxmLCBzdGF0ZTogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXRlX3Aud3Jp"
    "dGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0i"
    "dXRmLTgiCiAgICAgICAgKQoKICAgIGRlZiBfZGVmYXVsdF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAg"
    "ICAgIHJldHVybiB7CiAgICAgICAgICAgICJwZXJzb25hX25hbWUiOiAgICAgICAgICAgICBERUNLX05B"
    "TUUsCiAgICAgICAgICAgICJkZWNrX3ZlcnNpb24iOiAgICAgICAgICAgICBBUFBfVkVSU0lPTiwKICAg"
    "ICAgICAgICAgInNlc3Npb25fY291bnQiOiAgICAgICAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3N0"
    "YXJ0dXAiOiAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9zaHV0ZG93biI6ICAgICAg"
    "ICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3RfYWN0aXZlIjogICAgICAgICAgICAgIE5vbmUsCiAg"
    "ICAgICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAidG90YWxf"
    "bWVtb3JpZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgImludGVybmFsX25hcnJhdGl2ZSI6ICAg"
    "ICAgIHt9LAogICAgICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6IkRPUk1BTlQiLAog"
    "ICAgICAgIH0KCiAgICAjIOKUgOKUgCBNRVNTQUdFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVzc2FnZShzZWxmLCBzZXNzaW9uX2lkOiBz"
    "dHIsIHJvbGU6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICBjb250ZW50OiBzdHIsIGVtb3Rpb246"
    "IHN0ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAg"
    "ICAgICBmIm1zZ197dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAi"
    "OiAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6IHNlc3Npb25faWQsCiAg"
    "ICAgICAgICAgICJwZXJzb25hIjogICAgREVDS19OQU1FLAogICAgICAgICAgICAicm9sZSI6ICAgICAg"
    "IHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICAgY29udGVudCwKICAgICAgICAgICAgImVtb3Rp"
    "b24iOiAgICBlbW90aW9uLAogICAgICAgIH0KICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5tZXNzYWdl"
    "c19wLCByZWNvcmQpCiAgICAgICAgcmV0dXJuIHJlY29yZAoKICAgIGRlZiBsb2FkX3JlY2VudF9tZXNz"
    "YWdlcyhzZWxmLCBsaW1pdDogaW50ID0gMjApIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJl"
    "YWRfanNvbmwoc2VsZi5tZXNzYWdlc19wKVstbGltaXQ6XQoKICAgICMg4pSA4pSAIE1FTU9SSUVTIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9t"
    "ZW1vcnkoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJlY29y"
    "ZF90eXBlID0gaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKICAgICAg"
    "ICBrZXl3b3JkcyAgICA9IGV4dHJhY3Rfa2V5d29yZHModXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50"
    "X3RleHQpCiAgICAgICAgdGFncyAgICAgICAgPSBzZWxmLl9pbmZlcl90YWdzKHJlY29yZF90eXBlLCB1"
    "c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHRpdGxlICAgICAgID0gc2VsZi5faW5mZXJfdGl0bGUo"
    "cmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgc3VtbWFyeSAgICAgPSBzZWxm"
    "Ll9zdW1tYXJpemUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQpCgogICAgICAg"
    "IG1lbW9yeSA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmIm1lbV97dXVpZC51dWlk"
    "NCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiAgICAgICAgbG9jYWxfbm93X2lz"
    "bygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAgICAgIHNlc3Npb25faWQsCiAgICAgICAgICAg"
    "ICJwZXJzb25hIjogICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAidHlwZSI6ICAgICAgICAg"
    "ICAgIHJlY29yZF90eXBlLAogICAgICAgICAgICAidGl0bGUiOiAgICAgICAgICAgIHRpdGxlLAogICAg"
    "ICAgICAgICAic3VtbWFyeSI6ICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJjb250ZW50Ijog"
    "ICAgICAgICAgdXNlcl90ZXh0Wzo0MDAwXSwKICAgICAgICAgICAgImFzc2lzdGFudF9jb250ZXh0Ijph"
    "c3Npc3RhbnRfdGV4dFs6MTIwMF0sCiAgICAgICAgICAgICJrZXl3b3JkcyI6ICAgICAgICAga2V5d29y"
    "ZHMsCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgICAgdGFncywKICAgICAgICAgICAgImNvbmZp"
    "ZGVuY2UiOiAgICAgICAwLjcwIGlmIHJlY29yZF90eXBlIGluIHsKICAgICAgICAgICAgICAgICJkcmVh"
    "bSIsImlzc3VlIiwiaWRlYSIsInByZWZlcmVuY2UiLCJyZXNvbHV0aW9uIgogICAgICAgICAgICB9IGVs"
    "c2UgMC41NSwKICAgICAgICB9CgogICAgICAgIGlmIHNlbGYuX2lzX25lYXJfZHVwbGljYXRlKG1lbW9y"
    "eSk6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lbW9y"
    "aWVzX3AsIG1lbW9yeSkKICAgICAgICByZXR1cm4gbWVtb3J5CgogICAgZGVmIHNlYXJjaF9tZW1vcmll"
    "cyhzZWxmLCBxdWVyeTogc3RyLCBsaW1pdDogaW50ID0gNikgLT4gbGlzdFtkaWN0XToKICAgICAgICAi"
    "IiIKICAgICAgICBLZXl3b3JkLXNjb3JlZCBtZW1vcnkgc2VhcmNoLgogICAgICAgIFJldHVybnMgdXAg"
    "dG8gYGxpbWl0YCByZWNvcmRzIHNvcnRlZCBieSByZWxldmFuY2Ugc2NvcmUgZGVzY2VuZGluZy4KICAg"
    "ICAgICBGYWxscyBiYWNrIHRvIG1vc3QgcmVjZW50IGlmIG5vIHF1ZXJ5IHRlcm1zIG1hdGNoLgogICAg"
    "ICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApCiAgICAg"
    "ICAgaWYgbm90IHF1ZXJ5LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiBtZW1vcmllc1stbGltaXQ6"
    "XQoKICAgICAgICBxX3Rlcm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMocXVlcnksIGxpbWl0PTE2KSkK"
    "ICAgICAgICBzY29yZWQgID0gW10KCiAgICAgICAgZm9yIGl0ZW0gaW4gbWVtb3JpZXM6CiAgICAgICAg"
    "ICAgIGl0ZW1fdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcygiICIuam9pbihbCiAgICAgICAgICAg"
    "ICAgICBpdGVtLmdldCgidGl0bGUiLCAgICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJzdW1t"
    "YXJ5IiwgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoImNvbnRlbnQiLCAiIiksCiAgICAgICAg"
    "ICAgICAgICAiICIuam9pbihpdGVtLmdldCgia2V5d29yZHMiLCBbXSkpLAogICAgICAgICAgICAgICAg"
    "IiAiLmpvaW4oaXRlbS5nZXQoInRhZ3MiLCAgICAgW10pKSwKICAgICAgICAgICAgXSksIGxpbWl0PTQw"
    "KSkKCiAgICAgICAgICAgIHNjb3JlID0gbGVuKHFfdGVybXMgJiBpdGVtX3Rlcm1zKQoKICAgICAgICAg"
    "ICAgIyBCb29zdCBieSB0eXBlIG1hdGNoCiAgICAgICAgICAgIHFsID0gcXVlcnkubG93ZXIoKQogICAg"
    "ICAgICAgICBydCA9IGl0ZW0uZ2V0KCJ0eXBlIiwgIiIpCiAgICAgICAgICAgIGlmICJkcmVhbSIgIGlu"
    "IHFsIGFuZCBydCA9PSAiZHJlYW0iOiAgICBzY29yZSArPSA0CiAgICAgICAgICAgIGlmICJ0YXNrIiAg"
    "IGluIHFsIGFuZCBydCA9PSAidGFzayI6ICAgICBzY29yZSArPSAzCiAgICAgICAgICAgIGlmICJpZGVh"
    "IiAgIGluIHFsIGFuZCBydCA9PSAiaWRlYSI6ICAgICBzY29yZSArPSAyCiAgICAgICAgICAgIGlmICJs"
    "c2wiICAgIGluIHFsIGFuZCBydCBpbiB7Imlzc3VlIiwicmVzb2x1dGlvbiJ9OiBzY29yZSArPSAyCgog"
    "ICAgICAgICAgICBpZiBzY29yZSA+IDA6CiAgICAgICAgICAgICAgICBzY29yZWQuYXBwZW5kKChzY29y"
    "ZSwgaXRlbSkpCgogICAgICAgIHNjb3JlZC5zb3J0KGtleT1sYW1iZGEgeDogKHhbMF0sIHhbMV0uZ2V0"
    "KCJ0aW1lc3RhbXAiLCAiIikpLAogICAgICAgICAgICAgICAgICAgIHJldmVyc2U9VHJ1ZSkKICAgICAg"
    "ICByZXR1cm4gW2l0ZW0gZm9yIF8sIGl0ZW0gaW4gc2NvcmVkWzpsaW1pdF1dCgogICAgZGVmIGJ1aWxk"
    "X2NvbnRleHRfYmxvY2soc2VsZiwgcXVlcnk6IHN0ciwgbWF4X2NoYXJzOiBpbnQgPSAyMDAwKSAtPiBz"
    "dHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250ZXh0IHN0cmluZyBmcm9tIHJlbGV2YW50"
    "IG1lbW9yaWVzIGZvciBwcm9tcHQgaW5qZWN0aW9uLgogICAgICAgIFRydW5jYXRlcyB0byBtYXhfY2hh"
    "cnMgdG8gcHJvdGVjdCB0aGUgY29udGV4dCB3aW5kb3cuCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3Jp"
    "ZXMgPSBzZWxmLnNlYXJjaF9tZW1vcmllcyhxdWVyeSwgbGltaXQ9NCkKICAgICAgICBpZiBub3QgbWVt"
    "b3JpZXM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFsiW1JFTEVWQU5UIE1F"
    "TU9SSUVTXSJdCiAgICAgICAgdG90YWwgPSAwCiAgICAgICAgZm9yIG0gaW4gbWVtb3JpZXM6CiAgICAg"
    "ICAgICAgIGVudHJ5ID0gKAogICAgICAgICAgICAgICAgZiLigKIgW3ttLmdldCgndHlwZScsJycpLnVw"
    "cGVyKCl9XSB7bS5nZXQoJ3RpdGxlJywnJyl9OiAiCiAgICAgICAgICAgICAgICBmInttLmdldCgnc3Vt"
    "bWFyeScsJycpfSIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiB0b3RhbCArIGxlbihlbnRyeSkg"
    "PiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "ZW50cnkpCiAgICAgICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5k"
    "KCJbRU5EIE1FTU9SSUVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICAjIOKU"
    "gOKUgCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9pc19uZWFyX2R1cGxpY2F0ZShzZWxmLCBjYW5kaWRhdGU6IGRpY3QpIC0+IGJvb2w6"
    "CiAgICAgICAgcmVjZW50ID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApWy0yNTpdCiAgICAgICAg"
    "Y3QgPSBjYW5kaWRhdGUuZ2V0KCJ0aXRsZSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBjcyA9"
    "IGNhbmRpZGF0ZS5nZXQoInN1bW1hcnkiLCAiIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgZm9yIGl0"
    "ZW0gaW4gcmVjZW50OgogICAgICAgICAgICBpZiBpdGVtLmdldCgidGl0bGUiLCIiKS5sb3dlcigpLnN0"
    "cmlwKCkgPT0gY3Q6ICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiBpdGVtLmdldCgic3VtbWFyeSIs"
    "IiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjczogcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UK"
    "CiAgICBkZWYgX2luZmVyX3RhZ3Moc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdGV4dDogc3RyLAogICAg"
    "ICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0cl0pIC0+IGxpc3Rbc3RyXToKICAgICAgICB0"
    "ICAgID0gdGV4dC5sb3dlcigpCiAgICAgICAgdGFncyA9IFtyZWNvcmRfdHlwZV0KICAgICAgICBpZiAi"
    "ZHJlYW0iICAgaW4gdDogdGFncy5hcHBlbmQoImRyZWFtIikKICAgICAgICBpZiAibHNsIiAgICAgaW4g"
    "dDogdGFncy5hcHBlbmQoImxzbCIpCiAgICAgICAgaWYgInB5dGhvbiIgIGluIHQ6IHRhZ3MuYXBwZW5k"
    "KCJweXRob24iKQogICAgICAgIGlmICJnYW1lIiAgICBpbiB0OiB0YWdzLmFwcGVuZCgiZ2FtZV9pZGVh"
    "IikKICAgICAgICBpZiAic2wiICAgICAgaW4gdCBvciAic2Vjb25kIGxpZmUiIGluIHQ6IHRhZ3MuYXBw"
    "ZW5kKCJzZWNvbmRsaWZlIikKICAgICAgICBpZiBERUNLX05BTUUubG93ZXIoKSBpbiB0OiB0YWdzLmFw"
    "cGVuZChERUNLX05BTUUubG93ZXIoKSkKICAgICAgICBmb3Iga3cgaW4ga2V5d29yZHNbOjRdOgogICAg"
    "ICAgICAgICBpZiBrdyBub3QgaW4gdGFnczoKICAgICAgICAgICAgICAgIHRhZ3MuYXBwZW5kKGt3KQog"
    "ICAgICAgICMgRGVkdXBsaWNhdGUgcHJlc2VydmluZyBvcmRlcgogICAgICAgIHNlZW4sIG91dCA9IHNl"
    "dCgpLCBbXQogICAgICAgIGZvciB0YWcgaW4gdGFnczoKICAgICAgICAgICAgaWYgdGFnIG5vdCBpbiBz"
    "ZWVuOgogICAgICAgICAgICAgICAgc2Vlbi5hZGQodGFnKQogICAgICAgICAgICAgICAgb3V0LmFwcGVu"
    "ZCh0YWcpCiAgICAgICAgcmV0dXJuIG91dFs6MTJdCgogICAgZGVmIF9pbmZlcl90aXRsZShzZWxmLCBy"
    "ZWNvcmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICAga2V5d29y"
    "ZHM6IGxpc3Rbc3RyXSkgLT4gc3RyOgogICAgICAgIGRlZiBjbGVhbih3b3Jkcyk6CiAgICAgICAgICAg"
    "IHJldHVybiBbdy5zdHJpcCgiIC1fLiwhPyIpLmNhcGl0YWxpemUoKQogICAgICAgICAgICAgICAgICAg"
    "IGZvciB3IGluIHdvcmRzIGlmIGxlbih3KSA+IDJdCgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ0"
    "YXNrIjoKICAgICAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgICAgIG0gPSByZS5zZWFyY2gociJyZW1p"
    "bmQgbWUgLio/IHRvICguKykiLCB1c2VyX3RleHQsIHJlLkkpCiAgICAgICAgICAgIGlmIG06CiAgICAg"
    "ICAgICAgICAgICByZXR1cm4gZiJSZW1pbmRlcjoge20uZ3JvdXAoMSkuc3RyaXAoKVs6NjBdfSIKICAg"
    "ICAgICAgICAgcmV0dXJuICJSZW1pbmRlciBUYXNrIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJk"
    "cmVhbSI6CiAgICAgICAgICAgIHJldHVybiBmInsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6M10pKX0g"
    "RHJlYW0iLnN0cmlwKCkgb3IgIkRyZWFtIE1lbW9yeSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAi"
    "aXNzdWUiOgogICAgICAgICAgICByZXR1cm4gZiJJc3N1ZTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRz"
    "Wzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2FsIElzc3VlIgogICAgICAgIGlmIHJlY29yZF90eXBl"
    "ID09ICJyZXNvbHV0aW9uIjoKICAgICAgICAgICAgcmV0dXJuIGYiUmVzb2x1dGlvbjogeycgJy5qb2lu"
    "KGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2FsIFJlc29sdXRpb24iCiAg"
    "ICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOgogICAgICAgICAgICByZXR1cm4gZiJJZGVhOiB7"
    "JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJJZGVhIgogICAgICAgIGlm"
    "IGtleXdvcmRzOgogICAgICAgICAgICByZXR1cm4gIiAiLmpvaW4oY2xlYW4oa2V5d29yZHNbOjVdKSkg"
    "b3IgIkNvbnZlcnNhdGlvbiBNZW1vcnkiCiAgICAgICAgcmV0dXJuICJDb252ZXJzYXRpb24gTWVtb3J5"
    "IgoKICAgIGRlZiBfc3VtbWFyaXplKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3Ry"
    "LAogICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gc3RyOgogICAgICAgIHUg"
    "PSB1c2VyX3RleHQuc3RyaXAoKVs6MjIwXQogICAgICAgIGEgPSBhc3Npc3RhbnRfdGV4dC5zdHJpcCgp"
    "WzoyMjBdCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjogICAgICAgcmV0dXJuIGYiVXNl"
    "ciBkZXNjcmliZWQgYSBkcmVhbToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ0YXNrIjog"
    "ICAgICAgIHJldHVybiBmIlJlbWluZGVyL3Rhc2s6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAiaXNzdWUiOiAgICAgICByZXR1cm4gZiJUZWNobmljYWwgaXNzdWU6IHt1fSIKICAgICAgICBpZiBy"
    "ZWNvcmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6ICByZXR1cm4gZiJTb2x1dGlvbiByZWNvcmRlZDoge2Eg"
    "b3IgdX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOiAgICAgICAgcmV0dXJuIGYiSWRl"
    "YSBkaXNjdXNzZWQ6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicHJlZmVyZW5jZSI6ICBy"
    "ZXR1cm4gZiJQcmVmZXJlbmNlIG5vdGVkOiB7dX0iCiAgICAgICAgcmV0dXJuIGYiQ29udmVyc2F0aW9u"
    "OiB7dX0iCgoKIyDilIDilIAgU0VTU0lPTiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZXNzaW9uTWFuYWdlcjoKICAgICIi"
    "IgogICAgTWFuYWdlcyBjb252ZXJzYXRpb24gc2Vzc2lvbnMuCgogICAgQXV0by1zYXZlOiBldmVyeSAx"
    "MCBtaW51dGVzIChBUFNjaGVkdWxlciksIG1pZG5pZ2h0LXRvLW1pZG5pZ2h0IGJvdW5kYXJ5LgogICAg"
    "RmlsZTogc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubCDigJQgb3ZlcndyaXRlcyBvbiBlYWNoIHNhdmUu"
    "CiAgICBJbmRleDogc2Vzc2lvbnMvc2Vzc2lvbl9pbmRleC5qc29uIOKAlCBvbmUgZW50cnkgcGVyIGRh"
    "eS4KCiAgICBTZXNzaW9ucyBhcmUgbG9hZGVkIGFzIGNvbnRleHQgaW5qZWN0aW9uIChub3QgcmVhbCBt"
    "ZW1vcnkpIHVudGlsCiAgICB0aGUgU1FMaXRlL0Nocm9tYURCIHN5c3RlbSBpcyBidWlsdCBpbiBQaGFz"
    "ZSAyLgogICAgIiIiCgogICAgQVVUT1NBVkVfSU5URVJWQUwgPSAxMCAgICMgbWludXRlcwoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9zZXNzaW9uc19kaXIgID0gY2ZnX3BhdGgoInNl"
    "c3Npb25zIikKICAgICAgICBzZWxmLl9pbmRleF9wYXRoICAgID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8g"
    "InNlc3Npb25faW5kZXguanNvbiIKICAgICAgICBzZWxmLl9zZXNzaW9uX2lkICAgID0gZiJzZXNzaW9u"
    "X3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9j"
    "dXJyZW50X2RhdGUgID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgc2VsZi5fbWVzc2Fn"
    "ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsOiBPcHRpb25hbFtz"
    "dHJdID0gTm9uZSAgIyBkYXRlIG9mIGxvYWRlZCBqb3VybmFsCgogICAgIyDilIDilIAgQ1VSUkVOVCBT"
    "RVNTSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFkZF9tZXNzYWdlKHNlbGYsIHJv"
    "bGU6IHN0ciwgY29udGVudDogc3RyLAogICAgICAgICAgICAgICAgICAgIGVtb3Rpb246IHN0ciA9ICIi"
    "LCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgIHNlbGYuX21lc3NhZ2VzLmFwcGVu"
    "ZCh7CiAgICAgICAgICAgICJpZCI6ICAgICAgICBmIm1zZ197dXVpZC51dWlkNCgpLmhleFs6OF19IiwK"
    "ICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRpbWVzdGFtcCBvciBsb2NhbF9ub3dfaXNvKCksCiAgICAg"
    "ICAgICAgICJyb2xlIjogICAgICByb2xlLAogICAgICAgICAgICAiY29udGVudCI6ICAgY29udGVudCwK"
    "ICAgICAgICAgICAgImVtb3Rpb24iOiAgIGVtb3Rpb24sCiAgICAgICAgfSkKCiAgICBkZWYgZ2V0X2hp"
    "c3Rvcnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm4gaGlzdG9y"
    "eSBpbiBMTE0tZnJpZW5kbHkgZm9ybWF0LgogICAgICAgIFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFu"
    "dCIsICJjb250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHJldHVybiBbCiAgICAgICAg"
    "ICAgIHsicm9sZSI6IG1bInJvbGUiXSwgImNvbnRlbnQiOiBtWyJjb250ZW50Il19CiAgICAgICAgICAg"
    "IGZvciBtIGluIHNlbGYuX21lc3NhZ2VzCiAgICAgICAgICAgIGlmIG1bInJvbGUiXSBpbiAoInVzZXIi"
    "LCAiYXNzaXN0YW50IikKICAgICAgICBdCgogICAgQHByb3BlcnR5CiAgICBkZWYgc2Vzc2lvbl9pZChz"
    "ZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nlc3Npb25faWQKCiAgICBAcHJvcGVydHkK"
    "ICAgIGRlZiBtZXNzYWdlX2NvdW50KHNlbGYpIC0+IGludDoKICAgICAgICByZXR1cm4gbGVuKHNlbGYu"
    "X21lc3NhZ2VzKQoKICAgICMg4pSA4pSAIFNBVkUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgc2F2ZShzZWxmLCBhaV9nZW5lcmF0ZWRf"
    "bmFtZTogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2F2ZSBjdXJyZW50IHNl"
    "c3Npb24gdG8gc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubC4KICAgICAgICBPdmVyd3JpdGVzIHRoZSBm"
    "aWxlIGZvciB0b2RheSDigJQgZWFjaCBzYXZlIGlzIGEgZnVsbCBzbmFwc2hvdC4KICAgICAgICBVcGRh"
    "dGVzIHNlc3Npb25faW5kZXguanNvbi4KICAgICAgICAiIiIKICAgICAgICB0b2RheSA9IGRhdGUudG9k"
    "YXkoKS5pc29mb3JtYXQoKQogICAgICAgIG91dF9wYXRoID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gZiJ7"
    "dG9kYXl9Lmpzb25sIgoKICAgICAgICAjIFdyaXRlIGFsbCBtZXNzYWdlcwogICAgICAgIHdyaXRlX2pz"
    "b25sKG91dF9wYXRoLCBzZWxmLl9tZXNzYWdlcykKCiAgICAgICAgIyBVcGRhdGUgaW5kZXgKICAgICAg"
    "ICBpbmRleCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGV4aXN0aW5nID0gbmV4dCgKICAgICAg"
    "ICAgICAgKHMgZm9yIHMgaW4gaW5kZXhbInNlc3Npb25zIl0gaWYgc1siZGF0ZSJdID09IHRvZGF5KSwg"
    "Tm9uZQogICAgICAgICkKCiAgICAgICAgbmFtZSA9IGFpX2dlbmVyYXRlZF9uYW1lIG9yIGV4aXN0aW5n"
    "LmdldCgibmFtZSIsICIiKSBpZiBleGlzdGluZyBlbHNlICIiCiAgICAgICAgaWYgbm90IG5hbWUgYW5k"
    "IHNlbGYuX21lc3NhZ2VzOgogICAgICAgICAgICAjIEF1dG8tbmFtZSBmcm9tIGZpcnN0IHVzZXIgbWVz"
    "c2FnZSAoZmlyc3QgNSB3b3JkcykKICAgICAgICAgICAgZmlyc3RfdXNlciA9IG5leHQoCiAgICAgICAg"
    "ICAgICAgICAobVsiY29udGVudCJdIGZvciBtIGluIHNlbGYuX21lc3NhZ2VzIGlmIG1bInJvbGUiXSA9"
    "PSAidXNlciIpLAogICAgICAgICAgICAgICAgIiIKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3Jk"
    "cyA9IGZpcnN0X3VzZXIuc3BsaXQoKVs6NV0KICAgICAgICAgICAgbmFtZSAgPSAiICIuam9pbih3b3Jk"
    "cykgaWYgd29yZHMgZWxzZSBmIlNlc3Npb24ge3RvZGF5fSIKCiAgICAgICAgZW50cnkgPSB7CiAgICAg"
    "ICAgICAgICJkYXRlIjogICAgICAgICAgdG9kYXksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAg"
    "c2VsZi5fc2Vzc2lvbl9pZCwKICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgICBuYW1lLAogICAgICAg"
    "ICAgICAibWVzc2FnZV9jb3VudCI6IGxlbihzZWxmLl9tZXNzYWdlcyksCiAgICAgICAgICAgICJmaXJz"
    "dF9tZXNzYWdlIjogKHNlbGYuX21lc3NhZ2VzWzBdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICAgICAgImxhc3Rf"
    "bWVzc2FnZSI6ICAoc2VsZi5fbWVzc2FnZXNbLTFdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICB9CgogICAgICAg"
    "IGlmIGV4aXN0aW5nOgogICAgICAgICAgICBpZHggPSBpbmRleFsic2Vzc2lvbnMiXS5pbmRleChleGlz"
    "dGluZykKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl1baWR4XSA9IGVudHJ5CiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl0uaW5zZXJ0KDAsIGVudHJ5KQoKICAgICAgICAj"
    "IEtlZXAgbGFzdCAzNjUgZGF5cyBpbiBpbmRleAogICAgICAgIGluZGV4WyJzZXNzaW9ucyJdID0gaW5k"
    "ZXhbInNlc3Npb25zIl1bOjM2NV0KICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQoKICAgICMg"
    "4pSA4pSAIExPQUQgLyBKT1VSTkFMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxp"
    "c3Rfc2Vzc2lvbnMoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiJSZXR1cm4gYWxsIHNlc3Np"
    "b25zIGZyb20gaW5kZXgsIG5ld2VzdCBmaXJzdC4iIiIKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZF9p"
    "bmRleCgpLmdldCgic2Vzc2lvbnMiLCBbXSkKCiAgICBkZWYgbG9hZF9zZXNzaW9uX2FzX2NvbnRleHQo"
    "c2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIpIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBMb2FkIGEg"
    "cGFzdCBzZXNzaW9uIGFzIGEgY29udGV4dCBpbmplY3Rpb24gc3RyaW5nLgogICAgICAgIFJldHVybnMg"
    "Zm9ybWF0dGVkIHRleHQgdG8gcHJlcGVuZCB0byB0aGUgc3lzdGVtIHByb21wdC4KICAgICAgICBUaGlz"
    "IGlzIE5PVCByZWFsIG1lbW9yeSDigJQgaXQncyBhIHRlbXBvcmFyeSBjb250ZXh0IHdpbmRvdyBpbmpl"
    "Y3Rpb24KICAgICAgICB1bnRpbCB0aGUgUGhhc2UgMiBtZW1vcnkgc3lzdGVtIGlzIGJ1aWx0LgogICAg"
    "ICAgICIiIgogICAgICAgIHBhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmIntzZXNzaW9uX2RhdGV9"
    "Lmpzb25sIgogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gIiIK"
    "CiAgICAgICAgbWVzc2FnZXMgPSByZWFkX2pzb25sKHBhdGgpCiAgICAgICAgc2VsZi5fbG9hZGVkX2pv"
    "dXJuYWwgPSBzZXNzaW9uX2RhdGUKCiAgICAgICAgbGluZXMgPSBbZiJbSk9VUk5BTCBMT0FERUQg4oCU"
    "IHtzZXNzaW9uX2RhdGV9XSIsCiAgICAgICAgICAgICAgICAgIlRoZSBmb2xsb3dpbmcgaXMgYSByZWNv"
    "cmQgb2YgYSBwcmlvciBjb252ZXJzYXRpb24uIiwKICAgICAgICAgICAgICAgICAiVXNlIHRoaXMgYXMg"
    "Y29udGV4dCBmb3IgdGhlIGN1cnJlbnQgc2Vzc2lvbjpcbiJdCgogICAgICAgICMgSW5jbHVkZSB1cCB0"
    "byBsYXN0IDMwIG1lc3NhZ2VzIGZyb20gdGhhdCBzZXNzaW9uCiAgICAgICAgZm9yIG1zZyBpbiBtZXNz"
    "YWdlc1stMzA6XToKICAgICAgICAgICAgcm9sZSAgICA9IG1zZy5nZXQoInJvbGUiLCAiPyIpLnVwcGVy"
    "KCkKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIilbOjMwMF0KICAgICAg"
    "ICAgICAgdHMgICAgICA9IG1zZy5nZXQoInRpbWVzdGFtcCIsICIiKVs6MTZdCiAgICAgICAgICAgIGxp"
    "bmVzLmFwcGVuZChmIlt7dHN9XSB7cm9sZX06IHtjb250ZW50fSIpCgogICAgICAgIGxpbmVzLmFwcGVu"
    "ZCgiW0VORCBKT1VSTkFMXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihsaW5lcykKCiAgICBkZWYg"
    "Y2xlYXJfbG9hZGVkX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2FkZWRfam91"
    "cm5hbCA9IE5vbmUKCiAgICBAcHJvcGVydHkKICAgIGRlZiBsb2FkZWRfam91cm5hbF9kYXRlKHNlbGYp"
    "IC0+IE9wdGlvbmFsW3N0cl06CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZF9qb3VybmFsCgogICAg"
    "ZGVmIHJlbmFtZV9zZXNzaW9uKHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyLCBuZXdfbmFtZTogc3RyKSAt"
    "PiBib29sOgogICAgICAgICIiIlJlbmFtZSBhIHNlc3Npb24gaW4gdGhlIGluZGV4LiBSZXR1cm5zIFRy"
    "dWUgb24gc3VjY2Vzcy4iIiIKICAgICAgICBpbmRleCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAg"
    "IGZvciBlbnRyeSBpbiBpbmRleFsic2Vzc2lvbnMiXToKICAgICAgICAgICAgaWYgZW50cnlbImRhdGUi"
    "XSA9PSBzZXNzaW9uX2RhdGU6CiAgICAgICAgICAgICAgICBlbnRyeVsibmFtZSJdID0gbmV3X25hbWVb"
    "OjgwXQogICAgICAgICAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKICAgICAgICAgICAgICAg"
    "IHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgIyDilIDilIAgSU5ERVggSEVMUEVS"
    "UyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9pbmRleChzZWxmKSAt"
    "PiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLl9pbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgICAg"
    "ICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpz"
    "b24ubG9hZHMoCiAgICAgICAgICAgICAgICBzZWxmLl9pbmRleF9wYXRoLnJlYWRfdGV4dChlbmNvZGlu"
    "Zz0idXRmLTgiKQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KCiAgICBkZWYgX3NhdmVfaW5kZXgoc2VsZiwgaW5kZXg6"
    "IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faW5kZXhfcGF0aC53cml0ZV90ZXh0KAogICAgICAg"
    "ICAgICBqc29uLmR1bXBzKGluZGV4LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICAp"
    "CgoKIyDilIDilIAgTEVTU09OUyBMRUFSTkVEIERBVEFCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBMZXNzb25zTGVhcm5lZERCOgogICAgIiIiCiAgICBQZXJzaXN0ZW50IGtub3ds"
    "ZWRnZSBiYXNlIGZvciBjb2RlIGxlc3NvbnMsIHJ1bGVzLCBhbmQgcmVzb2x1dGlvbnMuCgogICAgQ29s"
    "dW1ucyBwZXIgcmVjb3JkOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBlbnZpcm9ubWVudCAoTFNMfFB5"
    "dGhvbnxQeVNpZGU2fC4uLiksIGxhbmd1YWdlLAogICAgICAgIHJlZmVyZW5jZV9rZXkgKHNob3J0IHVu"
    "aXF1ZSB0YWcpLCBzdW1tYXJ5LCBmdWxsX3J1bGUsCiAgICAgICAgcmVzb2x1dGlvbiwgbGluaywgdGFn"
    "cwoKICAgIFF1ZXJpZWQgRklSU1QgYmVmb3JlIGFueSBjb2RlIHNlc3Npb24gaW4gdGhlIHJlbGV2YW50"
    "IGxhbmd1YWdlLgogICAgVGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBsaXZlcyBoZXJlLgogICAgR3Jv"
    "d2luZywgbm9uLWR1cGxpY2F0aW5nLCBzZWFyY2hhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJsZXNzb25z"
    "X2xlYXJuZWQuanNvbmwiCgogICAgZGVmIGFkZChzZWxmLCBlbnZpcm9ubWVudDogc3RyLCBsYW5ndWFn"
    "ZTogc3RyLCByZWZlcmVuY2Vfa2V5OiBzdHIsCiAgICAgICAgICAgIHN1bW1hcnk6IHN0ciwgZnVsbF9y"
    "dWxlOiBzdHIsIHJlc29sdXRpb246IHN0ciA9ICIiLAogICAgICAgICAgICBsaW5rOiBzdHIgPSAiIiwg"
    "dGFnczogbGlzdCA9IE5vbmUpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgIGYibGVzc29uX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAg"
    "ICAgImNyZWF0ZWRfYXQiOiAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJlbnZpcm9ubWVu"
    "dCI6ICAgZW52aXJvbm1lbnQsCiAgICAgICAgICAgICJsYW5ndWFnZSI6ICAgICAgbGFuZ3VhZ2UsCiAg"
    "ICAgICAgICAgICJyZWZlcmVuY2Vfa2V5IjogcmVmZXJlbmNlX2tleSwKICAgICAgICAgICAgInN1bW1h"
    "cnkiOiAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiZnVsbF9ydWxlIjogICAgIGZ1bGxfcnVsZSwK"
    "ICAgICAgICAgICAgInJlc29sdXRpb24iOiAgICByZXNvbHV0aW9uLAogICAgICAgICAgICAibGluayI6"
    "ICAgICAgICAgIGxpbmssCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgdGFncyBvciBbXSwKICAg"
    "ICAgICB9CiAgICAgICAgaWYgbm90IHNlbGYuX2lzX2R1cGxpY2F0ZShyZWZlcmVuY2Vfa2V5KToKICAg"
    "ICAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYuX3BhdGgsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVj"
    "b3JkCgogICAgZGVmIHNlYXJjaChzZWxmLCBxdWVyeTogc3RyID0gIiIsIGVudmlyb25tZW50OiBzdHIg"
    "PSAiIiwKICAgICAgICAgICAgICAgbGFuZ3VhZ2U6IHN0ciA9ICIiKSAtPiBsaXN0W2RpY3RdOgogICAg"
    "ICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgcmVzdWx0cyA9IFtdCiAg"
    "ICAgICAgcSA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAg"
    "ICBpZiBlbnZpcm9ubWVudCBhbmQgci5nZXQoImVudmlyb25tZW50IiwiIikubG93ZXIoKSAhPSBlbnZp"
    "cm9ubWVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbGFu"
    "Z3VhZ2UgYW5kIHIuZ2V0KCJsYW5ndWFnZSIsIiIpLmxvd2VyKCkgIT0gbGFuZ3VhZ2UubG93ZXIoKToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIHE6CiAgICAgICAgICAgICAgICBo"
    "YXlzdGFjayA9ICIgIi5qb2luKFsKICAgICAgICAgICAgICAgICAgICByLmdldCgic3VtbWFyeSIsIiIp"
    "LAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJmdWxsX3J1bGUiLCIiKSwKICAgICAgICAgICAgICAg"
    "ICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIpLAogICAgICAgICAgICAgICAgICAgICIgIi5qb2lu"
    "KHIuZ2V0KCJ0YWdzIixbXSkpLAogICAgICAgICAgICAgICAgXSkubG93ZXIoKQogICAgICAgICAgICAg"
    "ICAgaWYgcSBub3QgaW4gaGF5c3RhY2s6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAg"
    "ICAgICAgcmVzdWx0cy5hcHBlbmQocikKICAgICAgICByZXR1cm4gcmVzdWx0cwoKICAgIGRlZiBnZXRf"
    "YWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5fcGF0"
    "aCkKCiAgICBkZWYgZGVsZXRlKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBib29sOgogICAgICAgIHJl"
    "Y29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgZmlsdGVyZWQgPSBbciBmb3IgciBp"
    "biByZWNvcmRzIGlmIHIuZ2V0KCJpZCIpICE9IHJlY29yZF9pZF0KICAgICAgICBpZiBsZW4oZmlsdGVy"
    "ZWQpIDwgbGVuKHJlY29yZHMpOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBmaWx0"
    "ZXJlZCkKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYg"
    "YnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2Uoc2VsZiwgbGFuZ3VhZ2U6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBtYXhfY2hhcnM6IGludCA9IDE1MDApIC0+IHN0cjoKICAgICAg"
    "ICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIG9mIGFsbCBydWxlcyBmb3IgYSBnaXZl"
    "biBsYW5ndWFnZS4KICAgICAgICBGb3IgaW5qZWN0aW9uIGludG8gc3lzdGVtIHByb21wdCBiZWZvcmUg"
    "Y29kZSBzZXNzaW9ucy4KICAgICAgICAiIiIKICAgICAgICByZWNvcmRzID0gc2VsZi5zZWFyY2gobGFu"
    "Z3VhZ2U9bGFuZ3VhZ2UpCiAgICAgICAgaWYgbm90IHJlY29yZHM6CiAgICAgICAgICAgIHJldHVybiAi"
    "IgoKICAgICAgICBwYXJ0cyA9IFtmIlt7bGFuZ3VhZ2UudXBwZXIoKX0gUlVMRVMg4oCUIEFQUExZIEJF"
    "Rk9SRSBXUklUSU5HIENPREVdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgciBpbiByZWNv"
    "cmRzOgogICAgICAgICAgICBlbnRyeSA9IGYi4oCiIHtyLmdldCgncmVmZXJlbmNlX2tleScsJycpfTog"
    "e3IuZ2V0KCdmdWxsX3J1bGUnLCcnKX0iCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+"
    "IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChl"
    "bnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "ZiJbRU5EIHtsYW5ndWFnZS51cHBlcigpfSBSVUxFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4o"
    "cGFydHMpCgogICAgZGVmIF9pc19kdXBsaWNhdGUoc2VsZiwgcmVmZXJlbmNlX2tleTogc3RyKSAtPiBi"
    "b29sOgogICAgICAgIHJldHVybiBhbnkoCiAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5Iiwi"
    "IikubG93ZXIoKSA9PSByZWZlcmVuY2Vfa2V5Lmxvd2VyKCkKICAgICAgICAgICAgZm9yIHIgaW4gcmVh"
    "ZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICkKCiAgICBkZWYgc2VlZF9sc2xfcnVsZXMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTZWVkIHRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQg"
    "b24gZmlyc3QgcnVuIGlmIHRoZSBEQiBpcyBlbXB0eS4KICAgICAgICBUaGVzZSBhcmUgdGhlIGhhcmQg"
    "cnVsZXMgZnJvbSB0aGUgcHJvamVjdCBzdGFuZGluZyBydWxlcy4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiByZWFkX2pzb25sKHNlbGYuX3BhdGgpOgogICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBzZWVk"
    "ZWQKCiAgICAgICAgbHNsX3J1bGVzID0gWwogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVEVS"
    "TkFSWSIsCiAgICAgICAgICAgICAiTm8gdGVybmFyeSBvcGVyYXRvcnMgaW4gTFNMIiwKICAgICAgICAg"
    "ICAgICJOZXZlciB1c2UgdGhlIHRlcm5hcnkgb3BlcmF0b3IgKD86KSBpbiBMU0wgc2NyaXB0cy4gIgog"
    "ICAgICAgICAgICAgIlVzZSBpZi9lbHNlIGJsb2NrcyBpbnN0ZWFkLiBMU0wgZG9lcyBub3Qgc3VwcG9y"
    "dCB0ZXJuYXJ5LiIsCiAgICAgICAgICAgICAiUmVwbGFjZSB3aXRoIGlmL2Vsc2UgYmxvY2suIiwgIiIp"
    "LAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fRk9SRUFDSCIsCiAgICAgICAgICAgICAiTm8g"
    "Zm9yZWFjaCBsb29wcyBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBoYXMgbm8gZm9yZWFjaCBsb29w"
    "IGNvbnN0cnVjdC4gVXNlIGludGVnZXIgaW5kZXggd2l0aCAiCiAgICAgICAgICAgICAibGxHZXRMaXN0"
    "TGVuZ3RoKCkgYW5kIGEgZm9yIG9yIHdoaWxlIGxvb3AuIiwKICAgICAgICAgICAgICJVc2U6IGZvcihp"
    "bnRlZ2VyIGk9MDsgaTxsbEdldExpc3RMZW5ndGgobXlMaXN0KTsgaSsrKSIsICIiKSwKICAgICAgICAg"
    "ICAgKCJMU0wiLCAiTFNMIiwgIk5PX0dMT0JBTF9BU1NJR05fRlJPTV9GVU5DIiwKICAgICAgICAgICAg"
    "ICJObyBnbG9iYWwgdmFyaWFibGUgYXNzaWdubWVudHMgZnJvbSBmdW5jdGlvbiBjYWxscyIsCiAgICAg"
    "ICAgICAgICAiR2xvYmFsIHZhcmlhYmxlIGluaXRpYWxpemF0aW9uIGluIExTTCBjYW5ub3QgY2FsbCBm"
    "dW5jdGlvbnMuICIKICAgICAgICAgICAgICJJbml0aWFsaXplIGdsb2JhbHMgd2l0aCBsaXRlcmFsIHZh"
    "bHVlcyBvbmx5LiAiCiAgICAgICAgICAgICAiQXNzaWduIGZyb20gZnVuY3Rpb25zIGluc2lkZSBldmVu"
    "dCBoYW5kbGVycyBvciBvdGhlciBmdW5jdGlvbnMuIiwKICAgICAgICAgICAgICJNb3ZlIHRoZSBhc3Np"
    "Z25tZW50IGludG8gYW4gZXZlbnQgaGFuZGxlciAoc3RhdGVfZW50cnksIGV0Yy4pIiwgIiIpLAogICAg"
    "ICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVk9JRF9LRVlXT1JEIiwKICAgICAgICAgICAgICJObyB2"
    "b2lkIGtleXdvcmQgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgZG9lcyBub3QgaGF2ZSBhIHZvaWQg"
    "a2V5d29yZCBmb3IgZnVuY3Rpb24gcmV0dXJuIHR5cGVzLiAiCiAgICAgICAgICAgICAiRnVuY3Rpb25z"
    "IHRoYXQgcmV0dXJuIG5vdGhpbmcgc2ltcGx5IG9taXQgdGhlIHJldHVybiB0eXBlLiIsCiAgICAgICAg"
    "ICAgICAiUmVtb3ZlICd2b2lkJyBmcm9tIGZ1bmN0aW9uIHNpZ25hdHVyZS4gIgogICAgICAgICAgICAg"
    "ImUuZy4gbXlGdW5jKCkgeyAuLi4gfSBub3Qgdm9pZCBteUZ1bmMoKSB7IC4uLiB9IiwgIiIpLAogICAg"
    "ICAgICAgICAoIkxTTCIsICJMU0wiLCAiQ09NUExFVEVfU0NSSVBUU19PTkxZIiwKICAgICAgICAgICAg"
    "ICJBbHdheXMgcHJvdmlkZSBjb21wbGV0ZSBzY3JpcHRzLCBuZXZlciBwYXJ0aWFsIGVkaXRzIiwKICAg"
    "ICAgICAgICAgICJXaGVuIHdyaXRpbmcgb3IgZWRpdGluZyBMU0wgc2NyaXB0cywgYWx3YXlzIG91dHB1"
    "dCB0aGUgY29tcGxldGUgIgogICAgICAgICAgICAgInNjcmlwdC4gTmV2ZXIgcHJvdmlkZSBwYXJ0aWFs"
    "IHNuaXBwZXRzIG9yICdhZGQgdGhpcyBzZWN0aW9uJyAiCiAgICAgICAgICAgICAiaW5zdHJ1Y3Rpb25z"
    "LiBUaGUgZnVsbCBzY3JpcHQgbXVzdCBiZSBjb3B5LXBhc3RlIHJlYWR5LiIsCiAgICAgICAgICAgICAi"
    "V3JpdGUgdGhlIGVudGlyZSBzY3JpcHQgZnJvbSB0b3AgdG8gYm90dG9tLiIsICIiKSwKICAgICAgICBd"
    "CgogICAgICAgIGZvciBlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9u"
    "LCBsaW5rIGluIGxzbF9ydWxlczoKICAgICAgICAgICAgc2VsZi5hZGQoZW52LCBsYW5nLCByZWYsIHN1"
    "bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluaywKICAgICAgICAgICAgICAgICAgICAgdGFn"
    "cz1bImxzbCIsICJmb3JiaWRkZW4iLCAic3RhbmRpbmdfcnVsZSJdKQoKCiMg4pSA4pSAIFRBU0sgTUFO"
    "QUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgVGFza01hbmFnZXI6CiAgICAiIiIKICAgIFRhc2svcmVtaW5kZXIgQ1JVRCBh"
    "bmQgZHVlLWV2ZW50IGRldGVjdGlvbi4KCiAgICBGaWxlOiBtZW1vcmllcy90YXNrcy5qc29ubAoKICAg"
    "IFRhc2sgcmVjb3JkIGZpZWxkczoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZHVlX2F0LCBwcmVfdHJp"
    "Z2dlciAoMW1pbiBiZWZvcmUpLAogICAgICAgIHRleHQsIHN0YXR1cyAocGVuZGluZ3x0cmlnZ2VyZWR8"
    "c25vb3plZHxjb21wbGV0ZWR8Y2FuY2VsbGVkKSwKICAgICAgICBhY2tub3dsZWRnZWRfYXQsIHJldHJ5"
    "X2NvdW50LCBsYXN0X3RyaWdnZXJlZF9hdCwgbmV4dF9yZXRyeV9hdCwKICAgICAgICBzb3VyY2UgKGxv"
    "Y2FsfGdvb2dsZSksIGdvb2dsZV9ldmVudF9pZCwgc3luY19zdGF0dXMsIG1ldGFkYXRhCgogICAgRHVl"
    "LWV2ZW50IGN5Y2xlOgogICAgICAgIC0gUHJlLXRyaWdnZXI6IDEgbWludXRlIGJlZm9yZSBkdWUg4oaS"
    "IGFubm91bmNlIHVwY29taW5nCiAgICAgICAgLSBEdWUgdHJpZ2dlcjogYXQgZHVlIHRpbWUg4oaSIGFs"
    "ZXJ0IHNvdW5kICsgQUkgY29tbWVudGFyeQogICAgICAgIC0gMy1taW51dGUgd2luZG93OiBpZiBub3Qg"
    "YWNrbm93bGVkZ2VkIOKGkiBzbm9vemUKICAgICAgICAtIDEyLW1pbnV0ZSByZXRyeTogcmUtdHJpZ2dl"
    "cgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdf"
    "cGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29ubCIKCiAgICAjIOKUgOKUgCBDUlVEIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxv"
    "YWRfYWxsKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgbm9ybWFsaXplZCA9IFtdCiAgICAg"
    "ICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKHQsIGRpY3QpOgog"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgImlkIiBub3QgaW4gdDoKICAgICAg"
    "ICAgICAgICAgIHRbImlkIl0gPSBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iCiAgICAgICAg"
    "ICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAjIE5vcm1hbGl6ZSBmaWVsZCBuYW1lcwog"
    "ICAgICAgICAgICBpZiAiZHVlX2F0IiBub3QgaW4gdDoKICAgICAgICAgICAgICAgIHRbImR1ZV9hdCJd"
    "ID0gdC5nZXQoImR1ZSIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICB0"
    "LnNldGRlZmF1bHQoInN0YXR1cyIsICAgICAgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0"
    "ZGVmYXVsdCgicmV0cnlfY291bnQiLCAgICAgIDApCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiYWNr"
    "bm93bGVkZ2VkX2F0IiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibGFzdF90cmlnZ2Vy"
    "ZWRfYXQiLE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibmV4dF9yZXRyeV9hdCIsICAgIE5v"
    "bmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicHJlX2Fubm91bmNlZCIsICAgIEZhbHNlKQogICAg"
    "ICAgICAgICB0LnNldGRlZmF1bHQoInNvdXJjZSIsICAgICAgICAgICAibG9jYWwiKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoImdvb2dsZV9ldmVudF9pZCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRl"
    "ZmF1bHQoInN5bmNfc3RhdHVzIiwgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVs"
    "dCgibWV0YWRhdGEiLCAgICAgICAgIHt9KQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImNyZWF0ZWRf"
    "YXQiLCAgICAgICBsb2NhbF9ub3dfaXNvKCkpCgogICAgICAgICAgICAjIENvbXB1dGUgcHJlX3RyaWdn"
    "ZXIgaWYgbWlzc2luZwogICAgICAgICAgICBpZiB0LmdldCgiZHVlX2F0IikgYW5kIG5vdCB0LmdldCgi"
    "cHJlX3RyaWdnZXIiKToKICAgICAgICAgICAgICAgIGR0ID0gcGFyc2VfaXNvKHRbImR1ZV9hdCJdKQog"
    "ICAgICAgICAgICAgICAgaWYgZHQ6CiAgICAgICAgICAgICAgICAgICAgcHJlID0gZHQgLSB0aW1lZGVs"
    "dGEobWludXRlcz0xKQogICAgICAgICAgICAgICAgICAgIHRbInByZV90cmlnZ2VyIl0gPSBwcmUuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQoKICAgICAgICAgICAgbm9ybWFsaXplZC5hcHBlbmQodCkKCiAgICAgICAgaWYgY2hhbmdlZDoKICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgbm9ybWFsaXplZCkKICAgICAgICByZXR1cm4g"
    "bm9ybWFsaXplZAoKICAgIGRlZiBzYXZlX2FsbChzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9u"
    "ZToKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCB0YXNrcykKCiAgICBkZWYgYWRkKHNlbGYs"
    "IHRleHQ6IHN0ciwgZHVlX2R0OiBkYXRldGltZSwKICAgICAgICAgICAgc291cmNlOiBzdHIgPSAibG9j"
    "YWwiKSAtPiBkaWN0OgogICAgICAgIHByZSA9IGR1ZV9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAg"
    "ICAgICAgdGFzayA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmInRhc2tfe3V1aWQu"
    "dXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgIGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICBkdWVfZHQuaXNvZm9ybWF0KHRp"
    "bWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6ICAgICAgcHJlLmlzb2Zv"
    "cm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgIHRl"
    "eHQuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAicGVuZGluZyIsCiAgICAg"
    "ICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgTm9uZSwKICAgICAgICAgICAgInJldHJ5X2NvdW50Ijog"
    "ICAgICAwLAogICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOk5vbmUsCiAgICAgICAgICAgICJu"
    "ZXh0X3JldHJ5X2F0IjogICAgTm9uZSwKICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiAgICBGYWxz"
    "ZSwKICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICBzb3VyY2UsCiAgICAgICAgICAgICJnb29n"
    "bGVfZXZlbnRfaWQiOiAgTm9uZSwKICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAicGVuZGlu"
    "ZyIsCiAgICAgICAgICAgICJtZXRhZGF0YSI6ICAgICAgICAge30sCiAgICAgICAgfQogICAgICAgIHRh"
    "c2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgc2Vs"
    "Zi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gdGFzawoKICAgIGRlZiB1cGRhdGVfc3RhdHVz"
    "KHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhY2tu"
    "b3dsZWRnZWQ6IGJvb2wgPSBGYWxzZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBz"
    "ZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQo"
    "ImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdID0gc3RhdHVzCiAgICAg"
    "ICAgICAgICAgICBpZiBhY2tub3dsZWRnZWQ6CiAgICAgICAgICAgICAgICAgICAgdFsiYWNrbm93bGVk"
    "Z2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNv"
    "bXBsZXRlKHNlbGYsIHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3Mg"
    "PSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5n"
    "ZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdICAgICAgICAgID0g"
    "ImNvbXBsZXRlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93"
    "X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAg"
    "cmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjYW5jZWwoc2VsZiwgdGFza19pZDog"
    "c3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgog"
    "ICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY2FuY2VsbGVkIgogICAgICAgICAg"
    "ICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAg"
    "IHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVy"
    "biBOb25lCgogICAgZGVmIGNsZWFyX2NvbXBsZXRlZChzZWxmKSAtPiBpbnQ6CiAgICAgICAgdGFza3Mg"
    "ICAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBrZXB0ICAgICA9IFt0IGZvciB0IGluIHRhc2tzCiAg"
    "ICAgICAgICAgICAgICAgICAgaWYgdC5nZXQoInN0YXR1cyIpIG5vdCBpbiB7ImNvbXBsZXRlZCIsImNh"
    "bmNlbGxlZCJ9XQogICAgICAgIHJlbW92ZWQgID0gbGVuKHRhc2tzKSAtIGxlbihrZXB0KQogICAgICAg"
    "IGlmIHJlbW92ZWQ6CiAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwoa2VwdCkKICAgICAgICByZXR1cm4g"
    "cmVtb3ZlZAoKICAgIGRlZiB1cGRhdGVfZ29vZ2xlX3N5bmMoc2VsZiwgdGFza19pZDogc3RyLCBzeW5j"
    "X3N0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICBnb29nbGVfZXZlbnRfaWQ6IHN0"
    "ciA9ICIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICBlcnJvcjogc3RyID0gIiIpIC0+IE9wdGlv"
    "bmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4g"
    "dGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAg"
    "ICB0WyJzeW5jX3N0YXR1cyJdICAgID0gc3luY19zdGF0dXMKICAgICAgICAgICAgICAgIHRbImxhc3Rf"
    "c3luY2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIGlmIGdvb2dsZV9ldmVu"
    "dF9pZDoKICAgICAgICAgICAgICAgICAgICB0WyJnb29nbGVfZXZlbnRfaWQiXSA9IGdvb2dsZV9ldmVu"
    "dF9pZAogICAgICAgICAgICAgICAgaWYgZXJyb3I6CiAgICAgICAgICAgICAgICAgICAgdC5zZXRkZWZh"
    "dWx0KCJtZXRhZGF0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgIHRbIm1ldGFkYXRhIl1bImdvb2ds"
    "ZV9zeW5jX2Vycm9yIl0gPSBlcnJvcls6MjQwXQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0"
    "YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAjIOKU"
    "gOKUgCBEVUUgRVZFTlQgREVURUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGdldF9kdWVfZXZlbnRz"
    "KHNlbGYpIC0+IGxpc3RbdHVwbGVbc3RyLCBkaWN0XV06CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sg"
    "YWxsIHRhc2tzIGZvciBkdWUvcHJlLXRyaWdnZXIvcmV0cnkgZXZlbnRzLgogICAgICAgIFJldHVybnMg"
    "bGlzdCBvZiAoZXZlbnRfdHlwZSwgdGFzaykgdHVwbGVzLgogICAgICAgIGV2ZW50X3R5cGU6ICJwcmUi"
    "IHwgImR1ZSIgfCAicmV0cnkiCgogICAgICAgIE1vZGlmaWVzIHRhc2sgc3RhdHVzZXMgaW4gcGxhY2Ug"
    "YW5kIHNhdmVzLgogICAgICAgIENhbGwgZnJvbSBBUFNjaGVkdWxlciBldmVyeSAzMCBzZWNvbmRzLgog"
    "ICAgICAgICIiIgogICAgICAgIG5vdyAgICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAg"
    "ICAgIHRhc2tzICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGV2ZW50cyA9IFtdCiAgICAgICAgY2hh"
    "bmdlZCA9IEZhbHNlCgogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBpZiB0YXNr"
    "LmdldCgiYWNrbm93bGVkZ2VkX2F0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAg"
    "ICAgc3RhdHVzICAgPSB0YXNrLmdldCgic3RhdHVzIiwgInBlbmRpbmciKQogICAgICAgICAgICBkdWUg"
    "ICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJkdWVfYXQiKSkKICAgICAgICAgICAgcHJl"
    "ICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgicHJlX3RyaWdnZXIiKSkKICAgICAgICAg"
    "ICAgbmV4dF9yZXQgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgibmV4dF9yZXRyeV9hdCIpKQog"
    "ICAgICAgICAgICBkZWFkbGluZSA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJhbGVydF9kZWFk"
    "bGluZSIpKQoKICAgICAgICAgICAgIyBQcmUtdHJpZ2dlcgogICAgICAgICAgICBpZiAoc3RhdHVzID09"
    "ICJwZW5kaW5nIiBhbmQgcHJlIGFuZCBub3cgPj0gcHJlCiAgICAgICAgICAgICAgICAgICAgYW5kIG5v"
    "dCB0YXNrLmdldCgicHJlX2Fubm91bmNlZCIpKToKICAgICAgICAgICAgICAgIHRhc2tbInByZV9hbm5v"
    "dW5jZWQiXSA9IFRydWUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJwcmUiLCB0YXNrKSkK"
    "ICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICAjIER1ZSB0cmlnZ2VyCiAg"
    "ICAgICAgICAgIGlmIHN0YXR1cyA9PSAicGVuZGluZyIgYW5kIGR1ZSBhbmQgbm93ID49IGR1ZToKICAg"
    "ICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAg"
    "ICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAg"
    "ICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRl"
    "dGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAg"
    "ICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgZXZlbnRzLmFw"
    "cGVuZCgoImR1ZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFNub296ZSBhZnRlciAzLW1pbnV0ZSB3aW5kb3cK"
    "ICAgICAgICAgICAgaWYgc3RhdHVzID09ICJ0cmlnZ2VyZWQiIGFuZCBkZWFkbGluZSBhbmQgbm93ID49"
    "IGRlYWRsaW5lOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgID0gInNub296ZWQi"
    "CiAgICAgICAgICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gPSAoCiAgICAgICAgICAgICAgICAg"
    "ICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MTIpCiAgICAg"
    "ICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBj"
    "aGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgUmV0cnkK"
    "ICAgICAgICAgICAgaWYgc3RhdHVzIGluIHsicmV0cnlfcGVuZGluZyIsInNub296ZWQifSBhbmQgbmV4"
    "dF9yZXQgYW5kIG5vdyA+PSBuZXh0X3JldDoKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAg"
    "ICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAgICAgICAgICAgdGFza1sicmV0cnlfY291bnQiXSAg"
    "ICAgICA9IGludCh0YXNrLmdldCgicmV0cnlfY291bnQiLDApKSArIDEKICAgICAgICAgICAgICAgIHRh"
    "c2tbImxhc3RfdHJpZ2dlcmVkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHRh"
    "c2tbImFsZXJ0X2RlYWRsaW5lIl0gICAgPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93"
    "KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlf"
    "YXQiXSAgICAgPSBOb25lCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgicmV0cnkiLCB0YXNr"
    "KSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAg"
    "ICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgcmV0dXJuIGV2ZW50cwoKICAgIGRlZiBf"
    "cGFyc2VfbG9jYWwoc2VsZiwgdmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAg"
    "ICIiIlBhcnNlIElTTyBzdHJpbmcgdG8gdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUgZm9yIGNvbXBhcmlz"
    "b24uIiIiCiAgICAgICAgZHQgPSBwYXJzZV9pc28odmFsdWUpCiAgICAgICAgaWYgZHQgaXMgTm9uZToK"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBkdC50emluZm8gaXMgTm9uZToKICAgICAg"
    "ICAgICAgZHQgPSBkdC5hc3RpbWV6b25lKCkKICAgICAgICByZXR1cm4gZHQKCiAgICAjIOKUgOKUgCBO"
    "QVRVUkFMIExBTkdVQUdFIFBBUlNJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgY2xhc3NpZnlfaW50"
    "ZW50KHRleHQ6IHN0cikgLT4gZGljdDoKICAgICAgICAiIiIKICAgICAgICBDbGFzc2lmeSB1c2VyIGlu"
    "cHV0IGFzIHRhc2svcmVtaW5kZXIvdGltZXIvY2hhdC4KICAgICAgICBSZXR1cm5zIHsiaW50ZW50Ijog"
    "c3RyLCAiY2xlYW5lZF9pbnB1dCI6IHN0cn0KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAg"
    "ICAgICAjIFN0cmlwIGNvbW1vbiBpbnZvY2F0aW9uIHByZWZpeGVzCiAgICAgICAgY2xlYW5lZCA9IHJl"
    "LnN1YigKICAgICAgICAgICAgcmYiXlxzKig/OntERUNLX05BTUUubG93ZXIoKX18aGV5XHMre0RFQ0tf"
    "TkFNRS5sb3dlcigpfSlccyosP1xzKls6XC1dP1xzKiIsCiAgICAgICAgICAgICIiLCB0ZXh0LCBmbGFn"
    "cz1yZS5JCiAgICAgICAgKS5zdHJpcCgpCgogICAgICAgIGxvdyA9IGNsZWFuZWQubG93ZXIoKQoKICAg"
    "ICAgICB0aW1lcl9wYXRzICAgID0gW3IiXGJzZXQoPzpccythKT9ccyt0aW1lclxiIiwgciJcYnRpbWVy"
    "XHMrZm9yXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYnN0YXJ0KD86XHMrYSk/XHMrdGlt"
    "ZXJcYiJdCiAgICAgICAgcmVtaW5kZXJfcGF0cyA9IFtyIlxicmVtaW5kIG1lXGIiLCByIlxic2V0KD86"
    "XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxiYWRkKD86XHMr"
    "YSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic2V0KD86XHMrYW4/"
    "KT9ccythbGFybVxiIiwgciJcYmFsYXJtXHMrZm9yXGIiXQogICAgICAgIHRhc2tfcGF0cyAgICAgPSBb"
    "ciJcYmFkZCg/OlxzK2EpP1xzK3Rhc2tcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxiY3Jl"
    "YXRlKD86XHMrYSk/XHMrdGFza1xiIiwgciJcYm5ld1xzK3Rhc2tcYiJdCgogICAgICAgIGltcG9ydCBy"
    "ZSBhcyBfcmUKICAgICAgICBpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRpbWVyX3Bh"
    "dHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGltZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJj"
    "aChwLCBsb3cpIGZvciBwIGluIHJlbWluZGVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAicmVt"
    "aW5kZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRhc2tfcGF0"
    "cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0YXNrIgogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGlu"
    "dGVudCA9ICJjaGF0IgoKICAgICAgICByZXR1cm4geyJpbnRlbnQiOiBpbnRlbnQsICJjbGVhbmVkX2lu"
    "cHV0IjogY2xlYW5lZH0KCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2VfZHVlX2RhdGV0aW1l"
    "KHRleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIgogICAgICAgIFBhcnNl"
    "IG5hdHVyYWwgbGFuZ3VhZ2UgdGltZSBleHByZXNzaW9uIGZyb20gdGFzayB0ZXh0LgogICAgICAgIEhh"
    "bmRsZXM6ICJpbiAzMCBtaW51dGVzIiwgImF0IDNwbSIsICJ0b21vcnJvdyBhdCA5YW0iLAogICAgICAg"
    "ICAgICAgICAgICJpbiAyIGhvdXJzIiwgImF0IDE1OjMwIiwgZXRjLgogICAgICAgIFJldHVybnMgYSBk"
    "YXRldGltZSBvciBOb25lIGlmIHVucGFyc2VhYmxlLgogICAgICAgICIiIgogICAgICAgIGltcG9ydCBy"
    "ZQogICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3coKQogICAgICAgIGxvdyAgPSB0ZXh0Lmxvd2VyKCku"
    "c3RyaXAoKQoKICAgICAgICAjICJpbiBYIG1pbnV0ZXMvaG91cnMvZGF5cyIKICAgICAgICBtID0gcmUu"
    "c2VhcmNoKAogICAgICAgICAgICByImluXHMrKFxkKylccyoobWludXRlfG1pbnxob3VyfGhyfGRheXxz"
    "ZWNvbmR8c2VjKSIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAg"
    "ICAgICBuICAgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIHVuaXQgPSBtLmdyb3VwKDIpCiAg"
    "ICAgICAgICAgIGlmICJtaW4iIGluIHVuaXQ6ICByZXR1cm4gbm93ICsgdGltZWRlbHRhKG1pbnV0ZXM9"
    "bikKICAgICAgICAgICAgaWYgImhvdXIiIGluIHVuaXQgb3IgImhyIiBpbiB1bml0OiByZXR1cm4gbm93"
    "ICsgdGltZWRlbHRhKGhvdXJzPW4pCiAgICAgICAgICAgIGlmICJkYXkiICBpbiB1bml0OiByZXR1cm4g"
    "bm93ICsgdGltZWRlbHRhKGRheXM9bikKICAgICAgICAgICAgaWYgInNlYyIgIGluIHVuaXQ6IHJldHVy"
    "biBub3cgKyB0aW1lZGVsdGEoc2Vjb25kcz1uKQoKICAgICAgICAjICJhdCBISDpNTSIgb3IgImF0IEg6"
    "TU1hbS9wbSIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImF0XHMrKFxkezEsMn0p"
    "KD86OihcZHsyfSkpP1xzKihhbXxwbSk/IiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAg"
    "IGlmIG06CiAgICAgICAgICAgIGhyICA9IGludChtLmdyb3VwKDEpKQogICAgICAgICAgICBtbiAgPSBp"
    "bnQobS5ncm91cCgyKSkgaWYgbS5ncm91cCgyKSBlbHNlIDAKICAgICAgICAgICAgYXBtID0gbS5ncm91"
    "cCgzKQogICAgICAgICAgICBpZiBhcG0gPT0gInBtIiBhbmQgaHIgPCAxMjogaHIgKz0gMTIKICAgICAg"
    "ICAgICAgaWYgYXBtID09ICJhbSIgYW5kIGhyID09IDEyOiBociA9IDAKICAgICAgICAgICAgZHQgPSBu"
    "b3cucmVwbGFjZShob3VyPWhyLCBtaW51dGU9bW4sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKQogICAg"
    "ICAgICAgICBpZiBkdCA8PSBub3c6CiAgICAgICAgICAgICAgICBkdCArPSB0aW1lZGVsdGEoZGF5cz0x"
    "KQogICAgICAgICAgICByZXR1cm4gZHQKCiAgICAgICAgIyAidG9tb3Jyb3cgYXQgLi4uIiAgKHJlY3Vy"
    "c2Ugb24gdGhlICJhdCIgcGFydCkKICAgICAgICBpZiAidG9tb3Jyb3ciIGluIGxvdzoKICAgICAgICAg"
    "ICAgdG9tb3Jyb3dfdGV4dCA9IHJlLnN1YihyInRvbW9ycm93IiwgIiIsIGxvdykuc3RyaXAoKQogICAg"
    "ICAgICAgICByZXN1bHQgPSBUYXNrTWFuYWdlci5wYXJzZV9kdWVfZGF0ZXRpbWUodG9tb3Jyb3dfdGV4"
    "dCkKICAgICAgICAgICAgaWYgcmVzdWx0OgogICAgICAgICAgICAgICAgcmV0dXJuIHJlc3VsdCArIHRp"
    "bWVkZWx0YShkYXlzPTEpCgogICAgICAgIHJldHVybiBOb25lCgoKIyDilIDilIAgUkVRVUlSRU1FTlRT"
    "LlRYVCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiB3cml0ZV9yZXF1aXJlbWVu"
    "dHNfdHh0KCkgLT4gTm9uZToKICAgICIiIgogICAgV3JpdGUgcmVxdWlyZW1lbnRzLnR4dCBuZXh0IHRv"
    "IHRoZSBkZWNrIGZpbGUgb24gZmlyc3QgcnVuLgogICAgSGVscHMgdXNlcnMgaW5zdGFsbCBhbGwgZGVw"
    "ZW5kZW5jaWVzIHdpdGggb25lIHBpcCBjb21tYW5kLgogICAgIiIiCiAgICByZXFfcGF0aCA9IFBhdGgo"
    "Q0ZHLmdldCgiYmFzZV9kaXIiLCBzdHIoU0NSSVBUX0RJUikpKSAvICJyZXF1aXJlbWVudHMudHh0Igog"
    "ICAgaWYgcmVxX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgY29udGVudCA9ICIiIlwK"
    "IyBNb3JnYW5uYSBEZWNrIOKAlCBSZXF1aXJlZCBEZXBlbmRlbmNpZXMKIyBJbnN0YWxsIGFsbCB3aXRo"
    "OiBwaXAgaW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0CgojIENvcmUgVUkKUHlTaWRlNgoKIyBTY2hl"
    "ZHVsaW5nIChpZGxlIHRpbWVyLCBhdXRvc2F2ZSwgcmVmbGVjdGlvbiBjeWNsZXMpCmFwc2NoZWR1bGVy"
    "CgojIExvZ2dpbmcKbG9ndXJ1CgojIFNvdW5kIHBsYXliYWNrIChXQVYgKyBNUDMpCnB5Z2FtZQoKIyBE"
    "ZXNrdG9wIHNob3J0Y3V0IGNyZWF0aW9uIChXaW5kb3dzIG9ubHkpCnB5d2luMzIKCiMgU3lzdGVtIG1v"
    "bml0b3JpbmcgKENQVSwgUkFNLCBkcml2ZXMsIG5ldHdvcmspCnBzdXRpbAoKIyBIVFRQIHJlcXVlc3Rz"
    "CnJlcXVlc3RzCgojIEdvb2dsZSBpbnRlZ3JhdGlvbiAoQ2FsZW5kYXIsIERyaXZlLCBEb2NzLCBHbWFp"
    "bCkKZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Cmdvb2dsZS1hdXRoLW9hdXRobGliCmdvb2dsZS1hdXRo"
    "CgojIOKUgOKUgCBPcHRpb25hbCAobG9jYWwgbW9kZWwgb25seSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMg"
    "VW5jb21tZW50IGlmIHVzaW5nIGEgbG9jYWwgSHVnZ2luZ0ZhY2UgbW9kZWw6CiMgdG9yY2gKIyB0cmFu"
    "c2Zvcm1lcnMKIyBhY2NlbGVyYXRlCgojIOKUgOKUgCBPcHRpb25hbCAoTlZJRElBIEdQVSBtb25pdG9y"
    "aW5nKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKIyBVbmNvbW1lbnQgaWYgeW91IGhhdmUgYW4gTlZJRElBIEdQVToKIyBweW52bWwKIiIiCiAg"
    "ICByZXFfcGF0aC53cml0ZV90ZXh0KGNvbnRlbnQsIGVuY29kaW5nPSJ1dGYtOCIpCgoKIyDilIDilIAg"
    "UEFTUyA0IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAojIE1lbW9yeSwgU2Vzc2lvbiwgTGVzc29uc0xlYXJuZWQsIFRhc2tNYW5hZ2Vy"
    "IGFsbCBkZWZpbmVkLgojIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhdXRvLXNlZWRlZCBvbiBmaXJzdCBy"
    "dW4uCiMgcmVxdWlyZW1lbnRzLnR4dCB3cml0dGVuIG9uIGZpcnN0IHJ1bi4KIwojIE5leHQ6IFBhc3Mg"
    "NSDigJQgVGFiIENvbnRlbnQgQ2xhc3NlcwojIChTTFNjYW5zVGFiLCBTTENvbW1hbmRzVGFiLCBKb2JU"
    "cmFja2VyVGFiLCBSZWNvcmRzVGFiLAojICBUYXNrc1RhYiwgU2VsZlRhYiwgRGlhZ25vc3RpY3NUYWIp"
    "CgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDU6IFRBQiBDT05URU5UIENMQVNTRVMKIwojIFRhYnMg"
    "ZGVmaW5lZCBoZXJlOgojICAgU0xTY2Fuc1RhYiAgICAgIOKAlCBncmltb2lyZS1jYXJkIHN0eWxlLCBy"
    "ZWJ1aWx0IChEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwKIyAgICAgICAgICAgICAgICAgICAgIHBh"
    "cnNlciBmaXhlZCwgY29weS10by1jbGlwYm9hcmQgcGVyIGl0ZW0pCiMgICBTTENvbW1hbmRzVGFiICAg"
    "4oCUIGdvdGhpYyB0YWJsZSwgY29weSBjb21tYW5kIHRvIGNsaXBib2FyZAojICAgSm9iVHJhY2tlclRh"
    "YiAgIOKAlCBmdWxsIHJlYnVpbGQgZnJvbSBzcGVjLCBDU1YvVFNWIGV4cG9ydAojICAgUmVjb3Jkc1Rh"
    "YiAgICAgIOKAlCBHb29nbGUgRHJpdmUvRG9jcyB3b3Jrc3BhY2UKIyAgIFRhc2tzVGFiICAgICAgICDi"
    "gJQgdGFzayByZWdpc3RyeSArIG1pbmkgY2FsZW5kYXIKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRs"
    "ZSBuYXJyYXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1"
    "IG91dHB1dCArIGhhcmR3YXJlIHJlcG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMgICBMZXNzb25z"
    "VGFiICAgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpp"
    "bXBvcnQgcmUgYXMgX3JlCgoKIyDilIDilIAgU0hBUkVEIEdPVEhJQyBUQUJMRSBTVFlMRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAtPiBzdHI6CiAgICBy"
    "ZXR1cm4gZiIiIgogICAgICAgIFFUYWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRF"
    "Un07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAg"
    "IGZvbnQtc2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxl"
    "Y3RlZCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAg"
    "IGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAgICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0"
    "ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgfX0K"
    "ICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19C"
    "RzN9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAg"
    "ICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAx"
    "MHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9sZDsKICAgICAgICAgICAgbGV0dGVyLXNwYWNp"
    "bmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4dDogc3RyLCB0b29s"
    "dGlwOiBzdHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQog"
    "ICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07"
    "IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07"
    "IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogNHB4IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAg"
    "ICAgICBidG4uc2V0VG9vbFRpcCh0b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xi"
    "bCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdl"
    "aWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMg"
    "VEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlm"
    "ZSBhdmF0YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZyb20gc3BlYzoKICAg"
    "ICAgLSBDYXJkL2dyaW1vaXJlLWVudHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGlt"
    "ZXN0YW1wLWF3YXJlIHBhcnNlcikKICAgICAgLSBEaXNwbGF5IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFi"
    "bGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRlc2NyaXB0aW9uLCBpbmRpdmlkdWFsIGl0ZW1z"
    "KQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBh"
    "cnNlICh3YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAg"
    "ICAgIC0gQ29weS10by1jbGlwYm9hcmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX3Nj"
    "YW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNl"
    "bGYuX3NlbGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3Vp"
    "KCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFy"
    "Z2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRv"
    "biBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICAg"
    "PSBfZ290aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAgICAgIHNlbGYu"
    "X2J0bl9kaXNwbGF5ID0gX2dvdGhpY19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2Nh"
    "biBkZXRhaWxzIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9k"
    "aWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgID0gX2dv"
    "dGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxm"
    "Ll9idG5fcmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4"
    "dCBvZiBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9zaG93X2FkZCkKICAgICAgICBzZWxmLl9idG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fcmVwYXJzZSkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rp"
    "c3BsYXksIHNlbGYuX2J0bl9tb2RpZnksCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9kZWxldGUs"
    "IHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJh"
    "ci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgICMgU3RhY2s6"
    "IGxpc3QgdmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAgIHNlbGYuX3N0YWNr"
    "ID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoK"
    "ICAgICAgICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4gbGlzdCAoZ3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAg"
    "ICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Nj"
    "cm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNp"
    "emFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAgc2VsZi5fY2FyZF9jb250YWluZXIg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94TGF5b3V0KHNlbGYu"
    "X2NhcmRfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAg"
    "ICBzZWxmLl9jYXJkX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5z"
    "ZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2Nh"
    "cmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyDilIDi"
    "lIAgUEFHRSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwx"
    "ID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBTQ0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0g"
    "UUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8t"
    "ZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFt"
    "ZSkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAg"
    "ICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLnNl"
    "dE1heGltdW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAg"
    "ICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJl"
    "KSIpKQogICAgICAgIHNlbGYuX2FkZF9yYXcgICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRk"
    "X3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJQYXN0ZSB0aGUgcmF3IFNlY29uZCBM"
    "aWZlIHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3"
    "XSB3aWxsIGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAgICApCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBp"
    "dGVtcwogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJF"
    "VklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3Jl"
    "YXRvciJdKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX2Fk"
    "ZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFk"
    "ZFdpZGdldChzZWxmLl9hZGRfcHJldmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fcHJldmlld19wYXJzZSkKCiAgICAgICAgYnRuczEgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzEgPSBfZ290aGljX2J0bigi4pyX"
    "IENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBj"
    "MS5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAg"
    "ICAgICAgYnRuczEuYWRkV2lkZ2V0KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0bnMxKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdp"
    "ZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAyOiBkaXNwbGF5IOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRD"
    "b250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVs"
    "KCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX2Rpc3BfZGVzYyAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRX"
    "b3JkV3JhcChUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFi"
    "bGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJM"
    "YWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250"
    "YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcu"
    "UmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5"
    "KAogICAgICAgICAgICBRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAg"
    "ICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5f"
    "ZGlzcF9uYW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIu"
    "YWRkV2lkZ2V0KHNlbGYuX2Rpc3BfdGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgi"
    "UmlnaHQtY2xpY2sgYW55IGl0ZW0gdG8gY29weSBpdCB0byBjbGlwYm9hcmQuIikKICAgICAgICBjb3B5"
    "X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAg"
    "ICAgIGwyLmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNfYnRuKCLil4Ag"
    "QmFjayIpCiAgICAgICAgYmsyLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleCgwKSkKICAgICAgICBsMi5hZGRXaWRnZXQoYmsyKQogICAgICAgIHNlbGYuX3N0YWNr"
    "LmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAgUEFHRSAzOiBtb2RpZnkg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAg"
    "IGwzLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkK"
    "ICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTkFNRSIpKQogICAgICAgIHNlbGYu"
    "X21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX25hbWUp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAg"
    "ICAgc2VsZi5fbW9kX2Rlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9t"
    "b2RfZGVzYykKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSVRFTVMgKGRvdWJs"
    "ZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZSA9IFFUYWJsZVdpZGdldCgw"
    "LCAyKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRl"
    "bSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5T"
    "dHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkK"
    "ICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgczMgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzMgPSBfZ290"
    "aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21v"
    "ZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNl"
    "dEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBidG5zMy5hZGRXaWRn"
    "ZXQoYzMpOyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAg"
    "ICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAg"
    "IGRlZiBwYXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAg"
    "ICAgICAgIiIiCiAgICAgICAgUGFyc2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1l"
    "LCBpdGVtcykuCgogICAgICAgIEtFWSBGSVg6IEJlZm9yZSBzcGxpdHRpbmcsIGluc2VydCBuZXdsaW5l"
    "cyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRpbWVzdGFtcCBzbyBzaW5nbGUtbGluZSBwYXN0"
    "ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzEx"
    "OjQ3XSBBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46"
    "IEl0ZW0gTmFtZSBbQXR0YWNobWVudF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3XSAuLi4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBub3QgcmF3LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5L"
    "Tk9XTiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTogbm9ybWFsaXplIOKAlCBpbnNlcnQgbmV3"
    "bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbm9ybWFsaXpl"
    "ZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAg"
    "IGxpbmVzID0gW2wuc3RyaXAoKSBmb3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0"
    "cmlwKCldCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMjogZXh0cmFjdCBhdmF0YXIgbmFtZSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFtZSA9ICJVTktOT1dO"
    "IgogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0YXJOYW1lJ3MgcHVi"
    "bGljIGF0dGFjaG1lbnRzIiBvciBzaW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAg"
    "ICAgICAgICAgICAgciIoXHdbXHdcc10rPyknc1xzK3B1YmxpY1xzK2F0dGFjaG1lbnRzIiwKICAgICAg"
    "ICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgbToKICAgICAg"
    "ICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBi"
    "cmVhawoKICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQog"
    "ICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjIFN0cmlwIGxlYWRpbmcgdGltZXN0"
    "YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpcZHsyfVxdXHMqJywg"
    "JycsIGxpbmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIn"
    "cyBwdWJsaWMgYXR0YWNobWVudHMiIGluIGNvbnRlbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93ZXIoKS5zdGFydHN3aXRoKCJvYmplY3QiKToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZpZGVyIGxpbmVzIOKA"
    "lCBsaW5lcyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAgICAgICAgICAj"
    "IGUuZy4g4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkCBvciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50LnN0cmlwKCIuOiAiKQogICAgICAgICAgICBp"
    "ZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250"
    "aW51ZSAgIyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAg"
    "IyBUcnkgdG8gZXh0cmFjdCBDUkVBVE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9yID0gIlVOS05P"
    "V04iCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0"
    "Y2ggPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidDUkVBVE9SOlxzKihbXHdcc10rPykoPzpc"
    "cypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgY3JlYXRv"
    "cl9tYXRjaDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSku"
    "c3RyaXAoKQogICAgICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5z"
    "dGFydCgpXS5zdHJpcCgpCgogICAgICAgICAgICAjIFN0cmlwIGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4"
    "ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBpdGVtX25hbWUgPSBfcmUuc3ViKHInXHMqXFtb"
    "XHdcc19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBpdGVtX25hbWUgPSBp"
    "dGVtX25hbWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUgYW5kIGxlbihpdGVt"
    "X25hbWUpID4gMToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUs"
    "ICJjcmVhdG9yIjogY3JlYXRvcn0pCgogICAgICAgIHJldHVybiBhdmF0YXJfbmFtZSwgaXRlbXMKCiAg"
    "ICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBf"
    "YnVpbGRfY2FyZHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNhcmRzIChr"
    "ZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAg"
    "ICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYg"
    "aXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoK"
    "ICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9t"
    "YWtlX2NhcmQocmVjKQogICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpIC0gMSwgY2FyZAogICAgICAgICAg"
    "ICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVjOiBkaWN0KSAtPiBRV2lkZ2V0OgogICAgICAg"
    "IGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgicmVjb3JkX2lkIikg"
    "PT0gc2VsZi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDogeycjMWEwYTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBD"
    "X0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IHBhZGRpbmc6IDJweDsi"
    "CiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChy"
    "ZWMuZ2V0KCJuYW1lIiwgIlVOS05PV04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09M"
    "RH07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGNvdW50ID0gbGVu"
    "KHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0g"
    "aXRlbXMiKQogICAgICAgIGNvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJsID0gUUxhYmVsKHJlYy5nZXQoImNyZWF0ZWRf"
    "YXQiLCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoY291bnRfbGJs"
    "KQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZGF0"
    "ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgi"
    "cmVjb3JkX2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlk"
    "PXJlY19pZDogc2VsZi5fc2VsZWN0X2NhcmQocmlkKQogICAgICAgIHJldHVybiBjYXJkCgogICAgZGVm"
    "IF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9z"
    "ZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkgICMgUmVidWls"
    "ZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVkX3JlY29yZChzZWxm"
    "KSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9y"
    "IHIgaW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNl"
    "bGYuX3NlbGVjdGVkX2lkKSwKICAgICAgICAgICAgTm9uZQogICAgICAgICkKCiAgICAjIOKUgOKUgCBB"
    "Q1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgICMgRW5zdXJlIHJlY29yZF9pZCBmaWVsZCBleGlzdHMKICAgICAgICBj"
    "aGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBp"
    "ZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSBy"
    "LmdldCgiaWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX2J1aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFj"
    "ay5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZpZXdfcGFyc2Uoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVt"
    "cyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFj"
    "ZWhvbGRlclRleHQobmFtZSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQog"
    "ICAgICAgIGZvciBpdCBpbiBpdGVtc1s6MjBdOiAgIyBwcmV2aWV3IGZpcnN0IDIwCiAgICAgICAgICAg"
    "IHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2"
    "aWV3Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDAs"
    "IFFUYWJsZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "LnNldEl0ZW0ociwgMSwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3No"
    "b3dfYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYWRkX25hbWUuY2xlYXIoKQogICAgICAg"
    "IHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4g"
    "dGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcu"
    "Y2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2Vs"
    "Zi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRl"
    "bXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgb3ZlcnJpZGVfbmFtZSA9IHNlbGYu"
    "X2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAg"
    "ICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQu"
    "dXVpZDQoKSksCiAgICAgICAgICAgICJuYW1lIjogICAgICAgIG92ZXJyaWRlX25hbWUgb3IgbmFtZSwK"
    "ICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5fYWRkX2Rlc2MudG9QbGFpblRleHQoKVs6MjQ0"
    "XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAgICJyYXdfdGV4dCI6"
    "ICAgIHJhdywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAgICAidXBkYXRl"
    "ZF9hdCI6ICBub3csCiAgICAgICAgfQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkK"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYu"
    "X3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQiXQogICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxl"
    "Y3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lmlu"
    "Zm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJTZWxlY3QgYSBzY2FuIHRvIGRpc3BsYXkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "c2VsZi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAg"
    "IHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAg"
    "c2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJp"
    "dGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAg"
    "ICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2Rpc3Bf"
    "dGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQo"
    "Iml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAxLAogICAg"
    "ICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0"
    "X21lbnUoc2VsZiwgcG9zKSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5k"
    "ZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1ZhbGlkKCk6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IK"
    "ICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBj"
    "cmVhdG9yICAgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDEpIG9yCiAgICAgICAg"
    "ICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNp"
    "ZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1lbnUoc2VsZikKICAgICAg"
    "ICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyIKICAgICAgICApCiAgICAgICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRl"
    "bSBOYW1lIikKICAgICAgICBhX2NyZWF0b3IgPSBtZW51LmFkZEFjdGlvbigiQ29weSBDcmVhdG9yIikK"
    "ICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBCb3RoIikKICAgICAgICBhY3Rp"
    "b24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykp"
    "CiAgICAgICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBhY3Rpb24gPT0g"
    "YV9pdGVtOiAgICBjYi5zZXRUZXh0KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2Ny"
    "ZWF0b3I6IGNiLnNldFRleHQoY3JlYXRvcikKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBj"
    "Yi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVhdG9yfSIpCgogICAgZGVmIF9zaG93X21vZGlm"
    "eShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAg"
    "ICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNM"
    "IFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4g"
    "dG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRl"
    "eHQocmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjLnNldFRleHQocmVjLmdl"
    "dCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0Um93Q291bnQoMCkK"
    "ICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYu"
    "X21vZF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3co"
    "cikKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAg"
    "IFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9tb2Rf"
    "dGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQo"
    "ImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgz"
    "KQoKICAgIGRlZiBfZG9fbW9kaWZ5X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxm"
    "Ll9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYuX21vZF9uYW1lLnRleHQoKS5zdHJpcCgpIG9y"
    "ICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQo"
    "KVs6MjQ0XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2Rf"
    "dGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShp"
    "LDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYu"
    "X21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAg"
    "ICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9XTiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAg"
    "ICAgcmVjWyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0"
    "ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19k"
    "ZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQog"
    "ICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYs"
    "ICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBz"
    "Y2FuIHRvIGRlbGV0ZS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lID0gcmVjLmdldCgi"
    "bmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAg"
    "ICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/"
    "IFRoaXMgY2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1"
    "dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBp"
    "ZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lkXQogICAgICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9z"
    "ZWxlY3RlZF9pZCA9IE5vbmUKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3Jl"
    "cGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQog"
    "ICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYs"
    "ICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBz"
    "Y2FuIHRvIHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJhdyA9IHJlYy5nZXQo"
    "InJhd190ZXh0IiwiIikKICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5p"
    "bmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2UiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlzIHNjYW4uIikKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVj"
    "WyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1l"
    "Il0gb3IgbmFtZQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25l"
    "LnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "c2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJGb3VuZCB7"
    "bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMQ29tbWFu"
    "ZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQgcmVmZXJlbmNlIHRh"
    "YmxlLgogICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQgYnV0"
    "dG9uIHBlciByb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdf"
    "cGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0"
    "W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0"
    "KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBy"
    "b290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYu"
    "X2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlm"
    "eSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dv"
    "dGhpY19idG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0"
    "bigi4qeJIENvcHkgQ29tbWFuZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAiQ29weSBzZWxlY3RlZCBjb21tYW5kIHRvIGNsaXBib2FyZCIpCiAgICAgICAgc2VsZi5fYnRuX3Jl"
    "ZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2NvcHlfY29tbWFuZCkKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5f"
    "bW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwg"
    "c2VsZi5fYnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFy"
    "LmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFi"
    "bGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVh"
    "ZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIHNlbGYuX3RhYmxlLmhv"
    "cml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFk"
    "ZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXpl"
    "TW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAg"
    "ICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJT"
    "ZWxlY3QgYSByb3cgYW5kIGNsaWNrIOKniSBDb3B5IENvbW1hbmQgdG8gY29weSBqdXN0IHRoZSBjb21t"
    "YW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRl"
    "ZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwo"
    "c2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBy"
    "ZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkK"
    "ICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29t"
    "bWFuZCIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAg"
    "ICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKSkKCiAgICBkZWYg"
    "X2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJl"
    "bnRSb3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW0g"
    "PSBzZWxmLl90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBRQXBw"
    "bGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2lu"
    "ZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChk"
    "bGcpCiAgICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBm"
    "b3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9u"
    "OiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNf"
    "YnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5j"
    "b25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBi"
    "dG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0"
    "bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAg"
    "ICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAg"
    "ICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0"
    "KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5zdHJpcCgpWzoyNDRd"
    "LAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwK"
    "ICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgaWYgcmVjWyJjb21tYW5kIl06CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3co"
    "KQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURp"
    "YWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kaWZ5IENvbW1hbmQiKQogICAg"
    "ICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9"
    "OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0"
    "KHJlYy5nZXQoImNvbW1hbmQiLCIiKSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRl"
    "c2NyaXB0aW9uIiwiIikpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAg"
    "IGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5j"
    "ZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25u"
    "ZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChj"
    "eCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxv"
    "Zy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZWNbImNvbW1hbmQiXSAgICAgPSBjbWQu"
    "dGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50"
    "ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGlt"
    "ZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJv"
    "dygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwi"
    "dGhpcyBjb21tYW5kIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAg"
    "ICAgICBzZWxmLCAiRGVsZXRlIiwgZiJEZWxldGUgJ3tjbWR9Jz8iLAogICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAg"
    "ICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKU"
    "gCBKT0IgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpv"
    "YiBhcHBsaWNhdGlvbiB0cmFja2luZy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAgIEZpZWxkczog"
    "Q29tcGFueSwgSm9iIFRpdGxlLCBEYXRlIEFwcGxpZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBN"
    "dWx0aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1YgYW5kIFRTViBleHBvcnQuCiAgICBIaWRk"
    "ZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBqdXN0IG5vdCBzaG93"
    "bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBw"
    "bGllZCIsCiAgICAgICAgICAgICAgICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiam9iX3RyYWNrZXIu"
    "anNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "c2hvd19oaWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9t"
    "b2RpZnkgPSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dv"
    "dGhpY19idG4oIkFyY2hpdmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "Ik1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVkL3JlamVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5o"
    "aWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAgICBzZWxmLl9idG5f"
    "ZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9n"
    "b3RoaWNfYnRuKCJTaG93IEFyY2hpdmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhp"
    "Y19idG4oIkV4cG9ydCIpCgogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5f"
    "bW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSwg"
    "c2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSwgc2VsZi5f"
    "YnRuX2V4cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAgICAgICAgICBi"
    "LnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAg"
    "c2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0"
    "bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5f"
    "aGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9oaWRkZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAg"
    "ICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0"
    "KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFk"
    "ZXJMYWJlbHMoc2VsZi5DT0xVTU5TKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhl"
    "YWRlcigpCiAgICAgICAgIyBDb21wYW55IGFuZCBKb2IgVGl0bGUgc3RyZXRjaAogICAgICAgIGhoLnNl"
    "dFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAg"
    "ICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gp"
    "CiAgICAgICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRoCiAgICAgICAgaGgu"
    "c2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgyLCAxMDApCiAgICAgICAgIyBMaW5rIHN0cmV0Y2hl"
    "cwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "U3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldENvbHVtbldpZHRoKDQsIDgwKQogICAgICAgICMgTm90ZXMgc3RyZXRjaGVzCiAgICAg"
    "ICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFi"
    "c3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rp"
    "b25Nb2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5n"
    "Um93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3Rh"
    "YmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFibGUsIDEpCgogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJl"
    "YyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRl"
    "biIsIEZhbHNlKSkKICAgICAgICAgICAgaWYgaGlkZGVuIGFuZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291"
    "bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVz"
    "ID0gIkFyY2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAg"
    "ICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAg"
    "ICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0"
    "KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAg"
    "ICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAg"
    "ICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAg"
    "ICAgICAgICAgaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYg"
    "aGlkZGVuOgogICAgICAgICAgICAgICAgICAgIGl0ZW0uc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhU"
    "X0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIGMsIGl0ZW0pCiAgICAg"
    "ICAgICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVzZXIgZGF0YQogICAg"
    "ICAgICAgICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAgICAgICAgICBRdC5J"
    "dGVtRGF0YVJvbGUuVXNlclJvbGUsCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJl"
    "YykKICAgICAgICAgICAgKQoKICAgIGRlZiBfc2VsZWN0ZWRfaW5kaWNlcyhzZWxmKSAtPiBsaXN0W2lu"
    "dF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAgICAgZm9yIGl0ZW0gaW4gc2VsZi5fdGFibGUu"
    "c2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRl"
    "bS5yb3coKSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSBy"
    "b3dfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgICAgIGlmIGlk"
    "eCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAg"
    "cmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5v"
    "bmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAg"
    "ZGxnLnNldFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNo"
    "ZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJl"
    "c2l6ZSg1MDAsIDMyMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQoKICAgICAgICBjb21w"
    "YW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnkiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAg"
    "ICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlmIHJlYyBlbHNlICIi"
    "KQogICAgICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVuZGFyUG9wdXAo"
    "VHJ1ZSkKICAgICAgICBkZS5zZXREaXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiBy"
    "ZWMgYW5kIHJlYy5nZXQoImRhdGVfYXBwbGllZCIpOgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRl"
    "LmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwieXl5eS1NTS1kZCIpKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAg"
    "ID0gUUxpbmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0"
    "dXMgID0gUUxpbmVFZGl0KHJlYy5nZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMgZWxzZSAiQXBw"
    "bGllZCIpCiAgICAgICAgbm90ZXMgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJl"
    "YyBlbHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiQ29t"
    "cGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAgICAgICAoIkRhdGUg"
    "QXBwbGllZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3Rh"
    "dHVzKSwgKCJOb3RlczoiLCBub3RlcyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3co"
    "bGFiZWwsIHdpZGdldCkKCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9n"
    "b3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xp"
    "Y2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAg"
    "ICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRk"
    "Um93KGJ0bnMpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2Vw"
    "dGVkOgogICAgICAgICAgICByZXR1cm4gewogICAgICAgICAgICAgICAgImNvbXBhbnkiOiAgICAgIGNv"
    "bXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiam9iX3RpdGxlIjogICAgdGl0bGUu"
    "dGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRv"
    "U3RyaW5nKCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICBzdGF0dXMudGV4dCgp"
    "LnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVz"
    "LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYg"
    "X2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2coKQogICAgICAgIGlm"
    "IG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpv"
    "bmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAg"
    "ICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJoaWRkZW4iOiAgICAgICAgIEZh"
    "bHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUiOiBOb25lLAogICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5vdywKICAgICAgICB9"
    "KQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5f"
    "cGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9k"
    "aWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQog"
    "ICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlv"
    "bihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVj"
    "dCBleGFjdGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3JlY29yZHNbaWR4c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFsb2cocmVjKQog"
    "ICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAg"
    "ICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3Jt"
    "YXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3Ig"
    "aWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNl"
    "bGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAg"
    "ICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJjb21wbGV0ZWRf"
    "ZGF0ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XS5nZXQoImNvbXBs"
    "ZXRlZF9kYXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5kYXRlKCkuaXNv"
    "Zm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4"
    "XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9f"
    "dW5oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRp"
    "Y2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRh"
    "dGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYu"
    "X3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIG5vdCBpZHhzOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVs"
    "ZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQgYXBwbGljYXRpb24o"
    "cyk/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0"
    "b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYg"
    "cmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBiYWQgPSBz"
    "ZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciBpLCByIGluIGVudW1lcmF0"
    "ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJh"
    "ZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IG5vdCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNl"
    "bGYuX2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAgIuKYgCBIaWRlIEFyY2hpdmVkIiBpZiBz"
    "ZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBh"
    "dGgsIGZpbHQgPSBRRmlsZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJF"
    "eHBvcnQgSm9iIFRyYWNrZXIiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImV4cG9ydHMiKSAvICJq"
    "b2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNTViBGaWxlcyAoKi5jc3YpOztUYWIgRGVsaW1p"
    "dGVkICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRoKCIudHh0IikgZWxz"
    "ZSAiLCIKICAgICAgICBoZWFkZXIgPSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQi"
    "LCJsaW5rIiwKICAgICAgICAgICAgICAgICAgInN0YXR1cyIsImhpZGRlbiIsImNvbXBsZXRlZF9kYXRl"
    "Iiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRoLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIsIG5l"
    "d2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxu"
    "IikKICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFs"
    "cyA9IFsKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIp"
    "LAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAgICAgICAgICAgICAg"
    "ICAgIHN0cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAg"
    "cmVjLmdldCgiY29tcGxldGVkX2RhdGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgXQogICAgICAgICAgICAgICAgZi53cml0ZShk"
    "ZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0cih2KS5yZXBsYWNlKCJcbiIsIiAiKS5yZXBs"
    "YWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxzCiAgICAgICAgICAg"
    "ICAgICApICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0"
    "ZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgoj"
    "IOKUgOKUgCBTRUxGIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgUmVjb3Jkc1RhYihRV2lkZ2V0"
    "KToKICAgICIiIkdvb2dsZSBEcml2ZS9Eb2NzIHJlY29yZHMgYnJvd3NlciB0YWIuIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRz"
    "TWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxm"
    "LnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiUmVjb3JkcyBhcmUgbm90IGxvYWRlZCB5ZXQuIikKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19U"
    "RVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsi"
    "CiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAg"
    "ICBzZWxmLnBhdGhfbGFiZWwgPSBRTGFiZWwoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBzZWxmLnBh"
    "dGhfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnBhdGhfbGFiZWwpCgogICAgICAgIHNlbGYucmVjb3Jk"
    "c19saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYucmVjb3Jkc19saXN0LnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5yZWNvcmRzX2xpc3QsIDEpCgogICAgZGVmIHNldF9pdGVtcyhzZWxmLCBmaWxlczogbGlzdFtk"
    "aWN0XSwgcGF0aF90ZXh0OiBzdHIgPSAiTXkgRHJpdmUiKSAtPiBOb25lOgogICAgICAgIHNlbGYucGF0"
    "aF9sYWJlbC5zZXRUZXh0KGYiUGF0aDoge3BhdGhfdGV4dH0iKQogICAgICAgIHNlbGYucmVjb3Jkc19s"
    "aXN0LmNsZWFyKCkKICAgICAgICBmb3IgZmlsZV9pbmZvIGluIGZpbGVzOgogICAgICAgICAgICB0aXRs"
    "ZSA9IChmaWxlX2luZm8uZ2V0KCJuYW1lIikgb3IgIlVudGl0bGVkIikuc3RyaXAoKSBvciAiVW50aXRs"
    "ZWQiCiAgICAgICAgICAgIG1pbWUgPSAoZmlsZV9pbmZvLmdldCgibWltZVR5cGUiKSBvciAiIikuc3Ry"
    "aXAoKQogICAgICAgICAgICBpZiBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9s"
    "ZGVyIjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OBIgogICAgICAgICAgICBlbGlmIG1pbWUg"
    "PT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCI6CiAgICAgICAgICAgICAgICBw"
    "cmVmaXggPSAi8J+TnSIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLw"
    "n5OEIgogICAgICAgICAgICBtb2RpZmllZCA9IChmaWxlX2luZm8uZ2V0KCJtb2RpZmllZFRpbWUiKSBv"
    "ciAiIikucmVwbGFjZSgiVCIsICIgIikucmVwbGFjZSgiWiIsICIgVVRDIikKICAgICAgICAgICAgdGV4"
    "dCA9IGYie3ByZWZpeH0ge3RpdGxlfSIgKyAoZiIgICAgW3ttb2RpZmllZH1dIiBpZiBtb2RpZmllZCBl"
    "bHNlICIiKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKHRleHQpCiAgICAgICAgICAg"
    "IGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGZpbGVfaW5mbykKICAgICAgICAg"
    "ICAgc2VsZi5yZWNvcmRzX2xpc3QuYWRkSXRlbShpdGVtKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVs"
    "LnNldFRleHQoZiJMb2FkZWQge2xlbihmaWxlcyl9IEdvb2dsZSBEcml2ZSBpdGVtKHMpLiIpCgoKY2xh"
    "c3MgVGFza3NUYWIoUVdpZGdldCk6CiAgICAiIiJUYXNrIHJlZ2lzdHJ5ICsgR29vZ2xlLWZpcnN0IGVk"
    "aXRvciB3b3JrZmxvdyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAg"
    "ICAgdGFza3NfcHJvdmlkZXIsCiAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuLAogICAgICAgIG9uX2Nv"
    "bXBsZXRlX3NlbGVjdGVkLAogICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZCwKICAgICAgICBvbl90b2dn"
    "bGVfY29tcGxldGVkLAogICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZCwKICAgICAgICBvbl9maWx0ZXJf"
    "Y2hhbmdlZCwKICAgICAgICBvbl9lZGl0b3Jfc2F2ZSwKICAgICAgICBvbl9lZGl0b3JfY2FuY2VsLAog"
    "ICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lLAogICAgICAgIHBhcmVudD1Ob25lLAogICAgKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl90YXNrc19wcm92aWRl"
    "ciA9IHRhc2tzX3Byb3ZpZGVyCiAgICAgICAgc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuID0gb25fYWRk"
    "X2VkaXRvcl9vcGVuCiAgICAgICAgc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQgPSBvbl9jb21wbGV0"
    "ZV9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCA9IG9uX2NhbmNlbF9zZWxl"
    "Y3RlZAogICAgICAgIHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQgPSBvbl90b2dnbGVfY29tcGxldGVk"
    "CiAgICAgICAgc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkID0gb25fcHVyZ2VfY29tcGxldGVkCiAgICAg"
    "ICAgc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQgPSBvbl9maWx0ZXJfY2hhbmdlZAogICAgICAgIHNlbGYu"
    "X29uX2VkaXRvcl9zYXZlID0gb25fZWRpdG9yX3NhdmUKICAgICAgICBzZWxmLl9vbl9lZGl0b3JfY2Fu"
    "Y2VsID0gb25fZWRpdG9yX2NhbmNlbAogICAgICAgIHNlbGYuX2RpYWdfbG9nZ2VyID0gZGlhZ25vc3Rp"
    "Y3NfbG9nZ2VyCiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfdGhyZWFkID0gTm9uZQogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICBkZWYgX2J1"
    "aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAg"
    "ICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNp"
    "bmcoNCkKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAg"
    "ICByb290LmFkZFdpZGdldChzZWxmLndvcmtzcGFjZV9zdGFjaywgMSkKCiAgICAgICAgbm9ybWFsID0g"
    "UVdpZGdldCgpCiAgICAgICAgbm9ybWFsX2xheW91dCA9IFFWQm94TGF5b3V0KG5vcm1hbCkKICAgICAg"
    "ICBub3JtYWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG5vcm1h"
    "bF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgi"
    "VGFzayByZWdpc3RyeSBpcyBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAg"
    "bm9ybWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIGZpbHRlcl9y"
    "b3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgREFURSBSQU5HRSIpKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8gPSBRQ29tYm9C"
    "b3goKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiV0VFSyIsICJ3ZWVrIikK"
    "ICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk1PTlRIIiwgIm1vbnRoIikKICAg"
    "ICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk5FWFQgMyBNT05USFMiLCAibmV4dF8z"
    "X21vbnRocyIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJZRUFSIiwgInll"
    "YXIiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uc2V0Q3VycmVudEluZGV4KDIpCiAgICAg"
    "ICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgIGxhbWJkYSBfOiBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZChzZWxmLnRhc2tfZmlsdGVyX2Nv"
    "bWJvLmN1cnJlbnREYXRhKCkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgICkKICAgICAgICBmaWx0"
    "ZXJfcm93LmFkZFdpZGdldChzZWxmLnRhc2tfZmlsdGVyX2NvbWJvKQogICAgICAgIGZpbHRlcl9yb3cu"
    "YWRkU3RyZXRjaCgxKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgog"
    "ICAgICAgIHNlbGYudGFza190YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiU3RhdHVzIiwgIkR1ZSIsICJUYXNrIiwg"
    "IlNvdXJjZSJdKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcihRQWJz"
    "dHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0"
    "ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEVkaXRUcmlnZ2VycyhRQWJz"
    "dHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmlnZ2VycykKICAgICAgICBzZWxmLnRhc2tf"
    "dGFibGUudmVydGljYWxIZWFkZXIoKS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYudGFza190"
    "YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcu"
    "UmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9u"
    "dGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5S"
    "ZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCku"
    "c2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl91cGRhdGVfYWN0aW9uX2J1"
    "dHRvbl9zdGF0ZSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfdGFibGUs"
    "IDEpCgogICAgICAgIGFjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rh"
    "c2tfd29ya3NwYWNlID0gX2dvdGhpY19idG4oIkFERCBUQVNLIikKICAgICAgICBzZWxmLmJ0bl9jb21w"
    "bGV0ZV90YXNrID0gX2dvdGhpY19idG4oIkNPTVBMRVRFIFNFTEVDVEVEIikKICAgICAgICBzZWxmLmJ0"
    "bl9jYW5jZWxfdGFzayA9IF9nb3RoaWNfYnRuKCJDQU5DRUwgU0VMRUNURUQiKQogICAgICAgIHNlbGYu"
    "YnRuX3RvZ2dsZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiU0hPVyBDT01QTEVURUQiKQogICAgICAg"
    "IHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJQVVJHRSBDT01QTEVURUQiKQog"
    "ICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25f"
    "YWRkX2VkaXRvcl9vcGVuKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNr"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5f"
    "dG9nZ2xlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCkK"
    "ICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3B1"
    "cmdlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJsZWQoRmFs"
    "c2UpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBm"
    "b3IgYnRuIGluICgKICAgICAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLAogICAgICAg"
    "ICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFz"
    "aywKICAgICAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICAgICAgc2VsZi5i"
    "dG5fcHVyZ2VfY29tcGxldGVkLAogICAgICAgICk6CiAgICAgICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0"
    "KGJ0bikKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChhY3Rpb25zKQogICAgICAgIHNlbGYu"
    "d29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChub3JtYWwpCgogICAgICAgIGVkaXRvciA9IFFXaWRnZXQo"
    "KQogICAgICAgIGVkaXRvcl9sYXlvdXQgPSBRVkJveExheW91dChlZGl0b3IpCiAgICAgICAgZWRpdG9y"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBlZGl0b3JfbGF5b3V0"
    "LnNldFNwYWNpbmcoNCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBUQVNLIEVESVRPUiDigJQgR09PR0xFLUZJUlNUIikpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0"
    "byBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19U"
    "RVhUX0RJTX07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAg"
    "ICAgKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfc3RhdHVz"
    "X2xhYmVsKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiVGFzayBOYW1lIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IERhdGUgKFlZWVktTU0t"
    "REQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUgPSBRTGluZUVkaXQoKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IFRp"
    "bWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBE"
    "YXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZSA9IFFMaW5l"
    "RWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQo"
    "IkVuZCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24gPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24uc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJMb2NhdGlvbiAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Ug"
    "PSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRQbGFjZWhv"
    "bGRlclRleHQoIlJlY3VycmVuY2UgUlJVTEUgKG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2Vk"
    "aXRvcl9hbGxfZGF5ID0gUUNoZWNrQm94KCJBbGwtZGF5IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9y"
    "X25vdGVzID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiTm90ZXMiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0TWF4aW11"
    "bUhlaWdodCg5MCkKICAgICAgICBmb3Igd2lkZ2V0IGluICgKICAgICAgICAgICAgc2VsZi50YXNrX2Vk"
    "aXRvcl9uYW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUsCiAgICAgICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9lbmRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZSwKICAgICAgICAg"
    "ICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9y"
    "ZWN1cnJlbmNlLAogICAgICAgICk6CiAgICAgICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHdp"
    "ZGdldCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX2FsbF9k"
    "YXkpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9ub3Rlcywg"
    "MSkKICAgICAgICBlZGl0b3JfYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSA9"
    "IF9nb3RoaWNfYnRuKCJTQVZFIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNBTkNF"
    "TCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9zYXZlKQog"
    "ICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9jYW5jZWwpCiAg"
    "ICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGVkaXRvcl9hY3Rp"
    "b25zLmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFN0cmV0Y2go"
    "MSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZExheW91dChlZGl0b3JfYWN0aW9ucykKICAgICAgICBz"
    "ZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQoZWRpdG9yKQoKICAgICAgICBzZWxmLm5vcm1hbF93"
    "b3Jrc3BhY2UgPSBub3JtYWwKICAgICAgICBzZWxmLmVkaXRvcl93b3Jrc3BhY2UgPSBlZGl0b3IKICAg"
    "ICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtz"
    "cGFjZSkKCiAgICBkZWYgX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZW5hYmxlZCA9IGJvb2woc2VsZi5zZWxlY3RlZF90YXNrX2lkcygpKQogICAgICAgIHNlbGYu"
    "YnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNl"
    "bF90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKCiAgICBkZWYgc2VsZWN0ZWRfdGFza19pZHMoc2VsZikg"
    "LT4gbGlzdFtzdHJdOgogICAgICAgIGlkczogbGlzdFtzdHJdID0gW10KICAgICAgICBmb3IgciBpbiBy"
    "YW5nZShzZWxmLnRhc2tfdGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0g"
    "c2VsZi50YXNrX3RhYmxlLml0ZW0ociwgMCkKICAgICAgICAgICAgaWYgc3RhdHVzX2l0ZW0gaXMgTm9u"
    "ZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdCBzdGF0dXNfaXRlbS5p"
    "c1NlbGVjdGVkKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICB0YXNrX2lkID0g"
    "c3RhdHVzX2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIGlmIHRh"
    "c2tfaWQgYW5kIHRhc2tfaWQgbm90IGluIGlkczoKICAgICAgICAgICAgICAgIGlkcy5hcHBlbmQodGFz"
    "a19pZCkKICAgICAgICByZXR1cm4gaWRzCgogICAgZGVmIGxvYWRfdGFza3Moc2VsZiwgdGFza3M6IGxp"
    "c3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFJvd0NvdW50KDApCiAg"
    "ICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIHJvdyA9IHNlbGYudGFza190YWJsZS5y"
    "b3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5pbnNlcnRSb3cocm93KQogICAgICAg"
    "ICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAg"
    "ICAgICAgICBzdGF0dXNfaWNvbiA9ICLimJEiIGlmIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5j"
    "ZWxsZWQifSBlbHNlICLigKIiCiAgICAgICAgICAgIGR1ZSA9ICh0YXNrLmdldCgiZHVlX2F0Iikgb3Ig"
    "IiIpLnJlcGxhY2UoIlQiLCAiICIpCiAgICAgICAgICAgIHRleHQgPSAodGFzay5nZXQoInRleHQiKSBv"
    "ciAiUmVtaW5kZXIiKS5zdHJpcCgpIG9yICJSZW1pbmRlciIKICAgICAgICAgICAgc291cmNlID0gKHRh"
    "c2suZ2V0KCJzb3VyY2UiKSBvciAibG9jYWwiKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pdGVt"
    "ID0gUVRhYmxlV2lkZ2V0SXRlbShmIntzdGF0dXNfaWNvbn0ge3N0YXR1c30iKQogICAgICAgICAgICBz"
    "dGF0dXNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgdGFzay5nZXQoImlkIikp"
    "CiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMCwgc3RhdHVzX2l0ZW0pCiAg"
    "ICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRhYmxlV2lkZ2V0SXRlbShk"
    "dWUpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdl"
    "dEl0ZW0odGV4dCkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMywgUVRh"
    "YmxlV2lkZ2V0SXRlbShzb3VyY2UpKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJM"
    "b2FkZWQge2xlbih0YXNrcyl9IHRhc2socykuIikKICAgICAgICBzZWxmLl91cGRhdGVfYWN0aW9uX2J1"
    "dHRvbl9zdGF0ZSgpCgogICAgZGVmIF9kaWFnKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9"
    "ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIHNlbGYuX2RpYWdfbG9n"
    "Z2VyOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIobWVzc2FnZSwgbGV2ZWwpCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGRlZiBzdG9wX3JlZnJlc2hf"
    "d29ya2VyKHNlbGYsIHJlYXNvbjogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgdGhyZWFkID0gZ2V0"
    "YXR0cihzZWxmLCAiX3JlZnJlc2hfdGhyZWFkIiwgTm9uZSkKICAgICAgICBpZiB0aHJlYWQgaXMgbm90"
    "IE5vbmUgYW5kIGhhc2F0dHIodGhyZWFkLCAiaXNSdW5uaW5nIikgYW5kIHRocmVhZC5pc1J1bm5pbmco"
    "KToKICAgICAgICAgICAgc2VsZi5fZGlhZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtUSFJFQURd"
    "W1dBUk5dIHN0b3AgcmVxdWVzdGVkIGZvciByZWZyZXNoIHdvcmtlciByZWFzb249e3JlYXNvbiBvciAn"
    "dW5zcGVjaWZpZWQnfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdGhyZWFkLnJlcXVlc3RJbnRlcnJ1cHRpb24oKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucXVpdCgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRocmVhZC53YWl0KDIwMDApCiAgICAg"
    "ICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBpZiBub3QgY2FsbGFibGUoc2VsZi5fdGFza3NfcHJvdmlkZXIpOgogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYubG9hZF90YXNrcyhzZWxmLl90YXNr"
    "c19wcm92aWRlcigpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWcoZiJbVEFTS1NdW1RBQl1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9S"
    "IikKICAgICAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX3Jl"
    "ZnJlc2hfZXhjZXB0aW9uIikKCiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfY2xvc2UiKQog"
    "ICAgICAgIHN1cGVyKCkuY2xvc2VFdmVudChldmVudCkKCiAgICBkZWYgc2V0X3Nob3dfY29tcGxldGVk"
    "KHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQg"
    "PSBib29sKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5zZXRUZXh0KCJI"
    "SURFIENPTVBMRVRFRCIgaWYgc2VsZi5fc2hvd19jb21wbGV0ZWQgZWxzZSAiU0hPVyBDT01QTEVURUQi"
    "KQoKICAgIGRlZiBzZXRfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4g"
    "Tm9uZToKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX1RFWFRfRElNCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge2NvbG9yfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgcGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0"
    "dXNfbGFiZWwuc2V0VGV4dCh0ZXh0KQoKICAgIGRlZiBvcGVuX2VkaXRvcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5lZGl0b3Jfd29y"
    "a3NwYWNlKQoKICAgIGRlZiBjbG9zZV9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLndv"
    "cmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCgpjbGFz"
    "cyBTZWxmVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hJ3MgaW50ZXJuYWwgZGlhbG9ndWUg"
    "c3BhY2UuCiAgICBSZWNlaXZlczogaWRsZSBuYXJyYXRpdmUgb3V0cHV0LCB1bnNvbGljaXRlZCB0cmFu"
    "c21pc3Npb25zLAogICAgICAgICAgICAgIFBvSSBsaXN0IGZyb20gZGFpbHkgcmVmbGVjdGlvbiwgdW5h"
    "bnN3ZXJlZCBxdWVzdGlvbiBmbGFncywKICAgICAgICAgICAgICBqb3VybmFsIGxvYWQgbm90aWZpY2F0"
    "aW9ucy4KICAgIFJlYWQtb25seSBkaXNwbGF5LiBTZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIg"
    "YWx3YXlzLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoZiLinacgSU5ORVIgU0FOQ1RVTSDigJQge0RFQ0tfTkFNRS51cHBlcigpfSdT"
    "IFBSSVZBVEUgVEhPVUdIVFMiKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi"
    "4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJv"
    "b3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtD"
    "X0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFX0RJTX07ICIK"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEx"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rp"
    "c3BsYXksIDEpCgogICAgZGVmIGFwcGVuZChzZWxmLCBsYWJlbDogc3RyLCB0ZXh0OiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikK"
    "ICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJOQVJSQVRJVkUiOiAgQ19HT0xELAogICAgICAg"
    "ICAgICAiUkVGTEVDVElPTiI6IENfUFVSUExFLAogICAgICAgICAgICAiSk9VUk5BTCI6ICAgIENfU0lM"
    "VkVSLAogICAgICAgICAgICAiUE9JIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICJTWVNU"
    "RU0iOiAgICAgQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBjb2xvcnMuZ2V0KGxh"
    "YmVsLnVwcGVyKCksIENfR09MRCkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAg"
    "ICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntjb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYn4p2nIHtsYWJl"
    "bH08L3NwYW4+PGJyPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57"
    "dGV4dH08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgiIikKICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAg"
    "IHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAg"
    "ZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDi"
    "lIDilIAgRElBR05PU1RJQ1MgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEaWFnbm9zdGljc1RhYihRV2lkZ2V0KToKICAgICIiIgog"
    "ICAgQmFja2VuZCBkaWFnbm9zdGljcyBkaXNwbGF5LgogICAgUmVjZWl2ZXM6IGhhcmR3YXJlIGRldGVj"
    "dGlvbiByZXN1bHRzLCBkZXBlbmRlbmN5IGNoZWNrIHJlc3VsdHMsCiAgICAgICAgICAgICAgQVBJIGVy"
    "cm9ycywgc3luYyBmYWlsdXJlcywgdGltZXIgZXZlbnRzLCBqb3VybmFsIGxvYWQgbm90aWNlcywKICAg"
    "ICAgICAgICAgICBtb2RlbCBsb2FkIHN0YXR1cywgR29vZ2xlIGF1dGggZXZlbnRzLgogICAgQWx3YXlz"
    "IHNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "cm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRyID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRElBR05PU1RJQ1Mg4oCU"
    "IFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19i"
    "dG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhk"
    "ci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAg"
    "ICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQog"
    "ICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9y"
    "OiB7Q19TSUxWRVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "IgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiAnQ291cmllciBOZXcnLCBtb25vc3BhY2U7ICIKICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGxvZyhzZWxmLCBtZXNzYWdl"
    "OiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0"
    "ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAg"
    "ICAgICAgICAgICJJTkZPIjogIENfU0lMVkVSLAogICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAog"
    "ICAgICAgICAgICAiV0FSTiI6ICBDX0dPTEQsCiAgICAgICAgICAgICJFUlJPUiI6IENfQkxPT0QsCiAg"
    "ICAgICAgICAgICJERUJVRyI6IENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gbGV2"
    "ZWxfY29sb3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZFUikKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyI+W3t0"
    "aW1lc3RhbXB9XTwvc3Bhbj4gJwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9"
    "OyI+e21lc3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Ny"
    "b2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBsb2dfbWFueShzZWxmLCBtZXNzYWdl"
    "czogbGlzdFtzdHJdLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIGZvciBtc2cg"
    "aW4gbWVzc2FnZXM6CiAgICAgICAgICAgIGx2bCA9IGxldmVsCiAgICAgICAgICAgIGlmICLinJMiIGlu"
    "IG1zZzogICAgbHZsID0gIk9LIgogICAgICAgICAgICBlbGlmICLinJciIGluIG1zZzogIGx2bCA9ICJX"
    "QVJOIgogICAgICAgICAgICBlbGlmICJFUlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2bCA9ICJFUlJPUiIK"
    "ICAgICAgICAgICAgc2VsZi5sb2cobXNnLCBsdmwpCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVs"
    "ZXNldCBhbmQgY29kZSBsZXNzb25zIGJyb3dzZXIuCiAgICBBZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRl"
    "IGxlc3NvbnMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVhcm5l"
    "ZERCIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNo"
    "KCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAg"
    "ICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBGaWx0ZXIgYmFyCiAgICAgICAgZmlsdGVyX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9zZWFyY2ggPSBRTGluZUVkaXQoKQogICAgICAg"
    "IHNlbGYuX3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNlYXJjaCBsZXNzb25zLi4uIikKICAgICAg"
    "ICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIu"
    "YWRkSXRlbXMoWyJBbGwiLCAiTFNMIiwgIlB5dGhvbiIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJKYXZhU2NyaXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5f"
    "c2VhcmNoLnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIHNlbGYuX2xhbmdf"
    "ZmlsdGVyLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmaWx0"
    "ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIlNlYXJjaDoiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdp"
    "ZGdldChzZWxmLl9zZWFyY2gsIDEpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJM"
    "YW5ndWFnZToiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikK"
    "ICAgICAgICByb290LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBidG5fYmFyID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0bigi4pymIEFkZCBMZXNzb24iKQogICAg"
    "ICAgIGJ0bl9kZWwgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGJ0bl9kZWwuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2RlbGV0ZSkKICAgICAgICBidG5fYmFyLmFkZFdpZGdldChidG5fYWRkKQogICAgICAgIGJ0"
    "bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAg"
    "ICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdl"
    "dCgwLCA0KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoCiAgICAg"
    "ICAgICAgIFsiTGFuZ3VhZ2UiLCAiUmVmZXJlbmNlIEtleSIsICJTdW1tYXJ5IiwgIkVudmlyb25tZW50"
    "Il0KICAgICAgICApCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0"
    "cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHls"
    "ZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0"
    "aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBVc2Ugc3BsaXR0ZXIg"
    "YmV0d2VlbiB0YWJsZSBhbmQgZGV0YWlsCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3Jp"
    "ZW50YXRpb24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoK"
    "ICAgICAgICAjIERldGFpbCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAg"
    "ICAgICBkZXRhaWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBkZXRh"
    "aWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIGRldGFpbF9sYXlv"
    "dXQuc2V0U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZVTEwgUlVMRSIpKQog"
    "ICAgICAgIGRldGFpbF9oZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVs"
    "ZSA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldEZpeGVk"
    "V2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2FibGUoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnRvZ2dsZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZWRpdF9t"
    "b2RlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYuX2J0bl9z"
    "YXZlX3J1bGUuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdp"
    "ZGdldChzZWxmLl9idG5fZWRpdF9ydWxlKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNl"
    "bGYuX2J0bl9zYXZlX3J1bGUpCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hl"
    "YWRlcikKCiAgICAgICAgc2VsZi5fZGV0YWlsID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kZXRh"
    "aWwuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0TWluaW11bUhlaWdodCgx"
    "MjApCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0"
    "YWlsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZGV0YWlsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdl"
    "dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFszMDAsIDE4MF0pCiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRlZiByZWZy"
    "ZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcSAgICA9IHNlbGYuX3NlYXJjaC50ZXh0KCkKICAgICAg"
    "ICBsYW5nID0gc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHQoKQogICAgICAgIGxhbmcgPSAiIiBp"
    "ZiBsYW5nID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAgIHNlbGYuX3JlY29yZHMgPSBzZWxmLl9kYi5z"
    "ZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3Vu"
    "dCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYu"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAg"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdl"
    "dEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2UiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgicmVmZXJlbmNl"
    "X2tleSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAg"
    "ICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRJdGVtKHIsIDMsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJl"
    "Yy5nZXQoImVudmlyb25tZW50IiwiIikpKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgc2VsZi5fZWRpdGlu"
    "Z19yb3cgPSByb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAg"
    "ICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRQ"
    "bGFpblRleHQoCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiAr"
    "CiAgICAgICAgICAgICAgICAoIlJlc29sdXRpb246ICIgKyByZWMuZ2V0KCJyZXNvbHV0aW9uIiwiIikg"
    "aWYgcmVjLmdldCgicmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "IyBSZXNldCBlZGl0IG1vZGUgb24gbmV3IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxmLl9idG5fZWRp"
    "dF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCgogICAgZGVmIF90b2dnbGVfZWRpdF9tb2RlKHNlbGYsIGVk"
    "aXRpbmc6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KG5vdCBl"
    "ZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShlZGl0aW5nKQogICAg"
    "ICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2VsIiBpZiBlZGl0aW5nIGVsc2UgIkVk"
    "aXQiKQogICAgICAgIGlmIGVkaXRpbmc6CiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfR09MRF9ESU19OyAiCiAgICAg"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFw"
    "eDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNl"
    "bGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgIyBSZWxvYWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5jZWwKICAgICAgICAgICAgc2VsZi5fb25f"
    "c2VsZWN0KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93"
    "ID0gc2VsZi5fZWRpdGluZ19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRz"
    "KToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2RldGFpbC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgIyBTcGxpdCByZXNvbHV0aW9uIGJhY2sgb3V0IGlmIHByZXNlbnQKICAgICAgICAgICAg"
    "aWYgIlxuXG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAgICAgICAgICAgICBwYXJ0cyA9IHRleHQu"
    "c3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHBh"
    "cnRzWzBdLnN0cmlwKCkKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBwYXJ0c1sxXS5zdHJpcCgp"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gdGV4dAogICAgICAg"
    "ICAgICAgICAgcmVzb2x1dGlvbiA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoInJlc29sdXRpb24iLCAi"
    "IikKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJmdWxsX3J1bGUiXSAgPSBmdWxsX3J1bGUK"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJyZXNvbHV0aW9uIl0gPSByZXNvbHV0aW9uCiAg"
    "ICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX2RiLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAg"
    "ICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlh"
    "bG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgTGVzc29uIikKICAgICAgICBk"
    "bGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQog"
    "ICAgICAgIGRsZy5yZXNpemUoNTAwLCA0MDApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykK"
    "ICAgICAgICBlbnYgID0gUUxpbmVFZGl0KCJMU0wiKQogICAgICAgIGxhbmcgPSBRTGluZUVkaXQoIkxT"
    "TCIpCiAgICAgICAgcmVmICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc3VtbSA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgcnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVtSGVpZ2h0KDEwMCkK"
    "ICAgICAgICByZXMgID0gUUxpbmVFZGl0KCkKICAgICAgICBsaW5rID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICBmb3IgbGFiZWwsIHcgaW4gWwogICAgICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgiTGFu"
    "Z3VhZ2U6IiwgbGFuZyksCiAgICAgICAgICAgICgiUmVmZXJlbmNlIEtleToiLCByZWYpLCAoIlN1bW1h"
    "cnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBSdWxlOiIsIHJ1bGUpLCAoIlJlc29sdXRpb246"
    "IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06CiAgICAgICAgICAg"
    "IGZvcm0uYWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "b2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAg"
    "IG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWpl"
    "Y3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBm"
    "b3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2Rl"
    "LkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9kYi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9u"
    "bWVudD1lbnYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQo"
    "KS5zdHJpcCgpLAogICAgICAgICAgICAgICAgcmVmZXJlbmNlX2tleT1yZWYudGV4dCgpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICAgICBzdW1tYXJ5PXN1bW0udGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAg"
    "ICBmdWxsX3J1bGU9cnVsZS50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZXNv"
    "bHV0aW9uPXJlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxpbms9bGluay50ZXh0KCku"
    "c3RyaXAoKSwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJv"
    "dygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJl"
    "Y19pZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImlkIiwiIikKICAgICAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTGVzc29uIiwK"
    "ICAgICAgICAgICAgICAgICJEZWxldGUgdGhpcyBsZXNzb24/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAg"
    "ICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3Nh"
    "Z2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fZGIuZGVsZXRlKHJl"
    "Y19pZCkKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgTU9EVUxFIFRSQUNL"
    "RVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBNb2R1bGVUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hbCBtb2R1bGUgcGlw"
    "ZWxpbmUgdHJhY2tlci4KICAgIFRyYWNrIHBsYW5uZWQvaW4tcHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBh"
    "cyB0aGV5IGFyZSBkZXNpZ25lZC4KICAgIEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNj"
    "cmlwdGlvbiwgTm90ZXMuCiAgICBFeHBvcnQgdG8gVFhUIGZvciBwYXN0aW5nIGludG8gc2Vzc2lvbnMu"
    "CiAgICBJbXBvcnQ6IHBhc3RlIGEgZmluYWxpemVkIHNwZWMsIGl0IHBhcnNlcyBuYW1lIGFuZCBkZXRh"
    "aWxzLgogICAgVGhpcyBpcyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5lY3RlZCB0byBkZWNr"
    "X2J1aWxkZXIncyBNT0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIs"
    "ICJEZXNpZ25pbmciLCAiUmVhZHkgdG8gQnVpbGQiLCAiUGFydGlhbCIsICJCdWlsdCJdCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibW9kdWxlX3RyYWNr"
    "ZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9kdWxlIikKICAgICAgICBzZWxmLl9idG5f"
    "ZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290"
    "aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4"
    "cG9ydCBUWFQiKQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNw"
    "ZWMiKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZWRpdCwgc2VsZi5f"
    "YnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCwgc2VsZi5fYnRuX2lt"
    "cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDgwKQogICAgICAgICAgICBiLnNldE1p"
    "bmltdW1IZWlnaHQoMjYpCiAgICAgICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYnRu"
    "X2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBz"
    "ZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRu"
    "X2VkaXQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBzZWxmLl9idG5faW1wb3J0LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19pbXBvcnQpCgogICAgICAgICMgVGFibGUKICAgICAgICBzZWxm"
    "Ll90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250"
    "YWxIZWFkZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3JpcHRpb24iXSkKICAg"
    "ICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgIGhoLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0Q29sdW1uV2lkdGgoMCwgMTYwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29s"
    "dW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhh"
    "dmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0"
    "Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAg"
    "IHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoK"
    "ICAgICAgICAjIFNwbGl0dGVyCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRp"
    "b24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAg"
    "ICAjIE5vdGVzIHBhbmVsCiAgICAgICAgbm90ZXNfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgbm90"
    "ZXNfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm90ZXNfd2lkZ2V0KQogICAgICAgIG5vdGVzX2xheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0U3BhY2lu"
    "ZygyKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTk9URVMi"
    "KSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9u"
    "b3Rlc19kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5z"
    "ZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4"
    "OyIKICAgICAgICApCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ub3Rlc19kaXNw"
    "bGF5KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChub3Rlc193aWRnZXQpCiAgICAgICAgc3BsaXR0"
    "ZXIuc2V0U2l6ZXMoWzI1MCwgMTUwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkK"
    "CiAgICAgICAgIyBDb3VudCBsYWJlbAogICAgICAgIHNlbGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikK"
    "ICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvdW50X2xibCkKCiAgICBk"
    "ZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3Ig"
    "cmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibmFtZSIsICIiKSkpCiAgICAg"
    "ICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdGF0dXMiLCAiSWRl"
    "YSIpKQogICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3Jz"
    "ID0gewogICAgICAgICAgICAgICAgIklkZWEiOiAgICAgICAgICAgICBDX1RFWFRfRElNLAogICAgICAg"
    "ICAgICAgICAgIkRlc2lnbmluZyI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAgICAgIlJl"
    "YWR5IHRvIEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAgICAgICAgICAgICJQYXJ0aWFsIjogICAgICAg"
    "ICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0IjogICAgICAgICAgICBDX0dSRUVOLAog"
    "ICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVncm91bmQoCiAgICAgICAg"
    "ICAgICAgICBRQ29sb3Ioc3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpLCBD"
    "X1RFWFRfRElNKSkKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIs"
    "IDEsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAg"
    "ICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwgIiIpWzo4MF0p"
    "KQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAg"
    "ICAgICAgICBzID0gcmVjLmdldCgic3RhdHVzIiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10g"
    "PSBjb3VudHMuZ2V0KHMsIDApICsgMQogICAgICAgIGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfTog"
    "e259IiBmb3IgcywgbiBpbiBjb3VudHMuaXRlbXMoKSkKICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0"
    "VGV4dCgKICAgICAgICAgICAgZiJUb3RhbDoge2xlbihzZWxmLl9yZWNvcmRzKX0gICB7Y291bnRfc3Ry"
    "fSIKICAgICAgICApCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cg"
    "PSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9y"
    "ZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNl"
    "bGYuX25vdGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwgIiIpKQoKICAgIGRl"
    "ZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZygpCgog"
    "ICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3Vy"
    "cmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAg"
    "ICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coc2VsZi5fcmVjb3Jkc1tyb3ddLCByb3cpCgogICAgZGVm"
    "IF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUsIHJvdzogaW50ID0gLTEpIC0+"
    "IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRs"
    "ZSgiTW9kdWxlIiBpZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAg"
    "ICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09M"
    "RH07IikKICAgICAgICBkbGcucmVzaXplKDU0MCwgNDQwKQogICAgICAgIGZvcm0gPSBRVkJveExheW91"
    "dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGluZUVkaXQocmVjLmdldCgibmFtZSIsIiIpIGlm"
    "IHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJNb2R1bGUg"
    "bmFtZSIpCgogICAgICAgIHN0YXR1c19jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2Nv"
    "bWJvLmFkZEl0ZW1zKHNlbGYuU1RBVFVTRVMpCiAgICAgICAgaWYgcmVjOgogICAgICAgICAgICBpZHgg"
    "PSBzdGF0dXNfY29tYm8uZmluZFRleHQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAg"
    "ICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgICAgIHN0YXR1c19jb21iby5zZXRDdXJyZW50SW5kZXgo"
    "aWR4KQoKICAgICAgICBkZXNjX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwi"
    "IikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9u"
    "ZS1saW5lIGRlc2NyaXB0aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAg"
    "ICAgIG5vdGVzX2ZpZWxkLnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIkZ1"
    "bGwgbm90ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVudHMsIGVkZ2UgY2FzZXMuLi4iCiAgICAg"
    "ICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1IZWlnaHQoMjAwKQoKICAgICAgICBmb3Ig"
    "bGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxkKSwKICAgICAg"
    "ICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzX2NvbWJvKSwKICAgICAgICAgICAgKCJEZXNjcmlwdGlvbjoi"
    "LCBkZXNjX2ZpZWxkKSwKICAgICAgICAgICAgKCJOb3RlczoiLCBub3Rlc19maWVsZCksCiAgICAgICAg"
    "XToKICAgICAgICAgICAgcm93X2xheW91dCA9IFFIQm94TGF5b3V0KCkKICAgICAgICAgICAgbGJsID0g"
    "UUxhYmVsKGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4ZWRXaWR0aCg5MCkKICAgICAgICAgICAg"
    "cm93X2xheW91dC5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldCh3"
    "aWRnZXQpCiAgICAgICAgICAgIGZvcm0uYWRkTGF5b3V0KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9y"
    "b3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgICA9IF9nb3RoaWNfYnRuKCJTYXZlIikK"
    "ICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX3NhdmUu"
    "Y2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5l"
    "Y3QoZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBi"
    "dG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGZvcm0uYWRkTGF5b3V0KGJ0bl9yb3cp"
    "CgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAg"
    "ICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgcmVjLmdldCgi"
    "aWQiLCBzdHIodXVpZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ugc3RyKHV1aWQudXVpZDQoKSksCiAgICAg"
    "ICAgICAgICAgICAibmFtZSI6ICAgICAgICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICAgICAgInN0YXR1cyI6ICAgICAgc3RhdHVzX2NvbWJvLmN1cnJlbnRUZXh0KCksCiAgICAgICAg"
    "ICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAg"
    "ICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0aW1lLm5vdygp"
    "Lmlzb2Zvcm1hdCgpKSBpZiByZWMgZWxzZSBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAg"
    "ICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAg"
    "ICAgICB9CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2Vs"
    "Zi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAg"
    "IGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICBuYW1lID0gc2VsZi5f"
    "cmVjb3Jkc1tyb3ddLmdldCgibmFtZSIsInRoaXMgbW9kdWxlIikKICAgICAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTW9kdWxlIiwK"
    "ICAgICAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAg"
    "ICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFu"
    "ZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJv"
    "dykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMi"
    "KQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkK"
    "ICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAg"
    "ICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYibW9kdWxlc197dHN9LnR4dCIKICAgICAg"
    "ICAgICAgbGluZXMgPSBbCiAgICAgICAgICAgICAgICAiRUNITyBERUNLIOKAlCBNT0RVTEUgVFJBQ0tF"
    "UiBFWFBPUlQiLAogICAgICAgICAgICAgICAgZiJFeHBvcnRlZDoge2RhdGV0aW1lLm5vdygpLnN0cmZ0"
    "aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAgICAgICAgICAgICBmIlRvdGFsIG1vZHVsZXM6"
    "IHtsZW4oc2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAgICAgICI9IiAqIDYwLAogICAgICAgICAg"
    "ICAgICAgIiIsCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRz"
    "OgogICAgICAgICAgICAgICAgbGluZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVM"
    "RToge3JlYy5nZXQoJ25hbWUnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiU3RhdHVzOiB7cmVj"
    "LmdldCgnc3RhdHVzJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIkRlc2NyaXB0aW9uOiB7cmVj"
    "LmdldCgnZGVzY3JpcHRpb24nLCcnKX0iLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAg"
    "ICAgICAgICAgICJOb3RlczoiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIi0iICogNDAsCiAgICAg"
    "ICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53"
    "cml0ZV90ZXh0KCJcbiIuam9pbihsaW5lcyksIGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIFFB"
    "cHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykpCiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwK"
    "ICAgICAgICAgICAgICAgIGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9XG5c"
    "bkFsc28gY29waWVkIHRvIGNsaXBib2FyZC4iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoc2VsZiwgIkV4cG9ydCBF"
    "cnJvciIsIHN0cihlKSkKCiAgICBkZWYgX2RvX2ltcG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IkltcG9ydCBhIG1vZHVsZSBzcGVjIGZyb20gY2xpcGJvYXJkIG9yIHR5cGVkIHRleHQuIiIiCiAgICAg"
    "ICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1v"
    "ZHVsZSBTcGVjIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTAwLCAzNDApCiAgICAgICAgbGF5"
    "b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKAogICAg"
    "ICAgICAgICAiUGFzdGUgYSBtb2R1bGUgc3BlYyBiZWxvdy5cbiIKICAgICAgICAgICAgIkZpcnN0IGxp"
    "bmUgd2lsbCBiZSB1c2VkIGFzIHRoZSBtb2R1bGUgbmFtZS4iCiAgICAgICAgKSkKICAgICAgICB0ZXh0"
    "X2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "UGFzdGUgbW9kdWxlIHNwZWMgaGVyZS4uLiIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2Zp"
    "ZWxkLCAxKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX29rICAgICA9"
    "IF9nb3RoaWNfYnRuKCJJbXBvcnQiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2Fu"
    "Y2VsIikKICAgICAgICBidG5fb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRu"
    "X2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdl"
    "dChidG5fb2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFs"
    "b2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByYXcgPSB0ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0KCku"
    "c3RyaXAoKQogICAgICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAg"
    "ICAgICAgIGxpbmVzID0gcmF3LnNwbGl0bGluZXMoKQogICAgICAgICAgICAjIEZpcnN0IG5vbi1lbXB0"
    "eSBsaW5lID0gbmFtZQogICAgICAgICAgICBuYW1lID0gIiIKICAgICAgICAgICAgZm9yIGxpbmUgaW4g"
    "bGluZXM6CiAgICAgICAgICAgICAgICBpZiBsaW5lLnN0cmlwKCk6CiAgICAgICAgICAgICAgICAgICAg"
    "bmFtZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIG5l"
    "d19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwK"
    "ICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVbOjYwXSwKICAgICAgICAgICAgICAgICJz"
    "dGF0dXMiOiAgICAgICJJZGVhIiwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6ICIiLAogICAg"
    "ICAgICAgICAgICAgIm5vdGVzIjogICAgICAgcmF3LAogICAgICAgICAgICAgICAgImNyZWF0ZWQiOiAg"
    "ICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAg"
    "ICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIFBBU1Mg"
    "NSBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBBbGwgdGFiIGNvbnRlbnQgY2xhc3NlcyBkZWZpbmVkLgojIFNMU2NhbnNUYWI6"
    "IHJlYnVpbHQg4oCUIERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLCB0aW1lc3RhbXAgcGFyc2VyIGZp"
    "eGVkLAojICAgICAgICAgICAgIGNhcmQvZ3JpbW9pcmUgc3R5bGUsIGNvcHktdG8tY2xpcGJvYXJkIGNv"
    "bnRleHQgbWVudS4KIyBTTENvbW1hbmRzVGFiOiBnb3RoaWMgdGFibGUsIOKniSBDb3B5IENvbW1hbmQg"
    "YnV0dG9uLgojIEpvYlRyYWNrZXJUYWI6IGZ1bGwgcmVidWlsZCDigJQgbXVsdGktc2VsZWN0LCBhcmNo"
    "aXZlL3Jlc3RvcmUsIENTVi9UU1YgZXhwb3J0LgojIFNlbGZUYWI6IGlubmVyIHNhbmN0dW0gZm9yIGlk"
    "bGUgbmFycmF0aXZlIGFuZCByZWZsZWN0aW9uIG91dHB1dC4KIyBEaWFnbm9zdGljc1RhYjogc3RydWN0"
    "dXJlZCBsb2cgd2l0aCBsZXZlbC1jb2xvcmVkIG91dHB1dC4KIyBMZXNzb25zVGFiOiBMU0wgRm9yYmlk"
    "ZGVuIFJ1bGVzZXQgYnJvd3NlciB3aXRoIGFkZC9kZWxldGUvc2VhcmNoLgojCiMgTmV4dDogUGFzcyA2"
    "IOKAlCBNYWluIFdpbmRvdwojIChNb3JnYW5uYURlY2sgY2xhc3MsIGZ1bGwgbGF5b3V0LCBBUFNjaGVk"
    "dWxlciwgZmlyc3QtcnVuIGZsb3csCiMgIGRlcGVuZGVuY3kgYm9vdHN0cmFwLCBzaG9ydGN1dCBjcmVh"
    "dGlvbiwgc3RhcnR1cCBzZXF1ZW5jZSkKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNjogTUFJTiBX"
    "SU5ET1cgJiBFTlRSWSBQT0lOVAojCiMgQ29udGFpbnM6CiMgICBib290c3RyYXBfY2hlY2soKSAgICAg"
    "4oCUIGRlcGVuZGVuY3kgdmFsaWRhdGlvbiArIGF1dG8taW5zdGFsbCBiZWZvcmUgVUkKIyAgIEZpcnN0"
    "UnVuRGlhbG9nICAgICAgICDigJQgbW9kZWwgcGF0aCArIGNvbm5lY3Rpb24gdHlwZSBzZWxlY3Rpb24K"
    "IyAgIEpvdXJuYWxTaWRlYmFyICAgICAgICDigJQgY29sbGFwc2libGUgbGVmdCBzaWRlYmFyIChzZXNz"
    "aW9uIGJyb3dzZXIgKyBqb3VybmFsKQojICAgVG9ycG9yUGFuZWwgICAgICAgICAgIOKAlCBBV0FLRSAv"
    "IEFVVE8gLyBTVVNQRU5EIHN0YXRlIHRvZ2dsZQojICAgTW9yZ2FubmFEZWNrICAgICAgICAgIOKAlCBt"
    "YWluIHdpbmRvdywgZnVsbCBsYXlvdXQsIGFsbCBzaWduYWwgY29ubmVjdGlvbnMKIyAgIG1haW4oKSAg"
    "ICAgICAgICAgICAgICDigJQgZW50cnkgcG9pbnQgd2l0aCBib290c3RyYXAgc2VxdWVuY2UKIyDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9y"
    "dCBzdWJwcm9jZXNzCgoKIyDilIDilIAgUFJFLUxBVU5DSCBERVBFTkRFTkNZIEJPT1RTVFJBUCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGJvb3RzdHJhcF9jaGVjaygpIC0+IE5vbmU6CiAgICAiIiIKICAgIFJ1bnMgQkVGT1JFIFFB"
    "cHBsaWNhdGlvbiBpcyBjcmVhdGVkLgogICAgQ2hlY2tzIGZvciBQeVNpZGU2IHNlcGFyYXRlbHkgKGNh"
    "bid0IHNob3cgR1VJIHdpdGhvdXQgaXQpLgogICAgQXV0by1pbnN0YWxscyBhbGwgb3RoZXIgbWlzc2lu"
    "ZyBub24tY3JpdGljYWwgZGVwcyB2aWEgcGlwLgogICAgVmFsaWRhdGVzIGluc3RhbGxzIHN1Y2NlZWRl"
    "ZC4KICAgIFdyaXRlcyByZXN1bHRzIHRvIGEgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFi"
    "IHRvIHBpY2sgdXAuCiAgICAiIiIKICAgICMg4pSA4pSAIFN0ZXAgMTogQ2hlY2sgUHlTaWRlNiAoY2Fu"
    "J3QgYXV0by1pbnN0YWxsIHdpdGhvdXQgaXQgYWxyZWFkeSBwcmVzZW50KSDilIAKICAgIHRyeToKICAg"
    "ICAgICBpbXBvcnQgUHlTaWRlNiAgIyBub3FhCiAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAg"
    "IyBObyBHVUkgYXZhaWxhYmxlIOKAlCB1c2UgV2luZG93cyBuYXRpdmUgZGlhbG9nIHZpYSBjdHlwZXMK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydCBjdHlwZXMKICAgICAgICAgICAgY3R5cGVzLndp"
    "bmRsbC51c2VyMzIuTWVzc2FnZUJveFcoCiAgICAgICAgICAgICAgICAwLAogICAgICAgICAgICAgICAg"
    "IlB5U2lkZTYgaXMgcmVxdWlyZWQgYnV0IG5vdCBpbnN0YWxsZWQuXG5cbiIKICAgICAgICAgICAgICAg"
    "ICJPcGVuIGEgdGVybWluYWwgYW5kIHJ1bjpcblxuIgogICAgICAgICAgICAgICAgIiAgICBwaXAgaW5z"
    "dGFsbCBQeVNpZGU2XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhlbiByZXN0YXJ0IHtERUNLX05BTUV9"
    "LiIsCiAgICAgICAgICAgICAgICBmIntERUNLX05BTUV9IOKAlCBNaXNzaW5nIERlcGVuZGVuY3kiLAog"
    "ICAgICAgICAgICAgICAgMHgxMCAgIyBNQl9JQ09ORVJST1IKICAgICAgICAgICAgKQogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHByaW50KCJDUklUSUNBTDogUHlTaWRlNiBub3QgaW5z"
    "dGFsbGVkLiBSdW46IHBpcCBpbnN0YWxsIFB5U2lkZTYiKQogICAgICAgIHN5cy5leGl0KDEpCgogICAg"
    "IyDilIDilIAgU3RlcCAyOiBBdXRvLWluc3RhbGwgb3RoZXIgbWlzc2luZyBkZXBzIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0FVVE9fSU5TVEFMTCA9IFsKICAgICAgICAoImFw"
    "c2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiKSwKICAgICAgICAoImxvZ3VydSIs"
    "ICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAg"
    "ICAgICAgICAgInB5Z2FtZSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJw"
    "eXdpbjMyIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIpLAog"
    "ICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIpLAogICAgICAgICgi"
    "Z29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJnb29nbGVhcGljbGllbnQiKSwKICAgICAgICAoImdv"
    "b2dsZS1hdXRoLW9hdXRobGliIiwgICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiKSwKICAgICAgICAo"
    "Imdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiKSwKICAgIF0KCiAgICBpbXBv"
    "cnQgaW1wb3J0bGliCiAgICBib290c3RyYXBfbG9nID0gW10KCiAgICBmb3IgcGlwX25hbWUsIGltcG9y"
    "dF9uYW1lIGluIF9BVVRPX0lOU1RBTEw6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnRsaWIu"
    "aW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQo"
    "ZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IOKckyIpCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgog"
    "ICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJB"
    "UF0ge3BpcF9uYW1lfSBtaXNzaW5nIOKAlCBpbnN0YWxsaW5nLi4uIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHN1YnByb2Nlc3MucnVuKAogICAgICAg"
    "ICAgICAgICAgICAgIFtzeXMuZXhlY3V0YWJsZSwgIi1tIiwgInBpcCIsICJpbnN0YWxsIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgcGlwX25hbWUsICItLXF1aWV0IiwgIi0tbm8td2Fybi1zY3JpcHQtbG9jYXRp"
    "b24iXSwKICAgICAgICAgICAgICAgICAgICBjYXB0dXJlX291dHB1dD1UcnVlLCB0ZXh0PVRydWUsIHRp"
    "bWVvdXQ9MTIwCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiByZXN1bHQucmV0dXJu"
    "Y29kZSA9PSAwOgogICAgICAgICAgICAgICAgICAgICMgVmFsaWRhdGUgaXQgYWN0dWFsbHkgaW1wb3J0"
    "ZWQgbm93CiAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBpbXBv"
    "cnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgICAgICAgICAgYm9v"
    "dHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbGVkIOKckyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgYm9v"
    "dHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBd"
    "IHtwaXBfbmFtZX0gaW5zdGFsbCBhcHBlYXJlZCB0byAiCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmInN1Y2NlZWQgYnV0IGltcG9ydCBzdGlsbCBmYWlscyDigJQgcmVzdGFydCBtYXkgIgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJiZSByZXF1aXJlZC4iCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5h"
    "cHBlbmQoCiAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0"
    "YWxsIGZhaWxlZDogIgogICAgICAgICAgICAgICAgICAgICAgICBmIntyZXN1bHQuc3RkZXJyWzoyMDBd"
    "fSIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBzdWJwcm9jZXNzLlRpbWVv"
    "dXRFeHBpcmVkOgogICAgICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgdGltZWQgb3V0LiIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7"
    "cGlwX25hbWV9IGluc3RhbGwgZXJyb3I6IHtlfSIKICAgICAgICAgICAgICAgICkKCiAgICAjIOKUgOKU"
    "gCBTdGVwIDM6IFdyaXRlIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgIHRyeToKICAgICAgICBsb2dfcGF0aCA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFw"
    "X2xvZy50eHQiCiAgICAgICAgd2l0aCBsb2dfcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04Iikg"
    "YXMgZjoKICAgICAgICAgICAgZi53cml0ZSgiXG4iLmpvaW4oYm9vdHN0cmFwX2xvZykpCiAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCgojIOKUgOKUgCBGSVJTVCBSVU4gRElBTE9HIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGaXJz"
    "dFJ1bkRpYWxvZyhRRGlhbG9nKToKICAgICIiIgogICAgU2hvd24gb24gZmlyc3QgbGF1bmNoIHdoZW4g"
    "Y29uZmlnLmpzb24gZG9lc24ndCBleGlzdC4KICAgIENvbGxlY3RzIG1vZGVsIGNvbm5lY3Rpb24gdHlw"
    "ZSBhbmQgcGF0aC9rZXkuCiAgICBWYWxpZGF0ZXMgY29ubmVjdGlvbiBiZWZvcmUgYWNjZXB0aW5nLgog"
    "ICAgV3JpdGVzIGNvbmZpZy5qc29uIG9uIHN1Y2Nlc3MuCiAgICBDcmVhdGVzIGRlc2t0b3Agc2hvcnRj"
    "dXQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoZiLinKYge0RF"
    "Q0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIikKICAgICAgICBzZWxmLnNldFN0eWxl"
    "U2hlZXQoU1RZTEUpCiAgICAgICAgc2VsZi5zZXRGaXhlZFNpemUoNTIwLCA0MDApCiAgICAgICAgc2Vs"
    "Zi5fc2V0dXBfdWkoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldFNwYWNpbmcoMTApCgogICAgICAgIHRp"
    "dGxlID0gUUxhYmVsKGYi4pymIHtERUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyDi"
    "nKYiKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NS"
    "SU1TT059OyBmb250LXNpemU6IDE0cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDJweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHRpdGxlLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVy"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHRpdGxlKQoKICAgICAgICBzdWIgPSBRTGFiZWwoCiAgICAg"
    "ICAgICAgIGYiQ29uZmlndXJlIHRoZSB2ZXNzZWwgYmVmb3JlIHtERUNLX05BTUV9IG1heSBhd2FrZW4u"
    "XG4iCiAgICAgICAgICAgICJBbGwgc2V0dGluZ3MgYXJlIHN0b3JlZCBsb2NhbGx5LiBOb3RoaW5nIGxl"
    "YXZlcyB0aGlzIG1hY2hpbmUuIgogICAgICAgICkKICAgICAgICBzdWIuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc3Vi"
    "LnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHN1YikKCiAgICAgICAgIyDilIDilIAgQ29ubmVjdGlvbiB0eXBlIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEFJIENPTk5FQ1RJT04gVFlQRSIp"
    "KQogICAgICAgIHNlbGYuX3R5cGVfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX3R5cGVf"
    "Y29tYm8uYWRkSXRlbXMoWwogICAgICAgICAgICAiTG9jYWwgbW9kZWwgZm9sZGVyICh0cmFuc2Zvcm1l"
    "cnMpIiwKICAgICAgICAgICAgIk9sbGFtYSAobG9jYWwgc2VydmljZSkiLAogICAgICAgICAgICAiQ2xh"
    "dWRlIEFQSSAoQW50aHJvcGljKSIsCiAgICAgICAgICAgICJPcGVuQUkgQVBJIiwKICAgICAgICBdKQog"
    "ICAgICAgIHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0KHNlbGYuX29u"
    "X3R5cGVfY2hhbmdlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3R5cGVfY29tYm8pCgogICAg"
    "ICAgICMg4pSA4pSAIER5bmFtaWMgY29ubmVjdGlvbiBmaWVsZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgp"
    "CgogICAgICAgICMgUGFnZSAwOiBMb2NhbCBwYXRoCiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBsMCA9IFFIQm94TGF5b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCww"
    "KQogICAgICAgIHNlbGYuX2xvY2FsX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2xvY2Fs"
    "X3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICByIkQ6XEFJXE1vZGVsc1xkb2xwaGlu"
    "LThiIgogICAgICAgICkKICAgICAgICBidG5fYnJvd3NlID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAg"
    "ICAgICAgYnRuX2Jyb3dzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX21vZGVsKQogICAgICAg"
    "IGwwLmFkZFdpZGdldChzZWxmLl9sb2NhbF9wYXRoKTsgbDAuYWRkV2lkZ2V0KGJ0bl9icm93c2UpCiAg"
    "ICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIFBhZ2UgMTogT2xsYW1hIG1v"
    "ZGVsIG5hbWUKICAgICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUUhCb3hMYXlvdXQocDEp"
    "CiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2xsYW1h"
    "X21vZGVsID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwuc2V0UGxhY2Vob2xk"
    "ZXJUZXh0KCJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX29sbGFtYV9t"
    "b2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgogICAgICAgICMgUGFnZSAyOiBD"
    "bGF1ZGUgQVBJIGtleQogICAgICAgIHAyID0gUVdpZGdldCgpCiAgICAgICAgbDIgPSBRVkJveExheW91"
    "dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9j"
    "bGF1ZGVfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KCJzay1hbnQtLi4uIikKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldEVjaG9Nb2Rl"
    "KFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9jbGF1ZGVfbW9kZWwgPSBR"
    "TGluZUVkaXQoImNsYXVkZS1zb25uZXQtNC02IikKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJB"
    "UEkgS2V5OiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9jbGF1ZGVfa2V5KQogICAgICAgIGwy"
    "LmFkZFdpZGdldChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9jbGF1"
    "ZGVfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIFBhZ2Ug"
    "MzogT3BlbkFJCiAgICAgICAgcDMgPSBRV2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAz"
    "KQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29haV9r"
    "ZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRQbGFjZWhvbGRlclRleHQo"
    "InNrLS4uLiIpCiAgICAgICAgc2VsZi5fb2FpX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01v"
    "ZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fb2FpX21vZGVsID0gUUxpbmVFZGl0KCJncHQtNG8iKQog"
    "ICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDMuYWRkV2lkZ2V0"
    "KHNlbGYuX29haV9rZXkpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAg"
    "ICAgbDMuYWRkV2lkZ2V0KHNlbGYuX29haV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRn"
    "ZXQocDMpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrKQoKICAgICAgICAjIOKUgOKU"
    "gCBUZXN0ICsgc3RhdHVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHRlc3Rfcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl90ZXN0ID0gX2dvdGhpY19idG4oIlRlc3QgQ29ubmVjdGlv"
    "biIpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Rlc3RfY29ubmVj"
    "dGlvbikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX3N0"
    "YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBm"
    "b250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl90ZXN0KQog"
    "ICAgICAgIHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9zdGF0dXNfbGJsLCAxKQogICAgICAgIHJvb3Qu"
    "YWRkTGF5b3V0KHRlc3Rfcm93KQoKICAgICAgICAjIOKUgOKUgCBGYWNlIFBhY2sg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "RkFDRSBQQUNLIChvcHRpb25hbCDigJQgWklQIGZpbGUpIikpCiAgICAgICAgZmFjZV9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxm"
    "Ll9mYWNlX3BhdGguc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICBmIkJyb3dzZSB0byB7REVD"
    "S19OQU1FfSBmYWNlIHBhY2sgWklQIChvcHRpb25hbCwgY2FuIGFkZCBsYXRlcikiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDZweCAx"
    "MHB4OyIKICAgICAgICApCiAgICAgICAgYnRuX2ZhY2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAg"
    "ICAgICBidG5fZmFjZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fYnJvd3NlX2ZhY2UpCiAgICAgICAgZmFj"
    "ZV9yb3cuYWRkV2lkZ2V0KHNlbGYuX2ZhY2VfcGF0aCkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQo"
    "YnRuX2ZhY2UpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmFjZV9yb3cpCgogICAgICAgICMg4pSA4pSA"
    "IFNob3J0Y3V0IG9wdGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYiA9IFFD"
    "aGVja0JveCgKICAgICAgICAgICAgIkNyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IChyZWNvbW1lbmRlZCki"
    "CiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiLnNldENoZWNrZWQoVHJ1ZSkKICAgICAg"
    "ICByb290LmFkZFdpZGdldChzZWxmLl9zaG9ydGN1dF9jYikKCiAgICAgICAgIyDilIDilIAgQnV0dG9u"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFN0cmV0"
    "Y2goKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtl"
    "biA9IF9nb3RoaWNfYnRuKCLinKYgQkVHSU4gQVdBS0VOSU5HIikKICAgICAgICBzZWxmLl9idG5fYXdh"
    "a2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCLinJcg"
    "Q2FuY2VsIikKICAgICAgICBzZWxmLl9idG5fYXdha2VuLmNsaWNrZWQuY29ubmVjdChzZWxmLmFjY2Vw"
    "dCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlamVjdCkKICAgICAgICBi"
    "dG5fcm93LmFkZFdpZGdldChzZWxmLl9idG5fYXdha2VuKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0"
    "KGJ0bl9jYW5jZWwpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICBkZWYgX29uX3R5"
    "cGVfY2hhbmdlKHNlbGYsIGlkeDogaW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKEZhbHNlKQog"
    "ICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiIikKCiAgICBkZWYgX2Jyb3dzZV9tb2RlbChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGggPSBRRmlsZURpYWxvZy5nZXRFeGlzdGluZ0RpcmVjdG9y"
    "eSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBNb2RlbCBGb2xkZXIiLAogICAgICAgICAgICByIkQ6"
    "XEFJXE1vZGVscyIKICAgICAgICApCiAgICAgICAgaWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fbG9j"
    "YWxfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAgZGVmIF9icm93c2VfZmFjZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHBhdGgsIF8gPSBRRmlsZURpYWxvZy5nZXRPcGVuRmlsZU5hbWUoCiAgICAgICAgICAgIHNl"
    "bGYsICJTZWxlY3QgRmFjZSBQYWNrIFpJUCIsCiAgICAgICAgICAgIHN0cihQYXRoLmhvbWUoKSAvICJE"
    "ZXNrdG9wIiksCiAgICAgICAgICAgICJaSVAgRmlsZXMgKCouemlwKSIKICAgICAgICApCiAgICAgICAg"
    "aWYgcGF0aDoKICAgICAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFRleHQocGF0aCkKCiAgICBAcHJv"
    "cGVydHkKICAgIGRlZiBmYWNlX3ppcF9wYXRoKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fZmFjZV9wYXRoLnRleHQoKS5zdHJpcCgpCgogICAgZGVmIF90ZXN0X2Nvbm5lY3Rpb24oc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQoIlRlc3RpbmcuLi4iKQogICAg"
    "ICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "VEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IgogICAgICAgICkKICAgICAgICBRQXBwbGljYXRpb24ucHJvY2Vzc0V2ZW50cygpCgogICAgICAgIGlk"
    "eCA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICBvayAgPSBGYWxzZQogICAg"
    "ICAgIG1zZyA9ICIiCgogICAgICAgIGlmIGlkeCA9PSAwOiAgIyBMb2NhbAogICAgICAgICAgICBwYXRo"
    "ID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBpZiBwYXRoIGFuZCBQ"
    "YXRoKHBhdGgpLmV4aXN0cygpOgogICAgICAgICAgICAgICAgb2sgID0gVHJ1ZQogICAgICAgICAgICAg"
    "ICAgbXNnID0gZiJGb2xkZXIgZm91bmQuIE1vZGVsIHdpbGwgbG9hZCBvbiBzdGFydHVwLiIKICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgIG1zZyA9ICJGb2xkZXIgbm90IGZvdW5kLiBDaGVjayB0"
    "aGUgcGF0aC4iCgogICAgICAgIGVsaWYgaWR4ID09IDE6ICAjIE9sbGFtYQogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAgICAgICAgICAg"
    "ICAgICAgICAiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0z"
    "KQogICAgICAgICAgICAgICAgb2sgICA9IHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgICAgICAgICAg"
    "bXNnICA9ICJPbGxhbWEgaXMgcnVubmluZyDinJMiIGlmIG9rIGVsc2UgIk9sbGFtYSBub3QgcmVzcG9u"
    "ZGluZy4iCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIG1z"
    "ZyA9IGYiT2xsYW1hIG5vdCByZWFjaGFibGU6IHtlfSIKCiAgICAgICAgZWxpZiBpZHggPT0gMjogICMg"
    "Q2xhdWRlCiAgICAgICAgICAgIGtleSA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgb2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay1hbnQiKSkKICAgICAg"
    "ICAgICAgbXNnID0gIkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRl"
    "ciBhIHZhbGlkIENsYXVkZSBBUEkga2V5LiIKCiAgICAgICAgZWxpZiBpZHggPT0gMzogICMgT3BlbkFJ"
    "CiAgICAgICAgICAgIGtleSA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAg"
    "b2sgID0gYm9vbChrZXkgYW5kIGtleS5zdGFydHN3aXRoKCJzay0iKSkKICAgICAgICAgICAgbXNnID0g"
    "IkFQSSBrZXkgZm9ybWF0IGxvb2tzIGNvcnJlY3QuIiBpZiBvayBlbHNlICJFbnRlciBhIHZhbGlkIE9w"
    "ZW5BSSBBUEkga2V5LiIKCiAgICAgICAgY29sb3IgPSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19DUklNU09O"
    "CiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KG1zZykKICAgICAgICBzZWxmLl9zdGF0dXNf"
    "bGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTog"
    "MTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChvaykKCiAgICBkZWYgYnVpbGRfY29uZmlnKHNlbGYpIC0+"
    "IGRpY3Q6CiAgICAgICAgIiIiQnVpbGQgYW5kIHJldHVybiB1cGRhdGVkIGNvbmZpZyBkaWN0IGZyb20g"
    "ZGlhbG9nIHNlbGVjdGlvbnMuIiIiCiAgICAgICAgY2ZnICAgICA9IF9kZWZhdWx0X2NvbmZpZygpCiAg"
    "ICAgICAgaWR4ICAgICA9IHNlbGYuX3R5cGVfY29tYm8uY3VycmVudEluZGV4KCkKICAgICAgICB0eXBl"
    "cyAgID0gWyJsb2NhbCIsICJvbGxhbWEiLCAiY2xhdWRlIiwgIm9wZW5haSJdCiAgICAgICAgY2ZnWyJt"
    "b2RlbCJdWyJ0eXBlIl0gPSB0eXBlc1tpZHhdCgogICAgICAgIGlmIGlkeCA9PSAwOgogICAgICAgICAg"
    "ICBjZmdbIm1vZGVsIl1bInBhdGgiXSA9IHNlbGYuX2xvY2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAxOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bIm9sbGFtYV9tb2RlbCJd"
    "ID0gc2VsZi5fb2xsYW1hX21vZGVsLnRleHQoKS5zdHJpcCgpIG9yICJkb2xwaGluLTIuNi03YiIKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAyOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0g"
    "c2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFw"
    "aV9tb2RlbCJdID0gc2VsZi5fY2xhdWRlX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNm"
    "Z1sibW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAiY2xhdWRlIgogICAgICAgIGVsaWYgaWR4ID09IDM6CiAg"
    "ICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9vYWlfa2V5LnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9vYWlfbW9k"
    "ZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJv"
    "cGVuYWkiCgogICAgICAgIGNmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQogICAgICAgIHJldHVybiBjZmcK"
    "CiAgICBAcHJvcGVydHkKICAgIGRlZiBjcmVhdGVfc2hvcnRjdXQoc2VsZikgLT4gYm9vbDoKICAgICAg"
    "ICByZXR1cm4gc2VsZi5fc2hvcnRjdXRfY2IuaXNDaGVja2VkKCkKCgojIOKUgOKUgCBKT1VSTkFMIFNJ"
    "REVCQVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIEpvdXJuYWxTaWRlYmFyKFFXaWRnZXQpOgogICAgIiIiCiAgICBDb2xsYXBzaWJsZSBs"
    "ZWZ0IHNpZGViYXIgbmV4dCB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KICAgIFRvcDogc2Vzc2lvbiBj"
    "b250cm9scyAoY3VycmVudCBzZXNzaW9uIG5hbWUsIHNhdmUvbG9hZCBidXR0b25zLAogICAgICAgICBh"
    "dXRvc2F2ZSBpbmRpY2F0b3IpLgogICAgQm9keTogc2Nyb2xsYWJsZSBzZXNzaW9uIGxpc3Qg4oCUIGRh"
    "dGUsIEFJIG5hbWUsIG1lc3NhZ2UgY291bnQuCiAgICBDb2xsYXBzZXMgbGVmdHdhcmQgdG8gYSB0aGlu"
    "IHN0cmlwLgoKICAgIFNpZ25hbHM6CiAgICAgICAgc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZChzdHIpICAg"
    "4oCUIGRhdGUgc3RyaW5nIG9mIHNlc3Npb24gdG8gbG9hZAogICAgICAgIHNlc3Npb25fY2xlYXJfcmVx"
    "dWVzdGVkKCkgICAgIOKAlCByZXR1cm4gdG8gY3VycmVudCBzZXNzaW9uCiAgICAiIiIKCiAgICBzZXNz"
    "aW9uX2xvYWRfcmVxdWVzdGVkICA9IFNpZ25hbChzdHIpCiAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3Rl"
    "ZCA9IFNpZ25hbCgpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNlc3Npb25fbWdyOiAiU2Vzc2lvbk1h"
    "bmFnZXIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9tZ3IgPSBzZXNzaW9uX21ncgogICAgICAgIHNlbGYuX2V4cGFuZGVkICAg"
    "ID0gVHJ1ZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAg"
    "IGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFVzZSBhIGhvcml6b250YWwgcm9v"
    "dCBsYXlvdXQg4oCUIGNvbnRlbnQgb24gbGVmdCwgdG9nZ2xlIHN0cmlwIG9uIHJpZ2h0CiAgICAgICAg"
    "cm9vdCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMCwg"
    "MCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyDilIDilIAgQ29sbGFw"
    "c2UgdG9nZ2xlIHN0cmlwIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcCA9IFFXaWRnZXQoKQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9zdHJpcC5zZXRGaXhlZFdpZHRoKDIwKQogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJp"
    "cC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1y"
    "aWdodDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHRzX2xheW91"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKICAgICAgICB0c19sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDgsIDAsIDgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0"
    "dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldEZpeGVkU2l6ZSgxOCwgMTgpCiAgICAgICAg"
    "c2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtD"
    "X0dPTERfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9n"
    "Z2xlKQogICAgICAgIHRzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX2J0bikKICAgICAgICB0"
    "c19sYXlvdXQuYWRkU3RyZXRjaCgpCgogICAgICAgICMg4pSA4pSAIE1haW4gY29udGVudCDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9jb250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fY29udGVudC5zZXRNaW5pbXVtV2lkdGgoMTgwKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWF4"
    "aW11bVdpZHRoKDIyMCkKICAgICAgICBjb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2Nv"
    "bnRlbnQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIFNlY3Rpb24gbGFi"
    "ZWwKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgSk9VUk5B"
    "TCIpKQoKICAgICAgICAjIEN1cnJlbnQgc2Vzc2lvbiBpbmZvCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9u"
    "YW1lID0gUUxhYmVsKCJOZXcgU2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEwcHg7IGZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBp"
    "dGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0V29yZFdyYXAoVHJ1"
    "ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vzc2lvbl9uYW1lKQoKICAg"
    "ICAgICAjIFNhdmUgLyBMb2FkIHJvdwogICAgICAgIGN0cmxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuX2J0bl9zYXZlID0gX2dvdGhpY19idG4oIvCfkr4iKQogICAgICAgIHNlbGYuX2J0bl9z"
    "YXZlLnNldEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VG9vbFRpcCgi"
    "U2F2ZSBzZXNzaW9uIG5vdyIpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQgPSBfZ290aGljX2J0bigi8J+T"
    "giIpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxm"
    "Ll9idG5fbG9hZC5zZXRUb29sVGlwKCJCcm93c2UgYW5kIGxvYWQgYSBwYXN0IHNlc3Npb24iKQogICAg"
    "ICAgIHNlbGYuX2F1dG9zYXZlX2RvdCA9IFFMYWJlbCgi4pePIikKICAgICAgICBzZWxmLl9hdXRvc2F2"
    "ZV9kb3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVf"
    "ZG90LnNldFRvb2xUaXAoIkF1dG9zYXZlIHN0YXR1cyIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX3NhdmUpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9z"
    "YXZlKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fbG9hZCkKICAgICAgICBjdHJs"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYXV0b3NhdmVfZG90KQogICAgICAgIGN0cmxfcm93LmFkZFN0cmV0"
    "Y2goKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZExheW91dChjdHJsX3JvdykKCiAgICAgICAgIyBK"
    "b3VybmFsIGxvYWRlZCBpbmRpY2F0b3IKICAgICAgICBzZWxmLl9qb3VybmFsX2xibCA9IFFMYWJlbCgi"
    "IikKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNv"
    "bG9yOiB7Q19QVVJQTEV9OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2pvdXJuYWxfbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfbGJsKQoKICAgICAgICAjIENsZWFyIGpvdXJuYWwgYnV0dG9u"
    "IChoaWRkZW4gd2hlbiBub3QgbG9hZGVkKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsID0g"
    "X2dvdGhpY19idG4oIuKclyBSZXR1cm4gdG8gUHJlc2VudCIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "X2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fY2xlYXJfam91cm5hbCkKICAgICAgICBjb250ZW50X2xheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwpCgogICAgICAgICMgRGl2aWRlcgogICAg"
    "ICAgIGRpdiA9IFFGcmFtZSgpCiAgICAgICAgZGl2LnNldEZyYW1lU2hhcGUoUUZyYW1lLlNoYXBlLkhM"
    "aW5lKQogICAgICAgIGRpdi5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsiKQog"
    "ICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChkaXYpCgogICAgICAgICMgU2Vzc2lvbiBsaXN0"
    "CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBU1QgU0VT"
    "U0lPTlMiKSkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbl9saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgICAgIGYiUUxpc3RXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQg"
    "e3sgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyB9fSIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGlj"
    "aykKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9z"
    "ZXNzaW9uX2NsaWNrKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9u"
    "X2xpc3QsIDEpCgogICAgICAgICMgQWRkIGNvbnRlbnQgYW5kIHRvZ2dsZSBzdHJpcCB0byB0aGUgcm9v"
    "dCBob3Jpem9udGFsIGxheW91dAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQoKICAgIGRlZiBfdG9nZ2xlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAg"
    "ICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX2J0bi5zZXRUZXh0KCLil4AiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIuKWtiIpCiAgICAg"
    "ICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAg"
    "ICAgICBpZiBwIGFuZCBwLmxheW91dCgpOgogICAgICAgICAgICBwLmxheW91dCgpLmFjdGl2YXRlKCkK"
    "CiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlc3Npb25zID0gc2VsZi5fc2Vz"
    "c2lvbl9tZ3IubGlzdF9zZXNzaW9ucygpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmNsZWFyKCkK"
    "ICAgICAgICBmb3IgcyBpbiBzZXNzaW9uczoKICAgICAgICAgICAgZGF0ZV9zdHIgPSBzLmdldCgiZGF0"
    "ZSIsIiIpCiAgICAgICAgICAgIG5hbWUgICAgID0gcy5nZXQoIm5hbWUiLCBkYXRlX3N0cilbOjMwXQog"
    "ICAgICAgICAgICBjb3VudCAgICA9IHMuZ2V0KCJtZXNzYWdlX2NvdW50IiwgMCkKICAgICAgICAgICAg"
    "aXRlbSA9IFFMaXN0V2lkZ2V0SXRlbShmIntkYXRlX3N0cn1cbntuYW1lfSAoe2NvdW50fSBtc2dzKSIp"
    "CiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGRhdGVfc3Ry"
    "KQogICAgICAgICAgICBpdGVtLnNldFRvb2xUaXAoZiJEb3VibGUtY2xpY2sgdG8gbG9hZCBzZXNzaW9u"
    "IGZyb20ge2RhdGVfc3RyfSIpCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5hZGRJdGVtKGl0"
    "ZW0pCgogICAgZGVmIHNldF9zZXNzaW9uX25hbWUoc2VsZiwgbmFtZTogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRUZXh0KG5hbWVbOjUwXSBvciAiTmV3IFNlc3Npb24iKQoK"
    "ICAgIGRlZiBzZXRfYXV0b3NhdmVfaW5kaWNhdG9yKHNlbGYsIHNhdmVkOiBib29sKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19HUkVFTiBpZiBzYXZlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2Rv"
    "dC5zZXRUb29sVGlwKAogICAgICAgICAgICAiQXV0b3NhdmVkIiBpZiBzYXZlZCBlbHNlICJQZW5kaW5n"
    "IGF1dG9zYXZlIgogICAgICAgICkKCiAgICBkZWYgc2V0X2pvdXJuYWxfbG9hZGVkKHNlbGYsIGRhdGVf"
    "c3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dChmIvCfk5Yg"
    "Sm91cm5hbDoge2RhdGVfc3RyfSIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0Vmlz"
    "aWJsZShUcnVlKQoKICAgIGRlZiBjbGVhcl9qb3VybmFsX2luZGljYXRvcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "X2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKCiAgICBkZWYgX2RvX3NhdmUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9uX21nci5zYXZlKCkKICAgICAgICBzZWxmLnNldF9hdXRvc2F2ZV9p"
    "bmRpY2F0b3IoVHJ1ZSkKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAgIHNlbGYuX2J0bl9zYXZl"
    "LnNldFRleHQoIuKckyIpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMCwgbGFtYmRhOiBzZWxm"
    "Ll9idG5fc2F2ZS5zZXRUZXh0KCLwn5K+IikpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwMCwg"
    "bGFtYmRhOiBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpKQoKICAgIGRlZiBfZG9fbG9h"
    "ZChzZWxmKSAtPiBOb25lOgogICAgICAgICMgVHJ5IHNlbGVjdGVkIGl0ZW0gZmlyc3QKICAgICAgICBp"
    "dGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBpZiBub3QgaXRlbToK"
    "ICAgICAgICAgICAgIyBJZiBub3RoaW5nIHNlbGVjdGVkLCB0cnkgdGhlIGZpcnN0IGl0ZW0KICAgICAg"
    "ICAgICAgaWYgc2VsZi5fc2Vzc2lvbl9saXN0LmNvdW50KCkgPiAwOgogICAgICAgICAgICAgICAgaXRl"
    "bSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtKDApCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9u"
    "X2xpc3Quc2V0Q3VycmVudEl0ZW0oaXRlbSkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBkYXRl"
    "X3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIHNlbGYu"
    "c2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfb25fc2Vzc2lvbl9j"
    "bGljayhzZWxmLCBpdGVtKSAtPiBOb25lOgogICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1p"
    "dChkYXRlX3N0cikKCiAgICBkZWYgX2RvX2NsZWFyX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmVtaXQoKQogICAgICAgIHNlbGYuY2xlYXJfam91"
    "cm5hbF9pbmRpY2F0b3IoKQoKCiMg4pSA4pSAIFRPUlBPUiBQQU5FTCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgVG9ycG9y"
    "UGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRocmVlLXN0YXRlIHN1c3BlbnNpb24gdG9nZ2xlOiBB"
    "V0FLRSB8IEFVVE8gfCBTVVNQRU5ECgogICAgQVdBS0UgIOKAlCBtb2RlbCBsb2FkZWQsIGF1dG8tdG9y"
    "cG9yIGRpc2FibGVkLCBpZ25vcmVzIFZSQU0gcHJlc3N1cmUKICAgIEFVVE8gICDigJQgbW9kZWwgbG9h"
    "ZGVkLCBtb25pdG9ycyBWUkFNIHByZXNzdXJlLCBhdXRvLXRvcnBvciBpZiBzdXN0YWluZWQKICAgIFNV"
    "U1BFTkQg4oCUIG1vZGVsIHVubG9hZGVkLCBzdGF5cyBzdXNwZW5kZWQgdW50aWwgbWFudWFsbHkgY2hh"
    "bmdlZAoKICAgIFNpZ25hbHM6CiAgICAgICAgc3RhdGVfY2hhbmdlZChzdHIpICDigJQgIkFXQUtFIiB8"
    "ICJBVVRPIiB8ICJTVVNQRU5EIgogICAgIiIiCgogICAgc3RhdGVfY2hhbmdlZCA9IFNpZ25hbChzdHIp"
    "CgogICAgU1RBVEVTID0gWyJBV0FLRSIsICJBVVRPIiwgIlNVU1BFTkQiXQoKICAgIFNUQVRFX1NUWUxF"
    "UyA9IHsKICAgICAgICAiQVdBS0UiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3Vu"
    "ZDogIzJhMWEwNTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiAxcHggc29saWQge0NfR09MRH07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4"
    "IDhweDsiLAogICAgICAgICAgICAiaW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9y"
    "OiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAg"
    "ICAgICAgICAgImxhYmVsIjogICAgIuKYgCBBV0FLRSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJN"
    "b2RlbCBhY3RpdmUuIEF1dG8tdG9ycG9yIGRpc2FibGVkLiIsCiAgICAgICAgfSwKICAgICAgICAiQVVU"
    "TyI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMWExMDA1OyBjb2xvcjog"
    "I2NjODgyMjsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkICNjYzg4"
    "MjI7IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6"
    "ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAi"
    "aW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXIt"
    "cmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjogICAg"
    "IuKXiSBBVVRPIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by1zdXNw"
    "ZW5kIG9uIFZSQU0gcHJlc3N1cmUuIiwKICAgICAgICB9LAogICAgICAgICJTVVNQRU5EIjogewogICAg"
    "ICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6IHtDX1BVUlBMRV9ESU19OyBjb2xvcjoge0Nf"
    "UFVSUExFfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BV"
    "UlBMRX07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAg"
    "ICAiaW5hY3RpdmUiOiBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3Jk"
    "ZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsg"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImxhYmVsIjog"
    "ICAgZiLimrAge1VJX1NVU1BFTlNJT05fTEFCRUwuc3RyaXAoKSBpZiBzdHIoVUlfU1VTUEVOU0lPTl9M"
    "QUJFTCkuc3RyaXAoKSBlbHNlICdTdXNwZW5kJ30iLAogICAgICAgICAgICAidG9vbHRpcCI6ICBmIk1v"
    "ZGVsIHVubG9hZGVkLiB7REVDS19OQU1FfSBzbGVlcHMgdW50aWwgbWFudWFsbHkgYXdha2VuZWQuIiwK"
    "ICAgICAgICB9LAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fY3VycmVudCA9ICJBV0FLRSIK"
    "ICAgICAgICBzZWxmLl9idXR0b25zOiBkaWN0W3N0ciwgUVB1c2hCdXR0b25dID0ge30KICAgICAgICBs"
    "YXlvdXQgPSBRSEJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBmb3Igc3RhdGUg"
    "aW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIGJ0biA9IFFQdXNoQnV0dG9uKHNlbGYuU1RBVEVfU1RZ"
    "TEVTW3N0YXRlXVsibGFiZWwiXSkKICAgICAgICAgICAgYnRuLnNldFRvb2xUaXAoc2VsZi5TVEFURV9T"
    "VFlMRVNbc3RhdGVdWyJ0b29sdGlwIl0pCiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZEhlaWdodCgyMikK"
    "ICAgICAgICAgICAgYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgY2hlY2tlZCwgcz1zdGF0ZTogc2Vs"
    "Zi5fc2V0X3N0YXRlKHMpKQogICAgICAgICAgICBzZWxmLl9idXR0b25zW3N0YXRlXSA9IGJ0bgogICAg"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJ0bikKCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkK"
    "CiAgICBkZWYgX3NldF9zdGF0ZShzZWxmLCBzdGF0ZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHN0"
    "YXRlID09IHNlbGYuX2N1cnJlbnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2N1cnJl"
    "bnQgPSBzdGF0ZQogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCiAgICAgICAgc2VsZi5zdGF0ZV9j"
    "aGFuZ2VkLmVtaXQoc3RhdGUpCgogICAgZGVmIF9hcHBseV9zdHlsZXMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBmb3Igc3RhdGUsIGJ0biBpbiBzZWxmLl9idXR0b25zLml0ZW1zKCk6CiAgICAgICAgICAgIHN0"
    "eWxlX2tleSA9ICJhY3RpdmUiIGlmIHN0YXRlID09IHNlbGYuX2N1cnJlbnQgZWxzZSAiaW5hY3RpdmUi"
    "CiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVtzdHls"
    "ZV9rZXldKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfc3RhdGUoc2VsZikgLT4gc3RyOgog"
    "ICAgICAgIHJldHVybiBzZWxmLl9jdXJyZW50CgogICAgZGVmIHNldF9zdGF0ZShzZWxmLCBzdGF0ZTog"
    "c3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBzdGF0ZSBwcm9ncmFtbWF0aWNhbGx5IChlLmcuIGZy"
    "b20gYXV0by10b3Jwb3IgZGV0ZWN0aW9uKS4iIiIKICAgICAgICBpZiBzdGF0ZSBpbiBzZWxmLlNUQVRF"
    "UzoKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXRlKHN0YXRlKQoKCiMg4pSA4pSAIE1BSU4gV0lORE9X"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBFY2hvRGVjayhRTWFpbldpbmRvdyk6CiAgICAiIiIKICAgIFRoZSBtYWlu"
    "IEVjaG8gRGVjayB3aW5kb3cuCiAgICBBc3NlbWJsZXMgYWxsIHdpZGdldHMsIGNvbm5lY3RzIGFsbCBz"
    "aWduYWxzLCBtYW5hZ2VzIGFsbCBzdGF0ZS4KICAgICIiIgoKICAgICMg4pSA4pSAIFRvcnBvciB0aHJl"
    "c2hvbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCICAgID0g"
    "MS41ICAgIyBleHRlcm5hbCBWUkFNID4gdGhpcyDihpIgY29uc2lkZXIgdG9ycG9yCiAgICBfRVhURVJO"
    "QUxfVlJBTV9XQUtFX0dCICAgICAgPSAwLjggICAjIGV4dGVybmFsIFZSQU0gPCB0aGlzIOKGkiBjb25z"
    "aWRlciB3YWtlCiAgICBfVE9SUE9SX1NVU1RBSU5FRF9USUNLUyAgICAgPSA2ICAgICAjIDYgw5cgNXMg"
    "PSAzMCBzZWNvbmRzIHN1c3RhaW5lZAogICAgX1dBS0VfU1VTVEFJTkVEX1RJQ0tTICAgICAgID0gMTIg"
    "ICAgIyA2MCBzZWNvbmRzIHN1c3RhaW5lZCBsb3cgcHJlc3N1cmUKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "Zik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCgogICAgICAgICMg4pSA4pSAIENvcmUgc3RhdGUg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHVzICAgICAgICAgICAg"
    "ICA9ICJPRkZMSU5FIgogICAgICAgIHNlbGYuX3Nlc3Npb25fc3RhcnQgICAgICAgPSB0aW1lLnRpbWUo"
    "KQogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICAgICAgICAgPSAwCiAgICAgICAgc2VsZi5fZmFjZV9s"
    "b2NrZWQgICAgICAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgICAgICAgICA9IFRy"
    "dWUKICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9uX2lkICAgICAgICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVkl"
    "bSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkczogbGlzdCA9IFtdICAjIGtl"
    "ZXAgcmVmcyB0byBwcmV2ZW50IEdDIHdoaWxlIHJ1bm5pbmcKICAgICAgICBzZWxmLl9maXJzdF90b2tl"
    "bjogYm9vbCA9IFRydWUgICAjIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHN0cmVhbWlu"
    "ZyB0b2tlbgoKICAgICAgICAjIFRvcnBvciAvIFZSQU0gdHJhY2tpbmcKICAgICAgICBzZWxmLl90b3Jw"
    "b3Jfc3RhdGUgICAgICAgID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlICA9IDAu"
    "MCAgICMgYmFzZWxpbmUgVlJBTSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA9IDAgICAgICMgc3VzdGFpbmVkIHByZXNzdXJlIGNvdW50ZXIKICAgICAgICBzZWxm"
    "Ll92cmFtX3JlbGllZl90aWNrcyAgID0gMCAgICAgIyBzdXN0YWluZWQgcmVsaWVmIGNvdW50ZXIKICAg"
    "ICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgc2VsZi5fdG9ycG9yX3Np"
    "bmNlICAgICAgICA9IE5vbmUgICMgZGF0ZXRpbWUgd2hlbiB0b3Jwb3IgYmVnYW4KICAgICAgICBzZWxm"
    "Ll9zdXNwZW5kZWRfZHVyYXRpb24gID0gIiIgICAjIGZvcm1hdHRlZCBkdXJhdGlvbiBzdHJpbmcKCiAg"
    "ICAgICAgIyDilIDilIAgTWFuYWdlcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc2VsZi5fbWVtb3J5ICAgPSBNZW1vcnlNYW5hZ2VyKCkKICAgICAgICBzZWxmLl9zZXNzaW9u"
    "cyA9IFNlc3Npb25NYW5hZ2VyKCkKICAgICAgICBzZWxmLl9sZXNzb25zICA9IExlc3NvbnNMZWFybmVk"
    "REIoKQogICAgICAgIHNlbGYuX3Rhc2tzICAgID0gVGFza01hbmFnZXIoKQogICAgICAgIHNlbGYuX3Jl"
    "Y29yZHNfY2FjaGU6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6"
    "ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIK"
    "ICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZ29vZ2xl"
    "X2luYm91bmRfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0gPSBOb25lCiAgICAgICAgc2VsZi5fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gLTEK"
    "ICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBzZWxmLl90YXNr"
    "X2RhdGVfZmlsdGVyID0gIm5leHRfM19tb250aHMiCgogICAgICAgICMg4pSA4pSAIEdvb2dsZSBTZXJ2"
    "aWNlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICAjIEluc3RhbnRpYXRlIHNlcnZpY2Ugd3JhcHBlcnMgdXAt"
    "ZnJvbnQ7IGF1dGggaXMgZm9yY2VkIGxhdGVyCiAgICAgICAgIyBmcm9tIG1haW4oKSBhZnRlciB3aW5k"
    "b3cuc2hvdygpIHdoZW4gdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBnX2NyZWRzX3Bh"
    "dGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJjcmVkZW50aWFs"
    "cyIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxz"
    "Lmpzb24iKQogICAgICAgICkpCiAgICAgICAgZ190b2tlbl9wYXRoID0gUGF0aChDRkcuZ2V0KCJnb29n"
    "bGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAidG9rZW4iLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgo"
    "Imdvb2dsZSIpIC8gInRva2VuLmpzb24iKQogICAgICAgICkpCiAgICAgICAgc2VsZi5fZ2NhbCA9IEdv"
    "b2dsZUNhbGVuZGFyU2VydmljZShnX2NyZWRzX3BhdGgsIGdfdG9rZW5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll9nZHJpdmUgPSBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlKAogICAgICAgICAgICBnX2NyZWRzX3BhdGgs"
    "CiAgICAgICAgICAgIGdfdG9rZW5fcGF0aCwKICAgICAgICAgICAgbG9nZ2VyPWxhbWJkYSBtc2csIGxl"
    "dmVsPSJJTkZPIjogc2VsZi5fZGlhZ190YWIubG9nKGYiW0dEUklWRV0ge21zZ30iLCBsZXZlbCkKICAg"
    "ICAgICApCgogICAgICAgICMgU2VlZCBMU0wgcnVsZXMgb24gZmlyc3QgcnVuCiAgICAgICAgc2VsZi5f"
    "bGVzc29ucy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAgICMgTG9hZCBlbnRpdHkgc3RhdGUKICAgICAg"
    "ICBzZWxmLl9zdGF0ZSA9IHNlbGYuX21lbW9yeS5sb2FkX3N0YXRlKCkKICAgICAgICBzZWxmLl9zdGF0"
    "ZVsic2Vzc2lvbl9jb3VudCJdID0gc2VsZi5fc3RhdGUuZ2V0KCJzZXNzaW9uX2NvdW50IiwwKSArIDEK"
    "ICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zdGFydHVwIl0gID0gbG9jYWxfbm93X2lzbygpCiAgICAg"
    "ICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICMgQnVpbGQgYWRh"
    "cHRvcgogICAgICAgIHNlbGYuX2FkYXB0b3IgPSBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAg"
    "ICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgKHNldCB1cCBhZnRlciB3aWRnZXRzIGJ1aWx0KQogICAg"
    "ICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyOiBPcHRpb25hbFtGYWNlVGltZXJNYW5hZ2VyXSA9IE5vbmUK"
    "CiAgICAgICAgIyDilIDilIAgQnVpbGQgVUkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShBUFBfTkFNRSkKICAgICAgICBzZWxmLnNldE1pbmlt"
    "dW1TaXplKDEyMDAsIDc1MCkKICAgICAgICBzZWxmLnJlc2l6ZSgxMzUwLCA4NTApCiAgICAgICAgc2Vs"
    "Zi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgogICAgICAgICMg"
    "RmFjZSB0aW1lciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBzZWxmLl9mYWNlX3RpbWVy"
    "X21nciA9IEZhY2VUaW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNlbGYuX21pcnJvciwgc2VsZi5fZW1v"
    "dGlvbl9ibG9jawogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyID0gUVRpbWVy"
    "KCkKICAgICAgICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRlX3N0"
    "YXRzKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnN0YXJ0KDEwMDApCgogICAgICAgIHNlbGYuX2Js"
    "aW5rX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9ibGlua190aW1lci50aW1lb3V0LmNvbm5l"
    "Y3Qoc2VsZi5fYmxpbmspCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIuc3RhcnQoODAwKQoKICAgICAg"
    "ICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1lcigpCiAgICAgICAgaWYgQUlfU1RBVEVTX0VO"
    "QUJMRUQgYW5kIHNlbGYuX3ZhbXBfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3N0"
    "YXRlX3N0cmlwX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl92YW1wX3N0cmlwLnJlZnJlc2gpCiAg"
    "ICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxm"
    "Ll9nb29nbGVfaW5ib3VuZF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2dsZV9p"
    "bmJvdW5kX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90"
    "aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAg"
    "ICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAg"
    "c2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25f"
    "Z29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNv"
    "cmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBh"
    "bmQgc3RhcnR1cCBkZWZlcnJlZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAg"
    "ICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVwX3NlcXVlbmNlKCkg"
    "aGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgZnJv"
    "bSBtYWluKCkgYWZ0ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5z"
    "IHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQo"
    "Y2VudHJhbCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSA"
    "IEJvZHk6IEpvdXJuYWwgfCBDaGF0IHwgU3lzdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICAjIEpvdXJuYWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIg"
    "PSBKb3VybmFsU2lkZWJhcihzZWxmLl9zZXNzaW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGVi"
    "YXIuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9sb2FkX2pv"
    "dXJuYWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVhcl9y"
    "ZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5hbF9zZXNzaW9uKQog"
    "ICAgICAgIGJvZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0"
    "IHBhbmVsIChjZW50ZXIsIGV4cGFuZHMpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRf"
    "Y2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAjIFN5c3RlbXMgKHJpZ2h0KQogICAgICAgIGJvZHkuYWRk"
    "TGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5lbCgpKQoKICAgICAgICByb290LmFkZExheW91"
    "dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0gUUxhYmVsKAogICAgICAgICAgICBmIuKcpiB7"
    "QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "OXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxp"
    "Z25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChmb290ZXIpCgogICAg"
    "ZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdpZGdldDoKICAgICAgICBiYXIgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAg"
    "ICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRp"
    "dGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25l"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVz"
    "ID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAg"
    "ICkKICAgICAgICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikK"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVT"
    "fSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQu"
    "QWxpZ25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAg"
    "ICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25lCiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgog"
    "ICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQYW5lbCgpCiAgICAgICAgICAgIHNl"
    "bGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRl"
    "X2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBzZWxmLl9pZGxlX2J0biA9IFFQ"
    "dXNoQnV0dG9uKCJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQo"
    "MjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5f"
    "aWRsZV9idG4uc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVz"
    "OiAycHg7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBh"
    "ZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNv"
    "bm5lY3Qoc2VsZi5fb25faWRsZV90b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAg"
    "ICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGUyIpCiAgICAgICAgc2VsZi5fYmxfYnRuID0g"
    "UVB1c2hCdXR0b24oIkJMIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuID0gUVB1c2hCdXR0b24oIkV4"
    "cG9ydCIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuID0gUVB1c2hCdXR0b24oIlNodXRkb3duIikK"
    "ICAgICAgICBmb3IgYnRuIGluIChzZWxmLl9mc19idG4sIHNlbGYuX2JsX2J0biwgc2VsZi5fZXhwb3J0"
    "X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFNpemUoMzAsIDIyKQogICAgICAgICAgICBidG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6"
    "IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4u"
    "c2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRIZWlnaHQo"
    "MjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2Vs"
    "Zi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsg"
    "cGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxs"
    "c2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVzcyAo"
    "RjEwKSIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNz"
    "aW9uIHRvIFRYVCBmaWxlIikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdy"
    "YWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhlaXIgbGFzdCB3b3JkcyIpCiAg"
    "ICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVlbikK"
    "ICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNz"
    "KQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0"
    "KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVf"
    "c2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1"
    "c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGlmIHNlbGYuX3RvcnBv"
    "cl9wYW5lbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b3Jw"
    "b3JfcGFuZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuX2lkbGVfYnRuKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fc2h1dGRvd25fYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZnNfYnRuKQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fYmxfYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAg"
    "ZGVmIF9idWlsZF9jaGF0X3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIE1haW4g"
    "dGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBzZWxmLl9tYWluX3Rh"
    "YnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAg"
    "ICAgZiJRVGFiQmFyOjp0YWIge3sgYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9u"
    "dC1zaXplOiAxMHB4OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFj"
    "a2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJv"
    "dHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSA"
    "IFRhYiAwOiBQZXJzb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2Vf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0U3BhY2lu"
    "ZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5f"
    "Y2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7"
    "Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIK"
    "ICAgICAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fY2hhdF9kaXNwbGF5"
    "KQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NI"
    "QVRfV0lORE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNl"
    "bGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNlbGZf"
    "bGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNl"
    "dFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAg"
    "IHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX3NlbGZfZGlz"
    "cGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBj"
    "b2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6"
    "IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rp"
    "c3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3RhYl93aWRn"
    "ZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fbWFpbl90YWJzLCAx"
    "KQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gYmxvY2sgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgTUlS"
    "Uk9SIHwgRU1PVElPTlMgfCBCTE9PRCB8IE1PT04gfCBNQU5BIHwgRVNTRU5DRQogICAgICAgIGJsb2Nr"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAg"
    "ICAjIE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgp"
    "CiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFj"
    "aW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBNSVJST1Ii"
    "KSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJv"
    "ci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9t"
    "aXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCkKCiAgICAgICAgIyBF"
    "bW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1v"
    "dGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xsYXBzaWJsZUJs"
    "b2NrKAogICAgICAgICAgICAi4p2nIEVNT1RJT05TIiwgc2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAg"
    "ICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMAogICAgICAgICkKICAgICAgICBibG9ja19y"
    "b3cuYWRkV2lkZ2V0KHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCkKCiAgICAgICAgc2VsZi5fYmxvb2Rf"
    "c3BoZXJlID0gTm9uZQogICAgICAgIHNlbGYuX21vb25fd2lkZ2V0ID0gTm9uZQogICAgICAgIHNlbGYu"
    "X21hbmFfc3BoZXJlID0gTm9uZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAg"
    "ICAjIEJsb29kIHNwaGVyZSAoY29sbGFwc2libGUpCiAgICAgICAgICAgIHNlbGYuX2Jsb29kX3NwaGVy"
    "ZSA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgICAgICJSRVNFUlZFIiwgQ19DUklNU09OLCBDX0NS"
    "SU1TT05fRElNCiAgICAgICAgICAgICkKICAgICAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAg"
    "ICAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soIuKdpyBSRVNFUlZFIiwgc2VsZi5fYmxvb2Rfc3Bo"
    "ZXJlLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtaW5fd2lkdGg9OTApCiAgICAgICAg"
    "ICAgICkKCiAgICAgICAgICAgICMgTW9vbiAoY29sbGFwc2libGUpCiAgICAgICAgICAgIHNlbGYuX21v"
    "b25fd2lkZ2V0ID0gTW9vbldpZGdldCgpCiAgICAgICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAg"
    "ICAgICAgICAgICAgICBDb2xsYXBzaWJsZUJsb2NrKCLinacgTFVOQVIiLCBzZWxmLl9tb29uX3dpZGdl"
    "dCwgbWluX3dpZHRoPTkwKQogICAgICAgICAgICApCgogICAgICAgICAgICAjIE1hbmEgc3BoZXJlIChj"
    "b2xsYXBzaWJsZSkKICAgICAgICAgICAgc2VsZi5fbWFuYV9zcGhlcmUgPSBTcGhlcmVXaWRnZXQoCiAg"
    "ICAgICAgICAgICAgICAiQVJDQU5BIiwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAgICAgICBDb2xsYXBzaWJs"
    "ZUJsb2NrKCLinacgQVJDQU5BIiwgc2VsZi5fbWFuYV9zcGhlcmUsIG1pbl93aWR0aD05MCkKICAgICAg"
    "ICAgICAgKQoKICAgICAgICAjIEVzc2VuY2UgKEhVTkdFUiArIFZJVEFMSVRZIGJhcnMsIGNvbGxhcHNp"
    "YmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlv"
    "dXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5n"
    "KDQpCiAgICAgICAgc2VsZi5faHVuZ2VyX2dhdWdlICAgPSBHYXVnZVdpZGdldCgiSFVOR0VSIiwgICAi"
    "JSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5fdml0YWxpdHlfZ2F1Z2UgPSBHYXVnZVdp"
    "ZGdldCgiVklUQUxJVFkiLCAiJSIsIDEwMC4wLCBDX0dSRUVOKQogICAgICAgIGVzc2VuY2VfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9odW5nZXJfZ2F1Z2UpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuX3ZpdGFsaXR5X2dhdWdlKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAg"
    "ICAgICAgIENvbGxhcHNpYmxlQmxvY2soIuKdpyBFU1NFTkNFIiwgZXNzZW5jZV93aWRnZXQsIG1pbl93"
    "aWR0aD0xMTApCiAgICAgICAgKQoKICAgICAgICBibG9ja19yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAg"
    "bGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMgQUkgU3RhdGUgU3RyaXAgaW5zdGFu"
    "Y2UgKGF0dGFjaGVkIGJlbG93IGlucHV0IHJvdykKICAgICAgICBzZWxmLl92YW1wX3N0cmlwID0gVmFt"
    "cGlyZVN0YXRlU3RyaXAoKSBpZiBBSV9TVEFURVNfRU5BQkxFRCBlbHNlIE5vbmUKCiAgICAgICAgIyDi"
    "lIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAg"
    "ICAgIHByb21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNP"
    "Tn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAg"
    "ICAgKQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5w"
    "dXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9s"
    "ZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1"
    "cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2Zp"
    "ZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1c2hCdXR0b24o"
    "VUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAg"
    "ICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRk"
    "V2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9pbnB1dF9m"
    "aWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxh"
    "eW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICAjIEFJIFN0YXRlIFN0cmlwIGluIGZvb3Rl"
    "ciBhcmVhIGJlbG93IHByb21wdC9pbnB1dCByb3cKICAgICAgICBpZiBzZWxmLl92YW1wX3N0cmlwIGlz"
    "IG5vdCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3ZhbXBfc3RyaXApCgog"
    "ICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2J1aWxkX3NwZWxsYm9va19wYW5lbChzZWxmKSAt"
    "PiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAg"
    "ICAgICMgVGFiIHdpZGdldAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLl9zcGVsbF90YWJzLnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3Bl"
    "bGxfdGFicy5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5k"
    "aW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQoKICAg"
    "ICAgICAjIEJ1aWxkIERpYWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBl"
    "dmVuIGJlZm9yZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0byB0aGUg"
    "d2lkZ2V0LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAj"
    "IOKUgOKUgCBJbnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5faHdfcGFuZWwg"
    "PSBIYXJkd2FyZVBhbmVsKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9od19w"
    "YW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDilIAgUmVjb3JkcyB0YWIgKHJlYWwpIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlbGYuX3JlY29yZHNfdGFiID0gUmVjb3Jkc1RhYigpCiAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9yZWNvcmRzX3RhYiwgIlJl"
    "Y29yZHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRz"
    "VGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgVGFza3MgdGFiIChyZWFsKSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl90YXNrc190YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3Nf"
    "cHJvdmlkZXI9c2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9h"
    "ZGRfZWRpdG9yX29wZW49c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAg"
    "IG9uX2NvbXBsZXRlX3NlbGVjdGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAg"
    "ICAgIG9uX2NhbmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAg"
    "ICAgb25fdG9nZ2xlX2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3MsCiAg"
    "ICAgICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0ZWRfdGFza3MsCiAg"
    "ICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQsCiAg"
    "ICAgICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0"
    "LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2UsCiAgICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2csCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFz"
    "a19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSBzZWxmLl9zcGVs"
    "bF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190YWIsICJUYXNrcyIpCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAg"
    "ICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKICAgICAgICBzZWxmLl9zcGVsbF90"
    "YWJzLmFkZFRhYihzZWxmLl9zbF9zY2FucywgIlNMIFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wg"
    "Q29tbWFuZHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21t"
    "YW5kc1RhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29tbWFuZHMs"
    "ICJTTCBDb21tYW5kcyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAiSm9iIFRyYWNrZXIiKQoKICAgICAg"
    "ICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKICAgICAgICBzZWxmLl9zcGVs"
    "bF90YWJzLmFkZFRhYihzZWxmLl9sZXNzb25zX3RhYiwgIkxlc3NvbnMiKQoKICAgICAgICAjIFNlbGYg"
    "dGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVhIGFsb25nc2lkZSB0aGUgcGVyc29uYSBjaGF0IHRhYgog"
    "ICAgICAgICMgS2VlcCBhIFNlbGZUYWIgaW5zdGFuY2UgZm9yIGlkbGUgY29udGVudCBnZW5lcmF0aW9u"
    "CiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBTZWxmVGFiKCkKCiAgICAgICAgIyDilIDilIAgTW9kdWxl"
    "IFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tl"
    "clRhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIs"
    "ICJNb2R1bGVzIikKCiAgICAgICAgIyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAiRGlhZ25vc3RpY3Mi"
    "KQoKICAgICAgICByaWdodF93b3Jrc3BhY2UgPSBRV2lkZ2V0KCkKICAgICAgICByaWdodF93b3Jrc3Bh"
    "Y2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0X3dvcmtz"
    "cGFjZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcmlnaHRfd29y"
    "a3NwYWNlX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX3NwZWxsX3RhYnMsIDEpCgogICAgICAgIGNhbGVuZGFyX2xhYmVsID0gUUxh"
    "YmVsKCLinacgQ0FMRU5EQVIiKQogICAgICAgIGNhbGVuZGFyX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEwcHg7IGxldHRlci1zcGFjaW5n"
    "OiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBy"
    "aWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChjYWxlbmRhcl9sYWJlbCkKCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhcl93aWRnZXQgPSBNaW5pQ2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXJfd2lkZ2V0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2VsZi5j"
    "YWxlbmRhcl93aWRnZXQuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5"
    "LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5Lk1heGltdW0KICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdodCgyNjApCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhcl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luc2VydF9j"
    "YWxlbmRhcl9kYXRlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "Y2FsZW5kYXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkU3RyZXRj"
    "aCgwKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFjZSwgMSkKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSByaWdodC1zaWRlIGNhbGVuZGFy"
    "IHJlc3RvcmVkIChwZXJzaXN0ZW50IGxvd2VyLXJpZ2h0IHNlY3Rpb24pLiIsCiAgICAgICAgICAgICJJ"
    "TkZPIgogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZ"
    "T1VUXSBwZXJzaXN0ZW50IG1pbmkgY2FsZW5kYXIgcmVzdG9yZWQvY29uZmlybWVkIChhbHdheXMgdmlz"
    "aWJsZSBsb3dlci1yaWdodCkuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAgIHJl"
    "dHVybiBsYXlvdXQKCiAgICAjIOKUgOKUgCBTVEFSVFVQIFNFUVVFTkNFIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zdGFydHVwX3NlcXVlbmNlKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtBUFBfTkFN"
    "RX0gQVdBS0VOSU5HLi4uIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYg"
    "e1JVTkVTfSDinKYiKQoKICAgICAgICAjIExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAgIGJvb3RfbG9n"
    "ID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBpZiBib290"
    "X2xvZy5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbXNncyA9IGJvb3Rf"
    "bG9nLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KG1zZ3MpCiAgICAgICAgICAgICAgICBib290X2xvZy51bmxp"
    "bmsoKSAgIyBjb25zdW1lZAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIEhhcmR3YXJlIGRldGVjdGlvbiBtZXNzYWdlcwogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdldF9kaWFnbm9zdGljcygpKQoKICAgICAg"
    "ICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBjcml0aWNhbCA9IERlcGVuZGVuY3lDaGVja2Vy"
    "LmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShkZXBfbXNncykKCiAgICAgICAg"
    "IyBMb2FkIHBhc3Qgc3RhdGUKICAgICAgICBsYXN0X3N0YXRlID0gc2VsZi5fc3RhdGUuZ2V0KCJ2YW1w"
    "aXJlX3N0YXRlX2F0X3NodXRkb3duIiwiIikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTVEFSVFVQXSBMYXN0IHNodXRk"
    "b3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAjIEJl"
    "Z2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAg"
    "ICAgVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAg"
    "ICAgICAgICAgIGYiU3VtbW9uaW5nIHtERUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNl"
    "bGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRl"
    "cldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3Qo"
    "CiAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAg"
    "ICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9h"
    "cHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5j"
    "b25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVk"
    "LmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJl"
    "YWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBk"
    "ZWYgX29uX2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBp"
    "ZiBzdWNjZXNzOgogICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAg"
    "IHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFi"
    "bGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAg"
    "ICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAgICAgIyBNZWFzdXJl"
    "IFZSQU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBn"
    "cHVfaGFuZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFUaW1lci5z"
    "aW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJhbV9iYXNlbGluZSkKICAgICAgICAgICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAgICAgIyBW"
    "YW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAg"
    "ICAgICAgICAgICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAgICAgICB2YW1w"
    "X2dyZWV0aW5ncyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkKICAgICAgICAgICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9jaGF0KAogICAgICAgICAgICAgICAgICAgICJTWVNURU0iLAogICAgICAgICAgICAgICAgICAg"
    "IHZhbXBfZ3JlZXRpbmdzLmdldChzdGF0ZSwgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUuIikKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgIyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVjdGlvbiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBJZiB0aGVyZSdzIGEg"
    "cHJldmlvdXMgc2h1dGRvd24gcmVjb3JkZWQsIGluamVjdCBjb250ZXh0CiAgICAgICAgICAgICMgc28g"
    "TW9yZ2FubmEgY2FuIGdyZWV0IHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHNoZSBzbGVwdAogICAg"
    "ICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg4MDAsIHNlbGYuX3NlbmRfd2FrZXVwX3Byb21wdCkKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJFUlJPUiIpCiAgICAgICAgICAg"
    "IHNlbGYuX21pcnJvci5zZXRfZmFjZSgicGFuaWNrZWQiKQoKICAgIGRlZiBfZm9ybWF0X2VsYXBzZWQo"
    "c2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgICAgICAiIiJGb3JtYXQgZWxhcHNlZCBzZWNv"
    "bmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0aW9uLiIiIgogICAgICAgIGlmIHNlY29uZHMgPCA2MDoK"
    "ICAgICAgICAgICAgcmV0dXJuIGYie2ludChzZWNvbmRzKX0gc2Vjb25keydzJyBpZiBzZWNvbmRzICE9"
    "IDEgZWxzZSAnJ30iCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAgICAgICAgICAgbSA9IGlu"
    "dChzZWNvbmRzIC8vIDYwKQogICAgICAgICAgICBzID0gaW50KHNlY29uZHMgJSA2MCkKICAgICAgICAg"
    "ICAgcmV0dXJuIGYie219IG1pbnV0ZXsncycgaWYgbSAhPSAxIGVsc2UgJyd9IiArIChmIiB7c31zIiBp"
    "ZiBzIGVsc2UgIiIpCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgODY0MDA6CiAgICAgICAgICAgIGggPSBp"
    "bnQoc2Vjb25kcyAvLyAzNjAwKQogICAgICAgICAgICBtID0gaW50KChzZWNvbmRzICUgMzYwMCkgLy8g"
    "NjApCiAgICAgICAgICAgIHJldHVybiBmIntofSBob3VyeydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsg"
    "KGYiIHttfW0iIGlmIG0gZWxzZSAiIikKICAgICAgICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNl"
    "Y29uZHMgLy8gODY0MDApCiAgICAgICAgICAgIGggPSBpbnQoKHNlY29uZHMgJSA4NjQwMCkgLy8gMzYw"
    "MCkKICAgICAgICAgICAgcmV0dXJuIGYie2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9IiArIChm"
    "IiB7aH1oIiBpZiBoIGVsc2UgIiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAiIiJTZW5kIGhpZGRlbiB3YWtlLXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9k"
    "ZWwgbG9hZHMuIiIiCiAgICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9z"
    "aHV0ZG93biIpCiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVybiAg"
    "IyBGaXJzdCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMg"
    "Q2FsY3VsYXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQg"
    "PSBkYXRldGltZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9"
    "IGRhdGV0aW1lLm5vdygpCiAgICAgICAgICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21wYXJpc29u"
    "CiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "ICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxhY2UodHppbmZvPU5v"
    "bmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3duX2R0KS50b3RhbF9z"
    "ZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9mb3JtYXRfZWxhcHNlZChlbGFw"
    "c2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBlbGFwc2VkX3N0ciA9"
    "ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBzdG9yZWQgZmFyZXdlbGwgYW5kIGxh"
    "c3QgY29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9mYXJl"
    "d2VsbCIsICIiKQogICAgICAgIGxhc3RfY29udGV4dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0"
    "ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAgICMgQnVpbGQgd2FrZS11cCBwcm9tcHQKICAgICAgICBj"
    "b250ZXh0X2Jsb2NrID0gIiIKICAgICAgICBpZiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgIGNvbnRl"
    "eHRfYmxvY2sgPSAiXG5cblRoZSBmaW5hbCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW9uOlxuIgog"
    "ICAgICAgICAgICBmb3IgaXRlbSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBzcGVha2Vy"
    "ID0gaXRlbS5nZXQoInJvbGUiLCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQg"
    "ICAgPSBpdGVtLmdldCgiY29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICAgY29udGV4dF9i"
    "bG9jayArPSBmIntzcGVha2VyfToge3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gIiIK"
    "ICAgICAgICBpZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSBmIlxuXG5Zb3Vy"
    "IGZpbmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3ZWxsfVwiIgoKICAg"
    "ICAgICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1c3QgYmVlbiByZWFj"
    "dGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgICAgICAgICAgZiJ7ZmFy"
    "ZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKICAgICAgICAgICAgZiJc"
    "bkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHlvdSBoYXZlIGJlZW4g"
    "YWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2FpZCB0byB0aGVtLiBC"
    "ZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxh"
    "cHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3Rv"
    "cnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YWtldXBfcHJvbXB0fSkKICAgICAg"
    "ICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRv"
    "ciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNlbGYuX3dha2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5f"
    "Zmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNl"
    "bGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYu"
    "X29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0"
    "KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VS"
    "Uk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19j"
    "aGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVk"
    "LmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0"
    "byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCgogICAgZGVm"
    "IF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgRm9y"
    "Y2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUgZXZlbnQgbG9vcCBpcyBydW5u"
    "aW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3NpbmcvaW52YWxpZCwgdGhlIGJyb3dzZXIgT0F1dGgg"
    "ZmxvdyBvcGVucyBuYXR1cmFsbHkuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IEdPT0dMRV9PSyBv"
    "ciBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVz"
    "ZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBpZiBHT09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBP"
    "UlRfRVJST1J9IiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fZ2NhbCBvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtX"
    "QVJOXSBHb29nbGUgYXV0aCBza2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWls"
    "YWJsZS4iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NU"
    "QVJUVVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2suIiwgIklORk8iKQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJU"
    "VVBdIGNyZWRlbnRpYWxzPXtzZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAgICAgICAg"
    "ICAgICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYuX2djYWwudG9rZW5fcGF0"
    "aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHNlbGYu"
    "X2djYWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09H"
    "TEVdW1NUQVJUVVBdIENhbGVuZGFyIGF1dGggcmVhZHkuIiwgIk9LIikKCiAgICAgICAgICAgIHNlbGYu"
    "X2dkcml2ZS5lbnN1cmVfc2VydmljZXMoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltH"
    "T09HTEVdW1NUQVJUVVBdIERyaXZlL0RvY3MgYXV0aCByZWFkeS4iLCAiT0siKQogICAgICAgICAgICBz"
    "ZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRydWUKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bU1RBUlRVUF0gU2NoZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRl"
    "ciBhdXRoLiIsICJJTkZPIikKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9y"
    "ZWZyZXNoX3JlY29yZHNfZG9jcykKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dM"
    "RV1bU1RBUlRVUF0gUG9zdC1hdXRoIHRhc2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAg"
    "ICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGluYm91bmQg"
    "c3luYyB0cmlnZ2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2Nv"
    "dW50ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1"
    "ZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xF"
    "XVtTVEFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1wb3J0ZWRf"
    "Y291bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xF"
    "XVtTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBfcmVmcmVzaF9yZWNvcmRz"
    "X2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lk"
    "ID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoIkxv"
    "YWRpbmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnBh"
    "dGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIGZpbGVzID0gc2VsZi5fZ2Ry"
    "aXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVy"
    "X2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fcmVjb3Jkc190"
    "YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX2dvb2ds"
    "ZV9pbmJvdW5kX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29v"
    "Z2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElN"
    "RVJdIENhbGVuZGFyIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwg"
    "IldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09H"
    "TEVdW1RJTUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3Vu"
    "ZCBwb2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAg"
    "ICAgICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1bHQg"
    "PSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwgY29tcGxldGUg"
    "4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1b"
    "VElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAg"
    "X3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAg"
    "ZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5"
    "IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQg"
    "c3RhcnRpbmcgYmFja2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFk"
    "aW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0"
    "ZS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJVkVd"
    "W1NZTkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVl"
    "KS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlz"
    "dFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cg"
    "PSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndl"
    "ZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03KQogICAgICAgIGVsaWYg"
    "c2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0"
    "aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInll"
    "YXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtz"
    "ZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBs"
    "ZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0"
    "KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbVEFTS1NdW0ZJTFRFUl0gaG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29u"
    "ZHMnKX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAg"
    "c2tpcHBlZF9pbnZhbGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAg"
    "ICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAg"
    "ICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBs"
    "ZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBk"
    "dWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBk"
    "dWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1"
    "ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9uZToKICAgICAg"
    "ICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBw"
    "aW5nIGludmFsaWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jh"
    "dz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgog"
    "ICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0"
    "ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAg"
    "ICAgICAgZmlsdGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0"
    "YXNrcyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2lu"
    "dmFsaWRfZHVlfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZp"
    "bHRlcmVkCgogICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0"
    "KToKICAgICAgICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAg"
    "ZGF0ZV90aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAg"
    "ICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJn"
    "b29nbGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAg"
    "ICByZXR1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAg"
    "ICBpZiBkYXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShm"
    "IntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGUiKQogICAgICAg"
    "ICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNo"
    "KCkKICAgICAgICAgICAgdmlzaWJsZV9jb3VudCA9IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3Jf"
    "cmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RS"
    "WV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVH"
    "SVNUUlldW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNv"
    "bj0icmVnaXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIHN0b3BfZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdv"
    "cmtlciBjbGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAg"
    "ICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2VsZiwgZmlsdGVyX2tl"
    "eTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBzdHIoZmlsdGVy"
    "X2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tT"
    "XSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2tfZGF0ZV9maWx0"
    "ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoK"
    "ICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl90YXNrX3Nob3dfY29t"
    "cGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVm"
    "IF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWYgZ2V0YXR0cihz"
    "ZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBbXQogICAg"
    "ICAgIHJldHVybiBzZWxmLl90YXNrc190YWIuc2VsZWN0ZWRfdGFza19pZHMoKQoKICAgIGRlZiBfc2V0"
    "X3Rhc2tfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlvbmFsW2Rp"
    "Y3RdOgogICAgICAgIGlmIHN0YXR1cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9"
    "IHNlbGYuX3Rhc2tzLmNvbXBsZXRlKHRhc2tfaWQpCiAgICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNl"
    "bGxlZCI6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jYW5jZWwodGFza19pZCkKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MudXBkYXRlX3N0YXR1cyh0"
    "YXNrX2lkLCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAgICByZXR1cm4g"
    "Tm9uZQoKICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9p"
    "ZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0ZV9ldmVudF9mb3JfdGFzayhnb29nbGVf"
    "ZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW1dBUk5dIEdv"
    "b2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza19pZD17dGFza19pZH06IHtleH0iLAogICAg"
    "ICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gdXBk"
    "YXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToK"
    "ICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjb21wbGV0ZWQiKToK"
    "ICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNL"
    "U10gQ09NUExFVEUgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9z"
    "ZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFz"
    "a19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRf"
    "dGFza19zdGF0dXModGFza19pZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAx"
    "CiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGll"
    "ZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3Jl"
    "Z2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHJlbW92ZWQgPSBzZWxmLl90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9"
    "IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5l"
    "bCgpCgogICAgZGVmIF9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJv"
    "b2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwg"
    "Tm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc3RhdHVzKHRl"
    "eHQsIG9rPW9rKQoKICAgIGRlZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBl"
    "bmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEobWludXRlcz0zMCkKICAgICAgICBzZWxmLl90"
    "YXNrc190YWIudGFza19lZGl0b3JfbmFtZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3Rh"
    "Yi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0l"
    "ZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQo"
    "bm93X2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2Vk"
    "aXRvcl9lbmRfZGF0ZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAg"
    "ICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3Ry"
    "ZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNl"
    "dFBsYWluVGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbG9jYXRpb24u"
    "c2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS5z"
    "ZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNldENo"
    "ZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmlndXJl"
    "IHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkKICAg"
    "ICAgICBzZWxmLl90YXNrc190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2VfdGFza19lZGl0"
    "b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tz"
    "X3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuY2xvc2Vf"
    "ZWRpdG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfcGFy"
    "c2VfZWRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDogc3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxs"
    "X2RheTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2UpOgogICAgICAgIGRhdGVfdGV4dCA9IChkYXRl"
    "X3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0aW1lX3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5z"
    "dHJpcCgpCiAgICAgICAgaWYgbm90IGRhdGVfdGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAg"
    "ICAgICBpZiBhbGxfZGF5OgogICAgICAgICAgICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAg"
    "ICAgICAgICBtaW51dGUgPSA1OSBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGRh"
    "dGV0aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge2hvdXI6MDJkfTp7bWludXRlOjAyZH0iLCAiJVkt"
    "JW0tJWQgJUg6JU0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0"
    "cnB0aW1lKGYie2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAg"
    "IG5vcm1hbGl6ZWQgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0"
    "PSJ0YXNrX2VkaXRvcl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICBmIltUQVNLU11bRURJVE9SXSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9LCBhbGxf"
    "ZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0"
    "fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25lJ30iLAog"
    "ICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAg"
    "ZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25lOgogICAgICAgIHRh"
    "YiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAgIGlmIHRhYiBpcyBOb25l"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50YXNrX2VkaXRvcl9uYW1lLnRl"
    "eHQoKS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2VkaXRvcl9hbGxfZGF5LmlzQ2hl"
    "Y2tlZCgpCiAgICAgICAgc3RhcnRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnRl"
    "eHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUgPSB0YWIudGFza19lZGl0b3JfZW5kX2RhdGUudGV4"
    "dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfdGltZS50ZXh0"
    "KCkuc3RyaXAoKQogICAgICAgIG5vdGVzID0gdGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxhaW5UZXh0"
    "KCkuc3RyaXAoKQogICAgICAgIGxvY2F0aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgcmVjdXJyZW5jZSA9IHRhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRl"
    "eHQoKS5zdHJpcCgpCgogICAgICAgIGlmIG5vdCB0aXRsZToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rh"
    "c2tfZWRpdG9yX3N0YXR1cygiVGFzayBOYW1lIGlzIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBub3QgZW5kX2RhdGUgb3IgKG5v"
    "dCBhbGxfZGF5IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1lKSk6CiAgICAgICAgICAg"
    "IHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZCBkYXRlIGFuZCB0aW1lIGFyZSBy"
    "ZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShzdGFydF9kYXRlLCBzdGFy"
    "dF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9IHNlbGYuX3Bh"
    "cnNlX2VkaXRvcl9kYXRldGltZShlbmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXksIGlzX2VuZD1UcnVl"
    "KQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQgb3Igbm90IGVuZF9kdDoKICAgICAgICAgICAgICAg"
    "IHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZhaWxlZCIpCiAgICAgICAgICAgIGlmIGVu"
    "ZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1"
    "cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQgZGF0ZXRpbWUuIiwgb2s9RmFsc2UpCiAg"
    "ICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBz"
    "ZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJbnZhbGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZ"
    "WVlZLU1NLUREIGFuZCBISDpNTS4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IHR6X25hbWUgPSBzZWxmLl9nY2FsLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBw"
    "YXlsb2FkID0geyJzdW1tYXJ5IjogdGl0bGV9CiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAg"
    "cGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZSI6IHN0YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAg"
    "ICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGUiOiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0"
    "YShkYXlzPTEpKS5pc29mb3JtYXQoKX0KICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJz"
    "dGFydCJdID0geyJkYXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXls"
    "b2FkWyJlbmQiXSA9IHsiZGF0ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9y"
    "bWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90"
    "ZXM6CiAgICAgICAgICAgIHBheWxvYWRbImRlc2NyaXB0aW9uIl0gPSBub3RlcwogICAgICAgIGlmIGxv"
    "Y2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJdID0gbG9jYXRpb24KICAgICAgICBp"
    "ZiByZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1cnJlbmNlLnVw"
    "cGVyKCkuc3RhcnRzd2l0aCgiUlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJlbmNlfSIKICAgICAg"
    "ICAgICAgcGF5bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1bGVdCgogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdGFydCBmb3IgdGl0bGU9J3t0aXRsZX0n"
    "LiIsICJJTkZPIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV2ZW50X2lkLCBfID0gc2VsZi5fZ2Nh"
    "bC5jcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBheWxvYWQsIGNhbGVuZGFyX2lkPSJwcmltYXJ5IikK"
    "ICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sg"
    "PSB7CiAgICAgICAgICAgICAgICAiaWQiOiBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAog"
    "ICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAg"
    "ICAiZHVlX2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAg"
    "ICAgICAgICAicHJlX3RyaWdnZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAog"
    "ICAgICAgICAgICAgICAgInN0YXR1cyI6ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3ds"
    "ZWRnZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgInJldHJ5X2NvdW50IjogMCwKICAgICAgICAg"
    "ICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAibmV4dF9yZXRy"
    "eV9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAogICAgICAg"
    "ICAgICAgICAgInNvdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lk"
    "IjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwKICAgICAg"
    "ICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAg"
    "ICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFza19lZGl0b3JfZ29v"
    "Z2xlX2ZpcnN0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3RlcywKICAgICAgICAgICAg"
    "ICAgICAgICAic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwK"
    "ICAgICAgICAgICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vj"
    "b25kcyIpLAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5IjogYm9vbChhbGxfZGF5KSwKICAgICAg"
    "ICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwKICAgICAgICAgICAgICAgICAgICAicmVj"
    "dXJyZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICB9CiAgICAg"
    "ICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0"
    "YXNrcykKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMg"
    "c3VjY2VlZGVkIGFuZCB0YXNrIHJlZ2lzdHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAg"
    "c2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3VjY2Vz"
    "cyBmb3IgdGl0bGU9J3t0aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICAg"
    "ICAiT0siLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dv"
    "cmtzcGFjZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZhbHNl"
    "KQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11b"
    "RURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0nOiB7ZXh9"
    "IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "Y2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9jYWxlbmRhcl9kYXRl"
    "KHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF0ZS50b1N0"
    "cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJub25lIgoKICAgICAgICBm"
    "b2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQogICAgICAgIGRpcmVjdF90YXJn"
    "ZXRzID0gWwogICAgICAgICAgICAoInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBnZXRhdHRyKGdldGF0"
    "dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBOb25l"
    "KSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5kX2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2Vs"
    "ZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgTm9uZSkpLAogICAg"
    "ICAgIF0KICAgICAgICBmb3IgbmFtZSwgd2lkZ2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAgICAgICAg"
    "ICBpZiB3aWRnZXQgaXMgbm90IE5vbmUgYW5kIGZvY3VzX3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAg"
    "ICAgICAgICB3aWRnZXQuc2V0VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICByb3V0ZWRfdGFy"
    "Z2V0ID0gbmFtZQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgcm91dGVkX3RhcmdldCA9"
    "PSAibm9uZSI6CiAgICAgICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIpIGFuZCBz"
    "ZWxmLl9pbnB1dF9maWVsZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdl"
    "dCBpcyBzZWxmLl9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVs"
    "ZC5pbnNlcnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5w"
    "dXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICByb3V0"
    "ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX3Rh"
    "c2tzX3RhYiIpIGFuZCBzZWxmLl90YXNrc190YWIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYu"
    "X3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkNhbGVuZGFyIGRhdGUgc2VsZWN0ZWQ6IHtk"
    "YXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2RpYWdfdGFiIikgYW5kIHNlbGYu"
    "X2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6IGRhdGU9e2Rh"
    "dGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgog"
    "ICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2Vs"
    "ZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNlKToKICAgICAgICAiIiIKICAgICAgICBTeW5jIEdvb2ds"
    "ZSBDYWxlbmRhciBldmVudHMg4oaSIGxvY2FsIHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBB"
    "UEkuCgogICAgICAgIFN0YWdlIDEgKGZpcnN0IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3Jl"
    "cyBuZXh0U3luY1Rva2VuLgogICAgICAgIFN0YWdlIDIgKGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3Jl"
    "bWVudGFsIGZldGNoIHVzaW5nIHN0b3JlZCBzeW5jVG9rZW4g4oCUCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgcmV0dXJucyBPTkxZIHdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0cy9jYW5j"
    "ZWxzKS4KICAgICAgICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZh"
    "bGxzIGJhY2sgdG8gZnVsbCBzeW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNl"
    "IGFuZCBub3QgYm9vbChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJs"
    "ZWQiLCBUcnVlKSk6CiAgICAgICAgICAgIHJldHVybiAwCgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "bm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxv"
    "YWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7CiAgICAgICAgICAgICAgICAo"
    "dC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAgICAgICAgICAgICBm"
    "b3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgaWYgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBv"
    "ciAiIikuc3RyaXAoKQogICAgICAgICAgICB9CgogICAgICAgICAgICAjIOKUgOKUgCBGZXRjaCBmcm9t"
    "IEdvb2dsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RvcmVkX3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJn"
    "b29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIpCgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5vdCBmb3JjZV9vbmNlOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIElu"
    "Y3JlbWVudGFsIHN5bmMgKHN5bmNUb2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxp"
    "c3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVk"
    "X3Rva2VuCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09P"
    "R0xFXVtTWU5DXSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAgICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5y"
    "ZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0"
    "YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAg"
    "ICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50"
    "cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAg"
    "ICAgICApCgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoKICAgICAgICAgICAg"
    "ICAgIGlmICI0MTAiIGluIHN0cihhcGlfZXgpIG9yICJHb25lIiBpbiBzdHIoYXBpX2V4KToKICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJb"
    "R09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDigJQgZnVsbCByZXN5bmMuIiwgIldB"
    "Uk4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3N0YXRlLnBv"
    "cCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iLCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5v"
    "d191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAg"
    "ICAgICAgICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1h"
    "dCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNl"
    "bGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9t"
    "aW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgICAgIHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2"
    "ZW50KHMpLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2Vu"
    "IGZvciBuZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3N0YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF90"
    "b2tlbgogICAgICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgog"
    "ICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAg"
    "ICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9IDAKICAgICAg"
    "ICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3IgZXZlbnQgaW4gcmVtb3RlX2V2ZW50"
    "czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2ZW50LmdldCgiaWQiKSBvciAiIikuc3RyaXAo"
    "KQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVkIC8gY2FuY2VsbGVkIG9uIEdvb2dsZSdzIHNpZGUK"
    "ICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgic3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAg"
    "ICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAg"
    "ICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3RhdHVzIikgbm90"
    "IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlz"
    "dGluZ1sic3RhdHVzIl0gICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGV4aXN0aW5nWyJjYW5jZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAg"
    "ICBleGlzdGluZ1sic3luY19zdGF0dXMiXSAgICA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pWyJnb29nbGVfZGVs"
    "ZXRlZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3ZlZF9jb3Vu"
    "dCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "W0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4dCcsJz8nKX0iLCAiSU5GTyIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAg"
    "ICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnkiKSBvciAiR29vZ2xlIENhbGVu"
    "ZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50IgogICAgICAgICAgICAg"
    "ICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUoZXZlbnQpCiAgICAgICAg"
    "ICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkKCiAgICAgICAg"
    "ICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgICAgICAjIFVwZGF0ZSBpZiBhbnl0aGlu"
    "ZyBjaGFuZ2VkCiAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAg"
    "ICAgICAgICAgICBpZiAoZXhpc3RpbmcuZ2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFy"
    "eToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlm"
    "IGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgZHVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQo"
    "ImR1ZV9hdCIpICE9IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "ZHVlX2F0Il0gICAgICAgPSBkdWVfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sicHJlX3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5n"
    "ZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0YXR1cyIp"
    "ICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMi"
    "XSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAg"
    "ICAgICAgICAgICAgICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4"
    "aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICB1"
    "cGRhdGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBVcGRhdGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICAjIE5ldyBldmVudAogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgp"
    "LmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5v"
    "d19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5p"
    "c29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90"
    "cmlnZ2VyIjogICAgICAgKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAg"
    "ICAgc3VtbWFyeSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAgInBl"
    "bmRpbmciLAogICAgICAgICAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogICBOb25lLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAibmV4dF9yZXRyeV9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX2Fu"
    "bm91bmNlZCI6ICAgICBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgInNvdXJjZSI6ICAgICAg"
    "ICAgICAgImdvb2dsZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAg"
    "IGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICAic3lu"
    "Y2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogICAgbm93X2lzbywK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgImdvb2dsZV9pbXBvcnRlZF9hdCI6IG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAgICAgZXZlbnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIH0sCiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRh"
    "c2tzLmFwcGVuZChuZXdfdGFzaykKICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtl"
    "dmVudF9pZF0gPSBuZXdfdGFzawogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEK"
    "ICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIp"
    "CgogICAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9h"
    "bGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZ"
    "TkNdIERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAgZiJ1"
    "cGRhdGVkPXt1cGRhdGVkX2NvdW50fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZPIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAoKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtT"
    "WU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAwCgoKICAgIGRlZiBf"
    "bWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgTlZNTF9PSyBhbmQg"
    "Z3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52"
    "bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBzZWxmLl9kZWNr"
    "X3ZyYW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2Vs"
    "Zi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIKICAgICAgICAgICAgICAgICAgICBmIih7REVDS19OQU1F"
    "fSdzIGZvb3RwcmludCkiLCAiSU5GTyIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNTQUdFIEhBTkRM"
    "SU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9z"
    "ZW5kX21lc3NhZ2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVk"
    "IG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0"
    "ZXh0OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBjaGF0"
    "IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX21haW5fdGFicy5jdXJy"
    "ZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4"
    "KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBzZWxmLl9hcHBlbmRf"
    "Y2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVu"
    "ZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4dCkKCiAgICAgICAgIyBJbnRlcnJ1"
    "cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVkaWF0ZWx5CiAgICAgICAgaWYgc2Vs"
    "Zi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLmludGVycnVw"
    "dCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21wdCB3aXRoIHZhbXBpcmUgY29udGV4dCArIG1l"
    "bW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9jdHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkK"
    "ICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0"
    "KQogICAgICAgIGpvdXJuYWxfY3R4ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRl"
    "ZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9h"
    "ZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRf"
    "am91cm5hbF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAg"
    "ICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAg"
    "ICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0"
    "eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVt"
    "ICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50"
    "IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJw"
    "eXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNM"
    "IiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAgICAgICAgICBsZXNzb25z"
    "X2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2UobGFuZykKICAgICAg"
    "ICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3Nv"
    "bnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55"
    "CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVy"
    "ID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJzb21lIHRpbWUiCiAgICAgICAgICAgIHN5c3Rl"
    "bSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxuIgogICAgICAg"
    "ICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBm"
    "IntzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAg"
    "ICAgICAgICAgICAgZiJkdXJpbmcgdGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4g"
    "Y2hhcmFjdGVyICIKICAgICAgICAgICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAg"
    "ICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5f"
    "c2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVu"
    "YWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAg"
    "ICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1"
    "bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIExhdW5j"
    "aCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAog"
    "ICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1heF90b2tlbnM9NTEyCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rv"
    "a2VuKQogICAgICAgIHNlbGYuX3dvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVz"
    "cG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdy"
    "aXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0"
    "YXJ0KCkKCiAgICBkZWYgX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICAiIiIKICAgICAgICBXcml0ZSB0aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAg"
    "YmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZpcnN0IHRva2VuIG9ubHku"
    "IFN1YnNlcXVlbnQgdG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1l"
    "c3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUg"
    "dGhlIHNwZWFrZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2VucwogICAg"
    "ICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rp"
    "c3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAg"
    "ICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7"
    "Ij4nCiAgICAgICAgICAgIGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+ICcKICAgICAgICAp"
    "CiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxhaW5UZXh0IGFwcGVuZHMgY29y"
    "cmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAg"
    "ICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9r"
    "ZW4oc2VsZiwgdG9rZW46IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRv"
    "a2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAgICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAg"
    "ICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0"
    "X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNv"
    "cigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVu"
    "ZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0"
    "X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hh"
    "dF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBf"
    "b25fcmVzcG9uc2VfZG9uZShzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5z"
    "dXJlIHJlc3BvbnNlIGlzIG9uIGl0cyBvd24gbGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRf"
    "ZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29y"
    "Lk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29y"
    "KGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikK"
    "CiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291"
    "bnQgKz0gbGVuKHJlc3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3Nh"
    "Z2UoImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2Fn"
    "ZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVt"
    "b3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAj"
    "IFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBpZiBzZWxmLl9ibG9vZF9zcGhlcmUgaXMgbm90IE5v"
    "bmU6CiAgICAgICAgICAgIHNlbGYuX2Jsb29kX3NwaGVyZS5zZXRGaWxsKAogICAgICAgICAgICAgICAg"
    "bWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAg"
    "IyBSZS1lbmFibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAg"
    "ICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0"
    "X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgIyBSZXN1bWUgaWRsZSB0aW1lcgogICAgICAgIGlmIHNl"
    "bGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lv"
    "biIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAg"
    "ICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2Up"
    "KQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQog"
    "ICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1l"
    "bnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50"
    "KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21n"
    "cjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAgICBk"
    "ZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5k"
    "X2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJ"
    "T04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdy"
    "OgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAg"
    "ICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFi"
    "bGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg"
    "4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRl"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAg"
    "aWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29u"
    "PSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAi"
    "QVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBB"
    "V0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwg"
    "aXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJl"
    "c2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3Mg"
    "ICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBW"
    "UkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Io"
    "c2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jw"
    "b3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBv"
    "cgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIp"
    "CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dk"
    "ZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAg"
    "aWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0"
    "b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2Rl"
    "bCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAg"
    "ICAgIGlmIFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUo"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIs"
    "ICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJu"
    "ZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxl"
    "ZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxj"
    "dWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAg"
    "ICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAg"
    "ICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9z"
    "ZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgog"
    "ICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDi"
    "gJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0"
    "aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVk"
    "X2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBs"
    "aXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAg"
    "IHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmll"
    "bGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1Jd"
    "IEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9h"
    "ZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYi"
    "VGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAg"
    "ICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCku"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAg"
    "ICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAg"
    "ICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRh"
    "IG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVy"
    "LmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQo"
    "IkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qo"
    "c2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNv"
    "bm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhy"
    "ZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoK"
    "ICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAg"
    "ICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0"
    "ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNh"
    "Z2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmln"
    "Z2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYg"
    "c2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYg"
    "bm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlm"
    "IHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVf"
    "aGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAg"
    "ICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAg"
    "ICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAg"
    "ICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAg"
    "ICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAg"
    "c2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJl"
    "c3N1cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAg"
    "ICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAg"
    "ICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNl"
    "bGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYu"
    "X3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jw"
    "b3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9"
    "R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJl"
    "IHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAog"
    "ICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBh"
    "dXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0"
    "b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92"
    "cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9d"
    "IFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSA"
    "IEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3Jv"
    "dW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVs"
    "ZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0K"
    "ICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5f"
    "c2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "ICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAg"
    "ICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJz"
    "ZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1"
    "dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1"
    "dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1"
    "dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykK"
    "ICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJh"
    "bV9wcmVzc3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVj"
    "ayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCU"
    "IGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0u"
    "Z2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdz"
    "Il0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxl"
    "X21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAg"
    "ICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAg"
    "ICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgog"
    "ICAgICAgICMgTW9vbiB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBpZiBzZWxm"
    "Ll9tb29uX3dpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9q"
    "b2IoCiAgICAgICAgICAgICAgICBzZWxmLl9tb29uX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFs"
    "IiwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hl"
    "ZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBB"
    "RlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMg"
    "cnVubmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUu"
    "CgogICAgZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAg"
    "IENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4"
    "ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVu"
    "bmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlm"
    "IHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMg"
    "cGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNz"
    "aW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxl"
    "ciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9IiwgIkVSUk9S"
    "IikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNl"
    "dF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAg"
    "ICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3Nh"
    "dmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJy"
    "b3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0g"
    "IkdFTkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2lu"
    "Y2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGlu"
    "ZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5z"
    "bWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAg"
    "ICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5H"
    "IiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBidWlsZF92YW1w"
    "aXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgp"
    "CgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAgc2VsZi5f"
    "YWRhcHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBoaXN0b3J5"
    "LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29udGV4dD12YW1waXJl"
    "X2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9pZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBhcHBlbmQgdGhlcmUKICAgICAgICAgICAg"
    "c2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1l"
    "Lm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBl"
    "bmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicK"
    "ICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxi"
    "cj4nCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJ"
    "VkUiLCB0KQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVj"
    "dChfb25faWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5j"
    "b25uZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJS"
    "T1JdIHtlfSIsICJFUlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0"
    "KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChk"
    "YXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9"
    "IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91"
    "cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVf"
    "c3RyfSBhcyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9m"
    "IHRoYXQgY29udmVyc2F0aW9uLiIsICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiQSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yg"
    "e2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9y"
    "Z2FubmEKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAg"
    "ICAgICAgICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91"
    "cm5hbCBmcm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBi"
    "cmllZmx5IOKAlCB5b3Ugbm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhh"
    "dCBjb252ZXJzYXRpb24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFk"
    "ZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pvdXJuYWwoKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVk"
    "LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAg"
    "IlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAgICApCgog"
    "ICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAg"
    "ICAgICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFw"
    "c2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgog"
    "ICAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9z"
    "dGF0dXMsCiAgICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCks"
    "CiAgICAgICAgICAgIHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQp"
    "LAogICAgICAgICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAj"
    "IExlZnQgc3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAgICAg"
    "ICBibG9vZF9maWxsID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAg"
    "aWYgc2VsZi5fYmxvb2Rfc3BoZXJlIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9ibG9vZF9z"
    "cGhlcmUuc2V0RmlsbChibG9vZF9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgIyBSaWdodCBz"
    "cGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX21hbmFfc3BoZXJlIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5"
    "SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbS51c2VkICAv"
    "IDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBtZW0udG90YWwgLyAxMDI0Kioz"
    "CiAgICAgICAgICAgICAgICAgICAgbWFuYV9maWxsID0gbWF4KDAuMCwgMS4wIC0gKHZyYW1fdXNlZCAv"
    "IHZyYW1fdG90KSkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZS5zZXRGaWxsKG1h"
    "bmFfZmlsbCwgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX21hbmFfc3BoZXJlLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9"
    "RmFsc2UpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZS5z"
    "ZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAjIEhVTkdFUiA9IGludmVyc2Ugb2Yg"
    "bGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGh1bmdlciA9IDEuMCAtIGJsb29kX2ZpbGwKICAgICAgICBp"
    "ZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5faHVuZ2VyX2dhdWdlLnNldFZhbHVl"
    "KGh1bmdlciAqIDEwMCwgZiJ7aHVuZ2VyKjEwMDouMGZ9JSIpCgogICAgICAgICMgVklUQUxJVFkgPSBS"
    "QU0gZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxf"
    "T0s6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1"
    "dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAgICB2aXRhbGl0eSAgPSAxLjAgLSAo"
    "bWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdml0YWxpdHlfZ2F1"
    "Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgICAgIHZpdGFsaXR5ICogMTAwLCBmInt2aXRh"
    "bGl0eSoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl92aXRhbGl0eV9nYXVnZS5zZXRVbmF2"
    "YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92aXRhbGl0eV9n"
    "YXVnZS5zZXRVbmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRv"
    "c2F2ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKU"
    "gOKUgCBDSEFUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4"
    "dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBD"
    "X0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAgIlNZ"
    "U1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0K"
    "ICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwK"
    "ICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVN"
    "IjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAg"
    "ICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dPTEQpCiAgICAgICAgbGFiZWxf"
    "Y29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAgICAgICAgdGltZXN0"
    "YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzcGVh"
    "a2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAg"
    "ICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBw"
    "eDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+Jwog"
    "ICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFw"
    "cGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAg"
    "ICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0"
    "OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAg"
    "ICAgICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAo"
    "bm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBwZXIo"
    "KToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAgc2VsZi5f"
    "Y2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYu"
    "X2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICAj"
    "IOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3Rh"
    "dHVzOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3Rh"
    "dHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAg"
    "ICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExF"
    "LAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMSU5FIjog"
    "ICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAg"
    "fQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAg"
    "ICAgICB0b3Jwb3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAi"
    "VE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRl"
    "eHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAgICAgIGlm"
    "IHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBz"
    "ZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNl"
    "dFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRP"
    "UlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLi"
    "ipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBm"
    "IntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExF"
    "IFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5v"
    "bmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAg"
    "ICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZG"
    "IikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNv"
    "bG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAg"
    "IGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "c2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBlbmFibGVkLiIsICJP"
    "SyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJ"
    "TkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfdG9nZ2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxm"
    "LmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBz"
    "ZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBzZWxmLl9mc19idG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19"
    "OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAgIGRlZiBfdG9nZ2xlX2JvcmRlcmxl"
    "c3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYg"
    "UXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAg"
    "ICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygp"
    "ICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAg"
    "ICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNl"
    "bGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAg"
    "ICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07"
    "ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6"
    "ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIK"
    "ICAgICAgICAgICAgKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVu"
    "dCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2No"
    "YXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6CiAg"
    "ICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBv"
    "cnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRy"
    "dWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMi"
    "KQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAg"
    "ICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAg"
    "ICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlw"
    "Ym9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVN"
    "IiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5k"
    "IGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VY"
    "UE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIp"
    "CgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0g"
    "ZXZlbnQua2V5KCkKICAgICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoK"
    "ICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0"
    "LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNo"
    "b3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAg"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTog"
    "OXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAg"
    "ICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJlc3NFdmVudChl"
    "dmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2"
    "ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1"
    "dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9p"
    "bml0aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBz"
    "aHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQg"
    "bGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwg"
    "anVzdCBmb3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dy"
    "ZXNzJywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAg"
    "IyBTaG93IGNvbmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRs"
    "ZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikK"
    "ICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9"
    "OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAgICAgICAg"
    "ICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g"
    "bWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQog"
    "ICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoK"
    "ICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0"
    "dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9u"
    "KCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikK"
    "CiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2VsKToKICAgICAgICAg"
    "ICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsi"
    "CiAgICAgICAgICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAg"
    "ICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBi"
    "dG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5j"
    "ZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRX"
    "aWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogICAgICAg"
    "IGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3Jv"
    "dykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAg"
    "ICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3Mg"
    "PSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAg"
    "ICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCUIG5vIGxh"
    "c3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJl"
    "c3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAg"
    "ICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dv"
    "cmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHBy"
    "b21wdCwgc2hvdyByZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAg"
    "IGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQu"
    "IFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdv"
    "cmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVz"
    "cG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9j"
    "aGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVh"
    "ayBoZXIgZmluYWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVu"
    "YWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAg"
    "ICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0"
    "b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0fSkKICAg"
    "ICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRh"
    "cHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBz"
    "ZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBfb25fZG9uZShyZXNwb25zZTog"
    "c3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9"
    "IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQog"
    "ICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNo"
    "dXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYu"
    "X2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAt"
    "PiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJO"
    "XSBMYXN0IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RvX3NodXRkb3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChz"
    "ZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25f"
    "ZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQog"
    "ICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQog"
    "ICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAg"
    "ICAgICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBB"
    "SSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFUaW1l"
    "ci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVz"
    "cycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5d"
    "IExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FS"
    "TiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0IHNodXQg"
    "ZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRv"
    "d24oc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24g"
    "c2VxdWVuY2UuIiIiCiAgICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "IHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBo"
    "aXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Np"
    "b25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlm"
    "IGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFz"
    "dF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9s"
    "ZSIsIiIpLCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAg"
    "ICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3Qg"
    "TW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJl"
    "ZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAg"
    "ICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQnLCAi"
    "IikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2"
    "ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNz"
    "aXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIs"
    "ICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9z"
    "dGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28o"
    "KQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9j"
    "YWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRk"
    "b3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9z"
    "dGF0ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1"
    "bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZh"
    "bHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3No"
    "dXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRl"
    "cikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg"
    "4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQ"
    "cmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQog"
    "ICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24g"
    "Zmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBj"
    "aG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhh"
    "dCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAg"
    "ICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAg"
    "ICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAg"
    "ICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0"
    "Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFu"
    "ZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKU"
    "gCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAg"
    "ICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dzKSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9l"
    "YXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0"
    "aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIElu"
    "c3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJu"
    "aW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAg"
    "ICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBs"
    "aWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQ"
    "aGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4i"
    "LCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygp"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAg"
    "ICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxv"
    "ZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdf"
    "Y2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5u"
    "YSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDov"
    "QUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIg"
    "ICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBt"
    "b3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1r"
    "ZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAgICAgIyDilIDilIAgVXBkYXRlIGFs"
    "bCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAg"
    "ICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdb"
    "InBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZh"
    "Y2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIp"
    "LAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAog"
    "ICAgICAgICAgICAic2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAg"
    "ICAgICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAi"
    "ZXhwb3J0cyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dz"
    "IjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAg"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIo"
    "bW9yZ2FubmFfaG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9y"
    "Z2FubmFfaG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0g"
    "PSB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIg"
    "LyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3Ry"
    "KG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAgICJ0aW1l"
    "em9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAg"
    "ICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwK"
    "ICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAg"
    "ICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAg"
    "ICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UK"
    "CiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAg"
    "ICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHki"
    "CiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2Fybmlu"
    "ZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAg"
    "ICAgICBmIkNvdWxkIG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1c"
    "blxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHku"
    "IgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRv"
    "IG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyAi"
    "Y29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlz"
    "dF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04Iikg"
    "YXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAj"
    "IOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gYm9vdHN0"
    "cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAg"
    "ICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAg"
    "ICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJ"
    "UCBpZiBwcm92aWRlZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBm"
    "YWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFj"
    "ZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAg"
    "ICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNl"
    "c19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAg"
    "ICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAgICAgIGZvciBtZW1i"
    "ZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2Vy"
    "KCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0g"
    "UGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9IGZhY2Vz"
    "X2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aXRoIHpmLm9wZW4obWVt"
    "YmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0"
    "ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAg"
    "ZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5n"
    "KAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAg"
    "ICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAg"
    "ICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9p"
    "bnRpbmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRj"
    "dXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1w"
    "b3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAg"
    "ICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAgICAgc2NfcGF0aCAgICAg"
    "PSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAgICAgcHl0aG9udyAg"
    "ICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFt"
    "ZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9"
    "IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBw"
    "eXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMu"
    "ZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1Nj"
    "cmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1"
    "dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3Ry"
    "KHB5dGhvbncpCiAgICAgICAgICAgICAgICAgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9k"
    "ZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5h"
    "X2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1F"
    "fSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAg"
    "ICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNo"
    "b3J0Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVl"
    "biBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJv"
    "bSBub3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAg"
    "Ik5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBi"
    "eSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05B"
    "TUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVt"
    "IGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5c"
    "biIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0"
    "dXAgd2luZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQg"
    "b3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAg"
    "IyDilIDilIAgRXhpdCBzZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0"
    "aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAg"
    "UGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2Vx"
    "dWVudCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vh"
    "cmx5X2xvZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5k"
    "b3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3Jl"
    "YXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygi"
    "W01BSU5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAj"
    "IERlZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1"
    "bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxzIHNo"
    "b3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJkYTogKF9l"
    "YXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9z"
    "Y2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2co"
    "IltUSU1FUl0gc3RhcnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkp"
    "KQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9z"
    "dGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVuY2UoKSkpCiAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVw"
    "X2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAg"
    "IyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUg"
    "dGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVw"
    "X3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3Vu"
    "ZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAg"
    "ICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwg"
    "X3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09ICJf"
    "X21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNr"
    "IGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50byBt"
    "b3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBhc3MgMyDi"
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
