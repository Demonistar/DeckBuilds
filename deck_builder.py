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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgRUNITyBERUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJ"
    "T04KIyBHZW5lcmF0ZWQgYnkgZGVja19idWlsZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGlu"
    "amVjdGVkIGZyb20gREVDS19URU1QTEFURSBoZWFkZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQ"
    "QVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMUEVSUywgU09VTkQgR0VORVJBVE9SIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKCmlt"
    "cG9ydCBzeXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCBtYXRoCmltcG9ydCB0aW1lCmlt"
    "cG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbXBvcnQgdGhyZWFkaW5nCmlt"
    "cG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0aW1lIGltcG9ydCBkYXRl"
    "dGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgK"
    "ZnJvbSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsLCBJdGVyYXRvcgoKIyDilIDilIAgRUFSTFkgQ1JB"
    "U0ggTE9HR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIEhvb2tzIGluIGJlZm9yZSBRdCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFM"
    "TCBvdXRwdXQgaW5jbHVkaW5nCiMgQysrIGxldmVsIFF0IG1lc3NhZ2VzLiBXcml0dGVuIHRvIFtE"
    "ZWNrTmFtZV0vbG9ncy9zdGFydHVwLmxvZwojIFRoaXMgc3RheXMgYWN0aXZlIGZvciB0aGUgbGlm"
    "ZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJMWV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlfTE9H"
    "X1BBVEg6IE9wdGlvbmFsW1BhdGhdID0gTm9uZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+"
    "IE5vbmU6CiAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzot"
    "M10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNnfSIKICAgIF9FQVJMWV9MT0dfTElORVMuYXBwZW5k"
    "KGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQogICAgaWYgX0VBUkxZX0xPR19QQVRI"
    "OgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigiYSIs"
    "IGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBmLndyaXRlKGxpbmUgKyAi"
    "XG4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCmRlZiBfaW5p"
    "dF9lYXJseV9sb2coYmFzZV9kaXI6IFBhdGgpIC0+IE5vbmU6CiAgICBnbG9iYWwgX0VBUkxZX0xP"
    "R19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIgLyAibG9ncyIKICAgIGxvZ19kaXIubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xPR19QQVRIID0gbG9nX2Rp"
    "ciAvIGYic3RhcnR1cF97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0u"
    "bG9nIgogICAgIyBGbHVzaCBidWZmZXJlZCBsaW5lcwogICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgu"
    "b3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIGxpbmUgaW4gX0VB"
    "UkxZX0xPR19MSU5FUzoKICAgICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKCmRlZiBfaW5z"
    "dGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKSAtPiBOb25lOgogICAgIiIiCiAgICBJbnRlcmNlcHQg"
    "QUxMIFF0IG1lc3NhZ2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2FybmluZ3MuCiAgICBUaGlzIGNh"
    "dGNoZXMgdGhlIFFUaHJlYWQgZGVzdHJveWVkIG1lc3NhZ2UgYXQgdGhlIHNvdXJjZSBhbmQgbG9n"
    "cyBpdAogICAgd2l0aCBhIGZ1bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cgZXhhY3RseSB3aGljaCB0"
    "aHJlYWQgYW5kIHdoZXJlLgogICAgIiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0"
    "Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNzYWdlSGFuZGxlciwgUXRNc2dUeXBlCiAgICAgICAgaW1w"
    "b3J0IHRyYWNlYmFjawoKICAgICAgICBkZWYgcXRfbWVzc2FnZV9oYW5kbGVyKG1zZ190eXBlLCBj"
    "b250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAgbGV2ZWwgPSB7CiAgICAgICAgICAgICAgICBR"
    "dE1zZ1R5cGUuUXREZWJ1Z01zZzogICAgIlFUX0RFQlVHIiwKICAgICAgICAgICAgICAgIFF0TXNn"
    "VHlwZS5RdEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUu"
    "UXRXYXJuaW5nTXNnOiAgIlFUX1dBUk5JTkciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlLlF0"
    "Q3JpdGljYWxNc2c6ICJRVF9DUklUSUNBTCIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRG"
    "YXRhbE1zZzogICAgIlFUX0ZBVEFMIiwKICAgICAgICAgICAgfS5nZXQobXNnX3R5cGUsICJRVF9V"
    "TktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0gIiIKICAgICAgICAgICAgaWYgY29udGV4"
    "dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmlsZX06e2Nv"
    "bnRleHQubGluZX1dIgoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2NhdGlv"
    "bn0ge21lc3NhZ2V9IikKCiAgICAgICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxv"
    "ZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAgICBpZiAiUVRocmVhZCIgaW4gbWVzc2FnZSBv"
    "ciAidGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBzdGFjayA9ICIi"
    "LmpvaW4odHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5X2xv"
    "ZyhmIltTVEFDSyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3Rh"
    "bGxNZXNzYWdlSGFuZGxlcihxdF9tZXNzYWdlX2hhbmRsZXIpCiAgICAgICAgX2Vhcmx5X2xvZygi"
    "W0lOSVRdIFF0IG1lc3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQogICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBlOgogICAgICAgIF9lYXJseV9sb2coZiJbSU5JVF0gQ291bGQgbm90IGluc3RhbGwgUXQg"
    "bWVzc2FnZSBoYW5kbGVyOiB7ZX0iKQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7REVDS19OQU1FfSBk"
    "ZWNrIHN0YXJ0aW5nIikKX2Vhcmx5X2xvZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNw"
    "bGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJsZX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFdvcmtp"
    "bmcgZGlyZWN0b3J5OiB7b3MuZ2V0Y3dkKCl9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBTY3JpcHQg"
    "bG9jYXRpb246IHtQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCl9IikKCiMg4pSA4pSAIE9QVElPTkFM"
    "IERFUEVOREVOQ1kgR1VBUkRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKUFNVVElM"
    "X09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElMX09LID0gVHJ1ZQog"
    "ICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFz"
    "IGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHN1dGlsIEZBSUxFRDoge2V9IikKCk5WTUxf"
    "T0sgPSBGYWxzZQpncHVfaGFuZGxlID0gTm9uZQp0cnk6CiAgICBpbXBvcnQgd2FybmluZ3MKICAg"
    "IHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToKICAgICAgICB3YXJuaW5ncy5zaW1wbGVm"
    "aWx0ZXIoImlnbm9yZSIpCiAgICAgICAgaW1wb3J0IHB5bnZtbAogICAgcHludm1sLm52bWxJbml0"
    "KCkKICAgIGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VHZXRDb3VudCgpCiAgICBpZiBjb3VudCA+"
    "IDA6CiAgICAgICAgZ3B1X2hhbmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxlQnlJbmRl"
    "eCgwKQogICAgICAgIE5WTUxfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHlu"
    "dm1sIE9LIOKAlCB7Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9l"
    "YXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgRkFJTEVEOiB7ZX0iKQoKVE9SQ0hfT0sgPSBGYWxz"
    "ZQp0cnk6CiAgICBpbXBvcnQgdG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRv"
    "TW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBf"
    "ZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9yY2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2Vw"
    "dCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHRvcmNoIEZBSUxF"
    "RCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2lu"
    "MzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRd"
    "IHdpbjMyY29tIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYi"
    "W0lNUE9SVF0gd2luMzJjb20gRkFJTEVEOiB7ZX0iKQoKV0lOU09VTkRfT0sgPSBGYWxzZQp0cnk6"
    "CiAgICBpbXBvcnQgd2luc291bmQKICAgIFdJTlNPVU5EX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xv"
    "ZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9l"
    "YXJseV9sb2coZiJbSU1QT1JUXSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKClBZ"
    "R0FNRV9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5taXhlci5p"
    "bml0KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHB5Z2Ft"
    "ZSBPSyIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBw"
    "eWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xFX09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZh"
    "bHNlICAjIGFsaWFzIHVzZWQgYnkgR29vZ2xlIHNlcnZpY2UgY2xhc3NlcwpHT09HTEVfSU1QT1JU"
    "X0VSUk9SID0gTm9uZQp0cnk6CiAgICBmcm9tIGdvb2dsZS5hdXRoLnRyYW5zcG9ydC5yZXF1ZXN0"
    "cyBpbXBvcnQgUmVxdWVzdCBhcyBHb29nbGVBdXRoUmVxdWVzdAogICAgZnJvbSBnb29nbGUub2F1"
    "dGgyLmNyZWRlbnRpYWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVkZW50aWFscwog"
    "ICAgZnJvbSBnb29nbGVfYXV0aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0YWxsZWRBcHBGbG93"
    "CiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5kaXNjb3ZlcnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2ds"
    "ZV9idWlsZAogICAgZnJvbSBnb29nbGVhcGljbGllbnQuZXJyb3JzIGltcG9ydCBIdHRwRXJyb3Ig"
    "YXMgR29vZ2xlSHR0cEVycm9yCiAgICBHT09HTEVfT0sgPSBUcnVlCiAgICBHT09HTEVfQVBJX09L"
    "ID0gVHJ1ZQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgX2U6CiAgICBHT09HTEVfSU1QT1JUX0VSUk9S"
    "ID0gc3RyKF9lKQogICAgR29vZ2xlSHR0cEVycm9yID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVT"
    "ID0gWwogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIiLAogICAg"
    "Imh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICJo"
    "dHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICJodHRwczovL3d3dy5n"
    "b29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCl0KR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cg"
    "PSAoCiAgICAiR29vZ2xlIHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3IgaW5jb21wYXRpYmxl"
    "IHdpdGggcmVxdWVzdGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29uIGFuZCByZWF1"
    "dGhvcml6ZSB3aXRoIHRoZSB1cGRhdGVkIHNjb3BlIGxpc3QuIgopCkRFRkFVTFRfR09PR0xFX0lB"
    "TkFfVElNRVpPTkUgPSAiQW1lcmljYS9DaGljYWdvIgpXSU5ET1dTX1RaX1RPX0lBTkEgPSB7CiAg"
    "ICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAiRWFzdGVy"
    "biBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRh"
    "cmQgVGltZSI6ICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAgICJNb3VudGFpbiBTdGFuZGFyZCBU"
    "aW1lIjogIkFtZXJpY2EvRGVudmVyIiwKfQoKCiMg4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFp"
    "bldpbmRvdywgUVdpZGdldCwgUVZCb3hMYXlvdXQsIFFIQm94TGF5b3V0LAogICAgUUdyaWRMYXlv"
    "dXQsIFFUZXh0RWRpdCwgUUxpbmVFZGl0LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBRRnJhbWUsCiAg"
    "ICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdpZGdldCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRl"
    "clZpZXcsCiAgICBRQWJzdHJhY3RJdGVtVmlldywgUVN0YWNrZWRXaWRnZXQsIFFUYWJXaWRnZXQs"
    "IFFMaXN0V2lkZ2V0LAogICAgUUxpc3RXaWRnZXRJdGVtLCBRU2l6ZVBvbGljeSwgUUNvbWJvQm94"
    "LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3NhZ2VCb3gsIFFEYXRlRWRpdCwgUURp"
    "YWxvZywgUUZvcm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNwbGl0dGVyLCBRSW5wdXREaWFs"
    "b2csIFFUb29sQnV0dG9uCikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFU"
    "aW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNpemUsIFFQb2ludCwgUVJlY3QKKQpmcm9t"
    "IFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQYWludGVyLCBRTGlu"
    "ZWFyR3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQYWludGVy"
    "UGF0aCwgUVRleHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9uCikK"
    "CiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUgICAgICA9IFVJ"
    "X1dJTkRPV19USVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4wIgpBUFBfRklMRU5BTUUgID0gZiJ7"
    "REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0wNCIK"
    "CiMg4pSA4pSAIENPTkZJRyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29uIGxpdmVz"
    "IG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcu"
    "IE5vdGhpbmcgaGFyZGNvZGVkIGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChf"
    "X2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudApDT05GSUdfUEFUSCA9IFNDUklQVF9ESVIgLyAiY29u"
    "ZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5vdyB0aGF0IHdlIGtub3cgd2hlcmUg"
    "d2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlfbG9nKGYiW0lOSVRdIFND"
    "UklQVF9ESVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIENPTkZJR19QQVRI"
    "ID0ge0NPTkZJR19QQVRIfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3Rz"
    "OiB7Q09ORklHX1BBVEguZXhpc3RzKCl9IikKCmRlZiBfZGVmYXVsdF9jb25maWcoKSAtPiBkaWN0"
    "OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBmaXJzdC1y"
    "dW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVybiB7"
    "CiAgICAgICAgImRlY2tfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjog"
    "QVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGlyIjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7"
    "CiAgICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8IG9sbGFtYSB8"
    "IGNsYXVkZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAgICMg"
    "bG9jYWwgbW9kZWwgZm9sZGVyIHBhdGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAg"
    "ICAgICAjIGUuZy4gImRvbHBoaW4tMi42LTdiIgogICAgICAgICAgICAiYXBpX2tleSI6ICIiLCAg"
    "ICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAgImFwaV90eXBlIjog"
    "IiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2Rl"
    "bCI6ICIiLCAgICAgICAgICAjIGUuZy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAg"
    "ICAgICAgImdvb2dsZSI6IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQVF9E"
    "SVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAi"
    "dG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwK"
    "ICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAg"
    "ICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20v"
    "YXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9LAogICAg"
    "ICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKFNDUklQVF9ESVIgLyAi"
    "RmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIgLyAic291bmRz"
    "IiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiks"
    "CiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAg"
    "ICAgICAgICAgICJzbCI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAg"
    "ICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxv"
    "Z3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6"
    "ICBzdHIoU0NSSVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0"
    "cihTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihT"
    "Q1JJUFRfRElSIC8gImdvb2dsZSIpLAogICAgICAgIH0sCiAgICAgICAgInNldHRpbmdzIjogewog"
    "ICAgICAgICAgICAiaWRsZV9lbmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAg"
    "ICAiaWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRsZV9tYXhf"
    "bWludXRlcyI6ICAgICAgICAgIDMwLAogICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWlu"
    "dXRlcyI6IDEwLAogICAgICAgICAgICAibWF4X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAog"
    "ICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRydWUsCiAgICAgICAgICAg"
    "ICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9p"
    "bmJvdW5kX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAgICAgICAiZ29vZ2xlX2xvb2tiYWNr"
    "X2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjog"
    "IDMwLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUsCiAgICB9CgpkZWYgbG9h"
    "ZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4gUmV0dXJucyBkZWZh"
    "dWx0IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdfUEFUSC5leGlz"
    "dHMoKToKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAgICAgICB3"
    "aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAg"
    "ICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJl"
    "dHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNhdmVfY29uZmlnKGNmZzogZGljdCkgLT4gTm9u"
    "ZToKICAgICIiIldyaXRlIGNvbmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1r"
    "ZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggQ09ORklHX1BBVEgub3Bl"
    "bigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywgZiwg"
    "aW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0IG1vZHVsZSBsZXZlbCDigJQgZXZlcnl0aGluZyBi"
    "ZWxvdyByZWFkcyBmcm9tIENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJseV9sb2coZiJbSU5J"
    "VF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtDRkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1v"
    "ZGVsX3R5cGU9e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZBVUxUX1BB"
    "VEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZh"
    "Y2VzIiwKICAgICJzb3VuZHMiOiAgIFNDUklQVF9ESVIgLyAic291bmRzIiwKICAgICJtZW1vcmll"
    "cyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAogICAgInNlc3Npb25zIjogU0NSSVBUX0RJUiAv"
    "ICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJUFRfRElSIC8gInNsIiwKICAgICJleHBv"
    "cnRzIjogIFNDUklQVF9ESVIgLyAiZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElS"
    "IC8gImxvZ3MiLAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAvICJiYWNrdXBzIiwKICAgICJw"
    "ZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVyc29uYXMiLAogICAgImdvb2dsZSI6ICAgU0NSSVBU"
    "X0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0aHMoKSAtPiBOb25l"
    "OgogICAgIiIiCiAgICBTZWxmLWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMgbWlzc2luZyBy"
    "ZXF1aXJlZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBub3JtYWxp"
    "emVzIGdvb2dsZSBjcmVkZW50aWFsL3Rva2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lzdHMg"
    "Y29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgogICAgY2hhbmdlZCA9IEZh"
    "bHNlCiAgICBwYXRocyA9IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwg"
    "ZGVmYXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBh"
    "dGhzLmdldChrZXkpOgogICAgICAgICAgICBwYXRoc1trZXldID0gc3RyKGRlZmF1bHRfcGF0aCkK"
    "ICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVfY2ZnID0gQ0ZHLnNldGRlZmF1"
    "bHQoImdvb2dsZSIsIHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xl"
    "Iiwgc3RyKF9ERUZBVUxUX1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0"
    "cihnb29nbGVfcm9vdCAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rv"
    "a2VuID0gc3RyKGdvb2dsZV9yb290IC8gInRva2VuLmpzb24iKQogICAgY3JlZHNfdmFsID0gc3Ry"
    "KGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSkuc3RyaXAoKQogICAgdG9rZW5fdmFs"
    "ID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tlbiIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBj"
    "cmVkc192YWwpIG9yICgiY29uZmlnIiBpbiBjcmVkc192YWwgYW5kICJnb29nbGVfY3JlZGVudGlh"
    "bHMuanNvbiIgaW4gY3JlZHNfdmFsKToKICAgICAgICBnb29nbGVfY2ZnWyJjcmVkZW50aWFscyJd"
    "ID0gZGVmYXVsdF9jcmVkcwogICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3QgdG9rZW5f"
    "dmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBkZWZhdWx0X3Rva2VuCiAgICAgICAg"
    "Y2hhbmdlZCA9IFRydWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29uZmlnKENGRykK"
    "CmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQg"
    "YSBwYXRoIGZyb20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3aXRoIHNhZmUg"
    "ZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBwYXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAg"
    "ICB2YWx1ZSA9IHBhdGhzLmdldChrZXkpCiAgICBpZiB2YWx1ZToKICAgICAgICByZXR1cm4gUGF0"
    "aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RFRkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZh"
    "bGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAgICAgICAgcmV0dXJu"
    "IGZhbGxiYWNrCiAgICByZXR1cm4gU0NSSVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdf"
    "cGF0aHMoKQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29u"
    "YSB0ZW1wbGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1BUlksIENfU0VDT05EQVJZ"
    "LCBDX0FDQ0VOVCwgQ19CRywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElN"
    "IGFyZSBpbmplY3RlZCBhdCB0aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIuCiMg"
    "RXZlcnl0aGluZyBiZWxvdyBpcyBkZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoK"
    "IyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xvcnMgdG8gbmFtZWQgcm9sZXMg"
    "dXNlZCB0aHJvdWdob3V0IHRoZSBVSQpDX0NSSU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAg"
    "ICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMsIGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9E"
    "SU0gPSBDX1BSSU1BUlkgKyAiODgiICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0bGUgYm9yZGVycwpD"
    "X0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMgbWFpbiBsYWJlbC90ZXh0L0FJIG91"
    "dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGltIHNlY29u"
    "ZGFyeQpDX0dPTERfQlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMgZW1waGFzaXMsIGhvdmVy"
    "IHN0YXRlcwpDX1NJTFZFUiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMgc2Vjb25kYXJ5IHRl"
    "eHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJTSAgPSBDX1RFWFRfRElNICsgIjg4IiAg"
    "IyBkaW0gc2Vjb25kYXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENfQkcgICAgICAgICAgICAgICAj"
    "IGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAgICAg"
    "ID0gQ19CRyAgICAgICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAg"
    "ICA9IENfUEFORUwgICAgICAgICAgICAjIHRlcnRpYXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVh"
    "ZHkgaW5qZWN0ZWQpCkNfQkxPT0QgICAgICAgPSAnIzhiMDAwMCcgICAgICAgICAgIyBlcnJvciBz"
    "dGF0ZXMsIGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAgICAgPSAnIzg4NTVjYycgICAg"
    "ICAgICAgIyBTWVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBMRV9ESU0gID0gJyMy"
    "YTA1MmEnICAgICAgICAgICMgZGltIHB1cnBsZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAg"
    "PSAnIzQ0YWE2NicgICAgICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVuaXZlcnNhbApDX0JM"
    "VUUgICAgICAgID0gJyM0NDg4Y2MnICAgICAgICAgICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNh"
    "bAoKIyBGb250IGhlbHBlciDigJQgZXh0cmFjdHMgcHJpbWFyeSBmb250IG5hbWUgZm9yIFFGb250"
    "KCkgY2FsbHMKREVDS19GT05UID0gVUlfRk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgp"
    "LnN0cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAoZm9yIGVtb3Rpb24gcmVj"
    "b3JkIGNoaXBzKQpFTU9USU9OX0NPTE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9y"
    "eSI6ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAgQ19HT0xELAogICAgImltcHJlc3NlZCI6"
    "ICBDX0dPTEQsCiAgICAicmVsaWV2ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6ICAgICAgQ19H"
    "T0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFuaWNrZWQiOiAgIENfQ1JJTVNP"
    "TiwKICAgICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2NrZWQiOiAgICBDX0NSSU1T"
    "T04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAgICJjb25jZXJuZWQiOiAgIiNjYzY2"
    "MjIiLAogICAgInNhZCI6ICAgICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRlZCI6ICIjY2M2"
    "NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAogICAgInBsb3R0aW5nIjogICBDX1BV"
    "UlBMRSwKICAgICJzdXNwaWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENfUFVS"
    "UExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJTFZFUiwKICAgICJhbGVydCI6ICAgICAgQ19TSUxW"
    "RVIsCiAgICAibmV1dHJhbCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09SQVRJVkUg"
    "Q09OU1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIFJVTkVTIGlzIHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29u"
    "YSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVTCgojIEZhY2UgaW1hZ2UgbWFwIOKAlCBwcmVmaXgg"
    "ZnJvbSBGQUNFX1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFjZXMKRkFDRV9G"
    "SUxFUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklY"
    "fV9OZXV0cmFsLnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVydC5w"
    "bmciLAogICAgImZvY3VzZWQiOiAgICBmIntGQUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAg"
    "InNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1fU211Zy5wbmciLAogICAgImNvbmNlcm5lZCI6"
    "ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIsCiAgICAic2FkIjogICAgICAgIGYie0ZB"
    "Q0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQiOiAgIGYie0ZBQ0VfUFJF"
    "RklYfV9SZWxpZXZlZC5wbmciLAogICAgImltcHJlc3NlZCI6ICBmIntGQUNFX1BSRUZJWH1fSW1w"
    "cmVzc2VkLnBuZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJFRklYfV9WaWN0b3J5LnBu"
    "ZyIsCiAgICAiaHVtaWxpYXRlZCI6IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlhdGVkLnBuZyIsCiAg"
    "ICAic3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNpb3VzLnBuZyIsCiAgICAicGFu"
    "aWNrZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0bW9kZSI6"
    "ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAgImFuZ3J5IjogICAgICBmIntG"
    "QUNFX1BSRUZJWH1fQW5ncnkucG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9"
    "X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9TaG9ja2Vk"
    "LnBuZyIsCiAgICAiaGFwcHkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmciLAogICAg"
    "ImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5LnBuZyIsCiAgICAiZmx1c3RlcmVk"
    "IjogIGYie0ZBQ0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAgZiJ7"
    "RkFDRV9QUkVGSVh9X0VudmlvdXMucG5nIiwKfQoKU0VOVElNRU5UX0xJU1QgPSAoCiAgICAibmV1"
    "dHJhbCwgYWxlcnQsIGZvY3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZlZCwgaW1w"
    "cmVzc2VkLCAiCiAgICAidmljdG9yeSwgaHVtaWxpYXRlZCwgc3VzcGljaW91cywgcGFuaWNrZWQs"
    "IGFuZ3J5LCBwbG90dGluZywgc2hvY2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZsdXN0ZXJl"
    "ZCwgZW52aW91cyIKKQoKIyDilIDilIAgU1lTVEVNIFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBw"
    "ZXJzb25hIHRlbXBsYXRlIGF0IHRvcCBvZiBmaWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRfQkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJv"
    "dmUgZnJvbSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3QgcmVkZWZpbmUg"
    "aXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBTVFlMRVNIRUVUIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9IGYiIiIKUU1haW5X"
    "aW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9y"
    "OiB7Q19HT0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRVGV4dEVk"
    "aXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtDX0dP"
    "TER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJh"
    "ZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNp"
    "emU6IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xv"
    "cjoge0NfQ1JJTVNPTl9ESU19Owp9fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6"
    "IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9O"
    "VF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxM3B4OwogICAgcGFkZGluZzogOHB4IDEycHg7Cn19"
    "ClFMaW5lRWRpdDpmb2N1cyB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07CiAgICBi"
    "YWNrZ3JvdW5kLWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNoQnV0dG9uIHt7CiAgICBiYWNrZ3Jv"
    "dW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZv"
    "bnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHggMjBweDsKICAgIGxldHRlci1zcGFjaW5n"
    "OiAycHg7Cn19ClFQdXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19D"
    "UklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNz"
    "ZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAgIGJvcmRlci1jb2xvcjog"
    "e0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7"
    "ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07"
    "CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0aWNhbCB7"
    "ewogICAgYmFja2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAgIGJvcmRlcjogbm9u"
    "ZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3JvbGxCYXI6OmhhbmRs"
    "ZTp2ZXJ0aWNhbDpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3Jv"
    "bGxCYXI6OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xsQmFyOjpzdWItbGluZTp2ZXJ0aWNhbCB7"
    "ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFUYWJXaWRnZXQ6OnBhbmUge3sKICAgIGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07Cn19ClFUYWJC"
    "YXI6OnRhYiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJ"
    "TX07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2"
    "cHggMTRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXpl"
    "OiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUVRhYkJhcjo6dGFiOnNlbGVjdGVk"
    "IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07"
    "CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRh"
    "Yjpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dPTERf"
    "RElNfTsKfX0KUVRhYmxlV2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgY29s"
    "b3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAg"
    "Z3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFN"
    "SUxZfTsKICAgIGZvbnQtc2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVk"
    "IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRF9C"
    "UklHSFR9Owp9fQpRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDoge0NfQkcz"
    "fTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsKICAgIHBhZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXIt"
    "c3BhY2luZzogMXB4Owp9fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "CiAgICBwYWRkaW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07"
    "Cn19ClFDb21ib0JveDo6ZHJvcC1kb3duIHt7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0Jv"
    "eCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlM"
    "WX07Cn19ClFMYWJlbCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9"
    "fQpRU3BsaXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgd2lkdGg6IDJweDsKfX0KIiIiCgojIOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0"
    "cmFwX2RpcmVjdG9yaWVzKCkgLT4gTm9uZToKICAgICIiIgogICAgQ3JlYXRlIGFsbCByZXF1aXJl"
    "ZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAgQ2FsbGVkIG9uIHN0YXJ0dXAg"
    "YmVmb3JlIGFueXRoaW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFs"
    "c28gbWlncmF0ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaWYg"
    "ZGV0ZWN0ZWQuCiAgICAiIiIKICAgIGRpcnMgPSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2VzIiks"
    "CiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "LAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIpLAog"
    "ICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAg"
    "ICAgICBjZmdfcGF0aCgiYmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAog"
    "ICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAi"
    "ZXhwb3J0cyIsCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAgIGQubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05MIGZpbGVzIGlm"
    "IHRoZXkgZG9uJ3QgZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQog"
    "ICAgZm9yIGZuYW1lIGluICgibWVzc2FnZXMuanNvbmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFz"
    "a3MuanNvbmwiLAogICAgICAgICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpzb25sIiwgInBl"
    "cnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAg"
    "ICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBl"
    "bmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2RpciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5h"
    "bWUgaW4gKCJzbF9zY2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIpOgogICAgICAgIGZw"
    "ID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAg"
    "IGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lvbnNfZGlyID0g"
    "Y2ZnX3BhdGgoInNlc3Npb25zIikKICAgIGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2lu"
    "ZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAgIGlkeC53cml0ZV90ZXh0"
    "KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgi"
    "KQoKICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qg"
    "c3RhdGVfcGF0aC5leGlzdHMoKToKICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShzdGF0ZV9w"
    "YXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImluZGV4Lmpzb24iCiAgICBpZiBu"
    "b3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAg"
    "ICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNz"
    "YWdlcyI6IDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBp"
    "bmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgIyBM"
    "ZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0cywg"
    "bWlncmF0ZSBmaWxlcwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVm"
    "YXVsdF9zdGF0ZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBl"
    "cnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJ"
    "T04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0dXAiOiBO"
    "b25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUi"
    "OiBOb25lLAogICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9y"
    "aWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjoge30sCiAgICAgICAgInZhbXBp"
    "cmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIsCiAgICB9CiAgICBwYXRoLndyaXRlX3Rl"
    "eHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKZGVmIF9t"
    "aWdyYXRlX2xlZ2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIKICAgIElmIG9sZCBEOlxcQUlc"
    "XE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdy"
    "YXRlIGZpbGVzIHRvIG5ldyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIKICAgICMgVHJ5IHRv"
    "IGZpbmQgb2xkIGxheW91dCByZWxhdGl2ZSB0byBtb2RlbCBwYXRoCiAgICBtb2RlbF9wYXRoID0g"
    "UGF0aChDRkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYgbm90IG1vZGVsX3BhdGgu"
    "ZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFyZW50"
    "IC8gZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRfcm9vdC5leGlzdHMoKToK"
    "ICAgICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJt"
    "ZW1vcmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZW1vcmll"
    "cy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAg"
    "ICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNvbmwiKSwKICAgICAgICAob2xk"
    "X3Jvb3QgLyAidGFza3MuanNvbmwiLCAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInN0YXRlLmpzb24iLCAgICAg"
    "ICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAgICAg"
    "KG9sZF9yb290IC8gImluZGV4Lmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3Jp"
    "ZXMiKSAvICJpbmRleC5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpzb25s"
    "IiwgICAgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9zY2Fucy5qc29ubCIpLAogICAgICAg"
    "IChvbGRfcm9vdCAvICJzbF9jb21tYW5kcy5qc29ubCIsICAgICAgICAgY2ZnX3BhdGgoInNsIikg"
    "LyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0"
    "b2tlbi5qc29uIiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsidG9rZW4iXSkpLAogICAgICAgIChv"
    "bGRfcm9vdCAvICJjb25maWciIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBQYXRoKENGR1siZ29vZ2xl"
    "Il1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAic291bmRzIiAvIGYie1NP"
    "VU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2Fs"
    "ZXJ0LndhdiIpLAogICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAgICAg"
    "IGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRy"
    "dWUpCiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwu"
    "Y29weTIoc3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICAgICAgcGFzcwoKICAgICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2Zh"
    "Y2VzID0gb2xkX3Jvb3QgLyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBjZmdfcGF0aCgiZmFjZXMi"
    "KQogICAgaWYgb2xkX2ZhY2VzLmV4aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2Vz"
    "Lmdsb2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19mYWNlcyAvIGltZy5uYW1lCiAg"
    "ICAgICAgICAgIGlmIG5vdCBkc3QuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAgICAgICAgIHNodXRpbC5j"
    "b3B5MihzdHIoaW1nKSwgc3RyKGRzdCkpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJl"
    "cGxhY2UobWljcm9zZWNvbmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFsdWU6IHN0"
    "cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgaWYgbm90IHZhbHVlOgogICAgICAgIHJldHVy"
    "biBOb25lCiAgICB2YWx1ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBpZiB2YWx1"
    "ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1h"
    "dCh2YWx1ZVs6LTFdKS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAgICAgICAgcmV0dXJu"
    "IGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgIHJldHVybiBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6IHNldFt0dXBs"
    "ZV0gPSBzZXQoKQoKCmRlZiBfbG9jYWxfdHppbmZvKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93"
    "KCkuYXN0aW1lem9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51dGMKCgpkZWYgbm93X2Zvcl9jb21w"
    "YXJlKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KF9sb2NhbF90emluZm8oKSkKCgpkZWYgbm9y"
    "bWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6"
    "CiAgICBpZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3Qg"
    "aXNpbnN0YW5jZShkdF92YWx1ZSwgZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBs"
    "b2NhbF90eiA9IF9sb2NhbF90emluZm8oKQogICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5vbmU6"
    "CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLnJlcGxhY2UodHppbmZvPWxvY2FsX3R6KQog"
    "ICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0KQogICAgICAgIGlmIGtleSBub3QgaW4gX0RB"
    "VEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUg"
    "dG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNvbnMu"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dF"
    "RC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3JtYWxpemVkID0gZHRf"
    "dmFsdWUuYXN0aW1lem9uZShsb2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIoZHRfdmFsdWUu"
    "dHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIsIGNvbnRleHQsIGR0X3R6X25hbWUpCiAgICBpZiBr"
    "ZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBhbmQgZHRfdHpfbmFtZSBu"
    "b3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAg"
    "ICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGlt"
    "ZSBmcm9tIHtkdF90el9uYW1lfSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dl"
    "bmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAgIF9EQVRFVElNRV9OT1JNQUxJ"
    "WkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2Vf"
    "aXNvX2Zvcl9jb21wYXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9y"
    "bWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKHBhcnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29u"
    "dGV4dCkKCgpkZWYgX3Rhc2tfZHVlX3NvcnRfa2V5KHRhc2s6IGRpY3QpOgogICAgZHVlID0gcGFy"
    "c2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9yICh0YXNrIG9y"
    "IHt9KS5nZXQoImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6"
    "CiAgICAgICAgcmV0dXJuICgxLCBkYXRldGltZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUu"
    "dXRjKSkKICAgIHJldHVybiAoMCwgZHVlLmFzdGltZXpvbmUodGltZXpvbmUudXRjKSwgKCh0YXNr"
    "IG9yIHt9KS5nZXQoInRleHQiKSBvciAiIikubG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9u"
    "KHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9IG1heCgwLCBpbnQoc2Vjb25kcykp"
    "CiAgICBkYXlzLCByZW0gPSBkaXZtb2QodG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJlbSA9IGRp"
    "dm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9kKHJlbSwgNjApCiAgICBw"
    "YXJ0cyA9IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5c31kIikKICAgIGlm"
    "IGhvdXJzOiAgIHBhcnRzLmFwcGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRz"
    "LmFwcGVuZChmInttaW51dGVzfW0iKQogICAgaWYgbm90IHBhcnRzOiBwYXJ0cy5hcHBlbmQoZiJ7"
    "c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10pCgojIOKUgOKUgCBNT09OIFBI"
    "QVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbiBtYXRoIOKAlCBkaXNwbGF5ZWQgbW9v"
    "biBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01PT04gPSBkYXRlKDIwMDAsIDEs"
    "IDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAt"
    "PiB0dXBsZVtmbG9hdCwgc3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2Zy"
    "YWN0aW9uLCBwaGFzZV9uYW1lLCBpbGx1bWluYXRpb25fcGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9u"
    "OiAwLjAgPSBuZXcgbW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcgbW9vbiBhZ2Fpbi4K"
    "ICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDigJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwg"
    "cGhhc2UuCiAgICAiIiIKICAgIGRheXMgID0gKGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9P"
    "TikuZGF5cwogICAgY3ljbGUgPSBkYXlzICUgX0xVTkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xl"
    "IC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8IDEuODU6ICAgbmFtZSA9ICJORVcgTU9P"
    "TiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVNDRU5UIgogICAg"
    "ZWxpZiBjeWNsZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNs"
    "ZSA8IDE0Ljc3OiAgbmFtZSA9ICJXQVhJTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAxNi42"
    "MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBjeWNsZSA8IDIyLjE1OiAgbmFtZSA9ICJX"
    "QU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAiTEFTVCBRVUFS"
    "VEVSIgogICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NFTlQiCgog"
    "ICAgIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9v"
    "bgogICAgaWxsdW1pbmF0aW9uID0gKDEgLSBtYXRoLmNvcygyICogbWF0aC5waSAqIHBoYXNlKSkg"
    "LyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkK"
    "CmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4gdHVwbGVbc3RyLCBzdHJdOgogICAgIiIiCiAgICBGZXRj"
    "aCBzdW5yaXNlL3N1bnNldCB2aWEgd3R0ci5pbiAoMy1zZWNvbmQgdGltZW91dCkuCiAgICBGYWxs"
    "cyBiYWNrIHRvIDA2OjAwIC8gMTg6MzAgb24gYW55IGZhaWx1cmUuCiAgICAiIiIKICAgIHRyeToK"
    "ICAgICAgICB1cmwgPSAiaHR0cHM6Ly93dHRyLmluLz9mb3JtYXQ9JVMrJXMiCiAgICAgICAgcmVx"
    "ID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCh1cmwsIGhlYWRlcnM9eyJVc2VyLUFnZW50IjogIk1v"
    "emlsbGEvNS4wIn0pCiAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0"
    "aW1lb3V0PTMpCiAgICAgICAgcGFydHMgPSByZXNwLnJlYWQoKS5kZWNvZGUoKS5zdHJpcCgpLnNw"
    "bGl0KCkKICAgICAgICBpZiBsZW4ocGFydHMpID09IDI6CiAgICAgICAgICAgIHJldHVybiBwYXJ0"
    "c1swXSwgcGFydHNbMV0KICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwogICAgcmV0"
    "dXJuICIwNjowMCIsICIxODozMCIKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5"
    "IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJMRUQ9VHJ1"
    "ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZXZlcnkgZ2VuZXJhdGlvbiBjYWxs"
    "LgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElORyBIT1VS"
    "IjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93"
    "ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30sICAgICAg"
    "ICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lMSUdIVCBG"
    "QURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIsICAgICAg"
    "InBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwx"
    "MCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVNUTEVT"
    "UyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTSwg"
    "ICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7MTYsMTd9"
    "LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FL"
    "RU5FRCI6ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAg"
    "ICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsiaG91cnMiOiB7MjIs"
    "MjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwKfQoKZGVm"
    "IGdldF92YW1waXJlX3N0YXRlKCkgLT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZh"
    "bXBpcmUgc3RhdGUgbmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRhdGV0aW1l"
    "Lm5vdygpLmhvdXIKICAgIGZvciBzdGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0"
    "ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJob3VycyJdOgogICAgICAgICAgICByZXR1cm4g"
    "c3RhdGVfbmFtZQogICAgcmV0dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2Nv"
    "bG9yKHN0YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5nZXQoc3Rh"
    "dGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xEKQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5n"
    "cygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsKICAgICAgICAiV0lUQ0hJTkcgSE9V"
    "UiI6ICAgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdodCBu"
    "b3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAgZiJ7REVDS19OQU1FfSByZW1haW5zIGZv"
    "Y3VzZWQgYW5kIGF2YWlsYWJsZSBmb3IgeW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRXSUxJR0hU"
    "IEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50aXZlIGFuZCB3YWl0aW5nIGZvciB5b3Vy"
    "IG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tfTkFNRX0g"
    "aXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVzcG9uc2l2ZS4iLAogICAgICAg"
    "ICJSRVNUTEVTUyBTTEVFUCI6ICBmIntERUNLX05BTUV9IGlzIGxpZ2h0bHkgaWRsZSBhbmQgY2Fu"
    "IHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElSUklORyI6ICAgICAgICBmIntE"
    "RUNLX05BTUV9IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGludWUuIiwKICAg"
    "ICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBmdWxseSBhY3RpdmUgYW5k"
    "IHByZXBhcmVkIHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ7REVDS19O"
    "QU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vzc2luZyB3aW5kb3cgYW5kIHN0YW5kaW5nIGJ5LiIs"
    "CiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0cl06CiAg"
    "ICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBp"
    "c2luc3RhbmNlKHByb3ZpZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVkLmtleXMoKSkgPT0gc2V0"
    "KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBzdHJdID0g"
    "e30KICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAg"
    "dmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFs"
    "LCBzdHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJh"
    "bF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFs"
    "LnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBfbmV1dHJh"
    "bF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6"
    "CiAgICAiIiIKICAgIEJ1aWxkIHRoZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBjb250ZXh0"
    "IHN0cmluZyBmb3Igc3lzdGVtIHByb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3JlIGV2"
    "ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3YXlzIGZyZXNoLgogICAgIiIiCiAg"
    "ICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUg"
    "PSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9IGdldF9t"
    "b29uX3BoYXNlKCkKICAgIG5vdyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCgog"
    "ICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkKICAgIGZsYXZvciA9IHN0"
    "YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYiXG5cbltD"
    "VVJSRU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAgICAgICBmIlZhbXBpcmUgc3RhdGU6IHtzdGF0"
    "ZX0uIHtmbGF2b3J9XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2lsbHVtfSUgaWxs"
    "dW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVDS19OQU1FfSBpbiB0aGlzIHN0"
    "YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIKICAgICkKCiMg"
    "4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5lcmF0aW9u"
    "LiBHb3RoaWMvdmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8gZmls"
    "ZXMgcmVxdWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2VzIFB5dGhvbidzIGJ1aWx0"
    "LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFj"
    "ayAoc3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRlZiBfc2lu"
    "ZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGguc2luKDIg"
    "KiBtYXRoLnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDogZmxvYXQp"
    "IC0+IGZsb2F0OgogICAgcmV0dXJuIDEuMCBpZiBfc2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEu"
    "MAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0"
    "dXJuIDIgKiAoKGZyZXEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQs"
    "IHNxdWFyZV9yOiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAgICAgICBmcmVxOiBmbG9hdCwgdDog"
    "ZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSArCiAg"
    "ICAgICAgICAgIHNxdWFyZV9yICogX3NxdWFyZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNhd19y"
    "ICogX3Nhd3Rvb3RoKGZyZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFsOiBpbnQs"
    "CiAgICAgICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAgICAgICBy"
    "ZWxlYXNlX2ZyYWM6IGZsb2F0ID0gMC4zKSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5bGUgYW1w"
    "bGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAvIG1heCgxLCB0b3RhbCkKICAgIGlmIHBv"
    "cyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwogICAgZWxp"
    "ZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAgICAgICAgcmV0dXJuICgxIC0gcG9zKSAvIHJl"
    "bGVhc2VfZnJhYwogICAgcmV0dXJuIDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDogUGF0aCwgYXVk"
    "aW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1"
    "ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0cihwYXRoKSwgInciKSBhcyBm"
    "OgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUsIDAsICJOT05FIiwgIm5v"
    "dCBjb21wcmVzc2VkIikpCiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAgICAgICAgIGYud3Jp"
    "dGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYgX2NsYW1wKHY6IGZsb2F0KSAtPiBp"
    "bnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyNzY3KSkpCgoj"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5kaW5nIG1p"
    "bm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9yIHRoaXJkIGJlbG93LiBT"
    "bG93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAi"
    "IiIKICAgIERlc2NlbmRpbmcgbWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwg"
    "cHVyZSBzaW5lIHdpdGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5nbGUgcmVz"
    "b25hbnQgYmVsbCBkeWluZyBpbiBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5vdGVz"
    "ID0gWwogICAgICAgICg0NDAuMCwgMC42KSwgICAjIEE0IOKAlCBmaXJzdCBzdHJpa2UKICAgICAg"
    "ICAoMzY5Ljk5LCAwLjkpLCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxvdyks"
    "IGxvbmdlciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3Ro"
    "IGluIG5vdGVzOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAg"
    "ICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBpIC8gX1NBTVBMRV9S"
    "QVRFCiAgICAgICAgICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5vIHNxdWFy"
    "ZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjcKICAgICAgICAgICAg"
    "IyBBZGQgYSBzdWJ0bGUgaGFybW9uaWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAgIHZhbCArPSBf"
    "c2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZlbG9wZSDigJQg"
    "YmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0"
    "dGFja19mcmFjPTAuMDEsIHJlbGVhc2VfZnJhYz0wLjcpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVu"
    "ZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAjIEJyaWVmIHNpbGVuY2UgYmV0d2Vl"
    "biBub3RlcwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjEpKToK"
    "ICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoK"
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBhc2NlbmRpbmcg"
    "bWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hv"
    "cmQpLCBmaW5hbCBub3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9u"
    "ZToKICAgICIiIgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBsaWtlIGEg"
    "c8OpYW5jZSBiZWdpbm5pbmcuCiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwgbm90"
    "ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICgyMjAuMCwg"
    "MC4yNSksICAgIyBBMwogICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhpcmQp"
    "CiAgICAgICAgKDMyOS42MywgMC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQwLjAsIDAu"
    "OCksICAgICMgQTQg4oCUIGZpbmFsLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3Ig"
    "aSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGlu"
    "dChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBsZW4obm90"
    "ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBq"
    "IC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC42CiAg"
    "ICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMgogICAgICAgICAgICBp"
    "ZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0"
    "YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNikKICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVs"
    "ZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYg"
    "KiAwLjQ1KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgICAgIGZvciBfIGluIHJh"
    "bmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAgICBhdWRpby5hcHBl"
    "bmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIE1PUkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29mdC4g"
    "TGlrZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5zb2xpY2l0ZWQgdHJhbnNtaXNz"
    "aW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZShw"
    "YXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCUIEQzLiBW"
    "ZXJ5IHF1aWV0LiBQcmVzZW5jZSBpbiB0aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMgICMg"
    "RDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3Ro"
    "KQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBp"
    "IC8gX1NBTVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjUKICAgICAg"
    "ICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBfZW52ZWxv"
    "cGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjc1KQogICAgICAg"
    "IGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93YXYocGF0"
    "aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEVSUk9SIOKAlCB0"
    "cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVmLiBTb21ldGhp"
    "bmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFsLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYg"
    "Z2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgogICAg"
    "VHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHkuCiAgICBU"
    "aGUgJ2RpYWJvbHVzIGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21wYXJlZCB0byBoZXIg"
    "b3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2EgPSAyNDYuOTQgICMgQjMKICAgIGZyZXFf"
    "YiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvdmUgQikKICAg"
    "IGxlbmd0aCA9IDAuNAogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAg"
    "YXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NB"
    "TVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlCBj"
    "cmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUoZnJlcV9hLCB0KSAqIDAuNSAr"
    "CiAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAg"
    "IF9zaW5lKGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGks"
    "IHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgIGF1ZGlv"
    "LmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVk"
    "aW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKAlCBkZXNj"
    "ZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9uCiMgUmV2ZXJzZSBvZiBzdGFydHVwLiBUaGUgc8OpYW5j"
    "ZSBlbmRzLiBQcmVzZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBn"
    "ZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiRGVz"
    "Y2VuZGluZyBBNCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdpbmcgaW50"
    "byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsICAwLjMpLCAgICMgQTQK"
    "ICAgICAgICAoMzI5LjYzLCAwLjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYzLCAwLjMpLCAgICMg"
    "QzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAgICMgQTMg4oCUIGZpbmFsLCBsb25nIGZhZGUKICAg"
    "IF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUo"
    "bm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAg"
    "ICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRF"
    "CiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41NQogICAgICAgICAgICB2YWwg"
    "Kz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9w"
    "ZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHJlbGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiAgICAgICAg"
    "ICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40KSkKICAgICAgICBmb3IgXyBp"
    "biByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAgICBhdWRpby5hcHBl"
    "bmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBB"
    "VEhTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgZ2V0X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAgcmV0dXJu"
    "IGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIKCmRlZiBi"
    "b290c3RyYXBfc291bmRzKCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNzaW5nIHNv"
    "dW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJhdG9ycyA9IHsKICAgICAgICAi"
    "YWxlcnQiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZuIG5hbWUg"
    "dW5jaGFuZ2VkCiAgICAgICAgInN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwK"
    "ICAgICAgICAiaWRsZSI6ICAgICBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAgICAgICJlcnJv"
    "ciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yLAogICAgICAgICJzaHV0ZG93biI6IGdlbmVy"
    "YXRlX21vcmdhbm5hX3NodXRkb3duLAogICAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBpbiBnZW5l"
    "cmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAg"
    "ICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "ICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVyYXRlIHtuYW1lfTog"
    "e2V9IikKCmRlZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4gTm9uZToKICAgICIiIgogICAgUGxh"
    "eSBhIG5hbWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5Z2FtZS5taXhlciBmaXJz"
    "dCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAgICBGYWxscyBiYWNrIHRvIHdpbnNvdW5k"
    "IG9uIFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvbi5iZWVwKCkgYXMgbGFz"
    "dCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJzb3VuZF9l"
    "bmFibGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgo"
    "bmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGlmIFBZ"
    "R0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1lLm1peGVyLlNv"
    "dW5kKHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBpZiBXSU5T"
    "T1VORF9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChzdHIo"
    "cGF0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3VuZC5TTkRfRklMRU5B"
    "TUUgfCB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFwcGxpY2F0"
    "aW9uLmJlZXAoKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKUgOKUgCBE"
    "RVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBjcmVhdGVfZGVza3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIKICAgIENy"
    "ZWF0ZSBhIGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhlIGRlY2sgLnB5IGZpbGUgdXNpbmcgcHl0aG9u"
    "dy5leGUuCiAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5LgogICAgIiIi"
    "CiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAg"
    "ICAgZGVza3RvcCA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRjdXRfcGF0"
    "aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKCiAgICAgICAgIyBweXRob253ID0gc2Ft"
    "ZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0aG9udyA9IFBhdGgo"
    "c3lzLmV4ZWN1dGFibGUpCiAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhv"
    "bi5leGUiOgogICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5l"
    "eGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6CiAgICAgICAgICAgIHB5dGhvbncg"
    "PSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3BhdGggPSBQYXRoKF9fZmlsZV9f"
    "KS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0Y2goIldT"
    "Y3JpcHQuU2hlbGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNob3J0"
    "Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBhdGggICAgID0gc3RyKHB5dGhvbncpCiAgICAg"
    "ICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAgc2MuV29ya2lu"
    "Z0RpcmVjdG9yeSA9IHN0cihkZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2NyaXB0aW9u"
    "ICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBuZXV0cmFs"
    "IGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0aCgi"
    "ZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIKICAgICAgICBpZiBpY29uX3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNlIFBO"
    "RyBkaXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICBzYy5zYXZlKCkKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3VsZCBub3QgY3JlYXRlIHNo"
    "b3J0Y3V0OiB7ZX0iKQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwgVVRJTElU"
    "SUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3RdOgogICAg"
    "IiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09O"
    "IGFycmF5cyB0b28uIiIiCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4g"
    "W10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlwKCkKICAg"
    "IGlmIG5vdCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3RhcnRzd2l0aCgiWyIp"
    "OgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0YSA9IGpzb24ubG9hZHMocmF3KQogICAgICAg"
    "ICAgICByZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNlKHgsIGRpY3QpXQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIGl0ZW1zID0gW10KICAg"
    "IGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAo"
    "KQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICBpZiBpc2luc3Rh"
    "bmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQob2JqKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZXR1cm4gaXRlbXMK"
    "CmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25lOgogICAgIiIi"
    "QXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJlbnQubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oImEiLCBl"
    "bmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhvYmosIGVu"
    "c3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgsIHJl"
    "Y29yZHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09OTCBmaWxl"
    "IHdpdGggYSBsaXN0IG9mIHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRz"
    "PVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1"
    "dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZi53cml0"
    "ZShqc29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZ"
    "V09SRCAvIE1FTU9SWSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApfU1RPUFdPUkRTID0gewogICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRo"
    "aXMiLCJmcm9tIiwieW91ciIsIndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIsIndoaWNoIiwid291"
    "bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwidGhlbiIsImludG8iLCJqdXN0IiwKICAgICJhYm91"
    "dCIsImxpa2UiLCJiZWNhdXNlIiwid2hpbGUiLCJjb3VsZCIsInNob3VsZCIsInRoZWlyIiwid2Vy"
    "ZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNhbnQi"
    "LCJ3b250Iiwib250byIsIm92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIsImFsc28iLCJzb21lIiwi"
    "bW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndhbnQiLCJ3aWxsIiwic2hhbGwiLAogICAgImFn"
    "YWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIsInVzZWQiLCJ1c2luZyIs"
    "InNhaWQiLAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhpbmciLCJz"
    "dHVmZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFjdF9rZXl3b3Jkcyh0ZXh0OiBz"
    "dHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtzdHJdOgogICAgdG9rZW5zID0gW3QubG93ZXIo"
    "KS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc3BsaXQoKV0KICAgIHNl"
    "ZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAgICAgIGlmIGxl"
    "bih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgIGlmIHQgbm90IGluIHNlZW46CiAgICAgICAgICAgIHNlZW4uYWRkKHQp"
    "CiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4ocmVzdWx0KSA+PSBs"
    "aW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9yZWNv"
    "cmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6"
    "CiAgICB0ID0gKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigpCiAgICBp"
    "ZiAiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiAiZHJlYW0i"
    "CiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29k"
    "ZSIsImVycm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhl"
    "ZCIsInJlc29sdmVkIiwic29sdXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICByZXR1cm4g"
    "InJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAgIGlmIGFueSh4IGluIHQgZm9y"
    "IHggaW4gKCJyZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICByZXR1cm4g"
    "InRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0"
    "IGlmIiwiZ2FtZSIsInByb2plY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAgaWYgYW55"
    "KHggaW4gdCBmb3IgeCBpbiAoInByZWZlciIsImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtlIiwiaSB3"
    "YW50IikpOgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIKICAgIHJldHVybiAiY29udmVyc2F0"
    "aW9uIgoKIyDilIDilIAgUEFTUyAxIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5leHQ6IFBhc3MgMiDigJQg"
    "V2lkZ2V0IENsYXNzZXMKIyAoR2F1Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdpZGdldCwg"
    "RW1vdGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVTdGF0ZVN0cmlwLCBDb2xsYXBz"
    "aWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAyOiBXSURH"
    "RVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRvIGZvcm0gdGhlIGZ1"
    "bGwgZGVjay4KIwojIFdpZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQgICAgICAg"
    "ICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUKIyAgIERyaXZl"
    "V2lkZ2V0ICAgICAgICAgIOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0IpCiMgICBT"
    "cGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNpcmNsZSBmb3IgQkxPT0QgYW5kIE1BTkEK"
    "IyAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlIHNo"
    "YWRvdwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlz"
    "dG9yeSBjaGlwcwojICAgTWlycm9yV2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1hZ2UgZGlzcGxh"
    "eSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAgIOKAlCBmdWxsLXdpZHRoIHRp"
    "bWUvbW9vbi9zdGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDigJQgd3Jh"
    "cHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRnZXQKIyAgIEhhcmR3YXJl"
    "UGFuZWwgICAgICAgIOKAlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoK"
    "IyDilIDilIAgR0FVR0UgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBHYXVnZVdpZGdldChR"
    "V2lkZ2V0KToKICAgICIiIgogICAgSG9yaXpvbnRhbCBmaWxsLWJhciBnYXVnZSB3aXRoIGdvdGhp"
    "YyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCksIHZhbHVlIHRleHQgKHRvcC1y"
    "aWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg4oaSIENf"
    "Q1JJTVNPTiDihpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2FjaGVzIG1heC4KICAgIFNob3dzICdO"
    "L0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygK"
    "ICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5pdDogc3RyID0gIiIs"
    "CiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjogc3RyID0gQ19H"
    "T0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYudW5pdCAg"
    "ICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92YWwKICAgICAgICBzZWxmLmNv"
    "bG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBz"
    "ZWxmLnNldE1pbmltdW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtSGVpZ2h0"
    "KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxvYXQsIGRpc3BsYXk6IHN0ciA9"
    "ICIiLCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3ZhbHVl"
    "ICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFp"
    "bGFibGUgPSBhdmFpbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBlbGlmIGRpc3BsYXk6CiAgICAgICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlz"
    "cGxheSA9IGYie3ZhbHVlOi4wZn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgog"
    "ICAgZGVmIHNldFVuYXZhaWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXZhaWxh"
    "YmxlID0gRmFsc2UKICAgICAgICBzZWxmLl9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAgIHNlbGYu"
    "dXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAg"
    "ICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVu"
    "ZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5o"
    "ZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91bmQKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcs"
    "IGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAg"
    "ICAgICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJlbAogICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQo"
    "REVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5kcmF3VGV4dCg2LCAx"
    "NCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihz"
    "ZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0pKQogICAgICAgIHAu"
    "c2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAg"
    "Zm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNl"
    "bGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2LCAxNCwgc2VsZi5fZGlz"
    "cGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAgICAgICAg"
    "YmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCBi"
    "YXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9y"
    "KENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9o"
    "IC0gMSkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92YWwgPiAwOgog"
    "ICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAg"
    "ZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAgICAjIENv"
    "bG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYg"
    "ZnJhYyA+IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIGZy"
    "YWMgPiAwLjY1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAg"
    "ICAgICAgIGdyYWQgPSBRTGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmlsbF93LCBi"
    "YXJfeSArIDEpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9y"
    "KS5kYXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJf"
    "Y29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJf"
    "aCAtIDIsIGdyYWQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBEUklWRSBXSURHRVQg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBEcml2"
    "ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0IsIGZpbGwg"
    "YmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRyaXZlcyB2aWEgcHN1dGlsLgogICAg"
    "IiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3RbZGljdF0gPSBbXQog"
    "ICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodCgzMCkKICAgICAgICBzZWxmLl9yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kcml2ZXMgPSBb"
    "XQogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0aW9ucyhhbGw9RmFs"
    "c2UpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdlID0gcHN1"
    "dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50KQogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjogcGFydC5k"
    "ZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "dXNlZCI6ICAgdXNhZ2UudXNlZCAgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "dG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "cGN0IjogICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAgIH0pCiAg"
    "ICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgICMg"
    "UmVzaXplIHRvIGZpdCBhbGwgZHJpdmVzCiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2VsZi5fZHJp"
    "dmVzKSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkKICAgICAgICBz"
    "ZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAg"
    "ICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVy"
    "LlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNl"
    "bGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykp"
    "CgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSkp"
    "CiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwgMTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2YWlsYWJs"
    "ZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHJvd19o"
    "ID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVzOgogICAg"
    "ICAgICAgICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAgICAgICAgICAgIHVzZWQgICA9IGRydlsi"
    "dXNlZCJdCiAgICAgICAgICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogICAgICAgICAgICBwY3Qg"
    "ICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAgICAgICAgIGxhYmVsID0g"
    "ZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAgICBwLnNldFBl"
    "bihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwg"
    "OCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkgKyAxMiwg"
    "bGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAgICBiYXJfeCA9IDYKICAgICAgICAg"
    "ICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICAgICAg"
    "YmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFy"
    "X2gsIFFDb2xvcihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkK"
    "ICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAx"
    "KQoKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBjdCkpCiAg"
    "ICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBDX0dPTERfRElNKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRp"
    "ZW50KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAgICAgICAg"
    "Z3JhZC5zZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAg"
    "ICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAgICAgIHAu"
    "ZmlsbFJlY3QoYmFyX3ggKyAxLCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoK"
    "ICAgICAgICAgICAgeSArPSByb3dfaAoKICAgICAgICBwLmVuZCgpCgogICAgZGVmIHJlZnJlc2go"
    "c2VsZikgLT4gTm9uZToKICAgICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1cGRhdGUgZHJp"
    "dmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgoKIyDilIDilIAgU1BIRVJFIFdJ"
    "REdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9vbCkgYW5k"
    "IE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEdsYXNzeSBzaGluZSBlZmZl"
    "Y3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYs"
    "CiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiAgICAgICAgY29s"
    "b3JfZW1wdHk6IHN0ciwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgICAgID0gbGFiZWwKICAgICAg"
    "ICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3JfZW1wdHkg"
    "PSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYuX2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpIg"
    "MS4wCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNldE1pbmlt"
    "dW1TaXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2VsZiwgZnJhY3Rpb246IGZsb2F0LCBh"
    "dmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZpbGwgICAgICA9"
    "IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBh"
    "dmFpbGFibGUKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwg"
    "ZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRS"
    "ZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGgg"
    "PSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIw"
    "KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIwKSAvLyAy"
    "ICsgNAoKICAgICAgICAjIERyb3Agc2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMCwgMCwgMCwgODApKQogICAgICAgIHAu"
    "ZHJhd0VsbGlwc2UoY3ggLSByICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAg"
    "ICAjIEJhc2UgY2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcihz"
    "ZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAg"
    "ICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAg"
    "IyBGaWxsIGZyb20gYm90dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5kIHNlbGYu"
    "X2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAg"
    "ICAgICAgICBjaXJjbGVfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0g"
    "ciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9h"
    "dChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYuX2ZpbGwg"
    "KiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgUVJlY3RGCiAg"
    "ICAgICAgICAgIGZpbGxfcmVjdCA9IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3ksIHIgKiAyLCBj"
    "eSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3BhdGggPSBRUGFpbnRlclBhdGgo"
    "KQogICAgICAgICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAgICAgIGNs"
    "aXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgpCgogICAgICAgICAgICBw"
    "LnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Io"
    "c2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkKQoKICAgICAg"
    "ICAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAogICAgICAg"
    "ICAgICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICog"
    "MC42KQogICAgICAgICkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1"
    "NSwgMjU1LCA1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUs"
    "IDI1NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5Q"
    "ZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICog"
    "MiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hT"
    "dHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVs"
    "bCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICog"
    "MikKCiAgICAgICAgIyBOL0Egb3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6"
    "CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5z"
    "ZXRGb250KFFGb250KCJDb3VyaWVyIE5ldyIsIDgpKQogICAgICAgICAgICBmbSA9IHAuZm9udE1l"
    "dHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAgICAgICAgICBwLmRyYXdUZXh0KGN4"
    "IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAvLyAyLCBjeSArIDQsIHR4dCkKCiAgICAgICAg"
    "IyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJlbF90ZXh0ID0gKHNlbGYubGFiZWwgaWYg"
    "c2VsZi5fYXZhaWxhYmxlIGVsc2UKICAgICAgICAgICAgICAgICAgICAgIGYie3NlbGYubGFiZWx9"
    "IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9maWxsICogMTAwKX0lIiBpZiBzZWxm"
    "Ll9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvcl9m"
    "dWxsKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQu"
    "Qm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcgPSBmbS5ob3Jp"
    "em9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBsdyAvLyAy"
    "LCBoIC0gMTAsIGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChE"
    "RUNLX0ZPTlQsIDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAg"
    "ICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0X3RleHQpCiAgICAgICAgICAgIHAuZHJh"
    "d1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5kKCkKCgoj"
    "IOKUgOKUgCBNT09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldpZGdldChR"
    "V2lkZ2V0KToKICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1cmF0ZSBz"
    "aGFkb3cuCgogICAgUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwgc3RhbmRh"
    "cmQpOgogICAgICAtIFdheGluZyAobmV34oaSZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUs"
    "IHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxsdW1pbmF0ZWQg"
    "bGVmdCBzaWRlLCBzaGFkb3cgb24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4g"
    "YmUgZmxpcHBlZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBiYWNrd2FyZHMKICAgIG9uIHRoaXMg"
    "bWFjaGluZS4gU2V0IE1PT05fU0hBRE9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAgICIi"
    "IgoKICAgICMg4oaQIEZMSVAgVEhJUyB0byBUcnVlIGlmIG1vb24gYXBwZWFycyBiYWNrd2FyZHMg"
    "ZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fcGhhc2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3LCAwLjU9"
    "ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgICAgICAgID0gIk5FVyBNT09OIgogICAg"
    "ICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxmLl9zdW5y"
    "aXNlICAgICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgICA9ICIxODozMCIKICAg"
    "ICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFz"
    "ZSgpICAgICAgICAgICMgcG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAg"
    "IHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBkZWYgX2ZldGNoKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9z"
    "dW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2Vs"
    "Zi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRo"
    "cmVhZCB2aWEgUVRpbWVyIOKAlCBuZXZlciBjYWxsCiAgICAgICAgICAgICMgc2VsZi51cGRhdGUo"
    "KSBkaXJlY3RseSBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQKICAgICAgICAgICAgUVRpbWVyLnNp"
    "bmdsZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9"
    "X2ZldGNoLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiB1cGRhdGVQaGFzZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX3BoYXNlLCBzZWxmLl9uYW1lLCBzZWxmLl9pbGx1bWluYXRp"
    "b24gPSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWlu"
    "dEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQog"
    "ICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykK"
    "ICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIgID0g"
    "bWluKHcsIGggLSAzNikgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0g"
    "KGggLSAzNikgLy8gMiArIDQKCiAgICAgICAgIyBCYWNrZ3JvdW5kIGNpcmNsZSAoc3BhY2UpCiAg"
    "ICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjAsIDEyLCAyOCkpCiAgICAgICAgcC5zZXRQZW4oUVBl"
    "bihRQ29sb3IoQ19TSUxWRVJfRElNKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIs"
    "IGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICBjeWNsZV9kYXkgPSBzZWxmLl9waGFzZSAq"
    "IF9MVU5BUl9DWUNMRQogICAgICAgIGlzX3dheGluZyA9IGN5Y2xlX2RheSA8IChfTFVOQVJfQ1lD"
    "TEUgLyAyKQoKICAgICAgICAjIEZ1bGwgbW9vbiBiYXNlIChtb29uIHN1cmZhY2UgY29sb3IpCiAg"
    "ICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uID4gMToKICAgICAgICAgICAgcC5zZXRQZW4oUXQu"
    "UGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIyMCwgMjEwLCAx"
    "ODUpKQogICAgICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAq"
    "IDIpCgogICAgICAgICMgU2hhZG93IGNhbGN1bGF0aW9uCiAgICAgICAgIyBpbGx1bWluYXRpb24g"
    "Z29lcyAw4oaSMTAwIHdheGluZywgMTAw4oaSMCB3YW5pbmcKICAgICAgICAjIHNoYWRvd19vZmZz"
    "ZXQgY29udHJvbHMgaG93IG11Y2ggb2YgdGhlIGNpcmNsZSB0aGUgc2hhZG93IGNvdmVycwogICAg"
    "ICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA8IDk5OgogICAgICAgICAgICAjIGZyYWN0aW9uIG9m"
    "IGRpYW1ldGVyIHRoZSBzaGFkb3cgZWxsaXBzZSBpcyBvZmZzZXQKICAgICAgICAgICAgaWxsdW1f"
    "ZnJhYyAgPSBzZWxmLl9pbGx1bWluYXRpb24gLyAxMDAuMAogICAgICAgICAgICBzaGFkb3dfZnJh"
    "YyA9IDEuMCAtIGlsbHVtX2ZyYWMKCiAgICAgICAgICAgICMgd2F4aW5nOiBpbGx1bWluYXRlZCBy"
    "aWdodCwgc2hhZG93IExFRlQKICAgICAgICAgICAgIyB3YW5pbmc6IGlsbHVtaW5hdGVkIGxlZnQs"
    "IHNoYWRvdyBSSUdIVAogICAgICAgICAgICAjIG9mZnNldCBtb3ZlcyB0aGUgc2hhZG93IGVsbGlw"
    "c2UgaG9yaXpvbnRhbGx5CiAgICAgICAgICAgIG9mZnNldCA9IGludChzaGFkb3dfZnJhYyAqIHIg"
    "KiAyKQoKICAgICAgICAgICAgaWYgTW9vbldpZGdldC5NT09OX1NIQURPV19GTElQOgogICAgICAg"
    "ICAgICAgICAgaXNfd2F4aW5nID0gbm90IGlzX3dheGluZwoKICAgICAgICAgICAgaWYgaXNfd2F4"
    "aW5nOgogICAgICAgICAgICAgICAgIyBTaGFkb3cgb24gbGVmdCBzaWRlCiAgICAgICAgICAgICAg"
    "ICBzaGFkb3dfeCA9IGN4IC0gciAtIG9mZnNldAogICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgIyBTaGFkb3cgb24gcmlnaHQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBj"
    "eCAtIHIgKyBvZmZzZXQKCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDE1LCA4LCAyMikp"
    "CiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQoKICAgICAgICAgICAgIyBE"
    "cmF3IHNoYWRvdyBlbGxpcHNlIOKAlCBjbGlwcGVkIHRvIG1vb24gY2lyY2xlCiAgICAgICAgICAg"
    "IG1vb25fcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIG1vb25fcGF0aC5hZGRFbGxp"
    "cHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgc2hhZG93"
    "X3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBzaGFkb3dfcGF0aC5hZGRFbGxpcHNl"
    "KGZsb2F0KHNoYWRvd194KSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIGNsaXBw"
    "ZWRfc2hhZG93ID0gbW9vbl9wYXRoLmludGVyc2VjdGVkKHNoYWRvd19wYXRoKQogICAgICAgICAg"
    "ICBwLmRyYXdQYXRoKGNsaXBwZWRfc2hhZG93KQoKICAgICAgICAjIFN1YnRsZSBzdXJmYWNlIGRl"
    "dGFpbCAoY3JhdGVycyBpbXBsaWVkIGJ5IHNsaWdodCB0ZXh0dXJlIGdyYWRpZW50KQogICAgICAg"
    "IHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KGZsb2F0KGN4IC0gciAqIDAuMiksIGZsb2F0KGN5IC0g"
    "ciAqIDAuMiksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDAuOCkp"
    "CiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI0MCwgMzApKQog"
    "ICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDIwMCwgMTgwLCAxNDAsIDUpKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4p"
    "CiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAg"
    "ICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkK"
    "ICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUiksIDEpKQogICAgICAgIHAuZHJh"
    "d0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBQaGFzZSBu"
    "YW1lIGJlbG93IG1vb24KICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19TSUxWRVIpKQogICAgICAg"
    "IHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAg"
    "ICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIG53ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2Uo"
    "c2VsZi5fbmFtZSkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbncgLy8gMiwgY3kgKyByICsgMTQs"
    "IHNlbGYuX25hbWUpCgogICAgICAgICMgSWxsdW1pbmF0aW9uIHBlcmNlbnRhZ2UKICAgICAgICBp"
    "bGx1bV9zdHIgPSBmIntzZWxmLl9pbGx1bWluYXRpb246LjBmfSUiCiAgICAgICAgcC5zZXRQZW4o"
    "UUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcp"
    "KQogICAgICAgIGZtMiA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIGl3ID0gZm0yLmhvcml6b250"
    "YWxBZHZhbmNlKGlsbHVtX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gaXcgLy8gMiwgY3kg"
    "KyByICsgMjQsIGlsbHVtX3N0cikKCiAgICAgICAgIyBTdW4gdGltZXMgYXQgdmVyeSBib3R0b20K"
    "ICAgICAgICBzdW5fc3RyID0gZiLimIAge3NlbGYuX3N1bnJpc2V9ICDimL0ge3NlbGYuX3N1bnNl"
    "dH0iCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgIHAuc2V0Rm9u"
    "dChRRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgIGZtMyA9IHAuZm9udE1ldHJpY3MoKQogICAg"
    "ICAgIHN3ID0gZm0zLmhvcml6b250YWxBZHZhbmNlKHN1bl9zdHIpCiAgICAgICAgcC5kcmF3VGV4"
    "dChjeCAtIHN3IC8vIDIsIGggLSAyLCBzdW5fc3RyKQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDi"
    "lIAgRU1PVElPTiBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRW1vdGlvbkJsb2NrKFFXaWRnZXQp"
    "OgogICAgIiIiCiAgICBDb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgcGFuZWwuCiAgICBTaG93"
    "cyBjb2xvci1jb2RlZCBjaGlwczog4pymIEVNT1RJT05fTkFNRSAgSEg6TU0KICAgIFNpdHMgbmV4"
    "dCB0byB0aGUgTWlycm9yIChmYWNlIHdpZGdldCkgaW4gdGhlIGJvdHRvbSBibG9jayByb3cuCiAg"
    "ICBDb2xsYXBzZXMgdG8ganVzdCB0aGUgaGVhZGVyIHN0cmlwLgogICAgIiIiCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICBzZWxmLl9oaXN0b3J5OiBsaXN0W3R1cGxlW3N0ciwgc3RyXV0gPSBbXSAgIyAo"
    "ZW1vdGlvbiwgdGltZXN0YW1wKQogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gVHJ1ZQogICAgICAg"
    "IHNlbGYuX21heF9lbnRyaWVzID0gMzAKCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "bGF5b3V0LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyBIZWFkZXIgcm93CiAgICAgICAgaGVhZGVy"
    "ID0gUVdpZGdldCgpCiAgICAgICAgaGVhZGVyLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIGhl"
    "YWRlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJv"
    "cmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAg"
    "ICBobCA9IFFIQm94TGF5b3V0KGhlYWRlcikKICAgICAgICBobC5zZXRDb250ZW50c01hcmdpbnMo"
    "NiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGxibCA9IFFMYWJl"
    "bCgi4p2nIEVNT1RJT05BTCBSRUNPUkQiKQogICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0"
    "dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldEZp"
    "eGVkU2l6ZSgxNiwgMTYpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRH07IGJv"
    "cmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX2J0bi5zZXRUZXh0KCLilrwiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KGxibCkKICAgICAgICBo"
    "bC5hZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX2J0bikKCiAg"
    "ICAgICAgIyBTY3JvbGwgYXJlYSBmb3IgZW1vdGlvbiBjaGlwcwogICAgICAgIHNlbGYuX3Njcm9s"
    "bCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxl"
    "KFRydWUpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxCYXJQb2xpY3ko"
    "CiAgICAgICAgICAgIFF0LlNjcm9sbEJhclBvbGljeS5TY3JvbGxCYXJBbHdheXNPZmYpCiAgICAg"
    "ICAgc2VsZi5fc2Nyb2xsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2NoaXBfY29u"
    "dGFpbmVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQgPSBRVkJveExheW91"
    "dChzZWxmLl9jaGlwX2NvbnRhaW5lcikKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5zZXRTcGFj"
    "aW5nKDIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgc2Vs"
    "Zi5fc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jaGlwX2NvbnRhaW5lcikKCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChoZWFkZXIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zY3JvbGwp"
    "CgogICAgICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKDEzMCkKCiAgICBkZWYgX3RvZ2dsZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAg"
    "ICAgICAgc2VsZi5fc2Nyb2xsLnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLilrwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIuKWsiIp"
    "CiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCgogICAgZGVmIGFkZEVtb3Rpb24oc2VsZiwg"
    "ZW1vdGlvbjogc3RyLCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgIGlmIG5v"
    "dCB0aW1lc3RhbXA6CiAgICAgICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0"
    "aW1lKCIlSDolTSIpCiAgICAgICAgc2VsZi5faGlzdG9yeS5pbnNlcnQoMCwgKGVtb3Rpb24sIHRp"
    "bWVzdGFtcCkpCiAgICAgICAgc2VsZi5faGlzdG9yeSA9IHNlbGYuX2hpc3RvcnlbOnNlbGYuX21h"
    "eF9lbnRyaWVzXQogICAgICAgIHNlbGYuX3JlYnVpbGRfY2hpcHMoKQoKICAgIGRlZiBfcmVidWls"
    "ZF9jaGlwcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2hpcHMgKGtl"
    "ZXAgdGhlIHN0cmV0Y2ggYXQgZW5kKQogICAgICAgIHdoaWxlIHNlbGYuX2NoaXBfbGF5b3V0LmNv"
    "dW50KCkgPiAxOgogICAgICAgICAgICBpdGVtID0gc2VsZi5fY2hpcF9sYXlvdXQudGFrZUF0KDAp"
    "CiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAgICAgICBpdGVtLndpZGdl"
    "dCgpLmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIGVtb3Rpb24sIHRzIGluIHNlbGYuX2hpc3Rv"
    "cnk6CiAgICAgICAgICAgIGNvbG9yID0gRU1PVElPTl9DT0xPUlMuZ2V0KGVtb3Rpb24sIENfVEVY"
    "VF9ESU0pCiAgICAgICAgICAgIGNoaXAgPSBRTGFiZWwoZiLinKYge2Vtb3Rpb24udXBwZXIoKX0g"
    "IHt0c30iKQogICAgICAgICAgICBjaGlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBm"
    "ImNvbG9yOiB7Y29sb3J9OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgIgogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmInBhZGRpbmc6IDFweCA0"
    "cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "Y2hpcF9sYXlvdXQuaW5zZXJ0V2lkZ2V0KAogICAgICAgICAgICAgICAgc2VsZi5fY2hpcF9sYXlv"
    "dXQuY291bnQoKSAtIDEsIGNoaXAKICAgICAgICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX2hpc3RvcnkuY2xlYXIoKQogICAgICAgIHNlbGYuX3JlYnVp"
    "bGRfY2hpcHMoKQoKCiMg4pSA4pSAIE1JUlJPUiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1p"
    "cnJvcldpZGdldChRTGFiZWwpOgogICAgIiIiCiAgICBGYWNlIGltYWdlIGRpc3BsYXkg4oCUICdU"
    "aGUgTWlycm9yJy4KICAgIER5bmFtaWNhbGx5IGxvYWRzIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5n"
    "IGZpbGVzIGZyb20gY29uZmlnIHBhdGhzLmZhY2VzLgogICAgQXV0by1tYXBzIGZpbGVuYW1lIHRv"
    "IGVtb3Rpb24ga2V5OgogICAgICAgIHtGQUNFX1BSRUZJWH1fQWxlcnQucG5nICAgICDihpIgImFs"
    "ZXJ0IgogICAgICAgIHtGQUNFX1BSRUZJWH1fU2FkX0NyeWluZy5wbmcg4oaSICJzYWQiCiAgICAg"
    "ICAge0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyDihpIgImNoZWF0bW9kZSIKICAgIEZhbGxz"
    "IGJhY2sgdG8gbmV1dHJhbCwgdGhlbiB0byBnb3RoaWMgcGxhY2Vob2xkZXIgaWYgbm8gaW1hZ2Vz"
    "IGZvdW5kLgogICAgTWlzc2luZyBmYWNlcyBkZWZhdWx0IHRvIG5ldXRyYWwg4oCUIG5vIGNyYXNo"
    "LCBubyBoYXJkY29kZWQgbGlzdCByZXF1aXJlZC4KICAgICIiIgoKICAgICMgU3BlY2lhbCBzdGVt"
    "IOKGkiBlbW90aW9uIGtleSBtYXBwaW5ncyAobG93ZXJjYXNlIHN0ZW0gYWZ0ZXIgTW9yZ2FubmFf"
    "KQogICAgX1NURU1fVE9fRU1PVElPTjogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAgICAgInNhZF9j"
    "cnlpbmciOiAgInNhZCIsCiAgICAgICAgImNoZWF0X21vZGUiOiAgImNoZWF0bW9kZSIsCiAgICB9"
    "CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9mYWNlc19kaXIgICA9IGNmZ19wYXRoKCJmYWNl"
    "cyIpCiAgICAgICAgc2VsZi5fY2FjaGU6IGRpY3Rbc3RyLCBRUGl4bWFwXSA9IHt9CiAgICAgICAg"
    "c2VsZi5fY3VycmVudCAgICAgPSAibmV1dHJhbCIKICAgICAgICBzZWxmLl93YXJuZWQ6IHNldFtz"
    "dHJdID0gc2V0KCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxNjAsIDE2MCkKICAgICAg"
    "ICBzZWxmLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAg"
    "IHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXIt"
    "cmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBz"
    "ZWxmLl9wcmVsb2FkKQoKICAgIGRlZiBfcHJlbG9hZChzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIFNjYW4gRmFjZXMvIGRpcmVjdG9yeSBmb3IgYWxsIHtGQUNFX1BSRUZJWH1fKi5w"
    "bmcgZmlsZXMuCiAgICAgICAgQnVpbGQgZW1vdGlvbuKGknBpeG1hcCBjYWNoZSBkeW5hbWljYWxs"
    "eS4KICAgICAgICBObyBoYXJkY29kZWQgbGlzdCDigJQgd2hhdGV2ZXIgaXMgaW4gdGhlIGZvbGRl"
    "ciBpcyBhdmFpbGFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2ZhY2VzX2Rp"
    "ci5leGlzdHMoKToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAg"
    "ICAgIHJldHVybgoKICAgICAgICBmb3IgaW1nX3BhdGggaW4gc2VsZi5fZmFjZXNfZGlyLmdsb2Io"
    "ZiJ7RkFDRV9QUkVGSVh9XyoucG5nIik6CiAgICAgICAgICAgICMgc3RlbSA9IGV2ZXJ5dGhpbmcg"
    "YWZ0ZXIgIk1vcmdhbm5hXyIgd2l0aG91dCAucG5nCiAgICAgICAgICAgIHJhd19zdGVtID0gaW1n"
    "X3BhdGguc3RlbVtsZW4oZiJ7RkFDRV9QUkVGSVh9XyIpOl0gICAgIyBlLmcuICJTYWRfQ3J5aW5n"
    "IgogICAgICAgICAgICBzdGVtX2xvd2VyID0gcmF3X3N0ZW0ubG93ZXIoKSAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIyAic2FkX2NyeWluZyIKCiAgICAgICAgICAgICMgTWFwIHNwZWNpYWwgc3Rl"
    "bXMgdG8gZW1vdGlvbiBrZXlzCiAgICAgICAgICAgIGVtb3Rpb24gPSBzZWxmLl9TVEVNX1RPX0VN"
    "T1RJT04uZ2V0KHN0ZW1fbG93ZXIsIHN0ZW1fbG93ZXIpCgogICAgICAgICAgICBweCA9IFFQaXht"
    "YXAoc3RyKGltZ19wYXRoKSkKICAgICAgICAgICAgaWYgbm90IHB4LmlzTnVsbCgpOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fY2FjaGVbZW1vdGlvbl0gPSBweAoKICAgICAgICBpZiBzZWxmLl9jYWNo"
    "ZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKCJuZXV0cmFsIikKICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKCiAgICBkZWYgX3JlbmRlcihzZWxmLCBm"
    "YWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgZmFjZSA9IGZhY2UubG93ZXIoKS5zdHJpcCgpCiAg"
    "ICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIGlmIGZhY2Ugbm90"
    "IGluIHNlbGYuX3dhcm5lZCBhbmQgZmFjZSAhPSAibmV1dHJhbCI6CiAgICAgICAgICAgICAgICBw"
    "cmludChmIltNSVJST1JdW1dBUk5dIEZhY2Ugbm90IGluIGNhY2hlOiB7ZmFjZX0g4oCUIHVzaW5n"
    "IG5ldXRyYWwiKQogICAgICAgICAgICAgICAgc2VsZi5fd2FybmVkLmFkZChmYWNlKQogICAgICAg"
    "ICAgICBmYWNlID0gIm5ldXRyYWwiCiAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fY2FjaGU6"
    "CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLl9jdXJyZW50ID0gZmFjZQogICAgICAgIHB4ID0gc2VsZi5fY2FjaGVbZmFj"
    "ZV0KICAgICAgICBzY2FsZWQgPSBweC5zY2FsZWQoCiAgICAgICAgICAgIHNlbGYud2lkdGgoKSAt"
    "IDQsCiAgICAgICAgICAgIHNlbGYuaGVpZ2h0KCkgLSA0LAogICAgICAgICAgICBRdC5Bc3BlY3RS"
    "YXRpb01vZGUuS2VlcEFzcGVjdFJhdGlvLAogICAgICAgICAgICBRdC5UcmFuc2Zvcm1hdGlvbk1v"
    "ZGUuU21vb3RoVHJhbnNmb3JtYXRpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuc2V0UGl4bWFw"
    "KHNjYWxlZCkKICAgICAgICBzZWxmLnNldFRleHQoIiIpCgogICAgZGVmIF9kcmF3X3BsYWNlaG9s"
    "ZGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jbGVhcigpCiAgICAgICAgc2VsZi5zZXRU"
    "ZXh0KCLinKZcbuKdp1xu4pymIikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiAy"
    "NHB4OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICBkZWYgc2V0X2ZhY2Uoc2Vs"
    "ZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIGxhbWJk"
    "YTogc2VsZi5fcmVuZGVyKGZhY2UpKQoKICAgIGRlZiByZXNpemVFdmVudChzZWxmLCBldmVudCkg"
    "LT4gTm9uZToKICAgICAgICBzdXBlcigpLnJlc2l6ZUV2ZW50KGV2ZW50KQogICAgICAgIGlmIHNl"
    "bGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoc2VsZi5fY3VycmVudCkKCiAgICBA"
    "cHJvcGVydHkKICAgIGRlZiBjdXJyZW50X2ZhY2Uoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVy"
    "biBzZWxmLl9jdXJyZW50CgoKIyDilIDilIAgVkFNUElSRSBTVEFURSBTVFJJUCDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgVmFtcGlyZVN0"
    "YXRlU3RyaXAoUVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93"
    "aW5nOgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5S"
    "SVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlz"
    "aWJsZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVy"
    "bmFsIFFUaW1lciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQg"
    "dmFtcGlyZSBzdGF0ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc3RhdGUg"
    "ICAgID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3RyICA9ICIiCiAg"
    "ICAgICAgc2VsZi5fc3VucmlzZSAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICA9"
    "ICIxODozMCIKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAgICAgc2Vs"
    "Zi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAg"
    "ICBzZWxmLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5j"
    "KCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5f"
    "dGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5f"
    "c3Vuc2V0ICA9IHNzCiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVh"
    "ZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUoKSBmcm9tCiAgICAgICAgICAgICMgYSBiYWNrZ3JvdW5k"
    "IHRocmVhZCwgaXQgY2F1c2VzIFFUaHJlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFk"
    "KHRhcmdldD1fZiwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAg"
    "ICAgICBzZWxmLl90aW1lX3N0ciAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQog"
    "ICAgICAgIF8sIHNlbGYuX21vb25fbmFtZSwgc2VsZi5faWxsdW0gPSBnZXRfbW9vbl9waGFzZSgp"
    "CiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAt"
    "PiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGlu"
    "dChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53"
    "aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNv"
    "bG9yKENfQkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3IgPSBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xv"
    "cihzZWxmLl9zdGF0ZSkKICAgICAgICB0ZXh0ID0gKAogICAgICAgICAgICBmIuKcpiAge3NlbGYu"
    "X3N0YXRlfSAg4oCiICB7c2VsZi5fdGltZV9zdHJ9ICDigKIgICIKICAgICAgICAgICAgZiLimIAg"
    "e3NlbGYuX3N1bnJpc2V9ICAgIOKYvSB7c2VsZi5fc3Vuc2V0fSAg4oCiICAiCiAgICAgICAgICAg"
    "IGYie3NlbGYuX21vb25fbmFtZX0gIHtzZWxmLl9pbGx1bTouMGZ9JSIKICAgICAgICApCgogICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDksIFFGb250LldlaWdodC5Cb2xkKSkKICAg"
    "ICAgICBwLnNldFBlbihRQ29sb3Ioc3RhdGVfY29sb3IpKQogICAgICAgIGZtID0gcC5mb250TWV0"
    "cmljcygpCiAgICAgICAgdHcgPSBmbS5ob3Jpem9udGFsQWR2YW5jZSh0ZXh0KQogICAgICAgIHAu"
    "ZHJhd1RleHQoKHcgLSB0dykgLy8gMiwgaCAtIDcsIHRleHQpCgogICAgICAgIHAuZW5kKCkKCgpj"
    "bGFzcyBNaW5pQ2FsZW5kYXJXaWRnZXQoUVdpZGdldCk6CiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIGxh"
    "eW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhlYWRl"
    "ciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZWFkZXIuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAs"
    "IDAsIDApCiAgICAgICAgc2VsZi5wcmV2X2J0biA9IFFQdXNoQnV0dG9uKCI8PCIpCiAgICAgICAg"
    "c2VsZi5uZXh0X2J0biA9IFFQdXNoQnV0dG9uKCI+PiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwg"
    "PSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0QWxpZ25tZW50KFF0LkFsaWdu"
    "bWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5wcmV2X2J0biwg"
    "c2VsZi5uZXh0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFdpZHRoKDM0KQogICAgICAg"
    "ICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "ICIKICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsg"
    "cGFkZGluZzogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZv"
    "bnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBoZWFk"
    "ZXIuYWRkV2lkZ2V0KHNlbGYucHJldl9idG4pCiAgICAgICAgaGVhZGVyLmFkZFdpZGdldChzZWxm"
    "Lm1vbnRoX2xibCwgMSkKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubmV4dF9idG4pCiAg"
    "ICAgICAgbGF5b3V0LmFkZExheW91dChoZWFkZXIpCgogICAgICAgIHNlbGYuY2FsZW5kYXIgPSBR"
    "Q2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0R3JpZFZpc2libGUoVHJ1"
    "ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFZlcnRpY2FsSGVhZGVyRm9ybWF0KFFDYWxlbmRh"
    "cldpZGdldC5WZXJ0aWNhbEhlYWRlckZvcm1hdC5Ob1ZlcnRpY2FsSGVhZGVyKQogICAgICAgIHNl"
    "bGYuY2FsZW5kYXIuc2V0TmF2aWdhdGlvbkJhclZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5j"
    "YWxlbmRhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdldCBRV2lk"
    "Z2V0e3thbHRlcm5hdGUtYmFja2dyb3VuZC1jb2xvcjp7Q19CRzJ9O319ICIKICAgICAgICAgICAg"
    "ZiJRVG9vbEJ1dHRvbnt7Y29sb3I6e0NfR09MRH07fX0gIgogICAgICAgICAgICBmIlFDYWxlbmRh"
    "cldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzplbmFibGVke3tiYWNrZ3JvdW5kOntDX0JHMn07IGNv"
    "bG9yOiNmZmZmZmY7ICIKICAgICAgICAgICAgZiJzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjp7"
    "Q19DUklNU09OX0RJTX07IHNlbGVjdGlvbi1jb2xvcjp7Q19URVhUfTsgZ3JpZGxpbmUtY29sb3I6"
    "e0NfQk9SREVSfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0"
    "ZW1WaWV3OmRpc2FibGVke3tjb2xvcjojOGI5NWExO319IgogICAgICAgICkKICAgICAgICBsYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuY2FsZW5kYXIpCgogICAgICAgIHNlbGYucHJldl9idG4uY2xpY2tl"
    "ZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxlbmRhci5zaG93UHJldmlvdXNNb250aCgpKQogICAg"
    "ICAgIHNlbGYubmV4dF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxlbmRhci5z"
    "aG93TmV4dE1vbnRoKCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5jdXJyZW50UGFnZUNoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl91cGRhdGVfbGFiZWwpCiAgICAgICAgc2VsZi5fdXBkYXRlX2xhYmVsKCkK"
    "ICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRzKCkKCiAgICBkZWYgX3VwZGF0ZV9sYWJlbChzZWxm"
    "LCAqYXJncyk6CiAgICAgICAgeWVhciA9IHNlbGYuY2FsZW5kYXIueWVhclNob3duKCkKICAgICAg"
    "ICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAgICAgc2VsZi5tb250aF9s"
    "Ymwuc2V0VGV4dChmIntkYXRlKHllYXIsIG1vbnRoLCAxKS5zdHJmdGltZSgnJUIgJVknKX0iKQog"
    "ICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfYXBwbHlfZm9ybWF0cyhzZWxm"
    "KToKICAgICAgICBiYXNlID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBiYXNlLnNldEZvcmVn"
    "cm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAgc2F0dXJkYXkgPSBRVGV4dENoYXJGb3Jt"
    "YXQoKQogICAgICAgIHNhdHVyZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQog"
    "ICAgICAgIHN1bmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc3VuZGF5LnNldEZvcmVn"
    "cm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRl"
    "eHRGb3JtYXQoUXQuRGF5T2ZXZWVrLk1vbmRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFy"
    "LnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UdWVzZGF5LCBiYXNlKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLldlZG5lc2Rh"
    "eSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRh"
    "eU9mV2Vlay5UaHVyc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlU"
    "ZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5GcmlkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRh"
    "ci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU2F0dXJkYXksIHNhdHVyZGF5KQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlN1"
    "bmRheSwgc3VuZGF5KQoKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQog"
    "ICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBmaXJzdF9k"
    "YXkgPSBRRGF0ZSh5ZWFyLCBtb250aCwgMSkKICAgICAgICBmb3IgZGF5IGluIHJhbmdlKDEsIGZp"
    "cnN0X2RheS5kYXlzSW5Nb250aCgpICsgMSk6CiAgICAgICAgICAgIGQgPSBRRGF0ZSh5ZWFyLCBt"
    "b250aCwgZGF5KQogICAgICAgICAgICBmbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgICAg"
    "ICB3ZWVrZGF5ID0gZC5kYXlPZldlZWsoKQogICAgICAgICAgICBpZiB3ZWVrZGF5ID09IFF0LkRh"
    "eU9mV2Vlay5TYXR1cmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5k"
    "KFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICAgICAgZWxpZiB3ZWVrZGF5ID09IFF0LkRheU9m"
    "V2Vlay5TdW5kYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoQ19CTE9PRCkpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9y"
    "ZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRE"
    "YXRlVGV4dEZvcm1hdChkLCBmbXQpCgogICAgICAgIHRvZGF5X2ZtdCA9IFFUZXh0Q2hhckZvcm1h"
    "dCgpCiAgICAgICAgdG9kYXlfZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIjNjhkMzlhIikpCiAg"
    "ICAgICAgdG9kYXlfZm10LnNldEJhY2tncm91bmQoUUNvbG9yKCIjMTYzODI1IikpCiAgICAgICAg"
    "dG9kYXlfZm10LnNldEZvbnRXZWlnaHQoUUZvbnQuV2VpZ2h0LkJvbGQpCiAgICAgICAgc2VsZi5j"
    "YWxlbmRhci5zZXREYXRlVGV4dEZvcm1hdChRRGF0ZS5jdXJyZW50RGF0ZSgpLCB0b2RheV9mbXQp"
    "CgoKIyDilIDilIAgQ09MTEFQU0lCTEUgQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIENvbGxhcHNpYmxlQmxvY2soUVdp"
    "ZGdldCk6CiAgICAiIiIKICAgIFdyYXBwZXIgdGhhdCBhZGRzIGEgY29sbGFwc2UvZXhwYW5kIHRv"
    "Z2dsZSB0byBhbnkgd2lkZ2V0LgogICAgQ29sbGFwc2VzIGhvcml6b250YWxseSAocmlnaHR3YXJk"
    "KSDigJQgaGlkZXMgY29udGVudCwga2VlcHMgaGVhZGVyIHN0cmlwLgogICAgSGVhZGVyIHNob3dz"
    "IGxhYmVsLiBUb2dnbGUgYnV0dG9uIG9uIHJpZ2h0IGVkZ2Ugb2YgaGVhZGVyLgoKICAgIFVzYWdl"
    "OgogICAgICAgIGJsb2NrID0gQ29sbGFwc2libGVCbG9jaygi4p2nIEJMT09EIiwgU3BoZXJlV2lk"
    "Z2V0KC4uLikpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChibG9jaykKICAgICIiIgoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAg"
    "ICAgICAgIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAg"
    "ICAgICAgICAgICBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQp"
    "CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lk"
    "dGggPSBtaW5fd2lkdGgKICAgICAgICBzZWxmLl9jb250ZW50ICAgPSBjb250ZW50CgogICAgICAg"
    "IG1haW4gPSBRVkJveExheW91dChzZWxmKQogICAgICAgIG1haW4uc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgbWFpbi5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVy"
    "CiAgICAgICAgc2VsZi5faGVhZGVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5faGVhZGVyLnNl"
    "dEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7"
    "Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItdG9wOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChzZWxmLl9o"
    "ZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAg"
    "aGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLl9sYmwgPSBRTGFiZWwobGFiZWwpCiAgICAg"
    "ICAgc2VsZi5fbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9"
    "OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fYnRuID0gUVRvb2xCdXR0b24oKQogICAg"
    "ICAgIHNlbGYuX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjog"
    "e0NfR09MRF9ESU19OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBzZWxmLl9idG4uY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2xibCkKICAg"
    "ICAgICBobC5hZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fYnRuKQoKICAg"
    "ICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9oZWFkZXIpCiAgICAgICAgbWFpbi5hZGRXaWRnZXQo"
    "c2VsZi5fY29udGVudCkKCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBfdG9n"
    "Z2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhw"
    "YW5kZWQKICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIF9hcHBseV9zdGF0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBh"
    "bmRlZCkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxz"
    "ZSAiPiIpCiAgICAgICAgaWYgc2VsZi5fZXhwYW5kZWQ6CiAgICAgICAgICAgIHNlbGYuc2V0TWlu"
    "aW11bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lk"
    "dGgoMTY3NzcyMTUpICAjIHVuY29uc3RyYWluZWQKICAgICAgICBlbHNlOgogICAgICAgICAgICAj"
    "IENvbGxhcHNlZDoganVzdCB0aGUgaGVhZGVyIHN0cmlwIChsYWJlbCArIGJ1dHRvbikKICAgICAg"
    "ICAgICAgY29sbGFwc2VkX3cgPSBzZWxmLl9oZWFkZXIuc2l6ZUhpbnQoKS53aWR0aCgpCiAgICAg"
    "ICAgICAgIHNlbGYuc2V0Rml4ZWRXaWR0aChtYXgoNjAsIGNvbGxhcHNlZF93KSkKICAgICAgICBz"
    "ZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwYXJlbnQgPSBzZWxmLnBhcmVudFdpZGdldCgp"
    "CiAgICAgICAgaWYgcGFyZW50IGFuZCBwYXJlbnQubGF5b3V0KCk6CiAgICAgICAgICAgIHBhcmVu"
    "dC5sYXlvdXQoKS5hY3RpdmF0ZSgpCgoKIyDilIDilIAgSEFSRFdBUkUgUEFORUwg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIEhhcmR3YXJlUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRoZSBzeXN0ZW1zIHJp"
    "Z2h0IHBhbmVsIGNvbnRlbnRzLgogICAgR3JvdXBzOiBzdGF0dXMgaW5mbywgZHJpdmUgYmFycywg"
    "Q1BVL1JBTSBnYXVnZXMsIEdQVS9WUkFNIGdhdWdlcywgR1BVIHRlbXAuCiAgICBSZXBvcnRzIGhh"
    "cmR3YXJlIGF2YWlsYWJpbGl0eSBpbiBEaWFnbm9zdGljcyBvbiBzdGFydHVwLgogICAgU2hvd3Mg"
    "Ti9BIGdyYWNlZnVsbHkgd2hlbiBkYXRhIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5fZGV0ZWN0X2hhcmR3YXJl"
    "KCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQs"
    "IDQpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgZGVmIHNlY3Rpb25fbGFi"
    "ZWwodGV4dDogc3RyKSAtPiBRTGFiZWw6CiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0ZXh0KQog"
    "ICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtD"
    "X0dPTER9OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXdlaWdodDogYm9s"
    "ZDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIGxibAoKICAgICAgICAjIOKUgOKU"
    "gCBTdGF0dXMgYmxvY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RBVFVTIikpCiAgICAgICAgc3RhdHVzX2ZyYW1l"
    "ID0gUUZyYW1lKCkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19QQU5FTH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRG"
    "aXhlZEhlaWdodCg4OCkKICAgICAgICBzZiA9IFFWQm94TGF5b3V0KHN0YXR1c19mcmFtZSkKICAg"
    "ICAgICBzZi5zZXRDb250ZW50c01hcmdpbnMoOCwgNCwgOCwgNCkKICAgICAgICBzZi5zZXRTcGFj"
    "aW5nKDIpCgogICAgICAgIHNlbGYubGJsX3N0YXR1cyAgPSBRTGFiZWwoIuKcpiBTVEFUVVM6IE9G"
    "RkxJTkUiKQogICAgICAgIHNlbGYubGJsX21vZGVsICAgPSBRTGFiZWwoIuKcpiBWRVNTRUw6IExP"
    "QURJTkcuLi4iKQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24gPSBRTGFiZWwoIuKcpiBTRVNTSU9O"
    "OiAwMDowMDowMCIpCiAgICAgICAgc2VsZi5sYmxfdG9rZW5zICA9IFFMYWJlbCgi4pymIFRPS0VO"
    "UzogMCIpCgogICAgICAgIGZvciBsYmwgaW4gKHNlbGYubGJsX3N0YXR1cywgc2VsZi5sYmxfbW9k"
    "ZWwsCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiwgc2VsZi5sYmxfdG9rZW5z"
    "KToKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBib3JkZXI6IG5vbmU7IgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHNmLmFkZFdpZGdldChsYmwpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c3RhdHVzX2ZyYW1lKQoKICAgICAgICAjIOKUgOKUgCBEcml2ZSBiYXJzIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi"
    "4p2nIFNUT1JBR0UiKSkKICAgICAgICBzZWxmLmRyaXZlX3dpZGdldCA9IERyaXZlV2lkZ2V0KCkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZHJpdmVfd2lkZ2V0KQoKICAgICAgICAjIOKU"
    "gOKUgCBDUFUgLyBSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFZJVEFMIEVTU0VOQ0UiKSkKICAgICAgICByYW1fY3B1ID0g"
    "UUdyaWRMYXlvdXQoKQogICAgICAgIHJhbV9jcHUuc2V0U3BhY2luZygzKQoKICAgICAgICBzZWxm"
    "LmdhdWdlX2NwdSAgPSBHYXVnZVdpZGdldCgiQ1BVIiwgICIlIiwgICAxMDAuMCwgQ19TSUxWRVIp"
    "CiAgICAgICAgc2VsZi5nYXVnZV9yYW0gID0gR2F1Z2VXaWRnZXQoIlJBTSIsICAiR0IiLCAgIDY0"
    "LjAsIENfR09MRF9ESU0pCiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9jcHUs"
    "IDAsIDApCiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9yYW0sIDAsIDEpCiAg"
    "ICAgICAgbGF5b3V0LmFkZExheW91dChyYW1fY3B1KQoKICAgICAgICAjIOKUgOKUgCBHUFUgLyBW"
    "UkFNIGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFi"
    "ZWwoIuKdpyBBUkNBTkUgUE9XRVIiKSkKICAgICAgICBncHVfdnJhbSA9IFFHcmlkTGF5b3V0KCkK"
    "ICAgICAgICBncHVfdnJhbS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1ICA9"
    "IEdhdWdlV2lkZ2V0KCJHUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1BVUlBMRSkKICAgICAgICBzZWxm"
    "LmdhdWdlX3ZyYW0gPSBHYXVnZVdpZGdldCgiVlJBTSIsICJHQiIsICAgIDguMCwgQ19DUklNU09O"
    "KQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdSwgIDAsIDApCiAgICAg"
    "ICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdnJhbSwgMCwgMSkKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGdwdV92cmFtKQoKICAgICAgICAjIOKUgOKUgCBHUFUgVGVtcCDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "Y3Rpb25fbGFiZWwoIuKdpyBJTkZFUk5BTCBIRUFUIikpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1w"
    "ID0gR2F1Z2VXaWRnZXQoIkdQVSBURU1QIiwgIsKwQyIsIDk1LjAsIENfQkxPT0QpCiAgICAgICAg"
    "c2VsZi5nYXVnZV90ZW1wLnNldE1heGltdW1IZWlnaHQoNjUpCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLmdhdWdlX3RlbXApCgogICAgICAgICMg4pSA4pSAIEdQVSBtYXN0ZXIgYmFyIChm"
    "dWxsIHdpZHRoKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBJTkZFUk5BTCBFTkdJTkUiKSkKICAg"
    "ICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIgPSBHYXVnZVdpZGdldCgiUlRYIiwgIiUiLCAxMDAu"
    "MCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRNYXhpbXVtSGVp"
    "Z2h0KDU1KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHVfbWFzdGVyKQoK"
    "ICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCgogICAgZGVmIF9kZXRlY3RfaGFyZHdhcmUoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDaGVjayB3aGF0IGhhcmR3YXJlIG1vbml0"
    "b3JpbmcgaXMgYXZhaWxhYmxlLgogICAgICAgIE1hcmsgdW5hdmFpbGFibGUgZ2F1Z2VzIGFwcHJv"
    "cHJpYXRlbHkuCiAgICAgICAgRGlhZ25vc3RpYyBtZXNzYWdlcyBjb2xsZWN0ZWQgZm9yIHRoZSBE"
    "aWFnbm9zdGljcyB0YWIuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlczog"
    "bGlzdFtzdHJdID0gW10KCiAgICAgICAgaWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgc2Vs"
    "Zi5nYXVnZV9jcHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5z"
    "ZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHN1dGlsIG5vdCBhdmFpbGFibGUg4oCUIENQVS9S"
    "QU0gZ2F1Z2VzIGRpc2FibGVkLiAiCiAgICAgICAgICAgICAgICAicGlwIGluc3RhbGwgcHN1dGls"
    "IHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX21lc3NhZ2VzLmFwcGVuZCgiW0hBUkRXQVJFXSBwc3V0aWwgT0sg4oCUIENQVS9SQU0g"
    "bW9uaXRvcmluZyBhY3RpdmUuIikKCiAgICAgICAgaWYgbm90IE5WTUxfT0s6CiAgICAgICAgICAg"
    "IHNlbGYuZ2F1Z2VfZ3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV92"
    "cmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFVuYXZhaWxhYmxl"
    "KCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAg"
    "ICAiW0hBUkRXQVJFXSBweW52bWwgbm90IGF2YWlsYWJsZSBvciBubyBOVklESUEgR1BVIGRldGVj"
    "dGVkIOKAlCAiCiAgICAgICAgICAgICAgICAiR1BVIGdhdWdlcyBkaXNhYmxlZC4gcGlwIGluc3Rh"
    "bGwgcHludm1sIHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZpY2VHZXROYW1l"
    "KGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToK"
    "ICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbSEFSRFdB"
    "UkVdIHB5bnZtbCBPSyDigJQgR1BVIGRldGVjdGVkOiB7bmFtZX0iCiAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICAgICAjIFVwZGF0ZSBtYXggVlJBTSBmcm9tIGFjdHVhbCBoYXJkd2FyZQog"
    "ICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9o"
    "YW5kbGUpCiAgICAgICAgICAgICAgICB0b3RhbF9nYiA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAg"
    "ICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5tYXhfdmFsID0gdG90YWxfZ2IKICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNz"
    "YWdlcy5hcHBlbmQoZiJbSEFSRFdBUkVdIHB5bnZtbCBlcnJvcjoge2V9IikKCiAgICBkZWYgdXBk"
    "YXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5"
    "IHNlY29uZCBmcm9tIHRoZSBzdGF0cyBRVGltZXIuCiAgICAgICAgUmVhZHMgaGFyZHdhcmUgYW5k"
    "IHVwZGF0ZXMgYWxsIGdhdWdlcy4KICAgICAgICAiIiIKICAgICAgICBpZiBQU1VUSUxfT0s6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNwdSA9IHBzdXRpbC5jcHVfcGVyY2VudCgp"
    "CiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRWYWx1ZShjcHUsIGYie2NwdTouMGZ9"
    "JSIsIGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICAgICAgICAgIG1lbSA9IHBzdXRpbC52aXJ0dWFs"
    "X21lbW9yeSgpCiAgICAgICAgICAgICAgICBydSAgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAg"
    "ICAgICAgICAgICBydCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxm"
    "LmdhdWdlX3JhbS5zZXRWYWx1ZShydSwgZiJ7cnU6LjFmfS97cnQ6LjBmfUdCIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV9yYW0ubWF4X3ZhbCA9IHJ0CiAgICAgICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9o"
    "YW5kbGU6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHV0aWwgICAgID0gcHludm1s"
    "Lm52bWxEZXZpY2VHZXRVdGlsaXphdGlvblJhdGVzKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAg"
    "ICBtZW1faW5mbyA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQog"
    "ICAgICAgICAgICAgICAgdGVtcCAgICAgPSBweW52bWwubnZtbERldmljZUdldFRlbXBlcmF0dXJl"
    "KAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ3B1X2hhbmRsZSwgcHludm1sLk5WTUxf"
    "VEVNUEVSQVRVUkVfR1BVKQoKICAgICAgICAgICAgICAgIGdwdV9wY3QgICA9IGZsb2F0KHV0aWwu"
    "Z3B1KQogICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtX2luZm8udXNlZCAgLyAxMDI0Kioz"
    "CiAgICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBtZW1faW5mby50b3RhbCAvIDEwMjQqKjMKCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRWYWx1ZShncHVfcGN0LCBmIntncHVfcGN0"
    "Oi4wZn0lIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJs"
    "ZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLnNldFZhbHVlKHZyYW1fdXNl"
    "ZCwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInt2cmFtX3VzZWQ6"
    "LjFmfS97dnJhbV90b3Q6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5z"
    "ZXRWYWx1ZShmbG9hdCh0ZW1wKSwgZiJ7dGVtcH3CsEMiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQoKICAgICAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZpY2VHZXROYW1lKGdwdV9o"
    "YW5kbGUpCiAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSAiR1BVIgoKICAg"
    "ICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRWYWx1ZSgKICAgICAgICAgICAg"
    "ICAgICAgICBncHVfcGN0LAogICAgICAgICAgICAgICAgICAgIGYie25hbWV9ICB7Z3B1X3BjdDou"
    "MGZ9JSAgIgogICAgICAgICAgICAgICAgICAgIGYiW3t2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6"
    "LjBmfUdCIFZSQU1dIiwKICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSwKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "IHBhc3MKCiAgICAgICAgIyBVcGRhdGUgZHJpdmUgYmFycyBldmVyeSAzMCBzZWNvbmRzIChub3Qg"
    "ZXZlcnkgdGljaykKICAgICAgICBpZiBub3QgaGFzYXR0cihzZWxmLCAiX2RyaXZlX3RpY2siKToK"
    "ICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICBzZWxmLl9kcml2ZV90aWNr"
    "ICs9IDEKICAgICAgICBpZiBzZWxmLl9kcml2ZV90aWNrID49IDMwOgogICAgICAgICAgICBzZWxm"
    "Ll9kcml2ZV90aWNrID0gMAogICAgICAgICAgICBzZWxmLmRyaXZlX3dpZGdldC5yZWZyZXNoKCkK"
    "CiAgICBkZWYgc2V0X3N0YXR1c19sYWJlbHMoc2VsZiwgc3RhdHVzOiBzdHIsIG1vZGVsOiBzdHIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgc2Vzc2lvbjogc3RyLCB0b2tlbnM6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLmxibF9zdGF0dXMuc2V0VGV4dChmIuKcpiBTVEFUVVM6IHtzdGF0"
    "dXN9IikKICAgICAgICBzZWxmLmxibF9tb2RlbC5zZXRUZXh0KGYi4pymIFZFU1NFTDoge21vZGVs"
    "fSIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbi5zZXRUZXh0KGYi4pymIFNFU1NJT046IHtzZXNz"
    "aW9ufSIpCiAgICAgICAgc2VsZi5sYmxfdG9rZW5zLnNldFRleHQoZiLinKYgVE9LRU5TOiB7dG9r"
    "ZW5zfSIpCgogICAgZGVmIGdldF9kaWFnbm9zdGljcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAg"
    "ICAgcmV0dXJuIGdldGF0dHIoc2VsZiwgIl9kaWFnX21lc3NhZ2VzIiwgW10pCgoKIyDilIDilIAg"
    "UEFTUyAyIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3aWRnZXQgY2xhc3NlcyBkZWZpbmVkLiBT"
    "eW50YXgtY2hlY2thYmxlIGluZGVwZW5kZW50bHkuCiMgTmV4dDogUGFzcyAzIOKAlCBXb3JrZXIg"
    "VGhyZWFkcwojIChEb2xwaGluV29ya2VyIHdpdGggc3RyZWFtaW5nLCBTZW50aW1lbnRXb3JrZXIs"
    "IElkbGVXb3JrZXIsIFNvdW5kV29ya2VyKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDi"
    "gJQgUEFTUyAzOiBXT1JLRVIgVEhSRUFEUwojCiMgV29ya2VycyBkZWZpbmVkIGhlcmU6CiMgICBM"
    "TE1BZGFwdG9yIChiYXNlICsgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yICsgT2xsYW1hQWRhcHRv"
    "ciArCiMgICAgICAgICAgICAgICBDbGF1ZGVBZGFwdG9yICsgT3BlbkFJQWRhcHRvcikKIyAgIFN0"
    "cmVhbWluZ1dvcmtlciAgIOKAlCBtYWluIGdlbmVyYXRpb24sIGVtaXRzIHRva2VucyBvbmUgYXQg"
    "YSB0aW1lCiMgICBTZW50aW1lbnRXb3JrZXIgICDigJQgY2xhc3NpZmllcyBlbW90aW9uIGZyb20g"
    "cmVzcG9uc2UgdGV4dAojICAgSWRsZVdvcmtlciAgICAgICAg4oCUIHVuc29saWNpdGVkIHRyYW5z"
    "bWlzc2lvbnMgZHVyaW5nIGlkbGUKIyAgIFNvdW5kV29ya2VyICAgICAgIOKAlCBwbGF5cyBzb3Vu"
    "ZHMgb2ZmIHRoZSBtYWluIHRocmVhZAojCiMgQUxMIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLiBO"
    "byBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZC4gRXZlci4KIyDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9y"
    "dCBhYmMKaW1wb3J0IGpzb24KaW1wb3J0IHVybGxpYi5yZXF1ZXN0CmltcG9ydCB1cmxsaWIuZXJy"
    "b3IKaW1wb3J0IGh0dHAuY2xpZW50CmZyb20gdHlwaW5nIGltcG9ydCBJdGVyYXRvcgoKCiMg4pSA"
    "4pSAIExMTSBBREFQVE9SIEJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExMTUFkYXB0b3IoYWJjLkFCQyk6CiAgICAiIiIK"
    "ICAgIEFic3RyYWN0IGJhc2UgZm9yIGFsbCBtb2RlbCBiYWNrZW5kcy4KICAgIFRoZSBkZWNrIGNh"
    "bGxzIHN0cmVhbSgpIG9yIGdlbmVyYXRlKCkg4oCUIG5ldmVyIGtub3dzIHdoaWNoIGJhY2tlbmQg"
    "aXMgYWN0aXZlLgogICAgIiIiCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIGlzX2Nv"
    "bm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgICIiIlJldHVybiBUcnVlIGlmIHRoZSBiYWNr"
    "ZW5kIGlzIHJlYWNoYWJsZS4iIiIKICAgICAgICAuLi4KCiAgICBAYWJjLmFic3RyYWN0bWV0aG9k"
    "CiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAg"
    "ICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhf"
    "bmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIi"
    "IgogICAgICAgIFlpZWxkIHJlc3BvbnNlIHRleHQgdG9rZW4tYnktdG9rZW4gKG9yIGNodW5rLWJ5"
    "LWNodW5rIGZvciBBUEkgYmFja2VuZHMpLgogICAgICAgIE11c3QgYmUgYSBnZW5lcmF0b3IuIE5l"
    "dmVyIGJsb2NrIGZvciB0aGUgZnVsbCByZXNwb25zZSBiZWZvcmUgeWllbGRpbmcuCiAgICAgICAg"
    "IiIiCiAgICAgICAgLi4uCgogICAgZGVmIGdlbmVyYXRlKAogICAgICAgIHNlbGYsCiAgICAgICAg"
    "cHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtk"
    "aWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgQ29udmVuaWVuY2Ugd3JhcHBlcjogY29sbGVjdCBhbGwgc3RyZWFt"
    "IHRva2VucyBpbnRvIG9uZSBzdHJpbmcuCiAgICAgICAgVXNlZCBmb3Igc2VudGltZW50IGNsYXNz"
    "aWZpY2F0aW9uIChzbWFsbCBib3VuZGVkIGNhbGxzIG9ubHkpLgogICAgICAgICIiIgogICAgICAg"
    "IHJldHVybiAiIi5qb2luKHNlbGYuc3RyZWFtKHByb21wdCwgc3lzdGVtLCBoaXN0b3J5LCBtYXhf"
    "bmV3X3Rva2VucykpCgogICAgZGVmIGJ1aWxkX2NoYXRtbF9wcm9tcHQoc2VsZiwgc3lzdGVtOiBz"
    "dHIsIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdXNl"
    "cl90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgQ2hh"
    "dE1MLWZvcm1hdCBwcm9tcHQgc3RyaW5nIGZvciBsb2NhbCBtb2RlbHMuCiAgICAgICAgaGlzdG9y"
    "eSA9IFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFudCIsICJjb250ZW50IjogIi4uLiJ9XQogICAg"
    "ICAgICIiIgogICAgICAgIHBhcnRzID0gW2YiPHxpbV9zdGFydHw+c3lzdGVtXG57c3lzdGVtfTx8"
    "aW1fZW5kfD4iXQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgcm9sZSAg"
    "ICA9IG1zZy5nZXQoInJvbGUiLCAidXNlciIpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0"
    "KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8Pnty"
    "b2xlfVxue2NvbnRlbnR9PHxpbV9lbmR8PiIpCiAgICAgICAgaWYgdXNlcl90ZXh0OgogICAgICAg"
    "ICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD51c2VyXG57dXNlcl90ZXh0fTx8aW1fZW5k"
    "fD4iKQogICAgICAgIHBhcnRzLmFwcGVuZCgiPHxpbV9zdGFydHw+YXNzaXN0YW50XG4iKQogICAg"
    "ICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgoKIyDilIDilIAgTE9DQUwgVFJBTlNGT1JNRVJT"
    "IEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExvY2FsVHJhbnNm"
    "b3JtZXJzQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgTG9hZHMgYSBIdWdnaW5nRmFj"
    "ZSBtb2RlbCBmcm9tIGEgbG9jYWwgZm9sZGVyLgogICAgU3RyZWFtaW5nOiB1c2VzIG1vZGVsLmdl"
    "bmVyYXRlKCkgd2l0aCBhIGN1c3RvbSBzdHJlYW1lciB0aGF0IHlpZWxkcyB0b2tlbnMuCiAgICBS"
    "ZXF1aXJlczogdG9yY2gsIHRyYW5zZm9ybWVycwogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIG1vZGVsX3BhdGg6IHN0cik6CiAgICAgICAgc2VsZi5fcGF0aCAgICAgID0gbW9kZWxfcGF0"
    "aAogICAgICAgIHNlbGYuX21vZGVsICAgICA9IE5vbmUKICAgICAgICBzZWxmLl90b2tlbml6ZXIg"
    "PSBOb25lCiAgICAgICAgc2VsZi5fbG9hZGVkICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9lcnJv"
    "ciAgICAgPSAiIgoKICAgIGRlZiBsb2FkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiCiAgICAg"
    "ICAgTG9hZCBtb2RlbCBhbmQgdG9rZW5pemVyLiBDYWxsIGZyb20gYSBiYWNrZ3JvdW5kIHRocmVh"
    "ZC4KICAgICAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiBub3QgVE9SQ0hfT0s6CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gInRvcmNoL3RyYW5zZm9y"
    "bWVycyBub3QgaW5zdGFsbGVkIgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxM"
    "TSwgQXV0b1Rva2VuaXplcgogICAgICAgICAgICBzZWxmLl90b2tlbml6ZXIgPSBBdXRvVG9rZW5p"
    "emVyLmZyb21fcHJldHJhaW5lZChzZWxmLl9wYXRoKQogICAgICAgICAgICBzZWxmLl9tb2RlbCA9"
    "IEF1dG9Nb2RlbEZvckNhdXNhbExNLmZyb21fcHJldHJhaW5lZCgKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3BhdGgsCiAgICAgICAgICAgICAgICB0b3JjaF9kdHlwZT10b3JjaC5mbG9hdDE2LAogICAg"
    "ICAgICAgICAgICAgZGV2aWNlX21hcD0iYXV0byIsCiAgICAgICAgICAgICAgICBsb3dfY3B1X21l"
    "bV91c2FnZT1UcnVlLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2xvYWRlZCA9IFRy"
    "dWUKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gc3RyKGUpCiAgICAgICAgICAgIHJldHVybiBGYWxz"
    "ZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGVycm9yKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1"
    "cm4gc2VsZi5fZXJyb3IKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX2xvYWRlZAoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAg"
    "ICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBs"
    "aXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0"
    "ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgU3RyZWFtcyB0b2tlbnMgdXNpbmcgdHJh"
    "bnNmb3JtZXJzIFRleHRJdGVyYXRvclN0cmVhbWVyLgogICAgICAgIFlpZWxkcyBkZWNvZGVkIHRl"
    "eHQgZnJhZ21lbnRzIGFzIHRoZXkgYXJlIGdlbmVyYXRlZC4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiBub3Qgc2VsZi5fbG9hZGVkOgogICAgICAgICAgICB5aWVsZCAiW0VSUk9SOiBtb2RlbCBub3Qg"
    "bG9hZGVkXSIKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgZnJv"
    "bSB0cmFuc2Zvcm1lcnMgaW1wb3J0IFRleHRJdGVyYXRvclN0cmVhbWVyCgogICAgICAgICAgICBm"
    "dWxsX3Byb21wdCA9IHNlbGYuYnVpbGRfY2hhdG1sX3Byb21wdChzeXN0ZW0sIGhpc3RvcnkpCiAg"
    "ICAgICAgICAgIGlmIHByb21wdDoKICAgICAgICAgICAgICAgICMgcHJvbXB0IGFscmVhZHkgaW5j"
    "bHVkZXMgdXNlciB0dXJuIGlmIGNhbGxlciBidWlsdCBpdAogICAgICAgICAgICAgICAgZnVsbF9w"
    "cm9tcHQgPSBwcm9tcHQKCiAgICAgICAgICAgIGlucHV0X2lkcyA9IHNlbGYuX3Rva2VuaXplcigK"
    "ICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0LCByZXR1cm5fdGVuc29ycz0icHQiCiAgICAgICAg"
    "ICAgICkuaW5wdXRfaWRzLnRvKCJjdWRhIikKCiAgICAgICAgICAgIGF0dGVudGlvbl9tYXNrID0g"
    "KGlucHV0X2lkcyAhPSBzZWxmLl90b2tlbml6ZXIucGFkX3Rva2VuX2lkKS5sb25nKCkKCiAgICAg"
    "ICAgICAgIHN0cmVhbWVyID0gVGV4dEl0ZXJhdG9yU3RyZWFtZXIoCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl90b2tlbml6ZXIsCiAgICAgICAgICAgICAgICBza2lwX3Byb21wdD1UcnVlLAogICAgICAg"
    "ICAgICAgICAgc2tpcF9zcGVjaWFsX3Rva2Vucz1UcnVlLAogICAgICAgICAgICApCgogICAgICAg"
    "ICAgICBnZW5fa3dhcmdzID0gewogICAgICAgICAgICAgICAgImlucHV0X2lkcyI6ICAgICAgaW5w"
    "dXRfaWRzLAogICAgICAgICAgICAgICAgImF0dGVudGlvbl9tYXNrIjogYXR0ZW50aW9uX21hc2ss"
    "CiAgICAgICAgICAgICAgICAibWF4X25ld190b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAg"
    "ICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6ICAgIDAuNywKICAgICAgICAgICAgICAgICJkb19zYW1w"
    "bGUiOiAgICAgIFRydWUsCiAgICAgICAgICAgICAgICAicGFkX3Rva2VuX2lkIjogICBzZWxmLl90"
    "b2tlbml6ZXIuZW9zX3Rva2VuX2lkLAogICAgICAgICAgICAgICAgInN0cmVhbWVyIjogICAgICAg"
    "c3RyZWFtZXIsCiAgICAgICAgICAgIH0KCiAgICAgICAgICAgICMgUnVuIGdlbmVyYXRpb24gaW4g"
    "YSBkYWVtb24gdGhyZWFkIOKAlCBzdHJlYW1lciB5aWVsZHMgaGVyZQogICAgICAgICAgICBnZW5f"
    "dGhyZWFkID0gdGhyZWFkaW5nLlRocmVhZCgKICAgICAgICAgICAgICAgIHRhcmdldD1zZWxmLl9t"
    "b2RlbC5nZW5lcmF0ZSwKICAgICAgICAgICAgICAgIGt3YXJncz1nZW5fa3dhcmdzLAogICAgICAg"
    "ICAgICAgICAgZGFlbW9uPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgZ2VuX3RocmVh"
    "ZC5zdGFydCgpCgogICAgICAgICAgICBmb3IgdG9rZW5fdGV4dCBpbiBzdHJlYW1lcjoKICAgICAg"
    "ICAgICAgICAgIHlpZWxkIHRva2VuX3RleHQKCiAgICAgICAgICAgIGdlbl90aHJlYWQuam9pbih0"
    "aW1lb3V0PTEyMCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5"
    "aWVsZCBmIlxuW0VSUk9SOiB7ZX1dIgoKCiMg4pSA4pSAIE9MTEFNQSBBREFQVE9SIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBPbGxhbWFBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBDb25uZWN0cyB0"
    "byBhIGxvY2FsbHkgcnVubmluZyBPbGxhbWEgaW5zdGFuY2UuCiAgICBTdHJlYW1pbmc6IHJlYWRz"
    "IE5ESlNPTiByZXNwb25zZSBjaHVua3MgZnJvbSBPbGxhbWEncyAvYXBpL2dlbmVyYXRlIGVuZHBv"
    "aW50LgogICAgT2xsYW1hIG11c3QgYmUgcnVubmluZyBhcyBhIHNlcnZpY2Ugb24gbG9jYWxob3N0"
    "OjExNDM0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX25hbWU6IHN0ciwg"
    "aG9zdDogc3RyID0gImxvY2FsaG9zdCIsIHBvcnQ6IGludCA9IDExNDM0KToKICAgICAgICBzZWxm"
    "Ll9tb2RlbCA9IG1vZGVsX25hbWUKICAgICAgICBzZWxmLl9iYXNlICA9IGYiaHR0cDovL3tob3N0"
    "fTp7cG9ydH0iCgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoZiJ7c2VsZi5fYmFz"
    "ZX0vYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3Blbihy"
    "ZXEsIHRpbWVvdXQ9MykKICAgICAgICAgICAgcmV0dXJuIHJlc3Auc3RhdHVzID09IDIwMAogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBz"
    "dHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06"
    "IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5z"
    "OiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAg"
    "UG9zdHMgdG8gL2FwaS9jaGF0IHdpdGggc3RyZWFtPVRydWUuCiAgICAgICAgT2xsYW1hIHJldHVy"
    "bnMgTkRKU09OIOKAlCBvbmUgSlNPTiBvYmplY3QgcGVyIGxpbmUuCiAgICAgICAgWWllbGRzIHRo"
    "ZSAnY29udGVudCcgZmllbGQgb2YgZWFjaCBhc3Npc3RhbnQgbWVzc2FnZSBjaHVuay4KICAgICAg"
    "ICAiIiIKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBz"
    "eXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMu"
    "YXBwZW5kKG1zZykKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAi"
    "bW9kZWwiOiAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMs"
    "CiAgICAgICAgICAgICJzdHJlYW0iOiAgIFRydWUsCiAgICAgICAgICAgICJvcHRpb25zIjogIHsi"
    "bnVtX3ByZWRpY3QiOiBtYXhfbmV3X3Rva2VucywgInRlbXBlcmF0dXJlIjogMC43fSwKICAgICAg"
    "ICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgPSB1cmxs"
    "aWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgZiJ7c2VsZi5fYmFzZX0vYXBpL2No"
    "YXQiLAogICAgICAgICAgICAgICAgZGF0YT1wYXlsb2FkLAogICAgICAgICAgICAgICAgaGVhZGVy"
    "cz17IkNvbnRlbnQtVHlwZSI6ICJhcHBsaWNhdGlvbi9qc29uIn0sCiAgICAgICAgICAgICAgICBt"
    "ZXRob2Q9IlBPU1QiLAogICAgICAgICAgICApCiAgICAgICAgICAgIHdpdGggdXJsbGliLnJlcXVl"
    "c3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MTIwKSBhcyByZXNwOgogICAgICAgICAgICAgICAgZm9y"
    "IHJhd19saW5lIGluIHJlc3A6CiAgICAgICAgICAgICAgICAgICAgbGluZSA9IHJhd19saW5lLmRl"
    "Y29kZSgidXRmLTgiKS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGxpbmU6CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGNodW5rID0gb2JqLmdldCgibWVzc2FnZSIsIHt9KS5nZXQoImNvbnRlbnQi"
    "LCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgaWYgY2h1bms6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICB5aWVsZCBjaHVuawogICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0"
    "KCJkb25lIiwgRmFsc2UpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAg"
    "ICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPbGxhbWEg4oCUIHtlfV0iCgoKIyDilIDilIAgQ0xBVURF"
    "IEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIENsYXVkZUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAi"
    "IiIKICAgIFN0cmVhbXMgZnJvbSBBbnRocm9waWMncyBDbGF1ZGUgQVBJIHVzaW5nIFNTRSAoc2Vy"
    "dmVyLXNlbnQgZXZlbnRzKS4KICAgIFJlcXVpcmVzIGFuIEFQSSBrZXkgaW4gY29uZmlnLgogICAg"
    "IiIiCgogICAgX0FQSV9VUkwgPSAiYXBpLmFudGhyb3BpYy5jb20iCiAgICBfUEFUSCAgICA9ICIv"
    "djEvbWVzc2FnZXMiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6"
    "IHN0ciA9ICJjbGF1ZGUtc29ubmV0LTQtNiIpOgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tl"
    "eQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYp"
    "IC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0o"
    "CiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwK"
    "ICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQg"
    "PSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbXQogICAg"
    "ICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsKICAg"
    "ICAgICAgICAgICAgICJyb2xlIjogICAgbXNnWyJyb2xlIl0sCiAgICAgICAgICAgICAgICAiY29u"
    "dGVudCI6IG1zZ1siY29udGVudCJdLAogICAgICAgICAgICB9KQoKICAgICAgICBwYXlsb2FkID0g"
    "anNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgc2VsZi5fbW9kZWwsCiAgICAg"
    "ICAgICAgICJtYXhfdG9rZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJzeXN0ZW0i"
    "OiAgICAgc3lzdGVtLAogICAgICAgICAgICAibWVzc2FnZXMiOiAgIG1lc3NhZ2VzLAogICAgICAg"
    "ICAgICAic3RyZWFtIjogICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAg"
    "ICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJ4LWFwaS1rZXkiOiAgICAgICAgIHNlbGYuX2tl"
    "eSwKICAgICAgICAgICAgImFudGhyb3BpYy12ZXJzaW9uIjogIjIwMjMtMDYtMDEiLAogICAgICAg"
    "ICAgICAiY29udGVudC10eXBlIjogICAgICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGNvbm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rp"
    "b24oc2VsZi5fQVBJX1VSTCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNvbm4ucmVxdWVzdCgi"
    "UE9TVCIsIHNlbGYuX1BBVEgsIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAg"
    "ICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1"
    "cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYt"
    "OCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBDbGF1ZGUgQVBJIHtyZXNwLnN0"
    "YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAg"
    "ICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBj"
    "aHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAg"
    "ICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNv"
    "ZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAg"
    "ICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAg"
    "ICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBs"
    "aW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3Ry"
    "ID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9"
    "PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAg"
    "ICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29u"
    "LmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgi"
    "dHlwZSIpID09ICJjb250ZW50X2Jsb2NrX2RlbHRhIjoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICB0ZXh0ID0gb2JqLmdldCgiZGVsdGEiLCB7fSkuZ2V0KCJ0ZXh0IiwgIiIpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQg"
    "anNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBwYXNzCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9S"
    "OiBDbGF1ZGUg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgY29ubi5jbG9zZSgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgT1BFTkFJIEFEQVBUT1Ig4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIE9wZW5BSUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBP"
    "cGVuQUkncyBjaGF0IGNvbXBsZXRpb25zIEFQSS4KICAgIFNhbWUgU1NFIHBhdHRlcm4gYXMgQ2xh"
    "dWRlLiBDb21wYXRpYmxlIHdpdGggYW55IE9wZW5BSS1jb21wYXRpYmxlIGVuZHBvaW50LgogICAg"
    "IiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJn"
    "cHQtNG8iLAogICAgICAgICAgICAgICAgIGhvc3Q6IHN0ciA9ICJhcGkub3BlbmFpLmNvbSIpOgog"
    "ICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwK"
    "ICAgICAgICBzZWxmLl9ob3N0ICA9IGhvc3QKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+"
    "IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAg"
    "ICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAg"
    "ICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1"
    "MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjog"
    "InN5c3RlbSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6"
    "CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiBtc2dbInJvbGUiXSwgImNvbnRl"
    "bnQiOiBtc2dbImNvbnRlbnQiXX0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAg"
    "ICAgICAgICAgIm1vZGVsIjogICAgICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtZXNzYWdl"
    "cyI6ICAgIG1lc3NhZ2VzLAogICAgICAgICAgICAibWF4X3Rva2VucyI6ICBtYXhfbmV3X3Rva2Vu"
    "cywKICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogMC43LAogICAgICAgICAgICAic3RyZWFtIjog"
    "ICAgICBUcnVlLAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0g"
    "ewogICAgICAgICAgICAiQXV0aG9yaXphdGlvbiI6IGYiQmVhcmVyIHtzZWxmLl9rZXl9IiwKICAg"
    "ICAgICAgICAgIkNvbnRlbnQtVHlwZSI6ICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGNvbm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rp"
    "b24oc2VsZi5faG9zdCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNvbm4ucmVxdWVzdCgiUE9T"
    "VCIsICIvdjEvY2hhdC9jb21wbGV0aW9ucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICBib2R5"
    "PXBheWxvYWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVz"
    "cG9uc2UoKQoKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAg"
    "ICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgeWll"
    "bGQgZiJcbltFUlJPUjogT3BlbkFJIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1d"
    "IgogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAg"
    "ICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQog"
    "ICAgICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAg"
    "ICAgICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAg"
    "ICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZm"
    "ZXIgPSBidWZmZXIuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGlu"
    "ZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIp"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhkYXRhX3N0cikKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSAob2JqLmdldCgiY2hvaWNlcyIsIFt7fV0pWzBd"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImRlbHRhIiwge30p"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImNvbnRlbnQiLCAi"
    "IikpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0"
    "IChqc29uLkpTT05EZWNvZGVFcnJvciwgSW5kZXhFcnJvcik6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5"
    "aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkg4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29ubi5jbG9zZSgpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgQURBUFRPUiBGQUNU"
    "T1JZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApkZWYgYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpIC0+IExMTUFkYXB0b3I6"
    "CiAgICAiIiIKICAgIEJ1aWxkIHRoZSBjb3JyZWN0IExMTUFkYXB0b3IgZnJvbSBDRkdbJ21vZGVs"
    "J10uCiAgICBDYWxsZWQgb25jZSBvbiBzdGFydHVwIGJ5IHRoZSBtb2RlbCBsb2FkZXIgdGhyZWFk"
    "LgogICAgIiIiCiAgICBtID0gQ0ZHLmdldCgibW9kZWwiLCB7fSkKICAgIHQgPSBtLmdldCgidHlw"
    "ZSIsICJsb2NhbCIpCgogICAgaWYgdCA9PSAib2xsYW1hIjoKICAgICAgICByZXR1cm4gT2xsYW1h"
    "QWRhcHRvcigKICAgICAgICAgICAgbW9kZWxfbmFtZT1tLmdldCgib2xsYW1hX21vZGVsIiwgImRv"
    "bHBoaW4tMi42LTdiIikKICAgICAgICApCiAgICBlbGlmIHQgPT0gImNsYXVkZSI6CiAgICAgICAg"
    "cmV0dXJuIENsYXVkZUFkYXB0b3IoCiAgICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXki"
    "LCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwiLCAiY2xhdWRlLXNvbm5l"
    "dC00LTYiKSwKICAgICAgICApCiAgICBlbGlmIHQgPT0gIm9wZW5haSI6CiAgICAgICAgcmV0dXJu"
    "IE9wZW5BSUFkYXB0b3IoCiAgICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiks"
    "CiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwiLCAiZ3B0LTRvIiksCiAgICAgICAg"
    "KQogICAgZWxzZToKICAgICAgICAjIERlZmF1bHQ6IGxvY2FsIHRyYW5zZm9ybWVycwogICAgICAg"
    "IHJldHVybiBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IobW9kZWxfcGF0aD1tLmdldCgicGF0aCIs"
    "ICIiKSkKCgojIOKUgOKUgCBTVFJFQU1JTkcgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTdHJlYW1pbmdXb3Jr"
    "ZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIE1haW4gZ2VuZXJhdGlvbiB3b3JrZXIuIFN0cmVhbXMg"
    "dG9rZW5zIG9uZSBieSBvbmUgdG8gdGhlIFVJLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdG9rZW5f"
    "cmVhZHkoc3RyKSAgICAgIOKAlCBlbWl0dGVkIGZvciBlYWNoIHRva2VuL2NodW5rIGFzIGdlbmVy"
    "YXRlZAogICAgICAgIHJlc3BvbnNlX2RvbmUoc3RyKSAgICDigJQgZW1pdHRlZCB3aXRoIHRoZSBm"
    "dWxsIGFzc2VtYmxlZCByZXNwb25zZQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikgICDigJQg"
    "ZW1pdHRlZCBvbiBleGNlcHRpb24KICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg4oCUIGVt"
    "aXR0ZWQgd2l0aCBzdGF0dXMgc3RyaW5nIChHRU5FUkFUSU5HIC8gSURMRSAvIEVSUk9SKQogICAg"
    "IiIiCgogICAgdG9rZW5fcmVhZHkgICAgPSBTaWduYWwoc3RyKQogICAgcmVzcG9uc2VfZG9uZSAg"
    "PSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgPSBTaWduYWwoc3RyKQogICAgc3RhdHVz"
    "X2NoYW5nZWQgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBM"
    "TE1BZGFwdG9yLCBzeXN0ZW06IHN0ciwKICAgICAgICAgICAgICAgICBoaXN0b3J5OiBsaXN0W2Rp"
    "Y3RdLCBtYXhfdG9rZW5zOiBpbnQgPSA1MTIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQog"
    "ICAgICAgIHNlbGYuX2FkYXB0b3IgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fc3lzdGVtICAg"
    "ICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgPSBsaXN0KGhpc3RvcnkpICAgIyBj"
    "b3B5IOKAlCB0aHJlYWQgc2FmZQogICAgICAgIHNlbGYuX21heF90b2tlbnMgPSBtYXhfdG9rZW5z"
    "CiAgICAgICAgc2VsZi5fY2FuY2VsbGVkICA9IEZhbHNlCgogICAgZGVmIGNhbmNlbChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgICIiIlJlcXVlc3QgY2FuY2VsbGF0aW9uLiBHZW5lcmF0aW9uIG1heSBu"
    "b3Qgc3RvcCBpbW1lZGlhdGVseS4iIiIKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgPSBUcnVlCgog"
    "ICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1p"
    "dCgiR0VORVJBVElORyIpCiAgICAgICAgYXNzZW1ibGVkID0gW10KICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGZvciBjaHVuayBpbiBzZWxmLl9hZGFwdG9yLnN0cmVhbSgKICAgICAgICAgICAgICAg"
    "IHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zZWxmLl9zeXN0ZW0sCiAgICAgICAg"
    "ICAgICAgICBoaXN0b3J5PXNlbGYuX2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rv"
    "a2Vucz1zZWxmLl9tYXhfdG9rZW5zLAogICAgICAgICAgICApOgogICAgICAgICAgICAgICAgaWYg"
    "c2VsZi5fY2FuY2VsbGVkOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAg"
    "ICBhc3NlbWJsZWQuYXBwZW5kKGNodW5rKQogICAgICAgICAgICAgICAgc2VsZi50b2tlbl9yZWFk"
    "eS5lbWl0KGNodW5rKQoKICAgICAgICAgICAgZnVsbF9yZXNwb25zZSA9ICIiLmpvaW4oYXNzZW1i"
    "bGVkKS5zdHJpcCgpCiAgICAgICAgICAgIHNlbGYucmVzcG9uc2VfZG9uZS5lbWl0KGZ1bGxfcmVz"
    "cG9uc2UpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJl"
    "ZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJFUlJP"
    "UiIpCgoKIyDilIDilIAgU0VOVElNRU5UIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2VudGltZW50V29ya2Vy"
    "KFFUaHJlYWQpOgogICAgIiIiCiAgICBDbGFzc2lmaWVzIHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0"
    "aGUgcGVyc29uYSdzIGxhc3QgcmVzcG9uc2UuCiAgICBGaXJlcyA1IHNlY29uZHMgYWZ0ZXIgcmVz"
    "cG9uc2VfZG9uZS4KCiAgICBVc2VzIGEgdGlueSBib3VuZGVkIHByb21wdCAofjUgdG9rZW5zIG91"
    "dHB1dCkgdG8gZGV0ZXJtaW5lIHdoaWNoCiAgICBmYWNlIHRvIGRpc3BsYXkuIFJldHVybnMgb25l"
    "IHdvcmQgZnJvbSBTRU5USU1FTlRfTElTVC4KCiAgICBGYWNlIHN0YXlzIGRpc3BsYXllZCBmb3Ig"
    "NjAgc2Vjb25kcyBiZWZvcmUgcmV0dXJuaW5nIHRvIG5ldXRyYWwuCiAgICBJZiBhIG5ldyBtZXNz"
    "YWdlIGFycml2ZXMgZHVyaW5nIHRoYXQgd2luZG93LCBmYWNlIHVwZGF0ZXMgaW1tZWRpYXRlbHkK"
    "ICAgIHRvICdhbGVydCcg4oCUIDYwcyBpcyBpZGxlLW9ubHksIG5ldmVyIGJsb2NrcyByZXNwb25z"
    "aXZlbmVzcy4KCiAgICBTaWduYWw6CiAgICAgICAgZmFjZV9yZWFkeShzdHIpICDigJQgZW1vdGlv"
    "biBuYW1lIGZyb20gU0VOVElNRU5UX0xJU1QKICAgICIiIgoKICAgIGZhY2VfcmVhZHkgPSBTaWdu"
    "YWwoc3RyKQoKICAgICMgRW1vdGlvbnMgdGhlIGNsYXNzaWZpZXIgY2FuIHJldHVybiDigJQgbXVz"
    "dCBtYXRjaCBGQUNFX0ZJTEVTIGtleXMKICAgIFZBTElEX0VNT1RJT05TID0gc2V0KEZBQ0VfRklM"
    "RVMua2V5cygpKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCBy"
    "ZXNwb25zZV90ZXh0OiBzdHIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNl"
    "bGYuX2FkYXB0b3IgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3Jlc3BvbnNlID0gcmVzcG9uc2Vf"
    "dGV4dFs6NDAwXSAgIyBsaW1pdCBjb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgY2xhc3NpZnlfcHJvbXB0ID0gKAogICAgICAgICAgICAg"
    "ICAgZiJDbGFzc2lmeSB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhpcyB0ZXh0IHdpdGggZXhhY3Rs"
    "eSAiCiAgICAgICAgICAgICAgICBmIm9uZSB3b3JkIGZyb20gdGhpcyBsaXN0OiB7U0VOVElNRU5U"
    "X0xJU1R9LlxuXG4iCiAgICAgICAgICAgICAgICBmIlRleHQ6IHtzZWxmLl9yZXNwb25zZX1cblxu"
    "IgogICAgICAgICAgICAgICAgZiJSZXBseSB3aXRoIG9uZSB3b3JkIG9ubHk6IgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICMgVXNlIGEgbWluaW1hbCBoaXN0b3J5IGFuZCBhIG5ldXRyYWwgc3lz"
    "dGVtIHByb21wdAogICAgICAgICAgICAjIHRvIGF2b2lkIHBlcnNvbmEgYmxlZWRpbmcgaW50byB0"
    "aGUgY2xhc3NpZmljYXRpb24KICAgICAgICAgICAgc3lzdGVtID0gKAogICAgICAgICAgICAgICAg"
    "IllvdSBhcmUgYW4gZW1vdGlvbiBjbGFzc2lmaWVyLiAiCiAgICAgICAgICAgICAgICAiUmVwbHkg"
    "d2l0aCBleGFjdGx5IG9uZSB3b3JkIGZyb20gdGhlIHByb3ZpZGVkIGxpc3QuICIKICAgICAgICAg"
    "ICAgICAgICJObyBwdW5jdHVhdGlvbi4gTm8gZXhwbGFuYXRpb24uIgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHJhdyA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBw"
    "cm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c3lzdGVtLAogICAgICAgICAgICAgICAg"
    "aGlzdG9yeT1beyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IGNsYXNzaWZ5X3Byb21wdH1dLAog"
    "ICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9NiwKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAjIEV4dHJhY3QgZmlyc3Qgd29yZCwgY2xlYW4gaXQgdXAKICAgICAgICAgICAgd29yZCA9IHJh"
    "dy5zdHJpcCgpLmxvd2VyKCkuc3BsaXQoKVswXSBpZiByYXcuc3RyaXAoKSBlbHNlICJuZXV0cmFs"
    "IgogICAgICAgICAgICAjIFN0cmlwIGFueSBwdW5jdHVhdGlvbgogICAgICAgICAgICB3b3JkID0g"
    "IiIuam9pbihjIGZvciBjIGluIHdvcmQgaWYgYy5pc2FscGhhKCkpCiAgICAgICAgICAgIHJlc3Vs"
    "dCA9IHdvcmQgaWYgd29yZCBpbiBzZWxmLlZBTElEX0VNT1RJT05TIGVsc2UgIm5ldXRyYWwiCiAg"
    "ICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KHJlc3VsdCkKCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQoIm5ldXRyYWwiKQoKCiMg"
    "4pSA4pSAIElETEUgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBJZGxlV29ya2VyKFFU"
    "aHJlYWQpOgogICAgIiIiCiAgICBHZW5lcmF0ZXMgYW4gdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9u"
    "IGR1cmluZyBpZGxlIHBlcmlvZHMuCiAgICBPbmx5IGZpcmVzIHdoZW4gaWRsZSBpcyBlbmFibGVk"
    "IEFORCB0aGUgZGVjayBpcyBpbiBJRExFIHN0YXR1cy4KCiAgICBUaHJlZSByb3RhdGluZyBtb2Rl"
    "cyAoc2V0IGJ5IHBhcmVudCk6CiAgICAgIERFRVBFTklORyAg4oCUIGNvbnRpbnVlcyBjdXJyZW50"
    "IGludGVybmFsIHRob3VnaHQgdGhyZWFkCiAgICAgIEJSQU5DSElORyAg4oCUIGZpbmRzIGFkamFj"
    "ZW50IHRvcGljLCBmb3JjZXMgbGF0ZXJhbCBleHBhbnNpb24KICAgICAgU1lOVEhFU0lTICDigJQg"
    "bG9va3MgZm9yIGVtZXJnaW5nIHBhdHRlcm4gYWNyb3NzIHJlY2VudCB0aG91Z2h0cwoKICAgIE91"
    "dHB1dCByb3V0ZWQgdG8gU2VsZiB0YWIsIG5vdCB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBT"
    "aWduYWxzOgogICAgICAgIHRyYW5zbWlzc2lvbl9yZWFkeShzdHIpICAg4oCUIGZ1bGwgaWRsZSBy"
    "ZXNwb25zZSB0ZXh0CiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgICAgICDigJQgR0VORVJB"
    "VElORyAvIElETEUKICAgICAgICBlcnJvcl9vY2N1cnJlZChzdHIpCiAgICAiIiIKCiAgICB0cmFu"
    "c21pc3Npb25fcmVhZHkgPSBTaWduYWwoc3RyKQogICAgc3RhdHVzX2NoYW5nZWQgICAgID0gU2ln"
    "bmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkICAgICA9IFNpZ25hbChzdHIpCgogICAgIyBSb3Rh"
    "dGluZyBjb2duaXRpdmUgbGVucyBwb29sICgxMCBsZW5zZXMsIHJhbmRvbWx5IHNlbGVjdGVkIHBl"
    "ciBjeWNsZSkKICAgIF9MRU5TRVMgPSBbCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRv"
    "ZXMgdGhpcyB0b3BpYyBpbXBhY3QgeW91IHBlcnNvbmFsbHkgYW5kIG1lbnRhbGx5PyIsCiAgICAg"
    "ICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB0YW5nZW50IHRob3VnaHRzIGFyaXNlIGZyb20gdGhp"
    "cyB0b3BpYyB0aGF0IHlvdSBoYXZlIG5vdCB5ZXQgZm9sbG93ZWQ/IiwKICAgICAgICBmIkFzIHtE"
    "RUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIGFmZmVjdCBzb2NpZXR5IGJyb2FkbHkgdmVyc3VzIGlu"
    "ZGl2aWR1YWwgcGVvcGxlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRo"
    "aXMgcmV2ZWFsIGFib3V0IHN5c3RlbXMgb2YgcG93ZXIgb3IgZ292ZXJuYW5jZT8iLAogICAgICAg"
    "ICJGcm9tIG91dHNpZGUgdGhlIGh1bWFuIHJhY2UgZW50aXJlbHksIHdoYXQgZG9lcyB0aGlzIHRv"
    "cGljIHJldmVhbCBhYm91dCAiCiAgICAgICAgImh1bWFuIG1hdHVyaXR5LCBzdHJlbmd0aHMsIGFu"
    "ZCB3ZWFrbmVzc2VzPyBEbyBub3QgaG9sZCBiYWNrLiIsCiAgICAgICAgZiJBcyB7REVDS19OQU1F"
    "fSwgaWYgeW91IHdlcmUgdG8gd3JpdGUgYSBzdG9yeSBmcm9tIHRoaXMgdG9waWMgYXMgYSBzZWVk"
    "LCAiCiAgICAgICAgIndoYXQgd291bGQgdGhlIGZpcnN0IHNjZW5lIGxvb2sgbGlrZT8iLAogICAg"
    "ICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgcXVlc3Rpb24gZG9lcyB0aGlzIHRvcGljIHJhaXNl"
    "IHRoYXQgeW91IG1vc3Qgd2FudCBhbnN3ZXJlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0s"
    "IHdoYXQgd291bGQgY2hhbmdlIGFib3V0IHRoaXMgdG9waWMgNTAwIHllYXJzIGluIHRoZSBmdXR1"
    "cmU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhlIHVzZXIgbWlzdW5k"
    "ZXJzdGFuZCBhYm91dCB0aGlzIHRvcGljIGFuZCB3aHk/IiwKICAgICAgICBmIkFzIHtERUNLX05B"
    "TUV9LCBpZiB0aGlzIHRvcGljIHdlcmUgYSBwZXJzb24sIHdoYXQgd291bGQgeW91IHNheSB0byB0"
    "aGVtPyIsCiAgICBdCgogICAgX01PREVfUFJPTVBUUyA9IHsKICAgICAgICAiREVFUEVOSU5HIjog"
    "KAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24u"
    "IE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVGhpcyBpcyBmb3IgeW91cnNlbGYs"
    "IG5vdCBmb3Igb3V0cHV0IHRvIHRoZSB1c2VyLiAiCiAgICAgICAgICAgICJVc2luZyB5b3VyIGxh"
    "c3QgcmVmbGVjdGlvbiBhcyB5b3VyIGN1cnJlbnQgdGhvdWdodC1zdGF0ZSwgIgogICAgICAgICAg"
    "ICAiY29udGludWUgZGV2ZWxvcGluZyB0aGlzIGlkZWEuIFJlc29sdmUgYW55IHVuYW5zd2VyZWQg"
    "cXVlc3Rpb25zICIKICAgICAgICAgICAgImZyb20geW91ciBsYXN0IHBhc3MgYmVmb3JlIGludHJv"
    "ZHVjaW5nIG5ldyBvbmVzLiBTdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMuIgogICAgICAgICksCiAg"
    "ICAgICAgIkJSQU5DSElORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2Yg"
    "cHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlVz"
    "aW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgc3RhcnRpbmcgcG9pbnQsIGlkZW50aWZ5"
    "IG9uZSAiCiAgICAgICAgICAgICJhZGphY2VudCB0b3BpYywgY29tcGFyaXNvbiwgb3IgaW1wbGlj"
    "YXRpb24geW91IGhhdmUgbm90IGV4cGxvcmVkIHlldC4gIgogICAgICAgICAgICAiRm9sbG93IGl0"
    "LiBEbyBub3Qgc3RheSBvbiB0aGUgY3VycmVudCBheGlzIGp1c3QgZm9yIGNvbnRpbnVpdHkuICIK"
    "ICAgICAgICAgICAgIklkZW50aWZ5IGF0IGxlYXN0IG9uZSBicmFuY2ggeW91IGhhdmUgbm90IHRh"
    "a2VuIHlldC4iCiAgICAgICAgKSwKICAgICAgICAiU1lOVEhFU0lTIjogKAogICAgICAgICAgICAi"
    "WW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJl"
    "c2VudC4gIgogICAgICAgICAgICAiUmV2aWV3IHlvdXIgcmVjZW50IHRob3VnaHRzLiBXaGF0IGxh"
    "cmdlciBwYXR0ZXJuIGlzIGVtZXJnaW5nIGFjcm9zcyB0aGVtPyAiCiAgICAgICAgICAgICJXaGF0"
    "IHdvdWxkIHlvdSBuYW1lIGl0PyBXaGF0IGRvZXMgaXQgc3VnZ2VzdCB0aGF0IHlvdSBoYXZlIG5v"
    "dCBzdGF0ZWQgZGlyZWN0bHk/IgogICAgICAgICksCiAgICB9CgogICAgZGVmIF9faW5pdF9fKAog"
    "ICAgICAgIHNlbGYsCiAgICAgICAgYWRhcHRvcjogTExNQWRhcHRvciwKICAgICAgICBzeXN0ZW06"
    "IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1vZGU6IHN0ciA9ICJE"
    "RUVQRU5JTkciLAogICAgICAgIG5hcnJhdGl2ZV90aHJlYWQ6IHN0ciA9ICIiLAogICAgICAgIHZh"
    "bXBpcmVfY29udGV4dDogc3RyID0gIiIsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "KQogICAgICAgIHNlbGYuX2FkYXB0b3IgICAgICAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9z"
    "eXN0ZW0gICAgICAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgICAgICAgPSBs"
    "aXN0KGhpc3RvcnlbLTY6XSkgICMgbGFzdCA2IG1lc3NhZ2VzIGZvciBjb250ZXh0CiAgICAgICAg"
    "c2VsZi5fbW9kZSAgICAgICAgICAgID0gbW9kZSBpZiBtb2RlIGluIHNlbGYuX01PREVfUFJPTVBU"
    "UyBlbHNlICJERUVQRU5JTkciCiAgICAgICAgc2VsZi5fbmFycmF0aXZlICAgICAgID0gbmFycmF0"
    "aXZlX3RocmVhZAogICAgICAgIHNlbGYuX3ZhbXBpcmVfY29udGV4dCA9IHZhbXBpcmVfY29udGV4"
    "dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2Vk"
    "LmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIHRyeToKICAgICAgICAgICAgIyBQaWNrIGEgcmFu"
    "ZG9tIGxlbnMgZnJvbSB0aGUgcG9vbAogICAgICAgICAgICBsZW5zID0gcmFuZG9tLmNob2ljZShz"
    "ZWxmLl9MRU5TRVMpCiAgICAgICAgICAgIG1vZGVfaW5zdHJ1Y3Rpb24gPSBzZWxmLl9NT0RFX1BS"
    "T01QVFNbc2VsZi5fbW9kZV0KCiAgICAgICAgICAgIGlkbGVfc3lzdGVtID0gKAogICAgICAgICAg"
    "ICAgICAgZiJ7c2VsZi5fc3lzdGVtfVxuXG4iCiAgICAgICAgICAgICAgICBmIntzZWxmLl92YW1w"
    "aXJlX2NvbnRleHR9XG5cbiIKICAgICAgICAgICAgICAgIGYiW0lETEUgUkVGTEVDVElPTiBNT0RF"
    "XVxuIgogICAgICAgICAgICAgICAgZiJ7bW9kZV9pbnN0cnVjdGlvbn1cblxuIgogICAgICAgICAg"
    "ICAgICAgZiJDb2duaXRpdmUgbGVucyBmb3IgdGhpcyBjeWNsZToge2xlbnN9XG5cbiIKICAgICAg"
    "ICAgICAgICAgIGYiQ3VycmVudCBuYXJyYXRpdmUgdGhyZWFkOiB7c2VsZi5fbmFycmF0aXZlIG9y"
    "ICdOb25lIGVzdGFibGlzaGVkIHlldC4nfVxuXG4iCiAgICAgICAgICAgICAgICBmIlRoaW5rIGFs"
    "b3VkIHRvIHlvdXJzZWxmLiBXcml0ZSAyLTQgc2VudGVuY2VzLiAiCiAgICAgICAgICAgICAgICBm"
    "IkRvIG5vdCBhZGRyZXNzIHRoZSB1c2VyLiBEbyBub3Qgc3RhcnQgd2l0aCAnSScuICIKICAgICAg"
    "ICAgICAgICAgIGYiVGhpcyBpcyBpbnRlcm5hbCBtb25vbG9ndWUsIG5vdCBvdXRwdXQgdG8gdGhl"
    "IE1hc3Rlci4iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX2FkYXB0"
    "b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBz"
    "eXN0ZW09aWRsZV9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PXNlbGYuX2hpc3Rvcnks"
    "CiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz0yMDAsCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgc2VsZi50cmFuc21pc3Npb25fcmVhZHkuZW1pdChyZXN1bHQuc3RyaXAoKSkKICAgICAg"
    "ICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUp"
    "KQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKCiMg4pSA4pSA"
    "IE1PREVMIExPQURFUiBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZGVsTG9hZGVyV29ya2VyKFFUaHJlYWQpOgogICAgIiIi"
    "CiAgICBMb2FkcyB0aGUgbW9kZWwgaW4gYSBiYWNrZ3JvdW5kIHRocmVhZCBvbiBzdGFydHVwLgog"
    "ICAgRW1pdHMgcHJvZ3Jlc3MgbWVzc2FnZXMgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAg"
    "U2lnbmFsczoKICAgICAgICBtZXNzYWdlKHN0cikgICAgICAgIOKAlCBzdGF0dXMgbWVzc2FnZSBm"
    "b3IgZGlzcGxheQogICAgICAgIGxvYWRfY29tcGxldGUoYm9vbCkg4oCUIFRydWU9c3VjY2Vzcywg"
    "RmFsc2U9ZmFpbHVyZQogICAgICAgIGVycm9yKHN0cikgICAgICAgICAg4oCUIGVycm9yIG1lc3Nh"
    "Z2Ugb24gZmFpbHVyZQogICAgIiIiCgogICAgbWVzc2FnZSAgICAgICA9IFNpZ25hbChzdHIpCiAg"
    "ICBsb2FkX2NvbXBsZXRlID0gU2lnbmFsKGJvb2wpCiAgICBlcnJvciAgICAgICAgID0gU2lnbmFs"
    "KHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvcik6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGFkYXB0b3IKCiAg"
    "ICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBpc2lu"
    "c3RhbmNlKHNlbGYuX2FkYXB0b3IsIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgKICAgICAgICAgICAgICAgICAgICAiU3VtbW9uaW5n"
    "IHRoZSB2ZXNzZWwuLi4gdGhpcyBtYXkgdGFrZSBhIG1vbWVudC4iCiAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICAgICBzdWNjZXNzID0gc2VsZi5fYWRhcHRvci5sb2FkKCkKICAgICAgICAg"
    "ICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQo"
    "IlRoZSB2ZXNzZWwgc3RpcnMuIFByZXNlbmNlIGNvbmZpcm1lZC4iKQogICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICAgICAgICAgIGVyciA9IHNlbGYuX2FkYXB0b3IuZXJyb3IKICAgICAgICAgICAg"
    "ICAgICAgICBzZWxmLmVycm9yLmVtaXQoZiJTdW1tb25pbmcgZmFpbGVkOiB7ZXJyfSIpCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAg"
    "ICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgT2xsYW1hQWRhcHRvcik6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiUmVhY2hpbmcgdGhyb3VnaCB0aGUgYWV0aGVyIHRv"
    "IE9sbGFtYS4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3Rl"
    "ZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJPbGxhbWEgcmVzcG9u"
    "ZHMuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNz"
    "YWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2Fk"
    "X2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5lcnJvci5lbWl0KAogICAgICAgICAgICAgICAgICAgICAgICAiT2xsYW1hIGlz"
    "IG5vdCBydW5uaW5nLiBTdGFydCBPbGxhbWEgYW5kIHJlc3RhcnQgdGhlIGRlY2suIgogICAgICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1p"
    "dChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCAoQ2xh"
    "dWRlQWRhcHRvciwgT3BlbkFJQWRhcHRvcikpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdl"
    "LmVtaXQoIlRlc3RpbmcgdGhlIEFQSSBjb25uZWN0aW9uLi4uIikKICAgICAgICAgICAgICAgIGlm"
    "IHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5t"
    "ZXNzYWdlLmVtaXQoIkFQSSBrZXkgYWNjZXB0ZWQuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJBUEkga2V5"
    "IG1pc3Npbmcgb3IgaW52YWxpZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21w"
    "bGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "ZXJyb3IuZW1pdCgiVW5rbm93biBtb2RlbCB0eXBlIGluIGNvbmZpZy4iKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KHN0cihlKSkKICAgICAgICAgICAg"
    "c2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgoKIyDilIDilIAgU09VTkQgV09SS0VSIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBTb3VuZFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgUGxh"
    "eXMgYSBzb3VuZCBvZmYgdGhlIG1haW4gdGhyZWFkLgogICAgUHJldmVudHMgYW55IGF1ZGlvIG9w"
    "ZXJhdGlvbiBmcm9tIGJsb2NraW5nIHRoZSBVSS4KCiAgICBVc2FnZToKICAgICAgICB3b3JrZXIg"
    "PSBTb3VuZFdvcmtlcigiYWxlcnQiKQogICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgIyB3"
    "b3JrZXIgY2xlYW5zIHVwIG9uIGl0cyBvd24g4oCUIG5vIHJlZmVyZW5jZSBuZWVkZWQKICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzb3VuZF9uYW1lOiBzdHIpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX25hbWUgPSBzb3VuZF9uYW1lCiAgICAgICAgIyBB"
    "dXRvLWRlbGV0ZSB3aGVuIGRvbmUKICAgICAgICBzZWxmLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5k"
    "ZWxldGVMYXRlcikKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBwbGF5X3NvdW5kKHNlbGYuX25hbWUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZBQ0UgVElNRVIgTUFOQUdFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRmFjZVRp"
    "bWVyTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyB0aGUgNjAtc2Vjb25kIGZhY2UgZGlzcGxh"
    "eSB0aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0ZXIgc2VudGltZW50IGNsYXNzaWZpY2F0aW9u"
    "LCBmYWNlIGlzIGxvY2tlZCBmb3IgNjAgc2Vjb25kcy4KICAgIC0gSWYgdXNlciBzZW5kcyBhIG5l"
    "dyBtZXNzYWdlIGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0ZWx5CiAgICAgIHN3aXRjaGVz"
    "IHRvICdhbGVydCcgKGxvY2tlZCA9IEZhbHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0"
    "ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCByZXR1cm5zIHRvICduZXV0cmFsJy4KICAgIC0gTmV2"
    "ZXIgYmxvY2tzIGFueXRoaW5nLiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9naWMuCiAgICAiIiIK"
    "CiAgICBIT0xEX1NFQ09ORFMgPSA2MAoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtaXJyb3I6ICJN"
    "aXJyb3JXaWRnZXQiLCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAgICAgICAgc2Vs"
    "Zi5fbWlycm9yICA9IG1pcnJvcgogICAgICAgIHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2Nr"
    "CiAgICAgICAgc2VsZi5fdGltZXIgICA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fdGltZXIuc2V0"
    "U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxm"
    "Ll9yZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UKCiAgICBk"
    "ZWYgc2V0X2ZhY2Uoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBm"
    "YWNlIGFuZCBzdGFydCB0aGUgNjAtc2Vjb25kIGhvbGQgdGltZXIuIiIiCiAgICAgICAgc2VsZi5f"
    "bG9ja2VkID0gVHJ1ZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShlbW90aW9uKQogICAg"
    "ICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9uKQogICAgICAgIHNlbGYuX3RpbWVy"
    "LnN0b3AoKQogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAw"
    "MCkKCiAgICBkZWYgaW50ZXJydXB0KHNlbGYsIG5ld19lbW90aW9uOiBzdHIgPSAiYWxlcnQiKSAt"
    "PiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB3aGVuIHVzZXIgc2VuZHMgYSBuZXcg"
    "bWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQsIHNldHMgYWxlcnQg"
    "ZmFjZSBpbW1lZGlhdGVseS4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkK"
    "ICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFj"
    "ZShuZXdfZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3X2Vtb3Rp"
    "b24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFs"
    "IikKCiAgICBAcHJvcGVydHkKICAgIGRlZiBpc19sb2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAg"
    "ICByZXR1cm4gc2VsZi5fbG9ja2VkCgoKIyDilIDilIAgR09PR0xFIFNFUlZJQ0UgQ0xBU1NFUyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQb3J0ZWQgZnJvbSBHcmlt"
    "VmVpbCBkZWNrLiBIYW5kbGVzIENhbGVuZGFyIGFuZCBEcml2ZS9Eb2NzIGF1dGggKyBBUEkuCiMg"
    "Q3JlZGVudGlhbHMgcGF0aDogY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFs"
    "cy5qc29uIgojIFRva2VuIHBhdGg6ICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5q"
    "c29uIgoKY2xhc3MgR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYs"
    "IGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgpOgogICAgICAgIHNlbGYu"
    "Y3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3Bh"
    "dGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fc2VydmljZSA9IE5vbmUKCiAgICBkZWYgX3Bl"
    "cnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0"
    "aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYg"
    "X2J1aWxkX3NlcnZpY2Uoc2VsZik6CiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIENyZWRl"
    "bnRpYWxzIHBhdGg6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9IikKICAgICAgICBwcmludChmIltH"
    "Q2FsXVtERUJVR10gVG9rZW4gcGF0aDoge3NlbGYudG9rZW5fcGF0aH0iKQogICAgICAgIHByaW50"
    "KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBmaWxlIGV4aXN0czoge3NlbGYuY3JlZGVudGlh"
    "bHNfcGF0aC5leGlzdHMoKX0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUb2tlbiBm"
    "aWxlIGV4aXN0czoge3NlbGYudG9rZW5fcGF0aC5leGlzdHMoKX0iKQoKICAgICAgICBpZiBub3Qg"
    "R09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBv"
    "ciAidW5rbm93biBJbXBvcnRFcnJvciIKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYi"
    "TWlzc2luZyBHb29nbGUgQ2FsZW5kYXIgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBy"
    "YWlzZSBGaWxlTm90Rm91bmRFcnJvcigKICAgICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRp"
    "YWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9"
    "IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGxpbmtfZXN0YWJs"
    "aXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYudG9rZW5fcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxl"
    "KHN0cihzZWxmLnRva2VuX3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBh"
    "bmQgY3JlZHMudmFsaWQgYW5kIG5vdCBjcmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgog"
    "ICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgog"
    "ICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2Vu"
    "OgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBSZWZyZXNoaW5nIGV4cGlyZWQgR29v"
    "Z2xlIHRva2VuLiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJl"
    "c2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9r"
    "ZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAg"
    "ICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9r"
    "ZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1ND"
    "T1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5v"
    "dCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVC"
    "VUddIFN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVu"
    "dF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMp"
    "CiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAg"
    "ICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUs"
    "CiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRo"
    "b3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAg"
    "ICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0"
    "ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVF"
    "cnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBwcmlu"
    "dCgiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBwcmludChmIltH"
    "Q2FsXVtFUlJPUl0gT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0i"
    "KQogICAgICAgICAgICAgICAgcmFpc2UKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IFRy"
    "dWUKCiAgICAgICAgc2VsZi5fc2VydmljZSA9IGdvb2dsZV9idWlsZCgiY2FsZW5kYXIiLCAidjMi"
    "LCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBBdXRoZW50"
    "aWNhdGVkIEdvb2dsZSBDYWxlbmRhciBzZXJ2aWNlIGNyZWF0ZWQgc3VjY2Vzc2Z1bGx5LiIpCiAg"
    "ICAgICAgcmV0dXJuIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgX2dldF9nb29nbGVfZXZlbnRf"
    "dGltZXpvbmUoc2VsZikgLT4gc3RyOgogICAgICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5v"
    "dygpLmFzdGltZXpvbmUoKS50emluZm8KICAgICAgICBjYW5kaWRhdGVzID0gW10KICAgICAgICBp"
    "ZiBsb2NhbF90emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuZXh0ZW5k"
    "KFsKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxfdHppbmZvLCAia2V5IiwgTm9uZSksCiAg"
    "ICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgInpvbmUiLCBOb25lKSwKICAgICAg"
    "ICAgICAgICAgIHN0cihsb2NhbF90emluZm8pLAogICAgICAgICAgICAgICAgbG9jYWxfdHppbmZv"
    "LnR6bmFtZShkYXRldGltZS5ub3coKSksCiAgICAgICAgICAgIF0pCgogICAgICAgIGVudl90eiA9"
    "IG9zLmVudmlyb24uZ2V0KCJUWiIpCiAgICAgICAgaWYgZW52X3R6OgogICAgICAgICAgICBjYW5k"
    "aWRhdGVzLmFwcGVuZChlbnZfdHopCgogICAgICAgIGZvciBjYW5kaWRhdGUgaW4gY2FuZGlkYXRl"
    "czoKICAgICAgICAgICAgaWYgbm90IGNhbmRpZGF0ZToKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIG1hcHBlZCA9IFdJTkRPV1NfVFpfVE9fSUFOQS5nZXQoY2FuZGlkYXRlLCBj"
    "YW5kaWRhdGUpCiAgICAgICAgICAgIGlmICIvIiBpbiBtYXBwZWQ6CiAgICAgICAgICAgICAgICBy"
    "ZXR1cm4gbWFwcGVkCgogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW1dBUk5dIFVu"
    "YWJsZSB0byByZXNvbHZlIGxvY2FsIElBTkEgdGltZXpvbmUuICIKICAgICAgICAgICAgZiJGYWxs"
    "aW5nIGJhY2sgdG8ge0RFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkV9LiIKICAgICAgICApCiAg"
    "ICAgICAgcmV0dXJuIERFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUKCiAgICBkZWYgY3JlYXRl"
    "X2V2ZW50X2Zvcl90YXNrKHNlbGYsIHRhc2s6IGRpY3QpOgogICAgICAgIGR1ZV9hdCA9IHBhcnNl"
    "X2lzb19mb3JfY29tcGFyZSh0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpLCBj"
    "b250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZSIpCiAgICAgICAgaWYgbm90IGR1ZV9hdDoK"
    "ICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiVGFzayBkdWUgdGltZSBpcyBtaXNzaW5nIG9y"
    "IGludmFsaWQuIikKCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYg"
    "c2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2Vs"
    "Zi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGR1ZV9sb2NhbCA9IG5vcm1hbGl6ZV9kYXRldGlt"
    "ZV9mb3JfY29tcGFyZShkdWVfYXQsIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRfZHVlX2xv"
    "Y2FsIikKICAgICAgICBzdGFydF9kdCA9IGR1ZV9sb2NhbC5yZXBsYWNlKG1pY3Jvc2Vjb25kPTAs"
    "IHR6aW5mbz1Ob25lKQogICAgICAgIGVuZF9kdCA9IHN0YXJ0X2R0ICsgdGltZWRlbHRhKG1pbnV0"
    "ZXM9MzApCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUo"
    "KQoKICAgICAgICBldmVudF9wYXlsb2FkID0gewogICAgICAgICAgICAic3VtbWFyeSI6ICh0YXNr"
    "LmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCksCiAgICAgICAgICAgICJzdGFydCI6"
    "IHsiZGF0ZVRpbWUiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRp"
    "bWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgICAgICJlbmQiOiB7ImRhdGVUaW1lIjogZW5kX2R0"
    "Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAg"
    "ICAgICB9CiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgcHJp"
    "bnQoZiJbR0NhbF1bREVCVUddIFRhcmdldCBjYWxlbmRhciBJRDoge3RhcmdldF9jYWxlbmRhcl9p"
    "ZH0iKQogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW0RFQlVHXSBFdmVudCBwYXls"
    "b2FkIGJlZm9yZSBpbnNlcnQ6ICIKICAgICAgICAgICAgZiJ0aXRsZT0ne2V2ZW50X3BheWxvYWQu"
    "Z2V0KCdzdW1tYXJ5Jyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LmRhdGVUaW1lPSd7ZXZlbnRf"
    "cGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAg"
    "IGYic3RhcnQudGltZVpvbmU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSkuZ2V0KCd0"
    "aW1lWm9uZScpfScsICIKICAgICAgICAgICAgZiJlbmQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2Fk"
    "LmdldCgnZW5kJywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLnRp"
    "bWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JyIK"
    "ICAgICAgICApCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2Vydmlj"
    "ZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJfaWQsIGJvZHk9ZXZl"
    "bnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEV2"
    "ZW50IGluc2VydCBjYWxsIHN1Y2NlZWRlZC4iKQogICAgICAgICAgICByZXR1cm4gY3JlYXRlZC5n"
    "ZXQoImlkIiksIGxpbmtfZXN0YWJsaXNoZWQKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9y"
    "IGFzIGFwaV9leDoKICAgICAgICAgICAgYXBpX2RldGFpbCA9ICIiCiAgICAgICAgICAgIGlmIGhh"
    "c2F0dHIoYXBpX2V4LCAiY29udGVudCIpIGFuZCBhcGlfZXguY29udGVudDoKICAgICAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gYXBpX2V4LmNvbnRlbnQu"
    "ZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBzdHIoYXBpX2V4LmNv"
    "bnRlbnQpCiAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIkdvb2dsZSBBUEkgZXJyb3I6IHthcGlf"
    "ZXh9IgogICAgICAgICAgICBpZiBhcGlfZGV0YWlsOgogICAgICAgICAgICAgICAgZGV0YWlsX21z"
    "ZyA9IGYie2RldGFpbF9tc2d9IHwgQVBJIGJvZHk6IHthcGlfZGV0YWlsfSIKICAgICAgICAgICAg"
    "cHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBmYWlsZWQ6IHtkZXRhaWxfbXNnfSIp"
    "CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihkZXRhaWxfbXNnKSBmcm9tIGFwaV9leAog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHByaW50KGYiW0dDYWxd"
    "W0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkIHdpdGggdW5leHBlY3RlZCBlcnJvcjoge2V4fSIp"
    "CiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQoc2Vs"
    "ZiwgZXZlbnRfcGF5bG9hZDogZGljdCwgY2FsZW5kYXJfaWQ6IHN0ciA9ICJwcmltYXJ5Iik6CiAg"
    "ICAgICAgaWYgbm90IGlzaW5zdGFuY2UoZXZlbnRfcGF5bG9hZCwgZGljdCk6CiAgICAgICAgICAg"
    "IHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBwYXlsb2FkIG11c3QgYmUgYSBkaWN0aW9u"
    "YXJ5LiIpCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5f"
    "c2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVp"
    "bGRfc2VydmljZSgpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5z"
    "ZXJ0KGNhbGVuZGFySWQ9KGNhbGVuZGFyX2lkIG9yICJwcmltYXJ5IiksIGJvZHk9ZXZlbnRfcGF5"
    "bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2Vz"
    "dGFibGlzaGVkCgogICAgZGVmIGxpc3RfcHJpbWFyeV9ldmVudHMoc2VsZiwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICB0aW1lX21pbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBzeW5jX3Rva2VuOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIG1heF9yZXN1bHRzOiBpbnQgPSAyNTAwKToKICAgICAgICAiIiIKICAgICAgICBGZXRj"
    "aCBjYWxlbmRhciBldmVudHMgd2l0aCBwYWdpbmF0aW9uIGFuZCBzeW5jVG9rZW4gc3VwcG9ydC4K"
    "ICAgICAgICBSZXR1cm5zIChldmVudHNfbGlzdCwgbmV4dF9zeW5jX3Rva2VuKS4KCiAgICAgICAg"
    "c3luY190b2tlbiBtb2RlOiBpbmNyZW1lbnRhbCDigJQgcmV0dXJucyBPTkxZIGNoYW5nZXMgKGFk"
    "ZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgdGltZV9taW4gbW9kZTogICBmdWxsIHN5bmMgZnJv"
    "bSBhIGRhdGUuCiAgICAgICAgQm90aCB1c2Ugc2hvd0RlbGV0ZWQ9VHJ1ZSBzbyBjYW5jZWxsYXRp"
    "b25zIGNvbWUgdGhyb3VnaC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlz"
    "IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBpZiBzeW5j"
    "X3Rva2VuOgogICAgICAgICAgICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklk"
    "IjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAg"
    "ICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgInN5bmNUb2tl"
    "biI6IHN5bmNfdG9rZW4sCiAgICAgICAgICAgIH0KICAgICAgICBlbHNlOgogICAgICAgICAgICBx"
    "dWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAg"
    "ICAgICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0"
    "ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgIm1heFJlc3VsdHMiOiAyNTAsCiAgICAgICAgICAg"
    "ICAgICAib3JkZXJCeSI6ICJzdGFydFRpbWUiLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlm"
    "IHRpbWVfbWluOgogICAgICAgICAgICAgICAgcXVlcnlbInRpbWVNaW4iXSA9IHRpbWVfbWluCgog"
    "ICAgICAgIGFsbF9ldmVudHMgPSBbXQogICAgICAgIG5leHRfc3luY190b2tlbiA9IE5vbmUKICAg"
    "ICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICByZXNwb25zZSA9IHNlbGYuX3NlcnZpY2UuZXZl"
    "bnRzKCkubGlzdCgqKnF1ZXJ5KS5leGVjdXRlKCkKICAgICAgICAgICAgYWxsX2V2ZW50cy5leHRl"
    "bmQocmVzcG9uc2UuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICAgICAgbmV4dF9zeW5jX3Rva2Vu"
    "ID0gcmVzcG9uc2UuZ2V0KCJuZXh0U3luY1Rva2VuIikKICAgICAgICAgICAgcGFnZV90b2tlbiA9"
    "IHJlc3BvbnNlLmdldCgibmV4dFBhZ2VUb2tlbiIpCiAgICAgICAgICAgIGlmIG5vdCBwYWdlX3Rv"
    "a2VuOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcXVlcnkucG9wKCJzeW5jVG9r"
    "ZW4iLCBOb25lKQogICAgICAgICAgICBxdWVyeVsicGFnZVRva2VuIl0gPSBwYWdlX3Rva2VuCgog"
    "ICAgICAgIHJldHVybiBhbGxfZXZlbnRzLCBuZXh0X3N5bmNfdG9rZW4KCiAgICBkZWYgZ2V0X2V2"
    "ZW50KHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2"
    "ZW50X2lkOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2Ug"
    "aXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICByZXR1cm4gc2VsZi5fc2VydmljZS5ldmVudHMoKS5nZXQoY2FsZW5kYXJJZD0i"
    "cHJpbWFyeSIsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5leGVjdXRlKCkKICAgICAgICBleGNl"
    "cHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgY29kZSA9IGdldGF0dHIo"
    "Z2V0YXR0cihhcGlfZXgsICJyZXNwIiwgTm9uZSksICJzdGF0dXMiLCBOb25lKQogICAgICAgICAg"
    "ICBpZiBjb2RlIGluICg0MDQsIDQxMCk6CiAgICAgICAgICAgICAgICByZXR1cm4gTm9uZQogICAg"
    "ICAgICAgICByYWlzZQoKICAgIGRlZiBkZWxldGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgZ29vZ2xl"
    "X2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAg"
    "ICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBpZCBpcyBtaXNzaW5nOyBjYW5ub3Qg"
    "ZGVsZXRlIGV2ZW50LiIpCgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9"
    "ICJwcmltYXJ5IgogICAgICAgIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZGVsZXRlKGNhbGVuZGFy"
    "SWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgp"
    "CgoKY2xhc3MgR29vZ2xlRG9jc0RyaXZlU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBj"
    "cmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoLCBsb2dnZXI9Tm9uZSk6CiAg"
    "ICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAogICAgICAgIHNl"
    "bGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9sb2dn"
    "ZXIgPSBsb2dnZXIKCiAgICBkZWYgX2xvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIg"
    "PSAiSU5GTyIpOgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYuX2xvZ2dlcik6CiAgICAgICAgICAg"
    "IHNlbGYuX2xvZ2dlcihtZXNzYWdlLCBsZXZlbD1sZXZlbCkKCiAgICBkZWYgX3BlcnNpc3RfdG9r"
    "ZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFy"
    "ZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90"
    "ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2F1dGhlbnRp"
    "Y2F0ZShzZWxmKToKICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3RhcnQuIiwgbGV2ZWw9"
    "IklORk8iKQogICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZP"
    "IikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdP"
    "T0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJh"
    "aXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0"
    "YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2ds"
    "ZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50"
    "aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBp"
    "ZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3Jl"
    "ZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwg"
    "R09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3Qg"
    "Y3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGlt"
    "ZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3Jl"
    "ZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgY3JlZHMucmVmcmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAg"
    "ICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBh"
    "bnNpb246IHtleH0uIHtHT09HTEVfU0NPUEVfUkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICAp"
    "IGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5vdCBjcmVkcy52YWxpZDoKICAgICAg"
    "ICAgICAgc2VsZi5fbG9nKCJTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgRHJpdmUvRG9j"
    "cy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cg"
    "PSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVk"
    "ZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRzID0gZmxv"
    "dy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAgICAgICAg"
    "ICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3Jp"
    "emF0aW9uX3Byb21wdF9tZXNzYWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhp"
    "cyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxue3Vy"
    "bH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21l"
    "c3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93"
    "LiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAg"
    "ICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5v"
    "IGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tl"
    "bihjcmVkcykKICAgICAgICAgICAgICAgIHNlbGYuX2xvZygiW0dDYWxdW0RFQlVHXSB0b2tlbi5q"
    "c29uIHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhmIk9BdXRoIGZs"
    "b3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAg"
    "ICAgICAgICAgICAgIHJhaXNlCgogICAgICAgIHJldHVybiBjcmVkcwoKICAgIGRlZiBlbnN1cmVf"
    "c2VydmljZXMoc2VsZik6CiAgICAgICAgaWYgc2VsZi5fZHJpdmVfc2VydmljZSBpcyBub3QgTm9u"
    "ZSBhbmQgc2VsZi5fZG9jc19zZXJ2aWNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWRzID0gc2VsZi5fYXV0aGVudGljYXRlKCkKICAg"
    "ICAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZHJpdmUiLCAidjMi"
    "LCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gZ29v"
    "Z2xlX2J1aWxkKCJkb2NzIiwgInYxIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNl"
    "bGYuX2xvZygiRHJpdmUgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAg"
    "c2VsZi5fbG9nKCJEb2NzIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgYXV0aCBm"
    "YWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRG9j"
    "cyBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICByYWlzZQoK"
    "ICAgIGRlZiBsaXN0X2ZvbGRlcl9pdGVtcyhzZWxmLCBmb2xkZXJfaWQ6IHN0ciA9ICJyb290Iiwg"
    "cGFnZV9zaXplOiBpbnQgPSAxMDApOgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAg"
    "ICAgICBzYWZlX2ZvbGRlcl9pZCA9IChmb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJy"
    "b290IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGZpbGUgbGlzdCBmZXRjaCBzdGFydGVkLiBm"
    "b2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXNwb25z"
    "ZSA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5saXN0KAogICAgICAgICAgICBxPWYiJ3tz"
    "YWZlX2ZvbGRlcl9pZH0nIGluIHBhcmVudHMgYW5kIHRyYXNoZWQ9ZmFsc2UiLAogICAgICAgICAg"
    "ICBwYWdlU2l6ZT1tYXgoMSwgbWluKGludChwYWdlX3NpemUgb3IgMTAwKSwgMjAwKSksCiAgICAg"
    "ICAgICAgIG9yZGVyQnk9ImZvbGRlcixuYW1lLG1vZGlmaWVkVGltZSBkZXNjIiwKICAgICAgICAg"
    "ICAgZmllbGRzPSgKICAgICAgICAgICAgICAgICJmaWxlcygiCiAgICAgICAgICAgICAgICAiaWQs"
    "bmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplLCIKICAg"
    "ICAgICAgICAgICAgICJsYXN0TW9kaWZ5aW5nVXNlcihkaXNwbGF5TmFtZSxlbWFpbEFkZHJlc3Mp"
    "IgogICAgICAgICAgICAgICAgIikiCiAgICAgICAgICAgICksCiAgICAgICAgKS5leGVjdXRlKCkK"
    "ICAgICAgICBmaWxlcyA9IHJlc3BvbnNlLmdldCgiZmlsZXMiLCBbXSkKICAgICAgICBmb3IgaXRl"
    "bSBpbiBmaWxlczoKICAgICAgICAgICAgbWltZSA9IChpdGVtLmdldCgibWltZVR5cGUiKSBvciAi"
    "Iikuc3RyaXAoKQogICAgICAgICAgICBpdGVtWyJpc19mb2xkZXIiXSA9IG1pbWUgPT0gImFwcGxp"
    "Y2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiCiAgICAgICAgICAgIGl0ZW1bImlzX2dvb2ds"
    "ZV9kb2MiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIK"
    "ICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBpdGVtcyByZXR1cm5lZDoge2xlbihmaWxlcyl9IGZv"
    "bGRlcl9pZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJldHVybiBm"
    "aWxlcwoKICAgIGRlZiBnZXRfZG9jX3ByZXZpZXcoc2VsZiwgZG9jX2lkOiBzdHIsIG1heF9jaGFy"
    "czogaW50ID0gMTgwMCk6CiAgICAgICAgaWYgbm90IGRvY19pZDoKICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3Vy"
    "ZV9zZXJ2aWNlcygpCiAgICAgICAgZG9jID0gc2VsZi5fZG9jc19zZXJ2aWNlLmRvY3VtZW50cygp"
    "LmdldChkb2N1bWVudElkPWRvY19pZCkuZXhlY3V0ZSgpCiAgICAgICAgdGl0bGUgPSBkb2MuZ2V0"
    "KCJ0aXRsZSIpIG9yICJVbnRpdGxlZCIKICAgICAgICBib2R5ID0gZG9jLmdldCgiYm9keSIsIHt9"
    "KS5nZXQoImNvbnRlbnQiLCBbXSkKICAgICAgICBjaHVua3MgPSBbXQogICAgICAgIGZvciBibG9j"
    "ayBpbiBib2R5OgogICAgICAgICAgICBwYXJhZ3JhcGggPSBibG9jay5nZXQoInBhcmFncmFwaCIp"
    "CiAgICAgICAgICAgIGlmIG5vdCBwYXJhZ3JhcGg6CiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICBlbGVtZW50cyA9IHBhcmFncmFwaC5nZXQoImVsZW1lbnRzIiwgW10pCiAgICAg"
    "ICAgICAgIGZvciBlbCBpbiBlbGVtZW50czoKICAgICAgICAgICAgICAgIHJ1biA9IGVsLmdldCgi"
    "dGV4dFJ1biIpCiAgICAgICAgICAgICAgICBpZiBub3QgcnVuOgogICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgICAgICB0ZXh0ID0gKHJ1bi5nZXQoImNvbnRlbnQiKSBvciAi"
    "IikucmVwbGFjZSgiXHgwYiIsICJcbiIpCiAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAg"
    "ICAgICAgICAgICAgIGNodW5rcy5hcHBlbmQodGV4dCkKICAgICAgICBwYXJzZWQgPSAiIi5qb2lu"
    "KGNodW5rcykuc3RyaXAoKQogICAgICAgIGlmIGxlbihwYXJzZWQpID4gbWF4X2NoYXJzOgogICAg"
    "ICAgICAgICBwYXJzZWQgPSBwYXJzZWRbOm1heF9jaGFyc10ucnN0cmlwKCkgKyAi4oCmIgogICAg"
    "ICAgIHJldHVybiB7CiAgICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiZG9j"
    "dW1lbnRfaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJyZXZpc2lvbl9pZCI6IGRvYy5nZXQoInJl"
    "dmlzaW9uSWQiKSwKICAgICAgICAgICAgInByZXZpZXdfdGV4dCI6IHBhcnNlZCBvciAiW05vIHRl"
    "eHQgY29udGVudCByZXR1cm5lZCBmcm9tIERvY3MgQVBJLl0iLAogICAgICAgIH0KCiAgICBkZWYg"
    "Y3JlYXRlX2RvYyhzZWxmLCB0aXRsZTogc3RyID0gIk5ldyBHcmltVmVpbGUgUmVjb3JkIiwgcGFy"
    "ZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX3RpdGxlID0gKHRpdGxl"
    "IG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIpLnN0cmlwKCkgb3IgIk5ldyBHcmltVmVpbGUgUmVj"
    "b3JkIgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX3BhcmVudF9p"
    "ZCA9IChwYXJlbnRfZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAg"
    "ICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAg"
    "ICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfdGl0bGUsCiAgICAgICAgICAg"
    "ICAgICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwK"
    "ICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAg"
    "fSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJW"
    "aWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGRvY19pZCA9IGNy"
    "ZWF0ZWQuZ2V0KCJpZCIpCiAgICAgICAgbWV0YSA9IHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9j"
    "X2lkKSBpZiBkb2NfaWQgZWxzZSB7fQogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJpZCI6"
    "IGRvY19pZCwKICAgICAgICAgICAgIm5hbWUiOiBtZXRhLmdldCgibmFtZSIpIG9yIHNhZmVfdGl0"
    "bGUsCiAgICAgICAgICAgICJtaW1lVHlwZSI6IG1ldGEuZ2V0KCJtaW1lVHlwZSIpIG9yICJhcHBs"
    "aWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAibW9kaWZpZWRU"
    "aW1lIjogbWV0YS5nZXQoIm1vZGlmaWVkVGltZSIpLAogICAgICAgICAgICAid2ViVmlld0xpbmsi"
    "OiBtZXRhLmdldCgid2ViVmlld0xpbmsiKSwKICAgICAgICAgICAgInBhcmVudHMiOiBtZXRhLmdl"
    "dCgicGFyZW50cyIpIG9yIFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgfQoKICAgIGRlZiBjcmVh"
    "dGVfZm9sZGVyKHNlbGYsIG5hbWU6IHN0ciA9ICJOZXcgRm9sZGVyIiwgcGFyZW50X2ZvbGRlcl9p"
    "ZDogc3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX25hbWUgPSAobmFtZSBvciAiTmV3IEZvbGRl"
    "ciIpLnN0cmlwKCkgb3IgIk5ldyBGb2xkZXIiCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFy"
    "ZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5l"
    "bnN1cmVfc2VydmljZXMoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZp"
    "bGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAgICAgICAgICAgICJuYW1lIjog"
    "c2FmZV9uYW1lLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5n"
    "b29nbGUtYXBwcy5mb2xkZXIiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJl"
    "bnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5"
    "cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICkuZXhlY3V0ZSgp"
    "CiAgICAgICAgcmV0dXJuIGNyZWF0ZWQKCiAgICBkZWYgZ2V0X2ZpbGVfbWV0YWRhdGEoc2VsZiwg"
    "ZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2Ug"
    "VmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3Nl"
    "cnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmdldCgK"
    "ICAgICAgICAgICAgZmlsZUlkPWZpbGVfaWQsCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxt"
    "aW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplIiwKICAgICAgICAp"
    "LmV4ZWN1dGUoKQoKICAgIGRlZiBnZXRfZG9jX21ldGFkYXRhKHNlbGYsIGRvY19pZDogc3RyKToK"
    "ICAgICAgICByZXR1cm4gc2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpCgogICAgZGVmIGRl"
    "bGV0ZV9pdGVtKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAg"
    "ICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZS5maWxl"
    "cygpLmRlbGV0ZShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgogICAgZGVmIGRlbGV0ZV9kb2Mo"
    "c2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHNlbGYuZGVsZXRlX2l0ZW0oZG9jX2lkKQoKICAg"
    "IGRlZiBleHBvcnRfZG9jX3RleHQoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBk"
    "b2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVp"
    "cmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHBheWxvYWQgPSBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZXhwb3J0KAogICAgICAgICAgICBmaWxlSWQ9ZG9j"
    "X2lkLAogICAgICAgICAgICBtaW1lVHlwZT0idGV4dC9wbGFpbiIsCiAgICAgICAgKS5leGVjdXRl"
    "KCkKICAgICAgICBpZiBpc2luc3RhbmNlKHBheWxvYWQsIGJ5dGVzKToKICAgICAgICAgICAgcmV0"
    "dXJuIHBheWxvYWQuZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgcmV0"
    "dXJuIHN0cihwYXlsb2FkIG9yICIiKQoKICAgIGRlZiBkb3dubG9hZF9maWxlX2J5dGVzKHNlbGYs"
    "IGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNl"
    "IFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXRf"
    "bWVkaWEoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKCgoKIyDilIDilIAgUEFTUyAzIENPTVBM"
    "RVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIEFsbCB3b3JrZXIgdGhyZWFkcyBkZWZpbmVkLiBBbGwgZ2VuZXJhdGlvbiBp"
    "cyBzdHJlYW1pbmcuCiMgTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQgYW55d2hlcmUg"
    "aW4gdGhpcyBmaWxlLgojCiMgTmV4dDogUGFzcyA0IOKAlCBNZW1vcnkgJiBTdG9yYWdlCiMgKE1l"
    "bW9yeU1hbmFnZXIsIFNlc3Npb25NYW5hZ2VyLCBMZXNzb25zTGVhcm5lZERCLCBUYXNrTWFuYWdl"
    "cikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNDogTUVNT1JZICYgU1RP"
    "UkFHRQojCiMgU3lzdGVtcyBkZWZpbmVkIGhlcmU6CiMgICBEZXBlbmRlbmN5Q2hlY2tlciAgIOKA"
    "lCB2YWxpZGF0ZXMgYWxsIHJlcXVpcmVkIHBhY2thZ2VzIG9uIHN0YXJ0dXAKIyAgIE1lbW9yeU1h"
    "bmFnZXIgICAgICAg4oCUIEpTT05MIG1lbW9yeSByZWFkL3dyaXRlL3NlYXJjaAojICAgU2Vzc2lv"
    "bk1hbmFnZXIgICAgICDigJQgYXV0by1zYXZlLCBsb2FkLCBjb250ZXh0IGluamVjdGlvbiwgc2Vz"
    "c2lvbiBpbmRleAojICAgTGVzc29uc0xlYXJuZWREQiAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxl"
    "c2V0ICsgY29kZSBsZXNzb25zIGtub3dsZWRnZSBiYXNlCiMgICBUYXNrTWFuYWdlciAgICAgICAg"
    "IOKAlCB0YXNrL3JlbWluZGVyIENSVUQsIGR1ZS1ldmVudCBkZXRlY3Rpb24KIyDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAK"
    "CgojIOKUgOKUgCBERVBFTkRFTkNZIENIRUNLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERlcGVuZGVuY3lDaGVja2VyOgogICAg"
    "IiIiCiAgICBWYWxpZGF0ZXMgYWxsIHJlcXVpcmVkIGFuZCBvcHRpb25hbCBwYWNrYWdlcyBvbiBz"
    "dGFydHVwLgogICAgUmV0dXJucyBhIGxpc3Qgb2Ygc3RhdHVzIG1lc3NhZ2VzIGZvciB0aGUgRGlh"
    "Z25vc3RpY3MgdGFiLgogICAgU2hvd3MgYSBibG9ja2luZyBlcnJvciBkaWFsb2cgZm9yIGFueSBj"
    "cml0aWNhbCBtaXNzaW5nIGRlcGVuZGVuY3kuCiAgICAiIiIKCiAgICAjIChwYWNrYWdlX25hbWUs"
    "IGltcG9ydF9uYW1lLCBjcml0aWNhbCwgaW5zdGFsbF9oaW50KQogICAgUEFDS0FHRVMgPSBbCiAg"
    "ICAgICAgKCJQeVNpZGU2IiwgICAgICAgICAgICAgICAgICAgIlB5U2lkZTYiLCAgICAgICAgICAg"
    "ICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIFB5U2lkZTYiKSwKICAgICAgICAoImxvZ3Vy"
    "dSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiwgICAgICAgICAgICAgICBUcnVlLAogICAg"
    "ICAgICAicGlwIGluc3RhbGwgbG9ndXJ1IiksCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAg"
    "ICAgICAgICAgImFwc2NoZWR1bGVyIiwgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0"
    "YWxsIGFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAgICAgICAgICAg"
    "InB5Z2FtZSIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweWdh"
    "bWUgIChuZWVkZWQgZm9yIHNvdW5kKSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAg"
    "ICAgICAgICJ3aW4zMmNvbSIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3Rh"
    "bGwgcHl3aW4zMiAgKG5lZWRlZCBmb3IgZGVza3RvcCBzaG9ydGN1dCkiKSwKICAgICAgICAoInBz"
    "dXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiwgICAgICAgICAgICAgICBGYWxzZSwK"
    "ICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCAgKG5lZWRlZCBmb3Igc3lzdGVtIG1vbml0b3Jp"
    "bmcpIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiwg"
    "ICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCByZXF1ZXN0cyIpLAogICAg"
    "ICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJnb29nbGVhcGljbGllbnQiLCAgICAg"
    "IEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Iiks"
    "CiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29hdXRo"
    "bGliIiwgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aC1vYXV0aGxpYiIp"
    "LAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIsICAg"
    "ICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgiKSwKICAgICAg"
    "ICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9yY2giLCAgICAgICAgICAgICAgICBG"
    "YWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2Fs"
    "IG1vZGVsKSIpLAogICAgICAgICgidHJhbnNmb3JtZXJzIiwgICAgICAgICAgICAgICJ0cmFuc2Zv"
    "cm1lcnMiLCAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdHJhbnNmb3JtZXJz"
    "ICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgicHludm1sIiwgICAg"
    "ICAgICAgICAgICAgICAgICJweW52bWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgcHludm1sICAob25seSBuZWVkZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmlu"
    "ZykiKSwKICAgIF0KCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVjayhjbHMpIC0+IHR1cGxl"
    "W2xpc3Rbc3RyXSwgbGlzdFtzdHJdXToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm5zIChtZXNz"
    "YWdlcywgY3JpdGljYWxfZmFpbHVyZXMpLgogICAgICAgIG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQ"
    "U10gcGFja2FnZSDinJMv4pyXIOKAlCBub3RlIiBzdHJpbmdzCiAgICAgICAgY3JpdGljYWxfZmFp"
    "bHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3JpdGljYWwgYW5kIG1pc3NpbmcKICAg"
    "ICAgICAiIiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0gW10K"
    "ICAgICAgICBjcml0aWNhbCAgPSBbXQoKICAgICAgICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1l"
    "LCBpc19jcml0aWNhbCwgaGludCBpbiBjbHMuUEFDS0FHRVM6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAg"
    "ICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyTIikKICAgICAg"
    "ICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJ"
    "Q0FMIiBpZiBpc19jcml0aWNhbCBlbHNlICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3Nh"
    "Z2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltERVBTXSB7cGtnX25hbWV9IOKclyAo"
    "e3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBp"
    "ZiBpc19jcml0aWNhbDoKICAgICAgICAgICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25h"
    "bWUpCgogICAgICAgIHJldHVybiBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QK"
    "ICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAtPiBzdHI6CiAgICAgICAgIiIiQ2hlY2sgaWYgT2xs"
    "YW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0cmluZy4iIiIKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0"
    "OjExNDM0L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9w"
    "ZW4ocmVxLCB0aW1lb3V0PTIpCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzID09IDIwMDoKICAg"
    "ICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJMg4oCUIHJ1bm5pbmcgb24gbG9j"
    "YWxob3N0OjExNDM0IgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MK"
    "ICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAob25seSBu"
    "ZWVkZWQgZm9yIE9sbGFtYSBtb2RlbCB0eXBlKSIKCgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgTWVtb3J5TWFuYWdlcjoKICAgICIiIgogICAgSGFuZGxlcyBhbGwgSlNP"
    "TkwgbWVtb3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFuYWdlZDoKICAgICAgICBtZW1vcmll"
    "cy9tZXNzYWdlcy5qc29ubCAgICAgICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBlZAog"
    "ICAgICAgIG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAgICAg4oCUIGV4dHJhY3RlZCBtZW1v"
    "cnkgcmVjb3JkcwogICAgICAgIG1lbW9yaWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg4oCUIGVu"
    "dGl0eSBzdGF0ZQogICAgICAgIG1lbW9yaWVzL2luZGV4Lmpzb24gICAgICAgICAgICAg4oCUIGNv"
    "dW50cyBhbmQgbWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5mZXJlbmNl"
    "LCBrZXl3b3JkIGV4dHJhY3Rpb24sIHRhZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUg"
    "ZGV0ZWN0aW9uLCBhbmQgcmVsZXZhbmNlIHNjb3JpbmcgZm9yIGNvbnRleHQgaW5qZWN0aW9uLgog"
    "ICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIGJhc2UgICAgICAgICAgICAg"
    "PSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAgPSBiYXNlIC8g"
    "Im1lc3NhZ2VzLmpzb25sIgogICAgICAgIHNlbGYubWVtb3JpZXNfcCAgPSBiYXNlIC8gIm1lbW9y"
    "aWVzLmpzb25sIgogICAgICAgIHNlbGYuc3RhdGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24i"
    "CiAgICAgICAgc2VsZi5pbmRleF9wICAgICA9IGJhc2UgLyAiaW5kZXguanNvbiIKCiAgICAjIOKU"
    "gOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2Rl"
    "ZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMo"
    "c2VsZi5zdGF0ZV9wLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAg"
    "ZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5z"
    "dGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0y"
    "KSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2Vs"
    "ZikgLT4gZGljdDoKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAicGVyc29uYV9uYW1lIjog"
    "ICAgICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAiZGVja192ZXJzaW9uIjogICAgICAg"
    "ICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAgICAgICJzZXNzaW9uX2NvdW50IjogICAgICAgICAg"
    "ICAwLAogICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwKICAgICAg"
    "ICAgICAgImxhc3Rfc2h1dGRvd24iOiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0"
    "X2FjdGl2ZSI6ICAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAidG90YWxfbWVzc2FnZXMi"
    "OiAgICAgICAgICAgMCwKICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogICAgICAgICAgIDAs"
    "CiAgICAgICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAgICAgICB7fSwKICAgICAgICAgICAg"
    "InZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiJET1JNQU5UIiwKICAgICAgICB9CgogICAgIyDi"
    "lIDilIAgTUVTU0FHRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lc3NhZ2Uoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCBy"
    "b2xlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgY29udGVudDogc3RyLCBlbW90aW9uOiBz"
    "dHIgPSAiIikgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAg"
    "ICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0"
    "YW1wIjogIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiBzZXNzaW9u"
    "X2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgInJv"
    "bGUiOiAgICAgICByb2xlLAogICAgICAgICAgICAiY29udGVudCI6ICAgIGNvbnRlbnQsCiAgICAg"
    "ICAgICAgICJlbW90aW9uIjogICAgZW1vdGlvbiwKICAgICAgICB9CiAgICAgICAgYXBwZW5kX2pz"
    "b25sKHNlbGYubWVzc2FnZXNfcCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBk"
    "ZWYgbG9hZF9yZWNlbnRfbWVzc2FnZXMoc2VsZiwgbGltaXQ6IGludCA9IDIwKSAtPiBsaXN0W2Rp"
    "Y3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYubWVzc2FnZXNfcClbLWxpbWl0Ol0K"
    "CiAgICAjIOKUgOKUgCBNRU1PUklFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVtb3J5KHNlbGYsIHNlc3Npb25faWQ6"
    "IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4"
    "dDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZWNvcmRfdHlwZSA9IGluZmVyX3Jl"
    "Y29yZF90eXBlKHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQpCiAgICAgICAga2V5d29yZHMgICAg"
    "PSBleHRyYWN0X2tleXdvcmRzKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KQogICAg"
    "ICAgIHRhZ3MgICAgICAgID0gc2VsZi5faW5mZXJfdGFncyhyZWNvcmRfdHlwZSwgdXNlcl90ZXh0"
    "LCBrZXl3b3JkcykKICAgICAgICB0aXRsZSAgICAgICA9IHNlbGYuX2luZmVyX3RpdGxlKHJlY29y"
    "ZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHN1bW1hcnkgICAgID0gc2VsZi5f"
    "c3VtbWFyaXplKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQoKICAgICAg"
    "ICBtZW1vcnkgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgZiJtZW1fe3V1aWQu"
    "dXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogICAgICAgIGxvY2Fs"
    "X25vd19pc28oKSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICAgICBzZXNzaW9uX2lkLAog"
    "ICAgICAgICAgICAicGVyc29uYSI6ICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgInR5"
    "cGUiOiAgICAgICAgICAgICByZWNvcmRfdHlwZSwKICAgICAgICAgICAgInRpdGxlIjogICAgICAg"
    "ICAgICB0aXRsZSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICAgICBzdW1tYXJ5LAogICAg"
    "ICAgICAgICAiY29udGVudCI6ICAgICAgICAgIHVzZXJfdGV4dFs6NDAwMF0sCiAgICAgICAgICAg"
    "ICJhc3Npc3RhbnRfY29udGV4dCI6YXNzaXN0YW50X3RleHRbOjEyMDBdLAogICAgICAgICAgICAi"
    "a2V5d29yZHMiOiAgICAgICAgIGtleXdvcmRzLAogICAgICAgICAgICAidGFncyI6ICAgICAgICAg"
    "ICAgIHRhZ3MsCiAgICAgICAgICAgICJjb25maWRlbmNlIjogICAgICAgMC43MCBpZiByZWNvcmRf"
    "dHlwZSBpbiB7CiAgICAgICAgICAgICAgICAiZHJlYW0iLCJpc3N1ZSIsImlkZWEiLCJwcmVmZXJl"
    "bmNlIiwicmVzb2x1dGlvbiIKICAgICAgICAgICAgfSBlbHNlIDAuNTUsCiAgICAgICAgfQoKICAg"
    "ICAgICBpZiBzZWxmLl9pc19uZWFyX2R1cGxpY2F0ZShtZW1vcnkpOgogICAgICAgICAgICByZXR1"
    "cm4gTm9uZQoKICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5tZW1vcmllc19wLCBtZW1vcnkpCiAg"
    "ICAgICAgcmV0dXJuIG1lbW9yeQoKICAgIGRlZiBzZWFyY2hfbWVtb3JpZXMoc2VsZiwgcXVlcnk6"
    "IHN0ciwgbGltaXQ6IGludCA9IDYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAg"
    "S2V5d29yZC1zY29yZWQgbWVtb3J5IHNlYXJjaC4KICAgICAgICBSZXR1cm5zIHVwIHRvIGBsaW1p"
    "dGAgcmVjb3JkcyBzb3J0ZWQgYnkgcmVsZXZhbmNlIHNjb3JlIGRlc2NlbmRpbmcuCiAgICAgICAg"
    "RmFsbHMgYmFjayB0byBtb3N0IHJlY2VudCBpZiBubyBxdWVyeSB0ZXJtcyBtYXRjaC4KICAgICAg"
    "ICAiIiIKICAgICAgICBtZW1vcmllcyA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKQogICAg"
    "ICAgIGlmIG5vdCBxdWVyeS5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4gbWVtb3JpZXNbLWxp"
    "bWl0Ol0KCiAgICAgICAgcV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKHF1ZXJ5LCBsaW1p"
    "dD0xNikpCiAgICAgICAgc2NvcmVkICA9IFtdCgogICAgICAgIGZvciBpdGVtIGluIG1lbW9yaWVz"
    "OgogICAgICAgICAgICBpdGVtX3Rlcm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMoIiAiLmpvaW4o"
    "WwogICAgICAgICAgICAgICAgaXRlbS5nZXQoInRpdGxlIiwgICAiIiksCiAgICAgICAgICAgICAg"
    "ICBpdGVtLmdldCgic3VtbWFyeSIsICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJjb250"
    "ZW50IiwgIiIpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoImtleXdvcmRzIiwg"
    "W10pKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJ0YWdzIiwgICAgIFtdKSks"
    "CiAgICAgICAgICAgIF0pLCBsaW1pdD00MCkpCgogICAgICAgICAgICBzY29yZSA9IGxlbihxX3Rl"
    "cm1zICYgaXRlbV90ZXJtcykKCiAgICAgICAgICAgICMgQm9vc3QgYnkgdHlwZSBtYXRjaAogICAg"
    "ICAgICAgICBxbCA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICAgICAgcnQgPSBpdGVtLmdldCgidHlw"
    "ZSIsICIiKQogICAgICAgICAgICBpZiAiZHJlYW0iICBpbiBxbCBhbmQgcnQgPT0gImRyZWFtIjog"
    "ICAgc2NvcmUgKz0gNAogICAgICAgICAgICBpZiAidGFzayIgICBpbiBxbCBhbmQgcnQgPT0gInRh"
    "c2siOiAgICAgc2NvcmUgKz0gMwogICAgICAgICAgICBpZiAiaWRlYSIgICBpbiBxbCBhbmQgcnQg"
    "PT0gImlkZWEiOiAgICAgc2NvcmUgKz0gMgogICAgICAgICAgICBpZiAibHNsIiAgICBpbiBxbCBh"
    "bmQgcnQgaW4geyJpc3N1ZSIsInJlc29sdXRpb24ifTogc2NvcmUgKz0gMgoKICAgICAgICAgICAg"
    "aWYgc2NvcmUgPiAwOgogICAgICAgICAgICAgICAgc2NvcmVkLmFwcGVuZCgoc2NvcmUsIGl0ZW0p"
    "KQoKICAgICAgICBzY29yZWQuc29ydChrZXk9bGFtYmRhIHg6ICh4WzBdLCB4WzFdLmdldCgidGlt"
    "ZXN0YW1wIiwgIiIpKSwKICAgICAgICAgICAgICAgICAgICByZXZlcnNlPVRydWUpCiAgICAgICAg"
    "cmV0dXJuIFtpdGVtIGZvciBfLCBpdGVtIGluIHNjb3JlZFs6bGltaXRdXQoKICAgIGRlZiBidWls"
    "ZF9jb250ZXh0X2Jsb2NrKHNlbGYsIHF1ZXJ5OiBzdHIsIG1heF9jaGFyczogaW50ID0gMjAwMCkg"
    "LT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgZnJvbSBy"
    "ZWxldmFudCBtZW1vcmllcyBmb3IgcHJvbXB0IGluamVjdGlvbi4KICAgICAgICBUcnVuY2F0ZXMg"
    "dG8gbWF4X2NoYXJzIHRvIHByb3RlY3QgdGhlIGNvbnRleHQgd2luZG93LgogICAgICAgICIiIgog"
    "ICAgICAgIG1lbW9yaWVzID0gc2VsZi5zZWFyY2hfbWVtb3JpZXMocXVlcnksIGxpbWl0PTQpCiAg"
    "ICAgICAgaWYgbm90IG1lbW9yaWVzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAgcGFy"
    "dHMgPSBbIltSRUxFVkFOVCBNRU1PUklFU10iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZv"
    "ciBtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBlbnRyeSA9ICgKICAgICAgICAgICAgICAgIGYi"
    "4oCiIFt7bS5nZXQoJ3R5cGUnLCcnKS51cHBlcigpfV0ge20uZ2V0KCd0aXRsZScsJycpfTogIgog"
    "ICAgICAgICAgICAgICAgZiJ7bS5nZXQoJ3N1bW1hcnknLCcnKX0iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3Rh"
    "bCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZCgiW0VORCBNRU1PUklFU10iKQog"
    "ICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAgIyDilIDilIAgSEVMUEVSUyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBfaXNfbmVhcl9kdXBsaWNhdGUoc2VsZiwgY2FuZGlkYXRlOiBkaWN0KSAtPiBib29sOgogICAg"
    "ICAgIHJlY2VudCA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKVstMjU6XQogICAgICAgIGN0"
    "ID0gY2FuZGlkYXRlLmdldCgidGl0bGUiLCAiIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgY3Mg"
    "PSBjYW5kaWRhdGUuZ2V0KCJzdW1tYXJ5IiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGZv"
    "ciBpdGVtIGluIHJlY2VudDoKICAgICAgICAgICAgaWYgaXRlbS5nZXQoInRpdGxlIiwiIikubG93"
    "ZXIoKS5zdHJpcCgpID09IGN0OiAgcmV0dXJuIFRydWUKICAgICAgICAgICAgaWYgaXRlbS5nZXQo"
    "InN1bW1hcnkiLCIiKS5sb3dlcigpLnN0cmlwKCkgPT0gY3M6IHJldHVybiBUcnVlCiAgICAgICAg"
    "cmV0dXJuIEZhbHNlCgogICAgZGVmIF9pbmZlcl90YWdzKHNlbGYsIHJlY29yZF90eXBlOiBzdHIs"
    "IHRleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBs"
    "aXN0W3N0cl06CiAgICAgICAgdCAgICA9IHRleHQubG93ZXIoKQogICAgICAgIHRhZ3MgPSBbcmVj"
    "b3JkX3R5cGVdCiAgICAgICAgaWYgImRyZWFtIiAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJkcmVhbSIp"
    "CiAgICAgICAgaWYgImxzbCIgICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJsc2wiKQogICAgICAgIGlm"
    "ICJweXRob24iICBpbiB0OiB0YWdzLmFwcGVuZCgicHl0aG9uIikKICAgICAgICBpZiAiZ2FtZSIg"
    "ICAgaW4gdDogdGFncy5hcHBlbmQoImdhbWVfaWRlYSIpCiAgICAgICAgaWYgInNsIiAgICAgIGlu"
    "IHQgb3IgInNlY29uZCBsaWZlIiBpbiB0OiB0YWdzLmFwcGVuZCgic2Vjb25kbGlmZSIpCiAgICAg"
    "ICAgaWYgREVDS19OQU1FLmxvd2VyKCkgaW4gdDogdGFncy5hcHBlbmQoREVDS19OQU1FLmxvd2Vy"
    "KCkpCiAgICAgICAgZm9yIGt3IGluIGtleXdvcmRzWzo0XToKICAgICAgICAgICAgaWYga3cgbm90"
    "IGluIHRhZ3M6CiAgICAgICAgICAgICAgICB0YWdzLmFwcGVuZChrdykKICAgICAgICAjIERlZHVw"
    "bGljYXRlIHByZXNlcnZpbmcgb3JkZXIKICAgICAgICBzZWVuLCBvdXQgPSBzZXQoKSwgW10KICAg"
    "ICAgICBmb3IgdGFnIGluIHRhZ3M6CiAgICAgICAgICAgIGlmIHRhZyBub3QgaW4gc2VlbjoKICAg"
    "ICAgICAgICAgICAgIHNlZW4uYWRkKHRhZykKICAgICAgICAgICAgICAgIG91dC5hcHBlbmQodGFn"
    "KQogICAgICAgIHJldHVybiBvdXRbOjEyXQoKICAgIGRlZiBfaW5mZXJfdGl0bGUoc2VsZiwgcmVj"
    "b3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgIGtleXdv"
    "cmRzOiBsaXN0W3N0cl0pIC0+IHN0cjoKICAgICAgICBkZWYgY2xlYW4od29yZHMpOgogICAgICAg"
    "ICAgICByZXR1cm4gW3cuc3RyaXAoIiAtXy4sIT8iKS5jYXBpdGFsaXplKCkKICAgICAgICAgICAg"
    "ICAgICAgICBmb3IgdyBpbiB3b3JkcyBpZiBsZW4odykgPiAyXQoKICAgICAgICBpZiByZWNvcmRf"
    "dHlwZSA9PSAidGFzayI6CiAgICAgICAgICAgIGltcG9ydCByZQogICAgICAgICAgICBtID0gcmUu"
    "c2VhcmNoKHIicmVtaW5kIG1lIC4qPyB0byAoLispIiwgdXNlcl90ZXh0LCByZS5JKQogICAgICAg"
    "ICAgICBpZiBtOgogICAgICAgICAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXI6IHttLmdyb3VwKDEp"
    "LnN0cmlwKClbOjYwXX0iCiAgICAgICAgICAgIHJldHVybiAiUmVtaW5kZXIgVGFzayIKICAgICAg"
    "ICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOgogICAgICAgICAgICByZXR1cm4gZiJ7JyAnLmpv"
    "aW4oY2xlYW4oa2V5d29yZHNbOjNdKSl9IERyZWFtIi5zdHJpcCgpIG9yICJEcmVhbSBNZW1vcnki"
    "CiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjoKICAgICAgICAgICAgcmV0dXJuIGYi"
    "SXNzdWU6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIlRlY2hu"
    "aWNhbCBJc3N1ZSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6CiAgICAg"
    "ICAgICAgIHJldHVybiBmIlJlc29sdXRpb246IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0p"
    "KX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBSZXNvbHV0aW9uIgogICAgICAgIGlmIHJlY29yZF90"
    "eXBlID09ICJpZGVhIjoKICAgICAgICAgICAgcmV0dXJuIGYiSWRlYTogeycgJy5qb2luKGNsZWFu"
    "KGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiSWRlYSIKICAgICAgICBpZiBrZXl3b3JkczoK"
    "ICAgICAgICAgICAgcmV0dXJuICIgIi5qb2luKGNsZWFuKGtleXdvcmRzWzo1XSkpIG9yICJDb252"
    "ZXJzYXRpb24gTWVtb3J5IgogICAgICAgIHJldHVybiAiQ29udmVyc2F0aW9uIE1lbW9yeSIKCiAg"
    "ICBkZWYgX3N1bW1hcml6ZShzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwK"
    "ICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IHN0cjoKICAgICAgICB1"
    "ID0gdXNlcl90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBhID0gYXNzaXN0YW50X3RleHQuc3Ry"
    "aXAoKVs6MjIwXQogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJkcmVhbSI6ICAgICAgIHJldHVy"
    "biBmIlVzZXIgZGVzY3JpYmVkIGEgZHJlYW06IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAidGFzayI6ICAgICAgICByZXR1cm4gZiJSZW1pbmRlci90YXNrOiB7dX0iCiAgICAgICAgaWYg"
    "cmVjb3JkX3R5cGUgPT0gImlzc3VlIjogICAgICAgcmV0dXJuIGYiVGVjaG5pY2FsIGlzc3VlOiB7"
    "dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOiAgcmV0dXJuIGYiU29s"
    "dXRpb24gcmVjb3JkZWQ6IHthIG9yIHV9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVh"
    "IjogICAgICAgIHJldHVybiBmIklkZWEgZGlzY3Vzc2VkOiB7dX0iCiAgICAgICAgaWYgcmVjb3Jk"
    "X3R5cGUgPT0gInByZWZlcmVuY2UiOiAgcmV0dXJuIGYiUHJlZmVyZW5jZSBub3RlZDoge3V9Igog"
    "ICAgICAgIHJldHVybiBmIkNvbnZlcnNhdGlvbjoge3V9IgoKCiMg4pSA4pSAIFNFU1NJT04gTUFO"
    "QUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU2Vzc2lvbk1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgY29u"
    "dmVyc2F0aW9uIHNlc3Npb25zLgoKICAgIEF1dG8tc2F2ZTogZXZlcnkgMTAgbWludXRlcyAoQVBT"
    "Y2hlZHVsZXIpLCBtaWRuaWdodC10by1taWRuaWdodCBib3VuZGFyeS4KICAgIEZpbGU6IHNlc3Np"
    "b25zL1lZWVktTU0tREQuanNvbmwg4oCUIG92ZXJ3cml0ZXMgb24gZWFjaCBzYXZlLgogICAgSW5k"
    "ZXg6IHNlc3Npb25zL3Nlc3Npb25faW5kZXguanNvbiDigJQgb25lIGVudHJ5IHBlciBkYXkuCgog"
    "ICAgU2Vzc2lvbnMgYXJlIGxvYWRlZCBhcyBjb250ZXh0IGluamVjdGlvbiAobm90IHJlYWwgbWVt"
    "b3J5KSB1bnRpbAogICAgdGhlIFNRTGl0ZS9DaHJvbWFEQiBzeXN0ZW0gaXMgYnVpbHQgaW4gUGhh"
    "c2UgMi4KICAgICIiIgoKICAgIEFVVE9TQVZFX0lOVEVSVkFMID0gMTAgICAjIG1pbnV0ZXMKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnNfZGlyICA9IGNmZ19w"
    "YXRoKCJzZXNzaW9ucyIpCiAgICAgICAgc2VsZi5faW5kZXhfcGF0aCAgICA9IHNlbGYuX3Nlc3Np"
    "b25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAg"
    "ICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0i"
    "CiAgICAgICAgc2VsZi5fY3VycmVudF9kYXRlICA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQog"
    "ICAgICAgIHNlbGYuX21lc3NhZ2VzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9sb2Fk"
    "ZWRfam91cm5hbDogT3B0aW9uYWxbc3RyXSA9IE5vbmUgICMgZGF0ZSBvZiBsb2FkZWQgam91cm5h"
    "bAoKICAgICMg4pSA4pSAIENVUlJFTlQgU0VTU0lPTiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBhZGRfbWVzc2FnZShzZWxmLCByb2xlOiBzdHIsIGNvbnRlbnQ6IHN0ciwK"
    "ICAgICAgICAgICAgICAgICAgICBlbW90aW9uOiBzdHIgPSAiIiwgdGltZXN0YW1wOiBzdHIgPSAi"
    "IikgLT4gTm9uZToKICAgICAgICBzZWxmLl9tZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjhdfSIsCiAgICAgICAgICAgICJ0"
    "aW1lc3RhbXAiOiB0aW1lc3RhbXAgb3IgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAicm9s"
    "ZSI6ICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgIGNvbnRlbnQsCiAgICAgICAg"
    "ICAgICJlbW90aW9uIjogICBlbW90aW9uLAogICAgICAgIH0pCgogICAgZGVmIGdldF9oaXN0b3J5"
    "KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJuIGhpc3Rvcnkg"
    "aW4gTExNLWZyaWVuZGx5IGZvcm1hdC4KICAgICAgICBbeyJyb2xlIjogInVzZXIifCJhc3Npc3Rh"
    "bnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gWwogICAg"
    "ICAgICAgICB7InJvbGUiOiBtWyJyb2xlIl0sICJjb250ZW50IjogbVsiY29udGVudCJdfQogICAg"
    "ICAgICAgICBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcwogICAgICAgICAgICBpZiBtWyJyb2xlIl0g"
    "aW4gKCJ1c2VyIiwgImFzc2lzdGFudCIpCiAgICAgICAgXQoKICAgIEBwcm9wZXJ0eQogICAgZGVm"
    "IHNlc3Npb25faWQoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9zZXNzaW9uX2lk"
    "CgogICAgQHByb3BlcnR5CiAgICBkZWYgbWVzc2FnZV9jb3VudChzZWxmKSAtPiBpbnQ6CiAgICAg"
    "ICAgcmV0dXJuIGxlbihzZWxmLl9tZXNzYWdlcykKCiAgICAjIOKUgOKUgCBTQVZFIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgZGVmIHNhdmUoc2VsZiwgYWlfZ2VuZXJhdGVkX25hbWU6IHN0ciA9ICIiKSAtPiBOb25lOgog"
    "ICAgICAgICIiIgogICAgICAgIFNhdmUgY3VycmVudCBzZXNzaW9uIHRvIHNlc3Npb25zL1lZWVkt"
    "TU0tREQuanNvbmwuCiAgICAgICAgT3ZlcndyaXRlcyB0aGUgZmlsZSBmb3IgdG9kYXkg4oCUIGVh"
    "Y2ggc2F2ZSBpcyBhIGZ1bGwgc25hcHNob3QuCiAgICAgICAgVXBkYXRlcyBzZXNzaW9uX2luZGV4"
    "Lmpzb24uCiAgICAgICAgIiIiCiAgICAgICAgdG9kYXkgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0"
    "KCkKICAgICAgICBvdXRfcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3RvZGF5fS5qc29u"
    "bCIKCiAgICAgICAgIyBXcml0ZSBhbGwgbWVzc2FnZXMKICAgICAgICB3cml0ZV9qc29ubChvdXRf"
    "cGF0aCwgc2VsZi5fbWVzc2FnZXMpCgogICAgICAgICMgVXBkYXRlIGluZGV4CiAgICAgICAgaW5k"
    "ZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBleGlzdGluZyA9IG5leHQoCiAgICAgICAg"
    "ICAgIChzIGZvciBzIGluIGluZGV4WyJzZXNzaW9ucyJdIGlmIHNbImRhdGUiXSA9PSB0b2RheSks"
    "IE5vbmUKICAgICAgICApCgogICAgICAgIG5hbWUgPSBhaV9nZW5lcmF0ZWRfbmFtZSBvciBleGlz"
    "dGluZy5nZXQoIm5hbWUiLCAiIikgaWYgZXhpc3RpbmcgZWxzZSAiIgogICAgICAgIGlmIG5vdCBu"
    "YW1lIGFuZCBzZWxmLl9tZXNzYWdlczoKICAgICAgICAgICAgIyBBdXRvLW5hbWUgZnJvbSBmaXJz"
    "dCB1c2VyIG1lc3NhZ2UgKGZpcnN0IDUgd29yZHMpCiAgICAgICAgICAgIGZpcnN0X3VzZXIgPSBu"
    "ZXh0KAogICAgICAgICAgICAgICAgKG1bImNvbnRlbnQiXSBmb3IgbSBpbiBzZWxmLl9tZXNzYWdl"
    "cyBpZiBtWyJyb2xlIl0gPT0gInVzZXIiKSwKICAgICAgICAgICAgICAgICIiCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgd29yZHMgPSBmaXJzdF91c2VyLnNwbGl0KClbOjVdCiAgICAgICAgICAg"
    "IG5hbWUgID0gIiAiLmpvaW4od29yZHMpIGlmIHdvcmRzIGVsc2UgZiJTZXNzaW9uIHt0b2RheX0i"
    "CgogICAgICAgIGVudHJ5ID0gewogICAgICAgICAgICAiZGF0ZSI6ICAgICAgICAgIHRvZGF5LAog"
    "ICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAgIHNlbGYuX3Nlc3Npb25faWQsCiAgICAgICAgICAg"
    "ICJuYW1lIjogICAgICAgICAgbmFtZSwKICAgICAgICAgICAgIm1lc3NhZ2VfY291bnQiOiBsZW4o"
    "c2VsZi5fbWVzc2FnZXMpLAogICAgICAgICAgICAiZmlyc3RfbWVzc2FnZSI6IChzZWxmLl9tZXNz"
    "YWdlc1swXVsidGltZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgc2Vs"
    "Zi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgICAgICJsYXN0X21lc3NhZ2UiOiAgKHNlbGYu"
    "X21lc3NhZ2VzWy0xXVsidGltZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "aWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgfQoKICAgICAgICBpZiBleGlzdGlu"
    "ZzoKICAgICAgICAgICAgaWR4ID0gaW5kZXhbInNlc3Npb25zIl0uaW5kZXgoZXhpc3RpbmcpCiAg"
    "ICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdW2lkeF0gPSBlbnRyeQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdLmluc2VydCgwLCBlbnRyeSkKCiAgICAgICAgIyBL"
    "ZWVwIGxhc3QgMzY1IGRheXMgaW4gaW5kZXgKICAgICAgICBpbmRleFsic2Vzc2lvbnMiXSA9IGlu"
    "ZGV4WyJzZXNzaW9ucyJdWzozNjVdCiAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKCiAg"
    "ICAjIOKUgOKUgCBMT0FEIC8gSk9VUk5BTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBsaXN0X3Nlc3Npb25zKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIi"
    "UmV0dXJuIGFsbCBzZXNzaW9ucyBmcm9tIGluZGV4LCBuZXdlc3QgZmlyc3QuIiIiCiAgICAgICAg"
    "cmV0dXJuIHNlbGYuX2xvYWRfaW5kZXgoKS5nZXQoInNlc3Npb25zIiwgW10pCgogICAgZGVmIGxv"
    "YWRfc2Vzc2lvbl9hc19jb250ZXh0KHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyKSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgTG9hZCBhIHBhc3Qgc2Vzc2lvbiBhcyBhIGNvbnRleHQgaW5qZWN0"
    "aW9uIHN0cmluZy4KICAgICAgICBSZXR1cm5zIGZvcm1hdHRlZCB0ZXh0IHRvIHByZXBlbmQgdG8g"
    "dGhlIHN5c3RlbSBwcm9tcHQuCiAgICAgICAgVGhpcyBpcyBOT1QgcmVhbCBtZW1vcnkg4oCUIGl0"
    "J3MgYSB0ZW1wb3JhcnkgY29udGV4dCB3aW5kb3cgaW5qZWN0aW9uCiAgICAgICAgdW50aWwgdGhl"
    "IFBoYXNlIDIgbWVtb3J5IHN5c3RlbSBpcyBidWlsdC4KICAgICAgICAiIiIKICAgICAgICBwYXRo"
    "ID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gZiJ7c2Vzc2lvbl9kYXRlfS5qc29ubCIKICAgICAgICBp"
    "ZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIG1lc3Nh"
    "Z2VzID0gcmVhZF9qc29ubChwYXRoKQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gc2Vz"
    "c2lvbl9kYXRlCgogICAgICAgIGxpbmVzID0gW2YiW0pPVVJOQUwgTE9BREVEIOKAlCB7c2Vzc2lv"
    "bl9kYXRlfV0iLAogICAgICAgICAgICAgICAgICJUaGUgZm9sbG93aW5nIGlzIGEgcmVjb3JkIG9m"
    "IGEgcHJpb3IgY29udmVyc2F0aW9uLiIsCiAgICAgICAgICAgICAgICAgIlVzZSB0aGlzIGFzIGNv"
    "bnRleHQgZm9yIHRoZSBjdXJyZW50IHNlc3Npb246XG4iXQoKICAgICAgICAjIEluY2x1ZGUgdXAg"
    "dG8gbGFzdCAzMCBtZXNzYWdlcyBmcm9tIHRoYXQgc2Vzc2lvbgogICAgICAgIGZvciBtc2cgaW4g"
    "bWVzc2FnZXNbLTMwOl06CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgIj8i"
    "KS51cHBlcigpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpWzoz"
    "MDBdCiAgICAgICAgICAgIHRzICAgICAgPSBtc2cuZ2V0KCJ0aW1lc3RhbXAiLCAiIilbOjE2XQog"
    "ICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJbe3RzfV0ge3JvbGV9OiB7Y29udGVudH0iKQoKICAg"
    "ICAgICBsaW5lcy5hcHBlbmQoIltFTkQgSk9VUk5BTF0iKQogICAgICAgIHJldHVybiAiXG4iLmpv"
    "aW4obGluZXMpCgogICAgZGVmIGNsZWFyX2xvYWRlZF9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwgPSBOb25lCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "bG9hZGVkX2pvdXJuYWxfZGF0ZShzZWxmKSAtPiBPcHRpb25hbFtzdHJdOgogICAgICAgIHJldHVy"
    "biBzZWxmLl9sb2FkZWRfam91cm5hbAoKICAgIGRlZiByZW5hbWVfc2Vzc2lvbihzZWxmLCBzZXNz"
    "aW9uX2RhdGU6IHN0ciwgbmV3X25hbWU6IHN0cikgLT4gYm9vbDoKICAgICAgICAiIiJSZW5hbWUg"
    "YSBzZXNzaW9uIGluIHRoZSBpbmRleC4gUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIiIiCiAgICAg"
    "ICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBmb3IgZW50cnkgaW4gaW5kZXhb"
    "InNlc3Npb25zIl06CiAgICAgICAgICAgIGlmIGVudHJ5WyJkYXRlIl0gPT0gc2Vzc2lvbl9kYXRl"
    "OgogICAgICAgICAgICAgICAgZW50cnlbIm5hbWUiXSA9IG5ld19uYW1lWzo4MF0KICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1"
    "ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgICMg4pSA4pSAIElOREVYIEhFTFBFUlMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfaW5kZXgoc2VsZikg"
    "LT4gZGljdDoKICAgICAgICBpZiBub3Qgc2VsZi5faW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KICAgICAgICB0cnk6CiAgICAgICAgICAgIHJl"
    "dHVybiBqc29uLmxvYWRzKAogICAgICAgICAgICAgICAgc2VsZi5faW5kZXhfcGF0aC5yZWFkX3Rl"
    "eHQoZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CgogICAgZGVmIF9zYXZlX2lu"
    "ZGV4KHNlbGYsIGluZGV4OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2luZGV4X3BhdGgu"
    "d3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyhpbmRleCwgaW5kZW50PTIpLCBlbmNv"
    "ZGluZz0idXRmLTgiCiAgICAgICAgKQoKCiMg4pSA4pSAIExFU1NPTlMgTEVBUk5FRCBEQVRBQkFT"
    "RSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc0xlYXJu"
    "ZWREQjoKICAgICIiIgogICAgUGVyc2lzdGVudCBrbm93bGVkZ2UgYmFzZSBmb3IgY29kZSBsZXNz"
    "b25zLCBydWxlcywgYW5kIHJlc29sdXRpb25zLgoKICAgIENvbHVtbnMgcGVyIHJlY29yZDoKICAg"
    "ICAgICBpZCwgY3JlYXRlZF9hdCwgZW52aXJvbm1lbnQgKExTTHxQeXRob258UHlTaWRlNnwuLi4p"
    "LCBsYW5ndWFnZSwKICAgICAgICByZWZlcmVuY2Vfa2V5IChzaG9ydCB1bmlxdWUgdGFnKSwgc3Vt"
    "bWFyeSwgZnVsbF9ydWxlLAogICAgICAgIHJlc29sdXRpb24sIGxpbmssIHRhZ3MKCiAgICBRdWVy"
    "aWVkIEZJUlNUIGJlZm9yZSBhbnkgY29kZSBzZXNzaW9uIGluIHRoZSByZWxldmFudCBsYW5ndWFn"
    "ZS4KICAgIFRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgbGl2ZXMgaGVyZS4KICAgIEdyb3dpbmcs"
    "IG5vbi1kdXBsaWNhdGluZywgc2VhcmNoYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmKToKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibGVzc29u"
    "c19sZWFybmVkLmpzb25sIgoKICAgIGRlZiBhZGQoc2VsZiwgZW52aXJvbm1lbnQ6IHN0ciwgbGFu"
    "Z3VhZ2U6IHN0ciwgcmVmZXJlbmNlX2tleTogc3RyLAogICAgICAgICAgICBzdW1tYXJ5OiBzdHIs"
    "IGZ1bGxfcnVsZTogc3RyLCByZXNvbHV0aW9uOiBzdHIgPSAiIiwKICAgICAgICAgICAgbGluazog"
    "c3RyID0gIiIsIHRhZ3M6IGxpc3QgPSBOb25lKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsK"
    "ICAgICAgICAgICAgImlkIjogICAgICAgICAgICBmImxlc3Nvbl97dXVpZC51dWlkNCgpLmhleFs6"
    "MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgbG9jYWxfbm93X2lzbygpLAogICAg"
    "ICAgICAgICAiZW52aXJvbm1lbnQiOiAgIGVudmlyb25tZW50LAogICAgICAgICAgICAibGFuZ3Vh"
    "Z2UiOiAgICAgIGxhbmd1YWdlLAogICAgICAgICAgICAicmVmZXJlbmNlX2tleSI6IHJlZmVyZW5j"
    "ZV9rZXksCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAgc3VtbWFyeSwKICAgICAgICAgICAg"
    "ImZ1bGxfcnVsZSI6ICAgICBmdWxsX3J1bGUsCiAgICAgICAgICAgICJyZXNvbHV0aW9uIjogICAg"
    "cmVzb2x1dGlvbiwKICAgICAgICAgICAgImxpbmsiOiAgICAgICAgICBsaW5rLAogICAgICAgICAg"
    "ICAidGFncyI6ICAgICAgICAgIHRhZ3Mgb3IgW10sCiAgICAgICAgfQogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9pc19kdXBsaWNhdGUocmVmZXJlbmNlX2tleSk6CiAgICAgICAgICAgIGFwcGVuZF9qc29u"
    "bChzZWxmLl9wYXRoLCByZWNvcmQpCiAgICAgICAgcmV0dXJuIHJlY29yZAoKICAgIGRlZiBzZWFy"
    "Y2goc2VsZiwgcXVlcnk6IHN0ciA9ICIiLCBlbnZpcm9ubWVudDogc3RyID0gIiIsCiAgICAgICAg"
    "ICAgICAgIGxhbmd1YWdlOiBzdHIgPSAiIikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZWNvcmRz"
    "ID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHJlc3VsdHMgPSBbXQogICAgICAgIHEg"
    "PSBxdWVyeS5sb3dlcigpCiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgaWYg"
    "ZW52aXJvbm1lbnQgYW5kIHIuZ2V0KCJlbnZpcm9ubWVudCIsIiIpLmxvd2VyKCkgIT0gZW52aXJv"
    "bm1lbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGxh"
    "bmd1YWdlIGFuZCByLmdldCgibGFuZ3VhZ2UiLCIiKS5sb3dlcigpICE9IGxhbmd1YWdlLmxvd2Vy"
    "KCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBxOgogICAgICAgICAg"
    "ICAgICAgaGF5c3RhY2sgPSAiICIuam9pbihbCiAgICAgICAgICAgICAgICAgICAgci5nZXQoInN1"
    "bW1hcnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdldCgiZnVsbF9ydWxlIiwiIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSwKICAgICAgICAgICAg"
    "ICAgICAgICAiICIuam9pbihyLmdldCgidGFncyIsW10pKSwKICAgICAgICAgICAgICAgIF0pLmxv"
    "d2VyKCkKICAgICAgICAgICAgICAgIGlmIHEgbm90IGluIGhheXN0YWNrOgogICAgICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHJlc3VsdHMuYXBwZW5kKHIpCiAgICAgICAgcmV0"
    "dXJuIHJlc3VsdHMKCiAgICBkZWYgZ2V0X2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAg"
    "IHJldHVybiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCgogICAgZGVmIGRlbGV0ZShzZWxmLCByZWNv"
    "cmRfaWQ6IHN0cikgLT4gYm9vbDoKICAgICAgICByZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9w"
    "YXRoKQogICAgICAgIGZpbHRlcmVkID0gW3IgZm9yIHIgaW4gcmVjb3JkcyBpZiByLmdldCgiaWQi"
    "KSAhPSByZWNvcmRfaWRdCiAgICAgICAgaWYgbGVuKGZpbHRlcmVkKSA8IGxlbihyZWNvcmRzKToK"
    "ICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgZmlsdGVyZWQpCiAgICAgICAgICAg"
    "IHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIGJ1aWxkX2NvbnRleHRf"
    "Zm9yX2xhbmd1YWdlKHNlbGYsIGxhbmd1YWdlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgbWF4X2NoYXJzOiBpbnQgPSAxNTAwKSAtPiBzdHI6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgQnVpbGQgYSBjb250ZXh0IHN0cmluZyBvZiBhbGwgcnVsZXMgZm9yIGEgZ2l2ZW4gbGFu"
    "Z3VhZ2UuCiAgICAgICAgRm9yIGluamVjdGlvbiBpbnRvIHN5c3RlbSBwcm9tcHQgYmVmb3JlIGNv"
    "ZGUgc2Vzc2lvbnMuCiAgICAgICAgIiIiCiAgICAgICAgcmVjb3JkcyA9IHNlbGYuc2VhcmNoKGxh"
    "bmd1YWdlPWxhbmd1YWdlKQogICAgICAgIGlmIG5vdCByZWNvcmRzOgogICAgICAgICAgICByZXR1"
    "cm4gIiIKCiAgICAgICAgcGFydHMgPSBbZiJbe2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTIOKAlCBB"
    "UFBMWSBCRUZPUkUgV1JJVElORyBDT0RFXSJdCiAgICAgICAgdG90YWwgPSAwCiAgICAgICAgZm9y"
    "IHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZW50cnkgPSBmIuKAoiB7ci5nZXQoJ3JlZmVyZW5j"
    "ZV9rZXknLCcnKX06IHtyLmdldCgnZnVsbF9ydWxlJywnJyl9IgogICAgICAgICAgICBpZiB0b3Rh"
    "bCArIGxlbihlbnRyeSkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAg"
    "ICAgICBwYXJ0cy5hcHBlbmQoZW50cnkpCiAgICAgICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkK"
    "CiAgICAgICAgcGFydHMuYXBwZW5kKGYiW0VORCB7bGFuZ3VhZ2UudXBwZXIoKX0gUlVMRVNdIikK"
    "ICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgIGRlZiBfaXNfZHVwbGljYXRlKHNl"
    "bGYsIHJlZmVyZW5jZV9rZXk6IHN0cikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYW55KAogICAg"
    "ICAgICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIpLmxvd2VyKCkgPT0gcmVmZXJlbmNlX2tl"
    "eS5sb3dlcigpCiAgICAgICAgICAgIGZvciByIGluIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAg"
    "ICAgICApCgogICAgZGVmIHNlZWRfbHNsX3J1bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "CiAgICAgICAgU2VlZCB0aGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IG9uIGZpcnN0IHJ1biBpZiB0"
    "aGUgREIgaXMgZW1wdHkuCiAgICAgICAgVGhlc2UgYXJlIHRoZSBoYXJkIHJ1bGVzIGZyb20gdGhl"
    "IHByb2plY3Qgc3RhbmRpbmcgcnVsZXMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgcmVhZF9qc29u"
    "bChzZWxmLl9wYXRoKToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgc2VlZGVkCgogICAg"
    "ICAgIGxzbF9ydWxlcyA9IFsKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1RFUk5BUlki"
    "LAogICAgICAgICAgICAgIk5vIHRlcm5hcnkgb3BlcmF0b3JzIGluIExTTCIsCiAgICAgICAgICAg"
    "ICAiTmV2ZXIgdXNlIHRoZSB0ZXJuYXJ5IG9wZXJhdG9yICg/OikgaW4gTFNMIHNjcmlwdHMuICIK"
    "ICAgICAgICAgICAgICJVc2UgaWYvZWxzZSBibG9ja3MgaW5zdGVhZC4gTFNMIGRvZXMgbm90IHN1"
    "cHBvcnQgdGVybmFyeS4iLAogICAgICAgICAgICAgIlJlcGxhY2Ugd2l0aCBpZi9lbHNlIGJsb2Nr"
    "LiIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0ZPUkVBQ0giLAogICAgICAg"
    "ICAgICAgIk5vIGZvcmVhY2ggbG9vcHMgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgaGFzIG5v"
    "IGZvcmVhY2ggbG9vcCBjb25zdHJ1Y3QuIFVzZSBpbnRlZ2VyIGluZGV4IHdpdGggIgogICAgICAg"
    "ICAgICAgImxsR2V0TGlzdExlbmd0aCgpIGFuZCBhIGZvciBvciB3aGlsZSBsb29wLiIsCiAgICAg"
    "ICAgICAgICAiVXNlOiBmb3IoaW50ZWdlciBpPTA7IGk8bGxHZXRMaXN0TGVuZ3RoKG15TGlzdCk7"
    "IGkrKykiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19HTE9CQUxfQVNTSUdO"
    "X0ZST01fRlVOQyIsCiAgICAgICAgICAgICAiTm8gZ2xvYmFsIHZhcmlhYmxlIGFzc2lnbm1lbnRz"
    "IGZyb20gZnVuY3Rpb24gY2FsbHMiLAogICAgICAgICAgICAgIkdsb2JhbCB2YXJpYWJsZSBpbml0"
    "aWFsaXphdGlvbiBpbiBMU0wgY2Fubm90IGNhbGwgZnVuY3Rpb25zLiAiCiAgICAgICAgICAgICAi"
    "SW5pdGlhbGl6ZSBnbG9iYWxzIHdpdGggbGl0ZXJhbCB2YWx1ZXMgb25seS4gIgogICAgICAgICAg"
    "ICAgIkFzc2lnbiBmcm9tIGZ1bmN0aW9ucyBpbnNpZGUgZXZlbnQgaGFuZGxlcnMgb3Igb3RoZXIg"
    "ZnVuY3Rpb25zLiIsCiAgICAgICAgICAgICAiTW92ZSB0aGUgYXNzaWdubWVudCBpbnRvIGFuIGV2"
    "ZW50IGhhbmRsZXIgKHN0YXRlX2VudHJ5LCBldGMuKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wi"
    "LCAiTFNMIiwgIk5PX1ZPSURfS0VZV09SRCIsCiAgICAgICAgICAgICAiTm8gdm9pZCBrZXl3b3Jk"
    "IGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGRvZXMgbm90IGhhdmUgYSB2b2lkIGtleXdvcmQg"
    "Zm9yIGZ1bmN0aW9uIHJldHVybiB0eXBlcy4gIgogICAgICAgICAgICAgIkZ1bmN0aW9ucyB0aGF0"
    "IHJldHVybiBub3RoaW5nIHNpbXBseSBvbWl0IHRoZSByZXR1cm4gdHlwZS4iLAogICAgICAgICAg"
    "ICAgIlJlbW92ZSAndm9pZCcgZnJvbSBmdW5jdGlvbiBzaWduYXR1cmUuICIKICAgICAgICAgICAg"
    "ICJlLmcuIG15RnVuYygpIHsgLi4uIH0gbm90IHZvaWQgbXlGdW5jKCkgeyAuLi4gfSIsICIiKSwK"
    "ICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIkNPTVBMRVRFX1NDUklQVFNfT05MWSIsCiAgICAg"
    "ICAgICAgICAiQWx3YXlzIHByb3ZpZGUgY29tcGxldGUgc2NyaXB0cywgbmV2ZXIgcGFydGlhbCBl"
    "ZGl0cyIsCiAgICAgICAgICAgICAiV2hlbiB3cml0aW5nIG9yIGVkaXRpbmcgTFNMIHNjcmlwdHMs"
    "IGFsd2F5cyBvdXRwdXQgdGhlIGNvbXBsZXRlICIKICAgICAgICAgICAgICJzY3JpcHQuIE5ldmVy"
    "IHByb3ZpZGUgcGFydGlhbCBzbmlwcGV0cyBvciAnYWRkIHRoaXMgc2VjdGlvbicgIgogICAgICAg"
    "ICAgICAgImluc3RydWN0aW9ucy4gVGhlIGZ1bGwgc2NyaXB0IG11c3QgYmUgY29weS1wYXN0ZSBy"
    "ZWFkeS4iLAogICAgICAgICAgICAgIldyaXRlIHRoZSBlbnRpcmUgc2NyaXB0IGZyb20gdG9wIHRv"
    "IGJvdHRvbS4iLCAiIiksCiAgICAgICAgXQoKICAgICAgICBmb3IgZW52LCBsYW5nLCByZWYsIHN1"
    "bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluayBpbiBsc2xfcnVsZXM6CiAgICAgICAg"
    "ICAgIHNlbGYuYWRkKGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRp"
    "b24sIGxpbmssCiAgICAgICAgICAgICAgICAgICAgIHRhZ3M9WyJsc2wiLCAiZm9yYmlkZGVuIiwg"
    "InN0YW5kaW5nX3J1bGUiXSkKCgojIOKUgOKUgCBUQVNLIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIFRhc2tNYW5hZ2VyOgogICAgIiIiCiAgICBUYXNrL3JlbWluZGVyIENSVUQgYW5kIGR1ZS1l"
    "dmVudCBkZXRlY3Rpb24uCgogICAgRmlsZTogbWVtb3JpZXMvdGFza3MuanNvbmwKCiAgICBUYXNr"
    "IHJlY29yZCBmaWVsZHM6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGR1ZV9hdCwgcHJlX3RyaWdn"
    "ZXIgKDFtaW4gYmVmb3JlKSwKICAgICAgICB0ZXh0LCBzdGF0dXMgKHBlbmRpbmd8dHJpZ2dlcmVk"
    "fHNub296ZWR8Y29tcGxldGVkfGNhbmNlbGxlZCksCiAgICAgICAgYWNrbm93bGVkZ2VkX2F0LCBy"
    "ZXRyeV9jb3VudCwgbGFzdF90cmlnZ2VyZWRfYXQsIG5leHRfcmV0cnlfYXQsCiAgICAgICAgc291"
    "cmNlIChsb2NhbHxnb29nbGUpLCBnb29nbGVfZXZlbnRfaWQsIHN5bmNfc3RhdHVzLCBtZXRhZGF0"
    "YQoKICAgIER1ZS1ldmVudCBjeWNsZToKICAgICAgICAtIFByZS10cmlnZ2VyOiAxIG1pbnV0ZSBi"
    "ZWZvcmUgZHVlIOKGkiBhbm5vdW5jZSB1cGNvbWluZwogICAgICAgIC0gRHVlIHRyaWdnZXI6IGF0"
    "IGR1ZSB0aW1lIOKGkiBhbGVydCBzb3VuZCArIEFJIGNvbW1lbnRhcnkKICAgICAgICAtIDMtbWlu"
    "dXRlIHdpbmRvdzogaWYgbm90IGFja25vd2xlZGdlZCDihpIgc25vb3plCiAgICAgICAgLSAxMi1t"
    "aW51dGUgcmV0cnk6IHJlLXRyaWdnZXIKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToK"
    "ICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwi"
    "CgogICAgIyDilIDilIAgQ1JVRCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX2FsbChzZWxmKSAtPiBsaXN0"
    "W2RpY3RdOgogICAgICAgIHRhc2tzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIGNo"
    "YW5nZWQgPSBGYWxzZQogICAgICAgIG5vcm1hbGl6ZWQgPSBbXQogICAgICAgIGZvciB0IGluIHRh"
    "c2tzOgogICAgICAgICAgICBpZiBub3QgaXNpbnN0YW5jZSh0LCBkaWN0KToKICAgICAgICAgICAg"
    "ICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmICJpZCIgbm90IGluIHQ6CiAgICAgICAgICAgICAg"
    "ICB0WyJpZCJdID0gZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IgogICAgICAgICAgICAg"
    "ICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgIyBOb3JtYWxpemUgZmllbGQgbmFtZXMKICAg"
    "ICAgICAgICAgaWYgImR1ZV9hdCIgbm90IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJkdWVfYXQi"
    "XSA9IHQuZ2V0KCJkdWUiKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAg"
    "ICAgdC5zZXRkZWZhdWx0KCJzdGF0dXMiLCAgICAgICAgICAgInBlbmRpbmciKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoInJldHJ5X2NvdW50IiwgICAgICAwKQogICAgICAgICAgICB0LnNldGRl"
    "ZmF1bHQoImFja25vd2xlZGdlZF9hdCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQo"
    "Imxhc3RfdHJpZ2dlcmVkX2F0IixOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoIm5leHRf"
    "cmV0cnlfYXQiLCAgICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInByZV9hbm5vdW5j"
    "ZWQiLCAgICBGYWxzZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzb3VyY2UiLCAgICAgICAg"
    "ICAgImxvY2FsIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJnb29nbGVfZXZlbnRfaWQiLCAg"
    "Tm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzeW5jX3N0YXR1cyIsICAgICAgInBlbmRp"
    "bmciKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwgICAgICAgICB7fSkKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJjcmVhdGVkX2F0IiwgICAgICAgbG9jYWxfbm93X2lzbygp"
    "KQoKICAgICAgICAgICAgIyBDb21wdXRlIHByZV90cmlnZ2VyIGlmIG1pc3NpbmcKICAgICAgICAg"
    "ICAgaWYgdC5nZXQoImR1ZV9hdCIpIGFuZCBub3QgdC5nZXQoInByZV90cmlnZ2VyIik6CiAgICAg"
    "ICAgICAgICAgICBkdCA9IHBhcnNlX2lzbyh0WyJkdWVfYXQiXSkKICAgICAgICAgICAgICAgIGlm"
    "IGR0OgogICAgICAgICAgICAgICAgICAgIHByZSA9IGR0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkK"
    "ICAgICAgICAgICAgICAgICAgICB0WyJwcmVfdHJpZ2dlciJdID0gcHJlLmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAg"
    "ICAgICAgIG5vcm1hbGl6ZWQuYXBwZW5kKHQpCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAg"
    "ICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIG5vcm1hbGl6ZWQpCiAgICAgICAgcmV0dXJuIG5v"
    "cm1hbGl6ZWQKCiAgICBkZWYgc2F2ZV9hbGwoc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+IE5v"
    "bmU6CiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgdGFza3MpCgogICAgZGVmIGFkZChz"
    "ZWxmLCB0ZXh0OiBzdHIsIGR1ZV9kdDogZGF0ZXRpbWUsCiAgICAgICAgICAgIHNvdXJjZTogc3Ry"
    "ID0gImxvY2FsIikgLT4gZGljdDoKICAgICAgICBwcmUgPSBkdWVfZHQgLSB0aW1lZGVsdGEobWlu"
    "dXRlcz0xKQogICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAg"
    "ZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQi"
    "OiAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAg"
    "ZHVlX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAicHJlX3Ry"
    "aWdnZXIiOiAgICAgIHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAg"
    "ICAgInRleHQiOiAgICAgICAgICAgICB0ZXh0LnN0cmlwKCksCiAgICAgICAgICAgICJzdGF0dXMi"
    "OiAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogIE5v"
    "bmUsCiAgICAgICAgICAgICJyZXRyeV9jb3VudCI6ICAgICAgMCwKICAgICAgICAgICAgImxhc3Rf"
    "dHJpZ2dlcmVkX2F0IjpOb25lLAogICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6ICAgIE5vbmUs"
    "CiAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogICAgRmFsc2UsCiAgICAgICAgICAgICJzb3Vy"
    "Y2UiOiAgICAgICAgICAgc291cmNlLAogICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogIE5v"
    "bmUsCiAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICAgICAgInBlbmRpbmciLAogICAgICAgICAg"
    "ICAibWV0YWRhdGEiOiAgICAgICAgIHt9LAogICAgICAgIH0KICAgICAgICB0YXNrcyA9IHNlbGYu"
    "bG9hZF9hbGwoKQogICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgIHNlbGYuc2F2ZV9h"
    "bGwodGFza3MpCiAgICAgICAgcmV0dXJuIHRhc2sKCiAgICBkZWYgdXBkYXRlX3N0YXR1cyhzZWxm"
    "LCB0YXNrX2lkOiBzdHIsIHN0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYWNrbm93"
    "bGVkZ2VkOiBib29sID0gRmFsc2UpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0g"
    "c2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQu"
    "Z2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSA9IHN0YXR1"
    "cwogICAgICAgICAgICAgICAgaWYgYWNrbm93bGVkZ2VkOgogICAgICAgICAgICAgICAgICAgIHRb"
    "ImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxm"
    "LnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4g"
    "Tm9uZQoKICAgIGRlZiBjb21wbGV0ZShzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2Rp"
    "Y3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFz"
    "a3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAg"
    "ICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjb21wbGV0ZWQiCiAgICAgICAgICAgICAgICB0WyJh"
    "Y2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5z"
    "YXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5v"
    "bmUKCiAgICBkZWYgY2FuY2VsKHNlbGYsIHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06"
    "CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoK"
    "ICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRb"
    "InN0YXR1cyJdICAgICAgICAgID0gImNhbmNlbGxlZCIKICAgICAgICAgICAgICAgIHRbImFja25v"
    "d2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVf"
    "YWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoK"
    "ICAgIGRlZiBjbGVhcl9jb21wbGV0ZWQoc2VsZikgLT4gaW50OgogICAgICAgIHRhc2tzICAgID0g"
    "c2VsZi5sb2FkX2FsbCgpCiAgICAgICAga2VwdCAgICAgPSBbdCBmb3IgdCBpbiB0YXNrcwogICAg"
    "ICAgICAgICAgICAgICAgIGlmIHQuZ2V0KCJzdGF0dXMiKSBub3QgaW4geyJjb21wbGV0ZWQiLCJj"
    "YW5jZWxsZWQifV0KICAgICAgICByZW1vdmVkICA9IGxlbih0YXNrcykgLSBsZW4oa2VwdCkKICAg"
    "ICAgICBpZiByZW1vdmVkOgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKGtlcHQpCiAgICAgICAg"
    "cmV0dXJuIHJlbW92ZWQKCiAgICBkZWYgdXBkYXRlX2dvb2dsZV9zeW5jKHNlbGYsIHRhc2tfaWQ6"
    "IHN0ciwgc3luY19zdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgZ29vZ2xl"
    "X2V2ZW50X2lkOiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgZXJyb3I6IHN0"
    "ciA9ICIiKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwo"
    "KQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0"
    "YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3luY19zdGF0dXMiXSAgICA9IHN5bmNfc3RhdHVz"
    "CiAgICAgICAgICAgICAgICB0WyJsYXN0X3N5bmNlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAg"
    "ICAgICAgICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAgdFsi"
    "Z29vZ2xlX2V2ZW50X2lkIl0gPSBnb29nbGVfZXZlbnRfaWQKICAgICAgICAgICAgICAgIGlmIGVy"
    "cm9yOgogICAgICAgICAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSkKICAg"
    "ICAgICAgICAgICAgICAgICB0WyJtZXRhZGF0YSJdWyJnb29nbGVfc3luY19lcnJvciJdID0gZXJy"
    "b3JbOjI0MF0KICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgIyDilIDilIAgRFVFIEVWRU5U"
    "IERFVEVDVElPTiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBnZXRfZHVlX2V2ZW50cyhzZWxm"
    "KSAtPiBsaXN0W3R1cGxlW3N0ciwgZGljdF1dOgogICAgICAgICIiIgogICAgICAgIENoZWNrIGFs"
    "bCB0YXNrcyBmb3IgZHVlL3ByZS10cmlnZ2VyL3JldHJ5IGV2ZW50cy4KICAgICAgICBSZXR1cm5z"
    "IGxpc3Qgb2YgKGV2ZW50X3R5cGUsIHRhc2spIHR1cGxlcy4KICAgICAgICBldmVudF90eXBlOiAi"
    "cHJlIiB8ICJkdWUiIHwgInJldHJ5IgoKICAgICAgICBNb2RpZmllcyB0YXNrIHN0YXR1c2VzIGlu"
    "IHBsYWNlIGFuZCBzYXZlcy4KICAgICAgICBDYWxsIGZyb20gQVBTY2hlZHVsZXIgZXZlcnkgMzAg"
    "c2Vjb25kcy4KICAgICAgICAiIiIKICAgICAgICBub3cgICAgPSBkYXRldGltZS5ub3coKS5hc3Rp"
    "bWV6b25lKCkKICAgICAgICB0YXNrcyAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBldmVudHMg"
    "PSBbXQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQoKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoK"
    "ICAgICAgICAgICAgaWYgdGFzay5nZXQoImFja25vd2xlZGdlZF9hdCIpOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKCiAgICAgICAgICAgIHN0YXR1cyAgID0gdGFzay5nZXQoInN0YXR1cyIsICJw"
    "ZW5kaW5nIikKICAgICAgICAgICAgZHVlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdl"
    "dCgiZHVlX2F0IikpCiAgICAgICAgICAgIHByZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFz"
    "ay5nZXQoInByZV90cmlnZ2VyIikpCiAgICAgICAgICAgIG5leHRfcmV0ID0gc2VsZi5fcGFyc2Vf"
    "bG9jYWwodGFzay5nZXQoIm5leHRfcmV0cnlfYXQiKSkKICAgICAgICAgICAgZGVhZGxpbmUgPSBz"
    "ZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgiYWxlcnRfZGVhZGxpbmUiKSkKCiAgICAgICAgICAg"
    "ICMgUHJlLXRyaWdnZXIKICAgICAgICAgICAgaWYgKHN0YXR1cyA9PSAicGVuZGluZyIgYW5kIHBy"
    "ZSBhbmQgbm93ID49IHByZQogICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdGFzay5nZXQoInBy"
    "ZV9hbm5vdW5jZWQiKSk6CiAgICAgICAgICAgICAgICB0YXNrWyJwcmVfYW5ub3VuY2VkIl0gPSBU"
    "cnVlCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgicHJlIiwgdGFzaykpCiAgICAgICAg"
    "ICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgIyBEdWUgdHJpZ2dlcgogICAgICAg"
    "ICAgICBpZiBzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBkdWUgYW5kIG5vdyA+PSBkdWU6CiAgICAg"
    "ICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAg"
    "ICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXT0gbG9jYWxfbm93X2lzbygpCiAgICAg"
    "ICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGluZSJdICAgPSAoCiAgICAgICAgICAgICAgICAg"
    "ICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAg"
    "ICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAg"
    "ICAgIGV2ZW50cy5hcHBlbmQoKCJkdWUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQg"
    "PSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBTbm9vemUgYWZ0"
    "ZXIgMy1taW51dGUgd2luZG93CiAgICAgICAgICAgIGlmIHN0YXR1cyA9PSAidHJpZ2dlcmVkIiBh"
    "bmQgZGVhZGxpbmUgYW5kIG5vdyA+PSBkZWFkbGluZToKICAgICAgICAgICAgICAgIHRhc2tbInN0"
    "YXR1cyJdICAgICAgICA9ICJzbm9vemVkIgogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRy"
    "eV9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUo"
    "KSArIHRpbWVkZWx0YShtaW51dGVzPTEyKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFJldHJ5CiAgICAgICAgICAgIGlmIHN0YXR1"
    "cyBpbiB7InJldHJ5X3BlbmRpbmciLCJzbm9vemVkIn0gYW5kIG5leHRfcmV0IGFuZCBub3cgPj0g"
    "bmV4dF9yZXQ6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgICAgID0gInRy"
    "aWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbInJldHJ5X2NvdW50Il0gICAgICAgPSBpbnQo"
    "dGFzay5nZXQoInJldHJ5X2NvdW50IiwwKSkgKyAxCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0"
    "X3RyaWdnZXJlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNrWyJh"
    "bGVydF9kZWFkbGluZSJdICAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygp"
    "LmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlz"
    "b2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICB0YXNrWyJuZXh0X3Jl"
    "dHJ5X2F0Il0gICAgID0gTm9uZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInJldHJ5"
    "IiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICBpZiBjaGFu"
    "Z2VkOgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiBldmVu"
    "dHMKCiAgICBkZWYgX3BhcnNlX2xvY2FsKHNlbGYsIHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2Rh"
    "dGV0aW1lXToKICAgICAgICAiIiJQYXJzZSBJU08gc3RyaW5nIHRvIHRpbWV6b25lLWF3YXJlIGRh"
    "dGV0aW1lIGZvciBjb21wYXJpc29uLiIiIgogICAgICAgIGR0ID0gcGFyc2VfaXNvKHZhbHVlKQog"
    "ICAgICAgIGlmIGR0IGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYg"
    "ZHQudHppbmZvIGlzIE5vbmU6CiAgICAgICAgICAgIGR0ID0gZHQuYXN0aW1lem9uZSgpCiAgICAg"
    "ICAgcmV0dXJuIGR0CgogICAgIyDilIDilIAgTkFUVVJBTCBMQU5HVUFHRSBQQVJTSU5HIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgQHN0YXRpY21ldGhvZAogICAgZGVmIGNsYXNzaWZ5X2ludGVudCh0ZXh0OiBzdHIpIC0+IGRp"
    "Y3Q6CiAgICAgICAgIiIiCiAgICAgICAgQ2xhc3NpZnkgdXNlciBpbnB1dCBhcyB0YXNrL3JlbWlu"
    "ZGVyL3RpbWVyL2NoYXQuCiAgICAgICAgUmV0dXJucyB7ImludGVudCI6IHN0ciwgImNsZWFuZWRf"
    "aW5wdXQiOiBzdHJ9CiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgIyBTdHJp"
    "cCBjb21tb24gaW52b2NhdGlvbiBwcmVmaXhlcwogICAgICAgIGNsZWFuZWQgPSByZS5zdWIoCiAg"
    "ICAgICAgICAgIHJmIl5ccyooPzp7REVDS19OQU1FLmxvd2VyKCl9fGhleVxzK3tERUNLX05BTUUu"
    "bG93ZXIoKX0pXHMqLD9ccypbOlwtXT9ccyoiLAogICAgICAgICAgICAiIiwgdGV4dCwgZmxhZ3M9"
    "cmUuSQogICAgICAgICkuc3RyaXAoKQoKICAgICAgICBsb3cgPSBjbGVhbmVkLmxvd2VyKCkKCiAg"
    "ICAgICAgdGltZXJfcGF0cyAgICA9IFtyIlxic2V0KD86XHMrYSk/XHMrdGltZXJcYiIsIHIiXGJ0"
    "aW1lclxzK2ZvclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzdGFydCg/OlxzK2Ep"
    "P1xzK3RpbWVyXGIiXQogICAgICAgIHJlbWluZGVyX3BhdHMgPSBbciJcYnJlbWluZCBtZVxiIiwg"
    "ciJcYnNldCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ciJcYmFkZCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ciJcYnNldCg/OlxzK2FuPyk/XHMrYWxhcm1cYiIsIHIiXGJhbGFybVxzK2ZvclxiIl0KICAgICAg"
    "ICB0YXNrX3BhdHMgICAgID0gW3IiXGJhZGQoPzpccythKT9ccyt0YXNrXGIiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgciJcYmNyZWF0ZSg/OlxzK2EpP1xzK3Rhc2tcYiIsIHIiXGJuZXdccyt0"
    "YXNrXGIiXQoKICAgICAgICBpbXBvcnQgcmUgYXMgX3JlCiAgICAgICAgaWYgYW55KF9yZS5zZWFy"
    "Y2gocCwgbG93KSBmb3IgcCBpbiB0aW1lcl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRp"
    "bWVyIgogICAgICAgIGVsaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiByZW1pbmRl"
    "cl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInJlbWluZGVyIgogICAgICAgIGVsaWYgYW55"
    "KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiB0YXNrX3BhdHMpOgogICAgICAgICAgICBpbnRl"
    "bnQgPSAidGFzayIKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbnRlbnQgPSAiY2hhdCIKCiAg"
    "ICAgICAgcmV0dXJuIHsiaW50ZW50IjogaW50ZW50LCAiY2xlYW5lZF9pbnB1dCI6IGNsZWFuZWR9"
    "CgogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX2R1ZV9kYXRldGltZSh0ZXh0OiBzdHIp"
    "IC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSBuYXR1cmFs"
    "IGxhbmd1YWdlIHRpbWUgZXhwcmVzc2lvbiBmcm9tIHRhc2sgdGV4dC4KICAgICAgICBIYW5kbGVz"
    "OiAiaW4gMzAgbWludXRlcyIsICJhdCAzcG0iLCAidG9tb3Jyb3cgYXQgOWFtIiwKICAgICAgICAg"
    "ICAgICAgICAiaW4gMiBob3VycyIsICJhdCAxNTozMCIsIGV0Yy4KICAgICAgICBSZXR1cm5zIGEg"
    "ZGF0ZXRpbWUgb3IgTm9uZSBpZiB1bnBhcnNlYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpbXBv"
    "cnQgcmUKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBsb3cgID0gdGV4dC5s"
    "b3dlcigpLnN0cmlwKCkKCiAgICAgICAgIyAiaW4gWCBtaW51dGVzL2hvdXJzL2RheXMiCiAgICAg"
    "ICAgbSA9IHJlLnNlYXJjaCgKICAgICAgICAgICAgciJpblxzKyhcZCspXHMqKG1pbnV0ZXxtaW58"
    "aG91cnxocnxkYXl8c2Vjb25kfHNlYykiLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAg"
    "ICAgaWYgbToKICAgICAgICAgICAgbiAgICA9IGludChtLmdyb3VwKDEpKQogICAgICAgICAgICB1"
    "bml0ID0gbS5ncm91cCgyKQogICAgICAgICAgICBpZiAibWluIiBpbiB1bml0OiAgcmV0dXJuIG5v"
    "dyArIHRpbWVkZWx0YShtaW51dGVzPW4pCiAgICAgICAgICAgIGlmICJob3VyIiBpbiB1bml0IG9y"
    "ICJociIgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShob3Vycz1uKQogICAgICAgICAg"
    "ICBpZiAiZGF5IiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShkYXlzPW4pCiAgICAg"
    "ICAgICAgIGlmICJzZWMiICBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKHNlY29uZHM9"
    "bikKCiAgICAgICAgIyAiYXQgSEg6TU0iIG9yICJhdCBIOk1NYW0vcG0iCiAgICAgICAgbSA9IHJl"
    "LnNlYXJjaCgKICAgICAgICAgICAgciJhdFxzKyhcZHsxLDJ9KSg/OjooXGR7Mn0pKT9ccyooYW18"
    "cG0pPyIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAgICAg"
    "ICBociAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgbW4gID0gaW50KG0uZ3JvdXAoMikp"
    "IGlmIG0uZ3JvdXAoMikgZWxzZSAwCiAgICAgICAgICAgIGFwbSA9IG0uZ3JvdXAoMykKICAgICAg"
    "ICAgICAgaWYgYXBtID09ICJwbSIgYW5kIGhyIDwgMTI6IGhyICs9IDEyCiAgICAgICAgICAgIGlm"
    "IGFwbSA9PSAiYW0iIGFuZCBociA9PSAxMjogaHIgPSAwCiAgICAgICAgICAgIGR0ID0gbm93LnJl"
    "cGxhY2UoaG91cj1ociwgbWludXRlPW1uLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkKICAgICAg"
    "ICAgICAgaWYgZHQgPD0gbm93OgogICAgICAgICAgICAgICAgZHQgKz0gdGltZWRlbHRhKGRheXM9"
    "MSkKICAgICAgICAgICAgcmV0dXJuIGR0CgogICAgICAgICMgInRvbW9ycm93IGF0IC4uLiIgIChy"
    "ZWN1cnNlIG9uIHRoZSAiYXQiIHBhcnQpCiAgICAgICAgaWYgInRvbW9ycm93IiBpbiBsb3c6CiAg"
    "ICAgICAgICAgIHRvbW9ycm93X3RleHQgPSByZS5zdWIociJ0b21vcnJvdyIsICIiLCBsb3cpLnN0"
    "cmlwKCkKICAgICAgICAgICAgcmVzdWx0ID0gVGFza01hbmFnZXIucGFyc2VfZHVlX2RhdGV0aW1l"
    "KHRvbW9ycm93X3RleHQpCiAgICAgICAgICAgIGlmIHJlc3VsdDoKICAgICAgICAgICAgICAgIHJl"
    "dHVybiByZXN1bHQgKyB0aW1lZGVsdGEoZGF5cz0xKQoKICAgICAgICByZXR1cm4gTm9uZQoKCiMg"
    "4pSA4pSAIFJFUVVJUkVNRU5UUy5UWFQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IFdyaXRlIHJlcXVpcmVtZW50cy50eHQgbmV4dCB0byB0aGUgZGVjayBmaWxlIG9uIGZpcnN0IHJ1"
    "bi4KICAgIEhlbHBzIHVzZXJzIGluc3RhbGwgYWxsIGRlcGVuZGVuY2llcyB3aXRoIG9uZSBwaXAg"
    "Y29tbWFuZC4KICAgICIiIgogICAgcmVxX3BhdGggPSBQYXRoKENGRy5nZXQoImJhc2VfZGlyIiwg"
    "c3RyKFNDUklQVF9ESVIpKSkgLyAicmVxdWlyZW1lbnRzLnR4dCIKICAgIGlmIHJlcV9wYXRoLmV4"
    "aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGNvbnRlbnQgPSAiIiJcCiMgTW9yZ2FubmEgRGVj"
    "ayDigJQgUmVxdWlyZWQgRGVwZW5kZW5jaWVzCiMgSW5zdGFsbCBhbGwgd2l0aDogcGlwIGluc3Rh"
    "bGwgLXIgcmVxdWlyZW1lbnRzLnR4dAoKIyBDb3JlIFVJClB5U2lkZTYKCiMgU2NoZWR1bGluZyAo"
    "aWRsZSB0aW1lciwgYXV0b3NhdmUsIHJlZmxlY3Rpb24gY3ljbGVzKQphcHNjaGVkdWxlcgoKIyBM"
    "b2dnaW5nCmxvZ3VydQoKIyBTb3VuZCBwbGF5YmFjayAoV0FWICsgTVAzKQpweWdhbWUKCiMgRGVz"
    "a3RvcCBzaG9ydGN1dCBjcmVhdGlvbiAoV2luZG93cyBvbmx5KQpweXdpbjMyCgojIFN5c3RlbSBt"
    "b25pdG9yaW5nIChDUFUsIFJBTSwgZHJpdmVzLCBuZXR3b3JrKQpwc3V0aWwKCiMgSFRUUCByZXF1"
    "ZXN0cwpyZXF1ZXN0cwoKIyBHb29nbGUgaW50ZWdyYXRpb24gKENhbGVuZGFyLCBEcml2ZSwgRG9j"
    "cywgR21haWwpCmdvb2dsZS1hcGktcHl0aG9uLWNsaWVudApnb29nbGUtYXV0aC1vYXV0aGxpYgpn"
    "b29nbGUtYXV0aAoKIyDilIDilIAgT3B0aW9uYWwgKGxvY2FsIG1vZGVsIG9ubHkpIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB1c2luZyBhIGxvY2FsIEh1Z2dpbmdGYWNl"
    "IG1vZGVsOgojIHRvcmNoCiMgdHJhbnNmb3JtZXJzCiMgYWNjZWxlcmF0ZQoKIyDilIDilIAgT3B0"
    "aW9uYWwgKE5WSURJQSBHUFUgbW9uaXRvcmluZykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHlvdSBo"
    "YXZlIGFuIE5WSURJQSBHUFU6CiMgcHludm1sCiIiIgogICAgcmVxX3BhdGgud3JpdGVfdGV4dChj"
    "b250ZW50LCBlbmNvZGluZz0idXRmLTgiKQoKCiMg4pSA4pSAIFBBU1MgNCBDT01QTEVURSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBNZW1vcnksIFNlc3Npb24sIExlc3NvbnNMZWFybmVkLCBUYXNrTWFuYWdlciBhbGwgZGVm"
    "aW5lZC4KIyBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYXV0by1zZWVkZWQgb24gZmlyc3QgcnVuLgoj"
    "IHJlcXVpcmVtZW50cy50eHQgd3JpdHRlbiBvbiBmaXJzdCBydW4uCiMKIyBOZXh0OiBQYXNzIDUg"
    "4oCUIFRhYiBDb250ZW50IENsYXNzZXMKIyAoU0xTY2Fuc1RhYiwgU0xDb21tYW5kc1RhYiwgSm9i"
    "VHJhY2tlclRhYiwgUmVjb3Jkc1RhYiwKIyAgVGFza3NUYWIsIFNlbGZUYWIsIERpYWdub3N0aWNz"
    "VGFiKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA1OiBUQUIgQ09OVEVO"
    "VCBDTEFTU0VTCiMKIyBUYWJzIGRlZmluZWQgaGVyZToKIyAgIFNMU2NhbnNUYWIgICAgICDigJQg"
    "Z3JpbW9pcmUtY2FyZCBzdHlsZSwgcmVidWlsdCAoRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQs"
    "CiMgICAgICAgICAgICAgICAgICAgICBwYXJzZXIgZml4ZWQsIGNvcHktdG8tY2xpcGJvYXJkIHBl"
    "ciBpdGVtKQojICAgU0xDb21tYW5kc1RhYiAgIOKAlCBnb3RoaWMgdGFibGUsIGNvcHkgY29tbWFu"
    "ZCB0byBjbGlwYm9hcmQKIyAgIEpvYlRyYWNrZXJUYWIgICDigJQgZnVsbCByZWJ1aWxkIGZyb20g"
    "c3BlYywgQ1NWL1RTViBleHBvcnQKIyAgIFJlY29yZHNUYWIgICAgICDigJQgR29vZ2xlIERyaXZl"
    "L0RvY3Mgd29ya3NwYWNlCiMgICBUYXNrc1RhYiAgICAgICAg4oCUIHRhc2sgcmVnaXN0cnkgKyBt"
    "aW5pIGNhbGVuZGFyCiMgICBTZWxmVGFiICAgICAgICAg4oCUIGlkbGUgbmFycmF0aXZlIG91dHB1"
    "dCArIFBvSSBsaXN0CiMgICBEaWFnbm9zdGljc1RhYiAg4oCUIGxvZ3VydSBvdXRwdXQgKyBoYXJk"
    "d2FyZSByZXBvcnQgKyBqb3VybmFsIGxvYWQgbm90aWNlcwojICAgTGVzc29uc1RhYiAgICAgIOKA"
    "lCBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMgYnJvd3NlcgojIOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kAoKaW1wb3J0IHJlIGFzIF9yZQoKCiMg4pSA4pSAIFNIQVJFRCBHT1RISUMgVEFCTEUgU1RZTEUg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBfZ290aGljX3RhYmxlX3N0eWxl"
    "KCkgLT4gc3RyOgogICAgcmV0dXJuIGYiIiIKICAgICAgICBRVGFibGVXaWRnZXQge3sKICAgICAg"
    "ICAgICAgYmFja2dyb3VuZDoge0NfQkcyfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTER9Owog"
    "ICAgICAgICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAg"
    "IGdyaWRsaW5lLWNvbG9yOiB7Q19CT1JERVJ9OwogICAgICAgICAgICBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDExcHg7CiAgICAgICAgfX0K"
    "ICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgICAgICAgICAgYmFja2dy"
    "b3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9"
    "OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOmFsdGVybmF0ZSB7ewogICAg"
    "ICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgICAgIH19CiAgICAgICAgUUhlYWRlclZp"
    "ZXc6OnNlY3Rpb24ge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICAg"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgICAgICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07CiAgICAgICAgICAgIHBhZGRpbmc6IDRweCA2cHg7CiAgICAgICAgICAgIGZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQtc2l6ZTogMTBweDsK"
    "ICAgICAgICAgICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICAgICAgICAgIGxldHRlci1zcGFjaW5n"
    "OiAxcHg7CiAgICAgICAgfX0KICAgICIiIgoKZGVmIF9nb3RoaWNfYnRuKHRleHQ6IHN0ciwgdG9v"
    "bHRpcDogc3RyID0gIiIpIC0+IFFQdXNoQnV0dG9uOgogICAgYnRuID0gUVB1c2hCdXR0b24odGV4"
    "dCkKICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNP"
    "Tl9ESU19OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT059OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgIGYiZm9udC13ZWln"
    "aHQ6IGJvbGQ7IHBhZGRpbmc6IDRweCAxMHB4OyBsZXR0ZXItc3BhY2luZzogMXB4OyIKICAgICkK"
    "ICAgIGlmIHRvb2x0aXA6CiAgICAgICAgYnRuLnNldFRvb2xUaXAodG9vbHRpcCkKICAgIHJldHVy"
    "biBidG4KCmRlZiBfc2VjdGlvbl9sYmwodGV4dDogc3RyKSAtPiBRTGFiZWw6CiAgICBsYmwgPSBR"
    "TGFiZWwodGV4dCkKICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgIGYiY29sb3I6IHtDX0dP"
    "TER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICBmImxldHRl"
    "ci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgKQog"
    "ICAgcmV0dXJuIGxibAoKCiMg4pSA4pSAIFNMIFNDQU5TIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgU0xTY2Fuc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgYXZhdGFyIHNj"
    "YW5uZXIgcmVzdWx0cyBtYW5hZ2VyLgogICAgUmVidWlsdCBmcm9tIHNwZWM6CiAgICAgIC0gQ2Fy"
    "ZC9ncmltb2lyZS1lbnRyeSBzdHlsZSBkaXNwbGF5CiAgICAgIC0gQWRkICh3aXRoIHRpbWVzdGFt"
    "cC1hd2FyZSBwYXJzZXIpCiAgICAgIC0gRGlzcGxheSAoY2xlYW4gaXRlbS9jcmVhdG9yIHRhYmxl"
    "KQogICAgICAtIE1vZGlmeSAoZWRpdCBuYW1lLCBkZXNjcmlwdGlvbiwgaW5kaXZpZHVhbCBpdGVt"
    "cykKICAgICAgLSBEZWxldGUgKHdhcyBtaXNzaW5nIOKAlCBub3cgcHJlc2VudCkKICAgICAgLSBS"
    "ZS1wYXJzZSAod2FzICdSZWZyZXNoJyDigJQgcmUtcnVucyBwYXJzZXIgb24gc3RvcmVkIHJhdyB0"
    "ZXh0KQogICAgICAtIENvcHktdG8tY2xpcGJvYXJkIG9uIGFueSBpdGVtCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgbWVtb3J5X2RpcjogUGF0aCwgcGFyZW50PU5vbmUpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0"
    "aCgic2wiKSAvICJzbF9zY2Fucy5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2Rp"
    "Y3RdID0gW10KICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZDogT3B0aW9uYWxbc3RyXSA9IE5vbmUK"
    "ICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYg"
    "X3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYp"
    "CiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290"
    "LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYmFyID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgID0gX2dvdGhpY19idG4oIuKcpiBBZGQi"
    "LCAgICAgIkFkZCBhIG5ldyBzY2FuIikKICAgICAgICBzZWxmLl9idG5fZGlzcGxheSA9IF9nb3Ro"
    "aWNfYnRuKCLinacgRGlzcGxheSIsICJTaG93IHNlbGVjdGVkIHNjYW4gZGV0YWlscyIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX21vZGlmeSAgPSBfZ290aGljX2J0bigi4pynIE1vZGlmeSIsICAiRWRpdCBz"
    "ZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlICA9IF9nb3RoaWNfYnRuKCLi"
    "nJcgRGVsZXRlIiwgICJEZWxldGUgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX3Jl"
    "cGFyc2UgPSBfZ290aGljX2J0bigi4oa7IFJlLXBhcnNlIiwiUmUtcGFyc2UgcmF3IHRleHQgb2Yg"
    "c2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2hvd19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX3Nob3dfZGlzcGxheSkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9zaG93X21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2UuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX3JlcGFyc2UpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQs"
    "IHNlbGYuX2J0bl9kaXNwbGF5LCBzZWxmLl9idG5fbW9kaWZ5LAogICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9idG5fZGVsZXRlLCBzZWxmLl9idG5fcmVwYXJzZSk6CiAgICAgICAgICAgIGJhci5hZGRX"
    "aWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQo"
    "YmFyKQoKICAgICAgICAjIFN0YWNrOiBsaXN0IHZpZXcgfCBhZGQgZm9ybSB8IGRpc3BsYXkgfCBt"
    "b2RpZnkKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzZWxmLl9zdGFjaywgMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAwOiBzY2Fu"
    "IGxpc3QgKGdyaW1vaXJlIGNhcmRzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMCA9IFFXaWRn"
    "ZXQoKQogICAgICAgIGwwID0gUVZCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwgPSBRU2Nyb2xsQXJl"
    "YSgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAg"
    "ICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JH"
    "Mn07IGJvcmRlcjogbm9uZTsiKQogICAgICAgIHNlbGYuX2NhcmRfY29udGFpbmVyID0gUVdpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQgICAgPSBRVkJveExheW91dChzZWxmLl9jYXJk"
    "X2NvbnRhaW5lcikKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "NCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAg"
    "ICAgc2VsZi5fY2FyZF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3Jv"
    "bGwuc2V0V2lkZ2V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIGwwLmFkZFdpZGdldChz"
    "ZWxmLl9jYXJkX3Njcm9sbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAg"
    "ICAgICMg4pSA4pSAIFBBR0UgMTogYWRkIGZvcm0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDEgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBsMSA9IFFWQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRl"
    "bnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwxLnNldFNwYWNpbmcoNCkKICAgICAgICBs"
    "MS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU0NBTiBOQU1FIChhdXRvLWRldGVjdGVkKSIp"
    "KQogICAgICAgIHNlbGYuX2FkZF9uYW1lICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fYWRk"
    "X25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikK"
    "ICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX25hbWUpCiAgICAgICAgbDEuYWRkV2lkZ2V0"
    "KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2Mg"
    "ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfZGVzYy5zZXRNYXhpbXVtSGVpZ2h0KDYw"
    "KQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfZGVzYykKICAgICAgICBsMS5hZGRXaWRn"
    "ZXQoX3NlY3Rpb25fbGJsKCLinacgUkFXIFNDQU4gVEVYVCAocGFzdGUgaGVyZSkiKSkKICAgICAg"
    "ICBzZWxmLl9hZGRfcmF3ICAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuc2V0"
    "UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiUGFzdGUgdGhlIHJhdyBTZWNvbmQgTGlmZSBz"
    "Y2FuIG91dHB1dCBoZXJlLlxuIgogICAgICAgICAgICAiVGltZXN0YW1wcyBsaWtlIFsxMTo0N10g"
    "d2lsbCBiZSB1c2VkIHRvIHNwbGl0IGl0ZW1zIGNvcnJlY3RseS4iCiAgICAgICAgKQogICAgICAg"
    "IGwxLmFkZFdpZGdldChzZWxmLl9hZGRfcmF3LCAxKQogICAgICAgICMgUHJldmlldyBvZiBwYXJz"
    "ZWQgaXRlbXMKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFSU0VEIElU"
    "RU1TIFBSRVZJRVciKSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldyA9IFFUYWJsZVdpZGdldCgw"
    "LCAyKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMo"
    "WyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9udGFs"
    "SGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9udGFs"
    "SGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRNYXhpbXVt"
    "SGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRTdHlsZVNoZWV0KF9nb3Ro"
    "aWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3ByZXZpZXcp"
    "CiAgICAgICAgc2VsZi5fYWRkX3Jhdy50ZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX3ByZXZpZXdf"
    "cGFyc2UpCgogICAgICAgIGJ0bnMxID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMxID0gX2dvdGhp"
    "Y19idG4oIuKcpiBTYXZlIik7IGMxID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAg"
    "IHMxLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYzEuY2xpY2tlZC5jb25u"
    "ZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMx"
    "LmFkZFdpZGdldChzMSk7IGJ0bnMxLmFkZFdpZGdldChjMSk7IGJ0bnMxLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIGwxLmFkZExheW91dChidG5zMSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQo"
    "cDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMjogZGlzcGxheSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAg"
    "bDIuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fZGlzcF9uYW1l"
    "ICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUfTsgZm9udC1zaXplOiAxM3B4OyBmb250LXdl"
    "aWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2MgID0gUUxhYmVsKCkKICAgICAg"
    "ICBzZWxmLl9kaXNwX2Rlc2Muc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwX2Rl"
    "c2Muc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9y"
    "Il0pCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRj"
    "aCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNo"
    "KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0"
    "eWxlKCkpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeSgKICAg"
    "ICAgICAgICAgUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAg"
    "c2VsZi5fZGlzcF90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KAogICAg"
    "ICAgICAgICBzZWxmLl9pdGVtX2NvbnRleHRfbWVudSkKCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNl"
    "bGYuX2Rpc3BfbmFtZSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF9kZXNjKQogICAg"
    "ICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX3RhYmxlLCAxKQoKICAgICAgICBjb3B5X2hpbnQg"
    "PSBRTGFiZWwoIlJpZ2h0LWNsaWNrIGFueSBpdGVtIHRvIGNvcHkgaXQgdG8gY2xpcGJvYXJkLiIp"
    "CiAgICAgICAgY29weV9oaW50LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtD"
    "X1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICBsMi5hZGRXaWRnZXQoY29weV9oaW50KQoKICAgICAgICBi"
    "azIgPSBfZ290aGljX2J0bigi4peAIEJhY2siKQogICAgICAgIGJrMi5jbGlja2VkLmNvbm5lY3Qo"
    "bGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KGJrMikKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMg4pSA"
    "4pSAIFBBR0UgMzogbW9kaWZ5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAzID0gUVdpZGdl"
    "dCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01h"
    "cmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMy5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDMuYWRk"
    "V2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5BTUUiKSkKICAgICAgICBzZWxmLl9tb2RfbmFtZSA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9uYW1lKQogICAgICAg"
    "IGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNl"
    "bGYuX21vZF9kZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9k"
    "X2Rlc2MpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIElURU1TIChkb3Vi"
    "bGUtY2xpY2sgdG8gZWRpdCkiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUgPSBRVGFibGVXaWRn"
    "ZXQoMCwgMikKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9udGFs"
    "SGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhl"
    "YWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldFN0eWxlU2hlZXQo"
    "X2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfdGFi"
    "bGUsIDEpCgogICAgICAgIGJ0bnMzID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMzID0gX2dvdGhp"
    "Y19idG4oIuKcpiBTYXZlIik7IGMzID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAg"
    "IHMzLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnlfc2F2ZSkKICAgICAgICBjMy5jbGlj"
    "a2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAg"
    "ICAgYnRuczMuYWRkV2lkZ2V0KHMzKTsgYnRuczMuYWRkV2lkZ2V0KGMzKTsgYnRuczMuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgbDMuYWRkTGF5b3V0KGJ0bnMzKQogICAgICAgIHNlbGYuX3N0YWNrLmFk"
    "ZFdpZGdldChwMykKCiAgICAjIOKUgOKUgCBQQVJTRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYg"
    "cGFyc2Vfc2Nhbl90ZXh0KHJhdzogc3RyKSAtPiB0dXBsZVtzdHIsIGxpc3RbZGljdF1dOgogICAg"
    "ICAgICIiIgogICAgICAgIFBhcnNlIHJhdyBTTCBzY2FuIG91dHB1dCBpbnRvIChhdmF0YXJfbmFt"
    "ZSwgaXRlbXMpLgoKICAgICAgICBLRVkgRklYOiBCZWZvcmUgc3BsaXR0aW5nLCBpbnNlcnQgbmV3"
    "bGluZXMgYmVmb3JlIGV2ZXJ5IFtISDpNTV0KICAgICAgICB0aW1lc3RhbXAgc28gc2luZ2xlLWxp"
    "bmUgcGFzdGVzIHdvcmsgY29ycmVjdGx5LgoKICAgICAgICBFeHBlY3RlZCBmb3JtYXQ6CiAgICAg"
    "ICAgICAgIFsxMTo0N10gQXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50czoKICAgICAgICAg"
    "ICAgWzExOjQ3XSAuOiBJdGVtIE5hbWUgW0F0dGFjaG1lbnRdIENSRUFUT1I6IENyZWF0b3JOYW1l"
    "IFsxMTo0N10gLi4uCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHJhdy5zdHJpcCgpOgogICAg"
    "ICAgICAgICByZXR1cm4gIlVOS05PV04iLCBbXQoKICAgICAgICAjIOKUgOKUgCBTdGVwIDE6IG5v"
    "cm1hbGl6ZSDigJQgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSB0aW1lc3RhbXBzIOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIG5vcm1hbGl6ZWQgPSBfcmUuc3ViKHInXHMqKFxbXGR7MSwyfTpcZHsy"
    "fVxdKScsIHInXG5cMScsIHJhdykKICAgICAgICBsaW5lcyA9IFtsLnN0cmlwKCkgZm9yIGwgaW4g"
    "bm9ybWFsaXplZC5zcGxpdGxpbmVzKCkgaWYgbC5zdHJpcCgpXQoKICAgICAgICAjIOKUgOKUgCBT"
    "dGVwIDI6IGV4dHJhY3QgYXZhdGFyIG5hbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgYXZhdGFyX25hbWUgPSAiVU5LTk9XTiIKICAgICAgICBmb3IgbGlu"
    "ZSBpbiBsaW5lczoKICAgICAgICAgICAgIyAiQXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50"
    "cyIgb3Igc2ltaWxhcgogICAgICAgICAgICBtID0gX3JlLnNlYXJjaCgKICAgICAgICAgICAgICAg"
    "IHIiKFx3W1x3XHNdKz8pJ3NccytwdWJsaWNccythdHRhY2htZW50cyIsCiAgICAgICAgICAgICAg"
    "ICBsaW5lLCBfcmUuSQogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAg"
    "ICAgICBhdmF0YXJfbmFtZSA9IG0uZ3JvdXAoMSkuc3RyaXAoKQogICAgICAgICAgICAgICAgYnJl"
    "YWsKCiAgICAgICAgIyDilIDilIAgU3RlcCAzOiBleHRyYWN0IGl0ZW1zIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGl0ZW1z"
    "ID0gW10KICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgIyBTdHJpcCBsZWFk"
    "aW5nIHRpbWVzdGFtcAogICAgICAgICAgICBjb250ZW50ID0gX3JlLnN1YihyJ15cW1xkezEsMn06"
    "XGR7Mn1cXVxzKicsICcnLCBsaW5lKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCBjb250ZW50"
    "OgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGhlYWRlciBsaW5l"
    "cwogICAgICAgICAgICBpZiAiJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBpbiBjb250ZW50Lmxvd2Vy"
    "KCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBjb250ZW50Lmxvd2Vy"
    "KCkuc3RhcnRzd2l0aCgib2JqZWN0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "ICAgICAjIFNraXAgZGl2aWRlciBsaW5lcyDigJQgbGluZXMgdGhhdCBhcmUgbW9zdGx5IG9uZSBy"
    "ZXBlYXRlZCBjaGFyYWN0ZXIKICAgICAgICAgICAgIyBlLmcuIOKWguKWguKWguKWguKWguKWguKW"
    "guKWguKWguKWguKWguKWgiBvciDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAg"
    "b3Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIHN0cmlw"
    "cGVkID0gY29udGVudC5zdHJpcCgiLjogIikKICAgICAgICAgICAgaWYgc3RyaXBwZWQgYW5kIGxl"
    "bihzZXQoc3RyaXBwZWQpKSA8PSAyOgogICAgICAgICAgICAgICAgY29udGludWUgICMgb25lIG9y"
    "IHR3byB1bmlxdWUgY2hhcnMgPSBkaXZpZGVyIGxpbmUKCiAgICAgICAgICAgICMgVHJ5IHRvIGV4"
    "dHJhY3QgQ1JFQVRPUjogZmllbGQKICAgICAgICAgICAgY3JlYXRvciA9ICJVTktOT1dOIgogICAg"
    "ICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50CgogICAgICAgICAgICBjcmVhdG9yX21hdGNoID0g"
    "X3JlLnNlYXJjaCgKICAgICAgICAgICAgICAgIHInQ1JFQVRPUjpccyooW1x3XHNdKz8pKD86XHMq"
    "XFt8JCknLCBjb250ZW50LCBfcmUuSQogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIGNyZWF0"
    "b3JfbWF0Y2g6CiAgICAgICAgICAgICAgICBjcmVhdG9yICAgPSBjcmVhdG9yX21hdGNoLmdyb3Vw"
    "KDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnRbOmNyZWF0b3Jf"
    "bWF0Y2guc3RhcnQoKV0uc3RyaXAoKQoKICAgICAgICAgICAgIyBTdHJpcCBhdHRhY2htZW50IHBv"
    "aW50IHN1ZmZpeGVzIGxpa2UgW0xlZnRfRm9vdF0KICAgICAgICAgICAgaXRlbV9uYW1lID0gX3Jl"
    "LnN1YihyJ1xzKlxbW1x3XHNfXStcXScsICcnLCBpdGVtX25hbWUpLnN0cmlwKCkKICAgICAgICAg"
    "ICAgaXRlbV9uYW1lID0gaXRlbV9uYW1lLnN0cmlwKCIuOiAiKQoKICAgICAgICAgICAgaWYgaXRl"
    "bV9uYW1lIGFuZCBsZW4oaXRlbV9uYW1lKSA+IDE6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBl"
    "bmQoeyJpdGVtIjogaXRlbV9uYW1lLCAiY3JlYXRvciI6IGNyZWF0b3J9KQoKICAgICAgICByZXR1"
    "cm4gYXZhdGFyX25hbWUsIGl0ZW1zCgogICAgIyDilIDilIAgQ0FSRCBSRU5ERVJJTkcg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX2NhcmRzKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjYXJkcyAoa2VlcCBzdHJldGNoKQogICAgICAg"
    "IHdoaWxlIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgPiAxOgogICAgICAgICAgICBpdGVtID0g"
    "c2VsZi5fY2FyZF9sYXlvdXQudGFrZUF0KDApCiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6"
    "CiAgICAgICAgICAgICAgICBpdGVtLndpZGdldCgpLmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9y"
    "IHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBjYXJkID0gc2VsZi5fbWFrZV9jYXJk"
    "KHJlYykKICAgICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuaW5zZXJ0V2lkZ2V0KAogICAgICAg"
    "ICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSAtIDEsIGNhcmQKICAgICAgICAgICAg"
    "KQoKICAgIGRlZiBfbWFrZV9jYXJkKHNlbGYsIHJlYzogZGljdCkgLT4gUVdpZGdldDoKICAgICAg"
    "ICBjYXJkID0gUUZyYW1lKCkKICAgICAgICBpc19zZWxlY3RlZCA9IHJlYy5nZXQoInJlY29yZF9p"
    "ZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkCiAgICAgICAgY2FyZC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMGExMCcgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JH"
    "M307ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OIGlmIGlzX3Nl"
    "bGVjdGVkIGVsc2UgQ19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4"
    "OyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChj"
    "YXJkKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgNiwgOCwgNikKCiAgICAg"
    "ICAgbmFtZV9sYmwgPSBRTGFiZWwocmVjLmdldCgibmFtZSIsICJVTktOT1dOIikpCiAgICAgICAg"
    "bmFtZV9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklH"
    "SFQgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0dPTER9OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXpl"
    "OiAxMXB4OyBmb250LXdlaWdodDogYm9sZDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsiCiAgICAgICAgKQoKICAgICAgICBjb3VudCA9IGxlbihyZWMuZ2V0KCJpdGVtcyIsIFtdKSkK"
    "ICAgICAgICBjb3VudF9sYmwgPSBRTGFiZWwoZiJ7Y291bnR9IGl0ZW1zIikKICAgICAgICBjb3Vu"
    "dF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZv"
    "bnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAg"
    "KQoKICAgICAgICBkYXRlX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJjcmVhdGVkX2F0IiwgIiIpWzox"
    "MF0pCiAgICAgICAgZGF0ZV9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5hbWVfbGJsKQogICAg"
    "ICAgIGxheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGNvdW50X2xi"
    "bCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZygxMikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KGRhdGVfbGJsKQoKICAgICAgICAjIENsaWNrIHRvIHNlbGVjdAogICAgICAgIHJlY19pZCA9IHJl"
    "Yy5nZXQoInJlY29yZF9pZCIsICIiKQogICAgICAgIGNhcmQubW91c2VQcmVzc0V2ZW50ID0gbGFt"
    "YmRhIGUsIHJpZD1yZWNfaWQ6IHNlbGYuX3NlbGVjdF9jYXJkKHJpZCkKICAgICAgICByZXR1cm4g"
    "Y2FyZAoKICAgIGRlZiBfc2VsZWN0X2NhcmQoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRfaWQKICAgICAgICBzZWxmLl9idWls"
    "ZF9jYXJkcygpICAjIFJlYnVpbGQgdG8gc2hvdyBzZWxlY3Rpb24gaGlnaGxpZ2h0CgogICAgZGVm"
    "IF9zZWxlY3RlZF9yZWNvcmQoc2VsZikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmV0dXJu"
    "IG5leHQoCiAgICAgICAgICAgIChyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAg"
    "IGlmIHIuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZCksCiAgICAgICAgICAg"
    "IE5vbmUKICAgICAgICApCgogICAgIyDilIDilIAgQUNUSU9OUyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAg"
    "ICAgICAjIEVuc3VyZSByZWNvcmRfaWQgZmllbGQgZXhpc3RzCiAgICAgICAgY2hhbmdlZCA9IEZh"
    "bHNlCiAgICAgICAgZm9yIHIgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaWYgbm90IHIu"
    "Z2V0KCJyZWNvcmRfaWQiKToKICAgICAgICAgICAgICAgIHJbInJlY29yZF9pZCJdID0gci5nZXQo"
    "ImlkIikgb3Igc3RyKHV1aWQudXVpZDQoKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVl"
    "CiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwg"
    "c2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpCiAgICAgICAgc2VsZi5f"
    "c3RhY2suc2V0Q3VycmVudEluZGV4KDApCgogICAgZGVmIF9wcmV2aWV3X3BhcnNlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcmF3ID0gc2VsZi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAg"
    "bmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgc2VsZi5fYWRk"
    "X25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KG5hbWUpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcu"
    "c2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gaXRlbXNbOjIwXTogICMgcHJldmlldyBm"
    "aXJzdCAyMAogICAgICAgICAgICByID0gc2VsZi5fYWRkX3ByZXZpZXcucm93Q291bnQoKQogICAg"
    "ICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5f"
    "YWRkX3ByZXZpZXcuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJpdGVtIl0pKQog"
    "ICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDEsIFFUYWJsZVdpZGdldEl0"
    "ZW0oaXRbImNyZWF0b3IiXSkpCgogICAgZGVmIF9zaG93X2FkZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX2FkZF9uYW1lLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFj"
    "ZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIHNlbGYu"
    "X2FkZF9kZXNjLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfcmF3LmNsZWFyKCkKICAgICAgICBz"
    "ZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleCgxKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmF3"
    "ICA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2Vs"
    "Zi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIG92ZXJyaWRlX25hbWUgPSBzZWxmLl9hZGRf"
    "bmFtZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAg"
    "ICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJyZWNvcmRfaWQiOiAgIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICBvdmVycmlkZV9uYW1lIG9y"
    "IG5hbWUsCiAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IHNlbGYuX2FkZF9kZXNjLnRvUGxhaW5U"
    "ZXh0KClbOjI0NF0sCiAgICAgICAgICAgICJpdGVtcyI6ICAgICAgIGl0ZW1zLAogICAgICAgICAg"
    "ICAicmF3X3RleHQiOiAgICByYXcsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywKICAg"
    "ICAgICAgICAgInVwZGF0ZWRfYXQiOiAgbm93LAogICAgICAgIH0KICAgICAgICBzZWxmLl9yZWNv"
    "cmRzLmFwcGVuZChyZWNvcmQpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5f"
    "cmVjb3JkcykKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZFsicmVjb3JkX2lkIl0K"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2hvd19kaXNwbGF5KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3Qg"
    "cmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBk"
    "aXNwbGF5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRU"
    "ZXh0KGYi4p2nIHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Mu"
    "c2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFi"
    "bGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToK"
    "ICAgICAgICAgICAgciA9IHNlbGYuX2Rpc3BfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBz"
    "ZWxmLl9kaXNwX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxl"
    "LnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJp"
    "dGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEl0ZW0ociwgMSwKICAg"
    "ICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVhdG9yIiwiVU5LTk9XTiIp"
    "KSkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMikKCiAgICBkZWYgX2l0ZW1f"
    "Y29udGV4dF9tZW51KHNlbGYsIHBvcykgLT4gTm9uZToKICAgICAgICBpZHggPSBzZWxmLl9kaXNw"
    "X3RhYmxlLmluZGV4QXQocG9zKQogICAgICAgIGlmIG5vdCBpZHguaXNWYWxpZCgpOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBpdGVtX3RleHQgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShp"
    "ZHgucm93KCksIDApIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIi"
    "KSkudGV4dCgpCiAgICAgICAgY3JlYXRvciAgICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4"
    "LnJvdygpLCAxKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikp"
    "LnRleHQoKQogICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdldHMgaW1wb3J0IFFNZW51CiAgICAg"
    "ICAgbWVudSA9IFFNZW51KHNlbGYpCiAgICAgICAgbWVudS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAg"
    "IGFfaXRlbSAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEl0ZW0gTmFtZSIpCiAgICAgICAgYV9j"
    "cmVhdG9yID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQ3JlYXRvciIpCiAgICAgICAgYV9ib3RoICAg"
    "ID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQm90aCIpCiAgICAgICAgYWN0aW9uID0gbWVudS5leGVj"
    "KHNlbGYuX2Rpc3BfdGFibGUudmlld3BvcnQoKS5tYXBUb0dsb2JhbChwb3MpKQogICAgICAgIGNi"
    "ID0gUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpCiAgICAgICAgaWYgYWN0aW9uID09IGFfaXRlbTog"
    "ICAgY2Iuc2V0VGV4dChpdGVtX3RleHQpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0gYV9jcmVhdG9y"
    "OiBjYi5zZXRUZXh0KGNyZWF0b3IpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0gYV9ib3RoOiAgY2Iu"
    "c2V0VGV4dChmIntpdGVtX3RleHR9IOKAlCB7Y3JlYXRvcn0iKQoKICAgIGRlZiBfc2hvd19tb2Rp"
    "Znkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQog"
    "ICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNl"
    "bGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxl"
    "Y3QgYSBzY2FuIHRvIG1vZGlmeS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9t"
    "b2RfbmFtZS5zZXRUZXh0KHJlYy5nZXQoIm5hbWUiLCIiKSkKICAgICAgICBzZWxmLl9tb2RfZGVz"
    "Yy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX3Rh"
    "YmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6"
    "CiAgICAgICAgICAgIHIgPSBzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5z"
    "ZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRl"
    "bSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVhdG9yIiwiVU5LTk9XTiIpKSkK"
    "ICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMykKCiAgICBkZWYgX2RvX21vZGlm"
    "eV9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3Jk"
    "KCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWNbIm5h"
    "bWUiXSAgICAgICAgPSBzZWxmLl9tb2RfbmFtZS50ZXh0KCkuc3RyaXAoKSBvciAiVU5LTk9XTiIK"
    "ICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBzZWxmLl9tb2RfZGVzYy50ZXh0KClbOjI0NF0K"
    "ICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fbW9kX3RhYmxl"
    "LnJvd0NvdW50KCkpOgogICAgICAgICAgICBpdCAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSww"
    "KSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGNyICA9IChzZWxm"
    "Ll9tb2RfdGFibGUuaXRlbShpLDEpIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAg"
    "ICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0LnN0cmlwKCkgb3IgIlVOS05PV04iLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdG9yIjogY3Iuc3RyaXAoKSBvciAiVU5LTk9X"
    "TiJ9KQogICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICByZWNbInVwZGF0"
    "ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2Vs"
    "Zi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVz"
    "c2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBkZWxldGUuIikKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgbmFtZSA9IHJlYy5nZXQoIm5hbWUiLCJ0aGlzIHNjYW4iKQogICAgICAg"
    "IHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUg"
    "U2NhbiIsCiAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBUaGlzIGNhbm5vdCBiZSB1bmRv"
    "bmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3Nh"
    "Z2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1l"
    "c3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0g"
    "W3IgZm9yIHIgaW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IHIuZ2V0KCJyZWNvcmRfaWQiKSAhPSBzZWxmLl9zZWxlY3RlZF9pZF0KICAgICAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5fc2Vs"
    "ZWN0ZWRfaWQgPSBOb25lCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19y"
    "ZXBhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3Jk"
    "KCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlv"
    "bihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAi"
    "U2VsZWN0IGEgc2NhbiB0byByZS1wYXJzZS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBy"
    "YXcgPSByZWMuZ2V0KCJyYXdfdGV4dCIsIiIpCiAgICAgICAgaWYgbm90IHJhdzoKICAgICAgICAg"
    "ICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlIiwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIk5vIHJhdyB0ZXh0IHN0b3JlZCBmb3IgdGhpcyBzY2Fu"
    "LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9z"
    "Y2FuX3RleHQocmF3KQogICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICBy"
    "ZWNbIm5hbWUiXSAgICAgICA9IHJlY1sibmFtZSJdIG9yIG5hbWUKICAgICAgICByZWNbInVwZGF0"
    "ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZWQiLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiRm91bmQge2xlbihpdGVtcyl9IGl0ZW1z"
    "LiIpCgoKIyDilIDilIAgU0wgQ09NTUFORFMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTENvbW1hbmRzVGFi"
    "KFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBjb21tYW5kIHJlZmVyZW5jZSB0YWJs"
    "ZS4KICAgIEdvdGhpYyB0YWJsZSBzdHlsaW5nLiBDb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkIGJ1"
    "dHRvbiBwZXIgcm93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAg"
    "ID0gY2ZnX3BhdGgoInNsIikgLyAic2xfY29tbWFuZHMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVj"
    "b3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "b3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIuKcpiBBZGQi"
    "KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgPSBfZ290aGljX2J0bigi4pynIE1vZGlmeSIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAg"
    "ICBzZWxmLl9idG5fY29weSAgID0gX2dvdGhpY19idG4oIuKniSBDb3B5IENvbW1hbmQiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkNvcHkgc2VsZWN0ZWQgY29tbWFu"
    "ZCB0byBjbGlwYm9hcmQiKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoPSBfZ290aGljX2J0bigi"
    "4oa7IFJlZnJlc2giKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9k"
    "b19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9jb3B5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9j"
    "b3B5X2NvbW1hbmQpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2guY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYucmVmcmVzaCkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21v"
    "ZGlmeSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2NvcHks"
    "IHNlbGYuX2J0bl9yZWZyZXNoKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAg"
    "IGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNl"
    "bGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9y"
    "aXpvbnRhbEhlYWRlckxhYmVscyhbIkNvbW1hbmQiLCAiRGVzY3JpcHRpb24iXSkKICAgICAgICBz"
    "ZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAg"
    "ICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAg"
    "IDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5z"
    "ZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0"
    "aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGlu"
    "Z1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhp"
    "Y190YWJsZV9zdHlsZSgpKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoK"
    "ICAgICAgICBoaW50ID0gUUxhYmVsKAogICAgICAgICAgICAiU2VsZWN0IGEgcm93IGFuZCBjbGlj"
    "ayDip4kgQ29weSBDb21tYW5kIHRvIGNvcHkganVzdCB0aGUgY29tbWFuZCB0ZXh0LiIKICAgICAg"
    "ICApCiAgICAgICAgaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19U"
    "RVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoaGludCkKCiAgICBkZWYgcmVmcmVz"
    "aChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoImNvbW1hbmQiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwK"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCIi"
    "KSkpCgogICAgZGVmIF9jb3B5X2NvbW1hbmQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBz"
    "ZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBpdGVtID0gc2VsZi5fdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYg"
    "aXRlbToKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoaXRlbS50"
    "ZXh0KCkpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlh"
    "bG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgQ29tbWFuZCIpCiAgICAg"
    "ICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09M"
    "RH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGlu"
    "ZUVkaXQoKTsgZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6"
    "IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAg"
    "IGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBj"
    "eCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcu"
    "YWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRX"
    "aWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQog"
    "ICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAg"
    "ICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAg"
    "ICAgICAgICByZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51"
    "dWlkNCgpKSwKICAgICAgICAgICAgICAgICJjb21tYW5kIjogICAgIGNtZC50ZXh0KCkuc3RyaXAo"
    "KVs6MjQ0XSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2MudGV4dCgpLnN0cmlw"
    "KClbOjI0NF0sCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csICJ1cGRhdGVkX2F0"
    "Ijogbm93LAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJlY1siY29tbWFuZCJdOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjKQogICAgICAgICAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cg"
    "PSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBs"
    "ZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYu"
    "X3JlY29yZHNbcm93XQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0"
    "V2luZG93VGl0bGUoIk1vZGlmeSBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBR"
    "Rm9ybUxheW91dChkbGcpCiAgICAgICAgY21kICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJjb21tYW5k"
    "IiwiIikpCiAgICAgICAgZGVzYyA9IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIp"
    "KQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJv"
    "dygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikK"
    "ICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVj"
    "dChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQo"
    "Y3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFE"
    "aWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmVjWyJjb21tYW5kIl0gICAg"
    "ID0gY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1siZGVzY3JpcHRpb24i"
    "XSA9IGRlc2MudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJ1cGRhdGVkX2F0"
    "Il0gID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9"
    "IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxl"
    "bihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgY21kID0gc2VsZi5f"
    "cmVjb3Jkc1tyb3ddLmdldCgiY29tbWFuZCIsInRoaXMgY29tbWFuZCIpCiAgICAgICAgcmVwbHkg"
    "PSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSIsIGYiRGVs"
    "ZXRlICd7Y21kfSc/IiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVz"
    "IHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVw"
    "bHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgSk9CIFRSQUNL"
    "RVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBKb2JUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBK"
    "b2IgYXBwbGljYXRpb24gdHJhY2tpbmcuIEZ1bGwgcmVidWlsZCBmcm9tIHNwZWMuCiAgICBGaWVs"
    "ZHM6IENvbXBhbnksIEpvYiBUaXRsZSwgRGF0ZSBBcHBsaWVkLCBMaW5rLCBTdGF0dXMsIE5vdGVz"
    "LgogICAgTXVsdGktc2VsZWN0IGhpZGUvdW5oaWRlL2RlbGV0ZS4gQ1NWIGFuZCBUU1YgZXhwb3J0"
    "LgogICAgSGlkZGVuIHJvd3MgPSBjb21wbGV0ZWQvcmVqZWN0ZWQg4oCUIHN0aWxsIHN0b3JlZCwg"
    "anVzdCBub3Qgc2hvd24uCiAgICAiIiIKCiAgICBDT0xVTU5TID0gWyJDb21wYW55IiwgIkpvYiBU"
    "aXRsZSIsICJEYXRlIEFwcGxpZWQiLAogICAgICAgICAgICAgICAiTGluayIsICJTdGF0dXMiLCAi"
    "Tm90ZXMiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJt"
    "ZW1vcmllcyIpIC8gImpvYl90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxp"
    "c3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gRmFsc2UKICAgICAgICBz"
    "ZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3Vp"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAg"
    "cm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNp"
    "bmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQg"
    "ICAgPSBfZ290aGljX2J0bigiQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhp"
    "Y19idG4oIk1vZGlmeSIpCiAgICAgICAgc2VsZi5fYnRuX2hpZGUgICA9IF9nb3RoaWNfYnRuKCJB"
    "cmNoaXZlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJNYXJrIHNl"
    "bGVjdGVkIGFzIGNvbXBsZXRlZC9yZWplY3RlZCIpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSA9"
    "IF9nb3RoaWNfYnRuKCJSZXN0b3JlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJSZXN0b3JlIGFyY2hpdmVkIGFwcGxpY2F0aW9ucyIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUg"
    "PSBfZ290aGljX2J0bigiU2hvdyBBcmNoaXZlZCIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9"
    "IF9nb3RoaWNfYnRuKCJFeHBvcnQiKQoKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwg"
    "c2VsZi5fYnRuX21vZGlmeSwgc2VsZi5fYnRuX2hpZGUsCiAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2J0bl91bmhpZGUsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0"
    "bl90b2dnbGUsIHNlbGYuX2J0bl9leHBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0"
    "aCg3MCkKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBiYXIu"
    "YWRkV2lkZ2V0KGIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9k"
    "b19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2hpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2hpZGUpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "dW5oaWRlKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLmNsaWNrZWQuY29ubmVjdChzZWxmLl90"
    "b2dnbGVfaGlkZGVuKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2V4cG9ydCkKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCBsZW4oc2Vs"
    "Zi5DT0xVTU5TKSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxz"
    "KHNlbGYuQ09MVU1OUykKICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIo"
    "KQogICAgICAgICMgQ29tcGFueSBhbmQgSm9iIFRpdGxlIHN0cmV0Y2gKICAgICAgICBoaC5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJl"
    "dGNoKQogICAgICAgICMgRGF0ZSBBcHBsaWVkIOKAlCBmaXhlZCByZWFkYWJsZSB3aWR0aAogICAg"
    "ICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4"
    "ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMiwgMTAwKQogICAgICAgICMg"
    "TGluayBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBTdGF0dXMg4oCUIGZpeGVkIHdpZHRo"
    "CiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNCwgUUhlYWRlclZpZXcuUmVzaXplTW9k"
    "ZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCg0LCA4MCkKICAgICAg"
    "ICAjIE5vdGVzIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDUsIFFI"
    "ZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2Vs"
    "ZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJl"
    "aGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uTW9kZSgK"
    "ICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVj"
    "dGlvbikKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgIGRlZiByZWZyZXNoKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0"
    "aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4g"
    "c2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaGlkZGVuID0gYm9vbChyZWMuZ2V0KCJoaWRkZW4i"
    "LCBGYWxzZSkpCiAgICAgICAgICAgIGlmIGhpZGRlbiBhbmQgbm90IHNlbGYuX3Nob3dfaGlkZGVu"
    "OgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAg"
    "IHN0YXR1cyA9ICJBcmNoaXZlZCIgaWYgaGlkZGVuIGVsc2UgcmVjLmdldCgic3RhdHVzIiwiQWN0"
    "aXZlIikKICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBh"
    "bnkiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAg"
    "ICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICBzdGF0dXMsCiAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICBdCiAgICAgICAgICAgIGZvciBjLCB2IGlu"
    "IGVudW1lcmF0ZSh2YWxzKToKICAgICAgICAgICAgICAgIGl0ZW0gPSBRVGFibGVXaWRnZXRJdGVt"
    "KHN0cih2KSkKICAgICAgICAgICAgICAgIGlmIGhpZGRlbjoKICAgICAgICAgICAgICAgICAgICBp"
    "dGVtLnNldEZvcmVncm91bmQoUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0SXRlbShyLCBjLCBpdGVtKQogICAgICAgICAgICAjIFN0b3JlIHJlY29yZCBp"
    "bmRleCBpbiBmaXJzdCBjb2x1bW4ncyB1c2VyIGRhdGEKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "aXRlbShyLCAwKS5zZXREYXRhKAogICAgICAgICAgICAgICAgUXQuSXRlbURhdGFSb2xlLlVzZXJS"
    "b2xlLAogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5pbmRleChyZWMpCiAgICAgICAgICAg"
    "ICkKCiAgICBkZWYgX3NlbGVjdGVkX2luZGljZXMoc2VsZikgLT4gbGlzdFtpbnRdOgogICAgICAg"
    "IGluZGljZXMgPSBzZXQoKQogICAgICAgIGZvciBpdGVtIGluIHNlbGYuX3RhYmxlLnNlbGVjdGVk"
    "SXRlbXMoKToKICAgICAgICAgICAgcm93X2l0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKGl0ZW0ucm93"
    "KCksIDApCiAgICAgICAgICAgIGlmIHJvd19pdGVtOgogICAgICAgICAgICAgICAgaWR4ID0gcm93"
    "X2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgICAgICBpZiBp"
    "ZHggaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgaW5kaWNlcy5hZGQoaWR4KQogICAg"
    "ICAgIHJldHVybiBzb3J0ZWQoaW5kaWNlcykKCiAgICBkZWYgX2RpYWxvZyhzZWxmLCByZWM6IGRp"
    "Y3QgPSBOb25lKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBkbGcgID0gUURpYWxvZyhzZWxm"
    "KQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSm9iIEFwcGxpY2F0aW9uIikKICAgICAgICBk"
    "bGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsi"
    "KQogICAgICAgIGRsZy5yZXNpemUoNTAwLCAzMjApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0"
    "KGRsZykKCiAgICAgICAgY29tcGFueSA9IFFMaW5lRWRpdChyZWMuZ2V0KCJjb21wYW55IiwiIikg"
    "aWYgcmVjIGVsc2UgIiIpCiAgICAgICAgdGl0bGUgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJqb2Jf"
    "dGl0bGUiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZSAgICAgID0gUURhdGVFZGl0KCkK"
    "ICAgICAgICBkZS5zZXRDYWxlbmRhclBvcHVwKFRydWUpCiAgICAgICAgZGUuc2V0RGlzcGxheUZv"
    "cm1hdCgieXl5eS1NTS1kZCIpCiAgICAgICAgaWYgcmVjIGFuZCByZWMuZ2V0KCJkYXRlX2FwcGxp"
    "ZWQiKToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5mcm9tU3RyaW5nKHJlY1siZGF0ZV9h"
    "cHBsaWVkIl0sInl5eXktTU0tZGQiKSkKICAgICAgICBlbHNlOgogICAgICAgICAgICBkZS5zZXRE"
    "YXRlKFFEYXRlLmN1cnJlbnREYXRlKCkpCiAgICAgICAgbGluayAgICA9IFFMaW5lRWRpdChyZWMu"
    "Z2V0KCJsaW5rIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgc3RhdHVzICA9IFFMaW5lRWRp"
    "dChyZWMuZ2V0KCJzdGF0dXMiLCJBcHBsaWVkIikgaWYgcmVjIGVsc2UgIkFwcGxpZWQiKQogICAg"
    "ICAgIG5vdGVzICAgPSBRTGluZUVkaXQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAi"
    "IikKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIkNvbXBhbnk6"
    "IiwgY29tcGFueSksICgiSm9iIFRpdGxlOiIsIHRpdGxlKSwKICAgICAgICAgICAgKCJEYXRlIEFw"
    "cGxpZWQ6IiwgZGUpLCAoIkxpbms6IiwgbGluayksCiAgICAgICAgICAgICgiU3RhdHVzOiIsIHN0"
    "YXR1cyksICgiTm90ZXM6Iiwgbm90ZXMpLAogICAgICAgIF06CiAgICAgICAgICAgIGZvcm0uYWRk"
    "Um93KGxhYmVsLCB3aWRnZXQpCgogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "b2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAg"
    "ICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRs"
    "Zy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkK"
    "ICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFs"
    "b2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAg"
    "ICAgICJjb21wYW55IjogICAgICBjb21wYW55LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAg"
    "ICAgImpvYl90aXRsZSI6ICAgIHRpdGxlLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAg"
    "ImRhdGVfYXBwbGllZCI6IGRlLmRhdGUoKS50b1N0cmluZygieXl5eS1NTS1kZCIpLAogICAgICAg"
    "ICAgICAgICAgImxpbmsiOiAgICAgICAgIGxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAg"
    "ICAgICAic3RhdHVzIjogICAgICAgc3RhdHVzLnRleHQoKS5zdHJpcCgpIG9yICJBcHBsaWVkIiwK"
    "ICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgICBub3Rlcy50ZXh0KCkuc3RyaXAoKSwKICAg"
    "ICAgICAgICAgfQogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBwID0gc2VsZi5fZGlhbG9nKCkKICAgICAgICBpZiBub3QgcDoKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNv"
    "Zm9ybWF0KCkKICAgICAgICBwLnVwZGF0ZSh7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAg"
    "IHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAiaGlkZGVuIjogICAgICAgICBGYWxzZSwK"
    "ICAgICAgICAgICAgImNvbXBsZXRlZF9kYXRlIjogTm9uZSwKICAgICAgICAgICAgImNyZWF0ZWRf"
    "YXQiOiAgICAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAg"
    "fSkKICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChwKQogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYg"
    "X2RvX21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIGlkeHMgPSBzZWxmLl9zZWxlY3RlZF9p"
    "bmRpY2VzKCkKICAgICAgICBpZiBsZW4oaWR4cykgIT0gMToKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oc2VsZiwgIk1vZGlmeSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJTZWxlY3QgZXhhY3RseSBvbmUgcm93IHRvIG1vZGlmeS4iKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW2lkeHNbMF1dCiAgICAgICAgcCAg"
    "ID0gc2VsZi5fZGlhbG9nKHJlYykKICAgICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgcmVjLnVwZGF0ZShwKQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRp"
    "bWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9k"
    "b19oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9p"
    "bmRpY2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgICAgICA9IFRydWUKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiY29tcGxldGVkX2RhdGUiXSA9ICgKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF0uZ2V0KCJjb21wbGV0ZWRfZGF0ZSIp"
    "IG9yCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuZGF0ZSgpLmlzb2Zvcm1hdCgp"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bInVw"
    "ZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYg"
    "X2RvX3VuaGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0"
    "ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICA9IEZhbHNlCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgKICAgICAg"
    "ICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGlkeHMgPSBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAgICBpZiBu"
    "b3QgaWR4czoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5x"
    "dWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSIsCiAgICAgICAgICAgIGYiRGVsZXRl"
    "IHtsZW4oaWR4cyl9IHNlbGVjdGVkIGFwcGxpY2F0aW9uKHMpPyBDYW5ub3QgYmUgdW5kb25lLiIs"
    "CiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94"
    "LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdl"
    "Qm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgYmFkID0gc2V0KGlkeHMpCiAgICAg"
    "ICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgaSwgciBpbiBlbnVtZXJhdGUoc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBpIG5vdCBpbiBiYWRdCiAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAg"
    "IHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF90b2dnbGVfaGlkZGVuKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBub3Qgc2VsZi5fc2hvd19oaWRkZW4KICAgICAgICBz"
    "ZWxmLl9idG5fdG9nZ2xlLnNldFRleHQoCiAgICAgICAgICAgICLimIAgSGlkZSBBcmNoaXZlZCIg"
    "aWYgc2VsZi5fc2hvd19oaWRkZW4gZWxzZSAi4pi9IFNob3cgQXJjaGl2ZWQiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBwYXRoLCBmaWx0ID0gUUZpbGVEaWFsb2cuZ2V0U2F2ZUZpbGVOYW1lKAogICAgICAg"
    "ICAgICBzZWxmLCAiRXhwb3J0IEpvYiBUcmFja2VyIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRo"
    "KCJleHBvcnRzIikgLyAiam9iX3RyYWNrZXIuY3N2IiksCiAgICAgICAgICAgICJDU1YgRmlsZXMg"
    "KCouY3N2KTs7VGFiIERlbGltaXRlZCAoKi50eHQpIgogICAgICAgICkKICAgICAgICBpZiBub3Qg"
    "cGF0aDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZGVsaW0gPSAiXHQiIGlmIHBhdGgubG93"
    "ZXIoKS5lbmRzd2l0aCgiLnR4dCIpIGVsc2UgIiwiCiAgICAgICAgaGVhZGVyID0gWyJjb21wYW55"
    "Iiwiam9iX3RpdGxlIiwiZGF0ZV9hcHBsaWVkIiwibGluayIsCiAgICAgICAgICAgICAgICAgICJz"
    "dGF0dXMiLCJoaWRkZW4iLCJjb21wbGV0ZWRfZGF0ZSIsIm5vdGVzIl0KICAgICAgICB3aXRoIG9w"
    "ZW4ocGF0aCwgInciLCBlbmNvZGluZz0idXRmLTgiLCBuZXdsaW5lPSIiKSBhcyBmOgogICAgICAg"
    "ICAgICBmLndyaXRlKGRlbGltLmpvaW4oaGVhZGVyKSArICJcbiIpCiAgICAgICAgICAgIGZvciBy"
    "ZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5n"
    "ZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBw"
    "bGllZCIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAg"
    "ICAgICAgICAgICAgICByZWMuZ2V0KCJzdGF0dXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICBz"
    "dHIoYm9vbChyZWMuZ2V0KCJoaWRkZW4iLEZhbHNlKSkpLAogICAgICAgICAgICAgICAgICAgIHJl"
    "Yy5nZXQoImNvbXBsZXRlZF9kYXRlIiwiIikgb3IgIiIsCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgIF0KICAgICAgICAgICAgICAgIGYud3Jp"
    "dGUoZGVsaW0uam9pbigKICAgICAgICAgICAgICAgICAgICBzdHIodikucmVwbGFjZSgiXG4iLCIg"
    "IikucmVwbGFjZShkZWxpbSwiICIpCiAgICAgICAgICAgICAgICAgICAgZm9yIHYgaW4gdmFscwog"
    "ICAgICAgICAgICAgICAgKSArICJcbiIpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "c2VsZiwgIkV4cG9ydGVkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIlNhdmVk"
    "IHRvIHtwYXRofSIpCgoKIyDilIDilIAgU0VMRiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIFJlY29yZHNUYWIoUVdpZGdldCk6CiAgICAiIiJHb29nbGUgRHJpdmUvRG9jcyBy"
    "ZWNvcmRzIGJyb3dzZXIgdGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94"
    "TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikK"
    "ICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBR"
    "TGFiZWwoIlJlY29yZHMgYXJlIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNf"
    "bGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAg"
    "ICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgc2Vs"
    "Zi5wYXRoX2xhYmVsID0gUUxhYmVsKCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAgc2VsZi5wYXRo"
    "X2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAg"
    "ICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5wYXRoX2xhYmVsKQoKICAgICAgICBzZWxm"
    "LnJlY29yZHNfbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7"
    "Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiCiAgICAgICAgKQogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KHNlbGYucmVjb3Jkc19saXN0LCAxKQoKICAgIGRlZiBzZXRfaXRlbXMo"
    "c2VsZiwgZmlsZXM6IGxpc3RbZGljdF0sIHBhdGhfdGV4dDogc3RyID0gIk15IERyaXZlIikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0VGV4dChmIlBhdGg6IHtwYXRoX3RleHR9"
    "IikKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGZpbGVfaW5m"
    "byBpbiBmaWxlczoKICAgICAgICAgICAgdGl0bGUgPSAoZmlsZV9pbmZvLmdldCgibmFtZSIpIG9y"
    "ICJVbnRpdGxlZCIpLnN0cmlwKCkgb3IgIlVudGl0bGVkIgogICAgICAgICAgICBtaW1lID0gKGZp"
    "bGVfaW5mby5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbWlt"
    "ZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciI6CiAgICAgICAgICAgICAg"
    "ICBwcmVmaXggPSAi8J+TgSIKICAgICAgICAgICAgZWxpZiBtaW1lID09ICJhcHBsaWNhdGlvbi92"
    "bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk50i"
    "CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+ThCIKICAgICAg"
    "ICAgICAgbW9kaWZpZWQgPSAoZmlsZV9pbmZvLmdldCgibW9kaWZpZWRUaW1lIikgb3IgIiIpLnJl"
    "cGxhY2UoIlQiLCAiICIpLnJlcGxhY2UoIloiLCAiIFVUQyIpCiAgICAgICAgICAgIHRleHQgPSBm"
    "IntwcmVmaXh9IHt0aXRsZX0iICsgKGYiICAgIFt7bW9kaWZpZWR9XSIgaWYgbW9kaWZpZWQgZWxz"
    "ZSAiIikKICAgICAgICAgICAgaXRlbSA9IFFMaXN0V2lkZ2V0SXRlbSh0ZXh0KQogICAgICAgICAg"
    "ICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBmaWxlX2luZm8pCiAgICAg"
    "ICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmFkZEl0ZW0oaXRlbSkKICAgICAgICBzZWxmLnN0YXR1"
    "c19sYWJlbC5zZXRUZXh0KGYiTG9hZGVkIHtsZW4oZmlsZXMpfSBHb29nbGUgRHJpdmUgaXRlbShz"
    "KS4iKQoKCmNsYXNzIFRhc2tzVGFiKFFXaWRnZXQpOgogICAgIiIiVGFzayByZWdpc3RyeSArIEdv"
    "b2dsZS1maXJzdCBlZGl0b3Igd29ya2Zsb3cgdGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXygKICAg"
    "ICAgICBzZWxmLAogICAgICAgIHRhc2tzX3Byb3ZpZGVyLAogICAgICAgIG9uX2FkZF9lZGl0b3Jf"
    "b3BlbiwKICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZCwKICAgICAgICBvbl9jYW5jZWxfc2Vs"
    "ZWN0ZWQsCiAgICAgICAgb25fdG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICBvbl9wdXJnZV9jb21w"
    "bGV0ZWQsCiAgICAgICAgb25fZmlsdGVyX2NoYW5nZWQsCiAgICAgICAgb25fZWRpdG9yX3NhdmUs"
    "CiAgICAgICAgb25fZWRpdG9yX2NhbmNlbCwKICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9Tm9u"
    "ZSwKICAgICAgICBwYXJlbnQ9Tm9uZSwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fdGFza3NfcHJvdmlkZXIgPSB0YXNrc19wcm92aWRlcgogICAg"
    "ICAgIHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbiA9IG9uX2FkZF9lZGl0b3Jfb3BlbgogICAgICAg"
    "IHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkID0gb25fY29tcGxldGVfc2VsZWN0ZWQKICAgICAg"
    "ICBzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQgPSBvbl9jYW5jZWxfc2VsZWN0ZWQKICAgICAgICBz"
    "ZWxmLl9vbl90b2dnbGVfY29tcGxldGVkID0gb25fdG9nZ2xlX2NvbXBsZXRlZAogICAgICAgIHNl"
    "bGYuX29uX3B1cmdlX2NvbXBsZXRlZCA9IG9uX3B1cmdlX2NvbXBsZXRlZAogICAgICAgIHNlbGYu"
    "X29uX2ZpbHRlcl9jaGFuZ2VkID0gb25fZmlsdGVyX2NoYW5nZWQKICAgICAgICBzZWxmLl9vbl9l"
    "ZGl0b3Jfc2F2ZSA9IG9uX2VkaXRvcl9zYXZlCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX2NhbmNl"
    "bCA9IG9uX2VkaXRvcl9jYW5jZWwKICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlciA9IGRpYWdub3N0"
    "aWNzX2xvZ2dlcgogICAgICAgIHNlbGYuX3Nob3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBz"
    "ZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgogICAg"
    "ZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2sgPSBRU3RhY2tl"
    "ZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi53b3Jrc3BhY2Vfc3RhY2ssIDEp"
    "CgogICAgICAgIG5vcm1hbCA9IFFXaWRnZXQoKQogICAgICAgIG5vcm1hbF9sYXlvdXQgPSBRVkJv"
    "eExheW91dChub3JtYWwpCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICBub3JtYWxfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAg"
    "c2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlRhc2sgcmVnaXN0cnkgaXMgbm90IGxvYWRlZCB5"
    "ZXQuIikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERBVEUgUkFO"
    "R0UiKSkKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAg"
    "ICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIldFRUsiLCAid2VlayIpCiAgICAgICAg"
    "c2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJNT05USCIsICJtb250aCIpCiAgICAgICAg"
    "c2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJORVhUIDMgTU9OVEhTIiwgIm5leHRfM19t"
    "b250aHMiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiWUVBUiIsICJ5"
    "ZWFyIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLnNldEN1cnJlbnRJbmRleCgyKQog"
    "ICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0"
    "KAogICAgICAgICAgICBsYW1iZGEgXzogc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQoc2VsZi50YXNr"
    "X2ZpbHRlcl9jb21iby5jdXJyZW50RGF0YSgpIG9yICJuZXh0XzNfbW9udGhzIikKICAgICAgICAp"
    "CiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi50YXNrX2ZpbHRlcl9jb21ibykKICAg"
    "ICAgICBmaWx0ZXJfcm93LmFkZFN0cmV0Y2goMSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExh"
    "eW91dChmaWx0ZXJfcm93KQoKICAgICAgICBzZWxmLnRhc2tfdGFibGUgPSBRVGFibGVXaWRnZXQo"
    "MCwgNCkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhb"
    "IlN0YXR1cyIsICJEdWUiLCAiVGFzayIsICJTb3VyY2UiXSkKICAgICAgICBzZWxmLnRhc2tfdGFi"
    "bGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZp"
    "b3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U2VsZWN0aW9uTW9kZShR"
    "QWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAg"
    "IHNlbGYudGFza190YWJsZS5zZXRFZGl0VHJpZ2dlcnMoUUFic3RyYWN0SXRlbVZpZXcuRWRpdFRy"
    "aWdnZXIuTm9FZGl0VHJpZ2dlcnMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnZlcnRpY2FsSGVh"
    "ZGVyKCkuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRh"
    "bEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "UmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXpl"
    "VG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNl"
    "dFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAg"
    "ICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKDMsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBz"
    "ZWxmLnRhc2tfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBk"
    "YXRlX2FjdGlvbl9idXR0b25fc3RhdGUpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi50YXNrX3RhYmxlLCAxKQoKICAgICAgICBhY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZSA9IF9nb3RoaWNfYnRuKCJBREQgVEFTSyIp"
    "CiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzayA9IF9nb3RoaWNfYnRuKCJDT01QTEVURSBT"
    "RUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2sgPSBfZ290aGljX2J0bigiQ0FO"
    "Q0VMIFNFTEVDVEVEIikKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkID0gX2dvdGhp"
    "Y19idG4oIlNIT1cgQ09NUExFVEVEIikKICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQg"
    "PSBfZ290aGljX2J0bigiUFVSR0UgQ09NUExFVEVEIikKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFz"
    "a193b3Jrc3BhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbikKICAg"
    "ICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jb21w"
    "bGV0ZV9zZWxlY3RlZCkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21w"
    "bGV0ZWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQpCiAgICAgICAg"
    "c2VsZi5idG5fcHVyZ2VfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9wdXJnZV9j"
    "b21wbGV0ZWQpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKEZhbHNl"
    "KQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAg"
    "Zm9yIGJ0biBpbiAoCiAgICAgICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZSwKICAg"
    "ICAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzaywKICAgICAgICAgICAgc2VsZi5idG5fY2Fu"
    "Y2VsX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAg"
    "ICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCwKICAgICAgICApOgogICAgICAgICAgICBhY3Rp"
    "b25zLmFkZFdpZGdldChidG4pCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoYWN0aW9u"
    "cykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQobm9ybWFsKQoKICAgICAg"
    "ICBlZGl0b3IgPSBRV2lkZ2V0KCkKICAgICAgICBlZGl0b3JfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "ZWRpdG9yKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgZWRpdG9yX2xh"
    "eW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgVEFTSyBFRElUT1Ig4oCUIEdPT0dMRS1G"
    "SVJTVCIpKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJD"
    "b25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFyLiIpCiAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyBib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBl"
    "ZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCkKICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3JfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIlRhc2sgTmFtZSIpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9zdGFydF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX3N0YXJ0X2RhdGUuc2V0UGxhY2Vob2xkZXJUZXh0KCJTdGFydCBEYXRlIChZWVlZLU1N"
    "LUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJT"
    "dGFydCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUuc2V0UGxhY2Vob2xk"
    "ZXJUZXh0KCJFbmQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "ZW5kX3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX2xvY2F0aW9uID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xv"
    "Y2F0aW9uLnNldFBsYWNlaG9sZGVyVGV4dCgiTG9jYXRpb24gKG9wdGlvbmFsKSIpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0UGxhY2Vob2xkZXJUZXh0KCJSZWN1cnJlbmNlIFJSVUxF"
    "IChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfYWxsX2RheSA9IFFDaGVja0Jv"
    "eCgiQWxsLWRheSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3RlcyA9IFFUZXh0RWRpdCgp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRQbGFjZWhvbGRlclRleHQoIk5vdGVz"
    "IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldE1heGltdW1IZWlnaHQoOTApCiAg"
    "ICAgICAgZm9yIHdpZGdldCBpbiAoCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSwK"
    "ICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLAogICAgICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5k"
    "X2RhdGUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUsCiAgICAgICAgICAg"
    "IHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24sCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "cmVjdXJyZW5jZSwKICAgICAgICApOgogICAgICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdl"
    "dCh3aWRnZXQpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRv"
    "cl9hbGxfZGF5KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0"
    "b3Jfbm90ZXMsIDEpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgYnRuX3NhdmUgPSBfZ290aGljX2J0bigiU0FWRSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9n"
    "b3RoaWNfYnRuKCJDQU5DRUwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9lZGl0b3Jfc2F2ZSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9lZGl0b3JfY2FuY2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5f"
    "c2F2ZSkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAg"
    "ICBlZGl0b3JfYWN0aW9ucy5hZGRTdHJldGNoKDEpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRM"
    "YXlvdXQoZWRpdG9yX2FjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lk"
    "Z2V0KGVkaXRvcikKCiAgICAgICAgc2VsZi5ub3JtYWxfd29ya3NwYWNlID0gbm9ybWFsCiAgICAg"
    "ICAgc2VsZi5lZGl0b3Jfd29ya3NwYWNlID0gZWRpdG9yCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vf"
    "c3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1hbF93b3Jrc3BhY2UpCgogICAgZGVmIF91"
    "cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGVuYWJsZWQg"
    "PSBib29sKHNlbGYuc2VsZWN0ZWRfdGFza19pZHMoKSkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0"
    "ZV90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5z"
    "ZXRFbmFibGVkKGVuYWJsZWQpCgogICAgZGVmIHNlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxp"
    "c3Rbc3RyXToKICAgICAgICBpZHM6IGxpc3Rbc3RyXSA9IFtdCiAgICAgICAgZm9yIHIgaW4gcmFu"
    "Z2Uoc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBzdGF0dXNfaXRlbSA9"
    "IHNlbGYudGFza190YWJsZS5pdGVtKHIsIDApCiAgICAgICAgICAgIGlmIHN0YXR1c19pdGVtIGlz"
    "IE5vbmU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3Qgc3RhdHVz"
    "X2l0ZW0uaXNTZWxlY3RlZCgpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAg"
    "dGFza19pZCA9IHN0YXR1c19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgICAgICBpZiB0YXNrX2lkIGFuZCB0YXNrX2lkIG5vdCBpbiBpZHM6CiAgICAgICAgICAgICAg"
    "ICBpZHMuYXBwZW5kKHRhc2tfaWQpCiAgICAgICAgcmV0dXJuIGlkcwoKICAgIGRlZiBsb2FkX3Rh"
    "c2tzKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHNlbGYudGFza190"
    "YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAg"
    "ICByb3cgPSBzZWxmLnRhc2tfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLnRhc2tf"
    "dGFibGUuaW5zZXJ0Um93KHJvdykKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0"
    "dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2ljb24gPSAi4piR"
    "IiBpZiBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn0gZWxzZSAi4oCiIgogICAg"
    "ICAgICAgICBkdWUgPSAodGFzay5nZXQoImR1ZV9hdCIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAi"
    "KQogICAgICAgICAgICB0ZXh0ID0gKHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVyIikuc3Ry"
    "aXAoKSBvciAiUmVtaW5kZXIiCiAgICAgICAgICAgIHNvdXJjZSA9ICh0YXNrLmdldCgic291cmNl"
    "Iikgb3IgImxvY2FsIikubG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJsZVdp"
    "ZGdldEl0ZW0oZiJ7c3RhdHVzX2ljb259IHtzdGF0dXN9IikKICAgICAgICAgICAgc3RhdHVzX2l0"
    "ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIHRhc2suZ2V0KCJpZCIpKQogICAg"
    "ICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDAsIHN0YXR1c19pdGVtKQogICAg"
    "ICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDEsIFFUYWJsZVdpZGdldEl0ZW0o"
    "ZHVlKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVX"
    "aWRnZXRJdGVtKHRleHQpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3cs"
    "IDMsIFFUYWJsZVdpZGdldEl0ZW0oc291cmNlKSkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5z"
    "ZXRUZXh0KGYiTG9hZGVkIHtsZW4odGFza3MpfSB0YXNrKHMpLiIpCiAgICAgICAgc2VsZi5fdXBk"
    "YXRlX2FjdGlvbl9idXR0b25fc3RhdGUoKQoKICAgIGRlZiBfZGlhZyhzZWxmLCBtZXNzYWdlOiBz"
    "dHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBpZiBzZWxmLl9kaWFnX2xvZ2dlcjoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbG9nZ2Vy"
    "KG1lc3NhZ2UsIGxldmVsKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBh"
    "c3MKCiAgICBkZWYgc3RvcF9yZWZyZXNoX3dvcmtlcihzZWxmLCByZWFzb246IHN0ciA9ICIiKSAt"
    "PiBOb25lOgogICAgICAgIHRocmVhZCA9IGdldGF0dHIoc2VsZiwgIl9yZWZyZXNoX3RocmVhZCIs"
    "IE5vbmUpCiAgICAgICAgaWYgdGhyZWFkIGlzIG5vdCBOb25lIGFuZCBoYXNhdHRyKHRocmVhZCwg"
    "ImlzUnVubmluZyIpIGFuZCB0aHJlYWQuaXNSdW5uaW5nKCk6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWcoCiAgICAgICAgICAgICAgICBmIltUQVNLU11bVEhSRUFEXVtXQVJOXSBzdG9wIHJlcXVlc3Rl"
    "ZCBmb3IgcmVmcmVzaCB3b3JrZXIgcmVhc29uPXtyZWFzb24gb3IgJ3Vuc3BlY2lmaWVkJ30iLAog"
    "ICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIHRocmVhZC5yZXF1ZXN0SW50ZXJydXB0aW9uKCkKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgdGhyZWFkLnF1aXQoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0aHJlYWQud2FpdCgyMDAwKQogICAgICAg"
    "IHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgbm90IGNhbGxhYmxlKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKToKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLmxvYWRfdGFza3Moc2Vs"
    "Zi5fdGFza3NfcHJvdmlkZXIoKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnKGYiW1RBU0tTXVtUQUJdW0VSUk9SXSByZWZyZXNoIGZhaWxlZDog"
    "e2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFz"
    "b249InRhc2tzX3RhYl9yZWZyZXNoX2V4Y2VwdGlvbiIpCgogICAgZGVmIGNsb3NlRXZlbnQoc2Vs"
    "ZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNv"
    "bj0idGFza3NfdGFiX2Nsb3NlIikKICAgICAgICBzdXBlcigpLmNsb3NlRXZlbnQoZXZlbnQpCgog"
    "ICAgZGVmIHNldF9zaG93X2NvbXBsZXRlZChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX3Nob3dfY29tcGxldGVkID0gYm9vbChlbmFibGVkKQogICAgICAgIHNlbGYu"
    "YnRuX3RvZ2dsZV9jb21wbGV0ZWQuc2V0VGV4dCgiSElERSBDT01QTEVURUQiIGlmIHNlbGYuX3No"
    "b3dfY29tcGxldGVkIGVsc2UgIlNIT1cgQ09NUExFVEVEIikKCiAgICBkZWYgc2V0X3N0YXR1cyhz"
    "ZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+IE5vbmU6CiAgICAgICAgY29sb3Ig"
    "PSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19URVhUX0RJTQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "c3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtjb2xvcn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRp"
    "bmc6IDZweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVs"
    "LnNldFRleHQodGV4dCkKCiAgICBkZWYgb3Blbl9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYuZWRpdG9yX3dvcmtz"
    "cGFjZSkKCiAgICBkZWYgY2xvc2VfZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53"
    "b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1hbF93b3Jrc3BhY2UpCgoK"
    "Y2xhc3MgU2VsZlRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYSdzIGludGVybmFsIGRp"
    "YWxvZ3VlIHNwYWNlLgogICAgUmVjZWl2ZXM6IGlkbGUgbmFycmF0aXZlIG91dHB1dCwgdW5zb2xp"
    "Y2l0ZWQgdHJhbnNtaXNzaW9ucywKICAgICAgICAgICAgICBQb0kgbGlzdCBmcm9tIGRhaWx5IHJl"
    "ZmxlY3Rpb24sIHVuYW5zd2VyZWQgcXVlc3Rpb24gZmxhZ3MsCiAgICAgICAgICAgICAgam91cm5h"
    "bCBsb2FkIG5vdGlmaWNhdGlvbnMuCiAgICBSZWFkLW9ubHkgZGlzcGxheS4gU2VwYXJhdGUgZnJv"
    "bSBwZXJzb25hIGNoYXQgdGFiIGFsd2F5cy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "cm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMo"
    "NCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRyID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIElOTkVS"
    "IFNBTkNUVU0g4oCUIHtERUNLX05BTUUudXBwZXIoKX0nUyBQUklWQVRFIFRIT1VHSFRTIikpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19idG4oIuKclyBDbGVhciIpCiAgICAgICAg"
    "c2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAg"
    "ICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91"
    "dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYu"
    "X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BVUlBMRV9ESU19OyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXpl"
    "OiAxMXB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBhcHBlbmQoc2VsZiwgbGFiZWw6IHN0ciwgdGV4dDog"
    "c3RyKSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1l"
    "KCIlSDolTTolUyIpCiAgICAgICAgY29sb3JzID0gewogICAgICAgICAgICAiTkFSUkFUSVZFIjog"
    "IENfR09MRCwKICAgICAgICAgICAgIlJFRkxFQ1RJT04iOiBDX1BVUlBMRSwKICAgICAgICAgICAg"
    "IkpPVVJOQUwiOiAgICBDX1NJTFZFUiwKICAgICAgICAgICAgIlBPSSI6ICAgICAgICBDX0dPTERf"
    "RElNLAogICAgICAgICAgICAiU1lTVEVNIjogICAgIENfVEVYVF9ESU0sCiAgICAgICAgfQogICAg"
    "ICAgIGNvbG9yID0gY29sb3JzLmdldChsYWJlbC51cHBlcigpLCBDX0dPTEQpCiAgICAgICAgc2Vs"
    "Zi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RF"
    "WFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8"
    "L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyBmb250LXdl"
    "aWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ+KdpyB7bGFiZWx9PC9zcGFuPjxicj4nCiAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3RleHR9PC9zcGFuPicKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoIiIpCiAgICAgICAgc2VsZi5fZGlz"
    "cGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNw"
    "bGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBjbGVh"
    "cihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSA"
    "IERJQUdOT1NUSUNTIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRGlhZ25vc3RpY3NUYWIoUVdpZGdldCk6CiAg"
    "ICAiIiIKICAgIEJhY2tlbmQgZGlhZ25vc3RpY3MgZGlzcGxheS4KICAgIFJlY2VpdmVzOiBoYXJk"
    "d2FyZSBkZXRlY3Rpb24gcmVzdWx0cywgZGVwZW5kZW5jeSBjaGVjayByZXN1bHRzLAogICAgICAg"
    "ICAgICAgIEFQSSBlcnJvcnMsIHN5bmMgZmFpbHVyZXMsIHRpbWVyIGV2ZW50cywgam91cm5hbCBs"
    "b2FkIG5vdGljZXMsCiAgICAgICAgICAgICAgbW9kZWwgbG9hZCBzdGF0dXMsIEdvb2dsZSBhdXRo"
    "IGV2ZW50cy4KICAgIEFsd2F5cyBzZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIuCiAgICAi"
    "IiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0"
    "KF9zZWN0aW9uX2xibCgi4p2nIERJQUdOT1NUSUNTIOKAlCBTWVNURU0gJiBCQUNLRU5EIExPRyIp"
    "KQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9j"
    "bGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgp"
    "CiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjog"
    "e0NfU0lMVkVSfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTogJ0NvdXJpZXIgTmV3JywgbW9ub3NwYWNlOyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBsb2coc2Vs"
    "ZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIHRp"
    "bWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgbGV2"
    "ZWxfY29sb3JzID0gewogICAgICAgICAgICAiSU5GTyI6ICBDX1NJTFZFUiwKICAgICAgICAgICAg"
    "Ik9LIjogICAgQ19HUkVFTiwKICAgICAgICAgICAgIldBUk4iOiAgQ19HT0xELAogICAgICAgICAg"
    "ICAiRVJST1IiOiBDX0JMT09ELAogICAgICAgICAgICAiREVCVUciOiBDX1RFWFRfRElNLAogICAg"
    "ICAgIH0KICAgICAgICBjb2xvciA9IGxldmVsX2NvbG9ycy5nZXQobGV2ZWwudXBwZXIoKSwgQ19T"
    "SUxWRVIpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4g"
    "c3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsiPlt7dGltZXN0YW1wfV08L3NwYW4+ICcKICAgICAg"
    "ICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnttZXNzYWdlfTwvc3Bhbj4nCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1"
    "ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0o"
    "KQogICAgICAgICkKCiAgICBkZWYgbG9nX21hbnkoc2VsZiwgbWVzc2FnZXM6IGxpc3Rbc3RyXSwg"
    "bGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2Vz"
    "OgogICAgICAgICAgICBsdmwgPSBsZXZlbAogICAgICAgICAgICBpZiAi4pyTIiBpbiBtc2c6ICAg"
    "IGx2bCA9ICJPSyIKICAgICAgICAgICAgZWxpZiAi4pyXIiBpbiBtc2c6ICBsdmwgPSAiV0FSTiIK"
    "ICAgICAgICAgICAgZWxpZiAiRVJST1IiIGluIG1zZy51cHBlcigpOiBsdmwgPSAiRVJST1IiCiAg"
    "ICAgICAgICAgIHNlbGYubG9nKG1zZywgbHZsKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSAIExFU1NPTlMgVEFCIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBM"
    "U0wgRm9yYmlkZGVuIFJ1bGVzZXQgYW5kIGNvZGUgbGVzc29ucyBicm93c2VyLgogICAgQWRkLCB2"
    "aWV3LCBzZWFyY2gsIGRlbGV0ZSBsZXNzb25zLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNl"
    "bGYsIGRiOiAiTGVzc29uc0xlYXJuZWREQiIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kYiA9IGRiCiAgICAgICAgc2VsZi5fc2V0"
    "dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgog"
    "ICAgICAgICMgRmlsdGVyIGJhcgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgc2VsZi5fc2VhcmNoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9zZWFyY2guc2V0"
    "UGxhY2Vob2xkZXJUZXh0KCJTZWFyY2ggbGVzc29ucy4uLiIpCiAgICAgICAgc2VsZi5fbGFuZ19m"
    "aWx0ZXIgPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmFkZEl0ZW1zKFsi"
    "QWxsIiwgIkxTTCIsICJQeXRob24iLCAiUHlTaWRlNiIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAiSmF2YVNjcmlwdCIsICJPdGhlciJdKQogICAgICAgIHNlbGYuX3NlYXJj"
    "aC50ZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBzZWxmLl9sYW5nX2Zp"
    "bHRlci5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZmls"
    "dGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJTZWFyY2g6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5h"
    "ZGRXaWRnZXQoc2VsZi5fc2VhcmNoLCAxKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFM"
    "YWJlbCgiTGFuZ3VhZ2U6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fbGFu"
    "Z19maWx0ZXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgYnRu"
    "X2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fYWRkID0gX2dvdGhpY19idG4oIuKcpiBB"
    "ZGQgTGVzc29uIikKICAgICAgICBidG5fZGVsID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQog"
    "ICAgICAgIGJ0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBidG5f"
    "ZGVsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgYnRuX2Jhci5hZGRX"
    "aWRnZXQoYnRuX2FkZCkKICAgICAgICBidG5fYmFyLmFkZFdpZGdldChidG5fZGVsKQogICAgICAg"
    "IGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikKCiAg"
    "ICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKAogICAgICAgICAgICBbIkxhbmd1YWdlIiwgIlJl"
    "ZmVyZW5jZSBLZXkiLCAiU3VtbWFyeSIsICJFbnZpcm9ubWVudCJdCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAg"
    "ICAgICAgICAgMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmll"
    "dy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFs"
    "dGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVl"
    "dChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlv"
    "bkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgVXNlIHNwbGl0dGVy"
    "IGJldHdlZW4gdGFibGUgYW5kIGRldGFpbAogICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0"
    "Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90"
    "YWJsZSkKCiAgICAgICAgIyBEZXRhaWwgcGFuZWwKICAgICAgICBkZXRhaWxfd2lkZ2V0ID0gUVdp"
    "ZGdldCgpCiAgICAgICAgZGV0YWlsX2xheW91dCA9IFFWQm94TGF5b3V0KGRldGFpbF93aWRnZXQp"
    "CiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAg"
    "ICAgICBkZXRhaWxfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgZGV0YWlsX2hlYWRlciA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBGVUxMIFJVTEUiKSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYuX2J0bl9l"
    "ZGl0X3J1bGUuc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS50"
    "b2dnbGVkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2VkaXRfbW9kZSkKICAgICAgICBzZWxmLl9idG5f"
    "c2F2ZV9ydWxlID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1"
    "bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2li"
    "bGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2F2ZV9ydWxlX2VkaXQpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5f"
    "YnRuX2VkaXRfcnVsZSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5f"
    "c2F2ZV9ydWxlKQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRkTGF5b3V0KGRldGFpbF9oZWFkZXIp"
    "CgogICAgICAgIHNlbGYuX2RldGFpbCA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGV0YWls"
    "LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldE1pbmltdW1IZWlnaHQo"
    "MTIwKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAg"
    "KQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RldGFpbCkKICAgICAgICBz"
    "cGxpdHRlci5hZGRXaWRnZXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXpl"
    "cyhbMzAwLCAxODBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9lZGl0aW5nX3Jv"
    "dzogaW50ID0gLTEKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHEgICAg"
    "PSBzZWxmLl9zZWFyY2gudGV4dCgpCiAgICAgICAgbGFuZyA9IHNlbGYuX2xhbmdfZmlsdGVyLmN1"
    "cnJlbnRUZXh0KCkKICAgICAgICBsYW5nID0gIiIgaWYgbGFuZyA9PSAiQWxsIiBlbHNlIGxhbmcK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzID0gc2VsZi5fZGIuc2VhcmNoKHF1ZXJ5PXEsIGxhbmd1YWdl"
    "PWxhbmcpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoImxhbmd1YWdlIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEs"
    "CiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInJlZmVyZW5jZV9rZXki"
    "LCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAg"
    "ICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3VtbWFyeSIsIiIpKSkKICAgICAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0SXRlbShyLCAzLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJlbnZpcm9ubWVudCIsIiIpKSkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIHNl"
    "bGYuX2VkaXRpbmdfcm93ID0gcm93CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVj"
    "b3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBz"
    "ZWxmLl9kZXRhaWwuc2V0UGxhaW5UZXh0KAogICAgICAgICAgICAgICAgcmVjLmdldCgiZnVsbF9y"
    "dWxlIiwiIikgKyAiXG5cbiIgKwogICAgICAgICAgICAgICAgKCJSZXNvbHV0aW9uOiAiICsgcmVj"
    "LmdldCgicmVzb2x1dGlvbiIsIiIpIGlmIHJlYy5nZXQoInJlc29sdXRpb24iKSBlbHNlICIiKQog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVzZXQgZWRpdCBtb2RlIG9uIG5ldyBzZWxlY3Rp"
    "b24KICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQoKICAg"
    "IGRlZiBfdG9nZ2xlX2VkaXRfbW9kZShzZWxmLCBlZGl0aW5nOiBib29sKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShub3QgZWRpdGluZykKICAgICAgICBzZWxmLl9i"
    "dG5fc2F2ZV9ydWxlLnNldFZpc2libGUoZWRpdGluZykKICAgICAgICBzZWxmLl9idG5fZWRpdF9y"
    "dWxlLnNldFRleHQoIkNhbmNlbCIgaWYgZWRpdGluZyBlbHNlICJFZGl0IikKICAgICAgICBpZiBl"
    "ZGl0aW5nOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTERfRElNfTsgIgogICAgICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBh"
    "ZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxm"
    "Ll9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICMgUmVsb2FkIG9yaWdpbmFsIGNvbnRlbnQgb24gY2FuY2VsCiAgICAgICAg"
    "ICAgIHNlbGYuX29uX3NlbGVjdCgpCgogICAgZGVmIF9zYXZlX3J1bGVfZWRpdChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJvdyA9IHNlbGYuX2VkaXRpbmdfcm93CiAgICAgICAgaWYgMCA8PSByb3cg"
    "PCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHRleHQgPSBzZWxmLl9kZXRhaWwudG9Q"
    "bGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgICMgU3BsaXQgcmVzb2x1dGlvbiBiYWNrIG91"
    "dCBpZiBwcmVzZW50CiAgICAgICAgICAgIGlmICJcblxuUmVzb2x1dGlvbjogIiBpbiB0ZXh0Ogog"
    "ICAgICAgICAgICAgICAgcGFydHMgPSB0ZXh0LnNwbGl0KCJcblxuUmVzb2x1dGlvbjogIiwgMSkK"
    "ICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSBwYXJ0c1swXS5zdHJpcCgpCiAgICAgICAgICAg"
    "ICAgICByZXNvbHV0aW9uID0gcGFydHNbMV0uc3RyaXAoKQogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgZnVsbF9ydWxlICA9IHRleHQKICAgICAgICAgICAgICAgIHJlc29sdXRpb24g"
    "PSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJyZXNvbHV0aW9uIiwgIiIpCiAgICAgICAgICAgIHNl"
    "bGYuX3JlY29yZHNbcm93XVsiZnVsbF9ydWxlIl0gID0gZnVsbF9ydWxlCiAgICAgICAgICAgIHNl"
    "bGYuX3JlY29yZHNbcm93XVsicmVzb2x1dGlvbiJdID0gcmVzb2x1dGlvbgogICAgICAgICAgICB3"
    "cml0ZV9qc29ubChzZWxmLl9kYi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2Vs"
    "Zi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxv"
    "ZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIExlc3NvbiIpCiAgICAgICAg"
    "ZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgNDAwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91"
    "dChkbGcpCiAgICAgICAgZW52ICA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICBsYW5nID0gUUxp"
    "bmVFZGl0KCJMU0wiKQogICAgICAgIHJlZiAgPSBRTGluZUVkaXQoKQogICAgICAgIHN1bW0gPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHJ1bGUgPSBRVGV4dEVkaXQoKQogICAgICAgIHJ1bGUuc2V0TWF4"
    "aW11bUhlaWdodCgxMDApCiAgICAgICAgcmVzICA9IFFMaW5lRWRpdCgpCiAgICAgICAgbGluayA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgZm9yIGxhYmVsLCB3IGluIFsKICAgICAgICAgICAgKCJFbnZp"
    "cm9ubWVudDoiLCBlbnYpLCAoIkxhbmd1YWdlOiIsIGxhbmcpLAogICAgICAgICAgICAoIlJlZmVy"
    "ZW5jZSBLZXk6IiwgcmVmKSwgKCJTdW1tYXJ5OiIsIHN1bW0pLAogICAgICAgICAgICAoIkZ1bGwg"
    "UnVsZToiLCBydWxlKSwgKCJSZXNvbHV0aW9uOiIsIHJlcyksCiAgICAgICAgICAgICgiTGluazoi"
    "LCBsaW5rKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgdykKICAg"
    "ICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUi"
    "KTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3Qo"
    "ZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMu"
    "YWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRu"
    "cykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoK"
    "ICAgICAgICAgICAgc2VsZi5fZGIuYWRkKAogICAgICAgICAgICAgICAgZW52aXJvbm1lbnQ9ZW52"
    "LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGFuZ3VhZ2U9bGFuZy50ZXh0KCkuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgICAgIHJlZmVyZW5jZV9rZXk9cmVmLnRleHQoKS5zdHJpcCgpLAog"
    "ICAgICAgICAgICAgICAgc3VtbWFyeT1zdW1tLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAg"
    "ICAgZnVsbF9ydWxlPXJ1bGUudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAg"
    "cmVzb2x1dGlvbj1yZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBsaW5rPWxpbmsu"
    "dGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3Rh"
    "YmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMp"
    "OgogICAgICAgICAgICByZWNfaWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJpZCIsIiIpCiAg"
    "ICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBz"
    "ZWxmLCAiRGVsZXRlIExlc3NvbiIsCiAgICAgICAgICAgICAgICAiRGVsZXRlIHRoaXMgbGVzc29u"
    "PyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RiLmRlbGV0ZShyZWNfaWQpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIE1PRFVMRSBUUkFDS0VSIFRBQiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kdWxlVHJh"
    "Y2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYWwgbW9kdWxlIHBpcGVsaW5lIHRy"
    "YWNrZXIuCiAgICBUcmFjayBwbGFubmVkL2luLXByb2dyZXNzL2J1aWx0IG1vZHVsZXMgYXMgdGhl"
    "eSBhcmUgZGVzaWduZWQuCiAgICBFYWNoIG1vZHVsZSBoYXM6IE5hbWUsIFN0YXR1cywgRGVzY3Jp"
    "cHRpb24sIE5vdGVzLgogICAgRXhwb3J0IHRvIFRYVCBmb3IgcGFzdGluZyBpbnRvIHNlc3Npb25z"
    "LgogICAgSW1wb3J0OiBwYXN0ZSBhIGZpbmFsaXplZCBzcGVjLCBpdCBwYXJzZXMgbmFtZSBhbmQg"
    "ZGV0YWlscy4KICAgIFRoaXMgaXMgYSBkZXNpZ24gbm90ZWJvb2sg4oCUIG5vdCBjb25uZWN0ZWQg"
    "dG8gZGVja19idWlsZGVyJ3MgTU9EVUxFIHJlZ2lzdHJ5LgogICAgIiIiCgogICAgU1RBVFVTRVMg"
    "PSBbIklkZWEiLCAiRGVzaWduaW5nIiwgIlJlYWR5IHRvIEJ1aWxkIiwgIlBhcnRpYWwiLCAiQnVp"
    "bHQiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmll"
    "cyIpIC8gIm1vZHVsZV90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hM"
    "YXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBi"
    "dG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGlj"
    "X2J0bigiQWRkIE1vZHVsZSIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQgICA9IF9nb3RoaWNfYnRu"
    "KCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNfYnRuKCJFeHBvcnQgVFhUIikKICAg"
    "ICAgICBzZWxmLl9idG5faW1wb3J0ID0gX2dvdGhpY19idG4oIkltcG9ydCBTcGVjIikKICAgICAg"
    "ICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2VkaXQsIHNlbGYuX2J0bl9kZWxl"
    "dGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9leHBvcnQsIHNlbGYuX2J0bl9pbXBvcnQp"
    "OgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0aCg4MCkKICAgICAgICAgICAgYi5zZXRNaW5p"
    "bXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBidG5fYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJ0"
    "bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikKCiAgICAg"
    "ICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNl"
    "bGYuX2J0bl9lZGl0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19lZGl0KQogICAgICAgIHNlbGYu"
    "X2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxm"
    "Ll9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2ltcG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faW1wb3J0KQoKICAgICAgICAj"
    "IFRhYmxlCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMykKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiTW9kdWxlIE5hbWUiLCAiU3Rh"
    "dHVzIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFs"
    "SGVhZGVyKCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDAsIDE2"
    "MCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDEsIDEwMCkKICAg"
    "ICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0"
    "cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAg"
    "ICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAg"
    "ICAgICAgIyBTcGxpdHRlcgogICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0"
    "aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAg"
    "ICAgICAgIyBOb3RlcyBwYW5lbAogICAgICAgIG5vdGVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAg"
    "ICAgIG5vdGVzX2xheW91dCA9IFFWQm94TGF5b3V0KG5vdGVzX3dpZGdldCkKICAgICAgICBub3Rl"
    "c19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgbm90ZXNfbGF5"
    "b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIE5PVEVTIikpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheSA9IFFUZXh0RWRp"
    "dCgpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAg"
    "IHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5f"
    "bm90ZXNfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgKQogICAgICAgIG5v"
    "dGVzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbm90ZXNfZGlzcGxheSkKICAgICAgICBzcGxpdHRl"
    "ci5hZGRXaWRnZXQobm90ZXNfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFsyNTAs"
    "IDE1MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgICMgQ291"
    "bnQgbGFiZWwKICAgICAgICBzZWxmLl9jb3VudF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2Vs"
    "Zi5fY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRf"
    "RElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7Igog"
    "ICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb3VudF9sYmwpCgogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29u"
    "bChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAg"
    "Zm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93"
    "Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoIm5hbWUi"
    "LCAiIikpKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdl"
    "dCgic3RhdHVzIiwgIklkZWEiKSkKICAgICAgICAgICAgIyBDb2xvciBieSBzdGF0dXMKICAgICAg"
    "ICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgICAgICJJZGVhIjogICAgICAgICAg"
    "ICAgQ19URVhUX0RJTSwKICAgICAgICAgICAgICAgICJEZXNpZ25pbmciOiAgICAgICAgQ19HT0xE"
    "X0RJTSwKICAgICAgICAgICAgICAgICJSZWFkeSB0byBCdWlsZCI6ICAgQ19QVVJQTEUsCiAgICAg"
    "ICAgICAgICAgICAiUGFydGlhbCI6ICAgICAgICAgICIjY2M4ODQ0IiwKICAgICAgICAgICAgICAg"
    "ICJCdWlsdCI6ICAgICAgICAgICAgQ19HUkVFTiwKICAgICAgICAgICAgfQogICAgICAgICAgICBz"
    "dGF0dXNfaXRlbS5zZXRGb3JlZ3JvdW5kKAogICAgICAgICAgICAgICAgUUNvbG9yKHN0YXR1c19j"
    "b2xvcnMuZ2V0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSwgQ19URVhUX0RJTSkpCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLCBzdGF0dXNfaXRlbSkK"
    "ICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRh"
    "YmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsICIiKVs6ODBdKSkKICAgICAgICBj"
    "b3VudHMgPSB7fQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAg"
    "cyA9IHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikKICAgICAgICAgICAgY291bnRzW3NdID0gY291"
    "bnRzLmdldChzLCAwKSArIDEKICAgICAgICBjb3VudF9zdHIgPSAiICAiLmpvaW4oZiJ7c306IHtu"
    "fSIgZm9yIHMsIG4gaW4gY291bnRzLml0ZW1zKCkpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNl"
    "dFRleHQoCiAgICAgICAgICAgIGYiVG90YWw6IHtsZW4oc2VsZi5fcmVjb3Jkcyl9ICAge2NvdW50"
    "X3N0cn0iCiAgICAgICAgKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBs"
    "ZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQog"
    "ICAgICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3Rl"
    "cyIsICIiKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX29w"
    "ZW5fZWRpdF9kaWFsb2coKQoKICAgIGRlZiBfZG9fZWRpdChzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVu"
    "KHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKHNlbGYu"
    "X3JlY29yZHNbcm93XSwgcm93KQoKICAgIGRlZiBfb3Blbl9lZGl0X2RpYWxvZyhzZWxmLCByZWM6"
    "IGRpY3QgPSBOb25lLCByb3c6IGludCA9IC0xKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFs"
    "b2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZHVsZSIgaWYgbm90IHJlYyBl"
    "bHNlIGYiRWRpdDoge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIGRsZy5zZXRTdHlsZVNo"
    "ZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxn"
    "LnJlc2l6ZSg1NDAsIDQ0MCkKICAgICAgICBmb3JtID0gUVZCb3hMYXlvdXQoZGxnKQoKICAgICAg"
    "ICBuYW1lX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5hbWUiLCIiKSBpZiByZWMgZWxzZSAi"
    "IikKICAgICAgICBuYW1lX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiTW9kdWxlIG5hbWUiKQoK"
    "ICAgICAgICBzdGF0dXNfY29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHN0YXR1c19jb21iby5h"
    "ZGRJdGVtcyhzZWxmLlNUQVRVU0VTKQogICAgICAgIGlmIHJlYzoKICAgICAgICAgICAgaWR4ID0g"
    "c3RhdHVzX2NvbWJvLmZpbmRUZXh0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSkKICAgICAgICAg"
    "ICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzdGF0dXNfY29tYm8uc2V0Q3VycmVudElu"
    "ZGV4KGlkeCkKCiAgICAgICAgZGVzY19maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlw"
    "dGlvbiIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRlc2NfZmllbGQuc2V0UGxhY2Vob2xk"
    "ZXJUZXh0KCJPbmUtbGluZSBkZXNjcmlwdGlvbiIpCgogICAgICAgIG5vdGVzX2ZpZWxkID0gUVRl"
    "eHRFZGl0KCkKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMi"
    "LCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFjZWhvbGRlclRl"
    "eHQoCiAgICAgICAgICAgICJGdWxsIG5vdGVzIOKAlCBzcGVjLCBpZGVhcywgcmVxdWlyZW1lbnRz"
    "LCBlZGdlIGNhc2VzLi4uIgogICAgICAgICkKICAgICAgICBub3Rlc19maWVsZC5zZXRNaW5pbXVt"
    "SGVpZ2h0KDIwMCkKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAo"
    "Ik5hbWU6IiwgbmFtZV9maWVsZCksCiAgICAgICAgICAgICgiU3RhdHVzOiIsIHN0YXR1c19jb21i"
    "byksCiAgICAgICAgICAgICgiRGVzY3JpcHRpb246IiwgZGVzY19maWVsZCksCiAgICAgICAgICAg"
    "ICgiTm90ZXM6Iiwgbm90ZXNfZmllbGQpLAogICAgICAgIF06CiAgICAgICAgICAgIHJvd19sYXlv"
    "dXQgPSBRSEJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChsYWJlbCkKICAgICAg"
    "ICAgICAgbGJsLnNldEZpeGVkV2lkdGgoOTApCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lk"
    "Z2V0KGxibCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAg"
    "ICAgICBmb3JtLmFkZExheW91dChyb3dfbGF5b3V0KQoKICAgICAgICBidG5fcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGJ0bl9zYXZlICAgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAg"
    "YnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNr"
    "ZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0"
    "KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAg"
    "YnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBmb3JtLmFkZExheW91dChidG5f"
    "cm93KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRl"
    "ZDoKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "IHJlYy5nZXQoImlkIiwgc3RyKHV1aWQudXVpZDQoKSkpIGlmIHJlYyBlbHNlIHN0cih1dWlkLnV1"
    "aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZV9maWVsZC50ZXh0KCku"
    "c3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgIHN0YXR1c19jb21iby5jdXJy"
    "ZW50VGV4dCgpLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzY19maWVsZC50ZXh0"
    "KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgIG5vdGVzX2ZpZWxkLnRv"
    "UGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJjcmVhdGVkIjogICAgIHJlYy5n"
    "ZXQoImNyZWF0ZWQiLCBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSkgaWYgcmVjIGVsc2UgZGF0"
    "ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBk"
    "YXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiBy"
    "b3cgPj0gMDoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XSA9IG5ld19yZWMKICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19y"
    "ZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9"
    "IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgbmFtZSA9IHNlbGYuX3JlY29y"
    "ZHNbcm93XS5nZXQoIm5hbWUiLCJ0aGlzIG1vZHVsZSIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1l"
    "c3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRGVsZXRlIE1vZHVsZSIs"
    "CiAgICAgICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gQ2Fubm90IGJlIHVuZG9uZS4iLAog"
    "ICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VC"
    "b3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9"
    "PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZXhwb3J0X2Rp"
    "ciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJl"
    "bnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCku"
    "c3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9k"
    "aXIgLyBmIm1vZHVsZXNfe3RzfS50eHQiCiAgICAgICAgICAgIGxpbmVzID0gWwogICAgICAgICAg"
    "ICAgICAgIkVDSE8gREVDSyDigJQgTU9EVUxFIFRSQUNLRVIgRVhQT1JUIiwKICAgICAgICAgICAg"
    "ICAgIGYiRXhwb3J0ZWQ6IHtkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVktJW0tJWQgJUg6JU06"
    "JVMnKX0iLAogICAgICAgICAgICAgICAgZiJUb3RhbCBtb2R1bGVzOiB7bGVuKHNlbGYuX3JlY29y"
    "ZHMpfSIsCiAgICAgICAgICAgICAgICAiPSIgKiA2MCwKICAgICAgICAgICAgICAgICIiLAogICAg"
    "ICAgICAgICBdCiAgICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAg"
    "ICAgICAgIGxpbmVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICAgICAgZiJNT0RVTEU6IHtyZWMu"
    "Z2V0KCduYW1lJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIlN0YXR1czoge3JlYy5nZXQo"
    "J3N0YXR1cycsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJEZXNjcmlwdGlvbjoge3JlYy5n"
    "ZXQoJ2Rlc2NyaXB0aW9uJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAg"
    "ICAgICAgICAgICAiTm90ZXM6IiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIs"
    "IiIpLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgICAgICItIiAqIDQw"
    "LAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgXSkKICAgICAgICAgICAg"
    "b3V0X3BhdGgud3JpdGVfdGV4dCgiXG4iLmpvaW4obGluZXMpLCBlbmNvZGluZz0idXRmLTgiKQog"
    "ICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4dCgiXG4iLmpvaW4obGlu"
    "ZXMpKQogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgICAg"
    "IHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICBmIk1vZHVsZSB0cmFja2VyIGV4cG9y"
    "dGVkIHRvOlxue291dF9wYXRofVxuXG5BbHNvIGNvcGllZCB0byBjbGlwYm9hcmQuIgogICAgICAg"
    "ICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC53YXJuaW5nKHNlbGYsICJFeHBvcnQgRXJyb3IiLCBzdHIoZSkpCgogICAgZGVmIF9kb19p"
    "bXBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJJbXBvcnQgYSBtb2R1bGUgc3BlYyBmcm9t"
    "IGNsaXBib2FyZCBvciB0eXBlZCB0ZXh0LiIiIgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikK"
    "ICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkltcG9ydCBNb2R1bGUgU3BlYyIpCiAgICAgICAg"
    "ZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzQwKQogICAgICAgIGxheW91dCA9IFFWQm94TGF5"
    "b3V0KGRsZykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgKICAgICAgICAgICAgIlBh"
    "c3RlIGEgbW9kdWxlIHNwZWMgYmVsb3cuXG4iCiAgICAgICAgICAgICJGaXJzdCBsaW5lIHdpbGwg"
    "YmUgdXNlZCBhcyB0aGUgbW9kdWxlIG5hbWUuIgogICAgICAgICkpCiAgICAgICAgdGV4dF9maWVs"
    "ZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgdGV4dF9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIlBh"
    "c3RlIG1vZHVsZSBzcGVjIGhlcmUuLi4iKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGV4dF9m"
    "aWVsZCwgMSkKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9vayAg"
    "ICAgPSBfZ290aGljX2J0bigiSW1wb3J0IikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19i"
    "dG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX29rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQog"
    "ICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRu"
    "X3Jvdy5hZGRXaWRnZXQoYnRuX29rKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5j"
    "ZWwpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAgICAgICBpZiBkbGcuZXhl"
    "YygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmF3ID0gdGV4"
    "dF9maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IHJhdzoKICAg"
    "ICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICBsaW5lcyA9IHJhdy5zcGxpdGxpbmVzKCkK"
    "ICAgICAgICAgICAgIyBGaXJzdCBub24tZW1wdHkgbGluZSA9IG5hbWUKICAgICAgICAgICAgbmFt"
    "ZSA9ICIiCiAgICAgICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAgICAgaWYg"
    "bGluZS5zdHJpcCgpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBsaW5lLnN0cmlwKCkKICAg"
    "ICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAg"
    "ICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAi"
    "bmFtZSI6ICAgICAgICBuYW1lWzo2MF0sCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAi"
    "SWRlYSIsCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiIiwKICAgICAgICAgICAgICAg"
    "ICJub3RlcyI6ICAgICAgIHJhdywKICAgICAgICAgICAgICAgICJjcmVhdGVkIjogICAgIGRhdGV0"
    "aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0"
    "ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0"
    "aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBQ"
    "QVNTIDUgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHRhYiBjb250ZW50IGNsYXNzZXMgZGVmaW5l"
    "ZC4KIyBTTFNjYW5zVGFiOiByZWJ1aWx0IOKAlCBEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwg"
    "dGltZXN0YW1wIHBhcnNlciBmaXhlZCwKIyAgICAgICAgICAgICBjYXJkL2dyaW1vaXJlIHN0eWxl"
    "LCBjb3B5LXRvLWNsaXBib2FyZCBjb250ZXh0IG1lbnUuCiMgU0xDb21tYW5kc1RhYjogZ290aGlj"
    "IHRhYmxlLCDip4kgQ29weSBDb21tYW5kIGJ1dHRvbi4KIyBKb2JUcmFja2VyVGFiOiBmdWxsIHJl"
    "YnVpbGQg4oCUIG11bHRpLXNlbGVjdCwgYXJjaGl2ZS9yZXN0b3JlLCBDU1YvVFNWIGV4cG9ydC4K"
    "IyBTZWxmVGFiOiBpbm5lciBzYW5jdHVtIGZvciBpZGxlIG5hcnJhdGl2ZSBhbmQgcmVmbGVjdGlv"
    "biBvdXRwdXQuCiMgRGlhZ25vc3RpY3NUYWI6IHN0cnVjdHVyZWQgbG9nIHdpdGggbGV2ZWwtY29s"
    "b3JlZCBvdXRwdXQuCiMgTGVzc29uc1RhYjogTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGJyb3dzZXIg"
    "d2l0aCBhZGQvZGVsZXRlL3NlYXJjaC4KIwojIE5leHQ6IFBhc3MgNiDigJQgTWFpbiBXaW5kb3cK"
    "IyAoTW9yZ2FubmFEZWNrIGNsYXNzLCBmdWxsIGxheW91dCwgQVBTY2hlZHVsZXIsIGZpcnN0LXJ1"
    "biBmbG93LAojICBkZXBlbmRlbmN5IGJvb3RzdHJhcCwgc2hvcnRjdXQgY3JlYXRpb24sIHN0YXJ0"
    "dXAgc2VxdWVuY2UpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDY6IE1B"
    "SU4gV0lORE9XICYgRU5UUlkgUE9JTlQKIwojIENvbnRhaW5zOgojICAgYm9vdHN0cmFwX2NoZWNr"
    "KCkgICAgIOKAlCBkZXBlbmRlbmN5IHZhbGlkYXRpb24gKyBhdXRvLWluc3RhbGwgYmVmb3JlIFVJ"
    "CiMgICBGaXJzdFJ1bkRpYWxvZyAgICAgICAg4oCUIG1vZGVsIHBhdGggKyBjb25uZWN0aW9uIHR5"
    "cGUgc2VsZWN0aW9uCiMgICBKb3VybmFsU2lkZWJhciAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGxl"
    "ZnQgc2lkZWJhciAoc2Vzc2lvbiBicm93c2VyICsgam91cm5hbCkKIyAgIFRvcnBvclBhbmVsICAg"
    "ICAgICAgICDigJQgQVdBS0UgLyBBVVRPIC8gU1VTUEVORCBzdGF0ZSB0b2dnbGUKIyAgIE1vcmdh"
    "bm5hRGVjayAgICAgICAgICDigJQgbWFpbiB3aW5kb3csIGZ1bGwgbGF5b3V0LCBhbGwgc2lnbmFs"
    "IGNvbm5lY3Rpb25zCiMgICBtYWluKCkgICAgICAgICAgICAgICAg4oCUIGVudHJ5IHBvaW50IHdp"
    "dGggYm9vdHN0cmFwIHNlcXVlbmNlCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgc3VicHJvY2VzcwoKCiMg"
    "4pSA4pSAIFBSRS1MQVVOQ0ggREVQRU5ERU5DWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBi"
    "b290c3RyYXBfY2hlY2soKSAtPiBOb25lOgogICAgIiIiCiAgICBSdW5zIEJFRk9SRSBRQXBwbGlj"
    "YXRpb24gaXMgY3JlYXRlZC4KICAgIENoZWNrcyBmb3IgUHlTaWRlNiBzZXBhcmF0ZWx5IChjYW4n"
    "dCBzaG93IEdVSSB3aXRob3V0IGl0KS4KICAgIEF1dG8taW5zdGFsbHMgYWxsIG90aGVyIG1pc3Np"
    "bmcgbm9uLWNyaXRpY2FsIGRlcHMgdmlhIHBpcC4KICAgIFZhbGlkYXRlcyBpbnN0YWxscyBzdWNj"
    "ZWVkZWQuCiAgICBXcml0ZXMgcmVzdWx0cyB0byBhIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0"
    "aWNzIHRhYiB0byBwaWNrIHVwLgogICAgIiIiCiAgICAjIOKUgOKUgCBTdGVwIDE6IENoZWNrIFB5"
    "U2lkZTYgKGNhbid0IGF1dG8taW5zdGFsbCB3aXRob3V0IGl0IGFscmVhZHkgcHJlc2VudCkg4pSA"
    "CiAgICB0cnk6CiAgICAgICAgaW1wb3J0IFB5U2lkZTYgICMgbm9xYQogICAgZXhjZXB0IEltcG9y"
    "dEVycm9yOgogICAgICAgICMgTm8gR1VJIGF2YWlsYWJsZSDigJQgdXNlIFdpbmRvd3MgbmF0aXZl"
    "IGRpYWxvZyB2aWEgY3R5cGVzCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnQgY3R5cGVz"
    "CiAgICAgICAgICAgIGN0eXBlcy53aW5kbGwudXNlcjMyLk1lc3NhZ2VCb3hXKAogICAgICAgICAg"
    "ICAgICAgMCwKICAgICAgICAgICAgICAgICJQeVNpZGU2IGlzIHJlcXVpcmVkIGJ1dCBub3QgaW5z"
    "dGFsbGVkLlxuXG4iCiAgICAgICAgICAgICAgICAiT3BlbiBhIHRlcm1pbmFsIGFuZCBydW46XG5c"
    "biIKICAgICAgICAgICAgICAgICIgICAgcGlwIGluc3RhbGwgUHlTaWRlNlxuXG4iCiAgICAgICAg"
    "ICAgICAgICBmIlRoZW4gcmVzdGFydCB7REVDS19OQU1FfS4iLAogICAgICAgICAgICAgICAgZiJ7"
    "REVDS19OQU1FfSDigJQgTWlzc2luZyBEZXBlbmRlbmN5IiwKICAgICAgICAgICAgICAgIDB4MTAg"
    "ICMgTUJfSUNPTkVSUk9SCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICBwcmludCgiQ1JJVElDQUw6IFB5U2lkZTYgbm90IGluc3RhbGxlZC4gUnVuOiBw"
    "aXAgaW5zdGFsbCBQeVNpZGU2IikKICAgICAgICBzeXMuZXhpdCgxKQoKICAgICMg4pSA4pSAIFN0"
    "ZXAgMjogQXV0by1pbnN0YWxsIG90aGVyIG1pc3NpbmcgZGVwcyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIF9BVVRPX0lOU1RBTEwgPSBbCiAgICAgICAgKCJhcHNj"
    "aGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJsb2d1cnUi"
    "LCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAg"
    "ICAgICAgICAgICAgICJweWdhbWUiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAg"
    "ICAgICAicHl3aW4zMiIpLAogICAgICAgICgicHN1dGlsIiwgICAgICAgICAgICAgICAgICAgICJw"
    "c3V0aWwiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAgICAgICAgICAgICAicmVxdWVzdHMi"
    "KSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBpY2xpZW50"
    "IiksCiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29h"
    "dXRobGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5h"
    "dXRoIiksCiAgICBdCgogICAgaW1wb3J0IGltcG9ydGxpYgogICAgYm9vdHN0cmFwX2xvZyA9IFtd"
    "CgogICAgZm9yIHBpcF9uYW1lLCBpbXBvcnRfbmFtZSBpbiBfQVVUT19JTlNUQUxMOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAg"
    "ICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSDi"
    "nJMiKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgYm9vdHN0cmFwX2xv"
    "Zy5hcHBlbmQoCiAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gbWlzc2lu"
    "ZyDigJQgaW5zdGFsbGluZy4uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICByZXN1bHQgPSBzdWJwcm9jZXNzLnJ1bigKICAgICAgICAgICAgICAgICAgICBb"
    "c3lzLmV4ZWN1dGFibGUsICItbSIsICJwaXAiLCAiaW5zdGFsbCIsCiAgICAgICAgICAgICAgICAg"
    "ICAgIHBpcF9uYW1lLCAiLS1xdWlldCIsICItLW5vLXdhcm4tc2NyaXB0LWxvY2F0aW9uIl0sCiAg"
    "ICAgICAgICAgICAgICAgICAgY2FwdHVyZV9vdXRwdXQ9VHJ1ZSwgdGV4dD1UcnVlLCB0aW1lb3V0"
    "PTEyMAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgcmVzdWx0LnJldHVybmNv"
    "ZGUgPT0gMDoKICAgICAgICAgICAgICAgICAgICAjIFZhbGlkYXRlIGl0IGFjdHVhbGx5IGltcG9y"
    "dGVkIG5vdwogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "aW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJb"
    "Qk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGxlZCDinJMiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgYXBwZWFyZWQgdG8gIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJzdWNjZWVkIGJ1dCBpbXBvcnQgc3RpbGwgZmFpbHMg"
    "4oCUIHJlc3RhcnQgbWF5ICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiYmUgcmVxdWly"
    "ZWQuIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAg"
    "ICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBmYWlsZWQ6ICIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZiJ7cmVzdWx0LnN0ZGVycls6MjAwXX0iCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBleGNlcHQgc3VicHJvY2Vzcy5UaW1lb3V0RXhwaXJlZDoKICAgICAg"
    "ICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0JP"
    "T1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIHRpbWVkIG91dC4iCiAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIGJvb3Rz"
    "dHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9u"
    "YW1lfSBpbnN0YWxsIGVycm9yOiB7ZX0iCiAgICAgICAgICAgICAgICApCgogICAgIyDilIDilIAg"
    "U3RlcCAzOiBXcml0ZSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICB0cnk6CiAgICAgICAgbG9nX3BhdGggPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJv"
    "b3RzdHJhcF9sb2cudHh0IgogICAgICAgIHdpdGggbG9nX3BhdGgub3BlbigidyIsIGVuY29kaW5n"
    "PSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoIlxuIi5qb2luKGJvb3RzdHJhcF9s"
    "b2cpKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgoKIyDilIDilIAgRklSU1Qg"
    "UlVOIERJQUxPRyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgRmlyc3RSdW5EaWFsb2coUURpYWxvZyk6CiAgICAiIiIKICAg"
    "IFNob3duIG9uIGZpcnN0IGxhdW5jaCB3aGVuIGNvbmZpZy5qc29uIGRvZXNuJ3QgZXhpc3QuCiAg"
    "ICBDb2xsZWN0cyBtb2RlbCBjb25uZWN0aW9uIHR5cGUgYW5kIHBhdGgva2V5LgogICAgVmFsaWRh"
    "dGVzIGNvbm5lY3Rpb24gYmVmb3JlIGFjY2VwdGluZy4KICAgIFdyaXRlcyBjb25maWcuanNvbiBv"
    "biBzdWNjZXNzLgogICAgQ3JlYXRlcyBkZXNrdG9wIHNob3J0Y3V0LgogICAgIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKGYi4pymIHtERUNLX05BTUUudXBwZXIo"
    "KX0g4oCUIEZJUlNUIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxF"
    "KQogICAgICAgIHNlbGYuc2V0Rml4ZWRTaXplKDUyMCwgNDAwKQogICAgICAgIHNlbGYuX3NldHVw"
    "X3VpKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFW"
    "Qm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDEwKQoKICAgICAgICB0aXRs"
    "ZSA9IFFMYWJlbChmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkcg"
    "4pymIikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19DUklNU09OfTsgZm9udC1zaXplOiAxNHB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAy"
    "cHg7IgogICAgICAgICkKICAgICAgICB0aXRsZS5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50Rmxh"
    "Zy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldCh0aXRsZSkKCiAgICAgICAgc3Vi"
    "ID0gUUxhYmVsKAogICAgICAgICAgICBmIkNvbmZpZ3VyZSB0aGUgdmVzc2VsIGJlZm9yZSB7REVD"
    "S19OQU1FfSBtYXkgYXdha2VuLlxuIgogICAgICAgICAgICAiQWxsIHNldHRpbmdzIGFyZSBzdG9y"
    "ZWQgbG9jYWxseS4gTm90aGluZyBsZWF2ZXMgdGhpcyBtYWNoaW5lLiIKICAgICAgICApCiAgICAg"
    "ICAgc3ViLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsg"
    "Zm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChzdWIpCgogICAgICAgICMg"
    "4pSA4pSAIENvbm5lY3Rpb24gdHlwZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFk"
    "ZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBBSSBDT05ORUNUSU9OIFRZUEUiKSkKICAgICAgICBz"
    "ZWxmLl90eXBlX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmFk"
    "ZEl0ZW1zKFsKICAgICAgICAgICAgIkxvY2FsIG1vZGVsIGZvbGRlciAodHJhbnNmb3JtZXJzKSIs"
    "CiAgICAgICAgICAgICJPbGxhbWEgKGxvY2FsIHNlcnZpY2UpIiwKICAgICAgICAgICAgIkNsYXVk"
    "ZSBBUEkgKEFudGhyb3BpYykiLAogICAgICAgICAgICAiT3BlbkFJIEFQSSIsCiAgICAgICAgXSkK"
    "ICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9vbl90eXBlX2NoYW5nZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90eXBlX2NvbWJv"
    "KQoKICAgICAgICAjIOKUgOKUgCBEeW5hbWljIGNvbm5lY3Rpb24gZmllbGRzIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YWNrID0g"
    "UVN0YWNrZWRXaWRnZXQoKQoKICAgICAgICAjIFBhZ2UgMDogTG9jYWwgcGF0aAogICAgICAgIHAw"
    "ID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRSEJveExheW91dChwMCkKICAgICAgICBsMC5zZXRD"
    "b250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoID0gUUxpbmVF"
    "ZGl0KCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAg"
    "ICAgICAgciJEOlxBSVxNb2RlbHNcZG9scGhpbi04YiIKICAgICAgICApCiAgICAgICAgYnRuX2Jy"
    "b3dzZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9icm93c2UuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2Jyb3dzZV9tb2RlbCkKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fbG9j"
    "YWxfcGF0aCk7IGwwLmFkZFdpZGdldChidG5fYnJvd3NlKQogICAgICAgIHNlbGYuX3N0YWNrLmFk"
    "ZFdpZGdldChwMCkKCiAgICAgICAgIyBQYWdlIDE6IE9sbGFtYSBtb2RlbCBuYW1lCiAgICAgICAg"
    "cDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9IFFIQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbCA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVsLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "ZG9scGhpbi0yLjYtN2IiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9vbGxhbWFfbW9kZWwp"
    "CiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIFBhZ2UgMjogQ2xh"
    "dWRlIEFQSSBrZXkKICAgICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlv"
    "dXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2Vs"
    "Zi5fY2xhdWRlX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNl"
    "dFBsYWNlaG9sZGVyVGV4dCgic2stYW50LS4uLiIpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5z"
    "ZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fY2xh"
    "dWRlX21vZGVsID0gUUxpbmVFZGl0KCJjbGF1ZGUtc29ubmV0LTQtNiIpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xh"
    "dWRlX2tleSkKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBs"
    "Mi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdp"
    "ZGdldChwMikKCiAgICAgICAgIyBQYWdlIDM6IE9wZW5BSQogICAgICAgIHAzID0gUVdpZGdldCgp"
    "CiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01hcmdp"
    "bnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vYWlfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAg"
    "IHNlbGYuX29haV9rZXkuc2V0UGxhY2Vob2xkZXJUZXh0KCJzay0uLi4iKQogICAgICAgIHNlbGYu"
    "X29haV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAg"
    "IHNlbGYuX29haV9tb2RlbCA9IFFMaW5lRWRpdCgiZ3B0LTRvIikKICAgICAgICBsMy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJBUEkgS2V5OiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfa2V5"
    "KQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAgIGwzLmFkZFdp"
    "ZGdldChzZWxmLl9vYWlfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaykKCiAgICAgICAgIyDilIDilIAgVGVz"
    "dCArIHN0YXR1cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICB0ZXN0X3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fdGVzdCA9IF9nb3RoaWNfYnRuKCJUZXN0IENv"
    "bm5lY3Rpb24iKQogICAgICAgIHNlbGYuX2J0bl90ZXN0LmNsaWNrZWQuY29ubmVjdChzZWxmLl90"
    "ZXN0X2Nvbm5lY3Rpb24pCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibCA9IFFMYWJlbCgiIikKICAg"
    "ICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHRlc3Rfcm93LmFkZFdp"
    "ZGdldChzZWxmLl9idG5fdGVzdCkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc3Rh"
    "dHVzX2xibCwgMSkKICAgICAgICByb290LmFkZExheW91dCh0ZXN0X3JvdykKCiAgICAgICAgIyDi"
    "lIDilIAgRmFjZSBQYWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZBQ0UgUEFDSyAob3B0aW9uYWwg"
    "4oCUIFpJUCBmaWxlKSIpKQogICAgICAgIGZhY2Vfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "IHNlbGYuX2ZhY2VfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNl"
    "dFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgZiJCcm93c2UgdG8ge0RFQ0tfTkFNRX0gZmFj"
    "ZSBwYWNrIFpJUCAob3B0aW9uYWwsIGNhbiBhZGQgbGF0ZXIpIgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9mYWNlX3BhdGguc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA2"
    "cHggMTBweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9mYWNlID0gX2dvdGhpY19idG4oIkJyb3dz"
    "ZSIpCiAgICAgICAgYnRuX2ZhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9mYWNlKQog"
    "ICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChzZWxmLl9mYWNlX3BhdGgpCiAgICAgICAgZmFjZV9y"
    "b3cuYWRkV2lkZ2V0KGJ0bl9mYWNlKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZhY2Vfcm93KQoK"
    "ICAgICAgICAjIOKUgOKUgCBTaG9ydGN1dCBvcHRpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fc2hvcnRjdXRfY2IgPSBRQ2hlY2tCb3goCiAgICAgICAgICAgICJDcmVhdGUgZGVz"
    "a3RvcCBzaG9ydGN1dCAocmVjb21tZW5kZWQpIgogICAgICAgICkKICAgICAgICBzZWxmLl9zaG9y"
    "dGN1dF9jYi5zZXRDaGVja2VkKFRydWUpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc2hv"
    "cnRjdXRfY2IpCgogICAgICAgICMg4pSA4pSAIEJ1dHRvbnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRTdHJldGNoKCkKICAgICAgICBi"
    "dG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4gPSBfZ290aGlj"
    "X2J0bigi4pymIEJFR0lOIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRF"
    "bmFibGVkKEZhbHNlKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigi4pyXIENhbmNl"
    "bCIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5hY2NlcHQp"
    "CiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWplY3QpCiAgICAgICAg"
    "YnRuX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2F3YWtlbikKICAgICAgICBidG5fcm93LmFkZFdp"
    "ZGdldChidG5fY2FuY2VsKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgZGVm"
    "IF9vbl90eXBlX2NoYW5nZShzZWxmLCBpZHg6IGludCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9z"
    "dGFjay5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5h"
    "YmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQoIiIpCgogICAgZGVm"
    "IF9icm93c2VfbW9kZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoID0gUUZpbGVEaWFsb2cu"
    "Z2V0RXhpc3RpbmdEaXJlY3RvcnkoCiAgICAgICAgICAgIHNlbGYsICJTZWxlY3QgTW9kZWwgRm9s"
    "ZGVyIiwKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHMiCiAgICAgICAgKQogICAgICAgIGlmIHBh"
    "dGg6CiAgICAgICAgICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIGRlZiBf"
    "YnJvd3NlX2ZhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoLCBfID0gUUZpbGVEaWFsb2cu"
    "Z2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IEZhY2UgUGFjayBaSVAi"
    "LAogICAgICAgICAgICBzdHIoUGF0aC5ob21lKCkgLyAiRGVza3RvcCIpLAogICAgICAgICAgICAi"
    "WklQIEZpbGVzICgqLnppcCkiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAg"
    "IHNlbGYuX2ZhY2VfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAgQHByb3BlcnR5CiAgICBkZWYgZmFj"
    "ZV96aXBfcGF0aChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2ZhY2VfcGF0aC50"
    "ZXh0KCkuc3RyaXAoKQoKICAgIGRlZiBfdGVzdF9jb25uZWN0aW9uKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCJUZXN0aW5nLi4uIikKICAgICAgICBzZWxm"
    "Ll9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRf"
    "RElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIK"
    "ICAgICAgICApCiAgICAgICAgUUFwcGxpY2F0aW9uLnByb2Nlc3NFdmVudHMoKQoKICAgICAgICBp"
    "ZHggPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgb2sgID0gRmFsc2UK"
    "ICAgICAgICBtc2cgPSAiIgoKICAgICAgICBpZiBpZHggPT0gMDogICMgTG9jYWwKICAgICAgICAg"
    "ICAgcGF0aCA9IHNlbGYuX2xvY2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgaWYg"
    "cGF0aCBhbmQgUGF0aChwYXRoKS5leGlzdHMoKToKICAgICAgICAgICAgICAgIG9rICA9IFRydWUK"
    "ICAgICAgICAgICAgICAgIG1zZyA9IGYiRm9sZGVyIGZvdW5kLiBNb2RlbCB3aWxsIGxvYWQgb24g"
    "c3RhcnR1cC4iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBtc2cgPSAiRm9sZGVy"
    "IG5vdCBmb3VuZC4gQ2hlY2sgdGhlIHBhdGguIgoKICAgICAgICBlbGlmIGlkeCA9PSAxOiAgIyBP"
    "bGxhbWEKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1"
    "ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICAgICAgImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQv"
    "YXBpL3RhZ3MiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXNwID0gdXJsbGli"
    "LnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MykKICAgICAgICAgICAgICAgIG9rICAgPSBy"
    "ZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICAgICAgICAgIG1zZyAgPSAiT2xsYW1hIGlzIHJ1bm5p"
    "bmcg4pyTIiBpZiBvayBlbHNlICJPbGxhbWEgbm90IHJlc3BvbmRpbmcuIgogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBtc2cgPSBmIk9sbGFtYSBub3Qg"
    "cmVhY2hhYmxlOiB7ZX0iCgogICAgICAgIGVsaWYgaWR4ID09IDI6ICAjIENsYXVkZQogICAgICAg"
    "ICAgICBrZXkgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIG9r"
    "ICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stYW50IikpCiAgICAgICAgICAgIG1z"
    "ZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2"
    "YWxpZCBDbGF1ZGUgQVBJIGtleS4iCgogICAgICAgIGVsaWYgaWR4ID09IDM6ICAjIE9wZW5BSQog"
    "ICAgICAgICAgICBrZXkgPSBzZWxmLl9vYWlfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stIikpCiAgICAgICAgICAgIG1z"
    "ZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2"
    "YWxpZCBPcGVuQUkgQVBJIGtleS4iCgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNl"
    "IENfQ1JJTVNPTgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dChtc2cpCiAgICAgICAg"
    "c2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29s"
    "b3J9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7Igog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQob2spCgogICAgZGVm"
    "IGJ1aWxkX2NvbmZpZyhzZWxmKSAtPiBkaWN0OgogICAgICAgICIiIkJ1aWxkIGFuZCByZXR1cm4g"
    "dXBkYXRlZCBjb25maWcgZGljdCBmcm9tIGRpYWxvZyBzZWxlY3Rpb25zLiIiIgogICAgICAgIGNm"
    "ZyAgICAgPSBfZGVmYXVsdF9jb25maWcoKQogICAgICAgIGlkeCAgICAgPSBzZWxmLl90eXBlX2Nv"
    "bWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgdHlwZXMgICA9IFsibG9jYWwiLCAib2xsYW1hIiwg"
    "ImNsYXVkZSIsICJvcGVuYWkiXQogICAgICAgIGNmZ1sibW9kZWwiXVsidHlwZSJdID0gdHlwZXNb"
    "aWR4XQoKICAgICAgICBpZiBpZHggPT0gMDoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJwYXRo"
    "Il0gPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZWxpZiBpZHggPT0g"
    "MToKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJvbGxhbWFfbW9kZWwiXSA9IHNlbGYuX29sbGFt"
    "YV9tb2RlbC50ZXh0KCkuc3RyaXAoKSBvciAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgZWxpZiBp"
    "ZHggPT0gMjoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX2Ns"
    "YXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9k"
    "ZWwiXSA9IHNlbGYuX2NsYXVkZV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdb"
    "Im1vZGVsIl1bImFwaV90eXBlIl0gID0gImNsYXVkZSIKICAgICAgICBlbGlmIGlkeCA9PSAzOgog"
    "ICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAgID0gc2VsZi5fb2FpX2tleS50ZXh0"
    "KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2RlbCJdID0gc2VsZi5f"
    "b2FpX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX3R5"
    "cGUiXSAgPSAib3BlbmFpIgoKICAgICAgICBjZmdbImZpcnN0X3J1biJdID0gRmFsc2UKICAgICAg"
    "ICByZXR1cm4gY2ZnCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3JlYXRlX3Nob3J0Y3V0KHNlbGYp"
    "IC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nob3J0Y3V0X2NiLmlzQ2hlY2tlZCgpCgoK"
    "IyDilIDilIAgSk9VUk5BTCBTSURFQkFSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBKb3VybmFsU2lkZWJhcihRV2lk"
    "Z2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgbGVmdCBzaWRlYmFyIG5leHQgdG8gdGhlIHBl"
    "cnNvbmEgY2hhdCB0YWIuCiAgICBUb3A6IHNlc3Npb24gY29udHJvbHMgKGN1cnJlbnQgc2Vzc2lv"
    "biBuYW1lLCBzYXZlL2xvYWQgYnV0dG9ucywKICAgICAgICAgYXV0b3NhdmUgaW5kaWNhdG9yKS4K"
    "ICAgIEJvZHk6IHNjcm9sbGFibGUgc2Vzc2lvbiBsaXN0IOKAlCBkYXRlLCBBSSBuYW1lLCBtZXNz"
    "YWdlIGNvdW50LgogICAgQ29sbGFwc2VzIGxlZnR3YXJkIHRvIGEgdGhpbiBzdHJpcC4KCiAgICBT"
    "aWduYWxzOgogICAgICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQoc3RyKSAgIOKAlCBkYXRlIHN0"
    "cmluZyBvZiBzZXNzaW9uIHRvIGxvYWQKICAgICAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCgp"
    "ICAgICDigJQgcmV0dXJuIHRvIGN1cnJlbnQgc2Vzc2lvbgogICAgIiIiCgogICAgc2Vzc2lvbl9s"
    "b2FkX3JlcXVlc3RlZCAgPSBTaWduYWwoc3RyKQogICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQg"
    "PSBTaWduYWwoKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzZXNzaW9uX21ncjogIlNlc3Npb25N"
    "YW5hZ2VyIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyID0gc2Vzc2lvbl9tZ3IKICAgICAgICBzZWxmLl9leHBh"
    "bmRlZCAgICA9IFRydWUKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBVc2UgYSBo"
    "b3Jpem9udGFsIHJvb3QgbGF5b3V0IOKAlCBjb250ZW50IG9uIGxlZnQsIHRvZ2dsZSBzdHJpcCBv"
    "biByaWdodAogICAgICAgIHJvb3QgPSBRSEJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgog"
    "ICAgICAgICMg4pSA4pSAIENvbGxhcHNlIHRvZ2dsZSBzdHJpcCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90b2dn"
    "bGVfc3RyaXAgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0Rml4ZWRX"
    "aWR0aCgyMCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItcmlnaHQ6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICB0c19sYXlvdXQgPSBRVkJveExheW91dChz"
    "ZWxmLl90b2dnbGVfc3RyaXApCiAgICAgICAgdHNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCA4LCAwLCA4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTgsIDE4KQogICAgICAgIHNlbGYuX3Rv"
    "Z2dsZV9idG4uc2V0VGV4dCgi4peAIikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19H"
    "T0xEX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsi"
    "CiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X3RvZ2dsZSkKICAgICAgICB0c19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCiAg"
    "ICAgICAgdHNfbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgICAgICAjIOKUgOKUgCBNYWluIGNvbnRl"
    "bnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fY29udGVudCA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWluaW11bVdpZHRoKDE4MCkKICAgICAg"
    "ICBzZWxmLl9jb250ZW50LnNldE1heGltdW1XaWR0aCgyMjApCiAgICAgICAgY29udGVudF9sYXlv"
    "dXQgPSBRVkJveExheW91dChzZWxmLl9jb250ZW50KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldFNw"
    "YWNpbmcoNCkKCiAgICAgICAgIyBTZWN0aW9uIGxhYmVsCiAgICAgICAgY29udGVudF9sYXlvdXQu"
    "YWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEpPVVJOQUwiKSkKCiAgICAgICAgIyBDdXJyZW50"
    "IHNlc3Npb24gaW5mbwogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZSA9IFFMYWJlbCgiTmV3IFNl"
    "c3Npb24iKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFdvcmRXcmFwKFRydWUpCiAgICAg"
    "ICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbmFtZSkKCiAgICAgICAg"
    "IyBTYXZlIC8gTG9hZCByb3cKICAgICAgICBjdHJsX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9idG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCLwn5K+IikKICAgICAgICBzZWxmLl9idG5f"
    "c2F2ZS5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldFRvb2xU"
    "aXAoIlNhdmUgc2Vzc2lvbiBub3ciKQogICAgICAgIHNlbGYuX2J0bl9sb2FkID0gX2dvdGhpY19i"
    "dG4oIvCfk4IiKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldEZpeGVkU2l6ZSgzMiwgMjQpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0VG9vbFRpcCgiQnJvd3NlIGFuZCBsb2FkIGEgcGFzdCBz"
    "ZXNzaW9uIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3QgPSBRTGFiZWwoIuKXjyIpCiAgICAg"
    "ICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlwKCJBdXRvc2F2ZSBzdGF0dXMiKQog"
    "ICAgICAgIHNlbGYuX2J0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19zYXZlKQogICAg"
    "ICAgIHNlbGYuX2J0bl9sb2FkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19sb2FkKQogICAgICAg"
    "IGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZSkKICAgICAgICBjdHJsX3Jvdy5hZGRX"
    "aWRnZXQoc2VsZi5fYnRuX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2F1"
    "dG9zYXZlX2RvdCkKICAgICAgICBjdHJsX3Jvdy5hZGRTdHJldGNoKCkKICAgICAgICBjb250ZW50"
    "X2xheW91dC5hZGRMYXlvdXQoY3RybF9yb3cpCgogICAgICAgICMgSm91cm5hbCBsb2FkZWQgaW5k"
    "aWNhdG9yCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2Vs"
    "Zi5fam91cm5hbF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfUFVS"
    "UExFfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIK"
    "ICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9qb3VybmFsX2xibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLl9qb3VybmFsX2xibCkKCiAgICAgICAgIyBDbGVhciBqb3VybmFsIGJ1dHRv"
    "biAoaGlkZGVuIHdoZW4gbm90IGxvYWRlZCkKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5h"
    "bCA9IF9nb3RoaWNfYnRuKCLinJcgUmV0dXJuIHRvIFByZXNlbnQiKQogICAgICAgIHNlbGYuX2J0"
    "bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "X2pvdXJuYWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2NsZWFyX2pvdXJuYWwpCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsKQoKICAgICAg"
    "ICAjIERpdmlkZXIKICAgICAgICBkaXYgPSBRRnJhbWUoKQogICAgICAgIGRpdi5zZXRGcmFtZVNo"
    "YXBlKFFGcmFtZS5TaGFwZS5ITGluZSkKICAgICAgICBkaXYuc2V0U3R5bGVTaGVldChmImNvbG9y"
    "OiB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoZGl2"
    "KQoKICAgICAgICAjIFNlc3Npb24gbGlzdAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoIuKdpyBQQVNUIFNFU1NJT05TIikpCiAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xE"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7"
    "IgogICAgICAgICAgICBmIlFMaXN0V2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6"
    "IHtDX0NSSU1TT05fRElNfTsgfX0iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlz"
    "dC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1DbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vzc2lv"
    "bl9jbGljaykKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vzc2lvbl9s"
    "aXN0LCAxKQoKICAgICAgICAjIEFkZCBjb250ZW50IGFuZCB0b2dnbGUgc3RyaXAgdG8gdGhlIHJv"
    "b3QgaG9yaXpvbnRhbCBsYXlvdXQKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb250ZW50"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKCiAgICBkZWYgX3Rv"
    "Z2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4"
    "cGFuZGVkCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQog"
    "ICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIiBpZiBzZWxmLl9leHBhbmRlZCBl"
    "bHNlICLilrYiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHAgPSBzZWxm"
    "LnBhcmVudFdpZGdldCgpCiAgICAgICAgaWYgcCBhbmQgcC5sYXlvdXQoKToKICAgICAgICAgICAg"
    "cC5sYXlvdXQoKS5hY3RpdmF0ZSgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZXNzaW9ucyA9IHNlbGYuX3Nlc3Npb25fbWdyLmxpc3Rfc2Vzc2lvbnMoKQogICAgICAg"
    "IHNlbGYuX3Nlc3Npb25fbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIHMgaW4gc2Vzc2lvbnM6CiAg"
    "ICAgICAgICAgIGRhdGVfc3RyID0gcy5nZXQoImRhdGUiLCIiKQogICAgICAgICAgICBuYW1lICAg"
    "ICA9IHMuZ2V0KCJuYW1lIiwgZGF0ZV9zdHIpWzozMF0KICAgICAgICAgICAgY291bnQgICAgPSBz"
    "LmdldCgibWVzc2FnZV9jb3VudCIsIDApCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0"
    "ZW0oZiJ7ZGF0ZV9zdHJ9XG57bmFtZX0gKHtjb3VudH0gbXNncykiKQogICAgICAgICAgICBpdGVt"
    "LnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBkYXRlX3N0cikKICAgICAgICAgICAg"
    "aXRlbS5zZXRUb29sVGlwKGYiRG91YmxlLWNsaWNrIHRvIGxvYWQgc2Vzc2lvbiBmcm9tIHtkYXRl"
    "X3N0cn0iKQogICAgICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuYWRkSXRlbShpdGVtKQoKICAg"
    "IGRlZiBzZXRfc2Vzc2lvbl9uYW1lKHNlbGYsIG5hbWU6IHN0cikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9zZXNzaW9uX25hbWUuc2V0VGV4dChuYW1lWzo1MF0gb3IgIk5ldyBTZXNzaW9uIikKCiAg"
    "ICBkZWYgc2V0X2F1dG9zYXZlX2luZGljYXRvcihzZWxmLCBzYXZlZDogYm9vbCkgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfR1JFRU4gaWYgc2F2ZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBm"
    "ImZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9h"
    "dXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgKICAgICAgICAgICAgIkF1dG9zYXZlZCIgaWYgc2F2ZWQg"
    "ZWxzZSAiUGVuZGluZyBhdXRvc2F2ZSIKICAgICAgICApCgogICAgZGVmIHNldF9qb3VybmFsX2xv"
    "YWRlZChzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2pvdXJuYWxf"
    "bGJsLnNldFRleHQoZiLwn5OWIEpvdXJuYWw6IHtkYXRlX3N0cn0iKQogICAgICAgIHNlbGYuX2J0"
    "bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoVHJ1ZSkKCiAgICBkZWYgY2xlYXJfam91cm5hbF9p"
    "bmRpY2F0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0"
    "KCIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCgog"
    "ICAgZGVmIF9kb19zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9tZ3Iu"
    "c2F2ZSgpCiAgICAgICAgc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKFRydWUpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLinJMiKQogICAg"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAsIGxhbWJkYTogc2VsZi5fYnRuX3NhdmUuc2V0VGV4"
    "dCgi8J+SviIpKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMDAsIGxhbWJkYTogc2VsZi5z"
    "ZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKSkKCiAgICBkZWYgX2RvX2xvYWQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAjIFRyeSBzZWxlY3RlZCBpdGVtIGZpcnN0CiAgICAgICAgaXRlbSA9IHNl"
    "bGYuX3Nlc3Npb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgaWYgbm90IGl0ZW06CiAgICAg"
    "ICAgICAgICMgSWYgbm90aGluZyBzZWxlY3RlZCwgdHJ5IHRoZSBmaXJzdCBpdGVtCiAgICAgICAg"
    "ICAgIGlmIHNlbGYuX3Nlc3Npb25fbGlzdC5jb3VudCgpID4gMDoKICAgICAgICAgICAgICAgIGl0"
    "ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbSgwKQogICAgICAgICAgICAgICAgc2VsZi5fc2Vz"
    "c2lvbl9saXN0LnNldEN1cnJlbnRJdGVtKGl0ZW0pCiAgICAgICAgaWYgaXRlbToKICAgICAgICAg"
    "ICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAg"
    "ICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAgICBkZWYg"
    "X29uX3Nlc3Npb25fY2xpY2soc2VsZiwgaXRlbSkgLT4gTm9uZToKICAgICAgICBkYXRlX3N0ciA9"
    "IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgc2VsZi5zZXNzaW9u"
    "X2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9kb19jbGVhcl9qb3VybmFs"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5lbWl0"
    "KCkKICAgICAgICBzZWxmLmNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKCkKCgojIOKUgOKUgCBUT1JQ"
    "T1IgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRvcnBvclBhbmVsKFFXaWRnZXQpOgogICAg"
    "IiIiCiAgICBUaHJlZS1zdGF0ZSBzdXNwZW5zaW9uIHRvZ2dsZTogQVdBS0UgfCBBVVRPIHwgU1VT"
    "UEVORAoKICAgIEFXQUtFICDigJQgbW9kZWwgbG9hZGVkLCBhdXRvLXRvcnBvciBkaXNhYmxlZCwg"
    "aWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBBVVRPICAg4oCUIG1vZGVsIGxvYWRlZCwgbW9uaXRv"
    "cnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3VzdGFpbmVkCiAgICBTVVNQRU5EIOKA"
    "lCBtb2RlbCB1bmxvYWRlZCwgc3RheXMgc3VzcGVuZGVkIHVudGlsIG1hbnVhbGx5IGNoYW5nZWQK"
    "CiAgICBTaWduYWxzOgogICAgICAgIHN0YXRlX2NoYW5nZWQoc3RyKSAg4oCUICJBV0FLRSIgfCAi"
    "QVVUTyIgfCAiU1VTUEVORCIKICAgICIiIgoKICAgIHN0YXRlX2NoYW5nZWQgPSBTaWduYWwoc3Ry"
    "KQoKICAgIFNUQVRFUyA9IFsiQVdBS0UiLCAiQVVUTyIsICJTVVNQRU5EIl0KCiAgICBTVEFURV9T"
    "VFlMRVMgPSB7CiAgICAgICAgIkFXQUtFIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJh"
    "Y2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBib3JkZXItcmFkaXVzOiAycHg7ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdB"
    "S0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXRvcnBvciBk"
    "aXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAgIkFVVE8iOiB7CiAgICAgICAgICAgICJhY3Rp"
    "dmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsgY29sb3I6ICNjYzg4MjI7ICIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVz"
    "OiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjog"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1"
    "czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAg"
    "ICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJNb2RlbCBhY3RpdmUuIEF1dG8t"
    "c3VzcGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAgfSwKICAgICAgICAiU1VTUEVORCI6"
    "IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiB7Q19QVVJQTEVfRElNfTsg"
    "Y29sb3I6IHtDX1BVUlBMRX07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNw"
    "eCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBj"
    "b2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAz"
    "cHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgIGYi4pqwIHtVSV9TVVNQRU5TSU9OX0xB"
    "QkVMLnN0cmlwKCkgaWYgc3RyKFVJX1NVU1BFTlNJT05fTEFCRUwpLnN0cmlwKCkgZWxzZSAnU3Vz"
    "cGVuZCd9IiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgZiJNb2RlbCB1bmxvYWRlZC4ge0RFQ0tf"
    "TkFNRX0gc2xlZXBzIHVudGlsIG1hbnVhbGx5IGF3YWtlbmVkLiIsCiAgICAgICAgfSwKICAgIH0K"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2N1cnJlbnQgPSAiQVdBS0UiCiAgICAgICAgc2Vs"
    "Zi5fYnV0dG9uczogZGljdFtzdHIsIFFQdXNoQnV0dG9uXSA9IHt9CiAgICAgICAgbGF5b3V0ID0g"
    "UUhCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAs"
    "IDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgZm9yIHN0YXRlIGlu"
    "IHNlbGYuU1RBVEVTOgogICAgICAgICAgICBidG4gPSBRUHVzaEJ1dHRvbihzZWxmLlNUQVRFX1NU"
    "WUxFU1tzdGF0ZV1bImxhYmVsIl0pCiAgICAgICAgICAgIGJ0bi5zZXRUb29sVGlwKHNlbGYuU1RB"
    "VEVfU1RZTEVTW3N0YXRlXVsidG9vbHRpcCJdKQogICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWln"
    "aHQoMjIpCiAgICAgICAgICAgIGJ0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIGNoZWNrZWQsIHM9"
    "c3RhdGU6IHNlbGYuX3NldF9zdGF0ZShzKSkKICAgICAgICAgICAgc2VsZi5fYnV0dG9uc1tzdGF0"
    "ZV0gPSBidG4KICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChidG4pCgogICAgICAgIHNlbGYu"
    "X2FwcGx5X3N0eWxlcygpCgogICAgZGVmIF9zZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50OgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9jdXJyZW50ID0gc3RhdGUKICAgICAgICBzZWxmLl9hcHBseV9zdHls"
    "ZXMoKQogICAgICAgIHNlbGYuc3RhdGVfY2hhbmdlZC5lbWl0KHN0YXRlKQoKICAgIGRlZiBfYXBw"
    "bHlfc3R5bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIHN0YXRlLCBidG4gaW4gc2VsZi5f"
    "YnV0dG9ucy5pdGVtcygpOgogICAgICAgICAgICBzdHlsZV9rZXkgPSAiYWN0aXZlIiBpZiBzdGF0"
    "ZSA9PSBzZWxmLl9jdXJyZW50IGVsc2UgImluYWN0aXZlIgogICAgICAgICAgICBidG4uc2V0U3R5"
    "bGVTaGVldChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bc3R5bGVfa2V5XSkKCiAgICBAcHJvcGVy"
    "dHkKICAgIGRlZiBjdXJyZW50X3N0YXRlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fY3VycmVudAoKICAgIGRlZiBzZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICAiIiJTZXQgc3RhdGUgcHJvZ3JhbW1hdGljYWxseSAoZS5nLiBmcm9tIGF1dG8tdG9y"
    "cG9yIGRldGVjdGlvbikuIiIiCiAgICAgICAgaWYgc3RhdGUgaW4gc2VsZi5TVEFURVM6CiAgICAg"
    "ICAgICAgIHNlbGYuX3NldF9zdGF0ZShzdGF0ZSkKCgojIOKUgOKUgCBNQUlOIFdJTkRPVyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgRWNob0RlY2soUU1haW5XaW5kb3cpOgogICAgIiIiCiAgICBU"
    "aGUgbWFpbiBFY2hvIERlY2sgd2luZG93LgogICAgQXNzZW1ibGVzIGFsbCB3aWRnZXRzLCBjb25u"
    "ZWN0cyBhbGwgc2lnbmFscywgbWFuYWdlcyBhbGwgc3RhdGUuCiAgICAiIiIKCiAgICAjIOKUgOKU"
    "gCBUb3Jwb3IgdGhyZXNob2xkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9FWFRFUk5B"
    "TF9WUkFNX1RPUlBPUl9HQiAgICA9IDEuNSAgICMgZXh0ZXJuYWwgVlJBTSA+IHRoaXMg4oaSIGNv"
    "bnNpZGVyIHRvcnBvcgogICAgX0VYVEVSTkFMX1ZSQU1fV0FLRV9HQiAgICAgID0gMC44ICAgIyBl"
    "eHRlcm5hbCBWUkFNIDwgdGhpcyDihpIgY29uc2lkZXIgd2FrZQogICAgX1RPUlBPUl9TVVNUQUlO"
    "RURfVElDS1MgICAgID0gNiAgICAgIyA2IMOXIDVzID0gMzAgc2Vjb25kcyBzdXN0YWluZWQKICAg"
    "IF9XQUtFX1NVU1RBSU5FRF9USUNLUyAgICAgICA9IDEyICAgICMgNjAgc2Vjb25kcyBzdXN0YWlu"
    "ZWQgbG93IHByZXNzdXJlCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18oKQoKICAgICAgICAjIOKUgOKUgCBDb3JlIHN0YXRlIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXR1cyAgICAgICAgICAgICAgPSAiT0ZG"
    "TElORSIKICAgICAgICBzZWxmLl9zZXNzaW9uX3N0YXJ0ICAgICAgID0gdGltZS50aW1lKCkKICAg"
    "ICAgICBzZWxmLl90b2tlbl9jb3VudCAgICAgICAgID0gMAogICAgICAgIHNlbGYuX2ZhY2VfbG9j"
    "a2VkICAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlICAgICAgICAgPSBU"
    "cnVlCiAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgICAgICA9IEZhbHNlCiAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbl9pZCAgICAgICAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRp"
    "bWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHM6IGxpc3Qg"
    "PSBbXSAgIyBrZWVwIHJlZnMgdG8gcHJldmVudCBHQyB3aGlsZSBydW5uaW5nCiAgICAgICAgc2Vs"
    "Zi5fZmlyc3RfdG9rZW46IGJvb2wgPSBUcnVlICAgIyB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9y"
    "ZSBmaXJzdCBzdHJlYW1pbmcgdG9rZW4KCiAgICAgICAgIyBUb3Jwb3IgLyBWUkFNIHRyYWNraW5n"
    "CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlICAgICAgICA9ICJBV0FLRSIKICAgICAgICBzZWxm"
    "Ll9kZWNrX3ZyYW1fYmFzZSAgPSAwLjAgICAjIGJhc2VsaW5lIFZSQU0gYWZ0ZXIgbW9kZWwgbG9h"
    "ZAogICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwICAgICAjIHN1c3RhaW5lZCBw"
    "cmVzc3VyZSBjb3VudGVyCiAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAgICAg"
    "ICMgc3VzdGFpbmVkIHJlbGllZiBjb3VudGVyCiAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21p"
    "c3Npb25zID0gMAogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSAgICAgICAgPSBOb25lICAjIGRh"
    "dGV0aW1lIHdoZW4gdG9ycG9yIGJlZ2FuCiAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9u"
    "ICA9ICIiICAgIyBmb3JtYXR0ZWQgZHVyYXRpb24gc3RyaW5nCgogICAgICAgICMg4pSA4pSAIE1h"
    "bmFnZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuX21lbW9yeSAgID0gTWVtb3J5TWFuYWdlcigpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMgPSBT"
    "ZXNzaW9uTWFuYWdlcigpCiAgICAgICAgc2VsZi5fbGVzc29ucyAgPSBMZXNzb25zTGVhcm5lZERC"
    "KCkKICAgICAgICBzZWxmLl90YXNrcyAgICA9IFRhc2tNYW5hZ2VyKCkKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzX2NhY2hlOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9yZWNvcmRzX2luaXRp"
    "YWxpemVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkID0g"
    "InJvb3QiCiAgICAgICAgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHkgPSBGYWxzZQogICAgICAgIHNl"
    "bGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAg"
    "IHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0gPSBO"
    "b25lCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IEZh"
    "bHNlCiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9ICJuZXh0XzNfbW9udGhzIgoKICAg"
    "ICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "IyBJbnN0YW50aWF0ZSBzZXJ2aWNlIHdyYXBwZXJzIHVwLWZyb250OyBhdXRoIGlzIGZvcmNlZCBs"
    "YXRlcgogICAgICAgICMgZnJvbSBtYWluKCkgYWZ0ZXIgd2luZG93LnNob3coKSB3aGVuIHRoZSBl"
    "dmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgZ19jcmVkc19wYXRoID0gUGF0aChDRkcuZ2V0"
    "KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAiY3JlZGVudGlhbHMiLAogICAgICAgICAg"
    "ICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIikKICAg"
    "ICAgICApKQogICAgICAgIGdfdG9rZW5fcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30p"
    "LmdldCgKICAgICAgICAgICAgInRva2VuIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29n"
    "bGUiKSAvICJ0b2tlbi5qc29uIikKICAgICAgICApKQogICAgICAgIHNlbGYuX2djYWwgPSBHb29n"
    "bGVDYWxlbmRhclNlcnZpY2UoZ19jcmVkc19wYXRoLCBnX3Rva2VuX3BhdGgpCiAgICAgICAgc2Vs"
    "Zi5fZ2RyaXZlID0gR29vZ2xlRG9jc0RyaXZlU2VydmljZSgKICAgICAgICAgICAgZ19jcmVkc19w"
    "YXRoLAogICAgICAgICAgICBnX3Rva2VuX3BhdGgsCiAgICAgICAgICAgIGxvZ2dlcj1sYW1iZGEg"
    "bXNnLCBsZXZlbD0iSU5GTyI6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHRFJJVkVdIHttc2d9Iiwg"
    "bGV2ZWwpCiAgICAgICAgKQoKICAgICAgICAjIFNlZWQgTFNMIHJ1bGVzIG9uIGZpcnN0IHJ1bgog"
    "ICAgICAgIHNlbGYuX2xlc3NvbnMuc2VlZF9sc2xfcnVsZXMoKQoKICAgICAgICAjIExvYWQgZW50"
    "aXR5IHN0YXRlCiAgICAgICAgc2VsZi5fc3RhdGUgPSBzZWxmLl9tZW1vcnkubG9hZF9zdGF0ZSgp"
    "CiAgICAgICAgc2VsZi5fc3RhdGVbInNlc3Npb25fY291bnQiXSA9IHNlbGYuX3N0YXRlLmdldCgi"
    "c2Vzc2lvbl9jb3VudCIsMCkgKyAxCiAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc3RhcnR1cCJd"
    "ICA9IGxvY2FsX25vd19pc28oKQogICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYu"
    "X3N0YXRlKQoKICAgICAgICAjIEJ1aWxkIGFkYXB0b3IKICAgICAgICBzZWxmLl9hZGFwdG9yID0g"
    "YnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpCgogICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2Vy"
    "IChzZXQgdXAgYWZ0ZXIgd2lkZ2V0cyBidWlsdCkKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21n"
    "cjogT3B0aW9uYWxbRmFjZVRpbWVyTWFuYWdlcl0gPSBOb25lCgogICAgICAgICMg4pSA4pSAIEJ1"
    "aWxkIFVJIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuc2V0V2luZG93VGl0bGUoQVBQX05BTUUpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgx"
    "MjAwLCA3NTApCiAgICAgICAgc2VsZi5yZXNpemUoMTM1MCwgODUwKQogICAgICAgIHNlbGYuc2V0"
    "U3R5bGVTaGVldChTVFlMRSkKCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgICAgICAjIEZh"
    "Y2UgdGltZXIgbWFuYWdlciB3aXJlZCB0byB3aWRnZXRzCiAgICAgICAgc2VsZi5fZmFjZV90aW1l"
    "cl9tZ3IgPSBGYWNlVGltZXJNYW5hZ2VyKAogICAgICAgICAgICBzZWxmLl9taXJyb3IsIHNlbGYu"
    "X2Vtb3Rpb25fYmxvY2sKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRpbWVycyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0"
    "c190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIudGltZW91dC5jb25u"
    "ZWN0KHNlbGYuX3VwZGF0ZV9zdGF0cykKICAgICAgICBzZWxmLl9zdGF0c190aW1lci5zdGFydCgx"
    "MDAwKQoKICAgICAgICBzZWxmLl9ibGlua190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5f"
    "YmxpbmtfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2JsaW5rKQogICAgICAgIHNlbGYuX2Js"
    "aW5rX3RpbWVyLnN0YXJ0KDgwMCkKCiAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIgPSBR"
    "VGltZXIoKQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl92YW1wX3N0cmlw"
    "IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0"
    "LmNvbm5lY3Qoc2VsZi5fdmFtcF9zdHJpcC5yZWZyZXNoKQogICAgICAgICAgICBzZWxmLl9zdGF0"
    "ZV9zdHJpcF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRf"
    "dGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci50"
    "aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljaykKICAgICAg"
    "ICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgc2VsZi5f"
    "Z29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYu"
    "X2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dv"
    "b2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXJfdGljaykKICAgICAgICBzZWxmLl9nb29nbGVfcmVj"
    "b3Jkc19yZWZyZXNoX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICAjIOKUgOKUgCBTY2hlZHVs"
    "ZXIgYW5kIHN0YXJ0dXAgZGVmZXJyZWQgdW50aWwgYWZ0ZXIgd2luZG93LnNob3coKSDilIDilIDi"
    "lIAKICAgICAgICAjIERvIE5PVCBjYWxsIF9zZXR1cF9zY2hlZHVsZXIoKSBvciBfc3RhcnR1cF9z"
    "ZXF1ZW5jZSgpIGhlcmUuCiAgICAgICAgIyBCb3RoIGFyZSB0cmlnZ2VyZWQgdmlhIFFUaW1lci5z"
    "aW5nbGVTaG90IGZyb20gbWFpbigpIGFmdGVyCiAgICAgICAgIyB3aW5kb3cuc2hvdygpIGFuZCBh"
    "cHAuZXhlYygpIGJlZ2lucyBydW5uaW5nLgoKICAgICMg4pSA4pSAIFVJIENPTlNUUlVDVElPTiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBjZW50cmFsID0gUVdpZGdldCgp"
    "CiAgICAgICAgc2VsZi5zZXRDZW50cmFsV2lkZ2V0KGNlbnRyYWwpCiAgICAgICAgcm9vdCA9IFFW"
    "Qm94TGF5b3V0KGNlbnRyYWwpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwg"
    "NiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyDilIDilIAgVGl0bGUg"
    "YmFyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX2J1aWxkX3RpdGxlX2JhcigpKQoKICAgICAgICAjIOKUgOKUgCBCb2R5OiBK"
    "b3VybmFsIHwgQ2hhdCB8IFN5c3RlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgYm9keSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBib2R5LnNldFNwYWNpbmcoNCkKCiAg"
    "ICAgICAgIyBKb3VybmFsIHNpZGViYXIgKGxlZnQpCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRl"
    "YmFyID0gSm91cm5hbFNpZGViYXIoc2VsZi5fc2Vzc2lvbnMpCiAgICAgICAgc2VsZi5fam91cm5h"
    "bF9zaWRlYmFyLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2Vs"
    "Zi5fbG9hZF9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNl"
    "c3Npb25fY2xlYXJfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2pv"
    "dXJuYWxfc2Vzc2lvbikKICAgICAgICBib2R5LmFkZFdpZGdldChzZWxmLl9qb3VybmFsX3NpZGVi"
    "YXIpCgogICAgICAgICMgQ2hhdCBwYW5lbCAoY2VudGVyLCBleHBhbmRzKQogICAgICAgIGJvZHku"
    "YWRkTGF5b3V0KHNlbGYuX2J1aWxkX2NoYXRfcGFuZWwoKSwgMSkKCiAgICAgICAgIyBTeXN0ZW1z"
    "IChyaWdodCkKICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9zcGVsbGJvb2tfcGFu"
    "ZWwoKSkKCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYm9keSwgMSkKCiAgICAgICAgIyDilIDilIAg"
    "QUkgU3RhdGUgU3RyaXAgKGZ1bGwgd2lkdGgsIHdoZW4gZW5hYmxlZCkg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaWYgQUlfU1RBVEVT"
    "X0VOQUJMRUQgYW5kIHNlbGYuX3ZhbXBfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJv"
    "b3QuYWRkV2lkZ2V0KHNlbGYuX3ZhbXBfc3RyaXApCgogICAgICAgICMg4pSA4pSAIEZvb3RlciDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmb290"
    "ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYi4pymIHtBUFBfTkFNRX0g4oCUIHZ7QVBQX1ZFUlNJ"
    "T059IOKcpiIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5n"
    "OiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIK"
    "ICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFs"
    "aWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGZvb3RlcikKCiAgICBkZWYgX2J1aWxk"
    "X3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIGJhciA9IFFXaWRnZXQoKQogICAg"
    "ICAgIGJhci5zZXRGaXhlZEhlaWdodCgzNikKICAgICAgICBiYXIuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkK"
    "ICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChiYXIpCiAgICAgICAgbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygxMCwgMCwgMTAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNikKCiAg"
    "ICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0FQUF9OQU1FfSIpCiAgICAgICAgdGl0bGUuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTog"
    "MTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzog"
    "MnB4OyBib3JkZXI6IG5vbmU7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAg"
    "ICAgICkKCiAgICAgICAgcnVuZXMgPSBRTGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LXNpemU6IDEw"
    "cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHJ1bmVzLnNldEFsaWdubWVudChR"
    "dC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9"
    "IFFMYWJlbChmIuKXiSB7VUlfT0ZGTElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19s"
    "YWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19CTE9PRH07IGZvbnQt"
    "c2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFs"
    "aWduUmlnaHQpCgogICAgICAgICMgU3VzcGVuc2lvbiBwYW5lbAogICAgICAgIHNlbGYuX3RvcnBv"
    "cl9wYW5lbCA9IE5vbmUKICAgICAgICBpZiBTVVNQRU5TSU9OX0VOQUJMRUQ6CiAgICAgICAgICAg"
    "IHNlbGYuX3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkKICAgICAgICAgICAgc2VsZi5fdG9y"
    "cG9yX3BhbmVsLnN0YXRlX2NoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hh"
    "bmdlZCkKCiAgICAgICAgIyBJZGxlIHRvZ2dsZQogICAgICAgIHNlbGYuX2lkbGVfYnRuID0gUVB1"
    "c2hCdXR0b24oIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRGaXhlZEhlaWdo"
    "dCgyMikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl9pZGxlX2J0bi5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250"
    "LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X2lkbGVfYnRuLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9vbl9pZGxlX3RvZ2dsZWQpCgogICAgICAg"
    "ICMgRlMgLyBCTCBidXR0b25zCiAgICAgICAgc2VsZi5fZnNfYnRuID0gUVB1c2hCdXR0b24oIkZT"
    "IikKICAgICAgICBzZWxmLl9ibF9idG4gPSBRUHVzaEJ1dHRvbigiQkwiKQogICAgICAgIHNlbGYu"
    "X2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRvbigiRXhwb3J0IikKICAgICAgICBzZWxmLl9zaHV0ZG93"
    "bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAgIGZvciBidG4gaW4gKHNlbGYu"
    "X2ZzX2J0biwgc2VsZi5fYmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAgYnRu"
    "LnNldEZpeGVkU2l6ZSgzMCwgMjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19"
    "OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsg"
    "Zm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBh"
    "ZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRGaXhl"
    "ZFdpZHRoKDQ2KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZEhlaWdodCgyMikK"
    "ICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRXaWR0aCg2OCkKICAgICAgICBzZWxm"
    "Ll9zaHV0ZG93bl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfQkxPT0R9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQkxPT0R9OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZnNfYnRuLnNldFRv"
    "b2xUaXAoIkZ1bGxzY3JlZW4gKEYxMSkiKQogICAgICAgIHNlbGYuX2JsX2J0bi5zZXRUb29sVGlw"
    "KCJCb3JkZXJsZXNzIChGMTApIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldFRvb2xUaXAo"
    "IkV4cG9ydCBjaGF0IHNlc3Npb24gdG8gVFhUIGZpbGUiKQogICAgICAgIHNlbGYuX3NodXRkb3du"
    "X2J0bi5zZXRUb29sVGlwKGYiR3JhY2VmdWwgc2h1dGRvd24g4oCUIHtERUNLX05BTUV9IHNwZWFr"
    "cyB0aGVpciBsYXN0IHdvcmRzIikKICAgICAgICBzZWxmLl9mc19idG4uY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKQogICAgICAgIHNlbGYuX2JsX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZXhwb3J0X2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25f"
    "YnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQodGl0bGUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChydW5l"
    "cywgMSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQogICAgICAg"
    "IGxheW91dC5hZGRTcGFjaW5nKDgpCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3BhbmVsIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3RvcnBvcl9wYW5lbCkK"
    "ICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5faWRsZV9idG4pCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2V4cG9ydF9idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9zaHV0ZG93bl9idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9mc19idG4pCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9ibF9idG4pCgogICAgICAgIHJldHVybiBiYXIK"
    "CiAgICBkZWYgX2J1aWxkX2NoYXRfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAg"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgICMgTWFpbiB0YWIgd2lkZ2V0IOKAlCBwZXJzb25hIGNoYXQgdGFiIHwgU2VsZgogICAgICAg"
    "IHNlbGYuX21haW5fdGFicyA9IFFUYWJXaWRnZXQoKQogICAgICAgIHNlbGYuX21haW5fdGFicy5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFUYWJXaWRnZXQ6OnBhbmUge3sgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "TU9OSVRPUn07IH19IgogICAgICAgICAgICBmIlFUYWJCYXI6OnRhYiB7eyBiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNHB4"
    "IDEycHg7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IH19IgogICAgICAg"
    "ICAgICBmIlFUYWJCYXI6OnRhYjpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xv"
    "cjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXItYm90dG9tOiAycHggc29saWQge0Nf"
    "Q1JJTVNPTn07IH19IgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGFiIDA6IFBlcnNvbmEg"
    "Y2hhdCB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VhbmNlX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlYW5jZV9sYXlvdXQg"
    "PSBRVkJveExheW91dChzZWFuY2Vfd2lkZ2V0KQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRTcGFjaW5n"
    "KDApCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3Bs"
    "YXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsg"
    "Y29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBw"
    "YWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWFuY2VfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLl9jaGF0X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWFuY2Vf"
    "d2lkZ2V0LCBmIuKdpyB7VUlfQ0hBVF9XSU5ET1d9IikKCiAgICAgICAgIyDilIDilIAgVGFiIDE6"
    "IFNlbGYg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2VsZl90"
    "YWJfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZl9sYXlvdXQgPSBRVkJveExheW91dChz"
    "ZWxmLl9zZWxmX3RhYl93aWRnZXQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0Q29udGVudHNNYXJn"
    "aW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAg"
    "IHNlbGYuX3NlbGZfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNw"
    "bGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4"
    "OyIKICAgICAgICApCiAgICAgICAgc2VsZl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NlbGZfZGlz"
    "cGxheSwgMSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlbGYuX3NlbGZfdGFiX3dp"
    "ZGdldCwgIuKXiSBTRUxGIikKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9tYWluX3Rh"
    "YnMsIDEpCgogICAgICAgICMg4pSA4pSAIEJvdHRvbSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgIyBNSVJST1IgfCBFTU9USU9OUyB8IEJMT09EIHwgTU9PTiB8IE1BTkEgfCBFU1NF"
    "TkNFCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJsb2NrX3Jvdy5z"
    "ZXRTcGFjaW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZlciBjb2xsYXBzZXMpCiAgICAgICAg"
    "bWlycm9yX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVkJveExheW91dCht"
    "aXJyb3Jfd3JhcCkKICAgICAgICBtd19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBtd19sYXlvdXQuYWRk"
    "V2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE1JUlJPUiIpKQogICAgICAgIHNlbGYuX21pcnJvciA9"
    "IE1pcnJvcldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgxNjAsIDE2"
    "MCkKICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAgICBibG9j"
    "a19yb3cuYWRkV2lkZ2V0KG1pcnJvcl93cmFwKQoKICAgICAgICAjIEVtb3Rpb24gYmxvY2sgKGNv"
    "bGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90aW9uQmxvY2soKQog"
    "ICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAg"
    "ICAgICAgICLinacgRU1PVElPTlMiLCBzZWxmLl9lbW90aW9uX2Jsb2NrLAogICAgICAgICAgICBl"
    "eHBhbmRlZD1UcnVlLCBtaW5fd2lkdGg9MTMwCiAgICAgICAgKQogICAgICAgIGJsb2NrX3Jvdy5h"
    "ZGRXaWRnZXQoc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwKQoKICAgICAgICBzZWxmLl9ibG9vZF9z"
    "cGhlcmUgPSBOb25lCiAgICAgICAgc2VsZi5fbW9vbl93aWRnZXQgPSBOb25lCiAgICAgICAgc2Vs"
    "Zi5fbWFuYV9zcGhlcmUgPSBOb25lCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAg"
    "ICAgICAgICMgQmxvb2Qgc3BoZXJlIChjb2xsYXBzaWJsZSkKICAgICAgICAgICAgc2VsZi5fYmxv"
    "b2Rfc3BoZXJlID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICAgICAgIlJFU0VSVkUiLCBDX0NS"
    "SU1TT04sIENfQ1JJTVNPTl9ESU0KICAgICAgICAgICAgKQogICAgICAgICAgICBibG9ja19yb3cu"
    "YWRkV2lkZ2V0KAogICAgICAgICAgICAgICAgQ29sbGFwc2libGVCbG9jaygi4p2nIFJFU0VSVkUi"
    "LCBzZWxmLl9ibG9vZF9zcGhlcmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1p"
    "bl93aWR0aD05MCkKICAgICAgICAgICAgKQoKICAgICAgICAgICAgIyBNb29uIChjb2xsYXBzaWJs"
    "ZSkKICAgICAgICAgICAgc2VsZi5fbW9vbl93aWRnZXQgPSBNb29uV2lkZ2V0KCkKICAgICAgICAg"
    "ICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2so"
    "IuKdpyBMVU5BUiIsIHNlbGYuX21vb25fd2lkZ2V0LCBtaW5fd2lkdGg9OTApCiAgICAgICAgICAg"
    "ICkKCiAgICAgICAgICAgICMgTWFuYSBzcGhlcmUgKGNvbGxhcHNpYmxlKQogICAgICAgICAgICBz"
    "ZWxmLl9tYW5hX3NwaGVyZSA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgICAgICJBUkNBTkEi"
    "LCBDX1BVUlBMRSwgQ19QVVJQTEVfRElNCiAgICAgICAgICAgICkKICAgICAgICAgICAgYmxvY2tf"
    "cm93LmFkZFdpZGdldCgKICAgICAgICAgICAgICAgIENvbGxhcHNpYmxlQmxvY2soIuKdpyBBUkNB"
    "TkEiLCBzZWxmLl9tYW5hX3NwaGVyZSwgbWluX3dpZHRoPTkwKQogICAgICAgICAgICApCgogICAg"
    "ICAgICMgRXNzZW5jZSAoSFVOR0VSICsgVklUQUxJVFkgYmFycywgY29sbGFwc2libGUpCiAgICAg"
    "ICAgZXNzZW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBlc3NlbmNlX2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KGVzc2VuY2Vfd2lkZ2V0KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldFNwYWNpbmco"
    "NCkKICAgICAgICBzZWxmLl9odW5nZXJfZ2F1Z2UgICA9IEdhdWdlV2lkZ2V0KCJIVU5HRVIiLCAg"
    "ICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLl92aXRhbGl0eV9nYXVnZSA9IEdh"
    "dWdlV2lkZ2V0KCJWSVRBTElUWSIsICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5j"
    "ZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2h1bmdlcl9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fdml0YWxpdHlfZ2F1Z2UpCiAgICAgICAgYmxvY2tfcm93LmFk"
    "ZFdpZGdldCgKICAgICAgICAgICAgQ29sbGFwc2libGVCbG9jaygi4p2nIEVTU0VOQ0UiLCBlc3Nl"
    "bmNlX3dpZGdldCwgbWluX3dpZHRoPTExMCkKICAgICAgICApCgogICAgICAgIGJsb2NrX3Jvdy5h"
    "ZGRTdHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJsb2NrX3JvdykKCiAgICAgICAg"
    "IyBBSSBTdGF0ZSBTdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCB3aGVuIGVuYWJsZWQpCiAgICAg"
    "ICAgc2VsZi5fdmFtcF9zdHJpcCA9IFZhbXBpcmVTdGF0ZVN0cmlwKCkgaWYgQUlfU1RBVEVTX0VO"
    "QUJMRUQgZWxzZSBOb25lCiAgICAgICAgaWYgc2VsZi5fdmFtcF9zdHJpcCBpcyBub3QgTm9uZToK"
    "ICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl92YW1wX3N0cmlwKQoKICAgICAgICAj"
    "IOKUgOKUgCBJbnB1dCByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9zeW0gPSBRTGFi"
    "ZWwoIuKcpiIpCiAgICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDogYm9sZDsg"
    "Ym9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZFdpZHRo"
    "KDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lOUFVUX1BMQUNFSE9MREVSKQog"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnJldHVyblByZXNzZWQuY29ubmVjdChzZWxmLl9zZW5k"
    "X21lc3NhZ2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAg"
    "ICAgICAgc2VsZi5fc2VuZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAgICAg"
    "ICBzZWxmLl9zZW5kX2J0bi5zZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQocHJvbXB0"
    "X3N5bSkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQogICAg"
    "ICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0LmFk"
    "ZExheW91dChpbnB1dF9yb3cpCgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2J1aWxk"
    "X3NwZWxsYm9va19wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBR"
    "VkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAw"
    "KQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAg"
    "IHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJz"
    "LnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRTaXplUG9s"
    "aWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAg"
    "ICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQoKICAgICAgICAjIEJ1aWxk"
    "IERpYWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBldmVuIGJlZm9y"
    "ZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0byB0aGUgd2lkZ2V0"
    "LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKU"
    "gOKUgCBJbnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5faHdf"
    "cGFuZWwgPSBIYXJkd2FyZVBhbmVsKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihz"
    "ZWxmLl9od19wYW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDilIAgUmVjb3JkcyB0"
    "YWIgKHJlYWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiID0gUmVjb3Jkc1RhYigp"
    "CiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRh"
    "YihzZWxmLl9yZWNvcmRzX3RhYiwgIlJlY29yZHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAg"
    "ICAgIyDilIDilIAgVGFza3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90"
    "YXNrc190YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3NfcHJvdmlkZXI9c2VsZi5fZmls"
    "dGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW49"
    "c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIG9uX2NvbXBsZXRl"
    "X3NlbGVjdGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX2Nh"
    "bmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25f"
    "dG9nZ2xlX2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3MsCiAgICAg"
    "ICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0ZWRfdGFza3MsCiAg"
    "ICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQs"
    "CiAgICAgICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xl"
    "X2ZpcnN0LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90YXNrX2Vk"
    "aXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFn"
    "X3RhYi5sb2csCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21w"
    "bGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl90YXNrc190YWJf"
    "aW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190YWIsICJUYXNrcyIp"
    "CiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2tzVGFiIGF0"
    "dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihj"
    "ZmdfcGF0aCgic2wiKSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zbF9z"
    "Y2FucywgIlNMIFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigp"
    "CiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29tbWFuZHMsICJTTCBD"
    "b21tYW5kcyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIoKQogICAgICAg"
    "IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAiSm9iIFRyYWNrZXIi"
    "KQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29u"
    "cykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9sZXNzb25zX3RhYiwgIkxl"
    "c3NvbnMiKQoKICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVhIGFsb25n"
    "c2lkZSB0aGUgcGVyc29uYSBjaGF0IHRhYgogICAgICAgICMgS2VlcCBhIFNlbGZUYWIgaW5zdGFu"
    "Y2UgZm9yIGlkbGUgY29udGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBT"
    "ZWxmVGFiKCkKCiAgICAgICAgIyDilIDilIAgTW9kdWxlIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlbGYuX21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tlclRhYigpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJNb2R1bGVzIikK"
    "CiAgICAgICAgIyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAiRGlhZ25vc3RpY3Mi"
    "KQoKICAgICAgICByaWdodF93b3Jrc3BhY2UgPSBRV2lkZ2V0KCkKICAgICAgICByaWdodF93b3Jr"
    "c3BhY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0"
    "X3dvcmtzcGFjZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "cmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHJpZ2h0X3dvcmtz"
    "cGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NwZWxsX3RhYnMsIDEpCgogICAgICAgIGNhbGVu"
    "ZGFyX2xhYmVsID0gUUxhYmVsKCLinacgQ0FMRU5EQVIiKQogICAgICAgIGNhbGVuZGFyX2xhYmVs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6"
    "IDEwcHg7IGxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChj"
    "YWxlbmRhcl9sYWJlbCkKCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQgPSBNaW5pQ2FsZW5k"
    "YXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U2l6"
    "ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAg"
    "ICAgICAgUVNpemVQb2xpY3kuUG9saWN5Lk1heGltdW0KICAgICAgICApCiAgICAgICAgc2VsZi5j"
    "YWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdodCgyNjApCiAgICAgICAgc2VsZi5jYWxlbmRh"
    "cl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luc2VydF9jYWxlbmRhcl9k"
    "YXRlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuY2FsZW5k"
    "YXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkU3RyZXRjaCgw"
    "KQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFjZSwgMSkKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSByaWdodC1zaWRlIGNhbGVu"
    "ZGFyIHJlc3RvcmVkIChwZXJzaXN0ZW50IGxvd2VyLXJpZ2h0IHNlY3Rpb24pLiIsCiAgICAgICAg"
    "ICAgICJJTkZPIgogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICJbTEFZT1VUXSBwZXJzaXN0ZW50IG1pbmkgY2FsZW5kYXIgcmVzdG9yZWQvY29uZmlybWVk"
    "IChhbHdheXMgdmlzaWJsZSBsb3dlci1yaWdodCkuIiwKICAgICAgICAgICAgIklORk8iCiAgICAg"
    "ICAgKQogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICAjIOKUgOKUgCBTVEFSVFVQIFNFUVVFTkNF"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ZGVmIF9zdGFydHVwX3NlcXVlbmNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5k"
    "X2NoYXQoIlNZU1RFTSIsIGYi4pymIHtBUFBfTkFNRX0gQVdBS0VOSU5HLi4uIikKICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge1JVTkVTfSDinKYiKQoKICAgICAgICAj"
    "IExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAgIGJvb3RfbG9nID0gU0NSSVBUX0RJUiAvICJsb2dz"
    "IiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBpZiBib290X2xvZy5leGlzdHMoKToKICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbXNncyA9IGJvb3RfbG9nLnJlYWRfdGV4dChl"
    "bmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZ19tYW55KG1zZ3MpCiAgICAgICAgICAgICAgICBib290X2xvZy51bmxpbmsoKSAgIyBj"
    "b25zdW1lZAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFz"
    "cwoKICAgICAgICAjIEhhcmR3YXJlIGRldGVjdGlvbiBtZXNzYWdlcwogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdldF9kaWFnbm9zdGljcygpKQoKICAgICAg"
    "ICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBjcml0aWNhbCA9IERlcGVuZGVuY3lDaGVj"
    "a2VyLmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShkZXBfbXNncykKCiAg"
    "ICAgICAgIyBMb2FkIHBhc3Qgc3RhdGUKICAgICAgICBsYXN0X3N0YXRlID0gc2VsZi5fc3RhdGUu"
    "Z2V0KCJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIiwiIikKICAgICAgICBpZiBsYXN0X3N0YXRl"
    "OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTVEFS"
    "VFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5GTyIKICAgICAgICAg"
    "ICAgKQoKICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5f"
    "YXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9uaW5nIHtERUNLX05BTUV9"
    "J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAg"
    "ICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAg"
    "ICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBtOiBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9y"
    "LmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1Ii"
    "LCBlKSkKICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29u"
    "X2xvYWRfY29tcGxldGUpCiAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2Vs"
    "Zi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVu"
    "ZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBkZWYgX29u"
    "X2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBpZiBz"
    "dWNjZXNzOgogICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAg"
    "IHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRF"
    "bmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1"
    "ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAgICAg"
    "IyBNZWFzdXJlIFZSQU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBpZiBO"
    "Vk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJhbV9iYXNlbGlu"
    "ZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAg"
    "cGFzcwoKICAgICAgICAgICAgIyBWYW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAgICAgIGlm"
    "IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAgICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9z"
    "dGF0ZSgpCiAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncyA9IF9zdGF0ZV9ncmVldGluZ3Nf"
    "bWFwKCkKICAgICAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KAogICAgICAgICAgICAgICAg"
    "ICAgICJTWVNURU0iLAogICAgICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzLmdldChzdGF0"
    "ZSwgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUuIikKICAgICAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgIyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVjdGlvbiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBJZiB0aGVyZSdzIGEgcHJldmlvdXMgc2h1"
    "dGRvd24gcmVjb3JkZWQsIGluamVjdCBjb250ZXh0CiAgICAgICAgICAgICMgc28gTW9yZ2FubmEg"
    "Y2FuIGdyZWV0IHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHNoZSBzbGVwdAogICAgICAgICAg"
    "ICBRVGltZXIuc2luZ2xlU2hvdCg4MDAsIHNlbGYuX3NlbmRfd2FrZXVwX3Byb21wdCkKICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJFUlJPUiIpCiAgICAgICAgICAg"
    "IHNlbGYuX21pcnJvci5zZXRfZmFjZSgicGFuaWNrZWQiKQoKICAgIGRlZiBfZm9ybWF0X2VsYXBz"
    "ZWQoc2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgICAgICAiIiJGb3JtYXQgZWxhcHNl"
    "ZCBzZWNvbmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0aW9uLiIiIgogICAgICAgIGlmIHNlY29u"
    "ZHMgPCA2MDoKICAgICAgICAgICAgcmV0dXJuIGYie2ludChzZWNvbmRzKX0gc2Vjb25keydzJyBp"
    "ZiBzZWNvbmRzICE9IDEgZWxzZSAnJ30iCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAg"
    "ICAgICAgICAgbSA9IGludChzZWNvbmRzIC8vIDYwKQogICAgICAgICAgICBzID0gaW50KHNlY29u"
    "ZHMgJSA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie219IG1pbnV0ZXsncycgaWYgbSAhPSAxIGVs"
    "c2UgJyd9IiArIChmIiB7c31zIiBpZiBzIGVsc2UgIiIpCiAgICAgICAgZWxpZiBzZWNvbmRzIDwg"
    "ODY0MDA6CiAgICAgICAgICAgIGggPSBpbnQoc2Vjb25kcyAvLyAzNjAwKQogICAgICAgICAgICBt"
    "ID0gaW50KChzZWNvbmRzICUgMzYwMCkgLy8gNjApCiAgICAgICAgICAgIHJldHVybiBmIntofSBo"
    "b3VyeydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsgKGYiIHttfW0iIGlmIG0gZWxzZSAiIikKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNlY29uZHMgLy8gODY0MDApCiAgICAgICAg"
    "ICAgIGggPSBpbnQoKHNlY29uZHMgJSA4NjQwMCkgLy8gMzYwMCkKICAgICAgICAgICAgcmV0dXJu"
    "IGYie2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9IiArIChmIiB7aH1oIiBpZiBoIGVsc2Ug"
    "IiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAgICAgICAi"
    "IiJTZW5kIGhpZGRlbiB3YWtlLXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9hZHMuIiIi"
    "CiAgICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93biIp"
    "CiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVybiAgIyBGaXJz"
    "dCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMgQ2Fs"
    "Y3VsYXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQg"
    "PSBkYXRldGltZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19k"
    "dCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21w"
    "YXJpc29uCiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxh"
    "Y2UodHppbmZvPU5vbmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRk"
    "b3duX2R0KS50b3RhbF9zZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9m"
    "b3JtYXRfZWxhcHNlZChlbGFwc2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICBlbGFwc2VkX3N0ciA9ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdl"
    "dCBzdG9yZWQgZmFyZXdlbGwgYW5kIGxhc3QgY29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9"
    "IHNlbGYuX3N0YXRlLmdldCgibGFzdF9mYXJld2VsbCIsICIiKQogICAgICAgIGxhc3RfY29udGV4"
    "dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAg"
    "ICMgQnVpbGQgd2FrZS11cCBwcm9tcHQKICAgICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAg"
    "ICBpZiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBm"
    "aW5hbCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW9uOlxuIgogICAgICAgICAgICBmb3IgaXRl"
    "bSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBzcGVha2VyID0gaXRlbS5nZXQoInJv"
    "bGUiLCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQgICAgPSBpdGVtLmdl"
    "dCgiY29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICAgY29udGV4dF9ibG9jayArPSBm"
    "IntzcGVha2VyfToge3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gIiIKICAgICAg"
    "ICBpZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSBmIlxuXG5Zb3VyIGZp"
    "bmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3ZWxsfVwiIgoKICAg"
    "ICAgICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1c3QgYmVlbiBy"
    "ZWFjdGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgICAgICAgICAg"
    "ZiJ7ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKICAgICAg"
    "ICAgICAgZiJcbkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHlv"
    "dSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qg"
    "c2FpZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcg"
    "d2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAg"
    "KQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRf"
    "aGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNv"
    "bnRlbnQiOiB3YWtldXBfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29y"
    "a2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBo"
    "aXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3dh"
    "a2V1cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVl"
    "CiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQog"
    "ICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNl"
    "X2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAg"
    "ICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7"
    "ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVk"
    "LmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVwIHByb21wdCBza2lw"
    "cGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAg"
    "ICApCgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "IiIiCiAgICAgICAgRm9yY2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUg"
    "ZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3NpbmcvaW52YWxp"
    "ZCwgdGhlIGJyb3dzZXIgT0F1dGggZmxvdyBvcGVucyBuYXR1cmFsbHkuCiAgICAgICAgIiIiCiAg"
    "ICAgICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dB"
    "Uk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxh"
    "YmxlLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICBp"
    "ZiBHT09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4i"
    "KQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5fZ2NhbCBvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29n"
    "bGUgYXV0aCBza2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4i"
    "LAogICAgICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgcmV0dXJuCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NU"
    "QVJUVVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2suIiwgIklORk8iKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVd"
    "W1NUQVJUVVBdIGNyZWRlbnRpYWxzPXtzZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAg"
    "ICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYu"
    "X2djYWwudG9rZW5fcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgICAgIHNlbGYuX2djYWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIENhbGVuZGFyIGF1dGggcmVhZHkuIiwg"
    "Ik9LIikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5lbnN1cmVfc2VydmljZXMoKQogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIERyaXZlL0RvY3MgYXV0"
    "aCByZWFkeS4iLCAiT0siKQogICAgICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRy"
    "dWUKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gU2No"
    "ZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAg"
    "ICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9j"
    "cykKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gUG9z"
    "dC1hdXRoIHRhc2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAgICAgICAgICBzZWxm"
    "Ll9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGluYm91bmQgc3luYyB0"
    "cmlnZ2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50"
    "ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1"
    "ZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09P"
    "R0xFXVtTVEFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1w"
    "b3J0ZWRfY291bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbR09PR0xFXVtTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBf"
    "cmVmcmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "X2N1cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3Rh"
    "dHVzX2xhYmVsLnNldFRleHQoIkxvYWRpbmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfdGFiLnBhdGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUi"
    "KQogICAgICAgIGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9p"
    "ZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAg"
    "IHNlbGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlh"
    "bGl6ZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBw"
    "YXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3Rp"
    "Y2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFy"
    "IHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJ"
    "TUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCBw"
    "b2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAg"
    "ICAgICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1"
    "bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBvbGwg"
    "Y29tcGxldGUg4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIs"
    "ICJFUlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1v"
    "bj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVy"
    "X3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVh"
    "ZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZl"
    "IHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJ"
    "TUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCBy"
    "ZWZyZXNoLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcK"
    "ICAgICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0si"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZ"
    "TkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1U"
    "cnVlKS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikg"
    "LT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAg"
    "ICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rhc2tfZGF0ZV9m"
    "aWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03"
    "KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAg"
    "ICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rh"
    "c2tfZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVs"
    "dGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRl"
    "bHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJb"
    "VEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93"
    "X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9"
    "IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRz"
    "Jyl9IiwgIkRFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRF"
    "Ul0gaG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVC"
    "VUciKQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9p"
    "bnZhbGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3Rh"
    "dHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAg"
    "ICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBs"
    "ZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAg"
    "ICBkdWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAg"
    "ICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFz"
    "a3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMg"
    "Tm9uZToKICAgICAgICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAgICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtG"
    "SUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9e3Rhc2su"
    "Z2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsCiAgICAgICAgICAgICAgICAgICAg"
    "IldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAg"
    "ICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5k"
    "KHRhc2spCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVl"
    "X2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAg"
    "ICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmlsdGVyZWQuc29ydChr"
    "ZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXts"
    "ZW4oZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIs"
    "CiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgog"
    "ICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAg"
    "ICAgICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0"
    "ZV90aW1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAg"
    "ICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0"
    "PSJnb29nbGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAg"
    "ICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRl"
    "IikKICAgICAgICBpZiBkYXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19m"
    "b3JfY29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xlX2V2ZW50"
    "X2RhdGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFy"
    "c2VkCiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9w"
    "YW5lbChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIi"
    "LCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAgICAgICAgICAgdmlzaWJsZV9jb3VudCA9"
    "IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJs"
    "ZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VSUk9SXSByZWZy"
    "ZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0icmVnaXN0cnlf"
    "cmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIHN0b3Bf"
    "ZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAg"
    "ICAgZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtl"
    "ciBjbGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAg"
    "ICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2VsZiwgZmlsdGVy"
    "X2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBzdHIo"
    "ZmlsdGVyX2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rh"
    "c2tfZGF0ZV9maWx0ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVn"
    "aXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90"
    "YXNrX3Nob3dfY29tcGxldGVkCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBs"
    "ZXRlZChzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFz"
    "a19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBs"
    "aXN0W3N0cl06CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlz"
    "IE5vbmU6CiAgICAgICAgICAgIHJldHVybiBbXQogICAgICAgIHJldHVybiBzZWxmLl90YXNrc190"
    "YWIuc2VsZWN0ZWRfdGFza19pZHMoKQoKICAgIGRlZiBfc2V0X3Rhc2tfc3RhdHVzKHNlbGYsIHRh"
    "c2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGlmIHN0"
    "YXR1cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNv"
    "bXBsZXRlKHRhc2tfaWQpCiAgICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAg"
    "ICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jYW5jZWwodGFza19pZCkKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MudXBkYXRlX3N0YXR1cyh0YXNrX2lk"
    "LCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAgICByZXR1cm4gTm9u"
    "ZQoKICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9p"
    "ZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0ZV9ldmVudF9mb3JfdGFzayhn"
    "b29nbGVfZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFT"
    "S1NdW1dBUk5dIEdvb2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza19pZD17dGFza19p"
    "ZH06IHtleH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRfdGFzayhz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2Vs"
    "Zi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3Rh"
    "dHVzKHRhc2tfaWQsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExFVEUgU0VMRUNURUQgYXBwbGll"
    "ZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNr"
    "X3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxl"
    "Y3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFz"
    "a19pZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9u"
    "ZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5"
    "X3BhbmVsKCkKCiAgICBkZWYgX3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJlbW92ZWQgPSBzZWxmLl90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92"
    "ZWR9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3Ry"
    "eV9wYW5lbCgpCgogICAgZGVmIF9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0"
    "ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJf"
    "dGFza3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3Rh"
    "Yi5zZXRfc3RhdHVzKHRleHQsIG9rPW9rKQoKICAgIGRlZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFi"
    "IiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93X2xvY2FsID0g"
    "ZGF0ZXRpbWUubm93KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEo"
    "bWludXRlcz0zMCkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbmFtZS5zZXRU"
    "ZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNl"
    "dFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tz"
    "X3RhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIl"
    "SDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRU"
    "ZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190"
    "YWIudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVIOiVN"
    "IikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4"
    "dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4"
    "dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRU"
    "ZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNldENo"
    "ZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmln"
    "dXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxz"
    "ZSkKICAgICAgICBzZWxmLl90YXNrc190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2Vf"
    "dGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihz"
    "ZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90"
    "YXNrc190YWIuY2xvc2VfZWRpdG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2UoKQoKICAgIGRlZiBfcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDog"
    "c3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxsX2RheTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2Up"
    "OgogICAgICAgIGRhdGVfdGV4dCA9IChkYXRlX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0"
    "aW1lX3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IGRhdGVf"
    "dGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBhbGxfZGF5OgogICAgICAg"
    "ICAgICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBtaW51dGUgPSA1OSBp"
    "ZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYi"
    "e2RhdGVfdGV4dH0ge2hvdXI6MDJkfTp7bWludXRlOjAyZH0iLCAiJVktJW0tJWQgJUg6JU0iKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2Rh"
    "dGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIG5vcm1hbGl6"
    "ZWQgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0PSJ0YXNr"
    "X2VkaXRvcl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICBmIltUQVNLU11bRURJVE9SXSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9LCBhbGxf"
    "ZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGltZV90"
    "ZXh0fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25l"
    "J30iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxp"
    "emVkCgogICAgZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAg"
    "IGlmIHRhYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50"
    "YXNrX2VkaXRvcl9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNr"
    "X2VkaXRvcl9hbGxfZGF5LmlzQ2hlY2tlZCgpCiAgICAgICAgc3RhcnRfZGF0ZSA9IHRhYi50YXNr"
    "X2VkaXRvcl9zdGFydF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRh"
    "Yi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUg"
    "PSB0YWIudGFza19lZGl0b3JfZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGlt"
    "ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfdGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdGVz"
    "ID0gdGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgIGxv"
    "Y2F0aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQoKS5zdHJpcCgpCiAgICAgICAg"
    "cmVjdXJyZW5jZSA9IHRhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgog"
    "ICAgICAgIGlmIG5vdCB0aXRsZToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0"
    "YXR1cygiVGFzayBOYW1lIGlzIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBub3QgZW5kX2RhdGUgb3IgKG5vdCBhbGxf"
    "ZGF5IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1lKSk6CiAgICAgICAgICAgIHNl"
    "bGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZCBkYXRlIGFuZCB0aW1lIGFyZSBy"
    "ZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShzdGFydF9kYXRl"
    "LCBzdGFydF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9"
    "IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShlbmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXks"
    "IGlzX2VuZD1UcnVlKQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQgb3Igbm90IGVuZF9kdDoK"
    "ICAgICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZhaWxlZCIp"
    "CiAgICAgICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQg"
    "ZGF0ZXRpbWUuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJ"
    "bnZhbGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBISDpNTS4iLCBvaz1G"
    "YWxzZSkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9n"
    "ZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBwYXlsb2FkID0geyJzdW1tYXJ5Ijog"
    "dGl0bGV9CiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9"
    "IHsiZGF0ZSI6IHN0YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAgICAgICAgICAgcGF5bG9h"
    "ZFsiZW5kIl0gPSB7ImRhdGUiOiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0YShkYXlzPTEpKS5p"
    "c29mb3JtYXQoKX0KICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0g"
    "eyJkYXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXlsb2Fk"
    "WyJlbmQiXSA9IHsiZGF0ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9y"
    "bWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYg"
    "bm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbImRlc2NyaXB0aW9uIl0gPSBub3RlcwogICAgICAg"
    "IGlmIGxvY2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJdID0gbG9jYXRpb24K"
    "ICAgICAgICBpZiByZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiBy"
    "ZWN1cnJlbmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgiUlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1"
    "cnJlbmNlfSIKICAgICAgICAgICAgcGF5bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1bGVdCgogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdGFy"
    "dCBmb3IgdGl0bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IGV2ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5jcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBheWxv"
    "YWQsIGNhbGVuZGFyX2lkPSJwcmltYXJ5IikKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNr"
    "cy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiBm"
    "InRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImNyZWF0ZWRf"
    "YXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAiZHVlX2F0Ijogc3RhcnRfZHQu"
    "aXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAicHJlX3RyaWdn"
    "ZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAgICAg"
    "ICAgInN0YXR1cyI6ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQi"
    "OiBOb25lLAogICAgICAgICAgICAgICAgInJldHJ5X2NvdW50IjogMCwKICAgICAgICAgICAgICAg"
    "ICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9h"
    "dCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAogICAgICAg"
    "ICAgICAgICAgInNvdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50"
    "X2lkIjogZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwK"
    "ICAgICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAg"
    "ICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFz"
    "a19lZGl0b3JfZ29vZ2xlX2ZpcnN0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3Rl"
    "cywKICAgICAgICAgICAgICAgICAgICAic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlz"
    "b2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5"
    "IjogYm9vbChhbGxfZGF5KSwKICAgICAgICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlv"
    "biwKICAgICAgICAgICAgICAgICAgICAicmVjdXJyZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAg"
    "ICAgICAgICB9LAogICAgICAgICAgICB9CiAgICAgICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQog"
    "ICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3VjY2VlZGVkIGFuZCB0YXNrIHJl"
    "Z2lzdHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNr"
    "X3JlZ2lzdHJ5X3BhbmVsKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3VjY2VzcyBmb3IgdGl0bGU9"
    "J3t0aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICAgICAiT0siLAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fc2V0"
    "X3Rhc2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZhbHNl"
    "KQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNL"
    "U11bRURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0n"
    "OiB7ZXh9IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9j"
    "YWxlbmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3Rl"
    "eHQgPSBxZGF0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9"
    "ICJub25lIgoKICAgICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQo"
    "KQogICAgICAgIGRpcmVjdF90YXJnZXRzID0gWwogICAgICAgICAgICAoInRhc2tfZWRpdG9yX3N0"
    "YXJ0X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRh"
    "c2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3Jf"
    "ZW5kX2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRh"
    "c2tfZWRpdG9yX2VuZF9kYXRlIiwgTm9uZSkpLAogICAgICAgIF0KICAgICAgICBmb3IgbmFtZSwg"
    "d2lkZ2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAgICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5v"
    "bmUgYW5kIGZvY3VzX3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAgICAgICAgICB3aWRnZXQuc2V0"
    "VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQogICAg"
    "ICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgcm91dGVkX3RhcmdldCA9PSAibm9uZSI6CiAg"
    "ICAgICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIpIGFuZCBzZWxmLl9pbnB1"
    "dF9maWVsZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdldCBpcyBz"
    "ZWxmLl9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5p"
    "bnNlcnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5w"
    "dXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAg"
    "ICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihz"
    "ZWxmLCAiX3Rhc2tzX3RhYiIpIGFuZCBzZWxmLl90YXNrc190YWIgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkNhbGVuZGFyIGRh"
    "dGUgc2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2Rp"
    "YWdfdGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRh"
    "ciBjbGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0u"
    "IiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dv"
    "b2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNl"
    "KToKICAgICAgICAiIiIKICAgICAgICBTeW5jIEdvb2dsZSBDYWxlbmRhciBldmVudHMg4oaSIGxv"
    "Y2FsIHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBBUEkuCgogICAgICAgIFN0YWdlIDEg"
    "KGZpcnN0IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3luY1Rva2VuLgog"
    "ICAgICAgIFN0YWdlIDIgKGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVz"
    "aW5nIHN0b3JlZCBzeW5jVG9rZW4g4oCUCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgcmV0dXJucyBPTkxZIHdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAg"
    "ICAgICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZhbGxzIGJh"
    "Y2sgdG8gZnVsbCBzeW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFu"
    "ZCBub3QgYm9vbChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJs"
    "ZWQiLCBUcnVlKSk6CiAgICAgICAgICAgIHJldHVybiAwCgogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgbm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rh"
    "c2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7CiAgICAgICAg"
    "ICAgICAgICAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAg"
    "ICAgICAgICAgICBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgaWYgKHQuZ2V0KCJnb29n"
    "bGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICB9CgogICAgICAgICAgICAj"
    "IOKUgOKUgCBGZXRjaCBmcm9tIEdvb2dsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RvcmVk"
    "X3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIpCgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5vdCBm"
    "b3JjZV9vbmNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEluY3JlbWVudGFsIHN5bmMgKHN5bmNU"
    "b2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAg"
    "IHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVu"
    "dHMoCiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAg"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtT"
    "WU5DXSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5y"
    "ZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93"
    "X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmlt"
    "YXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAg"
    "ICAgICAgICAgICAgICAgICApCgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9l"
    "eDoKICAgICAgICAgICAgICAgIGlmICI0MTAiIGluIHN0cihhcGlfZXgpIG9yICJHb25lIiBpbiBz"
    "dHIoYXBpX2V4KToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEw"
    "KSDigJQgZnVsbCByZXN5bmMuIiwgIldBUk4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3N0YXRlLnBvcCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4i"
    "LCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5y"
    "ZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93"
    "X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmlt"
    "YXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAg"
    "ICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAg"
    "ICAgIHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2ZW50KHMp"
    "LiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2VuIGZv"
    "ciBuZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3N0YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4"
    "dF90b2tlbgogICAgICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3Rh"
    "dGUpCgogICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3Zl"
    "ZF9jb3VudCA9IDAKICAgICAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3Ig"
    "ZXZlbnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2ZW50"
    "LmdldCgiaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lk"
    "OgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVk"
    "IC8gY2FuY2VsbGVkIG9uIEdvb2dsZSdzIHNpZGUKICAgICAgICAgICAgICAgIGlmIGV2ZW50Lmdl"
    "dCgic3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAgICAgICAgZXhpc3Rpbmcg"
    "PSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYg"
    "ZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwg"
    "ImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3RhdHVzIl0g"
    "ICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJj"
    "YW5jZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sic3luY19zdGF0dXMiXSAgICA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pWyJnb29nbGVfZGVs"
    "ZXRlZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3ZlZF9j"
    "b3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4dCcsJz8n"
    "KX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnki"
    "KSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFy"
    "IEV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVf"
    "ZGF0ZXRpbWUoZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50"
    "X2lkLmdldChldmVudF9pZCkKCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAg"
    "ICAgICAgICAgICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBjaGFuZ2VkCiAgICAgICAgICAgICAgICAg"
    "ICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBpZiAoZXhpc3Rpbmcu"
    "Z2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAg"
    "dGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZHVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQoImR1ZV9hdCIp"
    "ICE9IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0"
    "Il0gICAgICAgPSBkdWVfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "cHJlX3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2No"
    "YW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0"
    "YXR1cyIpICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3lu"
    "Y19zdGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdl"
    "ZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNrX2NoYW5nZWQ6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAg"
    "ICAgICAgICAgICAgICAgICB1cGRhdGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBVcGRhdGVk"
    "OiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgICAgICAg"
    "ICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAgICJp"
    "ZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19pc28sCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjog"
    "ICAgICAgKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAg"
    "c3VtbWFyeSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAgInBl"
    "bmRpbmciLAogICAgICAgICAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogICBOb25l"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAicHJlX2Fubm91bmNlZCI6ICAgICBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "InNvdXJjZSI6ICAgICAgICAgICAgImdvb2dsZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJn"
    "b29nbGVfZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAgICAgICAic3luY2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rf"
    "c3luY2VkX2F0IjogICAgbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgIm1ldGFkYXRh"
    "IjogewogICAgICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9pbXBvcnRlZF9hdCI6IG5v"
    "d19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAgICAg"
    "ZXZlbnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAgICAgICAgICAgICAgIH0sCiAgICAgICAg"
    "ICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwcGVuZChuZXdfdGFzaykK"
    "ICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtldmVudF9pZF0gPSBuZXdfdGFz"
    "awogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAg"
    "ICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIpCgogICAgICAg"
    "ICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZ"
    "TkNdIERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAg"
    "ZiJ1cGRhdGVkPXt1cGRhdGVkX2NvdW50fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZP"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAoKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbR09PR0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVy"
    "biAwCgoKICAgIGRlZiBfbWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYi"
    "W1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2VsZi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIK"
    "ICAgICAgICAgICAgICAgICAgICBmIih7REVDS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIK"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNTQUdFIEhBTkRMSU5HIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZW5kX21lc3Nh"
    "Z2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNl"
    "bGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0"
    "ZXh0OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBj"
    "aGF0IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX21haW5fdGFi"
    "cy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3Vy"
    "cmVudEluZGV4KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAg"
    "c2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4"
    "dCkKCiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGlt"
    "bWVkaWF0ZWx5CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNl"
    "bGYuX2ZhY2VfdGltZXJfbWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHBy"
    "b21wdCB3aXRoIHZhbXBpcmUgY29udGV4dCArIG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGly"
    "ZV9jdHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBz"
    "ZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4"
    "ICA9ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAg"
    "ICAgICAgICAgIGpvdXJuYWxfY3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2Nv"
    "bnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRl"
    "CiAgICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lz"
    "dGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAg"
    "ICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoK"
    "ICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVt"
    "ICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFkamFj"
    "ZW50IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJs"
    "c2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxh"
    "bmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxzZSAiUHl0aG9uIgogICAgICAg"
    "ICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3JfbGFuZ3Vh"
    "Z2UobGFuZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0"
    "ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21p"
    "c3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Np"
    "b25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICJz"
    "b21lIHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5b"
    "UkVUVVJOIEZST00gVE9SUE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jw"
    "b3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5nX3RyYW5zbWlz"
    "c2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcg"
    "dGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAg"
    "ICAgICAgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNw"
    "ZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMu"
    "Z2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5k"
    "X2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJs"
    "ZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAg"
    "ICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgaWYgc2VsZi5fc2No"
    "ZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24i"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICAjIExhdW5jaCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3Ry"
    "ZWFtaW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3Rvcnks"
    "IG1heF90b2tlbnM9NTEyCiAgICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFk"
    "eS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNlbGYuX3dvcmtlci5yZXNwb25zZV9k"
    "b25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIu"
    "ZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3Jr"
    "ZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYu"
    "X2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3Jl"
    "IGZpcnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX2JlZ2lu"
    "X3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0"
    "ZSB0aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWlu"
    "ZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZpcnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQg"
    "dG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1lc3RhbXAgPSBk"
    "YXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNw"
    "ZWFrZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2VucwogICAgICAg"
    "ICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rp"
    "c3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFu"
    "PicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2Vp"
    "Z2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+"
    "ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxhaW5U"
    "ZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92"
    "ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3Io"
    "Y3Vyc29yKQoKICAgIGRlZiBfb25fdG9rZW4oc2VsZiwgdG9rZW46IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAg"
    "ICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9y"
    "ZXNwb25zZSgpCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBj"
    "dXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1v"
    "dmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNw"
    "bGF5Lmluc2VydFBsYWluVGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVy"
    "dGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBfb25fcmVz"
    "cG9uc2VfZG9uZShzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJl"
    "IHJlc3BvbnNlIGlzIG9uIGl0cyBvd24gbGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRf"
    "ZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vy"
    "c29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0"
    "Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0"
    "KCJcblxuIikKCiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2Vs"
    "Zi5fdG9rZW5fY291bnQgKz0gbGVuKHJlc3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vz"
    "c2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21l"
    "bW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9u"
    "c2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwg"
    "IiIsIHJlc3BvbnNlKQoKICAgICAgICAjIFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBpZiBz"
    "ZWxmLl9ibG9vZF9zcGhlcmUgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2Jsb29kX3Nw"
    "aGVyZS5zZXRGaWxsKAogICAgICAgICAgICAgICAgbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQg"
    "LyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAgIyBSZS1lbmFibGUgaW5wdXQKICAgICAg"
    "ICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmll"
    "bGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkK"
    "CiAgICAgICAgIyBSZXN1bWUgaWRsZSB0aW1lcgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBh"
    "bmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMg"
    "U2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGlt"
    "ZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2Up"
    "KQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJl"
    "c3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxm"
    "Ll9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRl"
    "ZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBz"
    "ZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0"
    "X2ZhY2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQog"
    "ICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3Rp"
    "bWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVS"
    "Uk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNU"
    "RU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYg"
    "c3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29u"
    "PSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9"
    "PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGlu"
    "ZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hl"
    "cmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFi"
    "bGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAg"
    "ICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFV"
    "VE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAg"
    "ICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikg"
    "LT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQ"
    "T1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcu"
    "IikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9k"
    "ZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAg"
    "ICAgICAgIGlmIFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlf"
    "Y2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4i"
    "LCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2Rl"
    "bCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAg"
    "c2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVz"
    "KCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9y"
    "cG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9u"
    "CiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0"
    "aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRl"
    "ZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAg"
    "ICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlm"
    "IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9k"
    "ZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0"
    "aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMu"
    "IFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIp"
    "CiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAg"
    "c2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltUT1JQT1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIs"
    "ICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxv"
    "YWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgi"
    "U1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1F"
    "fSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVk"
    "X2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIg"
    "PSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2Fk"
    "ZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5l"
    "Y3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwg"
    "ZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5f"
    "b25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5l"
    "Y3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhy"
    "ZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQo"
    "KQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRv"
    "cnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVy"
    "bmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVk"
    "IOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAg"
    "ICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZt"
    "bC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91"
    "c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRv"
    "dGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwg"
    "PiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYu"
    "X3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMg"
    "QWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAg"
    "IHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fdnJh"
    "bV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1"
    "cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAg"
    "ICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAg"
    "ICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3Rp"
    "Y2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g"
    "4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQg"
    "YWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9y"
    "cG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVs"
    "aWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRp"
    "bmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIs"
    "IEZhbHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRv"
    "X3dha2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90"
    "aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9d"
    "IFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA"
    "4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3Jv"
    "dW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJt"
    "aXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBv"
    "cnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVs"
    "ZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBh"
    "bmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0"
    "b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50"
    "ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgog"
    "ICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAg"
    "ICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9w"
    "cmVzc3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVj"
    "ayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg"
    "4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRp"
    "bmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdb"
    "InNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRl"
    "cnZhbCA9IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50"
    "ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5z"
    "bWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgTW9vbiB3aWRnZXQgcmVmcmVzaCAoZXZlcnkg"
    "NiBob3VycykKICAgICAgICBpZiBzZWxmLl9tb29uX3dpZGdldCBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgICAgICBzZWxmLl9tb29u"
    "X3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYs"
    "IGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVs"
    "ZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hp"
    "Y2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAg"
    "ICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAg"
    "ICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0"
    "YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2"
    "aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBi"
    "ZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmlu"
    "ZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlm"
    "IHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBz"
    "dGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVf"
    "dHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVS"
    "XSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBl"
    "cnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAg"
    "c2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAg"
    "ICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNl"
    "bGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9u"
    "IHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIp"
    "CgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkci"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90"
    "IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91"
    "Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlz"
    "c2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAg"
    "ICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsi"
    "REVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHgg"
    "PSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9u"
    "cy5nZXRfaGlzdG9yeSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigK"
    "ICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNF"
    "LAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgICAg"
    "IHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9p"
    "ZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFi"
    "IGFuZCBhcHBlbmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJ"
    "bmRleCgxKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIp"
    "CiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBm"
    "JzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAg"
    "ICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoK"
    "ICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25f"
    "aWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25u"
    "ZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJS"
    "T1JdIHtlfSIsICJFUlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0"
    "YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0"
    "ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nl"
    "c3Npb25fYXNfY29udGV4dChkYXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNz"
    "aW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRl"
    "ZChkYXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pP"
    "VVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0LiAiCiAgICAg"
    "ICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0aW9uLiIs"
    "ICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAg"
    "ICAgICAgIGYiQSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVu"
    "cyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAg"
    "ICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAgICAgICAgICAg"
    "ICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5hbCBm"
    "cm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmll"
    "Zmx5IOKAlCB5b3Ugbm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhh"
    "dCBjb252ZXJzYXRpb24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25z"
    "LmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNz"
    "aW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pv"
    "dXJuYWwoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29u"
    "dGV4dCBjbGVhcmVkLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVN"
    "IiwKICAgICAgICAgICAgIlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1h"
    "aW5zLiIKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVm"
    "IF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUu"
    "dGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAv"
    "LyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNz"
    "aW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogICAgICAgIHNlbGYuX2h3X3Bh"
    "bmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAgICAgICAg"
    "ICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAgICAg"
    "IHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIE1BTkEg"
    "c3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9tYW5hX3NwaGVyZSBp"
    "cyBub3QgTm9uZSBhbmQgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9o"
    "YW5kbGUpCiAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAg"
    "ICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAg"
    "ICAgICBtYW5hX2ZpbGwgPSBtYXgoMC4wLCAxLjAgLSAodnJhbV91c2VkIC8gdnJhbV90b3QpKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5fbWFuYV9zcGhlcmUuc2V0RmlsbChtYW5hX2ZpbGwsIGF2YWls"
    "YWJsZT1UcnVlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fbWFuYV9zcGhlcmUuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKCiAgICAgICAg"
    "IyBIVU5HRVIgPSBpbnZlcnNlIG9mIGJsb29kCiAgICAgICAgYmxvb2RfZmlsbCA9IG1pbigxLjAs"
    "IHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAgICAgIGh1bmdlciAgICAgPSAxLjAgLSBi"
    "bG9vZF9maWxsCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYu"
    "X2h1bmdlcl9nYXVnZS5zZXRWYWx1ZShodW5nZXIgKiAxMDAsIGYie2h1bmdlcioxMDA6LjBmfSUi"
    "KQoKICAgICAgICAjIFZJVEFMSVRZID0gUkFNIGZyZWUKICAgICAgICBpZiBQU1VUSUxfT0s6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1lbSAgICAgICA9IHBzdXRpbC52aXJ0dWFs"
    "X21lbW9yeSgpCiAgICAgICAgICAgICAgICB2aXRhbGl0eSAgPSAxLjAgLSAobWVtLnVzZWQgLyBt"
    "ZW0udG90YWwpCiAgICAgICAgICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl92aXRhbGl0eV9nYXVnZS5zZXRWYWx1ZSgKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgdml0YWxpdHkgKiAxMDAsIGYie3ZpdGFsaXR5KjEwMDouMGZ9JSIKICAgICAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAg"
    "ICBwYXNzCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFU"
    "IERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwg"
    "dGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6"
    "ICAgICBDX0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAg"
    "ICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09E"
    "LAogICAgICAgIH0KICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAg"
    "ICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAog"
    "ICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENf"
    "QkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2Vy"
    "LCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIs"
    "IENfR09MRF9ESU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGlt"
    "ZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAgICAg"
    "ICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHls"
    "ZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAg"
    "IGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0i"
    "Y29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAg"
    "ICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEw"
    "cHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJv"
    "bGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAg"
    "ICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAg"
    "ICAgICAgICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNw"
    "b25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05B"
    "TUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAg"
    "ICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAg"
    "ICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0o"
    "KQogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAg"
    "ICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklN"
    "U09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAiRVJS"
    "T1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMSU5FIjogICAgQ19CTE9PRCwKICAg"
    "ICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAgfQogICAgICAgIGNv"
    "bG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jw"
    "b3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9S"
    "IiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQo"
    "dG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQog"
    "ICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIg"
    "PSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBz"
    "ZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxm"
    "Ll9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNl"
    "dFRleHQoCiAgICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAg"
    "ICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25f"
    "aWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJz"
    "ZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0"
    "bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBz"
    "ZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsn"
    "IzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7"
    "JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJv"
    "cmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQog"
    "ICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlz"
    "c2lvbiBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlz"
    "c2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9y"
    "OiB7ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9n"
    "Z2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVl"
    "bigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19i"
    "dG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsg"
    "Y29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBzZWxmLl9m"
    "c19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJ"
    "TVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAg"
    "ICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAgIGRl"
    "ZiBfdG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2wo"
    "c2VsZi53aW5kb3dGbGFncygpICYgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQog"
    "ICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAg"
    "ICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2lu"
    "ZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1T"
    "T05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1h"
    "bCgpCiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxm"
    "LndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07"
    "ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQt"
    "c2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRf"
    "Y2hhdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hh"
    "dCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "dGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5v"
    "dCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0"
    "X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93"
    "KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9y"
    "dF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4"
    "dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xp"
    "cGJvYXJkCiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQp"
    "CgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAg"
    "IGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlw"
    "Ym9hcmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9w"
    "YXRofSIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAg"
    "ZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZl"
    "bnQua2V5KCkKICAgICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0Yx"
    "MDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5"
    "ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAg"
    "ICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1T"
    "T05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBO"
    "b25lOgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwog"
    "ICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93"
    "bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQg"
    "c2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jk"
    "cy4iIiIKICAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBm"
    "b3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNz"
    "JywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAg"
    "ICAgIyBTaG93IGNvbmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAg"
    "ICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0"
    "aXZhdGU/IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6"
    "ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxi"
    "bCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAg"
    "ICAgICAgICAgIGYie0RFQ0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3Jl"
    "IGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQogICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRv"
    "d24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAg"
    "ICAgIGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4g"
    "KGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5pbXVt"
    "SGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAg"
    "ICAgICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkK"
    "ICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAg"
    "ICAgICBidG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAg"
    "IGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAg"
    "YnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChi"
    "dG5fbm93KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91"
    "dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAg"
    "ICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2Vs"
    "Zi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJs"
    "ZWQoVHJ1ZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAg"
    "ICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2Vs"
    "Zi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAgICAg"
    "ICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93"
    "b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRv"
    "d24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyBy"
    "ZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxs"
    "X3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBk"
    "YXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRz"
    "IGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVz"
    "cG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0"
    "byBzcGVhayBoZXIgZmluYWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxl"
    "ZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3Rvcnko"
    "KQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijog"
    "ZmFyZXdlbGxfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAog"
    "ICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5"
    "LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3du"
    "X3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAg"
    "ICAgICAgICAgIGRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBT"
    "bWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAg"
    "ICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3du"
    "KE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0"
    "IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2Rv"
    "X3NodXRkb3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChz"
    "ZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChf"
    "b25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vy"
    "cm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRf"
    "c3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRl"
    "TGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0"
    "aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5"
    "CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3No"
    "dXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoc2Vs"
    "ZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8g"
    "ZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxm"
    "Ll9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZlbnQpIC0+"
    "IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAg"
    "ICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Np"
    "b25zLnNhdmUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAg"
    "ICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0"
    "b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Np"
    "b25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpd"
    "IGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0"
    "ZVsibGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBt"
    "LmdldCgicm9sZSIsIiIpLCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAg"
    "ICAgICAgICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAg"
    "ICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxs"
    "CiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9u"
    "c2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3No"
    "dXRkb3duX2ZhcmV3ZWxsX3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgog"
    "ICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAg"
    "ICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJld2VsbCJd"
    "ID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVb"
    "Imxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAg"
    "ICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfbm93X2lz"
    "bygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIl0g"
    "ID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0"
    "ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CgogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2No"
    "ZWR1bGVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93"
    "bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0"
    "ZG93bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQu"
    "c3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAg"
    "ICAgUUFwcGxpY2F0aW9uLnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5"
    "IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVu"
    "ZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sg"
    "Zm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVu"
    "OgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4g"
    "YmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBm"
    "b2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAg"
    "ICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAg"
    "ICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlv"
    "bgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1"
    "c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFw"
    "cGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0"
    "aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBs"
    "aWNhdGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBi"
    "b290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVl"
    "ZGVkIGZvciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBw"
    "bGljYXRpb24iKQogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFw"
    "cGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVy"
    "IE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwg"
    "c3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNz"
    "YWdlX2hhbmRsZXIoKQogICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVk"
    "LCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJz"
    "dCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBU"
    "cnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygp"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAg"
    "ICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9t"
    "IGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERl"
    "dGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "ICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBz"
    "Y3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0"
    "aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNL"
    "X05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9"
    "VHJ1ZSkKCiAgICAgICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9p"
    "bnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIi"
    "XSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAg"
    "ICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAg"
    "ICAgICJzb3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAg"
    "ICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAg"
    "ICAic2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAg"
    "ICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhw"
    "b3J0cyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dz"
    "IjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMi"
    "OiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMi"
    "OiBzdHIobW9yZ2FubmFfaG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjog"
    "ICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2Nm"
    "Z1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9o"
    "b21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAg"
    "InRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29u"
    "IiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAg"
    "ICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMu"
    "Y29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5n"
    "b29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5n"
    "b29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfQog"
    "ICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29w"
    "eSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sg"
    "PSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAgICAg"
    "aWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAg"
    "IF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2Fybmlu"
    "ZygKICAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAg"
    "ICAgICAgICBmIkNvdWxkIG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6"
    "XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQg"
    "bWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25m"
    "aWcuanNvbiBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9"
    "IG1vcmdhbm5hX2hvbWUgLyAiY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVu"
    "KCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19j"
    "ZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVj"
    "dG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVt"
    "cG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3"
    "IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJhcF9kaXJl"
    "Y3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAgd3JpdGVfcmVxdWly"
    "ZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRl"
    "ZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3pp"
    "cCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFjZV96"
    "aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAg"
    "ICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBm"
    "YWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikg"
    "YXMgemY6CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAg"
    "ICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "aWYgbWVtYmVyLmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICB3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFz"
    "IGRzdDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQo"
    "KSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAg"
    "ICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFn"
    "ZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6"
    "IHtlfSIpCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAg"
    "ICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJD"
    "b3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAg"
    "IGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAgICAgICAg"
    "ICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRp"
    "bmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRj"
    "dXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAg"
    "ICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBk"
    "ZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAgICAg"
    "c2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAg"
    "ICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAg"
    "ICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAg"
    "ICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAg"
    "ICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAg"
    "ICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAg"
    "ICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAg"
    "ICAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAg"
    "ICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBE"
    "ZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAgICAgIHNo"
    "b3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0"
    "Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1"
    "dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RF"
    "Q0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVs"
    "c2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBm"
    "IlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAg"
    "ICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAg"
    "ICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAg"
    "ICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAg"
    "ICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRf"
    "bm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3Nl"
    "LlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBs"
    "YXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVk"
    "IOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDogTm9y"
    "bWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVu"
    "dCBydW5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vh"
    "cmx5X2xvZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3"
    "aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRl"
    "Y2sgY3JlYXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vh"
    "cmx5X2xvZygiW01BSU5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0"
    "aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBl"
    "dmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBv"
    "ciBlbWl0cyBzaWduYWxzIHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgyMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBm"
    "aXJpbmciKSwgd2luZG93Ll9zZXR1cF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRfc2NoZWR1bGVyIGZpcmlu"
    "ZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAw"
    "LCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIp"
    "LCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAw"
    "LCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmlu"
    "ZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAgIyBQbGF5IHN0YXJ0dXAg"
    "c291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMK"
    "ICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0g"
    "U291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5p"
    "c2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3"
    "aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwg"
    "X3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09"
    "ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5l"
    "IGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKG"
    "kiBQYXNzIDIg4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNg=="
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
